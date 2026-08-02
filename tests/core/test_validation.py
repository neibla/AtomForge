import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from atomforge.contracts import SIMULATION_MODES
from atomforge.schemas import DagNode, ExperimentSpec, Hypothesis
from atomforge.simulation_modes import MODE_CONTRACTS
from atomforge.validators import validate_experiment_spec, validate_runtime_sources


def test_rejects_invalid_simulation_mode():
    spec = ExperimentSpec(
        experiment_id="invalid-mode",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "not-a-mode", "trials": 1},
            ),
        ],
    )
    with pytest.raises(ValueError, match="invalid mode"):
        validate_experiment_spec(spec)


def test_mode_contract_registry_covers_public_modes():
    assert set(MODE_CONTRACTS) == SIMULATION_MODES


def test_accepts_single_point_probe():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "single-point-probe",
            "dag": [
                {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "s1",
                    "type": "SIMULATE",
                    "depends_on": "f1",
                    "params": {
                        "mode": "single_point",
                        "trials": 1,
                        "displacement": [0.2, 0.0, 0.0],
                    },
                },
            ],
            "hypotheses": [
                {
                    "id": "force-is-finite",
                    "target_node": "s1",
                    "metric": "max_force",
                    "assertion": "target.max_force >= 0",
                }
            ],
        }
    )
    validate_experiment_spec(spec)


def test_accepts_safe_structure_path_and_rejects_traversal():
    validate_experiment_spec(
        ExperimentSpec(
            experiment_id="file-backed-fetch",
            dag=[
                DagNode(
                    id="f1",
                    type="FETCH",
                    params={"structure_path": "Mg2SiO4_balanced.xyz"},
                )
            ],
        )
    )
    unsafe = ExperimentSpec(
        experiment_id="unsafe-file-backed-fetch",
        dag=[DagNode(id="f1", type="FETCH", params={"structure_path": "../secret"})],
    )
    with pytest.raises(ValueError, match="relative safe path"):
        validate_experiment_spec(unsafe)


def test_retained_demo_specs_are_valid():
    for path in (
        "experiments/dags/berger-vacancy-reproduction-20260801-r2.json",
        "experiments/dags/berger-vacancy-gpaw-validation-20260801-r2.json",
    ):
        validate_experiment_spec(ExperimentSpec.model_validate_json(Path(path).read_text()))


def test_accepts_first_class_lattice_parameter_sweep():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "lattice-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "Si"}},
                {
                    "id": "eos",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point", "params": {}, "trials": 1},
                        "coordinate": {
                            "name": "lattice_constant_A",
                            "label": "Lattice parameter",
                            "unit": "Å",
                            "grid": {"start": 5.35, "stop": 5.53, "step": 0.01},
                        },
                        "apply": {
                            "target": "cell_scale",
                            "transform": "ratio_to_reference",
                            "reference": 5.43,
                        },
                    },
                },
            ],
        }
    )
    validate_experiment_spec(spec)


def test_accepts_explicit_sweep_grid_and_cubic_reference_transform():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "migrated-lattice-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "Si"}},
                {
                    "id": "eos",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "lattice_constant_A",
                            "label": "Lattice parameter",
                            "unit": "Å",
                            "grid": {"values": [5.35, 5.38, 5.4, 5.43, 5.46, 5.5, 5.53]},
                        },
                        "apply": {
                            "target": "cell_scale",
                            "transform": "cubic_ratio_to_reference",
                            "reference": 5.43,
                        },
                    },
                },
            ],
        }
    )

    validate_experiment_spec(spec)


def test_accepts_vector_parameter_binding_for_coordinate_sweep():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "vector-coordinate-sweep",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {
                            "mode": "single_point",
                            "params": {"atom_index": 0},
                        },
                        "coordinate": {
                            "name": "displacement_A",
                            "label": "W atom [111] displacement",
                            "unit": "Å",
                            "grid": {"start": -1, "stop": 1, "step": 0.1},
                        },
                        "apply": {
                            "target": "displacement",
                            "transform": "scale_vector",
                            "vector": [0.5773502692, 0.5773502692, 0.5773502692],
                        },
                    },
                },
            ],
        }
    )

    validate_experiment_spec(spec)


