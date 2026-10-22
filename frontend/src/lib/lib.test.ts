import { describe, expect, it } from "vitest";

import { formatDuration, formatInZone, formatMiles, formatOffset } from "./format";
import { colorMatchByCode, levelColor, levelLabel } from "./levels";
import { heatmapFeatures } from "./mapData";
import { validateTrip } from "./validation";

describe("levels", () => {
  it("labels and colours every level the API can send", () => {
    expect(levelLabel("no_travel")).toBe("No Travel");
    expect(levelLabel("unknown")).toBe("Unknown");
    expect(levelLabel(null)).toBe("Unknown");
    expect(levelColor("severe")).toBe("#c62828");
  });

  it("keys heatmap colours by the server's numeric codes, -1 for unknown", () => {
    const arms = colorMatchByCode();
    expect(arms.slice(0, 4)).toEqual([0, "#2e7d32", 1, "#c9a100"]);
    expect(arms.slice(-2)).toEqual([-1, "#757575"]);
  });
});

describe("format", () => {
  it("shows a UTC time in the checkpoint's zone with its abbreviation", () => {
    expect(formatInZone("2026-10-22T15:25+00:00", "America/Chicago")).toBe("Thu, 10:25 AM CDT");
    expect(formatInZone("2026-10-22T15:25+00:00", "America/Denver")).toBe("Thu, 9:25 AM MDT");
  });

  it("uses standard time after the November change", () => {
    expect(formatInZone("2026-11-02T15:25+00:00", "America/Chicago")).toBe("Mon, 9:25 AM CST");
  });

  it("formats durations, miles and offsets", () => {
    expect(formatDuration(3 * 3600 + 5 * 60)).toBe("3 h 05 min");
    expect(formatDuration(25 * 60)).toBe("25 min");
    expect(formatMiles(1234.56)).toBe("1,234.6 mi");
    expect(formatOffset("-0500")).toBe("UTC−05:00");
  });
});

describe("validateTrip", () => {
  const place = { label: "A", lat: 41.88, lon: -87.63 };
  const other = { label: "B", lat: 39.74, lon: -104.99 };

  it("accepts a complete trip", () => {
    expect(
      validateTrip({ origin: place, destination: other, departureLocal: "2026-10-22T10:00", loadWeight: "35000" }),
    ).toEqual([]);
  });

  it("matches the server's rules for places and load weight", () => {
    expect(
      validateTrip({ origin: null, destination: place, departureLocal: "", loadWeight: "80001" }),
    ).toEqual([
      "Choose an origin from the suggestions.",
      "Enter a departure date and time.",
      "Load weight must be a whole number of pounds from 0 to 80,000.",
    ]);
    expect(
      validateTrip({ origin: place, destination: place, departureLocal: "2026-10-22T10:00", loadWeight: "1.5" }),
    ).toEqual([
      "Origin and destination must be different places.",
      "Load weight must be a whole number of pounds from 0 to 80,000.",
    ]);
  });
});

describe("heatmapFeatures", () => {
  it("builds one square per cell, keyed by index for feature state", () => {
    const collection = heatmapFeatures({
      spacing_deg: 0.5,
      cells: [[-90, 40]],
      frames: [
        { time_utc: "", levels: [2], wind_mph: [36], rain_in_hr: [0], snow_in_hr: [0] },
        { time_utc: "", levels: [-1], wind_mph: [null], rain_in_hr: [null], snow_in_hr: [null] },
      ],
    });

    const [feature] = collection.features;
    expect(feature?.id).toBe(0);
    expect(feature?.properties).toEqual({ index: 0 });
    expect(feature?.geometry).toEqual({
      type: "Polygon",
      coordinates: [
        [
          [-90.25, 39.75],
          [-89.75, 39.75],
          [-89.75, 40.25],
          [-90.25, 40.25],
          [-90.25, 39.75],
        ],
      ],
    });
  });
});
