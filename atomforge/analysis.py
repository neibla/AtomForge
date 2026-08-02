from __future__ import annotations

from typing import Any

from atomforge.schemas import ExperimentSpec, ResultsGraph
from atomforge.serialization import to_jsonable


def _summary_value(value: Any) -> Any:
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    if isinstance(value, dict):
        return {"type": "mapping", "count": len(value)}
    return value


def _data_summary(value: Any) -> dict[str, Any]:
    value = to_jsonable(value)
    if not isinstance(value, dict):
        return {"value": _summary_value(value)} if value is not None else {}
    return {str(key): _summary_value(item) for key, item in value.items()}


def build_analysis_payload(
    spec: ExperimentSpec,
    results: ResultsGraph,
    trial_metrics_by_node: dict[str, list[dict[str, Any]]],
    trial_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an experiment-neutral index of recorded node evidence."""
    trial_data = trial_data or {}
    node_ids = sorted((node.id for node in spec.dag), key=len, reverse=True)
    scoped_metrics: dict[str, dict[str, Any]] = {node_id: {} for node_id in node_ids}
    unscoped_metrics: dict[str, Any] = {}
    for name, metric in results.metrics.items():
        payload = to_jsonable(metric)
        node_id = next(
            (candidate for candidate in node_ids if name.startswith(f"{candidate}_")),
            None,
        )
        if node_id is None:
            unscoped_metrics[name] = payload
        else:
            scoped_metrics[node_id][name] = payload

    nodes = []
    for node in spec.dag:
        trials = to_jsonable(trial_metrics_by_node.get(node.id, []))
        nodes.append(
            {
                "node_id": node.id,
                "type": node.type,
                "dependencies": node.dependencies,
                "parameters": to_jsonable(node.params),
                "metrics": scoped_metrics[node.id],
                "trials": trials,
                "trial_count": len(trials),
                "data_summary": _data_summary(trial_data.get(node.id)),
                "error": results.errors.get(node.id),
            }
        )

    return {
        "contract_version": "v1",
        "experiment_id": spec.experiment_id,
        "nodes": nodes,
        "unscoped_metrics": unscoped_metrics,
        "scientific_decision_source": "script_results",
    }
