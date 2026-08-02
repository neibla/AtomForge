import math
from pathlib import Path, PurePosixPath

from atomforge.contracts import (
    MAX_SIMULATION_TRIALS,
    MAX_VISUALIZATION_CATALOG_ITEMS,
    NODE_TYPES,
    RESERVED_SCRIPT_ARGUMENTS,
    SCRIPT_EXECUTION_PROFILE_NAMES,
    SIMULATION_MODES,
    SWEEP_METRIC_NAMES,
)
from atomforge.execution.script_runner import resolve_script_path
from atomforge.execution.script_sources import script_root
from atomforge.schemas import (
    DagNode,
    ExperimentSpec,
    SweepParams,
)
from atomforge.simulation_modes import MODE_CONTRACTS, validate_mode_params
from atomforge.sweeps import bind_sweep_point, parameter_is_set

_MAX_SUPERCELL_VOLUME = 4096
_PACKAGE_ROOT = Path(__file__).resolve().parent


def validate_runtime_sources(source_root: Path | None = None) -> None:
    """Compile checked-in Python sources as an explicit preflight operation."""

    root = (source_root or _PACKAGE_ROOT).resolve()
    if not root.is_dir():
        raise ValueError(f"Runtime source root does not exist: {root}")
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (SyntaxError, UnicodeError) as exc:
            if isinstance(exc, SyntaxError):
                location = f"{path}:{exc.lineno or '?'}:{exc.offset or '?'}"
                detail = exc.msg
            else:
                location = str(path)
                detail = str(exc)
            raise ValueError(
                "Runtime source preflight failed at "
                f"{location}: {detail}. Repair the checked-in Python source and retry."
            ) from exc


def validate_experiment_spec(
    spec: ExperimentSpec,
    *,
    source_root: Path | None = None,
) -> None:
    """Fail-fast validation for DAG shape and mode-specific parameters."""

    node_ids = [node.id for node in spec.dag]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("DAG node ids must be unique.")

    node_set = set(node_ids)
    nodes = {node.id: node for node in spec.dag}
    active_script_root = (source_root or script_root()).resolve()

    _validate_decision_node(spec.decision_node_id, nodes)
    _validate_nodes(spec.dag, node_set, active_script_root)
    _validate_structural_dependencies(spec.dag, nodes)

    _validate_acyclic(spec)
    _validate_hypotheses(spec)
    _validate_visualization_budget(spec)


def _validate_decision_node(
    decision_node_id: str | None,
    nodes: dict[str, DagNode],
) -> None:
    if decision_node_id is None:
        return
    decision_node = nodes.get(decision_node_id)
    if decision_node is None:
        raise ValueError(f"decision_node_id '{decision_node_id}' does not reference a DAG node.")
    if decision_node.type != "SCRIPT":
        raise ValueError(f"decision_node_id '{decision_node_id}' must reference a SCRIPT node.")


def _validate_nodes(
    dag: list[DagNode],
    node_set: set[str],
    source_root: Path,
) -> None:
    for node in dag:
        if node.type not in NODE_TYPES:
            raise ValueError(f"Node '{node.id}' has unsupported node type '{node.type}'.")
        _validate_dependencies(node, node_set)
        if node.type == "FETCH":
            _validate_fetch(node.id, node.params)
        elif node.type == "ALLOY":
            _validate_alloy(node.id, node.dependencies, node.params)
        elif node.type == "SIMULATE":
            _validate_simulation(node.id, node.dependencies, node.params)
        elif node.type == "SWEEP":
            _validate_sweep(node.id, node.dependencies, node.params)
        elif node.type == "SCRIPT":
            _validate_script(node.id, node.params, source_root)


def _validate_dependencies(node: DagNode, node_set: set[str]) -> None:
    for dependency in node.dependencies:
        if dependency not in node_set:
            raise ValueError(f"Node '{node.id}' depends on unknown node '{dependency}'.")
        if dependency == node.id:
            raise ValueError(f"Node '{node.id}' cannot depend on itself.")


