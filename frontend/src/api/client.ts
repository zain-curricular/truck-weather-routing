import type { HeatmapResponse, LonLat, Place, PlanRequest, PlanResponse } from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

// Render's free tier sleeps the API; the first request after idle can take ~30-60 s.
export const SLOW_REQUEST_MS = 8000;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** The server's own message is what the user reads; field errors are joined as "field: message". */
export function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const parts = Object.entries(record).flatMap(([field, value]) =>
      flatten(value).map((msg) => (field === "non_field_errors" ? msg : `${label(field)}: ${msg}`)),
    );
    if (parts.length) return parts.join(" ");
  }
  return `Request failed (HTTP ${status}).`;
}

function flatten(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(flatten);
  if (value && typeof value === "object") return Object.values(value).flatMap(flatten);
  return [];
}

function label(field: string): string {
  return field.replace(/_/g, " ");
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body as T;
}

export function searchPlaces(query: string, signal: AbortSignal): Promise<{ results: Place[] }> {
  return request(`/api/geocode?q=${encodeURIComponent(query)}`, { signal });
}

export function planTrip(body: PlanRequest, signal: AbortSignal): Promise<PlanResponse> {
  return request("/api/plan", { method: "POST", body: JSON.stringify(body), signal });
}

export function fetchHeatmap(
  body: { routes: LonLat[][]; departure_utc: string; load_weight_lb: number },
  signal: AbortSignal,
): Promise<HeatmapResponse> {
  return request("/api/heatmap", { method: "POST", body: JSON.stringify(body), signal });
}
