import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, SLOW_REQUEST_MS, fetchHeatmap, planTrip } from "./api/client";
import type { HeatmapResponse, PlanRequest, PlanResponse } from "./api/types";
import { RouteCards } from "./components/RouteCards";
import { TripForm } from "./components/TripForm";

const MapView = lazy(() => import("./components/MapView"));

type HeatmapState = "idle" | "loading" | "error" | "ready";

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [heatmapState, setHeatmapState] = useState<HeatmapState>("idle");
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const planAbort = useRef<AbortController | null>(null);
  const heatmapAbort = useRef<AbortController | null>(null);
  const lastLoad = useRef(0);

  const loadHeatmap = useCallback((current: PlanResponse, loadWeight: number) => {
    heatmapAbort.current?.abort();
    const controller = new AbortController();
    heatmapAbort.current = controller;
    setHeatmapState("loading");
    setHeatmapError(null);
    fetchHeatmap(
      {
        routes: current.routes.map((route) => route.corridor),
        departure_utc: current.departure.utc,
        load_weight_lb: loadWeight,
      },
      controller.signal,
    )
      .then((data) => {
        setHeatmap(data);
        setHeatmapState("ready");
      })
      .catch((err: unknown) => {
        if (isAbort(err)) return;
        setHeatmapState("error");
        setHeatmapError(err instanceof ApiError ? err.message : "The weather heatmap failed to load.");
      });
  }, []);

  const submit = useCallback(
    (request: PlanRequest) => {
      planAbort.current?.abort();
      heatmapAbort.current?.abort();
      const controller = new AbortController();
      planAbort.current = controller;
      lastLoad.current = request.load_weight_lb;
      setPlanning(true);
      setSlow(false);
      setError(null);
      const slowTimer = window.setTimeout(() => setSlow(true), SLOW_REQUEST_MS);

      planTrip(request, controller.signal)
        .then((data) => {
          setPlan(data);
          setSelectedId(data.recommendation.route_id ?? data.routes[0]?.id ?? null);
          setHeatmap(null);
          if (data.routes.length) loadHeatmap(data, request.load_weight_lb);
        })
        .catch((err: unknown) => {
          if (isAbort(err)) return;
          setError(err instanceof ApiError ? err.message : "Something went wrong while planning.");
        })
        .finally(() => {
          window.clearTimeout(slowTimer);
          if (planAbort.current === controller) {
            setPlanning(false);
            setSlow(false);
          }
        });
    },
    [loadHeatmap],
  );

  useEffect(
    () => () => {
      planAbort.current?.abort();
      heatmapAbort.current?.abort();
    },
    [],
  );

  return (
    <div className="app">
      <aside className="panel">
        <header className="panel-header">
          <h1>Truck Weather Routing</h1>
          <p>Three truck routes, scored on forecast weather at the hour you reach each checkpoint.</p>
        </header>
        <TripForm busy={planning} hasPlan={plan !== null} onSubmit={submit} />
        {slow && <p className="status">Waking the server; the first request after a quiet spell can take up to a minute…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {plan && (
          <RouteCards plan={plan} selectedId={selectedId} hoveredId={hoveredId} onSelect={setSelectedId} />
        )}
      </aside>
      <main className="map-area">
        <Suspense fallback={<div className="map-loading">Loading map…</div>}>
          <MapView
            plan={plan}
            heatmap={heatmap}
            heatmapState={heatmapState}
            heatmapError={heatmapError}
            onRetryHeatmap={() => plan && loadHeatmap(plan, lastLoad.current)}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onHover={setHoveredId}
          />
        </Suspense>
      </main>
    </div>
  );
}
