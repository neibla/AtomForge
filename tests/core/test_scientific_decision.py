import pytest

from atomforge.scientific_decision import (
    blocked_decision_from_execution,
    decision_from_bundle,
    decision_from_script_results,
)


def test_failed_execution_gets_explicit_blocked_decision():
    decision = blocked_decision_from_execution({"scan": "all points failed"})

    assert decision.outcome == "BLOCKED"
    assert decision.calibration.status == "INSUFFICIENT_EVIDENCE"
    assert "scan" in decision.limitations[0]


def _decision() -> dict:
    return {
        "contract_version": "scientific-decision.v1",
        "outcome": "VALIDATED",
        "calibration": {
            "status": "INSUFFICIENT_EVIDENCE",
            "accepted_case_count": 1,
            "minimum_case_count": 30,
        },
        "scope": "One declared Ta vacancy and DFT protocol.",
        "headline": "Held-out DFT validation passed.",
        "supported_claims": ["The declared held-out case passed."],
        "limitations": ["One case does not calibrate uncertainty."],
        "quality_checks": [],
    }


def test_downstream_scientific_decision_is_the_single_decision_surface():
    decision = decision_from_script_results(
        {
            "screen": {
                "data": {
                    "scientific_decision": {
                        **_decision(),
                        "outcome": "REVIEW",
                        "headline": "Candidate selected for DFT.",
                    }
                }
            },
            "validate": {"data": {"scientific_decision": _decision()}},
        }
    )

    assert decision is not None
    assert decision.outcome == "VALIDATED"
    assert decision.calibration.accepted_case_count == 1


def test_explicit_decision_node_overrides_completion_or_mapping_order():
    decision = decision_from_script_results(
        {
            "screen": {"data": {"scientific_decision": _decision()}},
            "validate": {
                "data": {
                    "scientific_decision": {
                        **_decision(),
                        "outcome": "REVIEW",
                    }
                }
            },
        },
        decision_node_id="screen",
    )

    assert decision is not None
    assert decision.outcome == "VALIDATED"


def test_legacy_interpretation_is_not_a_supported_contract():
    assert (
        decision_from_bundle(
            {
                "script_results": {
                    "legacy": {
                        "data": {
                            "interpretation": {
                                "status": "DFT_VALIDATED",
                                "headline": "Old shape",
                            }
                        }
                    }
                }
            }
        )
        is None
    )


def test_malformed_scientific_decision_fails_closed():
    with pytest.raises(ValueError, match="calibration"):
        decision_from_script_results(
            {
                "validate": {
                    "data": {
                        "scientific_decision": {
                            "contract_version": "scientific-decision.v1",
                            "outcome": "VALIDATED",
                        }
                    }
                }
            }
        )
