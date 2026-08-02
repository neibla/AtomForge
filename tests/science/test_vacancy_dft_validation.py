import pytest

from atomforge.node_scripts.vacancy_dft_validation import build_output


def _promoted():
    return {
        "case_id": "bcc-w",
        "element": "W",
        "mp_id": "mp-91",
        "geometry_fingerprint": "geometry-123",
        "mace_self_consistent_vacancy_eV": 3.2,
        "mattersim_self_consistent_vacancy_eV": 4.5,
        "cross_model_disagreement_eV": 1.3,
    }


def _dft():
    return {
        "case_id": "bcc-w",
        "initial_geometry_fingerprint": "geometry-123",
        "dft_vacancy_formation_energy_eV": 3.4,
        "electronic_converged": True,
        "ionic_converged": True,
        "independent_of_selection_models": True,
        "max_force_eV_per_A": 0.02,
        "final_energy_change_eV": 5e-6,
        "code": "VASP",
        "code_version": "6.4",
        "exchange_correlation_functional": "PBE",
        "pseudopotential_set": "PAW-PBE-2024",
        "spin_treatment": "spin-polarised, converged from declared initial moments",
        "reference_convention": "self-consistent elemental bulk",
        "plane_wave_cutoff_eV": 520.0,
        "kpoint_density_per_A": 30.0,
        "source_artifact_sha256": "a" * 64,
    }


def _inputs():
    return {"select_dft_case": {"data": {"decision": {"promoted_candidate": _promoted()}}}}


def test_converged_held_out_dft_result_is_recorded_without_claiming_calibration():
    output = build_output(_inputs(), {"dft_result": _dft()})

    assert output["metrics"]["dft_validation_gate_passed"]["val"] == 1.0
    assert output["data"]["validation"]["status"] == "DFT_VALIDATED"
    assert output["data"]["validation"]["closer_model"] == "MACE-MP-0"
    assert output["data"]["calibration_update"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert output["data"]["scientific_decision"]["outcome"] == "VALIDATED"
    assert output["data"]["scientific_decision"]["calibration"] == {
        "status": "INSUFFICIENT_EVIDENCE",
        "accepted_case_count": 1,
        "minimum_case_count": 30,
    }
    assert "W (mp-91)" in output["data"]["scientific_decision"]["scope"]
    assert "does not calibrate" in output["data"]["calibration_update"]["claim_boundary"]


def test_case_and_geometry_lineage_must_match_the_promoted_candidate():
    dft = _dft()
    dft["case_id"] = "bcc-ta"
    dft["initial_geometry_fingerprint"] = "other"

    output = build_output(_inputs(), {"dft_result": dft})

    assert output["metrics"]["dft_validation_gate_passed"]["val"] == 0.0
    failures = output["data"]["validation"]["gate_failures"]
    assert any("case_id" in failure for failure in failures)
    assert any("initial geometry" in failure for failure in failures)


def test_unconverged_or_non_independent_dft_evidence_fails_closed():
    dft = _dft()
    dft["electronic_converged"] = False
    dft["independent_of_selection_models"] = False
    dft["max_force_eV_per_A"] = 0.2

    output = build_output(_inputs(), {"dft_result": dft})

    assert output["data"]["validation"]["status"] == "REVIEW"
    assert output["data"]["validation"]["supported_claims"] == []
    assert output["data"]["scientific_decision"]["outcome"] == "REVIEW"
    assert len(output["data"]["validation"]["gate_failures"]) == 3


def test_reference_convention_is_required_for_cross_model_comparison():
    dft = _dft()
    dft["reference_convention"] = "isolated atom"

    output = build_output(_inputs(), {"dft_result": dft})

    assert output["metrics"]["dft_validation_gate_passed"]["val"] == 0.0
    assert any(
        "self-consistent elemental bulk" in failure
        for failure in output["data"]["validation"]["gate_failures"]
    )


def test_calibration_program_cannot_be_declared_from_too_small_a_target():
    with pytest.raises(ValueError, match="at least 10"):
        build_output(
            _inputs(),
            {"dft_result": _dft(), "minimum_calibration_cases": 5},
        )