def test_rejects_invalid_sweep_grid_and_visualization_trial():
    base = {
        "operation": {"mode": "single_point", "trials": 1},
        "coordinate": {
            "name": "x",
            "label": "X",
            "grid": {"start": 1, "stop": 1, "step": 0.1},
        },
        "apply": {"target": "cell_scale"},
    }
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "invalid-sweep-range",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {"id": "scan", "type": "SWEEP", "depends_on": "fetch", "params": base},
            ],
        }
    )
    with pytest.raises(ValueError, match="at least two points"):
        validate_experiment_spec(spec)

    spec.dag[1].params = {
        **base,
        "coordinate": {"name": "x", "label": "X", "grid": {"values": [0.9, 1.0]}},
        "visualization_trial": 1,
    }
    with pytest.raises(ValueError, match="visualization_trial"):
        validate_experiment_spec(spec)

    from atomforge.schemas import SweepGrid

    for payload, message in (
        ({"values": [1, 2], "start": 0}, "cannot include range fields"),
        ({"start": 0, "stop": 1}, "exactly one"),
        ({"start": 0, "stop": 1, "step": 2}, "at least two points"),
    ):
        with pytest.raises(ValidationError, match=message):
            SweepGrid.model_validate(payload)


def test_rejects_reserved_simulation_fields_inside_sweep_operation_params():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "misleading-sweep-evidence",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {
                            "mode": "single_point",
                            "trials": 1,
                            "params": {"mode": "pka", "trials": 99},
                        },
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
            ],
        }
    )

    with pytest.raises(ValueError, match="cannot redefine reserved fields"):
        validate_experiment_spec(spec)


def test_rejects_non_structural_sweep_parent_and_catalog_overcommitment():
    invalid_parent = ExperimentSpec.model_validate(
        {
            "experiment_id": "script-fed-sweep",
            "dag": [
                {
                    "id": "analysis",
                    "type": "SCRIPT",
                    "params": {
                        "script": "vacancy_disagreement_rank.py",
                        "output_metrics": {"scan_points": "count"},
                    },
                },
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "analysis",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "x",
                            "label": "X",
                            "grid": {"values": [0.9, 1.0]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
            ],
        }
    )
    with pytest.raises(ValueError, match="structural parent"):
        validate_experiment_spec(invalid_parent)

    sweep_node = {
        "type": "SWEEP",
        "depends_on": "fetch",
        "params": {
            "operation": {"mode": "single_point"},
            "coordinate": {
                "name": "x",
                "label": "X",
                "grid": {"values": [0.81 + index * 0.0003 for index in range(1_000)]},
            },
            "apply": {"target": "cell_scale"},
        },
    }
    over_budget = ExperimentSpec.model_validate(
        {
            "experiment_id": "too-many-visualizations",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                *[{"id": f"scan_{index}", **sweep_node} for index in range(11)],
            ],
        }
    )
    with pytest.raises(ValueError, match="visualization catalog items"):
        validate_experiment_spec(over_budget)


def test_rejects_aggregate_sweep_as_a_structural_parent_with_specific_diagnostic():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "sweep-fed-simulation",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "scan",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "scale",
                            "label": "Scale",
                            "grid": {"values": [0.99, 1.01]},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
                {
                    "id": "downstream",
                    "type": "SIMULATE",
                    "depends_on": "scan",
                    "params": {"mode": "single_point"},
                },
            ],
        }
    )

    with pytest.raises(ValueError, match="cannot consume aggregate SWEEP output"):
        validate_experiment_spec(spec)


def test_rejects_sweep_with_more_than_one_thousand_points():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "too-wide",
            "dag": [
                {"id": "fetch", "type": "FETCH", "params": {"element": "Si"}},
                {
                    "id": "sweep",
                    "type": "SWEEP",
                    "depends_on": "fetch",
                    "params": {
                        "operation": {"mode": "single_point"},
                        "coordinate": {
                            "name": "x",
                            "label": "X",
                            "grid": {"start": 0, "stop": 10, "step": 0.001},
                        },
                        "apply": {"target": "cell_scale"},
                    },
                },
            ],
        }
    )
    with pytest.raises(ValueError, match="at most 1000"):
        validate_experiment_spec(spec)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("index", 7, "ordered and contiguous"),
        ("value", 999, "declared grid"),
        ("applied_value", -5, "apply contract"),
    ],
)
def test_sweep_result_rejects_points_that_contradict_its_contract(field, value, message):
    from atomforge.schemas import SweepResult

    base = {
        "coordinate": {"name": "x", "label": "X", "grid": {"values": [1.0, 2.0]}},
        "apply": {"target": "cell_scale"},
        "points": [
            {
                "id": f"scan-point-{index:04d}",
                "index": index,
                "value": value,
                "applied_value": value,
                "simulation_params": {"cell_scale": value},
                "status": "FAILED",
                "error": "fixture failure",
            }
            for index, value in enumerate((1.0, 2.0))
        ],
    }
    SweepResult.model_validate(base)

    invalid = copy.deepcopy(base)
    invalid["points"][1][field] = value
    with pytest.raises(ValueError, match=message):
        SweepResult.model_validate(invalid)


