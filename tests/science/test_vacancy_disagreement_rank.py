import pytest

from atomforge.node_scripts.vacancy_disagreement_rank import (
    build_output,
    rank_disagreements,
)
from atomforge.schemas import ScriptOutput


def _mace_rows():
    return [
        {
            "case_id": "v",
            "mp_id": "mp-1",
            "element": "V",
            "geometry_fingerprint": "a",
            "mace_self_consistent_vacancy_eV": 2.0,
            "absolute_reproduction_error_eV": 0.02,
            "finite": True,
            "reproduction_status": "PASS",
        },
        {
            "case_id": "w",
            "mp_id": "mp-2",
            "element": "W",
            "geometry_fingerprint": "b",
            "mace_self_consistent_vacancy_eV": 3.0,
            "absolute_reproduction_error_eV": 0.04,
            "finite": True,
            "reproduction_status": "PASS",
        },
    ]


def _mattersim_rows():
    return [
        {
            "case_id": "v",
            "mp_id": "mp-1",
            "element": "V",
            "geometry_fingerprint": "a",
            "mattersim_self_consistent_vacancy_eV": 2.1,
            "finite": True,
        },
        {
            "case_id": "w",
            "mp_id": "mp-2",
            "element": "W",
            "geometry_fingerprint": "b",
            "mattersim_self_consistent_vacancy_eV": 3.6,
            "finite": True,
        },
    ]


def _prepared_cases():
    return [
        {
            "case_id": "v",
            "geometry_fingerprint": "a",
            "pristine_structure": {
                "numbers": [23, 23],
                "symbols": ["V", "V"],
                "positions": [[0.0, 0.0, 0.0], [1.5, 1.5, 1.5]],
                "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
                "pbc": [True, True, True],
            },
            "defect_structure": {
                "numbers": [23],
                "symbols": ["V"],
                "positions": [[1.5, 1.5, 1.5]],
                "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
                "pbc": [True, True, True],
            },
        },
        {
            "case_id": "w",
            "geometry_fingerprint": "b",
            "pristine_structure": {
                "numbers": [74, 74],
                "symbols": ["W", "W"],
                "positions": [[0.0, 0.0, 0.0], [1.5, 1.5, 1.5]],
                "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
                "pbc": [True, True, True],
            },
            "defect_structure": {
                "numbers": [74],
                "symbols": ["W"],
                "positions": [[1.5, 1.5, 1.5]],
                "cell": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
                "pbc": [True, True, True],
            },
        },
    ]


def test_rank_promotes_largest_credible_disagreement():
    ranked, promoted = rank_disagreements(
        _mace_rows(),
        _mattersim_rows(),
        promotion_threshold_eV=0.25,
    )

    assert [row["case_id"] for row in ranked] == ["w", "v"]
    assert promoted is not None
    assert promoted["case_id"] == "w"
    assert promoted["decision"] == "PROMOTE_TO_DFT"


def test_failed_reproduction_is_ineligible_even_with_large_disagreement():
    mace = _mace_rows()
    mace[1]["reproduction_status"] = "REVIEW"

    ranked, promoted = rank_disagreements(
        mace,
        _mattersim_rows(),
        promotion_threshold_eV=0.25,
    )

    held = next(row for row in ranked if row["case_id"] == "w")
    assert held["eligible"] is False
    assert "reproduction" in held["reason"]
    assert promoted is None


def test_complete_panel_can_record_valid_no_promotion():
    mattersim = _mattersim_rows()
    mattersim[1]["mattersim_self_consistent_vacancy_eV"] = 3.1
    output = build_output(
        {
            "reproduce_mace": {"data": {"comparison_rows": _mace_rows()}},
            "evaluate_mattersim": {"data": {"comparison_rows": mattersim}},
        },
        {
            "expected_case_count": 2,
            "promotion_threshold_eV": 0.25,
        },
    )

    validated = ScriptOutput.model_validate(output)
    assert validated.metrics["decision_gate_passed"].val == 1
    assert validated.metrics["promotion_made"].val == 0
    assert validated.data["decision"]["promoted_candidate"] is None
    assert "No DFT escalation" in validated.data["decision"]["headline"]
    assert all(view.kind != "atomistic.v1" for view in validated.visualizations)


def test_promoted_case_emits_only_the_decision_selected_vacancy_lattice():
    output = build_output(
        {
            "reproduce_mace": {"data": {"comparison_rows": _mace_rows()}},
            "evaluate_mattersim": {"data": {"comparison_rows": _mattersim_rows()}},
            "prepare_paper_subset": {"data": {"cases": _prepared_cases()}},
        },
        {
            "expected_case_count": 2,
            "promotion_threshold_eV": 0.25,
            "geometry_node": "prepare_paper_subset",
        },
    )

    validated = ScriptOutput.model_validate(output)
    structure = next(view for view in validated.visualizations if view.kind == "atomistic.v1")
    assert structure.id == "promoted-w-monovacancy"
    assert structure.data.symbols == ["W"]
    assert structure.data.vacancy_positions == [[0.0, 0.0, 0.0]]
    assert structure.data.metadata["scientific_role"] == "held-out DFT target, not DFT evidence"
    assert validated.data["decision"]["selected_structure_visualization_id"] == structure.id


def test_failed_geometry_gate_cannot_be_reported_as_no_promotion():
    mattersim = _mattersim_rows()
    mattersim[0]["geometry_fingerprint"] = "different"
    output = build_output(
        {
            "reproduce_mace": {"data": {"comparison_rows": _mace_rows()}},
            "evaluate_mattersim": {"data": {"comparison_rows": mattersim}},
        },
        {
            "expected_case_count": 2,
            "promotion_threshold_eV": 10.0,
        },
    )

    validated = ScriptOutput.model_validate(output)
    assert validated.metrics["decision_gate_passed"].val == 0
    assert validated.metrics["promotion_made"].val == 0
    assert "No decision" in validated.data["decision"]["headline"]
    assert "Resolve the failed evidence gates" in validated.data["decision"]["next_calculation"]


def test_failed_reproduction_cannot_be_reported_as_a_decision():
    mace = _mace_rows()
    mace[1]["reproduction_status"] = "REVIEW"
    output = build_output(
        {
            "reproduce_mace": {"data": {"comparison_rows": mace}},
            "evaluate_mattersim": {"data": {"comparison_rows": _mattersim_rows()}},
        },
        {
            "expected_case_count": 2,
            "promotion_threshold_eV": 0.25,
        },
    )

    validated = ScriptOutput.model_validate(output)
    assert validated.metrics["decision_gate_passed"].val == 0
    assert validated.data["scientific_decision"]["outcome"] == "BLOCKED"
    assert validated.data["decision"]["promoted_candidate"] is None


def test_model_workers_must_use_identical_geometry():
    mattersim = _mattersim_rows()
    mattersim[0]["geometry_fingerprint"] = "different"

    ranked, _ = rank_disagreements(
        _mace_rows(),
        mattersim,
        promotion_threshold_eV=0.0,
    )

    row = next(item for item in ranked if item["case_id"] == "v")
    assert row["eligible"] is False
    assert "identical geometries" in row["reason"]


def test_model_case_sets_must_match():
    with pytest.raises(ValueError, match="model case sets differ"):
        rank_disagreements(
            _mace_rows(),
            _mattersim_rows()[:1],
            promotion_threshold_eV=0.25,
        )
