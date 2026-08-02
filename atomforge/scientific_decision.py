from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atomforge.schemas import ScientificDecision


def decision_from_script_data(data: Mapping[str, Any]) -> ScientificDecision | None:
    value = data.get("scientific_decision")
    if not isinstance(value, Mapping):
        return None
    return ScientificDecision.model_validate(value)


def decision_from_script_results(
    script_results: Mapping[str, Any] | None,
    *,
    decision_node_id: str | None = None,
    node_order: list[str] | tuple[str, ...] | None = None,
) -> ScientificDecision | None:
    if not script_results:
        return None

    if decision_node_id is not None:
        candidates = [script_results.get(decision_node_id)]
    else:
        # Mapping insertion order is an execution detail for the asynchronous
        # orchestrator. Fall back to specification order (or stable ID order for
        # direct callers) so scheduling cannot select the scientific conclusion.
        ordered_ids = list(node_order) if node_order is not None else sorted(script_results)
        candidates = [
            script_results[node_id]
            for node_id in reversed(ordered_ids)
            if node_id in script_results
        ]

    for result in candidates:
        if not isinstance(result, Mapping):
            continue
        data = result.get("data")
        if not isinstance(data, Mapping):
            continue
        decision = decision_from_script_data(data)
        if decision is not None:
            return decision
    return None


def blocked_decision_from_execution(errors: Mapping[str, str]) -> ScientificDecision:
    """Preserve failed execution evidence when the decision SCRIPT was blocked."""

    failed_nodes = ", ".join(sorted(errors)) or "an upstream node"
    return ScientificDecision(
        outcome="BLOCKED",
        calibration={
            "status": "INSUFFICIENT_EVIDENCE",
            "accepted_case_count": 0,
            "minimum_case_count": 0,
        },
        scope="Execution evidence only; no downstream scientific decision was produced.",
        headline="Scientific interpretation was blocked by failed execution.",
        limitations=[
            f"The decision-producing analysis did not complete because {failed_nodes} failed."
        ],
        quality_checks=[],
    )


def decision_from_bundle(bundle: Mapping[str, Any]) -> ScientificDecision | None:
    direct = bundle.get("scientific_decision")
    if isinstance(direct, Mapping):
        return ScientificDecision.model_validate(direct)
    script_results = bundle.get("script_results")
    spec = bundle.get("spec")
    decision_node_id = (
        spec.get("decision_node_id")
        if isinstance(spec, Mapping) and isinstance(spec.get("decision_node_id"), str)
        else None
    )
    return decision_from_script_results(
        script_results if isinstance(script_results, Mapping) else None,
        decision_node_id=decision_node_id,
    )
