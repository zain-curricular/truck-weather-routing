import { useEffect, useRef, useState } from "react";

import type { HeatmapFrame } from "../api/types";
import { formatInZone } from "../lib/format";

interface Props {
  frames: HeatmapFrame[];
  timeZone: string;
  onHour: (hour: number) => void;
}

/** Owns its own state so dragging re-renders only the slider; map updates are coalesced per frame. */
export function HeatmapSlider({ frames, timeZone, onHour }: Props) {
  const [hour, setHour] = useState(0);
  const pending = useRef<number | null>(null);
  const frameRequest = useRef(0);
  const onHourRef = useRef(onHour);

  useEffect(() => {
    onHourRef.current = onHour;
  }, [onHour]);

  useEffect(() => () => cancelAnimationFrame(frameRequest.current), []);

  function change(next: number) {
    setHour(next);
    pending.current = next;
    if (frameRequest.current) return;
    frameRequest.current = requestAnimationFrame(() => {
      frameRequest.current = 0;
      if (pending.current !== null) onHourRef.current(pending.current);
    });
  }

  const frame = frames[hour];
  const max = frames.length - 1;
  return (
    <div className="heatmap-slider">
      <label htmlFor="forecast-hour">
        <span className="slider-title">Weather heatmap</span>
        <span className="slider-time">
          +{hour} h · {frame ? formatInZone(frame.time_utc, timeZone) : ""}
        </span>
      </label>
      <input
        id="forecast-hour"
        type="range"
        min={0}
        max={max}
        step={1}
        value={hour}
        aria-valuetext={`${hour} hours after departure`}
        onChange={(event) => change(Number(event.target.value))}
      />
      <div className="slider-scale" aria-hidden="true">
        <span>Departure</span>
        <span>+24 h</span>
        <span>+{max} h</span>
      </div>
    </div>
  );
}
