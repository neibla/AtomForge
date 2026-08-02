from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from simpleeval import InvalidExpression, NameNotDefined, simple_eval

from atomforge.schemas import (
    AtomsData,
    ExperimentSpec,
    HypothesisEval,
    MetricResult,
    ModelMetadata,
    ResultsGraph,
    ScriptResult,
    SimulationResult,
    SweepResult,
)
from atomforge.stats import mean_and_bootstrap_ci

ScalarTrialMetric = bool | float
logger = logging.getLogger(__name__)


def _extract_ensemble_metrics(
    ensemble: list[Any],
) -> tuple[list[dict[str, ScalarTrialMetric]], dict[str, list[float]]]:
    """Extract typed scalar evidence without losing its original trial index."""

    if not ensemble:
        return [], {}
    if not all(isinstance(item, SimulationResult) for item in ensemble):
        raise ValueError("Simulation ensembles must contain SimulationResult values")

    result_type = type(ensemble[0])
    if any(type(item) is not result_type for item in ensemble):
        raise ValueError("Simulation ensembles must contain one result type")

    serialized = [item.model_dump(mode="python") for item in ensemble]
    per_trial: list[dict[str, ScalarTrialMetric]] = [{} for _ in ensemble]
    numeric_samples: dict[str, list[float]] = {}
    for field_name in serialized[0]:
        numeric_values: list[float] = []
        for trial_index, item in enumerate(serialized):
            value = item.get(field_name)
            if isinstance(value, bool):
                per_trial[trial_index][field_name] = value
            elif isinstance(value, int | float):
                numeric_value = float(value)
                per_trial[trial_index][field_name] = numeric_value
                numeric_values.append(numeric_value)
        if numeric_values:
            numeric_samples[field_name] = numeric_values
    return per_trial, numeric_samples


@dataclass(slots=True)
class _AssemblyState:
    """Typed accumulator for the independent evidence surfaces in a run."""

    context: dict[str, float] = field(default_factory=dict)
    trial_data: dict[str, Any] = field(default_factory=dict)
    trial_metric_samples: dict[str, list[float]] = field(default_factory=dict)
    trial_metrics_by_node: dict[str, list[dict[str, ScalarTrialMetric]]] = field(
        default_factory=dict
    )
    explicit_metric_units: dict[str, str] = field(default_factory=dict)

    def record(self, node_id: str, result: Any) -> None:
        if isinstance(result, Mapping) and "ensemble" in result:
            self._record_ensemble(node_id, result["ensemble"])
        elif isinstance(result, AtomsData):
            self._record_structure(node_id, result)
        elif isinstance(result, SweepResult):
            self._record_sweep(node_id, result)
        elif isinstance(result, ScriptResult):
            self._record_script(node_id, result)

    def _record_ensemble(self, node_id: str, ensemble: Any) -> None:
        if not isinstance(ensemble, list):
            raise ValueError("Simulation ensemble output must be a list")
        if not ensemble:
            return
        if len(ensemble) == 1:
            self.trial_data[node_id] = ensemble[0]

        trial_metrics, numeric_samples = _extract_ensemble_metrics(ensemble)
        if trial_metrics:
            self.trial_metrics_by_node[node_id] = trial_metrics
        for field_name, values in numeric_samples.items():
            metric_key = f"{node_id}_{field_name}"
            self.context[metric_key] = float(np.mean(values))
            self.trial_metric_samples[metric_key] = values

    def _record_structure(self, node_id: str, result: AtomsData) -> None:
        if result.dft_energy is not None:
            self.context[f"{node_id}_energy"] = result.dft_energy

    def _record_sweep(self, node_id: str, result: SweepResult) -> None:
        self.context[f"{node_id}_sample_count"] = float(len(result.points))
        self.context[f"{node_id}_completed_count"] = float(result.completed_count)
        self.context[f"{node_id}_failed_count"] = float(result.failed_count)

    def _record_script(self, node_id: str, result: ScriptResult) -> None:
        for metric_name, metric in result.metrics.items():
            metric_key = f"{node_id}_{metric_name}"
            self.context[metric_key] = metric.val
            self.explicit_metric_units[metric_key] = metric.unit


