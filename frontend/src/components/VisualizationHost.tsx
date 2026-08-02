import { lazy, Suspense, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { isPkaExplorerData } from "@/lib/pkaExplorer";
import {
  decisionCalibrationText,
  decisionOutcomeLabel,
  decisionOutcomeTone,
  formatDecisionQualityCheck,
} from "@/lib/scientificDecision";
import {
  contextualMetricEntries,
  contextualMetricLabel,
  formatParameterValue,
  orderVisualizations,
  preferredVisualizationId,
  selectVisualization,
  structureParameterSeriesList,
  visualizationLabel,
} from "@/lib/visualizations";
import type { StructureParameterSeries } from "@/lib/visualizations";
import type {
  AtomisticVisualization,
  ColorMode,
  MetricResult,
  ScientificDecision,
  VisualizationCatalog,
  VisualizationSpec,
} from "@/types";

const AtomViewer = lazy(() => import("@/components/AtomViewer"));
const ChartViewer = lazy(() => import("@/components/ChartViewer"));
const TableViewer = lazy(() => import("@/components/TableViewer"));
const ImageViewer = lazy(() => import("@/components/ImageViewer"));
const PKAEventExplorer = lazy(() => import("@/components/PKAEventExplorer"));

interface VisualizationHostProps {
  catalog: VisualizationCatalog | null;
  experimentId: string;
  colorMode: ColorMode;
  onColorModeChange: (mode: ColorMode) => void;
  metrics?: Record<string, MetricResult>;
  decision?: ScientificDecision | null;
}

function LoadingRenderer() {
  return (
    <div className="flex h-full items-center justify-center bg-[#0b141a] text-sm text-[#7891a0]">
      Loading renderer…
    </div>
  );
}

function ParameterScanSelector({
  series,
  selectedId,
  onSelect,
}: {
  series: StructureParameterSeries;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const points = series.points;
  const selectedIndex = Math.max(
    0,
    points.findIndex(({ visualization }) => visualization.id === selectedId),
  );
  const selectedPoint = points[selectedIndex];
  const selectIndex = (index: number) => {
    const point = points[Math.min(Math.max(index, 0), points.length - 1)];
    if (point) onSelect(point.visualization.id);
  };
  const tickIndexes =
    points.length <= 9
      ? points.map((_, index) => index)
      : [
          0,
          points.reduce(
            (closest, point, index) =>
              Math.abs(point.value) < Math.abs(points[closest].value)
                ? index
                : closest,
            0,
          ),
          points.length - 1,
        ].filter(
          (index, position, indexes) => indexes.indexOf(index) === position,
        );
  const formattedValue = formatParameterValue(
    selectedPoint.value,
    series.unit,
    series.valueStyle,
    series.precision,
  );

  return (
    <div
      className="min-w-[17rem] max-w-[42rem] flex-1"
      role="group"
      aria-label={`${series.label} scan`}
    >
      <div className="mb-1.5 flex items-baseline justify-between gap-4">
        <span className="text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-[#8ea5af]">
          {series.label}
        </span>
        <output className="data-value text-sm font-semibold text-[#fff2e9]">
          {formattedValue}
        </output>
      </div>
      <div className="grid grid-cols-[2.75rem_minmax(12rem,1fr)_2.75rem] items-center gap-2">
        <button
          type="button"
          aria-label={`Previous ${series.label.toLowerCase()} value`}
          disabled={selectedIndex === 0}
          onClick={() => selectIndex(selectedIndex - 1)}
          className="grid h-11 w-11 place-items-center rounded border border-[#3a5662] text-[#c4d2d5] transition hover:border-[#d5794f] hover:text-[#fff2e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f] disabled:cursor-not-allowed disabled:opacity-35"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0">
          <input
            type="range"
            min={0}
            max={points.length - 1}
            step={1}
            value={selectedIndex}
            onChange={(event) => selectIndex(Number(event.target.value))}
            aria-label={series.label}
            aria-valuetext={formattedValue}
            className="parameter-range block h-5 w-full cursor-pointer appearance-none bg-transparent"
          />
          <div className="relative h-3.5 px-0.5" aria-hidden="true">
            {tickIndexes.map((index) => {
              const point = points[index];
              const position =
                points.length === 1 ? 0 : (index / (points.length - 1)) * 100;
              return (
                <span
                  key={point.visualization.id}
                  style={{
                    left: `${position}%`,
                    transform:
                      index === 0
                        ? "translateX(0)"
                        : index === points.length - 1
                          ? "translateX(-100%)"
                          : "translateX(-50%)",
                  }}
                  className={cn(
                    "data-value absolute top-0 text-[0.56rem] tabular-nums",
                    index === selectedIndex
                      ? "text-[#f2a379]"
                      : "text-[#6f8791]",
                  )}
                >
                  {formatParameterValue(
                    point.value,
                    series.unit,
                    series.valueStyle,
                    series.precision,
                  )}
                </span>
              );
            })}
          </div>
        </div>
        <button
          type="button"
          aria-label={`Next ${series.label.toLowerCase()} value`}
          disabled={selectedIndex === points.length - 1}
          onClick={() => selectIndex(selectedIndex + 1)}
          className="grid h-11 w-11 place-items-center rounded border border-[#3a5662] text-[#c4d2d5] transition hover:border-[#d5794f] hover:text-[#fff2e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f] disabled:cursor-not-allowed disabled:opacity-35"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function renderVisualization(
  visualization: VisualizationSpec,
  experimentId: string,
  colorMode: ColorMode,
) {
  switch (visualization.kind) {
    case "atomistic.v1":
      return isPkaExplorerData(visualization.data) ? (
        <PKAEventExplorer data={visualization.data} colorMode={colorMode} />
      ) : (
        <AtomViewer
          data={visualization.data}
          colorMode={colorMode}
          title={visualizationLabel(visualization)}
          description={visualization.description}
        />
      );
    case "chart.v1":
      return <ChartViewer visualization={visualization} />;
    case "table.v1":
      return <TableViewer visualization={visualization} />;
    case "image.v1":
      return (
        <ImageViewer
          experimentId={experimentId}
          visualization={visualization}
        />
      );
  }
}

export default function VisualizationHost({
  catalog,
  experimentId,
  colorMode,
  onColorModeChange,
  metrics = {},
  decision = null,
}: VisualizationHostProps) {
  const visualizations = useMemo(
    () => orderVisualizations(catalog?.visualizations ?? []),
    [catalog],
  );
  const preferredId = useMemo(
    () => preferredVisualizationId(visualizations),
    [visualizations],
  );
  const parameterSeries = useMemo(
    () => structureParameterSeriesList(visualizations),
    [visualizations],
  );
  const parameterIds = useMemo(
    () =>
      new Set(
        parameterSeries.flatMap((series) =>
          series.points.map(({ visualization }) => visualization.id),
        ),
      ),
    [parameterSeries],
  );
  const ungroupedVisualizations = useMemo(
    () =>
      visualizations.filter(
        (visualization) => !parameterIds.has(visualization.id),
      ),
    [parameterIds, visualizations],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const effectiveSelectedId =
    selectedId &&
    visualizations.some((visualization) => visualization.id === selectedId)
      ? selectedId
      : preferredId;

  const selected = selectVisualization(visualizations, effectiveSelectedId);
  const atomistic = selected?.kind === "atomistic.v1" ? selected : null;
  const effectiveColorMode =
    atomistic && !availableColorModes(atomistic).includes(colorMode)
      ? "element"
      : colorMode;
  const selectedParameterSeries = selected
    ? (parameterSeries.find((series) =>
        series.points.some(
          ({ visualization }) => visualization.id === selected.id,
        ),
      ) ?? null)
    : null;
  const showArtifactTabs =
    ungroupedVisualizations.length > 0 || parameterSeries.length > 1;
  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center bg-[#0b141a] text-sm text-[#7891a0]">
        No visualization artifacts
      </div>
    );
  }

  return (
    <div className="flex h-auto min-h-[calc(100vh-8rem)] flex-col overflow-visible bg-[#0b141a]">
      <div className="relative flex flex-wrap items-center gap-3 border-b border-[#35515e] bg-[#0e1920] px-5 py-2.5 lg:px-8">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
          {showArtifactTabs ? (
            <div
              className="flex min-w-0 flex-wrap gap-1.5"
              role="group"
              aria-label="Visualization artifacts"
            >
              {ungroupedVisualizations.map((visualization) => (
                <button
                  type="button"
                  aria-pressed={selected.id === visualization.id}
                  key={visualization.id}
                  onClick={() => setSelectedId(visualization.id)}
                  className={cn(
                    "min-h-11 rounded-md border px-3 py-1.5 text-[0.76rem] font-semibold leading-none transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]",
                    selected.id === visualization.id
                      ? "border-[#d5794f] bg-[#462b20] text-[#fff2e9] shadow-[inset_0_0_0_1px_rgba(213,121,79,0.15)]"
                      : "border-[#3a5662] bg-[#101d24] text-[#c4d2d5] hover:border-[#6d8993] hover:bg-[#172832] hover:text-white",
                  )}
                  title={visualizationLabel(visualization)}
                >
                  {visualizationLabel(visualization)}
                </button>
              ))}
              {parameterSeries.map((series) => {
                const active = selectedParameterSeries?.key === series.key;
                return (
                  <button
                    type="button"
                    aria-pressed={active}
                    key={series.key}
                    onClick={() => {
                      const crossesZero =
                        series.points[0].value <= 0 &&
                        series.points[series.points.length - 1].value >= 0;
                      const target = crossesZero
                        ? 0
                        : (series.points[0].value +
                            series.points[series.points.length - 1].value) /
                          2;
                      const referencePoint = series.points.reduce(
                        (closest, point) =>
                          Math.abs(point.value - target) <
                          Math.abs(closest.value - target)
                            ? point
                            : closest,
                      );
                      setSelectedId(referencePoint.visualization.id);
                    }}
                    className={cn(
                      "min-h-11 rounded-md border px-3 py-1.5 text-[0.76rem] font-semibold leading-none transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]",
                      active
                        ? "border-[#d5794f] bg-[#462b20] text-[#fff2e9] shadow-[inset_0_0_0_1px_rgba(213,121,79,0.15)]"
                        : "border-[#3a5662] bg-[#101d24] text-[#c4d2d5] hover:border-[#6d8993] hover:bg-[#172832] hover:text-white",
                    )}
                  >
                    {series.label}
                  </button>
                );
              })}
            </div>
          ) : null}
          {selectedParameterSeries ? (
            <ParameterScanSelector
              series={selectedParameterSeries}
              selectedId={selected.id}
              onSelect={setSelectedId}
            />
          ) : null}
        </div>
        {atomistic ? (
          <div className="ml-auto flex shrink-0 items-center">
            <AtomisticControls
              visualization={atomistic}
              colorMode={effectiveColorMode}
              onColorModeChange={onColorModeChange}
            />
          </div>
        ) : (
          <span className="sr-only">
            {selected.kind} · {selected.source_node ?? "unknown source"}
          </span>
        )}
      </div>
      {!(atomistic && isPkaExplorerData(atomistic.data)) ? (
        <EvidenceSummary
          metrics={metrics}
          decision={decision}
          visualization={selected}
        />
      ) : null}
      <div className="h-[70vh] min-h-[32rem] max-h-[52rem] min-w-0 flex-none overflow-hidden">
        <Suspense fallback={<LoadingRenderer />}>
          {renderVisualization(selected, experimentId, effectiveColorMode)}
        </Suspense>
      </div>
    </div>
  );
}

function EvidenceSummary({
  metrics,
  decision,
  visualization,
}: {
  metrics: Record<string, MetricResult>;
  decision: ScientificDecision | null;
  visualization: VisualizationSpec;
}) {
  const visibleEntries = contextualMetricEntries(metrics, visualization);
  if (!visibleEntries.length && !decision) return null;

  return (
    <section className="shrink-0 border-b border-[#35515e] bg-[#0e1920]">
      {visibleEntries.length ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5">
          {visibleEntries.map(([name, metric], index) => (
            <div
              key={name}
              className={cn(
                "border-b border-[#263b46] px-4 py-2.5 xl:border-b-0",
                index > 0 ? "xl:border-l" : "",
              )}
            >
              <p
                className="truncate text-[0.59rem] font-semibold uppercase tracking-[0.1em] text-[#7891a0]"
                title={contextualMetricLabel(name, visualization)}
              >
                {contextualMetricLabel(name, visualization)}
              </p>
              <p className="mt-1 font-mono text-sm font-semibold text-[#eff8f4]">
                {formatNumber(metric.val)}{" "}
                <span className="text-[0.61rem] font-normal text-[#9bb0b8]">
                  {metric.unit}
                </span>
              </p>
            </div>
          ))}
        </div>
      ) : null}
      {decision ? <CompactDecision decision={decision} /> : null}
    </section>
  );
}

function CompactDecision({ decision }: { decision: ScientificDecision }) {
  const outcomeTone = decisionOutcomeTone(decision.outcome);
  const statusClasses = {
    success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    warning: "border-amber-500/40 bg-amber-500/10 text-amber-200",
    danger: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  }[outcomeTone];
  const calibrationText = decisionCalibrationText(decision);

  return (
    <div className="border-t border-[#263b46] px-5 py-2.5 lg:px-8">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 font-mono text-[0.61rem] font-semibold",
            statusClasses,
          )}
        >
          {decisionOutcomeLabel(decision.outcome)}
        </span>
        <span className="min-w-0 flex-1 text-sm font-medium text-[#e5efeb]">
          {decision.headline}
        </span>
        <span className="font-mono text-[0.66rem] text-[#9bb0b8]">
          {calibrationText ?? "Calibration not recorded"}
        </span>
        <details className="group">
          <summary className="cursor-pointer list-none text-[0.68rem] font-semibold text-[#b9c9ce] hover:text-white">
            Details{" "}
            <span className="font-mono text-[#d88a52] group-open:hidden">
              +
            </span>
            <span className="hidden font-mono text-[#d88a52] group-open:inline">
              −
            </span>
          </summary>
          <div className="mt-3 grid gap-3 border-t border-[#2f4853] pt-3 lg:grid-cols-[1fr_1fr_1.15fr]">
            <DecisionList
              title="Quality checks"
              items={(decision.quality_checks ?? []).map(
                formatDecisionQualityCheck,
              )}
            />
            <DecisionList
              title="What this establishes"
              items={decision.supported_claims ?? []}
            />
            <DecisionList
              title="Explicit limits"
              items={decision.limitations}
            />
          </div>
        </details>
      </div>
      <p className="mt-2 text-[0.68rem] leading-relaxed text-[#91a5ad]">
        {decision.scope}
      </p>
    </div>
  );
}

function DecisionList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-[#7891a0]">
        {title}
      </p>
      <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-[#b5c5c9]">
        {items.map((item) => (
          <li key={item}>— {item}</li>
        ))}
      </ul>
    </div>
  );
}

function availableColorModes(
  visualization: AtomisticVisualization,
): ColorMode[] {
  const atoms = visualization.data;
  const modes: ColorMode[] = ["element"];
  if (atoms.energies?.length) modes.push("energy");
  if (
    (atoms.vacancy_positions?.length ?? 0) > 0 ||
    (atoms.interstitial_positions?.length ?? 0) > 0 ||
    (atoms.trajectory?.length ?? 0) > 1
  ) {
    modes.push("defect");
  }
  return modes;
}

function AtomisticControls({
  visualization,
  colorMode,
  onColorModeChange,
}: {
  visualization: AtomisticVisualization;
  colorMode: ColorMode;
  onColorModeChange: (mode: ColorMode) => void;
}) {
  const modes = availableColorModes(visualization);
  if (modes.length < 2) return null;

  return (
    <div
      className="flex gap-1 rounded-lg border border-[#3a5662] bg-[#0b141a] p-1"
      role="group"
      aria-label="Atom color mapping"
    >
      {modes.map((mode) => (
        <button
          type="button"
          key={mode}
          aria-pressed={colorMode === mode}
          onClick={() => onColorModeChange(mode)}
          title={`Color atoms by ${mode}`}
          className={cn(
            "min-h-11 rounded-md px-3 py-2 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]",
            colorMode === mode
              ? "bg-[#304b58] text-[#ffab7d] shadow-sm"
              : "text-[#c4d2d5] hover:bg-[#172832] hover:text-white",
          )}
        >
          {mode === "defect" ? "defect map" : mode}
        </button>
      ))}
    </div>
  );
}

function formatNumber(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 5 });
}
