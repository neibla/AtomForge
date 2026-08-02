import type { AtomisticVisualizationData, PKAFrameMetric } from "@/types";
import { numericRange } from "./utils";

export type AtomFilter = "all" | "displaced" | "defects" | "neighbourhood";

export interface ExplorerFrameMetric {
  frame: number;
  step: number | null;
  time_fs: number | null;
  kinetic_energy_ev: number | null;
  potential_energy_ev: number | null;
  temperature_K: number | null;
  n_defects: number | null;
  interstitials: number | null;
  displaced_atoms: number;
  max_displacement_angstrom: number;
  vacancy_positions: number[][];
  interstitial_positions: number[][];
}

const DISPLACED_THRESHOLD = 0.5;
const DEFECT_THRESHOLD = 1.2;
const NEIGHBOURHOOD_RADIUS = 6;
const MAX_NEAREST_NEIGHBOUR_ATOMS = 10_000;

function invert3(matrix: number[][]): number[][] | null {
  const [a, b, c] = matrix;
  if (!a || !b || !c) return null;
  const determinant =
    a[0] * (b[1] * c[2] - b[2] * c[1]) -
    a[1] * (b[0] * c[2] - b[2] * c[0]) +
    a[2] * (b[0] * c[1] - b[1] * c[0]);
  if (Math.abs(determinant) < 1e-12) return null;
  return [
    [
      b[1] * c[2] - b[2] * c[1],
      a[2] * c[1] - a[1] * c[2],
      a[1] * b[2] - a[2] * b[1],
    ],
    [
      b[2] * c[0] - b[0] * c[2],
      a[0] * c[2] - a[2] * c[0],
      a[2] * b[0] - a[0] * b[2],
    ],
    [
      b[0] * c[1] - b[1] * c[0],
      a[1] * c[0] - a[0] * c[1],
      a[0] * b[1] - a[1] * b[0],
    ],
  ].map((row) => row.map((value) => value / determinant));
}

function multiply(vector: number[], matrix: number[][]): number[] {
  return [0, 1, 2].map(
    (column) =>
      vector[0] * matrix[0][column] +
      vector[1] * matrix[1][column] +
      vector[2] * matrix[2][column],
  );
}

export function displacementVector(
  position: number[],
  initial: number[],
  cell?: number[][] | null,
): number[] {
  return displacementVectorWithInverse(position, initial, cell, cell ? invert3(cell) : null);
}

function displacementVectorWithInverse(
  position: number[],
  initial: number[],
  cell: number[][] | null | undefined,
  inverse: number[][] | null,
): number[] {
  const delta = position.map((value, index) => value - initial[index]);
  if (!cell || !inverse) return delta;
  const fractional = multiply(delta, inverse).map(
    (value) => value - Math.round(value),
  );
  return multiply(fractional, cell);
}

export function displacementMagnitudes(
  data: AtomisticVisualizationData,
  frame: number,
): number[] {
  const initial = data.initial_positions ?? data.positions;
  const positions = data.trajectory?.[frame] ?? data.positions;
  const inverse = data.cell ? invert3(data.cell) : null;
  return positions.map((position, index) => {
    const vector = displacementVectorWithInverse(
      position,
      initial[index] ?? position,
      data.cell,
      inverse,
    );
    return Math.hypot(vector[0], vector[1], vector[2]);
  });
}

function bucketKey(x: number, y: number, z: number): string {
  return `${x}:${y}:${z}`;
}

function periodicImageOffsets(data: AtomisticVisualizationData): number[][] {
  if (!data.cell || !data.pbc?.some(Boolean)) return [[0, 0, 0]];
  const choices = data.pbc.map((periodic) => (periodic ? [-1, 0, 1] : [0]));
  const offsets: number[][] = [];
  for (const x of choices[0]) {
    for (const y of choices[1]) {
      for (const z of choices[2]) offsets.push([x, y, z]);
    }
  }
  return offsets;
}

function offsetPosition(position: number[], cell: number[][], offset: number[]): number[] {
  return [
    position[0] + offset[0] * cell[0][0] + offset[1] * cell[1][0] + offset[2] * cell[2][0],
    position[1] + offset[0] * cell[0][1] + offset[1] * cell[1][1] + offset[2] * cell[2][1],
    position[2] + offset[0] * cell[0][2] + offset[1] * cell[1][2] + offset[2] * cell[2][2],
  ];
}

