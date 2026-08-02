import type { DagNode } from "@/types";
import { humanizeIdentifier } from "./experimentPresentation";

export interface SweepPresentation {
  label: string;
  unit: string;
  start: number;
  stop: number;
  step: number;
  sampleCount: number;
  target: string;
  targetLabel: string;
  transform: string;
  transformLabel: string;
  operation: string;
  operationLabel: string;
  maxConcurrency: number;
  explicitValues: boolean;
}

const SWEEP_VALUE_LABELS: Record<string, string> = {
  cell_scale: "Cell scale",
  lattice_constant_A: "Lattice parameter",
  ratio_to_reference: "Ratio to reference",
  cubic_ratio_to_reference: "Cubic ratio to reference",
  identity: "Direct value",
  single_point: "Single-point simulation",
};

function readableSweepValue(value: string): string {
  return SWEEP_VALUE_LABELS[value] ?? humanizeIdentifier(value);
}

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function sweepPresentation(node: DagNode): SweepPresentation | null {
  if (node.type !== "SWEEP") return null;
  const params = object(node.params);
  const coordinate = object(params?.coordinate);
  const grid = object(coordinate?.grid);
  const apply = object(params?.apply);
  const operation = object(params?.operation);
  const values = Array.isArray(grid?.values)
    ? grid.values.map(Number).filter(Number.isFinite)
    : null;
  const start = values?.[0] ?? Number(grid?.start);
  const stop = values?.[values.length - 1] ?? Number(grid?.stop);
  const step = values ? 0 : Number(grid?.step);
  const coordinateName = String(coordinate?.name ?? "Sweep parameter");
  if (
    ![start, stop].every(Number.isFinite) ||
    (!values && (!Number.isFinite(step) || step <= 0)) ||
    stop < start
  )
    return null;
  return {
    label: String(coordinate?.label ?? readableSweepValue(coordinateName)),
    unit: String(coordinate?.unit ?? ""),
    start,
    stop,
    step,
    sampleCount: values?.length ?? Math.floor((stop - start) / step + 1e-9) + 1,
    target: String(apply?.target ?? "—"),
    targetLabel: readableSweepValue(String(apply?.target ?? "—")),
    transform: String(apply?.transform ?? "identity"),
    transformLabel: readableSweepValue(String(apply?.transform ?? "identity")),
    operation: String(operation?.mode ?? operation?.type ?? "—"),
    operationLabel: readableSweepValue(
      String(operation?.mode ?? operation?.type ?? "—"),
    ),
    maxConcurrency: Number(params?.max_concurrency ?? 4),
    explicitValues: Boolean(values),
  };
}

export function formatSweepRange(sweep: SweepPresentation): string {
  const unit = sweep.unit ? ` ${sweep.unit}` : "";
  return `${sweep.start} → ${sweep.stop}${unit}`;
}

export function formatSweepStep(sweep: SweepPresentation): string {
  if (sweep.explicitValues) return "Explicit values";
  const unit = sweep.unit ? ` ${sweep.unit}` : "";
  return `Step ${sweep.step}${unit}`;
}

export function formatSweepSummary(sweep: SweepPresentation): string {
  return `${sweep.label}: ${formatSweepRange(sweep)} · ${sweep.sampleCount} samples`;
}