def _validate_structural_dependencies(
    dag: list[DagNode],
    nodes: dict[str, DagNode],
) -> None:
    structural_types = {"ALLOY", "SIMULATE", "SWEEP"}
    for node in dag:
        if node.type not in structural_types:
            continue
        for dependency in node.dependencies:
            parent = nodes[dependency]
            if parent.type == "SWEEP":
                raise ValueError(
                    f"Node '{node.id}' cannot consume aggregate SWEEP output from "
                    f"'{parent.id}' as a structure. Use a SCRIPT node or an explicit selector."
                )
            if parent.type not in {"FETCH", "ALLOY", "SIMULATE"}:
                raise ValueError(
                    f"Node '{node.id}' requires a structural parent; '{parent.id}' "
                    f"emits {parent.type} output."
                )
            if parent.type == "SIMULATE" and int(parent.params.get("trials", 1)) > 1:
                raise ValueError(
                    f"Node '{node.id}' cannot consume multi-trial structure output from "
                    f"'{parent.id}' without an explicit ensemble selector."
                )


def _validate_visualization_budget(spec: ExperimentSpec) -> None:
    sweep_frames = sum(
        len(SweepParams.model_validate(node.params).coordinate.grid.materialize())
        for node in spec.dag
        if node.type == "SWEEP"
    )
    script_budget = sum(node.type == "SCRIPT" for node in spec.dag) * 32
    simulation_frames = sum(
        node.type == "SIMULATE" and int(node.params.get("trials", 1)) == 1 for node in spec.dag
    )
    total = sweep_frames + script_budget + simulation_frames
    if total > MAX_VISUALIZATION_CATALOG_ITEMS:
        raise ValueError(
            "Experiment can emit at most "
            f"{MAX_VISUALIZATION_CATALOG_ITEMS} visualization catalog items; "
            f"declared nodes require a budget of {total}."
        )


def _validate_fetch(node_id: str, params: dict) -> None:
    element = params.get("element")
    structure_path = params.get("structure_path")
    has_element = isinstance(element, str) and bool(element.strip())
    has_path = isinstance(structure_path, str) and bool(structure_path.strip())
    if has_element == has_path:
        raise ValueError(
            f"FETCH node '{node_id}' requires exactly one of non-empty 'element' "
            "or 'structure_path'."
        )
    if has_path:
        path = PurePosixPath(structure_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"FETCH node '{node_id}' structure_path must be a relative safe path.")


def _validate_alloy(node_id: str, deps: list[str], params: dict) -> None:
    if len(deps) != 1:
        raise ValueError(f"ALLOY node '{node_id}' must depend on exactly one parent node.")
    supercell = params.get("supercell", [3, 3, 3])
    if (
        not isinstance(supercell, list)
        or len(supercell) != 3
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in supercell
        )
    ):
        raise ValueError(f"ALLOY node '{node_id}' requires 'supercell' as 3 positive integers.")
    if math.prod(supercell) > _MAX_SUPERCELL_VOLUME:
        raise ValueError(
            f"ALLOY node '{node_id}' supercell volume must be <= {_MAX_SUPERCELL_VOLUME}."
        )

    dopants = params.get("dopants", {})
    if not isinstance(dopants, dict):
        raise ValueError(f"ALLOY node '{node_id}' requires 'dopants' to be an object.")
    vacancy = params.get("vacancy", False)
    if not isinstance(vacancy, bool):
        raise ValueError(f"ALLOY node '{node_id}' vacancy must be a boolean.")
    if vacancy and dopants:
        raise ValueError(
            f"ALLOY node '{node_id}' cannot combine vacancy=True with dopants; "
            "declare separate transformations instead."
        )
    from ase.data import atomic_numbers

    total_concentration = 0.0
    for element, concentration in dopants.items():
        if not isinstance(element, str) or not element.strip():
            raise ValueError(f"ALLOY node '{node_id}' dopant symbols must be strings.")
        if element not in atomic_numbers or atomic_numbers[element] <= 0:
            raise ValueError(f"ALLOY node '{node_id}' has unknown chemical symbol '{element}'.")
        if (
            not isinstance(concentration, int | float)
            or isinstance(concentration, bool)
            or not math.isfinite(concentration)
            or not 0 <= concentration <= 1
        ):
            raise ValueError(
                f"ALLOY node '{node_id}' dopant concentrations must be between 0 and 1."
            )
        total_concentration += concentration
    if total_concentration > 1:
        raise ValueError(f"ALLOY node '{node_id}' dopant concentrations must sum to <= 1.")

    seed = params.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError(f"ALLOY node '{node_id}' requires 'seed' to be a non-negative integer.")


