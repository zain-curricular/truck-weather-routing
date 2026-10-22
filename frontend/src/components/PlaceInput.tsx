import { useEffect, useId, useRef, useState } from "react";

import { searchPlaces } from "../api/client";
import type { Place } from "../api/types";

const DEBOUNCE_MS = 300;
const MIN_QUERY = 3;

interface Props {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
}

export function PlaceInput({ label, value, onChange }: Props) {
  const id = useId();
  const [text, setText] = useState(value?.label ?? "");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const typed = useRef(false);

  useEffect(() => {
    if (!typed.current) return;
    const query = text.trim();
    if (query.length < MIN_QUERY) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchPlaces(query, controller.signal)
        .then((data) => {
          setResults(data.results);
          setError(null);
          setOpen(true);
          setActive(-1);
        })
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError(err instanceof Error ? err.message : "Search failed.");
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  function choose(place: Place) {
    typed.current = false;
    setText(place.label);
    setResults([]);
    setOpen(false);
    onChange(place);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      const place = results[active];
      if (place) choose(place);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const listId = `${id}-list`;
  return (
    <div className="field place-input">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        placeholder="City, address or place in the US"
        value={text}
        onChange={(event) => {
          typed.current = true;
          setText(event.target.value);
          if (event.target.value.trim().length < MIN_QUERY) {
            setResults([]);
            setOpen(false);
          }
          if (value) onChange(null);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {open && results.length > 0 && (
        <ul id={listId} role="listbox" className="suggestions">
          {results.map((place, i) => (
            <li
              key={`${place.lat},${place.lon},${place.label}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(event) => {
                event.preventDefault();
                choose(place);
              }}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
