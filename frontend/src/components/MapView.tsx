import type { ExpressionSpecification } from "@maplibre/maplibre-gl-style-spec";
import {
  type GeoJSONSource,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import type { Checkpoint, HeatmapResponse, PlanResponse } from "../api/types";
import { formatInZone } from "../lib/format";
import { colorMatchByCode, colorMatchByName, levelColor, levelLabel } from "../lib/levels";
import {
  EMPTY,
  bounds,
  checkpointFeatures,
  endpointFeatures,
  heatmapFeatures,
  routeFeatures,
  segmentFeatures,
} from "../lib/mapData";
import { HeatmapSlider } from "./HeatmapSlider";

// MapLibre locates its worker relative to its own module URL, which bundling breaks.
setWorkerUrl(workerUrl);

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const ATTRIBUTION =
  'Weather <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a> (CC BY 4.0) · Routing &amp; search <a href="https://www.tomtom.com/" target="_blank" rel="noreferrer">TomTom</a>';

interface Props {
  plan: PlanResponse | null;
  heatmap: HeatmapResponse | null;
  heatmapState: "idle" | "loading" | "error" | "ready";
  heatmapError: string | null;
  onRetryHeatmap: () => void;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onHover: (id: number | null) => void;
}

export default function MapView(props: Props) {
  const { plan, heatmap, selectedId, onSelect, onHover } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const hourRef = useRef(0);
  const heatmapRef = useRef<HeatmapResponse | null>(null);
  const handlers = useRef({ onSelect, onHover });
  const popups = useRef<Popup[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    handlers.current = { onSelect, onHover };
  }, [onSelect, onHover]);

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: [-97, 39],
      zoom: 3.3,
      attributionControl: { compact: true, customAttribution: ATTRIBUTION },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      addLayers(map);
      popups.current = bindInteractions(map, handlers, hourRef, heatmapRef);
      setReady(true);
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // A popup from the previous plan would show that plan's weather.
    popups.current.forEach((popup) => popup.remove());
    source(map, "routes").setData(plan ? routeFeatures(plan) : EMPTY);
    source(map, "segments").setData(plan ? segmentFeatures(plan) : EMPTY);
    source(map, "checkpoints").setData(plan ? checkpointFeatures(plan) : EMPTY);
    source(map, "endpoints").setData(plan ? endpointFeatures(plan) : EMPTY);
    if (plan) map.fitBounds(bounds(plan), { padding: 60, duration: 600 });
  }, [plan, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const emphasis = (on: number, off: number): ExpressionSpecification => [
      "case",
      ["==", ["get", "routeId"], selectedId ?? -1],
      on,
      off,
    ];
    map.setPaintProperty("route-casing", "line-opacity", emphasis(0.95, 0.35));
    map.setPaintProperty("route-casing", "line-width", emphasis(9, 6));
    map.setPaintProperty("route-segments", "line-opacity", emphasis(1, 0.4));
    map.setPaintProperty("route-segments", "line-width", emphasis(5, 3));
    map.setPaintProperty("checkpoints", "circle-opacity", emphasis(1, 0.35));
    map.setPaintProperty("checkpoints", "circle-stroke-opacity", emphasis(1, 0.35));
    // Draw the selected route on top of the others.
    map.setLayoutProperty("route-segments", "line-sort-key", emphasis(1, 0));
    map.setLayoutProperty("route-casing", "line-sort-key", emphasis(1, 0));
    map.setLayoutProperty("checkpoints", "circle-sort-key", emphasis(1, 0));
  }, [selectedId, ready, plan]);

  useEffect(() => {
    const map = mapRef.current;
    heatmapRef.current = heatmap;
    if (!map || !ready) return;
    map.removeFeatureState({ source: "heatmap" });
    source(map, "heatmap").setData(heatmap ? heatmapFeatures(heatmap) : EMPTY);
    hourRef.current = 0;
    if (heatmap) paintHour(map, heatmap, 0);
  }, [heatmap, ready]);

  return (
    <div className="map-wrap">
      <div ref={container} className="map" aria-label="Route map" role="region" />
      <Legend />
      {props.heatmapState === "loading" && <div className="map-status">Loading weather heatmap…</div>}
      {props.heatmapState === "error" && (
        <div className="map-status error" role="alert">
          {props.heatmapError}{" "}
          <button type="button" onClick={props.onRetryHeatmap}>
            Retry
          </button>
        </div>
      )}
      {heatmap && plan && (
        <HeatmapSlider
          frames={heatmap.frames}
          timeZone={plan.departure.timezone}
          onHour={(hour) => {
            hourRef.current = hour;
            if (mapRef.current) paintHour(mapRef.current, heatmap, hour);
          }}
        />
      )}
    </div>
  );
}

/** A `match` expression; the style-spec tuple type cannot express a spread of arms. */
function match(
  input: ExpressionSpecification,
  arms: Array<string | number>,
  fallback: string | number,
): ExpressionSpecification {
  return ["match", input, ...arms, fallback] as unknown as ExpressionSpecification;
}

function source(map: MapLibreMap, id: string): GeoJSONSource {
  return map.getSource(id) as GeoJSONSource;
}

