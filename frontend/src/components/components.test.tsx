import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, errorMessage, planTrip } from "../api/client";
import type { PlanResponse } from "../api/types";
import { HeatmapSlider } from "./HeatmapSlider";
import { RouteCards } from "./RouteCards";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("server errors", () => {
  it("passes the server's detail message through unchanged", async () => {
    const detail = "No truck route between these points stays within the United States.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 422 })),
    );

    const failure = planTrip(
      {
        origin: { label: "A", lat: 1, lon: 1 },
        destination: { label: "B", lat: 2, lon: 2 },
        departure_local: "2026-10-22T10:00",
        load_weight_lb: 0,
        interval_miles: 25,
      },
      new AbortController().signal,
    );

    await expect(failure).rejects.toEqual(new ApiError(422, detail));
  });

  it("joins field errors with their field names", () => {
    expect(
      errorMessage(400, {
        load_weight_lb: ["Ensure this value is less than or equal to 80000."],
        non_field_errors: ["Origin and destination must be different places."],
      }),
    ).toBe(
      "load weight lb: Ensure this value is less than or equal to 80000. Origin and destination must be different places.",
    );
  });
});

describe("HeatmapSlider", () => {
  let frameCallbacks: FrameRequestCallback[];

  beforeEach(() => {
    frameCallbacks = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frameCallbacks.push(cb));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });

  const frames = Array.from({ length: 49 }, (_, h) => ({
    time_utc: new Date(Date.UTC(2026, 9, 22, 15 + h)).toISOString(),
    levels: [],
    wind_mph: [],
    rain_in_hr: [],
    snow_in_hr: [],
  }));

  it("coalesces rapid drags into one map update per animation frame", () => {
    const onHour = vi.fn();
    render(<HeatmapSlider frames={frames} timeZone="America/Chicago" onHour={onHour} />);
    const slider = screen.getByRole("slider");

    fireEvent.change(slider, { target: { value: "5" } });
    fireEvent.change(slider, { target: { value: "6" } });
    fireEvent.change(slider, { target: { value: "7" } });
    expect(onHour).not.toHaveBeenCalled();

    act(() => frameCallbacks.forEach((cb) => cb(0)));

    expect(onHour).toHaveBeenCalledTimes(1);
    expect(onHour).toHaveBeenCalledWith(7);
    expect(screen.getByText(/\+7 h · Thu, 5:00 PM CDT/)).toBeTruthy();
  });
});

describe("RouteCards", () => {
  const plan: PlanResponse = {
    departure: {
      local: "2026-10-22T10:00-05:00",
      utc: "2026-10-22T15:00+00:00",
      timezone: "America/Chicago",
      utc_offset: "-0500",
      substituted_now: false,
    },
    recommendation: { route_id: 0, reason: "Recommended because it has fewer Severe miles." },
    warnings: ["Only 2 distinct routes could be found for this trip."],
    routes: [0, 1].map((id) => ({
      id,
      rank: id + 1,
      recommended: id === 0,
      drivable: id === 0,
      complete: true,
      summary: {
        distance_mi: 130 - id * 30,
        duration_s: 7800,
        traffic_delay_s: 0,
        departure_utc: "2026-10-22T15:00+00:00",
        arrival_utc: "2026-10-22T17:10+00:00",
        no_travel_mi: id * 12.5,
        severe_mi: 0,
        high_mi: 0,
        avg_risk: 0.25,
        max_level: id === 0 ? "low" : "no_travel",
      },
      geometry: [],
      corridor: [],
      segments: [],
      checkpoints: [],
    })),
  };

  it("shows the server's reason, warnings and badges, and selects on click", () => {
    const onSelect = vi.fn();
    render(<RouteCards plan={plan} selectedId={0} hoveredId={null} onSelect={onSelect} />);

    expect(screen.getByText("Recommended because it has fewer Severe miles.")).toBeTruthy();
    expect(screen.getByText("Only 2 distinct routes could be found for this trip.")).toBeTruthy();
    expect(screen.getAllByText("Recommended")).toHaveLength(1);
    expect(screen.getAllByText("No Travel").length).toBeGreaterThan(0);
    expect(screen.getByText(/Departing Thu, 10:00 AM CDT \(America\/Chicago, UTC−05:00\)/)).toBeTruthy();

    fireEvent.click(screen.getByText("Route 2"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});
