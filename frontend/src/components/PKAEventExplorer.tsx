import { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Ghost,
  Pause,
  Play,
  RotateCcw,
  Route,
  SlidersHorizontal,
  Waves,
} from "lucide-react";

import AtomViewer from "@/components/AtomViewer";
import { numericRange } from "@/lib/utils";
import {
  buildExplorerFrames,
  type AtomFilter,
  type ExplorerFrameMetric,
} from "@/lib/pkaExplorer";
import { cn } from "@/lib/utils";
import type { AtomisticVisualizationData, ColorMode } from "@/types";

interface PKAEventExplorerProps {
  data: AtomisticVisualizationData;
  colorMode: ColorMode;
}

type EvidencePanel = "summary" | "vacancies" | "interstitials";

const FILTERS: Array<{ value: AtomFilter; label: string; swatch: string }> = [
  { value: "all", label: "All atoms", swatch: "#dce8e7" },
  { value: "displaced", label: "Displaced", swatch: "#c478ff" },
  { value: "defects", label: "Defects", swatch: "#ffb85c" },
  { value: "neighbourhood", label: "PKA zone", swatch: "#45e0c1" },
];

const PLOT_COLORS = {
  energy: "#b879ff",
  temperature: "#45e0c1",
  vacancies: "#ffb85c",
  interstitials: "#ff718d",
};

