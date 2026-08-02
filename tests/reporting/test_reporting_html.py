# ruff: noqa: E501
import hashlib
import json
import re

import pytest

from atomforge.reporting.html import (
    _chart_svg,
    _fmt_axis,
    build_html_report,
    render_html_report,
)


def generic_bundle() -> dict:
    return {
        "results": {
            "experiment_id": "generic-material-study",
            "status": "SUCCESS",
            "metrics": {
                "minimum_energy": {"val": -1.25, "unit": "eV/atom"},
                "maximum_force": {"val": 0.004, "unit": "eV/Å"},
            },
            "hypotheses": [
                {
                    "id": "force_gate",
                    "status": "PASSED",
                    "metric": "maximum_force",
                    "value": "0.004 eV/Å",
                }
            ],
            "model_info": {"name": "example-potential", "version": "1", "device": "cpu"},
        },
        "spec": {"experiment_id": "generic-material-study"},
        "script_results": {
            "analyse": {
                "data": {
                    "source": {
                        "title": "Recorded benchmark",
                        "authors": "A. Researcher",
                        "url": "https://example.com/paper",
                        "code_url": "https://example.com/code",
                        "data_url": "https://example.com/data",
                    },
                    "dataset": {
                        "selection_method": "Declared before execution",
                        "selected_case_count": 2,
                        "dataset_sha256": "a" * 64,
                    },
                    "acceptance_contract": {
                        "maximum_force": "<= 0.01 eV/Å",
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
                        "scope": (
                            "Two recorded cases under the declared force-validation protocol."
                        ),
                        "headline": "The configured validation checks passed.",
                        "quality_checks": [
                            {
                                "label": "Residual force",
                                "status": "PASS",
                                "value": 0.004,
                                "unit": "eV/Å",
                                "criterion": "<= 0.01 eV/Å",
                            }
                        ],
                        "supported_claims": [
                            "The recorded cases passed the configured force gate."
                        ],
                        "limitations": [
                            "This does not establish performance outside the recorded scope."
                        ],
                    },
                    "report_sections": [
                        {
                            "title": "Recommended next step",
                            "body": "Validate the most promising candidates with a higher-fidelity method.",
                        }
                    ],
                }
            }
        },
        "visualizations": {
            "contract_version": "v1",
            "experiment_id": "generic-material-study",
            "visualizations": [
                {
                    "id": "curve",
                    "kind": "chart.v1",
                    "title": "Recorded energy curve",
                    "description": "Values emitted by the experiment.",
                    "source_node": "analyse",
                    "mark": "line",
                    "rows": [
                        {"distance": 1.0, "energy": -1.0},
                        {"distance": 2.0, "energy": -1.25},
                    ],
                    "x": {
                        "field": "distance",
                        "label": "Distance",
                        "type": "quantitative",
                        "unit": "Å",
                    },
                    "y": {
                        "field": "energy",
                        "label": "Energy",
                        "type": "quantitative",
                        "unit": "eV",
                    },
                },
                {
                    "id": "evidence",
                    "kind": "table.v1",
                    "title": "Recorded evidence",
                    "source_node": "analyse",
                    "columns": [
                        {"field": "candidate", "label": "Candidate"},
                        {"field": "score", "label": "Score", "unit": "eV"},
                        {"field": "status", "label": "Status"},
                    ],
                    "rows": [{"candidate": "A", "score": -1.25, "status": "PASS"}],
                },
                {
                    "id": "structure",
                    "kind": "atomistic.v1",
                    "title": "Recorded structure",
                    "source_node": "analyse",
                    "data": {
                        "numbers": [14, 14],
                        "symbols": ["Si", "Si"],
                        "positions": [[0, 0, 0], [1.5, 1.5, 1.5]],
                        "vacancy_positions": [[0.75, 0.75, 0.75]],
                        "cell": [[3, 0, 0], [0, 3, 0], [0, 0, 3]],
                        "pbc": [True, True, True],
                        "metadata": {"role": "relaxed candidate"},
                    },
                },
            ],
        },
    }


