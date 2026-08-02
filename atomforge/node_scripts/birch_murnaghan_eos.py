# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "numpy>=2.4.4",
#   "pydantic==2.12.5",
# ]
# ///

"""Fit a compact third-order Birch–Murnaghan equation of state."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from atomforge.schemas import MetricResult, ScriptOutput

MIN_SCAN_POINTS = 5
MAX_FIT_RMSE_EV_PER_ATOM = 0.05
MIN_BPRIME = 0.0
MAX_BPRIME = 10.0
MIN_RELATIVE_VOLUME_SPAN = 1e-8


class InputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v1"]
    inputs: dict[str, Any]
    arguments: dict[str, Any]


def _trial(inputs: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = inputs.get(node_id)
    if not isinstance(node, dict) or not isinstance(node.get("ensemble"), list):
        raise ValueError(f"missing ensemble for {node_id}")
    if len(node["ensemble"]) != 1 or not isinstance(node["ensemble"][0], dict):
        raise ValueError(f"{node_id} must contain one trial")
    return node["ensemble"][0]


def _scan_points(payload: InputPayload) -> list[tuple[str, float, dict[str, Any]]]:
    sweep_node = payload.arguments.get("sweep_node")
    if isinstance(sweep_node, str):
        sweep = payload.inputs.get(sweep_node)
        if not isinstance(sweep, dict) or sweep.get("contract_version") != "sweep-result.v1":
            raise ValueError(f"missing sweep result for {sweep_node}")
        points = sweep.get("points")
        if not isinstance(points, list):
            raise ValueError(f"{sweep_node} has invalid points")
        parsed: list[tuple[str, float, dict[str, Any]]] = []
        for point in points:
            if not isinstance(point, dict) or point.get("status") != "COMPLETED":
                continue
            ensemble = point.get("ensemble")
            if not isinstance(ensemble, list) or len(ensemble) != 1:
                raise ValueError(f"{point.get('id', 'sweep point')} must contain one trial")
            parsed.append((str(point["id"]), float(point["value"]), ensemble[0]))
        if len(parsed) < MIN_SCAN_POINTS:
            raise ValueError(f"sweep must contain at least {MIN_SCAN_POINTS} completed points")
        return parsed

    raw = payload.arguments.get("scan_nodes")
    if not isinstance(raw, list) or len(raw) < MIN_SCAN_POINTS:
        raise ValueError(f"sweep_node or at least {MIN_SCAN_POINTS} scan_nodes are required")
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("scan_nodes entries must be objects")
        node_id = str(item["node_id"])
        parsed.append((node_id, float(item["linear_scale"]), _trial(payload.inputs, node_id)))
    return parsed


def _fit(volumes: np.ndarray, energies: np.ndarray) -> tuple[float, float, float, float, float]:
    order = np.argsort(volumes)
    volumes, energies = volumes[order], energies[order]
    v_guess = float(volumes[np.argmin(energies)])
    best: tuple[float, float, float, float, float] | None = None
    for v0 in np.linspace(v_guess * 0.90, v_guess * 1.10, 81):
        eta = (v0 / volumes) ** (2.0 / 3.0)
        for bp in np.linspace(2.0, 6.0, 81):
            x = eta - 1.0
            shape = (9.0 * v0 / 16.0) * (x**3 * bp + x**2 * (6.0 - 4.0 * eta))
            design = np.column_stack([np.ones_like(shape), shape])
            coeff, *_ = np.linalg.lstsq(design, energies, rcond=None)
            residual = float(np.mean((design @ coeff - energies) ** 2))
            if best is None or residual < best[0]:
                # coeff[1] = B0 in eV / Å^3
                best = (residual, v0, float(coeff[1]), bp, float(coeff[0]))
    assert best is not None
    residual, v0, b0, bp, e0 = best
    return v0, b0 * 160.21766208, bp, float(np.sqrt(residual)), e0


def build_output(payload: InputPayload) -> ScriptOutput:
    volumes: list[float] = []
    energies: list[float] = []
    rows: list[dict[str, float | str]] = []
    for node_id, scale, trial in _scan_points(payload):
        cell = np.asarray(trial.get("cell"), dtype=float)
        if cell.shape != (3, 3):
            raise ValueError(f"{node_id} has invalid cell")
        if not np.isfinite(cell).all():
            raise ValueError(f"{node_id} has non-finite cell values")
        positions = trial.get("positions")
        atomic_numbers = trial.get("atomic_numbers")
        atom_count = (
            len(positions)
            if isinstance(positions, list) and positions
            else (len(atomic_numbers) if isinstance(atomic_numbers, list) and atomic_numbers else 1)
        )
        determinant = float(np.linalg.det(cell))
        if not np.isfinite(determinant) or abs(determinant) <= 0.0:
            raise ValueError(f"{node_id} has a degenerate cell")
        volume = abs(determinant) / atom_count
        energy = float(trial["potential_energy"])
        if not np.isfinite(energy):
            raise ValueError(f"{node_id} has a non-finite potential energy")
        volumes.append(volume)
        energies.append(energy)
        rows.append(
            {
                "node_id": node_id,
                "linear_scale": scale,
                "volume_A3": volume,
                "energy_eV_per_atom": energy,
            }
        )
    volume_array = np.asarray(volumes, dtype=float)
    energy_array = np.asarray(energies, dtype=float)
    if len(np.unique(volume_array)) < MIN_SCAN_POINTS:
        raise ValueError("EOS scan must contain at least five distinct volumes")
    volume_span = float(np.ptp(volume_array))
    volume_scale = max(float(np.max(np.abs(volume_array))), 1.0)
    if volume_span <= MIN_RELATIVE_VOLUME_SPAN * volume_scale:
        raise ValueError("EOS volume range is degenerate")

    v0, b0, bp, rmse, e0 = _fit(volume_array, energy_array)
    fitted_values = np.asarray([v0, b0, bp, rmse, e0], dtype=float)
    if not np.isfinite(fitted_values).all():
        raise ValueError("EOS fit produced non-finite fitted values")
    inside = bool(min(volumes) < v0 < max(volumes))
    fit_checks = [
        ("Finite fitted values", True, "All fitted values are finite."),
        ("Positive equilibrium volume", v0 > 0.0, "Fitted equilibrium volume must be positive."),
        ("Positive bulk modulus", b0 > 0.0, "Fitted bulk modulus must be positive."),
        (
            "Reasonable derivative",
            MIN_BPRIME < bp <= MAX_BPRIME,
            f"Birch–Murnaghan B′ must be in ({MIN_BPRIME:g}, {MAX_BPRIME:g}].",
        ),
        (
            "Non-degenerate volume range",
            volume_span > MIN_RELATIVE_VOLUME_SPAN * volume_scale,
            "Distinct scan volumes must span a meaningful range.",
        ),
        (
            "Fit residual",
            rmse <= MAX_FIT_RMSE_EV_PER_ATOM,
            f"RMSE must be <= {MAX_FIT_RMSE_EV_PER_ATOM:g} eV/atom.",
        ),
        (
            "Interior minimum",
            inside,
            "Fitted minimum lies inside the scanned volume range.",
        ),
    ]
    fit_usable = all(passed for _, passed, _ in fit_checks[:-1])
    if inside and fit_usable:
        headline = (
            "The fitted EOS has an interior minimum on the declared grid and "
            "passes numerical quality checks."
        )
    elif not inside:
        headline = (
            "The EOS scan does not bracket the fitted equilibrium volume; "
            "the result is inconclusive."
        )
    else:
        headline = (
            "The EOS fit is inconclusive because one or more numerical quality "
            "checks failed."
        )
    source = payload.arguments.get("source", {})
    source_title = (
        str(source.get("title", "declared literature protocol"))
        if isinstance(source, dict)
        else "declared literature protocol"
    )
    observable = (
        str(source.get("observable", "equation-of-state scan"))
        if isinstance(source, dict)
        else "equation-of-state scan"
    )
    scope = f"{len(rows)}-point {observable} MLIP scan"
    return ScriptOutput(
        metrics={
            "eos_equilibrium_volume": MetricResult(val=v0, unit="Å^3/atom"),
            "eos_bulk_modulus": MetricResult(val=b0, unit="GPa"),
            "eos_birch_murnaghan_bprime": MetricResult(val=bp, unit="dimensionless"),
            "eos_fit_rmse": MetricResult(val=rmse, unit="eV/atom"),
            "eos_minimum_inside_scan": MetricResult(val=float(inside), unit="dimensionless"),
            "eos_scan_points": MetricResult(val=float(len(rows)), unit="count"),
        },
        data={
            "rows": rows,
            "fit": {
                "equilibrium_volume_A3_per_atom": v0,
                "bulk_modulus_GPa": b0,
                "bprime": bp,
                "rmse_eV_per_atom": rmse,
                "minimum_inside_scan": inside,
                "energy_minimum_eV_per_atom": e0,
                "quality": {
                    "fit_usable": fit_usable,
                    "max_rmse_eV_per_atom": MAX_FIT_RMSE_EV_PER_ATOM,
                    "volume_span_A3_per_atom": volume_span,
                },
            },
            "source": payload.arguments.get("source", {}),
            "method_alignment": payload.arguments.get("method_alignment", "cross_method"),
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "REVIEW",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 1,
                },
                "scope": scope,
                "headline": headline,
                "supported_claims": [
                    "The selected MLIP produces a numerically fit-able "
                    f"{observable} for this finite cell."
                ],
                "limitations": [
                    "This is cross-method evidence relative to "
                    f"{source_title}; no paper reference curve is evaluated."
                ],
                "quality_checks": [
                    {
                        "label": label,
                        "status": "PASS" if passed else "FAILED",
                        "value": float(passed),
                        "unit": "dimensionless",
                        "criterion": criterion,
                    }
                    for label, passed, criterion in fit_checks
                ],
            },
            "limitations": [
                "This is cross-method evidence relative to "
                f"{source_title}; no paper reference curve is evaluated."
            ],
        },
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: birch_murnaghan_eos.py INPUT_JSON OUTPUT_JSON")
    payload = InputPayload.model_validate_json(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(build_output(payload).model_dump_json(indent=2))