def test_runtime_source_preflight_is_explicit_and_rejects_invalid_source(tmp_path):
    source_root = tmp_path / "atomforge"
    source_root.mkdir()
    (source_root / "simulator.py").write_bytes(b"def setup():\n    annotation: tuple\x1b\n")

    with pytest.raises(ValueError, match="Runtime source preflight failed.*simulator.py"):
        validate_runtime_sources(source_root)


def script_spec(script: str, **params) -> ExperimentSpec:
    return ExperimentSpec.model_validate(
        {
            "experiment_id": "script-validation",
            "dag": [
                {
                    "id": "script",
                    "type": "SCRIPT",
                    "params": {
                        "script": script,
                        "output_metrics": {"value": "dimensionless"},
                        **params,
                    },
                }
            ],
        }
    )


def test_rejects_unsafe_or_missing_script_source():
    with pytest.raises(ValueError, match="safe relative .py path"):
        validate_experiment_spec(script_spec("../secrets.py"))
    with pytest.raises(ValueError, match="does not exist"):
        validate_experiment_spec(script_spec("not_a_real_script.py"))


def test_rejects_reserved_or_hidden_script_runtime_arguments():
    cases = (
        (
            "vacancy_disagreement_rank.py",
            {"fixture_results": {"result": 1}},
            "reserved test-only",
        ),
        ("berger_vacancy_mace.py", {"runtime": "physics_gpu"}, "execution_profile"),
    )
    for script, arguments, message in cases:
        with pytest.raises(ValueError, match=message):
            validate_experiment_spec(script_spec(script, arguments=arguments))


def test_physics_profile_validates_contract_not_source_tokens():
    validate_experiment_spec(
        script_spec(
            "vacancy_disagreement_rank.py",
            execution_profile="physics_gpu",
        )
    )


def test_pka_requires_explicit_unvalidated_demo_flag():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "unsafe-pka",
            "dag": [
                {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "pka",
                    "type": "SIMULATE",
                    "depends_on": "f1",
                    "params": {"mode": "pka", "trials": 1},
                },
            ],
        }
    )
    with pytest.raises(ValueError, match="PKA is blocked"):
        validate_experiment_spec(spec)


def test_rejects_multi_trial_structure_consumption():
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "ambiguous-ensemble-lineage",
            "dag": [
                {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "relax",
                    "type": "SIMULATE",
                    "depends_on": "f1",
                    "params": {"mode": "relax", "trials": 2},
                },
                {
                    "id": "probe",
                    "type": "SIMULATE",
                    "depends_on": "relax",
                    "params": {"mode": "single_point", "trials": 1},
                },
            ],
        }
    )
    with pytest.raises(ValueError, match="explicit ensemble selector"):
        validate_experiment_spec(spec)


def test_rejects_dependency_cycles():
    spec = ExperimentSpec(
        experiment_id="cyclic",
        dag=[
            DagNode(id="a1", type="ALLOY", depends_on="s1"),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="a1",
                params={
                    "mode": "pka",
                    "trials": 1,
                    "allow_unvalidated_short_range": True,
                },
            ),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_experiment_spec(spec)


def test_rejects_unimplemented_node_types_at_schema_boundary():
    with pytest.raises(ValidationError, match="ANALYZE"):
        ExperimentSpec.model_validate(
            {"experiment_id": "unsupported-node", "dag": [{"id": "a", "type": "ANALYZE"}]}
        )


def test_rejects_invalid_alloy_seed_and_dopant_budget():
    invalid_seed = ExperimentSpec(
        experiment_id="invalid-seed",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(id="a1", type="ALLOY", depends_on="f1", params={"seed": "random"}),
        ],
    )
    with pytest.raises(ValueError, match="seed"):
        validate_experiment_spec(invalid_seed)

    invalid_dopants = ExperimentSpec(
        experiment_id="invalid-dopants",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="a1",
                type="ALLOY",
                depends_on="f1",
                params={"supercell": [3, 3, 3], "dopants": {"Cr": 0.75, "Ni": 0.5}},
            ),
        ],
    )
    with pytest.raises(ValueError, match="sum to <= 1"):
        validate_experiment_spec(invalid_dopants)