/** Classify displaced atoms without quadratic work for stable trajectories. */
export function classifyDefectAtoms(
  data: AtomisticVisualizationData,
  frame: number,
): boolean[] | null {
  const initial = data.initial_positions ?? data.positions;
  const positions = data.trajectory?.[frame] ?? data.positions;
  if (!initial.length) return null;
  if (initial.length === positions.length) {
    return displacementMagnitudes(data, frame).map(
      (magnitude) => magnitude > DEFECT_THRESHOLD,
    );
  }
  if (
    initial.length > MAX_NEAREST_NEIGHBOUR_ATOMS ||
    positions.length > MAX_NEAREST_NEIGHBOUR_ATOMS
  ) {
    return null;
  }

  const cell = data.cell;
  const cellSize = DEFECT_THRESHOLD;
  const buckets = new Map<string, number[][]>();
  const offsets = cell ? periodicImageOffsets(data) : [[0, 0, 0]];
  for (let index = 0; index < initial.length; index++) {
    for (const offset of offsets) {
      const image = cell ? offsetPosition(initial[index], cell, offset) : initial[index];
      const key = bucketKey(
        Math.floor(image[0] / cellSize),
        Math.floor(image[1] / cellSize),
        Math.floor(image[2] / cellSize),
      );
      const candidates = buckets.get(key) ?? [];
      candidates.push(image);
      buckets.set(key, candidates);
    }
  }

  return positions.map((position) => {
    const x = Math.floor(position[0] / cellSize);
    const y = Math.floor(position[1] / cellSize);
    const z = Math.floor(position[2] / cellSize);
    let minimum = Number.POSITIVE_INFINITY;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dz = -1; dz <= 1; dz++) {
          const candidates = buckets.get(bucketKey(x + dx, y + dy, z + dz));
          if (!candidates) continue;
          for (const candidate of candidates) {
            const distanceX = position[0] - candidate[0];
            const distanceY = position[1] - candidate[1];
            const distanceZ = position[2] - candidate[2];
            minimum = Math.min(
              minimum,
              distanceX * distanceX + distanceY * distanceY + distanceZ * distanceZ,
            );
          }
        }
      }
    }
    return minimum > DEFECT_THRESHOLD * DEFECT_THRESHOLD;
  });
}

export function selectAtomIndices(
  data: AtomisticVisualizationData,
  frame: number,
  filter: AtomFilter,
): number[] {
  const positions = data.trajectory?.[frame] ?? data.positions;
  const initial = data.initial_positions ?? data.positions;
  if (filter === "all") return positions.map((_, index) => index);
  const magnitudes = displacementMagnitudes(data, frame);
  if (filter === "displaced") {
    return magnitudes.flatMap((magnitude, index) =>
      magnitude > DISPLACED_THRESHOLD ? [index] : [],
    );
  }
  if (filter === "defects") {
    return magnitudes.flatMap((magnitude, index) =>
      magnitude > DEFECT_THRESHOLD ? [index] : [],
    );
  }

  const fallbackIndex = magnitudes.reduce(
    (best, magnitude, index) => (magnitude > magnitudes[best] ? index : best),
    0,
  );
  const centerIndex = Math.min(
    data.pka_index ?? fallbackIndex,
    initial.length - 1,
  );
  const center = initial[centerIndex];
  const inverse = data.cell ? invert3(data.cell) : null;
  return initial.flatMap((position, index) => {
    const vector = displacementVectorWithInverse(position, center, data.cell, inverse);
    return Math.hypot(vector[0], vector[1], vector[2]) <= NEIGHBOURHOOD_RADIUS
      ? [index]
      : [];
  });
}

function normalizeMetric(metric: PKAFrameMetric): ExplorerFrameMetric {
  return {
    ...metric,
    vacancy_positions: metric.vacancy_positions ?? [],
    interstitial_positions: metric.interstitial_positions ?? [],
  };
}

export function buildExplorerFrames(
  data: AtomisticVisualizationData,
): ExplorerFrameMetric[] {
  if (data.frame_metrics?.length)
    return data.frame_metrics.map(normalizeMetric);
  const frames = data.trajectory?.length ?? 0;
  return Array.from({ length: frames }, (_, frame) => {
    const magnitudes = displacementMagnitudes(data, frame);
    return {
      frame,
      step: null,
      time_fs: null,
      kinetic_energy_ev: null,
      potential_energy_ev: null,
      temperature_K: null,
      n_defects: frame === frames - 1 ? (data.n_defects ?? null) : null,
      interstitials: frame === frames - 1 ? (data.interstitials ?? null) : null,
      displaced_atoms: magnitudes.filter((value) => value > DISPLACED_THRESHOLD)
        .length,
      max_displacement_angstrom: numericRange(magnitudes).max,
      vacancy_positions:
        frame === frames - 1 ? (data.vacancy_positions ?? []) : [],
      interstitial_positions:
        frame === frames - 1 ? (data.interstitial_positions ?? []) : [],
    };
  });
}

export function isPkaExplorerData(data: AtomisticVisualizationData): boolean {
  return Boolean(
    data.trajectory &&
      data.trajectory.length > 1 &&
      data.initial_positions?.length &&
      (data.simulation_mode === "pka" ||
        data.frame_metrics?.length ||
        data.vacancy_positions),
  );
}
