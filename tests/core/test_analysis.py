from atomforge.analysis import build_analysis_payload
from atomforge.schemas import (
    DagNode,
    ExperimentSpec,
    MetricResult,
    ModelMetadata,
    ResultsGraph,
)


def test_analysis_payload_is_generic_and_grouped_by_node():
    spec = ExperimentSpec(
        experiment_id="two-method-study",
        dag=[
            DagNode(id="prepare", type="FETCH", params={"element": "Si"}),
            DagNode(
                id="evaluate",
                type="SIMULATE",
                depends_on="prepare",
                params={"mode": "custom-mode", "temperature": 450},
            ),
        ],
    )
    results = ResultsGraph(
        experiment_id=spec.experiment_id,
        metrics={
            "evaluate_score": MetricResult(val=1.5, unit="eV"),
            "global_score": MetricResult(val=2.0, unit="dimensionless"),
        },
        hypotheses=[],
        model_info=ModelMetadata(name="example", version="1", device="cpu"),
        summary="Completed.",
    )

    payload = build_analysis_payload(
        spec,
        results,
        {"evaluate": [{"score": 1.4}, {"score": 1.6}]},
        trial_data={
            "evaluate": {
                "positions": [[0.0, 0.0, 0.0]],
                "metadata": {"method": "recorded by executor"},
                "converged": True,
            }
        },
    )

    assert payload["contract_version"] == "v1"
    assert payload["scientific_decision_source"] == "script_results"
    assert payload["unscoped_metrics"]["global_score"] == {
        "val": 2.0,
        "unit": "dimensionless",
    }
    evaluate = next(node for node in payload["nodes"] if node["node_id"] == "evaluate")
    assert evaluate["parameters"]["mode"] == "custom-mode"
    assert evaluate["dependencies"] == ["prepare"]
    assert evaluate["metrics"]["evaluate_score"] == {"val": 1.5, "unit": "eV"}
    assert evaluate["trial_count"] == 2
    assert evaluate["data_summary"]["positions"] == {"type": "list", "count": 1}
    assert "pka_conditions" not in payload
    assert "nvt_analysis" not in payload


def test_physics_script_routing_depends_only_on_declared_profile():
    import inspect

    from atomforge.platform.modal.runtime import ModalExecutor

    source = inspect.getsource(ModalExecutor.script)
    assert "SCRIPT_EXECUTION_PROFILES[execution_profile]" in source
    assert "SCRIPT_WORKERS[policy.name]" in source
