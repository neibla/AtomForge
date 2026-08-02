import type { HypothesisEval, MetricResult, RunRecordResponse } from "@/types";

export function hasInspectableArtifacts(
  state: RunRecordResponse["state"] | undefined,
): boolean {
  return state === "COMPLETED" || state === "PARTIAL";
}

export function formatMetric(metric: MetricResult): string {
  const value = Number.isInteger(metric.val)
    ? metric.val.toString()
    : metric.val.toPrecision(5);
  return metric.unit === "dimensionless" ? value : `${value} ${metric.unit}`;
}

export function acceptanceCounts(evaluations: HypothesisEval[]) {
  return evaluations.reduce(
    (counts, evaluation) => {
      counts[
        evaluation.status.toLowerCase() as "passed" | "failed" | "review"
      ] += 1;
      return counts;
    },
    { passed: 0, failed: 0, review: 0 },
  );
}

export function statusClasses(status: HypothesisEval["status"]): string {
  if (status === "PASSED")
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "FAILED") return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-amber-200 bg-amber-50 text-amber-700";
}
