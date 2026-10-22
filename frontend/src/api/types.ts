export type LevelName = "low" | "moderate" | "high" | "severe" | "no_travel" | "unknown";

export type LonLat = [number, number];

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

export interface Checkpoint {
  mile: number;
  share_mi: number;
  lat: number;
  lon: number;
  eta_utc: string;
  forecast_hour_utc: string;
  timezone: string;
  weather: {
    wind_mph: number | null;
    gust_mph: number | null;
    rain_in_hr: number | null;
    snow_in_hr: number | null;
  };
  level: LevelName;
  drivers: Array<"wind" | "rain" | "snow">;
  load_escalated: boolean;
}

export interface RouteSummary {
  distance_mi: number;
  duration_s: number;
  traffic_delay_s: number;
  departure_utc: string;
  arrival_utc: string;
  no_travel_mi: number;
  severe_mi: number;
  high_mi: number;
  avg_risk: number | null;
  max_level: LevelName | null;
}

export interface PlannedRoute {
  id: number;
  rank: number;
  recommended: boolean;
  drivable: boolean;
  complete: boolean;
  summary: RouteSummary;
  geometry: LonLat[];
  corridor: LonLat[];
  segments: Array<{ level: LevelName; coordinates: LonLat[] }>;
  checkpoints: Checkpoint[];
}

export interface PlanResponse {
  departure: {
    local: string;
    utc: string;
    timezone: string;
    utc_offset: string;
    substituted_now: boolean;
  };
  recommendation: { route_id: number | null; reason: string };
  warnings: string[];
  routes: PlannedRoute[];
}

export interface PlanRequest {
  origin: Place;
  destination: Place;
  departure_local: string;
  load_weight_lb: number;
  interval_miles: 10 | 25 | 50;
}

export interface HeatmapFrame {
  time_utc: string;
  levels: number[];
  wind_mph: Array<number | null>;
  rain_in_hr: Array<number | null>;
  snow_in_hr: Array<number | null>;
}

export interface HeatmapResponse {
  spacing_deg: number;
  cells: LonLat[];
  frames: HeatmapFrame[];
}
