import type { LevelName } from "../api/types";

export const LEVELS: Array<{ name: LevelName; code: number; label: string; color: string }> = [
  { name: "low", code: 0, label: "Low", color: "#2e7d32" },
  { name: "moderate", code: 1, label: "Moderate", color: "#c9a100" },
  { name: "high", code: 2, label: "High", color: "#e65100" },
  { name: "severe", code: 3, label: "Severe", color: "#c62828" },
  { name: "no_travel", code: 4, label: "No Travel", color: "#6a1b9a" },
  { name: "unknown", code: -1, label: "Unknown", color: "#757575" },
];

const BY_NAME = new Map(LEVELS.map((level) => [level.name, level]));

export function levelLabel(name: LevelName | null): string {
  return name ? (BY_NAME.get(name)?.label ?? "Unknown") : "Unknown";
}

export function levelColor(name: LevelName | null): string {
  return name ? (BY_NAME.get(name)?.color ?? "#757575") : "#757575";
}

/** MapLibre `match` arms: [name, color, name, color, ...]. */
export function colorMatchByName(): Array<string> {
  return LEVELS.flatMap((level) => [level.name, level.color]);
}

/** MapLibre `match` arms keyed by the heatmap's numeric level codes. */
export function colorMatchByCode(): Array<number | string> {
  return LEVELS.flatMap((level) => [level.code, level.color]);
}
