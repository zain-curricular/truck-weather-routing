import type { FeatureCollection } from "geojson";
import type { LngLatBoundsLike } from "maplibre-gl";

import type { HeatmapResponse, PlanResponse } from "../api/types";

export const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

export function routeFeatures(plan: PlanResponse): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: plan.routes.map((route) => ({
      type: "Feature",
      properties: { routeId: route.id },
      geometry: { type: "LineString", coordinates: route.geometry },
    })),
  };
}

export function segmentFeatures(plan: PlanResponse): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: plan.routes.flatMap((route) =>
      route.segments.map((segment) => ({
        type: "Feature" as const,
        properties: { routeId: route.id, level: segment.level },
        geometry: { type: "LineString" as const, coordinates: segment.coordinates },
      })),
    ),
  };
}

export function checkpointFeatures(plan: PlanResponse): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: plan.routes.flatMap((route) =>
      route.checkpoints.map((cp) => ({
        type: "Feature" as const,
        properties: { routeId: route.id, level: cp.level, data: JSON.stringify(cp) },
        geometry: { type: "Point" as const, coordinates: [cp.lon, cp.lat] },
      })),
    ),
  };
}

export function endpointFeatures(plan: PlanResponse): FeatureCollection {
  const route = plan.routes[0];
  if (!route) return EMPTY;
  const start = route.geometry[0];
  const end = route.geometry.at(-1);
  if (!start || !end) return EMPTY;
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { kind: "origin" }, geometry: { type: "Point", coordinates: start } },
      { type: "Feature", properties: { kind: "destination" }, geometry: { type: "Point", coordinates: end } },
    ],
  };
}

/** One square per cell; the hour's level is applied as feature state keyed by `id`. */
export function heatmapFeatures(heatmap: HeatmapResponse): FeatureCollection {
  const half = heatmap.spacing_deg / 2;
  return {
    type: "FeatureCollection",
    features: heatmap.cells.map(([lon, lat], index) => ({
      type: "Feature",
      id: index,
      properties: { index },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
          ],
        ],
      },
    })),
  };
}

export function bounds(plan: PlanResponse): LngLatBoundsLike {
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  for (const route of plan.routes) {
    for (const [lon, lat] of route.geometry) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
  }
  return [
    [west, south],
    [east, north],
  ];
}
