import { describe, expect, test } from "bun:test";

import type { AtomisticVisualizationData } from "@/types";
import {
  buildExplorerFrames,
  classifyDefectAtoms,
  displacementVector,
  isPkaExplorerData,
  selectAtomIndices,
} from "./pkaExplorer";

const data: AtomisticVisualizationData = {
  positions: [
    [9.9, 0, 0],
    [5, 0, 0],
    [7, 0, 0],
  ],
  initial_positions: [
    [0.1, 0, 0],
    [5, 0, 0],
    [7, 0, 0],
  ],
  trajectory: [
    [
      [0.1, 0, 0],
      [5, 0, 0],
      [7, 0, 0],
    ],
    [
      [9.9, 0, 0],
      [6.5, 0, 0],
      [7, 0, 0],
    ],
  ],
  numbers: [74, 74, 74],
  cell: [
    [10, 0, 0],
    [0, 10, 0],
    [0, 0, 10],
  ],
  pka_index: 1,
  simulation_mode: "pka",
};

describe("PKA explorer data helpers", () => {
  test("uses the minimum image for periodic displacements", () => {
    expect(
      displacementVector([9.9, 0, 0], [0.1, 0, 0], data.cell)[0],
    ).toBeCloseTo(-0.2);
  });

  test("filters displaced and defect atoms", () => {
    expect(selectAtomIndices(data, 1, "displaced")).toEqual([1]);
    expect(selectAtomIndices(data, 1, "defects")).toEqual([1]);
  });

  test("classifies stable-identity trajectories in linear time with periodic displacement", () => {
    expect(classifyDefectAtoms(data, 1)).toEqual([false, true, false]);
  });

  test("uses a spatial index when atom counts differ", () => {
    const differentCounts: AtomisticVisualizationData = {
      ...data,
      positions: [
        [0.1, 0, 0],
        [10, 0, 0],
      ],
      numbers: [74, 74],
      initial_positions: [
        [0, 0, 0],
        [5, 0, 0],
        [7, 0, 0],
      ],
      trajectory: undefined,
    };
    expect(classifyDefectAtoms(differentCounts, 0)).toEqual([false, true]);
  });

  test("derives honest fallback metrics without inventing energy or temperature", () => {
    const frames = buildExplorerFrames(data);
    expect(frames[1].displaced_atoms).toBe(1);
    expect(frames[1].kinetic_energy_ev).toBeNull();
    expect(frames[1].temperature_K).toBeNull();
  });

  test("identifies a PKA trajectory", () => {
    expect(isPkaExplorerData(data)).toBe(true);
  });
});
