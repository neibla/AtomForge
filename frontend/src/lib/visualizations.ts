import type {
  AtomisticVisualization,
  MetricResult,
  VisualizationSpec,
} from "@/types";

export type VisualizationGroup = "evidence" | "structures";

export interface LatticeStructurePoint {
  visualization: AtomisticVisualization;
  latticeParameter: number;
}

export interface StructureParameterPoint {
  visualization: AtomisticVisualization;
  value: number;
}

export interface StructureParameterSeries {
  key: string;
  label: string;
  unit: string;
  valueStyle: "decimal" | "signed";
  precision: number;
  points: StructureParameterPoint[];
}

const KIND_ORDER: Record<NonNullable<VisualizationSpec["kind"]>, number> = {
  "chart.v1": 0,
  "table.v1": 1,
  "atomistic.v1": 2,
  "image.v1": 3,
};

interface ParameterCandidate {
  visualization: AtomisticVisualization;
  value: number;
  seriesKey: string;
  label?: string;
  unit: string;
  valueStyle: StructureParameterSeries["valueStyle"];
}

function parameterCandidate(
  visualization: VisualizationSpec,
): ParameterCandidate | null {
  if (visualization.kind !== "atomistic.v1") return null;

  const metadata = visualization.data.metadata;
  const authoredValue = metadata?.scan_parameter_value;
  if (typeof authoredValue === "number" && Number.isFinite(authoredValue)) {
    return {
      visualization,
      value: authoredValue,
      seriesKey:
        typeof metadata?.scan_parameter_series === "string"
          ? metadata.scan_parameter_series
          : "metadata:parameter-scan",
      label:
        typeof metadata?.scan_parameter_label === "string"
          ? metadata.scan_parameter_label
          : undefined,
      unit:
        typeof metadata?.scan_parameter_unit === "string"
          ? metadata.scan_parameter_unit
          : "",
      valueStyle:
        metadata?.scan_parameter_signed === true ? "signed" : "decimal",
    };
  }

  const latticeParameter = metadata?.lattice_parameter_A;
  if (
    typeof latticeParameter === "number" &&
    Number.isFinite(latticeParameter)
  ) {
    const authoredSeries = metadata?.lattice_series;
    const structure = metadata?.structure;
    return {
      visualization,
      value: latticeParameter,
      seriesKey:
        typeof authoredSeries === "string"
          ? authoredSeries
          : typeof structure === "string"
            ? `structure:${structure}`
            : "metadata:lattice-parameter",
      label:
        typeof metadata?.scan_parameter_label === "string"
          ? metadata.scan_parameter_label
          : "Lattice parameter",
      unit: "Å",
      valueStyle: "decimal",
    };
  }

  return null;
}

