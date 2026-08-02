import { describe, expect, test } from "bun:test";

import type { ScientificDecision } from "@/types";

import {
  decisionCalibrationText,
  decisionOutcomeLabel,
  decisionOutcomeTone,
  formatDecisionQualityCheck,
} from "./scientificDecision";

function decision(
  overrides: Partial<ScientificDecision> = {},
): ScientificDecision {
  return {
    outcome: "REVIEW",
    calibration: { status: "INSUFFICIENT_EVIDENCE" },
    scope: "Scope",
    headline: "Headline",
    limitations: ["Limit"],
    ...overrides,
  };
}

describe("scientific decision presentation", () => {
  test("uses one label and tone policy for every outcome", () => {
    expect(decisionOutcomeLabel("VALIDATED")).toBe("Validated");
    expect(decisionOutcomeTone("VALIDATED")).toBe("success");
    expect(decisionOutcomeLabel("REVIEW")).toBe("Review");
    expect(decisionOutcomeTone("REVIEW")).toBe("warning");
    expect(decisionOutcomeLabel("BLOCKED")).toBe("Blocked");
    expect(decisionOutcomeTone("BLOCKED")).toBe("danger");
  });

  test("formats calibration only from recorded counts", () => {
    expect(decisionCalibrationText(decision())).toBeNull();
    expect(
      decisionCalibrationText(
        decision({
          calibration: {
            status: "CALIBRATED",
            accepted_case_count: 3,
            minimum_case_count: 5,
          },
        }),
      ),
    ).toBe("3/5 calibration cases");
    expect(
      decisionCalibrationText(
        decision({
          calibration: { status: "CALIBRATED", accepted_case_count: 3 },
        }),
      ),
    ).toBe("3 calibration cases");
  });

  test("formats quality checks with their declared unit and criterion", () => {
    expect(
      formatDecisionQualityCheck({
        label: "Energy",
        status: "PASSED",
        value: 1.234567,
        unit: "eV",
        criterion: "< 2 eV",
      }),
    ).toBe("Energy: 1.23457 eV (< 2 eV)");
  });
});
