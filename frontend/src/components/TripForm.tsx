import { useState } from "react";

import type { Place, PlanRequest } from "../api/types";
import { INTERVALS, MAX_LOAD_LB, validateTrip } from "../lib/validation";
import { PlaceInput } from "./PlaceInput";

interface Props {
  busy: boolean;
  hasPlan: boolean;
  onSubmit: (request: PlanRequest) => void;
}

function nextQuarterHour(): string {
  const now = new Date(Date.now() + 15 * 60_000);
  now.setMinutes(Math.ceil(now.getMinutes() / 15) * 15, 0, 0);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export function TripForm({ busy, hasPlan, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [departureLocal, setDepartureLocal] = useState(nextQuarterHour);
  const [loadWeight, setLoadWeight] = useState("35000");
  const [interval, setIntervalMiles] = useState<PlanRequest["interval_miles"]>(25);
  const [errors, setErrors] = useState<string[]>([]);

  function submit(intervalMiles = interval) {
    const problems = validateTrip({ origin, destination, departureLocal, loadWeight });
    setErrors(problems);
    if (problems.length || !origin || !destination) return;
    onSubmit({
      origin,
      destination,
      departure_local: departureLocal,
      load_weight_lb: Number(loadWeight),
      interval_miles: intervalMiles,
    });
  }

  return (
    <form
      className="trip-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <PlaceInput label="Origin" value={origin} onChange={setOrigin} />
      <PlaceInput label="Destination" value={destination} onChange={setDestination} />
      <div className="field-row">
        <div className="field">
          <label htmlFor="departure">Departure (origin local time)</label>
          <input
            id="departure"
            type="datetime-local"
            value={departureLocal}
            onChange={(event) => setDepartureLocal(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LOAD_LB}
            step={1000}
            value={loadWeight}
            onChange={(event) => setLoadWeight(event.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <span className="field-label" id="interval-label">
          Weather checkpoint every
        </span>
        <div className="segmented" role="radiogroup" aria-labelledby="interval-label">
          {INTERVALS.map((miles) => (
            <button
              key={miles}
              type="button"
              role="radio"
              aria-checked={interval === miles}
              className={interval === miles ? "selected" : ""}
              disabled={busy}
              onClick={() => {
                setIntervalMiles(miles);
                if (hasPlan) submit(miles);
              }}
            >
              {miles} mi
            </button>
          ))}
        </div>
      </div>
      {errors.length > 0 && (
        <ul className="form-errors" role="alert">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Planning…" : "Plan routes"}
      </button>
    </form>
  );
}
