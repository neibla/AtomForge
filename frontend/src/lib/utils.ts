import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number")
    return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  return typeof value === "string"
    ? value
    : typeof value === "boolean"
      ? String(value)
      : (JSON.stringify(value) ?? String(value));
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function numericRange(
  values: readonly number[],
  fallback: { min: number; max: number } = { min: 0, max: 0 },
): { min: number; max: number } {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  return min === Number.POSITIVE_INFINITY ? fallback : { min, max };
}