def _validate_simulation(node_id: str, deps: list[str], params: dict) -> None:
    if len(deps) != 1:
        raise ValueError(f"SIMULATE node '{node_id}' must depend on exactly one parent node.")
    mode = params.get("mode")
    if mode not in SIMULATION_MODES:
        raise ValueError(
            f"SIMULATE node '{node_id}' has invalid mode '{mode}'. "
            f"Allowed: {sorted(SIMULATION_MODES)}"
        )
    trials = params.get("trials", 1)
    if not isinstance(trials, int) or isinstance(trials, bool) or trials <= 0:
        raise ValueError(f"SIMULATE node '{node_id}' requires 'trials' to be a positive int.")
    if trials > MAX_SIMULATION_TRIALS:
        raise ValueError(f"SIMULATE node '{node_id}' trials must be <= {MAX_SIMULATION_TRIALS}.")
    _validate_mode_params(node_id, mode, params)


def _validate_sweep(node_id: str, deps: list[str], raw_params: dict) -> None:
    if len(deps) != 1:
        raise ValueError(f"SWEEP node '{node_id}' must depend on exactly one parent node.")
    try:
        params = SweepParams.model_validate(raw_params)
    except Exception as exc:
        raise ValueError(f"SWEEP node '{node_id}' has invalid params: {exc}") from exc

    if parameter_is_set(params.operation.params, params.apply.target):
        raise ValueError(
            f"SWEEP node '{node_id}' target '{params.apply.target}' must not also be set "
            "in operation.params."
        )
    for value in params.coordinate.grid.materialize():
        binding = bind_sweep_point(
            operation_params=params.operation.params,
            target=params.apply.target,
            value=value,
            apply_value=params.apply.apply,
            mode=params.operation.mode,
            trials=params.operation.trials,
        )
        _validate_simulation(
            f"{node_id}[{params.coordinate.name}={value:g}]",
            deps,
            binding.simulation_params,
        )


def _validate_script(node_id: str, params: dict, source_root: Path) -> None:
    allowed_params = {
        "script",
        "arguments",
        "output_metrics",
        "timeout_seconds",
        "execution_profile",
    }
    unexpected = set(params) - allowed_params
    if unexpected:
        raise ValueError(f"SCRIPT node '{node_id}' has unsupported params: {sorted(unexpected)}")

    script = params.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError(f"SCRIPT node '{node_id}' requires a script path.")
    try:
        resolve_script_path(script, source_root=source_root)
    except ValueError as exc:
        raise ValueError(f"SCRIPT node '{node_id}' source is invalid: {exc}") from exc

    execution_profile = params.get("execution_profile", "analysis")
    if execution_profile not in SCRIPT_EXECUTION_PROFILE_NAMES:
        raise ValueError(
            f"SCRIPT node '{node_id}' execution_profile must be one of "
            f"{sorted(SCRIPT_EXECUTION_PROFILE_NAMES)}."
        )

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError(f"SCRIPT node '{node_id}' arguments must be an object.")
    reserved = RESERVED_SCRIPT_ARGUMENTS.intersection(arguments)
    private_test_keys = {key for key in arguments if str(key).startswith("_test")}
    if reserved or private_test_keys:
        blocked = sorted(reserved | private_test_keys)
        raise ValueError(
            f"SCRIPT node '{node_id}' contains reserved test-only arguments: {blocked}"
        )
    if "runtime" in arguments:
        raise ValueError(
            f"SCRIPT node '{node_id}' must declare execution_profile in params; "
            "arguments.runtime is not allowed."
        )

    output_metrics = params.get("output_metrics")
    if not isinstance(output_metrics, dict) or not output_metrics:
        raise ValueError(f"SCRIPT node '{node_id}' requires a non-empty output_metrics object.")
    for metric_name, unit in output_metrics.items():
        if (
            not isinstance(metric_name, str)
            or not metric_name.strip()
            or not metric_name.replace("_", "a").isalnum()
            or not isinstance(unit, str)
            or not unit.strip()
        ):
            raise ValueError(
                f"SCRIPT node '{node_id}' output_metrics must map metric names to units."
            )

    timeout_seconds = params.get("timeout_seconds", 300)
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 3600
    ):
        raise ValueError(f"SCRIPT node '{node_id}' timeout_seconds must be between 1 and 3600.")


