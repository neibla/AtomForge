import { describe, expect, test } from "bun:test";

import type { VisualizationSpec } from "@/types";
import {
  formatParameterValue,
  latticeStructureSeries,
  orderVisualizations,
  structureParameterSeries,
  structureParameterSeriesList,
  visualizationLabel,
} from "./visualizations";

function latticePoint(id: string, value: number): VisualizationSpec {
  return {
    id,
    kind: "atomistic.v1",
    title: id,
    data: {
      positions: [[0, 0, 0]],
      numbers: [74],
      metadata: {
        lattice_parameter_A: value,
        lattice_series: "bcc-w-eos",
        scan_parameter_label: "Lattice parameter",
      },
    },
  };
}

describe("visualization metadata", () => {
  test("orders visualization kinds consistently", () => {
    const views: VisualizationSpec[] = [
      latticePoint("structure", 3.2),
      {
        id: "table",
        kind: "table.v1",
        title: "Evidence",
        columns: [{ field: "candidate", label: "Candidate" }],
        rows: [{ candidate: "A" }],
      },
      {
        id: "chart",
        kind: "chart.v1",
        title: "Scores",
        mark: "bar",
        rows: [{ candidate: "A", score: 1 }],
        x: { field: "candidate", type: "nominal" },
        y: { field: "score", type: "quantitative" },
      },
    ];

    expect(orderVisualizations(views).map((view) => view.id)).toEqual([
      "chart",
      "table",
      "structure",
    ]);
  });

  test("builds lattice series only from authored metadata", () => {
    const scan = [latticePoint("high", 3.2), latticePoint("low", 3.1)];

    expect(
      latticeStructureSeries(scan).map((point) => point.latticeParameter),
    ).toEqual([3.1, 3.2]);
    expect(visualizationLabel(scan[0])).toBe("Structure · a = 3.20 Å");
  });

  test("does not infer legacy values from node names", () => {
    const views: VisualizationSpec[] = ["a535", "a540"].map((value) => ({
      id: value,
      kind: "atomistic.v1",
      title: `eos_${value} atomic structure`,
      source_node: `eos_${value}`,
      data: { positions: [[0, 0, 0]], numbers: [74] },
    }));

    expect(structureParameterSeries(views)).toBeNull();
  });

  test("uses authored signed scan metadata", () => {
    const scan: VisualizationSpec[] = [-1, 0, 1].map((value) => ({
      id: `point-${value}`,
      kind: "atomistic.v1",
      title: `Point ${value}`,
      data: {
        positions: [[0, 0, 0]],
        numbers: [74],
        metadata: {
          scan_parameter_series: "displacement",
          scan_parameter_label: "Displacement",
          scan_parameter_value: value,
          scan_parameter_unit: "Å",
          scan_parameter_signed: true,
        },
      },
    }));

    expect(
      structureParameterSeries(scan)?.points.map((point) => point.value),
    ).toEqual([-1, 0, 1]);
    expect(formatParameterValue(-0.1, "Å", "signed")).toBe("−0.10 Å");
    expect(formatParameterValue(0.1, "Å", "signed")).toBe("+0.10 Å");
  });

  test("keeps independent sweep series separate and preserves fine-grid precision", () => {
    const views: VisualizationSpec[] = ["scan-a", "scan-b"].flatMap((series) =>
      [1, 1.001, 1.002].map((value, index) => ({
        id: `${series}-${index}`,
        kind: "atomistic.v1" as const,
        title: `${series} ${value}`,
        data: {
          positions: [[0, 0, 0]],
          numbers: [74],
          metadata: {
            scan_parameter_series: series,
            scan_parameter_label: "Fine coordinate",
            scan_parameter_value: value,
          },
        },
      })),
    );

    const series = structureParameterSeriesList(views);

    expect(series).toHaveLength(2);
    expect(series[0].precision).toBe(3);
    expect(
      formatParameterValue(1.001, "", "decimal", series[0].precision),
    ).toBe("1.001");
  });
});
