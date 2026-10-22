# Truck Weather Routing

A React + Django app that helps a truck driver pick the safest of three routes. Weather is sampled along each route at the hour the truck is expected to reach each checkpoint. Each checkpoint is scored with the assignment's risk and load rules, and the routes are ranked by Severe miles, High miles, average risk and travel time.

**Live app:** _added after deployment_

## What it does

- Takes origin and destination (US addresses), departure date and time (origin local time), load weight in pounds, and a checkpoint interval of 10, 25 or 50 miles.
- Requests truck routes from TomTom (up to five alternatives), drops near-duplicates and any route that leaves the United States, and keeps the three best distinct routes.
- Places checkpoints along each route and estimates the arrival time at each one from TomTom's own per-point travel times.
- Reads the Open-Meteo forecast for the hour the truck reaches each checkpoint, then classifies wind, rain and snow with the risk table and load rules.
- Ranks the routes, recommends one (or none, with the reason), and shows everything on a map: routes coloured by risk, checkpoints with arrival time and weather, route summaries, and a risk heatmap along the corridor with a 0–48 hour slider.

## Architecture

```
frontend/  React 19 + TypeScript + Vite + MapLibre GL (OpenFreeMap tiles, no key)
             │  JSON over HTTPS
backend/   Django 6 + Django REST Framework, stateless (no database)
             ├── TomTom Search       geocoding (US only)
             ├── TomTom Routing      truck routes + alternatives + per-point travel time
             └── Open-Meteo          hourly forecasts, many locations per request
```

All third-party calls go through the backend, so the TomTom key never reaches the browser. The scoring logic lives in three modules with no I/O, so it is tested without the network:

| Module | Responsibility |
|---|---|
| `routing/risk.py` | Risk bands, load rules, worst-factor checkpoint level |
| `routing/geometry.py` | Distances, checkpoint placement, ETA interpolation, mile attribution, route de-duplication, heatmap corridor |
| `routing/ranking.py` | Per-route metrics and the ranking order |
| `routing/services.py` | Orchestrates providers and the modules above |

## Risk rules and how edge cases are read

Thresholds come from the assignment:

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind | <25 mph | 25–34 | 35–44 | 45–54 | ≥55 mph |
| Rain | <0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow | <0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

Load rules: 45–54 mph with more than 30,000 lb becomes No Travel; 35–44 mph with more than 40,000 lb becomes Severe.

The table leaves some cases open. They are resolved as follows:

- **Band edges** are half-open, `[low, high)`, with no rounding. Wind of 34.6 mph is Moderate; rain of exactly 0.25 in/hr is High. The No Travel edges for rain and snow are written as strict `>`, so 1.00 in/hr rain and 3.0 in/hr snow stay Severe.
- **Wind** is Open-Meteo's hourly 10 m wind speed. Gusts are shown in checkpoint details but not scored.
- **Rain** is `rain + showers`. Open-Meteo reports convective showers separately, and leaving them out would under-count thunderstorms.
- **Snow** is snowfall depth per hour in inches.
- **Exact arithmetic:** forecast values are parsed as decimals, because floating-point `0.01 + 0.09` lands just below the 0.10 edge.
- **Load rules** apply only to wind, as the assignment states them.
- **A checkpoint's level** is the worst of wind (after the load rule), rain and snow.
- **Missing weather is never treated as Low.** A checkpoint without data is "unknown", and its route is not recommended.

## Checkpoints, arrival times and miles

- Checkpoints sit at mile 0, then every 10/25/50 miles, then at the destination.
- **Arrival time:** departure plus TomTom's cumulative travel time at that point on the route, interpolated by distance between TomTom's timing points. Slow urban stretches and historic traffic are therefore reflected.
- **Forecast hour:** a checkpoint reads the forecast hour that contains its arrival. Open-Meteo's hourly precipitation covers the hour ending at each timestamp.
- **Miles per checkpoint:** each checkpoint represents half the distance to each neighbour, so the miles add up exactly to the route length.
- **Departure time** is entered in the origin's local time:
  - A time repeated when clocks fall back resolves to its first occurrence.
  - A time skipped when clocks spring forward is rejected.
  - Arrival times are shown in each checkpoint's own time zone.

## Recommendation

Routes are ranked lexicographically:

1. Fewest No Travel miles. No Travel is worse than Severe, so it is compared first.
2. Fewest Severe miles
3. Fewest High miles
4. Lowest average risk (distance-weighted; Low 0, Moderate 1, High 2, Severe 3, No Travel 4)
5. Shortest travel time

Travel time only breaks ties, which is how this app reads "balancing weather risk and travel time" given the assignment's ordered list. A route with unknown weather ranks after every fully forecast route. No route is recommended if even the best one has No Travel miles or missing weather. The app says why, and suggests a later departure.

