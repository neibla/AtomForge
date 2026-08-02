import math

import pytest

from atomforge.node_scripts.coordinate_scan_analysis import InputPayload, build_output


def _trial(displacement: float) -> dict:
    spring_constant = 2.0
    atom_count = 2
    total_energy = -20.0 + 0.5 * spring_constant * displacement**2
    projected_force = -spring_constant * displacement
    component = projected_force / math.sqrt(3.0)
    return {
        "ensemble": [
            {
                "potential_energy": total_energy / atom_count,
                "max_force": abs(projected_force),
                "forces": [[component, component, component], [0.0, 0.0, 0.0]],
                "positions": [
                    [
                        displacement / math.sqrt(3.0),
                        displacement / math.sqrt(3.0),
                        displacement / math.sqrt(3.0),
                    ],
                    [1.0, 1.0, 1.0],
                ],
            }
        ]
    }


def _payload() -> InputPayload:
    displacements = [-0.2, -0.1, 0.0, 0.1, 0.2]
    node_ids = ["m020", "m010", "zero", "p010", "p020"]
    return InputPayload.model_validate(
        {
            "contract_version": "v1",
            "inputs": {
                node_id: _trial(displacement)
                for node_id, displacement in zip(node_ids, displacements, strict=True)
            },
            "arguments": {
                "atom_index": 0,
                "coordinate_label": "Synthetic coordinate",
                "direction": [1.0, 1.0, 1.0],
                "method_alignment": "same_method",
                "source": {"kind": "analytic harmonic fixture"},
                "decision_context": {
                    "supported_claims": ["Contract and analytic consistency check."],
                    "limitations": ["Scientific validation."],
                    "decision_rule": "Require the analytic checks to pass.",
                },
                "quality_contract": {
                    "scientific_claim": "none",
                    "quality_gates": [],
                },
                "limitations": ["Synthetic fixture only."],
                "report_sections": [
                    {"title": "Fixture", "body": "Generic analyzer regression test."}
                ],
                "scan_nodes": [
                    {"node_id": node_id, "displacement_A": displacement}
                    for node_id, displacement in zip(node_ids, displacements, strict=True)
                ],
            },
        }
    )


def test_coordinate_scan_analyzer_is_configured_by_payload():
    output = build_output(_payload())

    assert output.metrics["scan_points"].val == 5
    assert output.metrics["energy_force_consistency_rmse"].val == pytest.approx(0.0, abs=1e-12)
    assert output.metrics["max_inversion_energy_mismatch"].val == pytest.approx(0.0)
    assert output.metrics["artificial_minima_count"].val == 0
    assert output.metrics["monotonicity_violation_count"].val == 0
    assert output.data["source"] == {"kind": "analytic harmonic fixture"}
    assert output.data["scientific_decision"]["outcome"] == "REVIEW"
    assert "same_method" in output.data["scientific_decision"]["scope"]
    assert (
        output.data["scientific_decision"]["headline"]
        == "Bounded coordinate scan found no obvious pathology."
    )


def test_coordinate_scan_analyzer_accepts_first_class_sweep_result():
    legacy = _payload()
    scan_nodes = legacy.arguments.pop("scan_nodes")
    legacy.arguments["sweep_node"] = "coordinate_scan"
    legacy.inputs = {
        "coordinate_scan": {
            "contract_version": "sweep-result.v1",
            "coordinate": {
                "name": "displacement_A",
                "label": "Synthetic coordinate",
                "unit": "Å",
                "grid": {"values": [point["displacement_A"] for point in scan_nodes]},
            },
            "apply": {
                "target": "displacement",
                "transform": "scale_vector",
                "vector": [1 / math.sqrt(3)] * 3,
            },
            "points": [
                {
                    "id": f"coordinate-scan-point-{index:04d}",
                    "index": index,
                    "value": point["displacement_A"],
                    "applied_value": [point["displacement_A"] / math.sqrt(3)] * 3,
                    "simulation_params": {},
                    "status": "COMPLETED",
                    "ensemble": legacy.inputs[point["node_id"]]["ensemble"],
                }
                for index, point in enumerate(scan_nodes)
            ],
        }
    }

    output = build_output(legacy)

    assert output.metrics["scan_points"].val == 5
    assert output.metrics["energy_force_consistency_rmse"].val == pytest.approx(0.0)
    assert output.data["scientific_decision"]["supported_claims"] == [
        "This bounded coordinate scan found no artificial minimum or "
        "non-monotonic branch on the declared grid.",
        "Contract and analytic consistency check.",
    ]
    assert output.data["scientific_decision"]["limitations"] == [
        "Scientific validation.",
        "Synthetic fixture only.",
    ]
    assert all(
        visualization.title.startswith("Synthetic coordinate")
        for visualization in output.visualizations
    )


def test_coordinate_scan_analyzer_rejects_projection_direction_mismatch():
    payload = _payload()
    scan_nodes = payload.arguments.pop("scan_nodes")
    payload.arguments["sweep_node"] = "coordinate_scan"
    payload.arguments["direction"] = [1.0, 0.0, 0.0]
    payload.inputs = {
        "coordinate_scan": {
            "contract_version": "sweep-result.v1",
            "coordinate": {
                "name": "displacement_A",
                "label": "Synthetic coordinate",
                "unit": "Å",
                "grid": {"values": [point["displacement_A"] for point in scan_nodes]},
            },
            "apply": {
                "target": "displacement",
                "transform": "scale_vector",
                "vector": [1 / math.sqrt(3)] * 3,
            },
            "points": [
                {
                    "id": point["node_id"],
                    "index": index,
                    "value": point["displacement_A"],
                    "applied_value": [point["displacement_A"] / math.sqrt(3)] * 3,
                    "simulation_params": {},
                    "status": "COMPLETED",
                    "ensemble": _trial(point["displacement_A"])["ensemble"],
                }
                for index, point in enumerate(scan_nodes)
            ],
        }
    }

    with pytest.raises(ValueError, match="must match the sweep displacement vector"):
        build_output(payload)


def test_coordinate_scan_analyzer_rejects_missing_decision_context():
    payload = _payload()
    payload.arguments.pop("decision_context")

    with pytest.raises(ValueError, match="decision_context"):
        build_output(payload)
