# ruff: noqa: E501
"""Bundle-driven HTML research reports.

The renderer consumes explicit result, interpretation, provenance, and
visualization contracts. It never branches on experiment IDs, materials,
models, papers, or historical result counts.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from atomforge.execution.evidence_artifacts import read_verified_json
from atomforge.execution.evidence_repository import default_results_dir
from atomforge.reporting.context import select_report_contexts
from atomforge.schemas import VisualizationCatalog, VisualizationCatalogReference
from atomforge.scientific_decision import decision_from_bundle, decision_from_script_data


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value: Any, digits: int = 6) -> str:
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return f"{value:.{digits}g}"
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _fmt_axis(value: float) -> str:
    if value == 0:
        return "0"
    return f"{value:.4g}"


def _human_label(value: Any) -> str:
    return str(value or "").replace("_", " ").replace("-", " ").strip().capitalize()


def _safe_link(url: Any, label: Any) -> str:
    if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
        return ""
    return f'<a href="{_esc(url)}" target="_blank" rel="noreferrer">{_esc(label)}</a>'


def find_result_bundle(
    experiment_id: str,
    *,
    root: Path | str = Path("."),
    input_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    root = Path(root)
    results_dir = (
        default_results_dir()
        if root.resolve() == Path(".").resolve()
        else root / ".atomforge" / "results"
    )
    candidates = [
        Path(input_path) if input_path is not None else None,
        results_dir / f"{experiment_id}.json",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"Result bundle must be a JSON object: {candidate}")
            return payload, candidate
    searched = ", ".join(str(path) for path in candidates if path is not None)
    raise FileNotFoundError(
        f"No persisted result bundle for {experiment_id!r}; searched {searched}"
    )


def _report_contexts(bundle: dict[str, Any]):
    raw = bundle.get("script_results")
    return select_report_contexts(raw if isinstance(raw, dict) else {})


def _visualizations(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = bundle.get("visualizations")
    if catalog is None:
        return []
    validated = VisualizationCatalog.model_validate(catalog)
    visuals = validated.model_dump(mode="json")["visualizations"]
    aggregate_nodes = {node_id for node_id, _ in _report_contexts(bundle)}
    if aggregate_nodes:
        aggregate_visuals = [
            visual for visual in visuals if str(visual.get("source_node")) in aggregate_nodes
        ]
        if aggregate_visuals:
            return aggregate_visuals
    return visuals


def _hydrate_visualization_catalog(
    bundle: dict[str, Any],
    source_path: Path | str | None,
) -> dict[str, Any]:
    reference_value = bundle.get("visualization_catalog_ref")
    if reference_value is None:
        return bundle
    if source_path is None:
        raise ValueError("A bundle with visualization_catalog_ref requires source_path")

    reference = VisualizationCatalogReference.model_validate(reference_value)
    source = Path(source_path).resolve()
    catalog_path = (source.parent / reference.artifact_path).resolve()
    if catalog_path.parent != source.parent:
        raise ValueError("Visualization catalog must be a sibling of the result bundle")
    try:
        catalog = read_verified_json(
            catalog_path,
            expected_artifact_path=reference.artifact_path,
            expected_sha256=reference.sha256,
            parse=VisualizationCatalog.model_validate,
        )
    except ValueError as exc:
        raise ValueError(
            f"Visualization catalog integrity failure for {reference.artifact_path}: {exc}"
        ) from exc
    if len(catalog.visualizations) != reference.visualization_count:
        raise ValueError(f"Visualization count mismatch for {reference.artifact_path}")
    hydrated = dict(bundle)
    hydrated["visualizations"] = catalog.model_dump(mode="json")
    return hydrated


def _scientific_verdict(bundle: dict[str, Any]) -> tuple[str, str, str]:
    decision = decision_from_bundle(bundle)
    if decision is not None:
        return (
            _human_label(decision.outcome),
            "pass" if decision.outcome == "VALIDATED" else "review",
            decision.headline,
        )

    result = bundle.get("results") if isinstance(bundle.get("results"), dict) else {}
    run_status = str(result.get("status") or "UNKNOWN").upper()
    hypotheses = result.get("hypotheses") if isinstance(result.get("hypotheses"), list) else []
    statuses = {
        str(item.get("status") or "").upper() for item in hypotheses if isinstance(item, dict)
    }
    if run_status != "SUCCESS":
        return (
            f"Run {run_status.lower()}",
            "review",
            "The workflow did not complete successfully. Resolve execution errors before interpreting scientific results.",
        )
    if "FAILED" in statuses:
        return (
            "Configured acceptance checks failed",
            "review",
            "At least one predeclared acceptance check failed. Review the recorded values, criteria, and limitations.",
        )
    if "REVIEW" in statuses:
        return (
            "Configured acceptance checks need review",
            "review",
            "At least one predeclared acceptance check requires scientific review.",
        )
    if hypotheses and statuses <= {"PASSED"}:
        return (
            "Configured acceptance checks passed",
            "pass",
            "All recorded acceptance checks passed for this run. This does not establish claims beyond the recorded scope.",
        )
    return (
        "Scientific decision not recorded",
        "review",
        "The workflow completed, but no experiment-authored scientific-decision.v1 contract was recorded.",
    )


def _quality_checks_html(checks: Any) -> str:
    if not isinstance(checks, list):
        return ""
    rows = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        status = str(check.get("status") or "not recorded")
        rows.append(
            "<tr>"
            f"<th>{_esc(check.get('label', 'Check'))}</th>"
            f'<td class="status-{_esc(status.lower())}">{_esc(status)}</td>'
            f"<td>{_esc(_fmt(check.get('value', 'not recorded')))} {_esc(check.get('unit', ''))}</td>"
            f"<td>{_esc(check.get('criterion', 'not recorded'))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<h3>Recorded quality checks</h3>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Check</th><th>Status</th><th>Value</th><th>Criterion</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _mapping_table(mapping: dict[str, Any], *, skip: set[str] | None = None) -> str:
    skip = skip or set()
    rows = []
    for key, value in mapping.items():
        if key in skip:
            continue
        if isinstance(value, dict):
            display = (
                ", ".join(f"{item_key}: {item_value}" for item_key, item_value in value.items())
                if len(value) <= 20
                else f"{len(value):,} recorded entries"
            )
        elif isinstance(value, list):
            display = (
                "; ".join(
                    json.dumps(item, sort_keys=True) if isinstance(item, dict | list) else str(item)
                    for item in value
                )
                if len(value) <= 10
                else f"{len(value):,} recorded entries"
            )
        else:
            display = value
        rows.append(f"<tr><th>{_esc(_human_label(key))}</th><td>{_esc(_fmt(display))}</td></tr>")
    return f"<table><tbody>{''.join(rows)}</tbody></table>" if rows else ""


def _decision_summary_html(bundle: dict[str, Any]) -> str:
    decision = decision_from_bundle(bundle)
    if decision is None:
        verdict, verdict_class, explanation = _scientific_verdict(bundle)
        return (
            f'<section class="panel verdict {verdict_class}">'
            '<div class="eyebrow">Final decision</div>'
            f"<h2>{_esc(verdict)}</h2><p>{_esc(explanation)}</p></section>"
        )

    claims = "".join(f"<li>{_esc(item)}</li>" for item in decision.supported_claims)
    limitations = "".join(f"<li>{_esc(item)}</li>" for item in decision.limitations)
    calibration = decision.calibration
    progress = (
        f"{calibration.accepted_case_count}/{calibration.minimum_case_count}"
        if calibration.minimum_case_count
        else str(calibration.accepted_case_count)
    )
    verdict_class = "pass" if decision.outcome == "VALIDATED" else "review"
    return (
        f'<section class="panel verdict decision-summary {verdict_class}">'
        '<div class="eyebrow">Final decision</div>'
        '<div class="decision-heading">'
        f"<div><h2>{_esc(decision.headline)}</h2>"
        f'<p class="decision-scope">{_esc(decision.scope)}</p></div>'
        f'<span class="decision-badge status-{_esc(decision.outcome.lower())}">'
        f"{_esc(_human_label(decision.outcome))}</span></div>"
        '<div class="decision-facts">'
        f"<div><span>Calibration</span><strong>{_esc(_human_label(calibration.status))}</strong></div>"
        f"<div><span>Accepted cases</span><strong>{_esc(progress)}</strong></div>"
        f"<div><span>Contract</span><strong>{_esc(decision.contract_version)}</strong></div>"
        "</div>"
        f"{_quality_checks_html([item.model_dump(mode='json') for item in decision.quality_checks])}"
        '<div class="claim-grid">'
        f"<div><h3>What this establishes</h3><ul>{claims or '<li>No positive claim recorded.</li>'}</ul></div>"
        f"<div><h3>Explicit limits</h3><ul>{limitations}</ul></div>"
        "</div></section>"
    )


def _recorded_context_html(bundle: dict[str, Any]) -> str:
    steps: list[str] = []
    for node_id, data in _report_contexts(bundle):
        decision = decision_from_script_data(data)
        source = data.get("source")
        detail_sections: list[str] = []
        if isinstance(source, dict):
            links = [
                _safe_link(source.get("url"), "Primary source"),
                _safe_link(source.get("code_url"), "Source code"),
                _safe_link(source.get("data_url"), "Source data"),
            ]
            links = [link for link in links if link]
            details = [
                str(value)
                for value in (
                    source.get("authors"),
                    source.get("journal"),
                    source.get("identifier"),
                    source.get("arxiv_id"),
                )
                if value
            ]
            detail_sections.append(
                "<h3>Source and reproducibility artifacts</h3>"
                f"<p><strong>{_esc(source.get('title', 'Recorded source'))}</strong>"
                f"{'<br>' + _esc(' · '.join(details)) if details else ''}</p>"
                f"{'<p>' + ' · '.join(links) + '</p>' if links else ''}"
            )

        acceptance = data.get("acceptance_contract")
        if isinstance(acceptance, dict):
            rationale = acceptance.get("threshold_rationale")
            detail_sections.append(
                "<h3>Predeclared acceptance contract</h3>"
                f"{f'<p>{_esc(rationale)}</p>' if rationale else ''}"
                f"{_mapping_table(acceptance, skip={'threshold_rationale'})}"
            )

        dataset = data.get("dataset")
        if isinstance(dataset, dict):
            table = _mapping_table(dataset, skip={"rows", "comparison_rows"})
            if table:
                detail_sections.append(f"<h3>Dataset identity and scope</h3>{table}")

        dft_result = data.get("dft_result")
        if isinstance(dft_result, dict):
            table = _mapping_table(
                dft_result,
                skip={
                    "artifact_files",
                    "final_structure",
                    "initial_structure",
                    "pristine_structure",
                    "phases",
                },
            )
            if table:
                detail_sections.append(f"<h3>DFT calculation and artifact</h3>{table}")

        report_sections = data.get("report_sections")
        if isinstance(report_sections, list):
            for section in report_sections:
                if not isinstance(section, dict) or not isinstance(section.get("title"), str):
                    continue
                items = section.get("items")
                item_html = (
                    "<ul>"
                    + "".join(f"<li>{_esc(item)}</li>" for item in items if isinstance(item, str))
                    + "</ul>"
                    if isinstance(items, list)
                    else ""
                )
                body = section.get("body")
                detail_sections.append(
                    f"<h3>{_esc(section['title'])}</h3>"
                    f"{f'<p>{_esc(body)}</p>' if isinstance(body, str) else ''}"
                    f"{item_html}"
                )

        headline = decision.headline if decision else _human_label(node_id)
        outcome = decision.outcome if decision else "EVIDENCE"
        node_claims = (
            "".join(f"<li>{_esc(item)}</li>" for item in decision.supported_claims)
            if decision
            else ""
        )
        node_limits = (
            "".join(f"<li>{_esc(item)}</li>" for item in decision.limitations) if decision else ""
        )
        steps.append(
            '<details class="panel evidence-step">'
            f"<summary><span>{_esc(_human_label(node_id))}</span>"
            f'<span class="status-{_esc(outcome.lower())}">{_esc(_human_label(outcome))}</span>'
            f"<small>{_esc(headline)}</small></summary>"
            f"{''.join(detail_sections)}"
            f"{'<h3>Recorded support</h3><ul>' + node_claims + '</ul>' if node_claims else ''}"
            f"{'<h3>Recorded limits</h3><ul>' + node_limits + '</ul>' if node_limits else ''}"
            "</details>"
        )
    if not steps:
        return ""
    return (
        '<section class="evidence-chain"><div class="eyebrow">Evidence chain</div>'
        "<h2>How the workflow reached this decision</h2>"
        '<p class="description">Expand a step for its source, acceptance contract, and recorded limits.</p>'
        + "".join(steps)
        + "</section>"
    )


def _axis_spec(visual: dict[str, Any], axis: str, rows: list[dict[str, Any]]) -> tuple[str, str]:
    spec = visual.get(axis) if isinstance(visual.get(axis), dict) else {}
    field = spec.get("field")
    if not isinstance(field, str):
        field = next(iter(rows[0]), "") if rows else ""
    label = str(spec.get("label") or _human_label(field))
    unit = spec.get("unit")
    if unit:
        label = f"{label} ({unit})"
    return field, label


def _chart_svg(visual: dict[str, Any]) -> str:
    rows = [row for row in visual.get("rows", []) if isinstance(row, dict)]
    if not rows:
        return '<div class="empty">No chart rows were recorded.</div>'
    x_field, x_label = _axis_spec(visual, "x", rows)
    y_field, y_label = _axis_spec(visual, "y", rows)
    mark = str(visual.get("mark") or "line")
    width, height = 980, 420
    left, right, top, bottom = 82, 28, 28, 72
    plot_w, plot_h = width - left - right, height - top - bottom

    numeric_x = all(isinstance(row.get(x_field), int | float) for row in rows)
    points: list[tuple[float, float, str]] = []
    y_values = [
        float(row[y_field])
        for row in rows
        if isinstance(row.get(y_field), int | float) and math.isfinite(float(row[y_field]))
    ]
    if not y_values:
        return '<div class="empty">No finite quantitative values were recorded.</div>'
    y_min, y_max = min(y_values), max(y_values)
    if mark == "bar":
        # Quantitative bars encode magnitude from zero. Padding a positive-only
        # domain below zero invents a negative tick; omitting zero exaggerates
        # small differences. Preserve zero as the baseline and pad only the
        # magnitude-facing edge.
        if y_min >= 0.0:
            y_min = 0.0
            y_max = y_max if y_max > 0.0 else 1.0
            y_max += (y_max - y_min) * 0.08
        elif y_max <= 0.0:
            y_max = 0.0
            y_min = y_min if y_min < 0.0 else -1.0
            y_min -= (y_max - y_min) * 0.08
        else:
            y_pad = (y_max - y_min) * 0.08
            y_min -= y_pad
            y_max += y_pad
    else:
        if math.isclose(y_min, y_max):
            y_min -= 0.5
            y_max += 0.5
        y_pad = (y_max - y_min) * 0.08
        y_min -= y_pad
        y_max += y_pad

    if numeric_x:
        x_values = [float(row[x_field]) for row in rows]
        x_min, x_max = min(x_values), max(x_values)
        if math.isclose(x_min, x_max):
            x_min -= 0.5
            x_max += 0.5
        for row in rows:
            if not isinstance(row.get(y_field), int | float):
                continue
            x_value = float(row[x_field])
            y_value = float(row[y_field])
            x = left + (x_value - x_min) / (x_max - x_min) * plot_w
            y = top + (y_max - y_value) / (y_max - y_min) * plot_h
            points.append((x, y, str(row[x_field])))
    else:
        denominator = max(len(rows) - 1, 1)
        for index, row in enumerate(rows):
            if not isinstance(row.get(y_field), int | float):
                continue
            x = (
                left + (index + 0.5) / len(rows) * plot_w
                if mark == "bar"
                else left + index / denominator * plot_w
            )
            y_value = float(row[y_field])
            y = top + (y_max - y_value) / (y_max - y_min) * plot_h
            points.append((x, y, str(row.get(x_field, index))))

    grid = []
    ticks = []
    for index in range(5):
        y = top + index / 4 * plot_h
        value = y_max - index / 4 * (y_max - y_min)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="grid"/>'
        )
        ticks.append(
            f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" class="tick">{_esc(_fmt_axis(value))}</text>'
        )

    if mark == "bar":
        bar_width = max(10.0, plot_w / max(len(points), 1) * 0.62)
        baseline = top + (y_max - max(0.0, y_min)) / (y_max - y_min) * plot_h
        marks = "".join(
            f'<rect x="{x - bar_width / 2:.1f}" y="{min(y, baseline):.1f}" width="{bar_width:.1f}" height="{abs(baseline - y):.1f}" class="bar"><title>{_esc(label)}</title></rect>'
            for x, y, label in points
        )
    elif mark == "scatter":
        marks = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="point" opacity="0.58"><title>{_esc(label)}</title></circle>'
            for x, y, label in points
        )
        if numeric_x and x_field != y_field:
            x_values = [float(row[x_field]) for row in rows]
            lo = max(min(x_values), y_min)
            hi = min(max(x_values), y_max)
            if lo < hi:
                x_min, x_max = min(x_values), max(x_values)
                x1 = left + (lo - x_min) / (x_max - x_min) * plot_w
                x2 = left + (hi - x_min) / (x_max - x_min) * plot_w
                y1 = top + (y_max - lo) / (y_max - y_min) * plot_h
                y2 = top + (y_max - hi) / (y_max - y_min) * plot_h
                marks += f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="agreement"/>'
    else:
        path = " ".join(
            f"{'M' if index == 0 else 'L'} {x:.1f} {y:.1f}"
            for index, (x, y, _) in enumerate(points)
        )
        marks = f'<path d="{path}" fill="none" class="series"/>' + "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="point"><title>{_esc(label)}</title></circle>'
            for x, y, label in points
        )

    x_ticks = "".join(
        f'<text x="{x:.1f}" y="{height - bottom + 24}" text-anchor="middle" class="tick">{_esc(label[:18])}</text>'
        for x, _, label in points[:12]
    )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(visual.get("title", "Chart"))}">'
        + "".join(grid)
        + "".join(ticks)
        + marks
        + x_ticks
        + f'<text x="{left + plot_w / 2:.1f}" y="{height - 14}" text-anchor="middle" class="axis">{_esc(x_label)}</text>'
        + f'<text x="20" y="{top + plot_h / 2:.1f}" transform="rotate(-90 20 {top + plot_h / 2:.1f})" text-anchor="middle" class="axis">{_esc(y_label)}</text>'
        + "</svg>"
    )


def _table_html(visual: dict[str, Any]) -> str:
    rows = [row for row in visual.get("rows", []) if isinstance(row, dict)]
    if not rows:
        return '<div class="empty">No table rows were recorded.</div>'
    raw_columns = visual.get("columns")
    if isinstance(raw_columns, list) and raw_columns:
        columns = [
            column for column in raw_columns if isinstance(column, dict) and column.get("field")
        ]
    else:
        columns = [{"field": field, "label": _human_label(field)} for field in rows[0]]
    headers = []
    for column in columns:
        label = str(column.get("label") or _human_label(column["field"]))
        unit = column.get("unit")
        headers.append(f"{label} ({unit})" if unit else label)
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for column, header in zip(columns, headers, strict=True):
            value = row.get(column["field"], "")
            status_class = (
                f' class="status-{_esc(str(value).lower())}"'
                if str(column["field"]).lower() == "status"
                else ""
            )
            cells.append(
                f'<td data-label="{_esc(header)}"{status_class}>{_esc(_fmt(value, 4))}</td>'
            )
        body.append("<tr>" + "".join(cells) + "</tr>")
    width_class = " wide-table" if len(columns) >= 7 else ""
    return (
        f'<div class="table-wrap{width_class}"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _symbols(data: dict[str, Any]) -> list[str]:
    symbols = data.get("symbols")
    if isinstance(symbols, list) and symbols:
        return [str(symbol) for symbol in symbols]
    numbers = data.get("numbers")
    if not isinstance(numbers, list):
        return []
    try:
        from ase.data import chemical_symbols

        return [
            chemical_symbols[int(number)]
            if 0 < int(number) < len(chemical_symbols)
            else f"Z{number}"
            for number in numbers
        ]
    except (ImportError, TypeError, ValueError):
        return [f"Z{number}" for number in numbers]


def _structure_svg(data: dict[str, Any]) -> str:
    positions = [
        [float(value) for value in point[:3]]
        for point in data.get("positions", [])
        if isinstance(point, list) and len(point) >= 3
    ]
    if not positions:
        return '<div class="empty">No atom positions were recorded.</div>'
    vacancy_positions = [
        [float(value) for value in point[:3]]
        for point in (data.get("vacancy_positions") or [])
        if isinstance(point, list) and len(point) >= 3
    ]
    labels = _symbols(data)

    def project(point: list[float]) -> tuple[float, float]:
        return point[0] - 0.55 * point[1], point[2] + 0.35 * point[1]

    projected = [project(point) for point in positions]
    projected_vacancies = [project(point) for point in vacancy_positions]
    all_projected = [*projected, *projected_vacancies]
    min_x, max_x = min(x for x, _ in all_projected), max(x for x, _ in all_projected)
    min_y, max_y = min(y for _, y in all_projected), max(y for _, y in all_projected)
    width, height, padding = 980, 420, 60
    scale = min(
        (width - 2 * padding) / max(max_x - min_x, 1e-9),
        (height - 2 * padding) / max(max_y - min_y, 1e-9),
    )
    circles = []
    for index, ((x, y), point) in enumerate(zip(projected, positions, strict=True)):
        screen_x = padding + (x - min_x) * scale
        screen_y = height - padding - (y - min_y) * scale
        label = labels[index] if index < len(labels) else "Atom"
        circles.append(
            f'<circle cx="{screen_x:.1f}" cy="{screen_y:.1f}" r="7" class="atom-point"><title>{_esc(label)} · {_esc(point)}</title></circle>'
        )
    vacancy_markers = []
    for (x, y), point in zip(projected_vacancies, vacancy_positions, strict=True):
        screen_x = padding + (x - min_x) * scale
        screen_y = height - padding - (y - min_y) * scale
        vacancy_markers.append(
            f'<circle cx="{screen_x:.1f}" cy="{screen_y:.1f}" r="12" class="vacancy-point"><title>Vacancy site · {_esc(point)}</title></circle>'
        )
    return (
        f'<svg class="structure" viewBox="0 0 {width} {height}" role="img" aria-label="Atomic structure with {len(positions)} atoms and {len(vacancy_positions)} vacancy sites">'
        + "".join(circles)
        + "".join(vacancy_markers)
        + "</svg>"
    )


def _atomistic_html(visual: dict[str, Any]) -> str:
    data = visual.get("data") if isinstance(visual.get("data"), dict) else {}
    symbols = _symbols(data)
    counts: dict[str, int] = {}
    for symbol in symbols:
        counts[symbol] = counts.get(symbol, 0) + 1
    composition = (
        ", ".join(f"{_esc(symbol)} × {count}" for symbol, count in sorted(counts.items()))
        or "not recorded"
    )
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    metadata_table = _mapping_table(metadata)
    vacancy_positions = data.get("vacancy_positions")
    vacancy_count = len(vacancy_positions) if isinstance(vacancy_positions, list) else 0
    vacancy_summary = (
        f'<div><span class="label">Vacancy sites</span><strong>{vacancy_count}</strong></div>'
        if vacancy_count
        else ""
    )
    return (
        _structure_svg(data)
        + '<div class="structure-summary">'
        + f'<div><span class="label">Atoms</span><strong>{len(symbols) or len(data.get("positions", []))}</strong></div>'
        + f'<div><span class="label">Composition</span><strong>{composition}</strong></div>'
        + f'<div><span class="label">Periodic boundary</span><strong>{_esc(data.get("pbc", "not recorded"))}</strong></div>'
        + vacancy_summary
        + "</div>"
        + metadata_table
    )


def _unit_glossary(metrics: dict[str, Any], visuals: list[dict[str, Any]]) -> str:
    units = {
        str(metric.get("unit"))
        for metric in metrics.values()
        if isinstance(metric, dict) and metric.get("unit")
    }
    for visual in visuals:
        for axis in ("x", "y"):
            spec = visual.get(axis)
            if isinstance(spec, dict) and spec.get("unit"):
                units.add(str(spec["unit"]))
        columns = visual.get("columns")
        if isinstance(columns, list):
            for column in columns:
                if isinstance(column, dict) and column.get("unit"):
                    units.add(str(column["unit"]))
    definitions = {
        "Å": "Ångström, a length unit equal to 10⁻¹⁰ metres.",
        "eV": "Electronvolt, an energy unit commonly used for atomic systems.",
        "meV": "Millielectronvolt, one thousandth of an electronvolt.",
        "eV/atom": "Energy normalized by atom count.",
        "meV/atom": "Millielectronvolts normalized by atom count.",
        "eV/Å": "Force expressed as energy per distance.",
        "GPa": "Gigapascal, a pressure or elastic-modulus unit.",
        "K": "Kelvin, an absolute-temperature unit.",
        "fs": "Femtosecond, 10⁻¹⁵ seconds.",
    }
    rows = "".join(
        f"<tr><th>{_esc(unit)}</th><td>{_esc(definitions[unit])}</td></tr>"
        for unit in sorted(units)
        if unit in definitions
    )
    return (
        f'<section class="panel"><h2>Units in this report</h2><table><tbody>{rows}</tbody></table></section>'
        if rows
        else ""
    )


def _hypothesis_value(metrics: dict[str, Any], item: dict[str, Any]) -> str:
    value = item.get("value")
    if value not in (None, ""):
        return str(value)
    metric_name = str(item.get("metric") or "")
    direct = metrics.get(metric_name)
    if isinstance(direct, dict):
        return f"{_fmt(direct.get('val'))} {direct.get('unit', '')}".strip()
    matches = [metric for name, metric in metrics.items() if str(name).endswith(f"_{metric_name}")]
    if len(matches) == 1 and isinstance(matches[0], dict):
        return f"{_fmt(matches[0].get('val'))} {matches[0].get('unit', '')}".strip()
    return "not recorded"


def render_html_report(bundle: dict[str, Any], *, source_path: Path | str | None = None) -> str:
    bundle = _hydrate_visualization_catalog(bundle, source_path)
    result = bundle.get("results") if isinstance(bundle.get("results"), dict) else {}
    spec = bundle.get("spec") if isinstance(bundle.get("spec"), dict) else {}
    experiment_id = str(result.get("experiment_id") or spec.get("experiment_id") or "experiment")
    status = str(result.get("status") or "UNKNOWN")
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    hypotheses = result.get("hypotheses") if isinstance(result.get("hypotheses"), list) else []
    model = result.get("model_info") if isinstance(result.get("model_info"), dict) else {}
    for _, data in _report_contexts(bundle):
        if isinstance(data.get("model_info"), dict):
            model = data["model_info"]
            break
    visuals = _visualizations(bundle)

    metric_cards = "".join(
        f'<div class="metric"><span>{_esc(_human_label(key))}</span><strong>{_esc(_fmt(value.get("val", value)))} <small>{_esc(value.get("unit", ""))}</small></strong></div>'
        for key, value in metrics.items()
        if isinstance(value, dict)
    )
    hypothesis_rows = "".join(
        f"<tr><td>{_esc(_human_label(item.get('id', '')))}</td>"
        f'<td class="status-{_esc(str(item.get("status", "")).lower())}">{_esc(item.get("status", ""))}</td>'
        f"<td>{_esc(_human_label(item.get('metric', '')))}</td>"
        f"<td>{_esc(_hypothesis_value(metrics, item))}</td></tr>"
        for item in hypotheses
        if isinstance(item, dict)
    )
    method_rows = "".join(
        f"<tr><th>{_esc(_human_label(key))}</th><td>{_esc(_fmt(value))}</td></tr>"
        for key, value in model.items()
        if value not in (None, "")
    )

    visual_sections = []
    for visual in visuals:
        kind = str(visual.get("kind") or "")
        content = (
            _chart_svg(visual)
            if kind == "chart.v1"
            else _table_html(visual)
            if kind == "table.v1"
            else _atomistic_html(visual)
            if kind == "atomistic.v1"
            else f"<pre>{_esc(json.dumps(visual, indent=2))}</pre>"
        )
        visual_sections.append(
            f'<section class="visual"><h2>{_esc(visual.get("title", visual.get("id", "Visualization")))}</h2>'
            f'<p class="description">{_esc(visual.get("description", ""))}</p>{content}'
            f'<p class="provenance">{_esc(kind)} · source node: {_esc(visual.get("source_node", "not recorded"))}</p></section>'
        )

    logo_html = '<div class="logo-fallback" aria-hidden="true">AF</div>'
    status_html = (
        ""
        if status.upper() == "SUCCESS"
        else f'<div class="status status-error">● RUN {_esc(status)}</div>'
    )
    run_problem = (
        ""
        if status.upper() == "SUCCESS"
        else f'<section class="panel run-problem"><h2>Run problem: {_esc(status)}</h2>'
        "<p>The experiment did not finish normally. Review execution errors before interpreting scientific results.</p></section>"
    )
    source_note = (
        f"Source bundle: {_esc(source_path)}"
        if source_path
        else "Source bundle: persisted AtomForge result"
    )

    styles = """