def _validate_acyclic(spec: ExperimentSpec) -> None:
    dependencies = {node.id: node.dependencies for node in spec.dag}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError(f"DAG contains a dependency cycle involving node '{node_id}'.")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency_id in dependencies[node_id]:
            visit(dependency_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in dependencies:
        visit(node_id)


def _validate_mode_params(node_id: str, mode: str, params: dict) -> None:
    try:
        validate_mode_params(mode, params)
    except Exception as exc:
        raise ValueError(
            f"SIMULATE node '{node_id}' invalid params for mode '{mode}': {exc}"
        ) from exc


def _validate_hypotheses(spec: ExperimentSpec) -> None:
    hypothesis_ids = [hypothesis.id for hypothesis in spec.hypotheses]
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        raise ValueError("Hypothesis ids must be unique.")

    nodes = {node.id: node for node in spec.dag}
    for hypothesis in spec.hypotheses:
        target = nodes.get(hypothesis.target_node)
        if target is None:
            raise ValueError(
                f"Hypothesis '{hypothesis.id}' targets unknown node '{hypothesis.target_node}'."
            )
        if target.type == "SCRIPT":
            output_metrics = target.params.get("output_metrics", {})
            if hypothesis.metric not in output_metrics:
                raise ValueError(
                    f"Hypothesis '{hypothesis.id}' uses metric '{hypothesis.metric}', "
                    f"which is not declared by SCRIPT node '{target.id}'. "
                    f"Allowed: {sorted(output_metrics)}"
                )
            continue
        if target.type == "SWEEP":
            if hypothesis.metric not in SWEEP_METRIC_NAMES:
                raise ValueError(
                    f"Hypothesis '{hypothesis.id}' uses metric '{hypothesis.metric}', "
                    f"which is not emitted by SWEEP node '{target.id}'. "
                    f"Allowed: {sorted(SWEEP_METRIC_NAMES)}"
                )
            continue
        if target.type != "SIMULATE":
            raise ValueError(
                f"Hypothesis '{hypothesis.id}' must target a SIMULATE node, not '{target.type}'."
            )
        mode = target.params["mode"]
        definition = MODE_CONTRACTS[mode]
        if hypothesis.metric not in definition.metrics:
            raise ValueError(
                f"Hypothesis '{hypothesis.id}' uses metric '{hypothesis.metric}', "
                f"which is not emitted by mode '{mode}'. "
                f"Allowed: {sorted(definition.metrics)}"
            )
        if hypothesis.metric in definition.boolean_metrics:
            raise ValueError(
                f"Hypothesis '{hypothesis.id}' targets boolean metric '{hypothesis.metric}', "
                "but boolean hypothesis reductions are not supported yet. Publish a numeric "
                "decision metric from a SCRIPT node instead."
            )
