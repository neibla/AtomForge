import { useMemo } from "react";

import { numericRange } from "@/lib/utils";
import type { ChartVisualization, VisualizationValue } from "@/types";

const WIDTH = 900;
const HEIGHT = 500;
const MARGIN = { top: 42, right: 40, bottom: 92, left: 132 };

function label(value: VisualizationValue): string {
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(5);
  return String(value ?? "—");
}

function tickLabel(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 100) return value.toFixed(1);
  if (magnitude >= 10) return value.toFixed(2);
  if (magnitude >= 1) return value.toFixed(3);
  return value.toPrecision(3);
}

export default function ChartViewer({
  visualization,
}: {
  visualization: ChartVisualization;
}) {
  const chart = useMemo(() => {
    const numericX = visualization.x.type === "quantitative";
    const points = visualization.rows.flatMap((row, index) => {
      const x = numericX ? Number(row[visualization.x.field]) : index;
      const y = Number(row[visualization.y.field]);
      return Number.isFinite(x) && Number.isFinite(y)
        ? [{ row, index, x, y }]
        : [];
    });
    const orderedPoints =
      visualization.mark === "line" && numericX
        ? [...points].sort((left, right) => left.x - right.x)
        : points;
    const xValues = orderedPoints.map((point) => point.x);
    const yValues = orderedPoints.map((point) => point.y);
    const xRange = numericRange(xValues, { min: -0.5, max: 0.5 });
    const yRange = numericRange(yValues);
    const rawXMin = numericX ? xRange.min : -0.5;
    const rawXMax = numericX
      ? xRange.max
      : Math.max(xValues.length - 0.5, 0.5);
    const rawYMin =
      visualization.mark === "bar"
        ? Math.min(yRange.min, 0)
        : yRange.min;
    const rawYMax =
      visualization.mark === "bar"
        ? Math.max(yRange.max, 0)
        : yRange.max;
    const scatterComparison = visualization.mark === "scatter" && numericX;
    const domainMin = scatterComparison ? Math.min(rawXMin, rawYMin) : rawYMin;
    const domainMax = scatterComparison ? Math.max(rawXMax, rawYMax) : rawYMax;
    const domainSpan = domainMax - domainMin || 1;
    const ySpan = rawYMax - rawYMin || 1;
    const xSpan = rawXMax - rawXMin || 1;
    const xMin = scatterComparison
      ? domainMin - domainSpan * 0.08
      : rawXMin - xSpan * 0.08;
    const xMax = scatterComparison
      ? domainMax + domainSpan * 0.08
      : rawXMax + xSpan * 0.08;
    const min = scatterComparison
      ? xMin
      : rawYMin === 0 && visualization.mark === "bar"
        ? rawYMin
        : rawYMin - ySpan * 0.08;
    const max = scatterComparison ? xMax : rawYMax + ySpan * 0.08;
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const slot = innerWidth / Math.max(orderedPoints.length, 1);
    const x = (value: number) =>
      numericX
        ? MARGIN.left + ((value - xMin) / (xMax - xMin || 1)) * innerWidth
        : MARGIN.left + slot * (value + 0.5);
    const y = (value: number) =>
      MARGIN.top + ((max - value) / (max - min)) * innerHeight;
    const xTicks = numericX
      ? Array.from(
          { length: 5 },
          (_, index) => xMin + ((xMax - xMin) * index) / 4,
        )
      : [];
    return {
      points: orderedPoints,
      numericX,
      scatterComparison,
      min,
      max,
      xMin,
      xMax,
      innerWidth,
      innerHeight,
      slot,
      x,
      y,
      xTicks,
    };
  }, [visualization]);

  const zeroY = chart.y(0);
  const labelStep = Math.max(1, Math.ceil(chart.points.length / 8));
  const showPointLabels = chart.points.length <= 20;
  const yTicks = Array.from(
    { length: 5 },
    (_, index) => chart.min + ((chart.max - chart.min) * index) / 4,
  );
  const linePoints = chart.points
    .map((point) => `${chart.x(point.x)},${chart.y(point.y)}`)
    .join(" ");

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0b141a] p-5 lg:p-8">
      <div className="flex min-h-[32rem] flex-1 flex-col overflow-hidden rounded-xl border border-[#35515e] bg-[#0e1920] p-4 shadow-[0_20px_60px_rgba(0,0,0,0.22)] lg:min-h-[36rem] lg:p-5">
        <div className="mb-3 shrink-0 border-b border-[#263f4a] pb-3 text-center">
          <h3 className="text-lg font-semibold text-[#f0f5f2]">
            {visualization.title}
          </h3>
          {visualization.description ? (
            <p className="mx-auto mt-1 max-w-3xl text-sm leading-relaxed text-[#9fb2b9]">
              {visualization.description}
            </p>
          ) : null}
        </div>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="min-h-0 w-full flex-1"
          role="img"
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={chart.y(tick)}
                y2={chart.y(tick)}
                stroke="#263f4a"
              />
              <text
                x={MARGIN.left - 14}
                y={chart.y(tick) + 4}
                textAnchor="end"
                fill="#9fb2b9"
                fontSize="11"
                fontFamily="monospace"
              >
                {tickLabel(tick)}
              </text>
            </g>
          ))}

          {visualization.mark === "bar" ? (
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={zeroY}
              y2={zeroY}
              stroke="#607985"
            />
          ) : null}

          {chart.scatterComparison ? (
            <g aria-label="Ideal agreement line">
              <line
                x1={chart.x(chart.xMin)}
                y1={chart.y(chart.xMin)}
                x2={chart.x(chart.xMax)}
                y2={chart.y(chart.xMax)}
                stroke="#8bd7ff"
                strokeDasharray="8 6"
                strokeWidth="2"
                opacity="0.8"
              />
              <text
                x={WIDTH - MARGIN.right - 8}
                y={MARGIN.top + 18}
                textAnchor="end"
                fill="#8bd7ff"
                fontSize="11"
              >
                ideal y = x
              </text>
            </g>
          ) : null}

          {visualization.mark === "bar"
            ? chart.points.map((point) => {
                const top = Math.min(chart.y(point.y), zeroY);
                const height = Math.max(2, Math.abs(zeroY - chart.y(point.y)));
                return (
                  <rect
                    key={`${point.index}-${point.y}`}
                    x={chart.x(point.x) - chart.slot * 0.31}
                    y={top}
                    width={chart.slot * 0.62}
                    height={height}
                    rx="6"
                    fill="#58b6b0"
                    opacity="0.92"
                  >
                    <title>{`${label(point.row[visualization.x.field])}: ${label(point.y)} ${visualization.y.unit ?? ""}`}</title>
                  </rect>
                );
              })
            : null}

          {visualization.mark === "line" ? (
            <polyline
              points={linePoints}
              fill="none"
              stroke="#58b6b0"
              strokeWidth="4"
              strokeLinejoin="round"
            />
          ) : null}

          {visualization.mark !== "bar"
            ? chart.points.map((point) => (
                <circle
                  key={`${point.index}-${point.x}-${point.y}`}
                  cx={chart.x(point.x)}
                  cy={chart.y(point.y)}
                  r={chart.scatterComparison ? 3.5 : 7}
                  fill="#f29a68"
                  opacity={chart.scatterComparison ? 0.58 : 1}
                  stroke="#0e1920"
                  strokeWidth={chart.scatterComparison ? 1 : 3}
                >
                  <title>{`${visualization.x.label ?? visualization.x.field}: ${label(point.row[visualization.x.field])}; ${visualization.y.label ?? visualization.y.field}: ${label(point.y)} ${visualization.y.unit ?? ""}`}</title>
                </circle>
              ))
            : null}

          {showPointLabels
            ? chart.points.map((point) => (
                <text
                  key={`value-${point.index}`}
                  x={chart.x(point.x)}
                  y={chart.y(point.y) - 14}
                  textAnchor="middle"
                  fill="#eef5f2"
                  fontSize="12"
                  fontFamily="monospace"
                  fontWeight="600"
                >
                  {label(point.y)}
                </text>
              ))
            : null}

          {chart.numericX
            ? chart.xTicks.map((tick) => (
                <text
                  key={`x-tick-${tick}`}
                  x={chart.x(tick)}
                  y={HEIGHT - MARGIN.bottom + 28}
                  textAnchor="middle"
                  fill="#b7c7cc"
                  fontSize="11"
                  fontFamily="monospace"
                >
                  {tickLabel(tick)}
                </text>
              ))
            : chart.points.map((point, index) =>
                index % labelStep === 0 ? (
                  <text
                    key={`${index}-${label(point.row[visualization.x.field])}`}
                    x={chart.x(point.x)}
                    y={HEIGHT - MARGIN.bottom + 28}
                    textAnchor="middle"
                    fill="#b7c7cc"
                    fontSize="11"
                    fontFamily="monospace"
                  >
                    {label(point.row[visualization.x.field]).slice(0, 18)}
                  </text>
                ) : null,
              )}

          <text
            x={WIDTH / 2}
            y={HEIGHT - 24}
            textAnchor="middle"
            fill="#b7c7cc"
            fontSize="12"
          >
            {visualization.x.label ?? visualization.x.field}
            {visualization.x.unit ? ` (${visualization.x.unit})` : ""}
          </text>
          <text
            x="28"
            y={HEIGHT / 2}
            textAnchor="middle"
            fill="#b7c7cc"
            fontSize="12"
            transform={`rotate(-90 28 ${HEIGHT / 2})`}
          >
            {visualization.y.label ?? visualization.y.field}
            {visualization.y.unit ? ` (${visualization.y.unit})` : ""}
          </text>
        </svg>
      </div>
    </div>
  );
}
