from __future__ import annotations

from typing import Any

from atomforge.reporting.context import select_report_contexts
from atomforge.schemas import ExperimentSpec, ResultsGraph, ScientificDecision, ScriptResult
from atomforge.scientific_decision import decision_from_script_data


def _append_mapping(lines: list[str], title: str, mapping: dict[str, Any]) -> None:
    lines.extend([f"### {title}", ""])
    for key, value in mapping.items():
        if key != "threshold_rationale":
            lines.append(f"- `{key}`: `{value}`")
    rationale = mapping.get("threshold_rationale")
    if rationale:
        lines.extend(["", str(rationale), ""])


def _append_scientific_decision(lines: list[str], decision: ScientificDecision) -> None:
    lines.extend(
        [
            f"- Outcome: **{decision.outcome}**",
            f"- Calibration: **{decision.calibration.status}** "
            f"({decision.calibration.accepted_case_count}/"
            f"{decision.calibration.minimum_case_count or 'not set'})",
            f"- Scope: {decision.scope}",
            "",
            decision.headline,
            "",
        ]
    )

    if decision.quality_checks:
        lines.extend(["### Recorded quality checks", ""])
        for check in decision.quality_checks:
            lines.append(
                f"- **{check.label}** — {check.status}: `{check.value}` "
                f"{check.unit}; criterion: {check.criterion}"
            )
        lines.append("")

    for title, items in (
        ("What this result supports", decision.supported_claims),
        ("What this result does not establish", decision.limitations),
    ):
        if items:
            lines.extend([f"### {title}", ""])
            lines.extend(f"- {item}" for item in items)
            lines.append("")


def _append_source(lines: list[str], source: dict[str, Any]) -> None:
    lines.extend(["### Source and reproducibility artifacts", ""])
    for label, key in (
        ("Title", "title"),
        ("Authors", "authors"),
        ("Publication", "journal"),
        ("Identifier", "identifier"),
        ("Primary source", "url"),
        ("Source code", "code_url"),
        ("Source data", "data_url"),
    ):
        value = source.get(key)
        if value:
            lines.append(f"- {label}: `{value}`")
    lines.append("")


def _append_report_sections(lines: list[str], sections: list[Any]) -> None:
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str):
            continue
        lines.extend([f"### {section['title']}", ""])
        body = section.get("body")
        if isinstance(body, str):
            lines.extend([body, ""])
        items = section.get("items")
        if isinstance(items, list):
            lines.extend(f"- {item}" for item in items if isinstance(item, str))
            lines.append("")


def _append_script_context(lines: list[str], node_id: str, data: dict[str, Any]) -> None:
    decision = decision_from_script_data(data)
    source = data.get("source")
    dataset = data.get("dataset")
    acceptance = data.get("acceptance_contract")
    report_sections = data.get("report_sections")
    values = (decision, source, dataset, acceptance, report_sections)
    if not any(value is not None for value in values):
        return

    lines.extend(["", f"## Recorded scientific context ({node_id})", ""])
    if decision is not None:
        _append_scientific_decision(lines, decision)
    if isinstance(source, dict):
        _append_source(lines, source)
    if isinstance(dataset, dict):
        _append_mapping(lines, "Dataset identity and scope", dataset)
    if isinstance(acceptance, dict):
        _append_mapping(lines, "Predeclared acceptance contract", acceptance)
    if isinstance(report_sections, list):
        _append_report_sections(lines, report_sections)


def render_research_report(
    spec: ExperimentSpec,
    result: ResultsGraph,
    *,
    script_results: dict[str, ScriptResult] | None = None,
) -> str:
    lines = [
        f"# Research Report: {spec.experiment_id}",
        "",
        "## Execution Summary",
        "",
        f"The experiment executed {len(spec.dag)} nodes and finished with status "
        f"**{result.status}**.",
        "Workflow status is separate from scientific validity.",
        "",
        "## Method Identity",
        "",
        f"- Model: `{result.model_info.name}`",
        f"- Version: `{result.model_info.version}`",
        f"- Head: `{result.model_info.head or 'not specified'}`",
        f"- Precision: `{result.model_info.dtype or 'not specified'}`",
        f"- Device: `{result.model_info.device}`",
        "",
        "## Quality and Acceptance Checks",
        "",
    ]

    assertions = {hypothesis.id: hypothesis.assertion for hypothesis in spec.hypotheses}
    if not result.hypotheses:
        lines.append("No acceptance checks were defined.")
    for evaluation in result.hypotheses:
        sample_basis = (
            f"- Sample size: `{evaluation.sample_size}`"
            if evaluation.sample_size > 0
            else ("- Sample basis: `deterministic derived metric; no ensemble confidence interval`")
        )
        lines.extend(
            [
                f"### {evaluation.id}: {evaluation.status}",
                "",
                f"- Metric: `{evaluation.metric}`",
                f"- Value: `{evaluation.value}`",
                f"- Assertion: `{assertions.get(evaluation.id, 'not available')}`",
                sample_basis,
                (
                    "- Interpretation: this is a configured gate, not independent "
                    "proof of a broader claim."
                ),
                "",
            ]
        )

    lines.extend(["## Methodology", ""])
    for node in spec.dag:
        lines.extend(
            [
                f"### {node.id} ({node.type})",
                "",
                f"- Parameters: `{node.params}`",
                f"- Dependencies: `{node.depends_on or 'none'}`",
                "",
            ]
        )

    lines.extend(["## Metrics", ""])
    for key, metric in result.metrics.items():
        lines.append(f"- **{key}**: {metric.val:.6g} {metric.unit}")

    contexts = select_report_contexts(script_results or {})
    for node_id, data in contexts:
        _append_script_context(lines, node_id, data)

    lines.extend(["", "## Claim Boundary", ""])
    has_decision = any(decision_from_script_data(data) is not None for _, data in contexts)
    if has_decision:
        lines.append(
            "Use the experiment-authored supported claims and limitations above; "
            "do not infer claims from workflow success alone."
        )
    else:
        lines.append(
            "No experiment-authored scientific decision was recorded. Acceptance checks "
            "describe this configured run only."
        )

    if result.errors:
        lines.extend(["", "## Execution Errors", ""])
        for node_id, message in result.errors.items():
            lines.append(f"- **{node_id}**: {message}")

    lines.extend(["", "---", "Generated by AtomForge."])
    return "\n".join(lines) + "\n"
