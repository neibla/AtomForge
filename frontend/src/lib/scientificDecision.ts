import type { ScientificDecision, ScientificQualityCheck } from "@/types";

export type DecisionOutcomeTone = "success" | "warning" | "danger";

const OUTCOME_LABELS: Record<ScientificDecision["outcome"], string> = {
  VALIDATED: "Validated",
  REVIEW: "Review",
  BLOCKED: "Blocked",
};

const OUTCOME_TONES: Record<
  ScientificDecision["outcome"],
  DecisionOutcomeTone
> = {
  VALIDATED: "success",
  REVIEW: "warning",
  BLOCKED: "danger",
};

export function decisionOutcomeLabel(
  outcome: ScientificDecision["outcome"],
): string {
  return OUTCOME_LABELS[outcome];
}

export function decisionOutcomeTone(
  outcome: ScientificDecision["outcome"],
): DecisionOutcomeTone {
  return OUTCOME_TONES[outcome];
}

export function decisionCalibrationText(
  decision: ScientificDecision,
): string | null {
  const accepted = decision.calibration.accepted_case_count;
  const minimum = decision.calibration.minimum_case_count;
  if (accepted == null && minimum == null) return null;
  if (minimum != null) return `${accepted ?? 0}/${minimum} calibration cases`;
  return `${accepted ?? 0} calibration cases`;
}

export function formatDecisionQualityCheck(
  check: ScientificQualityCheck,
): string {
  const value =
    typeof check.value === "number"
      ? check.value.toLocaleString(undefined, { maximumFractionDigits: 5 })
      : check.value.replaceAll("_", " ");
  const measuredValue = check.unit ? `${value} ${check.unit}` : value;
  return `${check.label}: ${measuredValue} (${check.criterion})`;
}
