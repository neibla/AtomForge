import math

import pytest

from atomforge.node_scripts.birch_murnaghan_eos import InputPayload, build_output


def _bm_shape(volume: float, equilibrium: float, bprime: float) -> float:
    eta = (equilibrium / volume) ** (2.0 / 3.0)
    x = eta - 1.0
    return (9.0 * equilibrium / 16.0) * (x**3 * bprime + x**2 * (6.0 - 4.0 * eta))


def _payload(
    volumes: list[float],
    energies: list[float],
) -> InputPayload:
    inputs = {}
    scan_nodes = []
    for index, (volume, energy) in enumerate(zip(volumes, energies, strict=True)):
        node_id = f"point_{index}"
        side = volume ** (1.0 / 3.0)
        inputs[node_id] = {
            "ensemble": [
                {
                    "cell": [[side, 0.0, 0.0], [0.0, side, 0.0], [0.0, 0.0, side]],
                    "positions": [[0.0, 0.0, 0.0]],
                    "atomic_numbers": [74],
                    "potential_energy": energy,
                }
            ]
        }
        scan_nodes.append({"node_id": node_id, "linear_scale": side})
    return InputPayload(
        contract_version="v1",
        inputs=inputs,
        arguments={"scan_nodes": scan_nodes},
    )


def _clean_payload(equilibrium: float = 10.0) -> InputPayload:
    volumes = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
    energies = [
        -10.0 + 0.04 * _bm_shape(volume, equilibrium, 4.0)
        for volume in volumes
    ]
    return _payload(volumes, energies)


@pytest.mark.parametrize("noisy", [False, True])
def test_clean_birch_murnaghan_curve_has_supported_headline(noisy):
    payload = _clean_payload()
    if noisy:
        for index, node in enumerate(payload.inputs.values()):
            node["ensemble"][0]["potential_energy"] += (index % 2) * 0.001
    output = build_output(payload)
    decision = output.data["scientific_decision"]

    assert output.metrics["eos_minimum_inside_scan"].val == 1.0
    assert decision["headline"].startswith("The fitted EOS has an interior minimum")
    assert all(check["status"] == "PASS" for check in decision["quality_checks"])
    assert output.data["fit"]["quality"]["fit_usable"] is True


def test_minimum_outside_scan_is_reported_as_inconclusive():
    output = build_output(_clean_payload(equilibrium=6.0))
    decision = output.data["scientific_decision"]

    assert output.metrics["eos_minimum_inside_scan"].val == 0.0
    assert "does not bracket" in decision["headline"]
    assert decision["quality_checks"][-1]["status"] == "FAILED"


def test_flat_curve_fails_bulk_modulus_quality_check():
    output = build_output(_payload([8.0, 9.0, 10.0, 11.0, 12.0], [-1.0] * 5))
    decision = output.data["scientific_decision"]

    assert "inconclusive" in decision["headline"]
    assert any(
        check["label"] == "Positive bulk modulus" and check["status"] == "FAILED"
        for check in decision["quality_checks"]
    )


def test_negative_bulk_modulus_is_not_described_as_stable():
    volumes = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
    energies = [-10.0 - 0.04 * _bm_shape(volume, 10.0, 4.0) for volume in volumes]
    output = build_output(_payload(volumes, energies))

    assert "inconclusive" in output.data["scientific_decision"]["headline"]


@pytest.mark.parametrize(
    "volumes, energies, message",
    [
        ([8.0, 9.0, 9.0, 11.0, 12.0], [-1.0] * 5, "distinct volumes"),
        ([8.0, 9.0, 10.0, 11.0], [-1.0] * 4, "5 scan_nodes"),
    ],
)
def test_invalid_scan_shapes_are_rejected(volumes, energies, message):
    with pytest.raises(ValueError, match=message):
        build_output(_payload(volumes, energies))


def test_non_finite_input_is_rejected():
    payload = _clean_payload()
    payload.inputs["point_0"]["ensemble"][0]["potential_energy"] = math.nan

    with pytest.raises(ValueError, match="non-finite"):
        build_output(payload)
