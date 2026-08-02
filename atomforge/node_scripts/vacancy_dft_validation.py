# /// script
# requires-python = ">=3.12"
# ///

"""Validate a promoted vacancy candidate against held-out DFT evidence.

This node deliberately does not run DFT. It validates an immutable result from a
separate DFT backend and refuses to label the candidate validated unless the
calculation, geometry lineage, reference convention, and artifact provenance all
pass explicit gates.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_TEXT_FIELDS = (
    "code",
    "code_version",
    "exchange_correlation_functional",
    "pseudopotential_set",
    "spin_treatment",
    "reference_convention",
)


def _node_data(inputs: dict[str, Any], node_id: str) -> dict[str, Any]:
    upstream = inputs.get(node_id)
    if not isinstance(upstream, dict) or not isinstance(upstream.get("data"), dict):
        raise ValueError(f"source node {node_id!r} is missing SCRIPT data")
    return upstream["data"]


def _promoted_candidate(inputs: dict[str, Any], node_id: str) -> dict[str, Any]:
    decision = _node_data(inputs, node_id).get("decision")
    if not isinstance(decision, dict):
        raise ValueError(f"selection node {node_id!r} is missing decision data")
    promoted = decision.get("promoted_candidate")
    if not isinstance(promoted, dict):
        raise ValueError("held-out DFT validation requires a promoted candidate")
    return promoted


def _dft_result(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    node_id = arguments.get("dft_result_node")
    if node_id is not None:
        result = _node_data(inputs, str(node_id)).get("dft_result")
    else:
        result = arguments.get("dft_result")
    if not isinstance(result, dict):
        raise ValueError(
            "DFT evidence must be supplied as arguments.dft_result or "
            "data.dft_result from arguments.dft_result_node"
        )
    return result


def _finite_number(value: Any, field: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def validate_dft_evidence(
    promoted: dict[str, Any],
    dft: dict[str, Any],
    *,
    force_tolerance_eV_per_A: float,
    energy_tolerance_eV: float,
) -> dict[str, Any]:
    """Return fail-closed gates and model residuals for one held-out DFT result."""

    force_tolerance = _finite_number(force_tolerance_eV_per_A, "force_tolerance_eV_per_A")
    energy_tolerance = _finite_number(energy_tolerance_eV, "energy_tolerance_eV")
    if force_tolerance <= 0 or energy_tolerance <= 0:
        raise ValueError("DFT convergence tolerances must be positive")

    reasons: list[str] = []
    promoted_case_id = str(promoted.get("case_id") or "").strip()
    result_case_id = str(dft.get("case_id") or "").strip()
    if not promoted_case_id or result_case_id != promoted_case_id:
        reasons.append("DFT case_id does not match the promoted candidate")

    promoted_geometry = str(promoted.get("geometry_fingerprint") or "").strip()
    result_geometry = str(dft.get("initial_geometry_fingerprint") or "").strip()
    if not promoted_geometry or result_geometry != promoted_geometry:
        reasons.append("DFT initial geometry does not match the promoted frozen geometry")

    for field in _REQUIRED_TEXT_FIELDS:
        if not isinstance(dft.get(field), str) or not dft[field].strip():
            reasons.append(f"DFT evidence is missing {field}")

    if dft.get("reference_convention") != "self-consistent elemental bulk":
        reasons.append("DFT vacancy energy must use the self-consistent elemental bulk reference")

    if dft.get("independent_of_selection_models") is not True:
        reasons.append("DFT evidence must be independent of the selection models")
    if dft.get("electronic_converged") is not True:
        reasons.append("electronic convergence gate failed")
    if dft.get("ionic_converged") is not True:
        reasons.append("ionic convergence gate failed")

    dft_energy = _finite_number(
        dft.get("dft_vacancy_formation_energy_eV"),
        "dft_vacancy_formation_energy_eV",
    )
    max_force = _finite_number(dft.get("max_force_eV_per_A"), "max_force_eV_per_A")
    energy_change = abs(_finite_number(dft.get("final_energy_change_eV"), "final_energy_change_eV"))
    cutoff = _finite_number(dft.get("plane_wave_cutoff_eV"), "plane_wave_cutoff_eV")
    kpoint_density = _finite_number(dft.get("kpoint_density_per_A"), "kpoint_density_per_A")
    if max_force > force_tolerance:
        reasons.append(f"maximum force {max_force:g} eV/Å exceeds {force_tolerance:g} eV/Å")
    if energy_change > energy_tolerance:
        reasons.append(f"final energy change {energy_change:g} eV exceeds {energy_tolerance:g} eV")
    if cutoff <= 0 or kpoint_density <= 0:
        reasons.append("DFT cutoff and k-point density must be positive")

    artifact_sha = str(dft.get("source_artifact_sha256") or "").lower()
    if not _SHA256.fullmatch(artifact_sha):
        reasons.append("source_artifact_sha256 must be an exact lowercase SHA-256")

    mace_energy = _finite_number(
        promoted.get("mace_self_consistent_vacancy_eV"),
        "promoted.mace_self_consistent_vacancy_eV",
    )
    mattersim_energy = _finite_number(
        promoted.get("mattersim_self_consistent_vacancy_eV"),
        "promoted.mattersim_self_consistent_vacancy_eV",
    )
    mace_error = abs(mace_energy - dft_energy)
    mattersim_error = abs(mattersim_energy - dft_energy)
    closer_model = "MACE-MP-0" if mace_error < mattersim_error else "MatterSim"
    if math.isclose(mace_error, mattersim_error, rel_tol=0.0, abs_tol=1e-12):
        closer_model = "TIE"

    return {
        "passed": not reasons,
        "reasons": reasons,
        "case_id": promoted_case_id,
        "element": str(promoted.get("element") or ""),
        "mp_id": str(promoted.get("mp_id") or ""),
        "dft_vacancy_formation_energy_eV": dft_energy,
        "mace_absolute_error_to_dft_eV": mace_error,
        "mattersim_absolute_error_to_dft_eV": mattersim_error,
        "closer_model": closer_model,
        "calculation": {
            field: dft.get(field)
            for field in (
                "code",
                "code_version",
                "exchange_correlation_functional",
                "pseudopotential_set",
                "spin_treatment",
                "reference_convention",
                "plane_wave_cutoff_eV",
                "kpoint_density_per_A",
                "source_artifact_sha256",
            )
        },
    }


def build_output(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    selection_node = str(arguments.get("selection_node", "select_dft_case"))
    promoted = _promoted_candidate(inputs, selection_node)
    dft = _dft_result(inputs, arguments)
    force_tolerance = float(arguments.get("force_tolerance_eV_per_A", 0.03))
    energy_tolerance = float(arguments.get("energy_tolerance_eV", 1e-5))
    minimum_calibration_cases = int(arguments.get("minimum_calibration_cases", 30))
    if minimum_calibration_cases < 10:
        raise ValueError("minimum_calibration_cases must be at least 10")

    validation = validate_dft_evidence(
        promoted,
        dft,
        force_tolerance_eV_per_A=force_tolerance,
        energy_tolerance_eV=energy_tolerance,
    )
    passed = bool(validation["passed"])
    status = "DFT_VALIDATED" if passed else "REVIEW"
    headline = (
        f"Held-out DFT validation passed for {validation['element']} ({validation['mp_id']})."
        if passed
        else "Held-out DFT evidence failed one or more validation gates."
    )

    supported_claims = []
    if passed:
        supported_claims = [
            "The promoted frozen geometry was evaluated by an independent DFT calculation.",
            (
                f"MACE-MP-0 absolute error was "
                f"{validation['mace_absolute_error_to_dft_eV']:.3f} eV and MatterSim "
                f"absolute error was {validation['mattersim_absolute_error_to_dft_eV']:.3f} eV."
            ),
        ]
    calculation = validation["calculation"]
    accepted_case_count = 1 if passed else 0
    scientific_decision = {
        "contract_version": "scientific-decision.v1",
        "outcome": "VALIDATED" if passed else "REVIEW",
        "calibration": {
            "status": "INSUFFICIENT_EVIDENCE",
            "accepted_case_count": accepted_case_count,
            "minimum_case_count": minimum_calibration_cases,
        },
        "scope": (
            f"{validation['element']} ({validation['mp_id']}) elemental-bcc monovacancy "
            f"under {calculation['code']} {calculation['code_version']} "
            f"{calculation['exchange_correlation_functional']}/"
            f"{calculation['plane_wave_cutoff_eV']:g} eV with the declared "
            "k-point, spin, and self-consistent elemental-bulk reference protocol."
        ),
        "headline": headline,
        "supported_claims": supported_claims,
        "limitations": [
            "One DFT result cannot calibrate model uncertainty.",
            "Validation applies only to the selected case and declared DFT protocol.",
            "Broader claims require a stratified, held-out calibration programme.",
        ],
        "quality_checks": [
            {
                "label": "Held-out evidence gates",
                "status": "PASS" if passed else "FAILED",
                "value": "all passed" if passed else f"{len(validation['reasons'])} failed",
                "unit": "gate status",
                "criterion": (
                    "Exact lineage, convergence, protocol, independence, and artifact identity"
                ),
            },
            {
                "label": "Electronic convergence",
                "status": "PASS"
                if bool(dft.get("electronic_converged"))
                and abs(float(dft["final_energy_change_eV"])) <= energy_tolerance
                else "FAILED",
                "value": abs(float(dft["final_energy_change_eV"])),
                "unit": "eV",
                "criterion": f"final energy change <= {energy_tolerance:g} eV",
            },
            {
                "label": "Ionic convergence",
                "status": "PASS"
                if bool(dft.get("ionic_converged"))
                and float(dft["max_force_eV_per_A"]) <= force_tolerance
                else "FAILED",
                "value": float(dft["max_force_eV_per_A"]),
                "unit": "eV/Å",
                "criterion": f"maximum force <= {force_tolerance:g} eV/Å",
            },
            {
                "label": "Immutable artifact identity",
                "status": "PASS"
                if _SHA256.fullmatch(str(calculation.get("source_artifact_sha256") or "").lower())
                else "FAILED",
                "value": str(calculation.get("source_artifact_sha256") or ""),
                "unit": "SHA-256",
                "criterion": "exact lowercase SHA-256 of the calculation artifact set",
            },
            {
                "label": "Uncertainty calibration",
                "status": "REVIEW",
                "value": f"{accepted_case_count}/{minimum_calibration_cases}",
                "unit": "accepted cases",
                "criterion": (f"at least {minimum_calibration_cases} preregistered accepted cases"),
            },
        ],
    }

    return {
        "contract_version": "v1",
        "metrics": {
            "dft_validation_gate_passed": {
                "val": 1.0 if passed else 0.0,
                "unit": "dimensionless",
            },
            "mace_absolute_error_to_dft": {
                "val": validation["mace_absolute_error_to_dft_eV"],
                "unit": "eV",
            },
            "mattersim_absolute_error_to_dft": {
                "val": validation["mattersim_absolute_error_to_dft_eV"],
                "unit": "eV",
            },
            "calibration_case_count_increment": {
                "val": 1.0 if passed else 0.0,
                "unit": "count",
            },
        },
        "data": {
            "scientific_decision": scientific_decision,
            "validation": {
                "status": status,
                "headline": headline,
                "case_id": validation["case_id"],
                "closer_model": validation["closer_model"],
                "gate_failures": validation["reasons"],
                "supported_claims": supported_claims,
                "calculation": validation["calculation"],
            },
            "calibration_update": {
                "status": "INSUFFICIENT_EVIDENCE",
                "accepted_case_count_increment": accepted_case_count,
                "minimum_calibration_cases": minimum_calibration_cases,
                "observation": {
                    "case_id": validation["case_id"],
                    "material_class": "elemental-bcc-vacancy",
                    "cross_model_disagreement_eV": float(promoted["cross_model_disagreement_eV"]),
                    "mace_absolute_error_to_dft_eV": validation["mace_absolute_error_to_dft_eV"],
                    "mattersim_absolute_error_to_dft_eV": validation[
                        "mattersim_absolute_error_to_dft_eV"
                    ],
                }
                if passed
                else None,
                "claim_boundary": (
                    "One held-out DFT result tests this decision; it does not calibrate "
                    "uncertainty or establish generalisation."
                ),
            },
        },
        "visualizations": [
            {
                "id": "held-out-dft-model-errors",
                "kind": "chart.v1",
                "title": "Held-out DFT error by selection model",
                "description": (
                    "Single-case residuals; this chart is validation evidence, not a "
                    "calibrated uncertainty curve."
                ),
                "mark": "bar",
                "rows": [
                    {
                        "model": "MACE-MP-0",
                        "absolute_error_eV": validation["mace_absolute_error_to_dft_eV"],
                    },
                    {
                        "model": "MatterSim",
                        "absolute_error_eV": validation["mattersim_absolute_error_to_dft_eV"],
                    },
                ],
                "x": {"field": "model", "label": "Model", "type": "nominal"},
                "y": {
                    "field": "absolute_error_eV",
                    "label": "Absolute error to DFT",
                    "type": "quantitative",
                    "unit": "eV",
                },
            }
        ],
    }


def main(input_path: Path, output_path: Path) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output = build_output(payload["inputs"], payload.get("arguments", {}))
    output_path.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: vacancy_dft_validation.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