export function latticeParameterForVisualization(
  visualization: VisualizationSpec,
): number | null {
  if (visualization.kind !== "atomistic.v1") return null;
  const value = visualization.data.metadata?.lattice_parameter_A;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function structureParameterSeries(
  visualizations: VisualizationSpec[],
): StructureParameterSeries | null {
  return structureParameterSeriesList(visualizations)[0] ?? null;
}

export function structureParameterSeriesList(
  visualizations: VisualizationSpec[],
): StructureParameterSeries[] {
  const groups = new Map<string, ParameterCandidate[]>();
  visualizations.forEach((visualization) => {
    const point = parameterCandidate(visualization);
    if (!point) return;
    const group = groups.get(point.seriesKey) ?? [];
    group.push(point);
    groups.set(point.seriesKey, group);
  });

  return [...groups.entries()]
    .filter(([, candidates]) => candidates.length > 1)
    .map(([key, candidates]) => {
      const first = candidates[0];
      const sorted = candidates
        .map(({ visualization, value }) => ({ visualization, value }))
        .sort((left, right) => left.value - right.value);
      const minimumSpacing = Math.min(
        ...sorted
          .slice(1)
          .map((point, index) => point.value - sorted[index].value),
      );
      return {
        key,
        label: first.label ?? "Scan coordinate",
        unit: first.unit,
        valueStyle: first.valueStyle,
        precision: Math.max(
          2,
          Math.min(10, Math.ceil(-Math.log10(minimumSpacing) - 1e-10)),
        ),
        points: sorted,
      };
    })
    .sort(
      (left, right) =>
        right.points.length - left.points.length ||
        left.key.localeCompare(right.key),
    );
}

export function latticeStructureSeries(
  visualizations: VisualizationSpec[],
): LatticeStructurePoint[] {
  const series = structureParameterSeries(visualizations);
  if (!series || !series.label.toLowerCase().includes("lattice")) return [];
  return series.points.map(({ visualization, value }) => ({
    visualization,
    latticeParameter: value,
  }));
}

export function visualizationGroup(
  visualization: VisualizationSpec,
): VisualizationGroup {
  return visualization.kind === "atomistic.v1" ? "structures" : "evidence";
}

export function visualizationLabel(visualization: VisualizationSpec): string {
  const parameter = parameterCandidate(visualization);
  if (parameter) {
    const value = formatParameterValue(
      parameter.value,
      parameter.unit,
      parameter.valueStyle,
    );
    if (parameter.valueStyle === "signed")
      return `Displaced structure · ${value}`;
    if (parameter.label?.toLowerCase().includes("lattice"))
      return `Structure · a = ${value}`;
    return `Structure · ${value}`;
  }
  if (
    visualization.kind === "atomistic.v1" &&
    visualization.source_node === "relax_reference"
  ) {
    return "Relaxed reference";
  }
  if (visualization.kind === "atomistic.v1" && visualization.source_node) {
    const sourceLabel = visualization.source_node
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
    return `Atomic structure · ${sourceLabel}`;
  }
  return visualization.title;
}

export function formatParameterValue(
  value: number,
  unit: string,
  style: StructureParameterSeries["valueStyle"],
  precision = 2,
): string {
  const normalized = Math.abs(value) < 1e-12 ? 0 : value;
  const numeric =
    style === "signed"
      ? `${normalized < 0 ? "−" : normalized > 0 ? "+" : ""}${Math.abs(normalized).toFixed(precision)}`
      : normalized.toFixed(precision);
  return `${numeric}${unit ? ` ${unit}` : ""}`;
}

export function contextualMetricEntries(
  metrics: Record<string, MetricResult>,
  visualization: VisualizationSpec,
  limit = 5,
): Array<[string, MetricResult]> {
  const eligible = Object.entries(metrics)
    .filter(
      ([name]) => !name.endsWith("_seed") && !name.endsWith("_runtime_ms"),
    )
    .sort(([left], [right]) => left.localeCompare(right));
  const sourcePrefix = visualization.source_node
    ? `${visualization.source_node}_`
    : null;
  const contextual = sourcePrefix
    ? eligible.filter(([name]) => name.startsWith(sourcePrefix))
    : [];
  return (contextual.length ? contextual : eligible).slice(0, limit);
}

export function contextualMetricLabel(
  name: string,
  visualization: VisualizationSpec,
): string {
  const sourcePrefix = visualization.source_node
    ? `${visualization.source_node}_`
    : null;
  const contextualName =
    sourcePrefix && name.startsWith(sourcePrefix)
      ? name.slice(sourcePrefix.length)
      : name;
  return contextualName.replaceAll("_", " ");
}

export function orderVisualizations(
  visualizations: VisualizationSpec[],
): VisualizationSpec[] {
  return [...visualizations].sort((left, right) => {
    const kindDelta =
      (left.kind ? KIND_ORDER[left.kind] : 99) -
      (right.kind ? KIND_ORDER[right.kind] : 99);
    if (kindDelta !== 0) return kindDelta;
    return left.title.localeCompare(right.title);
  });
}

export function selectVisualization(
  visualizations: VisualizationSpec[],
  selectedId: string | null,
): VisualizationSpec | null {
  const ordered = orderVisualizations(visualizations);
  return (
    ordered.find((visualization) => visualization.id === selectedId) ??
    ordered[0] ??
    null
  );
}

export function preferredVisualizationId(
  visualizations: VisualizationSpec[],
): string | null {
  return orderVisualizations(visualizations)[0]?.id ?? null;
}
