from __future__ import annotations

from atomforge.sweeps import bind_sweep_point, get_parameter, parameter_is_set, with_parameter


def test_parameter_path_reader_handles_nested_dicts_lists_and_missing_values():
    params = {
        "simulation": {"vectors": [[1.0, 2.0], [3.0, 4.0]], "optional": None},
        "0": "dictionary key",
    }

    assert get_parameter(params, "simulation.vectors.1.0") == 3.0
    assert parameter_is_set(params, "simulation.vectors.0.1") is True
    assert get_parameter(params, "0") == "dictionary key"
    assert get_parameter(params, "simulation.optional") is None
    assert parameter_is_set(params, "simulation.optional") is True
    assert parameter_is_set(params, "simulation.vectors.2.0") is False
    assert get_parameter(params, "simulation.missing", default="sentinel") == "sentinel"
    assert get_parameter(params, "simulation.vectors.0.missing", default="sentinel") == "sentinel"


def test_bind_sweep_point_is_the_canonical_execution_contract():
    binding = bind_sweep_point(
        operation_params={"simulation": {"cell_scale": 1.0}},
        target="simulation.cell_scale",
        value=2.0,
        apply_value=lambda value: value * 0.5,
        mode="single_point",
        trials=3,
    )

    assert binding.value == 2.0
    assert binding.applied_value == 1.0
    assert binding.simulation_params == {
        "simulation": {"cell_scale": 1.0},
        "mode": "single_point",
        "trials": 3,
    }


def test_with_parameter_does_not_mutate_the_operation_params():
    params = {"vectors": [1.0, 2.0]}

    updated = with_parameter(params, "vectors.1", 4.0)

    assert params == {"vectors": [1.0, 2.0]}
    assert updated == {"vectors": [1.0, 4.0]}
