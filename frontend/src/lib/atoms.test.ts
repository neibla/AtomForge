import { describe, expect, it } from "bun:test";

import {
  cellVectorLengths,
  elementLegendEntries,
  elementStyle,
  isPeriodicStructure,
} from "./atoms";

describe("atomic structure presentation", () => {
  it("identifies silicon by name rather than its atomic number fallback", () => {
    expect(elementStyle(14)).toMatchObject({
      symbol: "Si",
      name: "Silicon",
    });
  });

  it("uses the same explicit aluminium color in the renderer and legend", () => {
    expect(elementStyle(13)).toMatchObject({
      symbol: "Al",
      name: "Aluminium",
      color: "#f1f5f2",
    });
    expect(elementLegendEntries([13, 13, 13])).toEqual([
      expect.objectContaining({ symbol: "Al", count: 3, color: "#f1f5f2" }),
    ]);
  });

  it("reports cell-vector lengths for non-orthogonal cells", () => {
    expect(
      cellVectorLengths([
        [3, 4, 0],
        [0, 6, 0],
        [0, 0, 7],
      ]),
    ).toEqual([5, 6, 7]);
  });

  it("recognizes periodic structures from the canonical pbc field", () => {
    expect(
      isPeriodicStructure({
        positions: [[0, 0, 0]],
        numbers: [14],
        pbc: [true, true, true],
      }),
    ).toBe(true);
    expect(
      isPeriodicStructure({
        positions: [[0, 0, 0]],
        numbers: [14],
        pbc: [false, false, false],
      }),
    ).toBe(false);
    expect(
      isPeriodicStructure({
        positions: [[0, 0, 0]],
        numbers: [14],
        pbc: [true, true, false],
      }),
    ).toBe(false);
  });

  it("gives tantalum a named, high-contrast element color", () => {
    expect(elementStyle(73)).toMatchObject({
      symbol: "Ta",
      name: "Tantalum",
      color: "#55c7d9",
    });
  });

  it("uses deterministic high-contrast colors for unmapped elements", () => {
    const phosphorusColor = elementStyle(15).color;
    expect(phosphorusColor).toBe(elementStyle(15).color);
    expect(phosphorusColor).not.toBe("#94a7ae");
    expect(phosphorusColor).not.toBe(elementStyle(16).color);
  });
});
