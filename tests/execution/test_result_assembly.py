import pytest

from atomforge.execution.result_assembly import assemble_results
from atomforge.schemas import (
    DagNode,
    ExperimentSpec,
    Hypothesis,
    ModelMetadata,
    NVTResult,
    PKAResult,
    SinglePointResult,
)


def _spec() -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id="assembly-fixture",
        dag=[DagNode(id="simulate", type="SIMULATE", params={"mode": "pka"})],
    )


def _assemble(result, spec=None):
    return assemble_results(
        spec or _spec(),
        {"simulate": {"ensemble": result}},
        {},
        executor_metadata=ModelMetadata(device="cpu"),
        node_model_info={},
    )


def _hypothesis_result(assertion: str, *, metric: str = "n_defects"):
    spec = _spec().model_copy(
        update={
            "hypotheses": [
                Hypothesis(
                    id="check",
                    target_node="simulate",
                    metric=metric,
                    assertion=assertion,
                )
            ]
        }
    )
    return _assemble([PKAResult(seed=0, n_defects=1, energy=-1.0)], spec)[0].hypotheses[0]


def test_sparse_optional_metrics_keep_their_original_trial_indices():
    _, trial_bundle = _assemble(
        [
            PKAResult(seed=0, n_defects=1, energy=-1.0, interstitials=None),
            PKAResult(seed=1, n_defects=2, energy=-2.0, interstitials=5),
            PKAResult(seed=2, n_defects=3, energy=-3.0, interstitials=None),
        ]
    )

    trials = trial_bundle["trial_metrics_by_node"]["simulate"]
    assert [trial["n_defects"] for trial in trials] == [1.0, 2.0, 3.0]
    assert "interstitials" not in trials[0]
    assert trials[1]["interstitials"] == 5.0
    assert "interstitials" not in trials[2]


def test_boolean_trial_evidence_is_not_aggregated_as_numeric():
    _, trial_bundle = _assemble(
        [
            NVTResult(
                seed=0,
                potential_energy=-1.0,
                mean_temperature_K=300.0,
                std_temperature_K=1.0,
                max_force=0.1,
                n_frames=2,
                stable=True,
                analysis_applicable=False,
                trajectory_quality_passed=True,
                bond_distance_stats={},
                bond_angle_stats={},
                rdf_stats={},
                positions=[[0.0, 0.0, 0.0]],
                cell=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            )
        ]
    )

    trial = trial_bundle["trial_metrics_by_node"]["simulate"][0]
    assert trial["stable"] is True
    assert trial["analysis_applicable"] is False
    assert trial["trajectory_quality_passed"] is True


def test_mixed_simulation_result_types_fail_with_a_clear_contract_error():
    with pytest.raises(ValueError, match="one result type"):
        _assemble(
            [
                PKAResult(seed=0, n_defects=1, energy=-1.0),
                SinglePointResult(
                    seed=1,
                    potential_energy=-1.0,
                    max_force=0.1,
                    force_norm=0.1,
                    forces=[[0.0, 0.0, 0.0]],
                    positions=[[0.0, 0.0, 0.0]],
                    cell=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                ),
            ]
        )


def test_hypothesis_review_preserves_missing_metric_reason_and_target_node():
    evaluation = _hypothesis_result("target.not_published > 0", metric="not_published")
    assert evaluation.target_node == "simulate"
    assert evaluation.status == "REVIEW"
    assert evaluation.review_reason == "MISSING_METRIC"
    assert evaluation.value == "Unavailable"


@pytest.mark.parametrize(
    "assertion, reason",
    [
        ("target.n_defects >", "INVALID_EXPRESSION"),
        ("target.n_defects + 'x' > 0", "NON_NUMERIC_VALUE"),
    ],
)
def test_hypothesis_review_preserves_evaluation_reason(assertion, reason):
    assert _hypothesis_result(assertion).review_reason == reason


def test_unexpected_hypothesis_error_is_structured(monkeypatch):
    def fail(_):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(
        "atomforge.execution.result_assembly.mean_and_bootstrap_ci",
        fail,
    )
    evaluation = _hypothesis_result("target.n_defects > 0")
    assert evaluation.review_reason == "EVALUATION_ERROR"
    assert evaluation.detail == "The hypothesis assertion raised an unexpected evaluation error."