def test_rejects_ambiguous_vacancy_and_dopant_transform():
    ambiguous = ExperimentSpec(
        experiment_id="ambiguous-alloy",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="a1",
                type="ALLOY",
                depends_on="f1",
                params={"vacancy": True, "dopants": {"Ni": 0.1}},
            ),
        ],
    )

    with pytest.raises(ValueError, match="cannot combine vacancy=True"):
        validate_experiment_spec(ambiguous)


def test_rejects_unknown_dopant_symbol():
    invalid = ExperimentSpec(
        experiment_id="unknown-element",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="a1",
                type="ALLOY",
                depends_on="f1",
                params={"dopants": {"NotAnElement": 0.1}},
            ),
        ],
    )

    with pytest.raises(ValueError, match="unknown chemical symbol"):
        validate_experiment_spec(invalid)


def test_validates_explicit_decision_node():
    spec = ExperimentSpec(
        experiment_id="decision-contract",
        decision_node_id="analysis",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="analysis",
                type="SCRIPT",
                depends_on="f1",
                params={
                    "script": "vacancy_disagreement_rank.py",
                    "output_metrics": {"value": "dimensionless"},
                },
            ),
        ],
    )

    validate_experiment_spec(spec)


def test_rejects_unknown_hypothesis_target_and_invalid_metric():
    unknown = ExperimentSpec.model_validate(
        {
            "experiment_id": "unknown-target",
            "dag": [{"id": "f1", "type": "FETCH", "params": {"element": "W"}}],
            "hypotheses": [
                {
                    "id": "check",
                    "target_node": "missing",
                    "metric": "n_defects",
                    "assertion": "target.n_defects >= 0",
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="unknown node 'missing'"):
        validate_experiment_spec(unknown)

    invalid_metric = ExperimentSpec.model_validate(
        {
            "experiment_id": "invalid-metric",
            "dag": [
                {"id": "f1", "type": "FETCH", "params": {"element": "W"}},
                {
                    "id": "s1",
                    "type": "SIMULATE",
                    "depends_on": "f1",
                    "params": {"mode": "relax"},
                },
            ],
            "hypotheses": [
                {
                    "id": "check",
                    "target_node": "s1",
                    "metric": "n_defects",
                    "assertion": "target.n_defects >= 0",
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="metric 'n_defects'.*mode 'relax'"):
        validate_experiment_spec(invalid_metric)


def test_default_hypothesis_uses_emitted_pka_metric():
    hypothesis = Hypothesis(id="check", target_node="s1")
    assert hypothesis.metric == "n_defects"
    assert hypothesis.assertion == "target.n_defects < 50"


def test_boolean_hypotheses_fail_fast_until_reduction_contract_exists():
    spec = ExperimentSpec(
        experiment_id="nvt-boolean-hypothesis",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="nvt",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "nvt"},
            ),
        ],
        hypotheses=[
            Hypothesis(
                id="stable",
                target_node="nvt",
                metric="stable",
                assertion="target.stable == True",
            )
        ],
    )

    with pytest.raises(ValueError, match="boolean hypothesis reductions are not supported"):
        validate_experiment_spec(spec)


def test_rejects_unbounded_trials_before_execution():
    spec = ExperimentSpec(
        experiment_id="too-many-trials",
        dag=[
            DagNode(id="f1", type="FETCH", params={"element": "W"}),
            DagNode(
                id="s1",
                type="SIMULATE",
                depends_on="f1",
                params={"mode": "pka", "trials": 101},
            ),
        ],
    )
    with pytest.raises(ValueError, match="trials must be <= 100"):
        validate_experiment_spec(spec)