def test_html_report_is_driven_by_recorded_contracts():
    report = render_html_report(generic_bundle())

    assert "Validated" in report
    assert "The configured validation checks passed" in report
    assert "The recorded cases passed the configured force gate" in report
    assert "This does not establish performance outside the recorded scope" in report
    assert "Recorded quality checks" in report
    assert "Predeclared acceptance contract" in report
    assert "Dataset identity and scope" in report
    assert "Recommended next step" in report
    assert 'href="https://example.com/paper"' in report
    assert "Recorded energy curve" in report
    assert "Distance (Å)" in report
    assert "Energy (eV)" in report
    assert "Recorded evidence" in report
    assert '<td data-label="Status" class="status-pass">PASS</td>' in report
    assert "Recorded structure" in report
    assert "Si × 2" in report
    assert "Vacancy sites" in report
    assert 'class="vacancy-point"' in report
    assert "@media print" in report


def test_html_report_uses_downstream_dft_decision_as_the_bottom_line():
    bundle = generic_bundle()
    bundle["script_results"]["validate_dft"] = {
        "data": {
            "scientific_decision": {
                "contract_version": "scientific-decision.v1",
                "outcome": "VALIDATED",
                "calibration": {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "accepted_case_count": 1,
                    "minimum_case_count": 30,
                },
                "scope": "Ta held-out vacancy under the declared DFT protocol.",
                "headline": "Held-out DFT validation passed for Ta.",
                "supported_claims": ["The promoted geometry passed the held-out DFT gates."],
                "limitations": ["One result does not calibrate uncertainty."],
            }
        }
    }

    report = render_html_report(bundle)

    bottom_line = report.split("decision-summary pass", maxsplit=1)[1].split(
        "</section>", maxsplit=1
    )[0]
    assert "Validated" in bottom_line
    assert "Held-out DFT validation passed for Ta." in bottom_line
    assert "The configured validation checks passed." not in bottom_line


def test_html_report_does_not_infer_science_from_experiment_id():
    bundle = {
        "results": {
            "experiment_id": "tungsten-vacancy-generic-demo",
            "status": "SUCCESS",
            "metrics": {},
            "hypotheses": [],
        },
        "visualizations": {
            "contract_version": "v1",
            "experiment_id": "tungsten-vacancy-generic-demo",
            "visualizations": [],
        },
    }

    report = render_html_report(bundle)

    assert "Scientific decision not recorded" in report
    assert "benchmark passed" not in report.lower()
    assert "reproduced" not in report.lower()
    assert "1,000" not in report
    assert "3,008" not in report


def test_html_report_rejects_nonconforming_scientific_decision():
    bundle = generic_bundle()
    bundle["script_results"]["analyse"]["data"]["scientific_decision"] = {
        "contract_version": "scientific-decision.v1",
        "supported_claims": ["The bounded scan can reveal obvious curve pathologies."],
        "limitations": ["This does not establish general model stability."],
        "decision_rule": "Escalate any detected anomaly.",
    }

    with pytest.raises(ValueError, match="outcome"):
        render_html_report(bundle)


def test_html_report_preserves_recorded_visual_copy_verbatim():
    bundle = generic_bundle()
    visual = bundle["visualizations"]["visualizations"][0]
    visual["title"] = "Exactly 17 recorded candidates"
    visual["description"] = "This copy came from the experiment contract."

    report = render_html_report(bundle)

    assert "Exactly 17 recorded candidates" in report
    assert "This copy came from the experiment contract" in report