function formatNumber(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (
    Math.abs(value) >= 10_000 ||
    (Math.abs(value) > 0 && Math.abs(value) < 0.01)
  ) {
    return value.toExponential(2);
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function timeLabel(time: number | null | undefined, frame: number): string {
  if (time === null || time === undefined)
    return `FRAME ${String(frame).padStart(3, "0")}`;
  return time >= 1_000
    ? `${(time / 1_000).toFixed(2)} ps`
    : `${time.toFixed(1)} fs`;
}

function MetricPlot({
  title,
  unit,
  frames,
  frame,
  series,
}: {
  title: string;
  unit: string;
  frames: ExplorerFrameMetric[];
  frame: number;
  series: Array<{
    color: string;
    label: string;
    value: (metric: ExplorerFrameMetric) => number | null;
  }>;
}) {
  const width = 520;
  const height = 142;
  const margin = { left: 42, right: 12, top: 24, bottom: 22 };
  const allValues = series
    .flatMap((item) => frames.map(item.value))
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
  const range = numericRange(allValues, { min: 0, max: 1 });
  const min = Math.min(range.min, 0);
  const max = Math.max(range.max, 1);
  const span = max - min || 1;
  const x = (index: number) =>
    margin.left +
    (index / Math.max(frames.length - 1, 1)) *
      (width - margin.left - margin.right);
  const y = (value: number) =>
    margin.top + ((max - value) / span) * (height - margin.top - margin.bottom);
  const current = frames[frame];

  return (
    <section className="pka-plot min-h-0 border-b border-[#263b46] px-4 py-3 last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Waves className="h-3.5 w-3.5 text-[#7891a0]" />
          <h4 className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-[#dfe9e8]">
            {title}
          </h4>
        </div>
        <div className="flex items-center gap-3 text-[0.61rem] text-[#7891a0]">
          {series.map((item) => (
            <span key={item.label} className="flex items-center gap-1.5">
              <span
                className="h-1.5 w-3 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              {item.label}
            </span>
          ))}
          <span className="pka-mono text-[#7891a0]">{unit}</span>
        </div>
      </div>
      {allValues.length ? (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="mt-2 h-[calc(100%-1.7rem)] min-h-20 w-full"
          role="img"
          aria-label={`${title} across the cascade trajectory`}
        >
          {[0, 0.5, 1].map((fraction) => {
            const value = min + span * fraction;
            return (
              <g key={fraction}>
                <line
                  x1={margin.left}
                  x2={width - margin.right}
                  y1={y(value)}
                  y2={y(value)}
                  stroke="#263b46"
                  strokeWidth="1"
                />
                <text
                  x={margin.left - 8}
                  y={y(value) + 3}
                  textAnchor="end"
                  fill="#7891a0"
                  fontSize="9"
                  fontFamily="ui-monospace, monospace"
                >
                  {formatNumber(value, 1)}
                </text>
              </g>
            );
          })}
          {series.map((item) => {
            const points = frames
              .flatMap((metric, index) => {
                const value = item.value(metric);
                return value === null ? [] : [`${x(index)},${y(value)}`];
              })
              .join(" ");
            return (
              <polyline
                key={item.label}
                points={points}
                fill="none"
                stroke={item.color}
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}
          <line
            x1={x(frame)}
            x2={x(frame)}
            y1={margin.top}
            y2={height - margin.bottom}
            stroke="#eaf5f2"
            strokeDasharray="2 3"
            opacity="0.85"
          />
          {series.map((item) => {
            const value = current ? item.value(current) : null;
            return value === null ? null : (
              <circle
                key={item.label}
                cx={x(frame)}
                cy={y(value)}
                r="3.8"
                fill="#0d171e"
                stroke={item.color}
                strokeWidth="2"
              />
            );
          })}
        </svg>
      ) : (
        <div className="flex h-20 items-center text-xs text-[#7891a0]">
          No time series emitted by this run
        </div>
      )}
    </section>
  );
}

function CoordinateTable({
  title,
  prefix,
  positions,
}: {
  title: string;
  prefix: string;
  positions: number[][];
}) {
  return (
    <div className="min-h-0 overflow-hidden">
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-[#dfe9e8]">
          {title}
        </h4>
        <span className="pka-mono text-[0.62rem] text-[#7891a0]">
          {positions.length} detected
        </span>
      </div>
      <div className="custom-scrollbar max-h-32 overflow-auto border-y border-[#263b46]">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 bg-[#14232b] text-[0.61rem] uppercase tracking-[0.08em] text-[#7891a0]">
            <tr>
              <th className="px-3 py-2 font-medium">Site</th>
              <th className="px-3 py-2 font-medium">x (Å)</th>
              <th className="px-3 py-2 font-medium">y (Å)</th>
              <th className="px-3 py-2 font-medium">z (Å)</th>
            </tr>
          </thead>
          <tbody className="pka-mono text-[#cbdad8]">
            {positions.length ? (
              positions.map((position, index) => (
                <tr
                  key={`${prefix}-${index}`}
                  className="border-t border-[#20343e] hover:bg-[#192c35]"
                >
                  <td className="px-3 py-2 text-[#ffb85c]">
                    {prefix}-{String(index + 1).padStart(3, "0")}
                  </td>
                  {position.slice(0, 3).map((value, coordinate) => (
                    <td key={coordinate} className="px-3 py-2">
                      {value.toFixed(3)}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td
                  colSpan={4}
                  className="px-3 py-5 text-center font-sans text-xs text-[#7891a0]"
                >
                  No {title.toLowerCase()} at this frame
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  unit,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  accent: string;
}) {
  return (
    <div className="pka-metric relative min-h-[74px] border border-[#263b46] bg-[#111e25] px-3 py-3">
      <span
        className="absolute left-0 top-0 h-full w-0.5"
        style={{ backgroundColor: accent }}
      />
      <div className="text-[0.6rem] font-semibold uppercase tracking-[0.11em] text-[#7891a0]">
        {label}
      </div>
      <div className="pka-mono mt-2 text-lg font-semibold tracking-tight text-[#eff8f4]">
        {value}
        <span className="ml-1 text-[0.65rem] font-normal text-[#7891a0]">
          {unit}
        </span>
      </div>
    </div>
  );
}

function EvidenceSummary({
  current,
}: {
  current: ExplorerFrameMetric | undefined;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
      <MetricCard
        label="Kinetic energy"
        value={formatNumber(current?.kinetic_energy_ev ?? null)}
        unit="eV"
        accent={PLOT_COLORS.energy}
      />
      <MetricCard
        label="Temperature"
        value={formatNumber(current?.temperature_K ?? null, 0)}
        unit="K"
        accent={PLOT_COLORS.temperature}
      />
      <MetricCard
        label="Displaced atoms"
        value={formatNumber(current?.displaced_atoms ?? null, 0)}
        accent="#c478ff"
      />
      <MetricCard
        label="Max displacement"
        value={formatNumber(current?.max_displacement_angstrom ?? null)}
        unit="Å"
        accent="#ffb85c"
      />
      <MetricCard
        label="Vacancies"
        value={formatNumber(current?.n_defects ?? null, 0)}
        accent={PLOT_COLORS.vacancies}
      />
      <MetricCard
        label="Interstitials"
        value={formatNumber(current?.interstitials ?? null, 0)}
        accent={PLOT_COLORS.interstitials}
      />
    </div>
  );
}

export default function PKAEventExplorer({
  data,
  colorMode,
}: PKAEventExplorerProps) {
  const frames = useMemo(() => buildExplorerFrames(data), [data]);
  const maxFrame = Math.max(frames.length - 1, 0);
  const [frame, setFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [filter, setFilter] = useState<AtomFilter>("all");
  const [showInitial, setShowInitial] = useState(false);
  const [showTrails, setShowTrails] = useState(true);
  const [evidencePanel, setEvidencePanel] = useState<EvidencePanel>("summary");
  const current = frames[Math.min(frame, maxFrame)];

  useEffect(() => {
    if (!isPlaying || maxFrame === 0) return;
    const interval = window.setInterval(() => {
      setFrame((previous) => (previous >= maxFrame ? 0 : previous + 1));
    }, 180);
    return () => window.clearInterval(interval);
  }, [isPlaying, maxFrame]);

  const eventFrames = frames.flatMap((metric, index) => {
    if (index === 0) return metric.n_defects ? [index] : [];
    const previous = frames[index - 1];
    return metric.n_defects !== previous.n_defects ||
      metric.interstitials !== previous.interstitials
      ? [index]
      : [];
  });
  const eventCount = eventFrames.length;
  const currentTime = timeLabel(current?.time_fs, frame);

  return (
    <div className="pka-shell flex h-full min-h-0 flex-col bg-[#0b141a] text-[#dfe9e8]">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-[#263b46] bg-[#0d171e] px-5 py-4 lg:px-7">
        <div className="flex min-w-0 items-center gap-4">
          <div className="pka-mark flex h-9 w-9 shrink-0 items-center justify-center border border-[#b879ff]/70 bg-[#211a31] text-[#c891ff]">
            <CircleDot className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6rem] font-semibold uppercase tracking-[0.16em] text-[#7891a0]">
              <span>ATOMFORGE</span>
              <span className="text-[#45e0c1]">/</span>
              <span>RADIATION EVENT</span>
            </div>
            <h3 className="mt-1 truncate text-lg font-semibold tracking-tight text-[#eff8f4]">
              PKA Event Explorer
            </h3>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-2 border border-[#263b46] bg-[#111e25] px-3 py-2 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-[#45e0c1] shadow-[0_0_10px_#45e0c1]" />
            <span className="text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-[#b6c8c5]">
              Linked evidence
            </span>
          </div>
          <div className="pka-mono border border-[#263b46] bg-[#111e25] px-3 py-2 text-[0.65rem] text-[#b6c8c5]">
            {data.positions.length.toLocaleString()} atoms
          </div>
        </div>
      </header>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="border-b border-[#263b46] bg-[#101c23] px-5 py-3 lg:px-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[0.61rem] font-semibold uppercase tracking-[0.15em] text-[#7891a0]">
                Primary knock-on cascade
              </p>
              <p className="mt-1 text-xs text-[#9bb0ae]">
                Atomic motion, thermodynamics, and Wigner–Seitz defects share
                one clock.
              </p>
            </div>
            <div
              className="flex flex-wrap items-center gap-1.5"
              aria-label="Atom visibility filter"
            >
              {FILTERS.map((item) => (
                <button
                  type="button"
                  key={item.value}
                  onClick={() => setFilter(item.value)}
                  aria-pressed={filter === item.value}
                  className={cn(
                    "pka-filter flex min-h-8 items-center gap-2 border px-2.5 text-[0.63rem] font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b879ff]",
                    filter === item.value
                      ? "border-[#b879ff] bg-[#2a1f3e] text-[#f0e4ff]"
                      : "border-[#263b46] bg-[#111e25] text-[#8fa8a7] hover:border-[#506673] hover:text-[#eff8f4]",
                  )}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: item.swatch }}
                  />
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <main className="grid min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1.35fr)_minmax(390px,0.65fr)]">
          <section className="pka-viewport relative min-h-[440px] overflow-hidden border-b border-[#263b46] xl:min-h-[570px] xl:border-r">
            <AtomViewer
              data={data}
              colorMode={colorMode}
              frame={frame}
              onFrameChange={setFrame}
              filterMode={filter}
              showInitialPositions={showInitial}
              showTrails={showTrails}
              showViewportControls={false}
            />
            <div className="pointer-events-none absolute left-5 top-5 flex items-start gap-3">
              <div className="border-l-2 border-[#b879ff] bg-[#0d171e]/90 px-3 py-2 backdrop-blur-sm">
                <p className="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-[#7891a0]">
                  Current frame
                </p>
                <p className="pka-mono mt-1 text-xl font-semibold text-[#f0e4ff]">
                  {currentTime}
                </p>
              </div>
              <div className="hidden border border-[#263b46] bg-[#0d171e]/90 px-3 py-2 backdrop-blur-sm sm:block">
                <p className="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-[#7891a0]">
                  Event state
                </p>
                <p className="pka-mono mt-1 text-xs text-[#45e0c1]">
                  {current?.displaced_atoms ?? 0} displaced
                </p>
              </div>
            </div>
            <div className="absolute bottom-5 left-5 right-5 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-1 border border-[#263b46] bg-[#0d171e]/95 p-1 backdrop-blur-sm">
                <button
                  type="button"
                  onClick={() => setShowInitial((value) => !value)}
                  aria-pressed={showInitial}
                  className={cn(
                    "flex min-h-8 items-center gap-1.5 px-2.5 text-[0.63rem] transition focus-visible:outline-2 focus-visible:outline-[#b879ff]",
                    showInitial
                      ? "bg-[#273641] text-[#eff8f4]"
                      : "text-[#8fa8a7] hover:text-[#eff8f4]",
                  )}
                >
                  <Ghost className="h-3.5 w-3.5" /> Initial sites
                </button>
                <button
                  type="button"
                  onClick={() => setShowTrails((value) => !value)}
                  aria-pressed={showTrails}
                  className={cn(
                    "flex min-h-8 items-center gap-1.5 px-2.5 text-[0.63rem] transition focus-visible:outline-2 focus-visible:outline-[#b879ff]",
                    showTrails
                      ? "bg-[#2a1f3e] text-[#e5d3ff]"
                      : "text-[#8fa8a7] hover:text-[#eff8f4]",
                  )}
                >
                  <Route className="h-3.5 w-3.5" /> Trails
                </button>
              </div>
              <div className="pka-mono border border-[#263b46] bg-[#0d171e]/95 px-3 py-2 text-[0.61rem] text-[#7891a0] backdrop-blur-sm">
                {filter.toUpperCase()} / {colorMode.toUpperCase()}
              </div>
            </div>
          </section>

          <aside className="grid min-h-0 grid-rows-3 border-b border-[#263b46] bg-[#0e1920] xl:border-b-0">
            <MetricPlot
              title="Kinetic energy"
              unit="eV"
              frames={frames}
              frame={frame}
              series={[
                {
                  color: PLOT_COLORS.energy,
                  label: "Total",
                  value: (metric) => metric.kinetic_energy_ev,
                },
              ]}
            />
            <MetricPlot
              title="Temperature"
              unit="K"
              frames={frames}
              frame={frame}
              series={[
                {
                  color: PLOT_COLORS.temperature,
                  label: "Instantaneous",
                  value: (metric) => metric.temperature_K,
                },
              ]}
            />
            <MetricPlot
              title="Defect population"
              unit="count"
              frames={frames}
              frame={frame}
              series={[
                {
                  color: PLOT_COLORS.vacancies,
                  label: "Vacancies",
                  value: (metric) => metric.n_defects,
                },
                {
                  color: PLOT_COLORS.interstitials,
                  label: "Interstitials",
                  value: (metric) => metric.interstitials,
                },
              ]}
            />
          </aside>
        </main>

        <section className="border-b border-[#263b46] bg-[#0d171e] px-5 py-3 lg:px-7">
          <div className="flex items-center gap-3">
            <div className="flex shrink-0 items-center gap-0.5 border border-[#263b46] bg-[#111e25] p-1">
              <button
                type="button"
                onClick={() => {
                  setFrame(0);
                  setIsPlaying(false);
                }}
                className="flex h-8 w-8 items-center justify-center text-[#8fa8a7] hover:bg-[#243641] hover:text-[#eff8f4]"
                title="Reset"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setFrame((value) => Math.max(0, value - 1))}
                className="flex h-8 w-8 items-center justify-center text-[#8fa8a7] hover:bg-[#243641] hover:text-[#eff8f4]"
                title="Previous frame"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setIsPlaying((value) => !value)}
                className="flex h-8 w-8 items-center justify-center bg-[#b879ff] text-[#130e1b] hover:bg-[#ca99ff]"
                title={isPlaying ? "Pause" : "Play"}
              >
                {isPlaying ? (
                  <Pause className="h-3.5 w-3.5" />
                ) : (
                  <Play className="ml-0.5 h-3.5 w-3.5" />
                )}
              </button>
              <button
                type="button"
                onClick={() =>
                  setFrame((value) => Math.min(maxFrame, value + 1))
                }
                className="flex h-8 w-8 items-center justify-center text-[#8fa8a7] hover:bg-[#243641] hover:text-[#eff8f4]"
                title="Next frame"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            <div className="hidden w-24 shrink-0 sm:block">
              <p className="pka-mono text-[0.65rem] font-semibold text-[#eff8f4]">
                {String(frame).padStart(3, "0")} /{" "}
                {String(maxFrame).padStart(3, "0")}
              </p>
              <p className="mt-0.5 text-[0.6rem] uppercase tracking-[0.1em] text-[#7891a0]">
                shared timeline
              </p>
            </div>
            <div className="relative flex-1">
              <div className="pointer-events-none absolute inset-x-1 top-1/2 h-px -translate-y-1/2 bg-[#3b5360]" />
              {eventFrames.map((eventFrame) => (
                <button
                  type="button"
                  key={eventFrame}
                  onClick={() => setFrame(eventFrame)}
                  aria-label={`Jump to event frame ${eventFrame}`}
                  className="absolute top-1/2 z-10 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#0d171e] bg-[#ffb85c] shadow-[0_0_8px_#ffb85c]"
                  style={{
                    left: `${(eventFrame / Math.max(maxFrame, 1)) * 100}%`,
                  }}
                />
              ))}
              <input
                aria-label="PKA frame"
                type="range"
                min="0"
                max={maxFrame}
                value={frame}
                onChange={(event) => setFrame(Number(event.target.value))}
                className="pka-range relative h-9 w-full cursor-pointer appearance-none bg-transparent"
              />
            </div>
            <div className="hidden shrink-0 items-center gap-2 text-right sm:flex">
              <div className="h-1.5 w-1.5 rounded-full bg-[#ffb85c]" />
              <span className="pka-mono text-[0.61rem] text-[#7891a0]">
                {eventCount} defect events
              </span>
            </div>
          </div>
        </section>

        <section className="border-b border-[#263b46] bg-[#101c23] px-5 py-4 lg:px-7">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[0.6rem] font-semibold uppercase tracking-[0.15em] text-[#7891a0]">
                Frame evidence
              </p>
              <h4 className="mt-1 text-sm font-semibold text-[#eff8f4]">
                Synchronized state at {currentTime}
              </h4>
            </div>
            <div className="flex items-center gap-2 text-[0.61rem] text-[#7891a0]">
              <SlidersHorizontal className="h-3.5 w-3.5" /> Click a timeline
              marker to inspect a defect transition
            </div>
          </div>
          <div
            className="mb-4 flex items-center gap-5 border-b border-[#263b46]"
            role="tablist"
            aria-label="Frame evidence"
          >
            {(
              [
                ["summary", "Snapshot"],
                [
                  "vacancies",
                  `Vacancies ${current?.vacancy_positions.length ?? 0}`,
                ],
                [
                  "interstitials",
                  `Interstitials ${current?.interstitial_positions.length ?? 0}`,
                ],
              ] as Array<[EvidencePanel, string]>
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={evidencePanel === id}
                onClick={() => setEvidencePanel(id)}
                className={cn(
                  "min-h-9 border-b-2 px-0.5 text-[0.63rem] font-semibold uppercase tracking-[0.1em] transition focus-visible:outline-2 focus-visible:outline-[#b879ff]",
                  evidencePanel === id
                    ? "border-[#b879ff] text-[#e9d5ff]"
                    : "border-transparent text-[#7891a0] hover:text-[#eff8f4]",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          {evidencePanel === "summary" ? (
            <EvidenceSummary current={current} />
          ) : null}
          {evidencePanel === "vacancies" ? (
            <CoordinateTable
              title="Vacancies"
              prefix="V"
              positions={current?.vacancy_positions ?? []}
            />
          ) : null}
          {evidencePanel === "interstitials" ? (
            <CoordinateTable
              title="Interstitials"
              prefix="I"
              positions={current?.interstitial_positions ?? []}
            />
          ) : null}
        </section>
      </div>
    </div>
  );
}
