import { memo } from "react";

import type { PlanResponse } from "../api/types";
import { formatDuration, formatInZone, formatMiles, formatOffset } from "../lib/format";
import { levelColor, levelLabel } from "../lib/levels";

interface Props {
  plan: PlanResponse;
  selectedId: number | null;
  hoveredId: number | null;
  onSelect: (id: number) => void;
}

export const RouteCards = memo(function RouteCards({ plan, selectedId, hoveredId, onSelect }: Props) {
  const { departure, recommendation } = plan;
  const tz = departure.timezone;
  return (
    <section className="results" aria-label="Route options">
      <p className={`recommendation ${recommendation.route_id === null ? "none" : ""}`}>
        {recommendation.reason}
      </p>
      <p className="departure-note">
        Departing {formatInZone(departure.utc, tz)} ({tz}, {formatOffset(departure.utc_offset)})
      </p>
      {plan.warnings.map((warning) => (
        <p key={warning} className="warning">
          {warning}
        </p>
      ))}
      <ol className="route-cards">
        {plan.routes.map((route) => {
          const s = route.summary;
          const classes = [
            "route-card",
            route.id === selectedId ? "selected" : "",
            route.id === hoveredId ? "hovered" : "",
          ].join(" ");
          return (
            <li key={route.id}>
              <button type="button" className={classes} onClick={() => onSelect(route.id)}>
                <span className="card-head">
                  <span className="rank">Route {route.rank}</span>
                  {route.recommended && <span className="badge recommended">Recommended</span>}
                  {!route.drivable && (
                    <span className="badge blocked">
                      {route.complete ? "No Travel" : "Weather missing"}
                    </span>
                  )}
                </span>
                <span className="card-main">
                  {formatMiles(s.distance_mi)} · {formatDuration(s.duration_s)}
                </span>
                <span className="card-times">
                  Arrive {formatInZone(s.arrival_utc, route.checkpoints.at(-1)?.timezone ?? tz)}
                </span>
                <span className="card-risk">
                  <Stat label="No Travel" value={formatMiles(s.no_travel_mi)} level="no_travel" />
                  <Stat label="Severe" value={formatMiles(s.severe_mi)} level="severe" />
                  <Stat label="High" value={formatMiles(s.high_mi)} level="high" />
                  <span className="stat">
                    <span className="stat-label">Avg risk</span>
                    <span className="stat-value">{s.avg_risk === null ? "—" : s.avg_risk.toFixed(2)}</span>
                  </span>
                </span>
                <span className="card-foot">
                  Worst: <span style={{ color: levelColor(s.max_level) }}>{levelLabel(s.max_level)}</span>
                  {" · "}
                  {route.checkpoints.length} checkpoints
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
});

function Stat({ label, value, level }: { label: string; value: string; level: "no_travel" | "severe" | "high" }) {
  return (
    <span className="stat">
      <span className="stat-label">
        <span className="dot" style={{ background: levelColor(level) }} aria-hidden="true" />
        {label}
      </span>
      <span className="stat-value">{value}</span>
    </span>
  );
}
