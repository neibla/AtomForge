import type { AtomisticVisualizationData } from "@/types";

export interface ElementStyle {
  atomicNumber: number;
  symbol: string;
  name: string;
  color: string;
}

export interface ElementLegendEntry extends ElementStyle {
  count: number;
}

const ELEMENT_STYLES: Record<number, Omit<ElementStyle, "atomicNumber">> = {
  1: { symbol: "H", name: "Hydrogen", color: "#f7faf9" },
  6: { symbol: "C", name: "Carbon", color: "#b8d7dc" },
  8: { symbol: "O", name: "Oxygen", color: "#ef6a63" },
  13: { symbol: "Al", name: "Aluminium", color: "#f1f5f2" },
  14: { symbol: "Si", name: "Silicon", color: "#ef8ab8" },
  22: { symbol: "Ti", name: "Titanium", color: "#cbd5d1" },
  24: { symbol: "Cr", name: "Chromium", color: "#8fc4d0" },
  26: { symbol: "Fe", name: "Iron", color: "#b9c9d2" },
  28: { symbol: "Ni", name: "Nickel", color: "#d8c5a6" },
  29: { symbol: "Cu", name: "Copper", color: "#d97845" },
  73: { symbol: "Ta", name: "Tantalum", color: "#55c7d9" },
  74: { symbol: "W", name: "Tungsten", color: "#e4b65c" },
};

// Keep unmapped elements legible and distinguishable on the dark viewport. The
// fallback is deterministic by atomic number, so a report never changes color
// merely because the element catalogue grows.
const FALLBACK_ELEMENT_COLORS = [
  "#8bd7ff",
  "#b9a7ff",
  "#ff8fbb",
  "#72e1b8",
  "#ffd166",
  "#ff9f68",
  "#f78f8f",
  "#80c7ff",
  "#c9e66b",
  "#e7a7ff",
  "#5eead4",
  "#f4b183",
] as const;

function fallbackElementColor(atomicNumber: number): string {
  const index =
    Math.abs(Math.trunc(atomicNumber)) % FALLBACK_ELEMENT_COLORS.length;
  return FALLBACK_ELEMENT_COLORS[index];
}

export function elementStyle(atomicNumber: number): ElementStyle {
  const style = ELEMENT_STYLES[atomicNumber];
  return style
    ? { atomicNumber, ...style }
    : {
        atomicNumber,
        symbol: `Z${atomicNumber}`,
        name: `Atomic number ${atomicNumber}`,
        color: fallbackElementColor(atomicNumber),
      };
}

export function elementLegendEntries(numbers: number[]): ElementLegendEntry[] {
  const counts = new Map<number, number>();
  numbers.forEach((number) =>
    counts.set(number, (counts.get(number) ?? 0) + 1),
  );
  return [...counts.entries()]
    .sort(([left], [right]) => left - right)
    .map(([atomicNumber, count]) => ({ ...elementStyle(atomicNumber), count }));
}

export function cellVectorLengths(cell: number[][]): number[] {
  return cell.map((vector) =>
    Math.sqrt(vector.reduce((sum, coordinate) => sum + coordinate ** 2, 0)),
  );
}

export function isPeriodicStructure(data: AtomisticVisualizationData): boolean {
  if (data.metadata?.periodic === true) return true;
  return (
    Array.isArray(data.pbc) && data.pbc.length === 3 && data.pbc.every(Boolean)
  );
}