## Heatmap

The heatmap colours a grid of cells within about 25 miles of the routes by combined, load-aware risk, using the same rules as the checkpoints. The grid is snapped to fixed coordinates so overlapping trips reuse cached forecasts. Spacing coarsens from 0.1° to 1° to keep about 300 cells or fewer.

The slider runs from the departure hour (hour 0) to 48 hours later. All 49 frames load in one request. Moving the slider only updates per-cell map state, with no network request and no layer rebuild.

## Running locally

Requirements: Python 3.12, Node 22.12+ (Node 24 recommended).

```bash
# Backend
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env           # then set TOMTOM_API_KEY (see below)
.venv/bin/python manage.py runserver 8000

# Frontend (second terminal)
cd frontend
npm ci
cp .env.example .env           # VITE_API_BASE_URL=http://localhost:8000
npm run dev                    # http://localhost:5173
```

### TomTom API key

1. Create a free account at [my.tomtom.com](https://my.tomtom.com).
2. Under **Keys**, create a key with only **Routing API** and **Search API** ticked.
3. Put it in `backend/.env` as `TOMTOM_API_KEY=...`. It is read by the backend only and never sent to the browser.

### Tests and checks

```bash
cd backend
.venv/bin/pytest                     # all upstream APIs are stubbed
.venv/bin/coverage run -m pytest && .venv/bin/coverage report
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy .

cd ../frontend
npm test && npm run lint && npm run typecheck && npm run build
```

CI runs the same checks on every push and pull request (`.github/workflows/ci.yml`).

## API

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/health` | — | `{"status": "ok"}` |
| GET | `/api/geocode` | `q` (3–100 chars) | `{"results": [{label, lat, lon}]}` |
| POST | `/api/plan` | `origin {lat, lon}`, `destination {lat, lon}`, `departure_local` (`YYYY-MM-DDTHH:MM`), `load_weight_lb` (0–80,000), `interval_miles` (10, 25 or 50) | Departure, recommendation, warnings, and up to three ranked routes with summary, geometry, risk-coloured segments and checkpoints |
| POST | `/api/heatmap` | `routes` (≤3 `[lon, lat]` lines from the plan's `corridor`), `departure_utc`, `load_weight_lb` | Cells and 49 hourly frames of risk levels and weather values |

**Errors** return `{"detail": "..."}` with a readable message:
- 400: invalid input, or a departure outside the window (15 minutes ago to 7 days ahead).
- 422: no route, or no route that stays in the US.
- 502/503: provider problems.

Field validation errors use DRF's per-field format.

## Deployment (Render)

`render.yaml` defines both services: the Django API as a Python web service and the React app as a static site.

1. In Render, create a Blueprint from this repository.
2. When prompted, enter `TOMTOM_API_KEY`. Leave `NUM_PROXIES` empty for now.
3. If Render assigns URLs other than `truck-routing-api.onrender.com` / `truck-routing-web.onrender.com`, update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL`, then redeploy the static site so the new API URL is built in.
4. Rate limiting is per client IP. Once deployed, check the `X-Forwarded-For` header Render passes to the API. Set `NUM_PROXIES` to the number of proxy entries after the client address, usually `1`. Without it, a client could vary that header to get around the limit.

The free web service sleeps after a period of inactivity, and the first request can take up to a minute. The app shows a "still working" message while it waits.

## Known limitations

- **Arrival times assume continuous driving.** Hours-of-service rest breaks are not modelled.
- **No vehicle weight is sent to TomTom.** The assignment gives load weight, not gross vehicle weight, so weight-restricted roads are not avoided. Load weight is used in the risk rules as specified.
- **Forecast accuracy** falls off with lead time. Departures are limited to the next 7 days.
- **Long trips are slow to plan.** TomTom takes 12–35 s to return truck routes with five alternatives, so the backend waits up to 40 s. A coast-to-coast plan can take close to a minute in total.
- **Free-tier limits:**
  - TomTom's free tier gives each API its own monthly request allowance; see [TomTom pricing](https://docs.tomtom.com/pricing).
  - Open-Meteo limits are counted per IP address, so a shared host such as Render may reach them sooner.
  - Responses are cached to stay within both. When weather is unavailable, routes are still shown and none is recommended.

## Data and licences

- Weather: [Open-Meteo](https://open-meteo.com/), CC BY 4.0. The free API is for non-commercial use, which this assessment is; commercial use needs an Open-Meteo subscription.
- Routing and geocoding: [TomTom](https://docs.tomtom.com/).
- Map tiles: [OpenFreeMap](https://openfreemap.org/), © [OpenMapTiles](https://openmaptiles.org/), © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
