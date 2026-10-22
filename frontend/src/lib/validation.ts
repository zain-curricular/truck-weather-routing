import type { Place } from "../api/types";

export const MAX_LOAD_LB = 80_000;
export const INTERVALS = [10, 25, 50] as const;

export interface TripInput {
  origin: Place | null;
  destination: Place | null;
  departureLocal: string;
  loadWeight: string;
}

/**
 * Mirrors the server's checks so mistakes show before a round trip. The server stays
 * authoritative: the departure window and time zone are only checked there, against the
 * origin's local time.
 */
export function validateTrip(input: TripInput): string[] {
  const errors: string[] = [];
  if (!input.origin) errors.push("Choose an origin from the suggestions.");
  if (!input.destination) errors.push("Choose a destination from the suggestions.");
  if (
    input.origin &&
    input.destination &&
    input.origin.lat.toFixed(4) === input.destination.lat.toFixed(4) &&
    input.origin.lon.toFixed(4) === input.destination.lon.toFixed(4)
  ) {
    errors.push("Origin and destination must be different places.");
  }
  if (input.departureLocal && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(input.departureLocal)) {
    errors.push("Enter a full departure date and time, or clear it to leave now.");
  }
  const load = Number(input.loadWeight);
  if (input.loadWeight.trim() === "" || !Number.isInteger(load) || load < 0 || load > MAX_LOAD_LB) {
    errors.push(`Load weight must be a whole number of pounds from 0 to ${MAX_LOAD_LB.toLocaleString("en-US")}.`);
  }
  return errors;
}
