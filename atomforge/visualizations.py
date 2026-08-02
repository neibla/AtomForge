import hashlib
from typing import Any

from atomforge.contracts import SimulationMode
from atomforge.schemas import (
    AtomisticVisualization,
    AtomisticVisualizationData,
    ExperimentSpec,
    ScriptResult,
    SweepParams,
    SweepResult,
    VisualizationCatalog,
    VisualizationSpec,
)


def build_visualization_catalog(
    spec: ExperimentSpec,
    *,
    trial_data: dict[str, Any],
    node_results: dict[str, Any],
) -> VisualizationCatalog:
    visualizations: list[VisualizationSpec] = []
    scan_metadata = _scan_parameter_metadata(spec)

    for node in spec.dag:
        visualizations.extend(
            _visualizations_for_node(
                node,
                trial_data=trial_data,
                node_results=node_results,
                scan_metadata=scan_metadata,
            )
        )

    return VisualizationCatalog(
        experiment_id=spec.experiment_id,
        visualizations=visualizations,
    )


def _visualizations_for_node(
    node: Any,
    *,
    trial_data: dict[str, Any],
    node_results: dict[str, Any],
    scan_metadata: dict[str, dict[str, Any]],
) -> list[VisualizationSpec]:
    if node.type == "SIMULATE":
        atomistic = _atomistic_visualization(
            node.id,
            trial_data.get(node.id),
            node.params.get("mode"),
            scan_metadata.get(node.id),
        )
        return [atomistic] if atomistic is not None else []
    if node.type == "SWEEP":
        result = node_results.get(node.id)
        return _sweep_visualizations(node, result) if isinstance(result, SweepResult) else []
    if node.type == "SCRIPT":
        result = node_results.get(node.id)
        return _script_visualizations(node.id, result) if isinstance(result, ScriptResult) else []
    return []


def _sweep_visualizations(node: Any, result: SweepResult) -> list[VisualizationSpec]:
    sweep = SweepParams.model_validate(node.params)
    values = [point.value for point in result.points]
    signed = bool(values) and min(values) < 0 < max(values)
    visualizations: list[VisualizationSpec] = []
    for point in result.points:
        if point.status != "COMPLETED" or not point.ensemble:
            continue
        metadata = {
            "scan_parameter_series": node.id,
            "scan_parameter_label": result.coordinate.label,
            "scan_parameter_value": point.value,
            "scan_parameter_unit": result.coordinate.unit,
            "scan_parameter_signed": signed,
            "sweep_point_index": point.index,
            "sweep_applied_value": point.applied_value,
            "sweep_visualization_trial": sweep.visualization_trial,
        }
        atomistic = _atomistic_visualization(
            node.id,
            point.ensemble[sweep.visualization_trial],
            sweep.operation.mode,
            metadata,
            visualization_id=f"{point.id}-atomistic",
            title=(f"{result.coordinate.label} {point.value:g} {result.coordinate.unit}").strip(),
        )
        if atomistic is not None:
            visualizations.append(atomistic)
    return visualizations


def _script_visualizations(node_id: str, result: ScriptResult) -> list[VisualizationSpec]:
    visualizations: list[VisualizationSpec] = []
    for visualization in result.visualizations:
        payload = visualization.model_dump(mode="json")
        payload.update(
            id=_namespaced_id(node_id, visualization.id),
            source_node=node_id,
        )
        visualizations.append(visualization.__class__.model_validate(payload))
    return visualizations


def _atomistic_visualization(
    node_id: str,
    trial: Any,
    simulation_mode: SimulationMode | None,
    presentation_metadata: dict[str, Any] | None = None,
    *,
    visualization_id: str | None = None,
    title: str | None = None,
) -> AtomisticVisualization | None:
    if trial is None:
        return None
    positions = _field(trial, "positions") or _field(trial, "final_positions")
    numbers = _field(trial, "atomic_numbers")
    if not positions or not numbers or len(positions) != len(numbers):
        return None

    trial_metadata = _field(trial, "metadata")
    metadata = dict(trial_metadata) if isinstance(trial_metadata, dict) else {}
    metadata.update(presentation_metadata or {})

    data = AtomisticVisualizationData(
        positions=positions,
        numbers=numbers,
        metadata=metadata or None,
        initial_positions=_field(trial, "initial_positions"),
        final_positions=_field(trial, "final_positions"),
        energies=_field(trial, "energies"),
        cell=_field(trial, "cell"),
        pbc=_field(trial, "pbc"),
        trajectory=_field(trial, "trajectory"),
        vacancy_positions=_field(trial, "vacancy_positions"),
        interstitial_positions=_field(trial, "interstitial_positions"),
        n_defects=_field(trial, "n_defects"),
        interstitials=_field(trial, "interstitials"),
        pka_index=_field(trial, "pka_index"),
        frame_metrics=_field(trial, "frame_metrics"),
        simulation_mode=simulation_mode,
    )
    return AtomisticVisualization(
        id=_namespaced_id(node_id, visualization_id or "atomistic"),
        title=title or f"{node_id} atomic structure",
        description="Atomic positions and trajectory emitted by the simulation node.",
        source_node=node_id,
        data=data,
    )


def _scan_parameter_metadata(spec: ExperimentSpec) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for node in spec.dag:
        if node.type != "SCRIPT":
            continue
        arguments = node.params.get("arguments")
        if not isinstance(arguments, dict):
            continue
        scan_nodes = arguments.get("scan_nodes")
        if not isinstance(scan_nodes, list) or len(scan_nodes) < 2:
            continue

        parsed: list[tuple[str, str, float]] = []
        for point in scan_nodes:
            if not isinstance(point, dict) or not isinstance(point.get("node_id"), str):
                continue
            parameter = next(
                (
                    (key, value)
                    for key, value in point.items()
                    if key != "node_id"
                    and isinstance(value, int | float)
                    and not isinstance(value, bool)
                ),
                None,
            )
            if parameter is None:
                continue
            key, value = parameter
            parsed.append((point["node_id"], key, float(value)))
        if len(parsed) < 2:
            continue

        values = [value for _, _, value in parsed]
        signed = min(values) < 0 < max(values)
        coordinate_label = arguments.get("coordinate_label")
        for node_id, key, value in parsed:
            label = (
                coordinate_label
                if isinstance(coordinate_label, str) and coordinate_label.strip()
                else key.removesuffix("_A").replace("_", " ").capitalize()
            )
            unit = "Å" if key.endswith("_A") else ""
            metadata[node_id] = {
                "scan_parameter_series": node.id,
                "scan_parameter_label": label,
                "scan_parameter_value": value,
                "scan_parameter_unit": unit,
                "scan_parameter_signed": signed,
            }
    return metadata


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _namespaced_id(node_id: str, visualization_id: str) -> str:
    combined = f"{node_id}-{visualization_id}"
    if len(combined) <= 100:
        return combined
    digest = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return f"{combined[:83]}-{digest}"
