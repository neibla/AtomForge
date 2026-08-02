# /// script
# requires-python = ">=3.12"
# ///

"""Join reproduction and extension evidence and select a bounded DFT follow-up."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def _rows(inputs: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    upstream = inputs.get(node_id)
    if not isinstance(upstream, dict) or not isinstance(upstream.get("data"), dict):
        raise ValueError(f"source node {node_id!r} is missing SCRIPT data")
    rows = upstream["data"].get("comparison_rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"source node {node_id!r} must include comparison_rows")
    return rows


def _prepared_case(inputs: dict[str, Any], node_id: str, case_id: str) -> dict[str, Any]:
    """Return the frozen geometry for the candidate selected by the decision rule."""
    upstream = inputs.get(node_id)
    if not isinstance(upstream, dict) or not isinstance(upstream.get("data"), dict):
        raise ValueError(f"geometry source node {node_id!r} is missing SCRIPT data")
    cases = upstream["data"].get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"geometry source node {node_id!r} must include cases")
    matches = [case for case in cases if isinstance(case, dict) and case.get("case_id") == case_id]
    if len(matches) != 1:
        raise ValueError(
            f"geometry source node {node_id!r} must contain exactly one case {case_id!r}"
        )
    return matches[0]


def _promoted_structure_visualization(
    inputs: dict[str, Any],
    *,
    geometry_node: str,
    promoted: dict[str, Any],
    promotion_threshold_eV: float,
) -> dict[str, Any]:
    """Make the decision-selected, frozen monovacancy geometry inspectable.

    This deliberately renders only the structure selected by the predeclared
    ranking rule.  It is not a representative or a visually-picked lattice.
    """
    case = _prepared_case(inputs, geometry_node, str(promoted["case_id"]))
    pristine = case.get("pristine_structure")
    defect = case.get("defect_structure")
    if not isinstance(pristine, dict) or not isinstance(defect, dict):
        raise ValueError("prepared case must include pristine_structure and defect_structure")

    pristine_positions = pristine.get("positions")
    defect_positions = defect.get("positions")
    defect_numbers = defect.get("numbers")
    if (
        not isinstance(pristine_positions, list)
        or not pristine_positions
        or not isinstance(defect_positions, list)
        or not isinstance(defect_numbers, list)
        or len(defect_positions) != len(defect_numbers)
    ):
        raise ValueError("prepared case has invalid atomistic geometry payloads")
    if len(pristine_positions) != len(defect_positions) + 1:
        raise ValueError("selected geometry must be a single-vacancy structure")

    element = str(promoted["element"])
    mp_id = str(promoted["mp_id"])
    disagreement = float(promoted["cross_model_disagreement_eV"])
    return {
        "id": f"promoted-{str(promoted['case_id'])}-monovacancy",
        "kind": "atomistic.v1",
        "title": f"{element} bcc monovacancy selected for held-out DFT",
        "description": (
            f"Frozen {len(defect_positions)}-atom {element} bcc vacancy supercell "
            f"({mp_id}). It is shown because the predeclared ranking selected it: "
            f"MACE–MatterSim disagreement {disagreement:.3f} eV exceeds the "
            f"{promotion_threshold_eV:g} eV DFT-promotion threshold. The orange "
            "marker in Defects mode is the removed atom site; this is not a "
            "relaxed DFT structure."
        ),
        "source_node": "select_dft_case",
        "data": {
            "numbers": defect_numbers,
            "symbols": defect.get("symbols"),
            "positions": defect_positions,
            "cell": defect.get("cell"),
            "pbc": defect.get("pbc"),
            "vacancy_positions": [pristine_positions[0]],
            "n_defects": 1,
            "metadata": {
                "structure": "bcc monovacancy supercell",
                "element": element,
                "materials_project_id": mp_id,
                "selection_rule": "largest eligible MACE–MatterSim disagreement",
                "cross_model_disagreement_eV": disagreement,
                "promotion_threshold_eV": promotion_threshold_eV,
                "pristine_atom_count": len(pristine_positions),
                "defect_atom_count": len(defect_positions),
                "geometry_fingerprint": case.get("geometry_fingerprint"),
                "geometry_state": "frozen, unrelaxed vacancy geometry",
                "scientific_role": "held-out DFT target, not DFT evidence",
            },
        },
    }


def _index(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"{label} rows require case_id")
        if case_id in indexed:
            raise ValueError(f"duplicate {label} case_id: {case_id}")
        indexed[case_id] = row
    return indexed


def rank_disagreements(
    mace_rows: list[dict[str, Any]],
    mattersim_rows: list[dict[str, Any]],
    *,
    promotion_threshold_eV: float,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not math.isfinite(promotion_threshold_eV) or promotion_threshold_eV < 0:
        raise ValueError("promotion_threshold_eV must be finite and non-negative")
    mace = _index(mace_rows, "MACE")
    mattersim = _index(mattersim_rows, "MatterSim")
    if set(mace) != set(mattersim):
        raise ValueError(
            f"model case sets differ: MACE={sorted(mace)}, MatterSim={sorted(mattersim)}"
        )

    ranked: list[dict[str, Any]] = []
    for case_id in sorted(mace):
        paper_row = mace[case_id]
        extension_row = mattersim[case_id]
        reasons: list[str] = []
        if paper_row.get("reproduction_status") != "PASS":
            reasons.append("paper reproduction did not pass")
        if not bool(paper_row.get("finite")) or not bool(extension_row.get("finite")):
            reasons.append("one or both model evaluations are non-finite")
        if paper_row.get("geometry_fingerprint") != extension_row.get("geometry_fingerprint"):
            reasons.append("model workers did not evaluate identical geometries")

        mace_energy = float(paper_row["mace_self_consistent_vacancy_eV"])
        mattersim_energy = float(extension_row["mattersim_self_consistent_vacancy_eV"])
        disagreement = abs(mace_energy - mattersim_energy)
        reproduction_error = float(paper_row["absolute_reproduction_error_eV"])
        if not all(
            math.isfinite(value)
            for value in (
                mace_energy,
                mattersim_energy,
                disagreement,
                reproduction_error,
            )
        ):
            reasons.append("derived comparison values are non-finite")

        ranked.append(
            {
                "rank": None,
                "case_id": case_id,
                "element": str(paper_row["element"]),
                "mp_id": str(paper_row["mp_id"]),
                "eligible": not reasons,
                "mace_self_consistent_vacancy_eV": mace_energy,
                "mattersim_self_consistent_vacancy_eV": mattersim_energy,
                "cross_model_disagreement_eV": disagreement,
                "reproduction_error_eV": reproduction_error,
                "decision": "ELIGIBLE" if not reasons else "HOLD",
                "reason": (
                    "; ".join(reasons) or "reproduction, numerical and geometry gates passed"
                ),
            }
        )

    ranked.sort(
        key=lambda row: (
            not row["eligible"],
            -row["cross_model_disagreement_eV"],
            row["case_id"],
        )
    )
    eligible = [row for row in ranked if row["eligible"]]
    for position, row in enumerate(eligible, start=1):
        row["rank"] = position
    promoted = (
        eligible[0]
        if eligible and eligible[0]["cross_model_disagreement_eV"] >= promotion_threshold_eV
        else None
    )
    if promoted is not None:
        promoted["decision"] = "PROMOTE_TO_DFT"
        promoted["reason"] = f"largest eligible disagreement exceeds {promotion_threshold_eV:g} eV"
    return ranked, promoted


def build_output(inputs: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    mace_node = str(arguments.get("mace_node", "reproduce_mace"))
    mattersim_node = str(arguments.get("mattersim_node", "evaluate_mattersim"))
    expected_count = int(arguments.get("expected_case_count", 5))
    threshold = float(arguments.get("promotion_threshold_eV", 0.25))
    mace_rows = _rows(inputs, mace_node)
    mattersim_rows = _rows(inputs, mattersim_node)
    ranked, promoted = rank_disagreements(
        mace_rows,
        mattersim_rows,
        promotion_threshold_eV=threshold,
    )
    eligible = [row for row in ranked if row["eligible"]]
    reproduction_pass_count = sum(
        1 for row in mace_rows if row.get("reproduction_status") == "PASS"
    )
    complete = len(ranked) == expected_count
    decision_gate_passed = (
        complete and reproduction_pass_count == expected_count and len(eligible) == expected_count
    )
    max_reproduction_error = max(float(row["reproduction_error_eV"]) for row in ranked)
    max_disagreement = max(float(row["cross_model_disagreement_eV"]) for row in ranked)

    if promoted is not None and decision_gate_passed:
        headline = (
            f"Promote {promoted['element']} ({promoted['mp_id']}) to held-out DFT validation."
        )
        next_calculation = (
            "Run a converged spin-consistent DFT monovacancy calculation for the promoted case."
        )
    elif decision_gate_passed:
        headline = (
            "No DFT escalation: the complete eligible panel stayed below the declared "
            f"{threshold:g} eV disagreement threshold."
        )
        next_calculation = "Do not spend DFT budget on this panel under the declared rule."
    else:
        headline = "No decision: one or more reproduction, numerical or geometry gates failed."
        next_calculation = "Resolve the failed evidence gates before allocating DFT budget."
        promoted = None

    selected_structure = None
    geometry_node = arguments.get("geometry_node")
    if promoted is not None and geometry_node is not None:
        promoted_case = _prepared_case(
            inputs,
            str(geometry_node),
            str(promoted["case_id"]),
        )
        geometry_fingerprint = promoted_case.get("geometry_fingerprint")
        if not isinstance(geometry_fingerprint, str) or not geometry_fingerprint:
            raise ValueError("promoted geometry is missing its immutable fingerprint")
        promoted = {**promoted, "geometry_fingerprint": geometry_fingerprint}
        selected_structure = _promoted_structure_visualization(
            inputs,
            geometry_node=str(geometry_node),
            promoted=promoted,
            promotion_threshold_eV=threshold,
        )

    supported_claims = [
        (
            f"{reproduction_pass_count} of {expected_count} frozen paper records passed "
            "reproduction tolerance."
        ),
        headline,
    ]
    if len(eligible) == expected_count:
        supported_claims.insert(
            1, "Both models evaluated identical finite unrelaxed vacancy geometries."
        )

    return {
        "contract_version": "v1",
        "metrics": {
            "candidate_count": {"val": float(len(ranked)), "unit": "count"},
            "reproduction_pass_count": {
                "val": float(reproduction_pass_count),
                "unit": "count",
            },
            "eligible_candidate_count": {
                "val": float(len(eligible)),
                "unit": "count",
            },
            "max_reproduction_error": {
                "val": max_reproduction_error,
                "unit": "eV",
            },
            "max_cross_model_disagreement": {
                "val": max_disagreement,
                "unit": "eV",
            },
            "promotion_made": {
                "val": 1.0 if promoted else 0.0,
                "unit": "dimensionless",
            },
            "decision_gate_passed": {
                "val": 1.0 if decision_gate_passed else 0.0,
                "unit": "dimensionless",
            },
        },
        "data": {
            "decision": {
                "headline": headline,
                "promoted_candidate": promoted,
                "promotion_threshold_eV": threshold,
                "next_calculation": next_calculation,
                "selected_structure_visualization_id": (
                    selected_structure["id"] if selected_structure else None
                ),
            },
            "candidate_ranking": ranked,
            "acceptance_contract": {
                "expected_case_count": expected_count,
                "paper_reproduction_required": True,
                "identical_geometry_fingerprint_required": True,
                "finite_model_outputs_required": True,
                "promotion_threshold_eV": threshold,
                "valid_no_promotion": True,
            },
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "REVIEW" if decision_gate_passed else "BLOCKED",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 0,
                    "minimum_case_count": 30,
                },
                "scope": (
                    "DFT-priority decision over the five-record elemental-bcc vacancy "
                    "panel using exact-geometry MACE/MatterSim disagreement."
                ),
                "headline": headline,
                "quality_checks": [
                    {
                        "label": "Selection decision contract",
                        "status": "PASS" if decision_gate_passed else "FAILED",
                        "value": 1 if decision_gate_passed else 0,
                        "unit": "gate",
                        "criterion": (
                            "exact geometry lineage, finite outputs, and a valid "
                            "promotion or no-promotion decision"
                        ),
                    }
                ],
                "supported_claims": supported_claims,
                "limitations": [
                    (
                        "Cross-model disagreement is a prioritisation heuristic, not "
                        "calibrated uncertainty."
                    ),
                    ("The five-record elemental panel is not a materials-discovery campaign."),
                    "A promoted result still requires a converged DFT calculation.",
                    (
                        "A no-promotion result is scientifically valid and should not be "
                        "overridden for presentation."
                    ),
                ],
            },
        },
        "visualizations": [
            {
                "id": "vacancy-disagreement-decision",
                "kind": "table.v1",
                "title": "Paper reproduction and cross-model DFT priority",
                "columns": [
                    {"field": "rank", "label": "Rank"},
                    {"field": "element", "label": "Element"},
                    {"field": "mp_id", "label": "Materials Project ID"},
                    {
                        "field": "reproduction_error_eV",
                        "label": "Reproduction error",
                        "unit": "eV",
                    },
                    {
                        "field": "mace_self_consistent_vacancy_eV",
                        "label": "MACE vacancy",
                        "unit": "eV",
                    },
                    {
                        "field": "mattersim_self_consistent_vacancy_eV",
                        "label": "MatterSim vacancy",
                        "unit": "eV",
                    },
                    {
                        "field": "cross_model_disagreement_eV",
                        "label": "Disagreement",
                        "unit": "eV",
                    },
                    {"field": "decision", "label": "Decision"},
                    {"field": "reason", "label": "Reason"},
                ],
                "rows": ranked,
            },
            {
                "id": "vacancy-disagreement-chart",
                "kind": "chart.v1",
                "title": "Cross-model vacancy-energy disagreement",
                "description": "Used only to prioritise held-out DFT evidence.",
                "mark": "bar",
                "rows": [
                    {
                        "candidate": f"{row['element']} ({row['mp_id']})",
                        "disagreement_eV": row["cross_model_disagreement_eV"],
                    }
                    for row in ranked
                ],
                "x": {
                    "field": "candidate",
                    "label": "Candidate",
                    "type": "nominal",
                },
                "y": {
                    "field": "disagreement_eV",
                    "label": "Absolute disagreement",
                    "type": "quantitative",
                    "unit": "eV",
                },
            },
        ]
        + ([selected_structure] if selected_structure else []),
    }


def main(input_path: Path, output_path: Path) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output = build_output(payload["inputs"], payload.get("arguments", {}))
    output_path.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: vacancy_disagreement_rank.py INPUT_JSON OUTPUT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
