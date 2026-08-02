import { describe, expect, test } from "bun:test";

import type { DagNode } from "@/types";

import {
  formatSweepRange,
  formatSweepStep,
  sweepPresentation,
} from "./sweeps";

function sweepNode(
  grid: Record<string, unknown>,
  apply: Record<string, unknown>,
): DagNode {
  return {
    id: "eos",
    type: "SWEEP",
    params: {
      operation: { type: "SIMULATE", mode: "single_point", trials: 1 },
      coordinate: {
        name: "lattice_constant_A",
        label: "Lattice parameter",
        unit: "Å",
        grid,
      },
      apply,
    },
  };
}

describe("sweep presentation", () => {
  test("shows a decimal grid as one range with its exact sample count", () => {
    const sweep = sweepPresentation(
      sweepNode(
        { start: 5.35, stop: 5.53, step: 0.01 },
        {
          target: "cell_scale",
          transform: "ratio_to_reference",
          reference: 5.43,
        },
      ),
    );

    expect(sweep?.sampleCount).toBe(19);
    expect(sweep && formatSweepRange(sweep)).toBe("5.35 → 5.53 Å");
    expect(sweep?.target).toBe("cell_scale");
    expect(sweep?.targetLabel).toBe("Cell scale");
    expect(sweep?.transformLabel).toBe("Ratio to reference");
    expect(sweep?.operationLabel).toBe("Single-point simulation");
    expect(sweep && formatSweepStep(sweep)).toBe("Step 0.01 Å");
  });

  test("presents migrated irregular grids as explicit values", () => {
    const sweep = sweepPresentation(
      sweepNode(
        { values: [5.35, 5.38, 5.4, 5.43, 5.46, 5.5, 5.53] },
        { target: "cell_scale", transform: "cubic_ratio_to_reference" },
      ),
    );

    expect(sweep?.sampleCount).toBe(7);
    expect(sweep?.explicitValues).toBe(true);
    expect(sweep && formatSweepRange(sweep)).toBe("5.35 → 5.53 Å");
    expect(sweep && formatSweepStep(sweep)).toBe("Explicit values");
  });
});
