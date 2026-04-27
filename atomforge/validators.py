from __future__ import annotations

from atomforge.schemas import (
    CompressionParams,
    ExperimentSpec,
    MeltParams,
    PKAParams,
    QuantumParams,
    RelaxParams,
)

_SIMULATION_MODES = {"pka", "relax", "compression", "two_phase_melt"}


def validate_experiment_spec(spec: ExperimentSpec) -> None:
    """Fail-fast validation for DAG shape and mode-specific params."""
    if not spec.dag:
        raise ValueError("ExperimentSpec.dag must contain at least one node.")

    node_ids = [node.id for node in spec.dag]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("DAG node ids must be unique.")

    node_set = set(node_ids)
    for node in spec.dag:
        deps = (
            node.depends_on
            if isinstance(node.depends_on, list)
            else ([node.depends_on] if node.depends_on else [])
        )
        for dep in deps:
            if dep not in node_set:
                raise ValueError(f"Node '{node.id}' depends on unknown node '{dep}'.")
            if dep == node.id:
                raise ValueError(f"Node '{node.id}' cannot depend on itself.")

        if node.type == "FETCH":
            element = node.params.get("element")
            if not isinstance(element, str) or not element.strip():
                raise ValueError(f"FETCH node '{node.id}' requires non-empty 'element' string.")

        elif node.type == "ALLOY":
            if len(deps) != 1:
                raise ValueError(f"ALLOY node '{node.id}' must depend on exactly one parent node.")
            supercell = node.params.get("supercell", [3, 3, 3])
            if (
                not isinstance(supercell, list)
                or len(supercell) != 3
                or any(not isinstance(v, int) or v <= 0 for v in supercell)
            ):
                raise ValueError(
                    f"ALLOY node '{node.id}' requires 'supercell' as 3 positive integers."
                )
            dopants = node.params.get("dopants", {})
            if not isinstance(dopants, dict):
                raise ValueError(f"ALLOY node '{node.id}' requires 'dopants' to be an object.")

        elif node.type == "SIMULATE":
            if len(deps) != 1:
                raise ValueError(f"SIMULATE node '{node.id}' must depend on exactly one parent node.")
            mode = node.params.get("mode")
            if mode not in _SIMULATION_MODES:
                raise ValueError(
                    f"SIMULATE node '{node.id}' has invalid mode '{mode}'. "
                    f"Allowed: {sorted(_SIMULATION_MODES)}"
                )
            trials = node.params.get("trials", 1)
            if not isinstance(trials, int) or trials <= 0:
                raise ValueError(f"SIMULATE node '{node.id}' requires 'trials' to be a positive int.")
            _validate_mode_params(node.id, mode, node.params)

        elif node.type == "SOLVE_QUANTUM":
            if len(deps) != 1:
                raise ValueError(
                    f"SOLVE_QUANTUM node '{node.id}' must depend on exactly one parent node."
                )
            QuantumParams.model_validate(node.params)


def _validate_mode_params(node_id: str, mode: str, params: dict) -> None:
    try:
        if mode == "pka":
            PKAParams.model_validate(params)
        elif mode == "relax":
            RelaxParams.model_validate(params)
        elif mode == "compression":
            CompressionParams.model_validate(params)
        elif mode == "two_phase_melt":
            MeltParams.model_validate(params)
    except Exception as exc:
        raise ValueError(f"SIMULATE node '{node_id}' invalid params for mode '{mode}': {exc}") from exc