def test_html_report_hydrates_verified_standalone_visualization_catalog(tmp_path):
    bundle = generic_bundle()
    catalog = {
        "contract_version": "v1",
        "experiment_id": "generic-material-study",
        "visualizations": [
            {
                "id": "curve",
                "kind": "chart.v1",
                "title": "Recorded energy curve",
                "description": "Values emitted by the experiment.",
                "source_node": "analyse",
                "mark": "line",
                "rows": [
                    {"distance": 1.0, "energy": -1.0},
                    {"distance": 2.0, "energy": -1.25},
                ],
                "x": {
                    "field": "distance",
                    "label": "Distance",
                    "type": "quantitative",
                    "unit": "Å",
                },
                "y": {
                    "field": "energy",
                    "label": "Energy",
                    "type": "quantitative",
                    "unit": "eV",
                },
            }
        ],
    }
    bundle.pop("visualizations")
    catalog_path = tmp_path / "generic-material-study_visualizations.json"
    catalog_content = json.dumps(catalog, indent=2)
    catalog_path.write_text(catalog_content)
    bundle["visualization_catalog_ref"] = {
        "contract_version": "catalog-reference.v1",
        "artifact_path": catalog_path.name,
        "sha256": hashlib.sha256(catalog_content.encode()).hexdigest(),
        "visualization_count": len(catalog["visualizations"]),
    }
    bundle_path = tmp_path / "generic-material-study.json"
    bundle_path.write_text(json.dumps(bundle, indent=2))

    report = render_html_report(bundle, source_path=bundle_path)

    assert "Recorded energy curve" in report


def test_html_report_rejects_standalone_catalog_checksum_mismatch(tmp_path):
    bundle = generic_bundle()
    bundle.pop("visualizations")
    catalog_path = tmp_path / "generic-material-study_visualizations.json"
    catalog_path.write_text(
        json.dumps(
            {
                "contract_version": "v1",
                "experiment_id": "generic-material-study",
                "visualizations": [],
            },
            indent=2,
        )
    )
    bundle["visualization_catalog_ref"] = {
        "contract_version": "catalog-reference.v1",
        "artifact_path": catalog_path.name,
        "sha256": "0" * 64,
        "visualization_count": 0,
    }

    with pytest.raises(ValueError, match="checksum mismatch"):
        render_html_report(bundle, source_path=tmp_path / "generic-material-study.json")


def test_html_report_uses_distinct_chart_marks_and_readable_ticks():
    bundle = generic_bundle()
    bundle["visualizations"]["visualizations"] = [
        {
            "id": "bars",
            "kind": "chart.v1",
            "title": "Bars",
            "mark": "bar",
            "rows": [{"name": "A", "value": 0.904042}],
            "x": {"field": "name", "type": "nominal"},
            "y": {"field": "value", "type": "quantitative"},
        },
        {
            "id": "scatter",
            "kind": "chart.v1",
            "title": "Scatter",
            "mark": "scatter",
            "rows": [{"x": 1.0, "y": 1.1}, {"x": 2.0, "y": 1.9}],
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    ]

    report = render_html_report(bundle)

    assert "<rect x=" in report
    assert 'class="bar"' in report
    assert 'class="agreement"' in report
    assert _fmt_axis(0.904042) == "0.904"


def test_positive_bar_chart_uses_zero_baseline_and_keeps_edge_bars_in_frame():
    svg = _chart_svg(
        {
            "kind": "chart.v1",
            "title": "Absolute errors",
            "mark": "bar",
            "rows": [
                {"model": "MACE-MP-0", "error": 0.058736},
                {"model": "MatterSim", "error": 1.53476},
            ],
            "x": {"field": "model", "type": "nominal"},
            "y": {"field": "error", "type": "quantitative", "unit": "eV"},
        }
    )

    tick_values = re.findall(r'class="tick">([^<]+)</text>', svg)
    rectangles = [
        (float(x), float(width))
        for x, width in re.findall(r'<rect x="([^"]+)"[^>]+width="([^"]+)"', svg)
    ]

    y_tick_values = tick_values[:5]
    assert y_tick_values[-1] == "0"
    assert all(not value.startswith("-") for value in y_tick_values)
    assert all(x >= 82 for x, _ in rectangles)
    assert all(x + width <= 952 for x, width in rectangles)


def test_build_html_report_loads_canonical_evidence_repository(tmp_path):
    results = tmp_path / ".atomforge" / "results"
    results.mkdir(parents=True)
    (results / "any-study.json").write_text(
        json.dumps({"results": {"experiment_id": "any-study", "status": "SUCCESS"}}),
        encoding="utf-8",
    )

    output = build_html_report("any-study", root=tmp_path)

    assert output == tmp_path / "experiments" / "reports" / "any-study.html"
    assert output.is_file()
    assert "any-study" in output.read_text(encoding="utf-8")