function addLayers(map: MapLibreMap) {
  for (const id of ["heatmap", "routes", "segments", "checkpoints", "endpoints"]) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  const firstLabel = map.getStyle().layers.find((layer: { type: string }) => layer.type === "symbol")?.id;
  map.addLayer(
    {
      id: "heatmap-fill",
      type: "fill",
      source: "heatmap",
      paint: {
        "fill-color": match(HEATMAP_LEVEL, colorMatchByCode(), "#000000"),
        "fill-opacity": match(HEATMAP_LEVEL, [0, 0.1, -1, 0.15], 0.42),
        "fill-antialias": false,
      },
    },
    firstLabel,
  );
  map.addLayer({
    id: "route-casing",
    type: "line",
    source: "routes",
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": "#ffffff", "line-width": 7 },
  });
  map.addLayer({
    id: "route-segments",
    type: "line",
    source: "segments",
    layout: { "line-join": "round", "line-cap": "round" },
    paint: {
      "line-color": match(["get", "level"], colorMatchByName(), "#757575"),
      "line-width": 4,
    },
  });
  map.addLayer({
    id: "checkpoints",
    type: "circle",
    source: "checkpoints",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3, 8, 6],
      "circle-color": match(["get", "level"], colorMatchByName(), "#757575"),
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });
  map.addLayer({
    id: "endpoints",
    type: "circle",
    source: "endpoints",
    paint: {
      "circle-radius": 7,
      "circle-color": ["match", ["get", "kind"], "origin", "#1565c0", "#111111"],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });
}

const HEATMAP_LEVEL: ExpressionSpecification = ["to-number", ["coalesce", ["feature-state", "level"], -1]];

/** Per-cell feature state lets MapLibre recolour existing buffers instead of rebuilding the layer. */
function paintHour(map: MapLibreMap, heatmap: HeatmapResponse, hour: number) {
  const levels = heatmap.frames[hour]?.levels ?? [];
  levels.forEach((level, id) => map.setFeatureState({ source: "heatmap", id }, { level }));
}

function bindInteractions(
  map: MapLibreMap,
  handlers: React.RefObject<{ onSelect: (id: number) => void; onHover: (id: number | null) => void }>,
  hourRef: React.RefObject<number>,
  heatmapRef: React.RefObject<HeatmapResponse | null>,
): Popup[] {
  const popup = new Popup({ closeButton: true, maxWidth: "280px" });
  const hoverPopup = new Popup({ closeButton: false, closeOnClick: false, className: "hover-popup" });
  const routeLayers = ["route-segments", "route-casing"];

  map.on("click", "checkpoints", (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature) return;
    const cp = JSON.parse(feature.properties.data as string) as Checkpoint;
    popup.setLngLat([cp.lon, cp.lat]).setDOMContent(checkpointPopup(cp, feature)).addTo(map);
    handlers.current.onSelect(feature.properties.routeId as number);
  });
  for (const layer of routeLayers) {
    map.on("click", layer, (event: MapLayerMouseEvent) => {
      const id = event.features?.[0]?.properties.routeId;
      if (typeof id === "number") handlers.current.onSelect(id);
    });
    map.on("mousemove", layer, (event: MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = "pointer";
      const id = event.features?.[0]?.properties.routeId;
      handlers.current.onHover(typeof id === "number" ? id : null);
    });
    map.on("mouseleave", layer, () => {
      map.getCanvas().style.cursor = "";
      handlers.current.onHover(null);
    });
  }
  map.on("mouseenter", "checkpoints", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "checkpoints", () => (map.getCanvas().style.cursor = ""));

  map.on("mousemove", "heatmap-fill", (event: MapLayerMouseEvent) => {
    const data = heatmapRef.current;
    const index = event.features?.[0]?.properties.index;
    const frame = data?.frames[hourRef.current];
    if (!frame || typeof index !== "number") return;
    const lines = [
      levelLabel(levelNameForCode(frame.levels[index] ?? -1)),
      `Wind ${fmt(frame.wind_mph[index], 0)} mph · Rain ${fmt(frame.rain_in_hr[index], 2)} in/hr · Snow ${fmt(frame.snow_in_hr[index], 1)} in/hr`,
    ];
    hoverPopup.setLngLat(event.lngLat).setDOMContent(textBlock(lines)).addTo(map);
  });
  map.on("mouseleave", "heatmap-fill", () => hoverPopup.remove());
  return [popup, hoverPopup];
}

function levelNameForCode(code: number) {
  return (["low", "moderate", "high", "severe", "no_travel"] as const)[code] ?? "unknown";
}

function fmt(value: number | null | undefined, digits: number): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function textBlock(lines: string[]): HTMLElement {
  const div = document.createElement("div");
  for (const line of lines) {
    const p = document.createElement("p");
    p.textContent = line;
    div.appendChild(p);
  }
  return div;
}

function checkpointPopup(cp: Checkpoint, feature: MapGeoJSONFeature): HTMLElement {
  const w = cp.weather;
  const drivers = cp.drivers.length ? ` (${cp.drivers.join(", ")})` : "";
  const lines = [
    `Route ${(feature.properties.routeId as number) + 1} · mile ${cp.mile}`,
    `${levelLabel(cp.level)}${drivers}`,
    `ETA ${formatInZone(cp.eta_utc, cp.timezone)}`,
    `Wind ${fmt(w.wind_mph, 0)} mph (gusts ${fmt(w.gust_mph, 0)}, not scored)`,
    `Rain ${fmt(w.rain_in_hr, 2)} in/hr · Snow ${fmt(w.snow_in_hr, 1)} in/hr`,
    `Forecast hour ending ${formatInZone(cp.forecast_hour_utc, cp.timezone)}`,
  ];
  if (cp.load_escalated) lines.push("Load weight raised the wind risk level.");
  const block = textBlock(lines);
  block.className = "checkpoint-popup";
  return block;
}

function Legend() {
  return (
    <div className="legend" aria-label="Risk legend">
      {(["low", "moderate", "high", "severe", "no_travel"] as const).map((name) => (
        <span key={name} className="legend-item">
          <span className="swatch" style={{ background: levelColor(name) }} aria-hidden="true" />
          {levelLabel(name)}
        </span>
      ))}
    </div>
  );
}
