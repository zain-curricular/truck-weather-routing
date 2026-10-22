import { useState } from "react";

import type { Place, PlanRequest } from "../api/types";
import { INTERVALS, MAX_LOAD_LB, validateTrip } from "../lib/validation";
import { PlaceInput } from "./PlaceInput";

interface Props {
  busy: boolean;
  /** Origin local departure of the plan on screen, as YYYY-MM-DDTHH:MM. */
  planDeparture: string | null;
  onSubmit: (request: PlanRequest) => void;
}

export function TripForm({ busy, planDeparture, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [departureLocal, setDepartureLocal] = useState("");
  const [loadWeight, setLoadWeight] = useState("35000");
  const [interval, setIntervalMiles] = useState<PlanRequest["interval_miles"]>(25);
  const [errors, setErrors] = useState<string[]>([]);

  function submit(intervalMiles = interval, departure = departureLocal || null) {
    const problems = validateTrip({ origin, destination, departureLocal, loadWeight });
    setErrors(problems);
    if (problems.length || !origin || !destination) return;
    onSubmit({
      origin,
      destination,
      departure_local: departure,
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
            aria-describedby="departure-hint"
            value={departureLocal}
            onChange={(event) => setDepartureLocal(event.target.value)}
          />
          <span className="field-hint" id="departure-hint">
            Leave empty to leave now.
          </span>
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
                // Same departure as the plan on screen, so only the checkpoints change.
                if (planDeparture) submit(miles, departureLocal || planDeparture);
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
