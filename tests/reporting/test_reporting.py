import pytest

from atomforge.reporting import render_research_report
from atomforge.schemas import (
    DagNode,
    ExperimentSpec,
    Hypothesis,
    HypothesisEval,
    MetricResult,
    ModelMetadata,
    ResultsGraph,
    ScriptResult,
)


def base_result() -> ResultsGraph:
    return ResultsGraph(
        experiment_id="generic-study",
        metrics={"analysis_score": MetricResult(val=1.2, unit="eV")},
        hypotheses=[
            HypothesisEval(
                id="score_gate",
                target_node="analysis",
                status="PASSED",
                metric="analysis_score",
                value="1.2 eV",
                sample_size=2,
                ci_low=1.0,
                ci_high=1.4,
            )
        ],
        model_info=ModelMetadata(
            name="example-potential",
            version="1",
            head="default",
            dtype="float64",
            device="cpu",
        ),
        summary="Completed.",
    )


def test_report_separates_execution_from_scientific_validity():
    spec = ExperimentSpec(
        experiment_id="generic-study",
        dag=[DagNode(id="analysis", type="SCRIPT", params={"script": "checked.py"})],
        hypotheses=[
            Hypothesis(
                id="score_gate",
                target_node="analysis",
                metric="analysis_score",
                assertion="target.analysis_score <= 2.0",
            )
        ],
    )

    report = render_research_report(spec, base_result())

    assert "Workflow status is separate from scientific validity" in report
    assert "Quality and Acceptance Checks" in report
    assert "configured gate" in report
    assert "No experiment-authored scientific decision was recorded" in report


def test_report_renders_script_authored_claim_boundary_and_provenance():
    spec = ExperimentSpec(
        experiment_id="generic-study",
        dag=[DagNode(id="analysis", type="SCRIPT", params={"script": "checked.py"})],
    )
    script = ScriptResult(
        metrics={"score": MetricResult(val=1.2, unit="eV")},
        data={
            "source": {
                "title": "Published protocol",
                "authors": "A. Researcher",
                "url": "https://example.com/paper",
                "code_url": "https://example.com/code",
            },
            "dataset": {
                "selection_method": "Declared before execution",
                "selected_case_count": 2,
                "dataset_sha256": "b" * 64,
            },
            "acceptance_contract": {
                "score_tolerance": "<= 2 eV",
                "threshold_rationale": "Declared before execution.",
            },
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "VALIDATED",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 1,
                    "minimum_case_count": 30,
                },
                "scope": "Two declared benchmark cases under the recorded protocol.",
                "headline": "The configured validation checks passed.",
                "quality_checks": [
                    {
                        "label": "Score",
                        "status": "PASS",
                        "value": 1.2,
                        "unit": "eV",
                        "criterion": "<= 2 eV",
                    }
                ],
                "supported_claims": ["The recorded cases passed the configured gate."],
                "limitations": ["This does not establish out-of-scope performance."],
            },
            "report_sections": [
                {
                    "title": "Recommended next step",
                    "body": "Run a higher-fidelity validation on the selected candidates.",
                }
            ],
        },
    )

    report = render_research_report(spec, base_result(), script_results={"analysis": script})

    assert "Recorded scientific context (analysis)" in report
    assert "The configured validation checks passed" in report
    assert "The recorded cases passed the configured gate" in report
    assert "This does not establish out-of-scope performance" in report
    assert "Recorded quality checks" in report
    assert "Published protocol" in report
    assert "Dataset identity and scope" in report
    assert "Predeclared acceptance contract" in report
    assert "Recommended next step" in report
    assert "do not infer claims from workflow success alone" in report


def test_markdown_report_rejects_nonconforming_scientific_decision():
    spec = ExperimentSpec(
        experiment_id="generic-study",
        dag=[DagNode(id="analysis", type="SCRIPT", params={"script": "checked.py"})],
    )
    script = ScriptResult(
        metrics={"score": MetricResult(val=1.2, unit="eV")},
        data={
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "supported_claims": ["The bounded scan can reveal obvious curve pathologies."],
                "limitations": ["This does not establish general model stability."],
            }
        },
    )

    with pytest.raises(ValueError, match="outcome"):
        render_research_report(
            spec,
            base_result(),
            script_results={"analysis": script},
        )


def test_report_does_not_infer_domain_copy_from_node_parameters():
    spec = ExperimentSpec(
        experiment_id="named-like-a-demo",
        dag=[DagNode(id="simulate", type="SIMULATE", params={"mode": "pka", "element": "W"})],
    )

    report = render_research_report(spec, base_result())

    assert "tungsten radiation damage" not in report.lower()
    assert "illustrative execution-pipeline demonstration" not in report.lower()
