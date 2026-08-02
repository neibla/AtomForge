import { describe, expect, test } from "bun:test";

import {
  acceptanceCounts,
  formatMetric,
  hasInspectableArtifacts,
} from "./results";

describe("result presentation", () => {
  test("formats metric values with their declared units", () => {
    expect(formatMetric({ val: 3, unit: "count" })).toBe("3 count");
    expect(formatMetric({ val: -4.123456, unit: "eV/atom" })).toBe(
      "-4.1235 eV/atom",
    );
  });

  test("summarizes acceptance checks without inventing confidence", () => {
    const counts = acceptanceCounts([
      {
        id: "one",
        status: "PASSED",
        metric: "n_defects",
        value: "1",
        sample_size: 2,
        ci_low: 1,
        ci_high: 1,
      },
      {
        id: "two",
        status: "REVIEW",
        metric: "energy",
        value: "Error",
        sample_size: 0,
        ci_low: null,
        ci_high: null,
      },
    ]);

    expect(counts).toEqual({ passed: 1, failed: 0, review: 1 });
  });
});

describe("run artifact visibility", () => {
  test("keeps partial evidence inspectable", () => {
    expect(hasInspectableArtifacts("COMPLETED")).toBe(true);
    expect(hasInspectableArtifacts("PARTIAL")).toBe(true);
    expect(hasInspectableArtifacts("RUNNING")).toBe(false);
    expect(hasInspectableArtifacts("FAILED")).toBe(false);
  });
});
