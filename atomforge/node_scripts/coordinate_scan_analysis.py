# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pydantic==2.12.5",
# ]
# ///

"""Analyze a bounded, symmetric single-coordinate displacement scan.

The analyzer is study-agnostic. It computes inspectable energy/force curve
diagnostics and conservative internal consistency checks from AtomForge
single-point results. Literature provenance, scientific interpretation,
quality-gate rationale, and limitations are supplied by the ExperimentSpec.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atomforge.schemas import (
    ChartVisualization,
    MetricResult,
    ScriptOutput,
    TableColumn,
    TableVisualization,
)


class InputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


class ScanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=100)
    displacement_A: float


class ScanPoint(BaseModel):
    displacement_A: float
    energy_per_atom_eV: float
    total_energy_eV: float
    projected_force_eV_per_A: float
    force_response_norm_eV_per_A: float
    max_force_eV_per_A: float
    atom_count: int


def _single_trial(inputs: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = inputs.get(node_id)
    if not isinstance(node, dict):
        raise ValueError(f"Missing input node {node_id!r}")
    ensemble = node.get("ensemble")
    if not isinstance(ensemble, list) or len(ensemble) != 1:
        raise ValueError(f"Input node {node_id!r} must contain exactly one trial")
    trial = ensemble[0]
    if not isinstance(trial, dict):
        raise ValueError(f"Input node {node_id!r} has an invalid trial result")
    return trial


def _sweep_trials(
    payload: InputPayload,
) -> tuple[list[ScanNode], list[dict[str, Any]], list[float]] | None:
    sweep_node = payload.arguments.get("sweep_node")
    if sweep_node is None:
        return None
    if not isinstance(sweep_node, str) or not sweep_node:
        raise ValueError("arguments.sweep_node must be a node id")
    sweep = payload.inputs.get(sweep_node)
    if not isinstance(sweep, dict) or sweep.get("contract_version") != "sweep-result.v1":
        raise ValueError(f"Missing sweep result {sweep_node!r}")
    points = sweep.get("points")
    if not isinstance(points, list):
        raise ValueError(f"Sweep result {sweep_node!r} has invalid points")
    apply_contract = sweep.get("apply")
    if not isinstance(apply_contract, dict):
        raise ValueError(f"Sweep result {sweep_node!r} has no apply contract")
    if (
        apply_contract.get("target") != "displacement"
        or apply_contract.get("transform") != "scale_vector"
    ):
        raise ValueError("coordinate scan sweep must bind displacement with scale_vector")
    vector = apply_contract.get("vector")
    if not isinstance(vector, list) or not vector:
        raise ValueError("coordinate scan sweep must declare its displacement vector")
    normalized_vector = [float(component) for component in vector]
    vector_norm = _vector_norm(normalized_vector)
    if not math.isclose(vector_norm, 1.0, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("coordinate scan scale_vector must have unit norm")

    nodes: list[ScanNode] = []
    trials: list[dict[str, Any]] = []
    for point in points:
        if not isinstance(point, dict) or point.get("status") != "COMPLETED":
            continue
        ensemble = point.get("ensemble")
        if not isinstance(ensemble, list) or len(ensemble) != 1:
            raise ValueError(f"Sweep point {point.get('id')!r} must contain exactly one trial")
        trial = ensemble[0]
        if not isinstance(trial, dict):
            raise ValueError(f"Sweep point {point.get('id')!r} has an invalid trial result")
        nodes.append(
            ScanNode(
                node_id=str(point.get("id", f"{sweep_node}-point-{len(nodes):04d}")),
                displacement_A=float(point["value"]),
            )
        )
        trials.append(trial)
    if len(nodes) < 5:
        raise ValueError("sweep must contain at least five completed scan points")
    return nodes, trials, normalized_vector


def _vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _flatten_forces(forces: list[list[float]]) -> list[float]:
    if not forces or any(len(vector) != 3 for vector in forces):
        raise ValueError("Each single-point result must contain non-empty 3-vector forces")
    return [float(value) for vector in forces for value in vector]


def _parse_scan(payload: InputPayload) -> tuple[list[ScanPoint], dict[str, Any]]:
    sweep_input = _sweep_trials(payload)
    if sweep_input is None:
        raw_nodes = payload.arguments.get("scan_nodes")
        if not isinstance(raw_nodes, list) or len(raw_nodes) < 5:
            raise ValueError("arguments.sweep_node or at least five scan_nodes are required")
        nodes = [ScanNode.model_validate(item) for item in raw_nodes]
        trials = [_single_trial(payload.inputs, node.node_id) for node in nodes]
    else:
        nodes, trials, sweep_direction = sweep_input
    if len({node.node_id for node in nodes}) != len(nodes):
        raise ValueError("scan node ids must be unique")

    displacements = [node.displacement_A for node in nodes]
    if any(not math.isfinite(value) for value in displacements):
        raise ValueError("scan displacements must be finite")
    if displacements != sorted(displacements):
        raise ValueError("scan_nodes must be ordered by increasing displacement")
    if len({round(value, 12) for value in displacements}) != len(displacements):
        raise ValueError("scan displacements must be unique")

    direction_raw = payload.arguments.get("direction", [1.0, 1.0, 1.0])
    if (
        not isinstance(direction_raw, list)
        or len(direction_raw) != 3
        or any(not isinstance(value, int | float) for value in direction_raw)
    ):
        raise ValueError("arguments.direction must be a numeric 3-vector")
    direction_norm = _vector_norm([float(value) for value in direction_raw])
    if direction_norm <= 0:
        raise ValueError("arguments.direction must have non-zero magnitude")
    direction = [float(value) / direction_norm for value in direction_raw]
    if sweep_input is not None and any(
        not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8)
        for actual, expected in zip(direction, sweep_direction, strict=True)
    ):
        raise ValueError("arguments.direction must match the sweep displacement vector")

    atom_index = payload.arguments.get("atom_index", 0)
    if not isinstance(atom_index, int) or isinstance(atom_index, bool) or atom_index < 0:
        raise ValueError("arguments.atom_index must be a non-negative integer")

    force_vectors: list[list[float]] = []
    for node, trial in zip(nodes, trials, strict=True):
        forces = trial.get("forces")
        positions = trial.get("positions")
        energy = trial.get("potential_energy")
        max_force = trial.get("max_force")
        if (
            not isinstance(forces, list)
            or not isinstance(positions, list)
            or not positions
            or not isinstance(energy, int | float)
            or not isinstance(max_force, int | float)
        ):
            raise ValueError(
                f"Input node {node.node_id!r} must expose forces, positions, "
                "potential_energy, and max_force"
            )
        if len(forces) != len(positions) or atom_index >= len(forces):
            raise ValueError(f"Input node {node.node_id!r} has inconsistent atom arrays")
        force_vectors.append(_flatten_forces(forces))

    zero_indices = [
        index for index, displacement in enumerate(displacements) if abs(displacement) <= 1e-12
    ]
    if len(zero_indices) != 1:
        raise ValueError("scan must contain exactly one zero-displacement reference")
    reference_forces = force_vectors[zero_indices[0]]

    points: list[ScanPoint] = []
    for node, trial, flat_forces in zip(nodes, trials, force_vectors, strict=True):
        forces = trial["forces"]
        atom_count = len(trial["positions"])
        projected_force = sum(
            float(forces[atom_index][axis]) * direction[axis] for axis in range(3)
        )
        response = _vector_norm(
            [
                force - reference
                for force, reference in zip(flat_forces, reference_forces, strict=True)
            ]
        )
        energy_per_atom = float(trial["potential_energy"])
        points.append(
            ScanPoint(
                displacement_A=node.displacement_A,
                energy_per_atom_eV=energy_per_atom,
                total_energy_eV=energy_per_atom * atom_count,
                projected_force_eV_per_A=projected_force,
                force_response_norm_eV_per_A=response,
                max_force_eV_per_A=float(trial["max_force"]),
                atom_count=atom_count,
            )
        )
    if len({point.atom_count for point in points}) != 1:
        raise ValueError("all scan points must contain the same number of atoms")
    return points, {
        "direction": direction,
        "atom_index": atom_index,
        "source": payload.arguments.get("source", {}),
        "method_alignment": str(payload.arguments.get("method_alignment", "cross_method")),
    }


def _diagnostics(points: list[ScanPoint]) -> tuple[dict[str, MetricResult], dict[str, Any]]:
    displacements = [point.displacement_A for point in points]
    spacings = [
        displacements[index + 1] - displacements[index] for index in range(len(displacements) - 1)
    ]
    if any(spacing <= 0 for spacing in spacings):
        raise ValueError("scan displacements must increase strictly")
    minimum_spacing = min(spacings)
    maximum_spacing = max(spacings)
    if maximum_spacing - minimum_spacing > max(1e-9, minimum_spacing * 1e-6):
        raise ValueError("scan grid must be uniformly spaced")

    zero_index = next(
        index for index, point in enumerate(points) if abs(point.displacement_A) <= 1e-12
    )
    equilibrium_energy = points[zero_index].energy_per_atom_eV
    energy_deltas = [point.energy_per_atom_eV - equilibrium_energy for point in points]

    inversion_mismatches: list[float] = []
    by_displacement = {
        round(point.displacement_A, 10): point.energy_per_atom_eV for point in points
    }
    for point in points:
        if point.displacement_A <= 0:
            continue
        opposite = by_displacement.get(round(-point.displacement_A, 10))
        if opposite is None:
            raise ValueError("scan grid must contain paired positive and negative displacements")
        inversion_mismatches.append(abs(point.energy_per_atom_eV - opposite))

    central_residuals: list[float] = []
    force_slopes: list[float] = []
    for index in range(1, len(points) - 1):
        left = points[index - 1]
        center = points[index]
        right = points[index + 1]
        d_energy_dd = (right.total_energy_eV - left.total_energy_eV) / (
            right.displacement_A - left.displacement_A
        )
        central_residuals.append(d_energy_dd + center.projected_force_eV_per_A)
    for left, right in zip(points, points[1:]):
        force_slopes.append(
            (right.projected_force_eV_per_A - left.projected_force_eV_per_A)
            / (right.displacement_A - left.displacement_A)
        )
    adjacent_slope_changes = [
        abs(right - left) for left, right in zip(force_slopes, force_slopes[1:])
    ]

    energy_tolerance = 1e-6
    artificial_minima_indices = [
        index
        for index in range(1, len(points) - 1)
        if index != zero_index
        and points[index].energy_per_atom_eV
        < min(
            points[index - 1].energy_per_atom_eV,
            points[index + 1].energy_per_atom_eV,
        )
        - energy_tolerance
    ]

    left_outward = list(reversed(points[: zero_index + 1]))
    right_outward = points[zero_index:]
    monotonicity_violations = 0
    for branch in (left_outward, right_outward):
        monotonicity_violations += sum(
            right.energy_per_atom_eV < left.energy_per_atom_eV - energy_tolerance
            for left, right in zip(branch, branch[1:])
        )

    rmse = math.sqrt(sum(value * value for value in central_residuals) / len(central_residuals))
    metrics = {
        "scan_points": MetricResult(val=float(len(points)), unit="count"),
        "max_displacement": MetricResult(val=max(abs(value) for value in displacements), unit="Å"),
        "max_energy_excursion": MetricResult(
            val=max(energy_deltas) - min(energy_deltas), unit="eV/atom"
        ),
        "max_force_response": MetricResult(
            val=max(point.force_response_norm_eV_per_A for point in points),
            unit="eV/Å",
        ),
        "max_inversion_energy_mismatch": MetricResult(
            val=max(inversion_mismatches, default=0.0), unit="eV/atom"
        ),
        "energy_force_consistency_rmse": MetricResult(val=rmse, unit="eV/Å"),
        "max_adjacent_force_slope_change": MetricResult(
            val=max(adjacent_slope_changes, default=0.0), unit="eV/Å²"
        ),
        "artificial_minima_count": MetricResult(
            val=float(len(artificial_minima_indices)), unit="count"
        ),
        "monotonicity_violation_count": MetricResult(
            val=float(monotonicity_violations), unit="count"
        ),
    }
    details = {
        "grid_spacing_A": minimum_spacing,
        "equilibrium_index": zero_index,
        "equilibrium_energy_per_atom_eV": equilibrium_energy,
        "energy_deltas_eV_per_atom": energy_deltas,
        "energy_force_residuals_eV_per_A": central_residuals,
        "force_slopes_eV_per_A2": force_slopes,
        "artificial_minima_indices": artificial_minima_indices,
    }
    return metrics, details


def build_output(payload: InputPayload) -> ScriptOutput:
    points, context = _parse_scan(payload)
    metrics, details = _diagnostics(points)
    equilibrium_energy = details["equilibrium_energy_per_atom_eV"]
    artificial_minima = set(details["artificial_minima_indices"])
    coordinate_label = str(payload.arguments.get("coordinate_label", "displacement coordinate"))
    decision_context = payload.arguments.get("decision_context")
    if not isinstance(decision_context, dict):
        raise ValueError("arguments.decision_context must be an object")
    required_decision_context = {
        "supported_claims",
        "limitations",
        "decision_rule",
    }
    missing_decision_context = required_decision_context - set(decision_context)
    if missing_decision_context:
        raise ValueError(
            f"arguments.decision_context is missing fields: {sorted(missing_decision_context)}"
        )
    for field in ("supported_claims", "limitations"):
        items = decision_context[field]
        if (
            not isinstance(items, list)
            or not items
            or any(not isinstance(item, str) or not item.strip() for item in items)
        ):
            raise ValueError(
                f"arguments.decision_context.{field} must be a non-empty list of strings"
            )
    quality_contract = payload.arguments.get("quality_contract")
    if not isinstance(quality_contract, dict):
        raise ValueError("arguments.quality_contract must be an object")
    limitations = payload.arguments.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise ValueError("arguments.limitations must be a non-empty list of strings")
    report_sections = payload.arguments.get("report_sections")
    if not isinstance(report_sections, list):
        raise ValueError("arguments.report_sections must be a list")
    rows = [
        {
            "displacement_A": round(point.displacement_A, 6),
            "energy_delta_meV_per_atom": round(
                1000.0 * (point.energy_per_atom_eV - equilibrium_energy), 6
            ),
            "projected_force_eV_per_A": round(point.projected_force_eV_per_A, 6),
            "force_response_norm_eV_per_A": round(point.force_response_norm_eV_per_A, 6),
            "max_force_eV_per_A": round(point.max_force_eV_per_A, 6),
            "local_minimum": "YES" if index in artificial_minima else "NO",
        }
        for index, point in enumerate(points)
    ]
    source = context["source"]
    has_escalation_feature = (
        metrics["artificial_minima_count"].val > 0
        or metrics["monotonicity_violation_count"].val > 0
    )
    result_claim = (
        "This bounded coordinate scan detected an artificial minimum or "
        "non-monotonic branch that requires escalation."
        if has_escalation_feature
        else "This bounded coordinate scan found no artificial minimum or "
        "non-monotonic branch on the declared grid."
    )
    scientific_decision = {
        "contract_version": "scientific-decision.v1",
        "outcome": "REVIEW",
        "calibration": {
            "status": "INSUFFICIENT_EVIDENCE",
            "accepted_case_count": 0,
            "minimum_case_count": 30,
        },
        "scope": (
            f"{coordinate_label} for one declared structure, atom, direction, "
            f"and model under {context['method_alignment']} method alignment."
        ),
        "headline": (
            "Coordinate scan detected a feature requiring escalation."
            if has_escalation_feature
            else "Bounded coordinate scan found no obvious pathology."
        ),
        "quality_checks": [
            {
                "label": "Coordinate-scan escalation gate",
                "status": "REVIEW" if has_escalation_feature else "PASS",
                "value": 1 if has_escalation_feature else 0,
                "unit": "detected features",
                "criterion": (
                    "no artificial minima or non-monotonic branches on the declared grid"
                ),
            }
        ],
        "supported_claims": [
            result_claim,
            *decision_context["supported_claims"],
        ],
        "limitations": [*decision_context["limitations"], *limitations],
    }
    visualizations = [
        ChartVisualization(
            id="coordinate-scan-energy-curve",
            title=f"{coordinate_label}: energy curve",
            description=(
                "Energy relative to the declared reference over the bounded coordinate scan."
            ),
            mark="line",
            rows=rows,
            x={
                "field": "displacement_A",
                "type": "quantitative",
                "label": coordinate_label,
                "unit": "Å",
            },
            y={
                "field": "energy_delta_meV_per_atom",
                "type": "quantitative",
                "label": "Energy relative to reference",
                "unit": "meV/atom",
            },
        ),
        ChartVisualization(
            id="coordinate-scan-force-curve",
            title=f"{coordinate_label}: projected-force curve",
            description=(
                "Force on the displaced atom projected along the configured scan direction."
            ),
            mark="line",
            rows=rows,
            x={
                "field": "displacement_A",
                "type": "quantitative",
                "label": coordinate_label,
                "unit": "Å",
            },
            y={
                "field": "projected_force_eV_per_A",
                "type": "quantitative",
                "label": "Projected force",
                "unit": "eV/Å",
            },
        ),
        TableVisualization(
            id="coordinate-scan-values",
            title=f"{coordinate_label}: persisted scan values",
            description="Persisted values used for every derived diagnostic.",
            columns=[
                TableColumn(field="displacement_A", label="Displacement", unit="Å"),
                TableColumn(
                    field="energy_delta_meV_per_atom",
                    label="Relative energy",
                    unit="meV/atom",
                ),
                TableColumn(
                    field="projected_force_eV_per_A",
                    label="Projected force",
                    unit="eV/Å",
                ),
                TableColumn(
                    field="force_response_norm_eV_per_A",
                    label="Force response norm",
                    unit="eV/Å",
                ),
                TableColumn(
                    field="max_force_eV_per_A",
                    label="Maximum atomic force",
                    unit="eV/Å",
                ),
                TableColumn(field="local_minimum", label="Artificial local minimum"),
            ],
            rows=rows,
        ),
    ]
    return ScriptOutput(
        metrics=metrics,
        data={
            "scan_rows": rows,
            "diagnostics": details,
            "direction": context["direction"],
            "atom_index": context["atom_index"],
            "source": source,
            "scientific_decision": scientific_decision,
            "acceptance": quality_contract,
            "limitations": limitations,
            "report_sections": report_sections,
        },
        visualizations=visualizations,
    )


def main(input_path: Path, output_path: Path) -> None:
    payload = InputPayload.model_validate_json(input_path.read_text(encoding="utf-8"))
    output_path.write_text(build_output(payload).model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: coordinate_scan_analysis.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