:root{color-scheme:dark;--bg:#09151b;--panel:#10252d;--line:#2b4b58;--text:#edf4f4;--muted:#9bb0b6;--accent:#f58d52;--good:#52d6a6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:38px 56px 80px}header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:30px}
.brand{display:flex;gap:14px;align-items:center;min-width:0}.logo-fallback{width:52px;height:52px;border:2px solid var(--accent);border-radius:14px;color:var(--accent);display:grid;place-items:center;font-weight:800;flex:0 0 auto}
h1{margin:0;font-size:30px;overflow-wrap:anywhere}h2{margin:0 0 6px;font-size:22px}h3{margin:22px 0 8px}.eyebrow,.label{color:var(--muted);text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}
.status{font-weight:700;white-space:nowrap}.status-error,.status-failed{color:#ff8c8c}.status-passed,.status-pass{color:var(--good)}.status-review{color:var(--accent)}
.panel,.visual{border:1px solid var(--line);background:rgba(16,37,45,.48);border-radius:12px;padding:24px;margin:22px 0}.verdict{padding:30px}.verdict h2{font-size:28px}.verdict p{font-size:17px;max-width:1050px}.verdict.pass{border-left:5px solid var(--good)}.verdict.review{border-left:5px solid var(--accent)}.run-problem{border-left:5px solid #ff8c8c}
.decision-heading{display:flex;justify-content:space-between;gap:24px;align-items:flex-start}.decision-scope{color:var(--muted);font-size:14px!important}.decision-badge{border:1px solid currentColor;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}.status-validated{color:var(--good)}.status-blocked{color:#ff8c8c}.decision-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:20px 0}.decision-facts>div{border:1px solid var(--line);background:#0b1b22;border-radius:8px;padding:12px}.decision-facts span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.decision-facts strong{display:block;margin-top:5px}.claim-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.evidence-chain{margin:30px 0}.evidence-step{padding:0;margin:10px 0}.evidence-step>summary{display:grid;grid-template-columns:minmax(180px,.7fr) auto minmax(240px,1.5fr);gap:16px;align-items:center;padding:17px 20px}.evidence-step[open]>summary{border-bottom:1px solid var(--line)}.evidence-step>summary small{font-weight:400}.evidence-step>h3,.evidence-step>p,.evidence-step>ul,.evidence-step>table,.evidence-step>.table-wrap{margin-left:20px;margin-right:20px}.evidence-step>*:last-child{margin-bottom:20px}
details>summary{cursor:pointer;font-size:18px;font-weight:700}a{color:#8bd7ff}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));border:1px solid var(--line);margin:18px 0}.metric{padding:18px;border-right:1px solid var(--line)}.metric span{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;margin-top:8px;font-size:24px}small{color:var(--muted);font-size:13px}
.table-wrap{max-width:100%;overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid var(--line);padding:11px 12px;vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.chart,.structure{width:100%;min-height:420px;display:block;background:#0b1b22;border:1px solid var(--line);border-radius:10px;margin-top:18px}.grid{stroke:#29434d;stroke-width:1}.series{stroke:var(--accent);stroke-width:3}.agreement{stroke:#8bd7ff;stroke-width:2;stroke-dasharray:8 6;opacity:.8}.point,.bar,.atom-point{fill:var(--accent)}.atom-point{stroke:#fff2c4;stroke-width:1}.vacancy-point{fill:#09151b;stroke:#f8d479;stroke-width:4;stroke-dasharray:5 3}.tick,.axis{fill:#b9cbd0;font-size:13px}.axis{font-size:14px}.description,.provenance{color:var(--muted)}.provenance{font-size:12px;margin:14px 0 0}.empty{padding:60px;text-align:center;color:var(--muted)}
.structure-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}.structure-summary>div{background:#0b1b22;border:1px solid var(--line);padding:15px;border-radius:8px}.structure-summary strong{display:block;margin-top:7px}pre{white-space:pre-wrap;overflow:auto;color:#c7d8dc}footer{color:var(--muted);margin-top:35px;font-size:12px}
@media(max-width:700px){main{padding:24px 18px 50px}header{display:block}.chart,.structure{min-height:280px}.decision-heading{display:block}.decision-badge{display:inline-block;margin-top:10px}.claim-grid{grid-template-columns:1fr}.evidence-step>summary{grid-template-columns:1fr auto}.evidence-step>summary small{grid-column:1/-1}}
@media print{ :root{color-scheme:light;--bg:#ffffff;--panel:#ffffff;--line:#cbd5e1;--text:#111827;--muted:#475569;--accent:#b45309;--good:#047857} body{background:#ffffff;color:#111827} main{max-width:none;padding:0} .panel,.visual{background:#ffffff;break-inside:avoid;box-shadow:none} .chart,.structure{background:#ffffff} a{color:#1d4ed8} footer{color:#475569} }
"""
    no_metrics = '<div class="metric"><span>Metrics</span><strong>None recorded</strong></div>'
    checks_html = (
        '<div class="table-wrap"><table><thead><tr><th>Check</th><th>Status</th><th>Metric</th><th>Value</th></tr></thead><tbody>'
        + hypothesis_rows
        + "</tbody></table></div>"
        if hypothesis_rows
        else '<p class="description">No acceptance checks were recorded.</p>'
    )
    model_html = (
        "<table><tbody>" + method_rows + "</tbody></table>"
        if method_rows
        else '<p class="description">No model provenance was recorded.</p>'
    )
    visuals_html = (
        "".join(visual_sections)
        or '<div class="panel"><p class="description">No visualizations were recorded in this bundle.</p></div>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>AtomForge report · {_esc(experiment_id)}</title><style>{styles}</style></head>"
        f'<body><main><header><div class="brand">{logo_html}<div><div class="eyebrow">AtomForge research report</div>'
        f"<h1>{_esc(experiment_id)}</h1></div></div>{status_html}</header>{run_problem}"
        f"{_decision_summary_html(bundle)}{_recorded_context_html(bundle)}"
        f"{_unit_glossary(metrics, visuals)}"
        f'<details class="panel"><summary>Raw recorded metrics</summary><div class="metrics">{metric_cards or no_metrics}</div></details>'
        f'<section class="panel"><h2>Checks used for this decision</h2>{checks_html}</section>'
        f'<details class="panel"><summary>Model and runtime details</summary>{model_html}</details>'
        f'<section><div class="eyebrow">Evidence and visualizations</div>{visuals_html}</section>'
        f"<footer>{source_note}. This report presents the recorded evidence and limits of this experiment.</footer>"
        "</main></body></html>"
    )


def build_html_report(
    experiment_id: str,
    *,
    root: Path | str = Path("."),
    input_path: Path | str | None = None,
    output_path: Path | str | None = None,
) -> Path:
    bundle, source = find_result_bundle(experiment_id, root=root, input_path=input_path)
    target = (
        Path(output_path)
        if output_path is not None
        else Path(root) / "experiments" / "reports" / f"{experiment_id}.html"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html_report(bundle, source_path=source), encoding="utf-8")
    return target