def assemble_results(
    spec: ExperimentSpec,
    results: Mapping[str, Any],
    errors: Mapping[str, str],
    *,
    executor_metadata: ModelMetadata,
    node_model_info: Mapping[str, ModelMetadata],
) -> tuple[ResultsGraph, dict[str, Any]]:
    """Turn recorded node outputs into the graph and trial evidence bundle."""

    state = _AssemblyState()
    for node_id, result in results.items():
        state.record(node_id, result)

    evaluations = []
    for hypothesis in spec.hypotheses:
        expression = hypothesis.assertion.replace("target.", f"{hypothesis.target_node}.")
        evaluated_expression = re.sub(
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b",
            r"\1_\2",
            expression,
        )
        metric_available = False
        try:
            metric_key = f"{hypothesis.target_node}_{hypothesis.metric}"
            samples = state.trial_metric_samples.get(metric_key, [])
            metric_available = metric_key in state.context or bool(samples)
            if samples:
                mean_value, ci_low, ci_high = mean_and_bootstrap_ci(samples)
                value = f"{mean_value:.6g} (95% CI [{ci_low:.6g}, {ci_high:.6g}], n={len(samples)})"
            else:
                value = str(state.context.get(metric_key, "0"))
                ci_low = ci_high = None
            evaluations.append(
                HypothesisEval(
                    id=hypothesis.id,
                    target_node=hypothesis.target_node,
                    status=(
                        "PASSED"
                        if simple_eval(evaluated_expression, names=state.context)
                        else "FAILED"
                    ),
                    metric=hypothesis.metric,
                    value=value,
                    sample_size=len(samples),
                    ci_low=ci_low,
                    ci_high=ci_high,
                )
            )
        except Exception as exc:  # noqa: BLE001
            reason, detail = _hypothesis_review_reason(
                exc,
                metric_available=metric_available,
                target_result=results.get(hypothesis.target_node),
            )
            if reason == "EVALUATION_ERROR":
                logger.exception(
                    "Unexpected hypothesis evaluation failure",
                    extra={
                        "hypothesis_id": hypothesis.id,
                        "target_node": hypothesis.target_node,
                    },
                )
            evaluations.append(
                HypothesisEval(
                    id=hypothesis.id,
                    target_node=hypothesis.target_node,
                    status="REVIEW",
                    metric=hypothesis.metric,
                    value="Unavailable",
                    review_reason=reason,
                    detail=detail,
                )
            )

    has_partial_sweep = any(
        isinstance(result, SweepResult) and result.failed_count > 0 for result in results.values()
    )
    status = "SUCCESS"
    if errors or has_partial_sweep:
        status = "PARTIAL" if results else "FAILED"
    model_info = workflow_model_metadata(executor_metadata, node_model_info)
    node_statuses = _node_statuses(spec, results, errors)
    return (
        ResultsGraph(
            experiment_id=spec.experiment_id,
            status=status,
            metrics={
                key: MetricResult(
                    val=value,
                    unit=state.explicit_metric_units.get(key, metric_unit(key)),
                )
                for key, value in state.context.items()
            },
            hypotheses=evaluations,
            node_statuses=node_statuses,
            model_info=model_info,
            node_model_info=dict(node_model_info),
            summary={
                "SUCCESS": "Completed; acceptance checks are reported separately.",
                "PARTIAL": "Partially completed; one or more nodes failed.",
            }.get(status, "Failed."),
            errors=dict(errors),
        ),
        {
            "trial_data": state.trial_data,
            "trial_metrics_by_node": state.trial_metrics_by_node,
        },
    )


def _hypothesis_review_reason(
    exc: Exception,
    *,
    metric_available: bool,
    target_result: Any,
) -> tuple[str, str]:
    """Map expected evaluation failures to concise persisted explanations."""

    if not metric_available:
        if isinstance(target_result, Mapping) and target_result.get("ensemble") == []:
            return "INSUFFICIENT_SAMPLES", "The target node produced no trial samples."
        return "MISSING_METRIC", "The target node did not publish the requested metric."
    if isinstance(exc, (NameNotDefined, InvalidExpression, SyntaxError)):
        return "INVALID_EXPRESSION", "The hypothesis assertion could not be evaluated."
    if isinstance(exc, (TypeError, ValueError)):
        return "NON_NUMERIC_VALUE", "The metric value is not compatible with the assertion."
    return "EVALUATION_ERROR", "The hypothesis assertion raised an unexpected evaluation error."


def _node_statuses(
    spec: ExperimentSpec,
    results: Mapping[str, Any],
    errors: Mapping[str, str],
) -> dict[str, str]:
    """Build terminal, per-node status evidence for the result contract."""

    statuses: dict[str, str] = {}
    for node in spec.dag:
        error = errors.get(node.id)
        if error:
            statuses[node.id] = "BLOCKED" if error.startswith("Dependency failed:") else "FAILED"
            continue
        result = results.get(node.id)
        if result is None:
            statuses[node.id] = "NOT_RUN"
            continue
        if isinstance(result, SweepResult) and result.failed_count:
            statuses[node.id] = "REVIEW"
            continue
        if isinstance(result, ScriptResult):
            decision = result.data.get("scientific_decision")
            if isinstance(decision, Mapping) and decision.get("outcome") in {"REVIEW", "BLOCKED"}:
                statuses[node.id] = "REVIEW"
                continue
        statuses[node.id] = "COMPLETE"
    return statuses


def workflow_model_metadata(
    executor_metadata: ModelMetadata,
    node_model_info: Mapping[str, ModelMetadata],
) -> ModelMetadata:
    """Return a top-level summary without erasing per-node provenance."""

    if not node_model_info:
        return executor_metadata

    identities = {
        (
            metadata.name,
            metadata.version,
            metadata.checkpoint,
            metadata.checkpoint_sha256,
            metadata.head,
            metadata.dtype,
            metadata.device,
        )
        for metadata in node_model_info.values()
    }
    if len(identities) == 1:
        return next(iter(node_model_info.values()))

    component_names = sorted(
        {f"{metadata.name}@{metadata.version}" for metadata in node_model_info.values()}
    )
    return ModelMetadata(
        name=f"Multi-component workflow: {', '.join(component_names)}",
        version="workflow-provenance.v1",
        checkpoint=None,
        checkpoint_sha256=None,
        head="per-node",
        dtype="per-node",
        hardware="per-node",
        device="per-node",
    )


def metric_unit(metric_key: str) -> str:
    units = {
        "youngs_modulus_gpa": "GPa",
        "max_stress_gpa": "GPa",
        "energy_absorption": "GPa",
        "potential_energy": "eV/atom",
        "max_force": "eV/Å",
        "force_norm": "eV/Å",
        "mean_temperature_K": "K",
        "std_temperature_K": "K",
        "temperature_K": "K",
        "runtime_ms": "ms",
        "n_defects": "count",
        "interstitials": "count",
        "vacancies": "count",
        "temperature": "K",
        "is_liquid": "boolean",
        "analysis_applicable": "boolean",
        "trajectory_quality_passed": "boolean",
        "stable": "boolean",
        "energy": "eV/atom",
        "seed": "index",
        "msd": "Å²",
    }
    for metric_name, unit in units.items():
        if metric_key.endswith(f"_{metric_name}"):
            return unit
    return "dimensionless"
