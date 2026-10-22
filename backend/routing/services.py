import logging
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

from routing import geometry
from routing.errors import (
    DepartureRejected,
    InvalidTrip,
    NoRouteFound,
    UpstreamBadResponse,
    UpstreamUnavailable,
)
from routing.geometry import LatLon
from routing.providers import open_meteo, tomtom
from routing.providers.open_meteo import Forecast, hour_ceil
from routing.ranking import RouteMetrics, deciding_reason, rank, route_metrics
from routing.risk import Assessment, Level, Weather, assess

logger = logging.getLogger(__name__)

DEPARTURE_GRACE = timedelta(minutes=15)
DEPARTURE_HORIZON = timedelta(days=7)
ROUTE_CACHE_SECONDS = 15 * 60
MAX_ROUTES_SHOWN = 3
WORKING_TOLERANCE_MI = 0.01
DISPLAY_TOLERANCE_MI = 0.03
HEATMAP_HOURS = 48
CORRIDOR_BUFFER_MI = 25.0
CORRIDOR_TOLERANCE_MI = 0.5
LEVEL_NAMES = {
    Level.LOW: "low",
    Level.MODERATE: "moderate",
    Level.HIGH: "high",
    Level.SEVERE: "severe",
    Level.NO_TRAVEL: "no_travel",
}


@dataclass(frozen=True)
class TripRequest:
    origin: LatLon
    destination: LatLon
    departure_local: datetime | None
    load_weight_lb: int
    interval_miles: int


@dataclass(frozen=True)
class Departure:
    utc: datetime
    local: datetime
    timezone: str


def resolve_departure(departure_local: datetime | None, tz_name: str, now: datetime) -> Departure:
    """Interpret a wall-clock time at the origin; None means leaving now.

    A time repeated when clocks go back resolves to its first occurrence (fold=0). A time
    skipped when clocks go forward does not survive a round trip through UTC and is rejected.
    """
    zone = ZoneInfo(tz_name)
    if departure_local is None:
        # Whole minutes, so a re-plan within the same minute reuses the cached routes.
        utc = now.replace(second=0, microsecond=0)
        return Departure(utc=utc, local=utc.astimezone(zone), timezone=tz_name)
    local = departure_local.replace(tzinfo=zone, fold=0)
    utc = local.astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != departure_local:
        raise InvalidTrip(
            f"This local time does not exist in {tz_name} (clocks move forward). "
            "Pick a time outside the skipped hour."
        )
    if utc < now - DEPARTURE_GRACE:
        raise InvalidTrip("Departure must not be more than 15 minutes in the past.")
    if utc > now + DEPARTURE_HORIZON:
        raise InvalidTrip("Departure must be within the next 7 days, the reliable forecast range.")
    return Departure(utc=utc, local=local, timezone=tz_name)


def _fetch_candidates(
    trip: TripRequest, departure: Departure, now: datetime
) -> tuple[list[tomtom.RouteCandidate], bool]:
    (olat, olon), (dlat, dlon) = trip.origin, trip.destination
    key = f"routes:{olat:.5f},{olon:.5f}:{dlat:.5f},{dlon:.5f}:{int(departure.utc.timestamp())}"
    cached: tuple[list[tomtom.RouteCandidate], bool] | None = cache.get(key)
    if cached is not None:
        return cached

    depart_at = departure.local.isoformat(timespec="seconds")
    substituted = False
    try:
        candidates = tomtom.calculate_routes(trip.origin, trip.destination, depart_at)
    except DepartureRejected:
        if departure.utc >= now:
            raise
        # Inside the grace window only: TomTom may refuse a past departAt, so ask for "now".
        candidates = tomtom.calculate_routes(trip.origin, trip.destination, "now")
        substituted = True
    cache.set(key, (candidates, substituted), ROUTE_CACHE_SECONDS)
    return candidates, substituted


@dataclass
class _Checkpoint:
    mile: float
    position: LatLon
    eta: datetime
    share_mi: float
    forecast: Forecast | None = None
    weather: Weather | None = None
    assessment: Assessment | None = None


@dataclass
class _Route:
    candidate: tomtom.RouteCandidate
    working: list[LatLon]
    cumulative: list[float]
    checkpoints: list[_Checkpoint]

    def metrics(self) -> RouteMetrics:
        return route_metrics(
            [cp.assessment.level if cp.assessment else None for cp in self.checkpoints],
            [cp.share_mi for cp in self.checkpoints],
            self.candidate.travel_time_s,
        )

    def max_level(self) -> str | None:
        levels = [
            cp.assessment.level
            for cp in self.checkpoints
            if cp.assessment and cp.assessment.level is not None
        ]
        return LEVEL_NAMES[max(levels)] if levels else None


def _build_route(
    candidate: tomtom.RouteCandidate, working: list[LatLon], departure: Departure, interval: int
) -> _Route:
    cumulative = geometry.cumulative_mi(candidate.points)
    if any(index >= len(cumulative) for index, _ in candidate.progress):
        raise UpstreamBadResponse("TomTom returned timing data that does not match the route.")
    anchor_miles = [cumulative[index] for index, _ in candidate.progress]
    anchor_seconds = [float(seconds) for _, seconds in candidate.progress]
    miles = geometry.sample_miles(cumulative[-1], interval)
    shares = geometry.attribute_miles(miles)
    checkpoints = [
        _Checkpoint(
            mile=mile,
            position=geometry.position_at(candidate.points, cumulative, mile),
            eta=departure.utc
            + timedelta(seconds=geometry.interpolate(anchor_miles, anchor_seconds, mile)),
            share_mi=share,
        )
        for mile, share in zip(miles, shares, strict=True)
    ]
    return _Route(
        candidate=candidate,
        working=working,
        cumulative=cumulative,
        checkpoints=checkpoints,
    )


def _attach_weather(routes: list[_Route], load_lb: int, now: datetime) -> list[str]:
    checkpoints = [cp for route in routes for cp in route.checkpoints]
    warnings: list[str] = []
    try:
        forecasts: list[Forecast | None] = list(
            open_meteo.forecasts(
                [cp.position for cp in checkpoints],
                now=now,
                until=max(cp.eta for cp in checkpoints),
            )
        )
    except UpstreamUnavailable as exc:
        logger.warning("checkpoint weather unavailable: %s", exc.message)
        warnings.append(f"{exc.message} Routes are shown without weather and none is recommended.")
        forecasts = [None] * len(checkpoints)

    for cp, forecast in zip(checkpoints, forecasts, strict=True):
        cp.forecast = forecast
        cp.weather = forecast.at(hour_ceil(cp.eta)) if forecast else Weather(None, None, None, None)
        cp.assessment = assess(cp.weather, load_lb)
    return warnings


def plan_trip(trip: TripRequest, now: datetime) -> dict[str, Any]:
    [origin_forecast] = open_meteo.forecasts([trip.origin], now=now, until=now)
    departure = resolve_departure(trip.departure_local, origin_forecast.timezone, now)

    candidates, substituted = _fetch_candidates(trip, departure, now)
    domestic = [c for c in candidates if c.countries == frozenset({"USA"})]
    if not domestic:
        raise NoRouteFound("No truck route between these points stays within the United States.")
    # Simplified once: within 16 m of the road, far inside the 0.25 mi duplicate tolerance.
    working = [geometry.simplify(c.points, WORKING_TOLERANCE_MI) for c in domestic]
    kept = geometry.distinct_routes(working)

    routes = [_build_route(domestic[i], working[i], departure, trip.interval_miles) for i in kept]
    warnings = _attach_weather(routes, trip.load_weight_lb, now)

    metrics = [r.metrics() for r in routes]
    order = rank(metrics)[:MAX_ROUTES_SHOWN]
    shown = [(routes[i], metrics[i]) for i in order]
    if len(shown) < MAX_ROUTES_SHOWN:
        warnings.append(
            f"Only {len(shown)} distinct route{'s' if len(shown) != 1 else ''} "
            "could be found for this trip."
        )
    if substituted:
        warnings.append(
            "The routing service would not accept a departure time in the past, so traffic "
            "was modelled from the current time. Arrival times still count from your entered "
            "departure."
        )

    best = shown[0][1]
    recommended = best.drivable
    if recommended:
        runner_up = shown[1][1] if len(shown) > 1 else None
        reason = f"Recommended because {deciding_reason(best, runner_up)}."
    elif not best.complete:
        reason = "No route is recommended because weather data is missing."
    else:
        reason = (
            "No route is safe to drive at this departure time: every route has No Travel "
            "conditions. Try a later departure."
        )

    return {
        "departure": {
            "local": departure.local.isoformat(timespec="minutes"),
            "utc": departure.utc.isoformat(timespec="minutes"),
            "timezone": departure.timezone,
            "utc_offset": departure.local.strftime("%z"),
            "substituted_now": substituted,
        },
        "recommendation": {"route_id": 0 if recommended else None, "reason": reason},
        "warnings": warnings,
        "routes": [
            _serialize_route(route, m, rank_index, recommended and rank_index == 0, departure)
            for rank_index, (route, m) in enumerate(shown)
        ],
    }


def _level_name(assessment: Assessment | None) -> str:
    if assessment is None or assessment.level is None:
        return "unknown"
    return LEVEL_NAMES[assessment.level]


def _decimal_out(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _lon_lat(points: list[LatLon], digits: int) -> list[list[float]]:
    return [[round(lon, digits), round(lat, digits)] for lat, lon in points]


def _segments(route: _Route, display: list[LatLon]) -> list[dict[str, Any]]:
    """Pieces of the display line coloured by the checkpoint whose miles they belong to.

    Checkpoint boundaries are measured on the full route and scaled onto the simplified
    display line, which is a few metres shorter.
    """
    cumulative = geometry.cumulative_mi(display)
    scale = cumulative[-1] / route.cumulative[-1] if route.cumulative[-1] else 0.0
    cps = route.checkpoints
    segments = []
    for i, cp in enumerate(cps):
        start = (cps[i - 1].mile + cp.mile) / 2 * scale if i > 0 else 0.0
        end = (cp.mile + cps[i + 1].mile) / 2 * scale if i < len(cps) - 1 else cumulative[-1]
        if end <= start:
            continue
        first, last = bisect_right(cumulative, start), bisect_left(cumulative, end)
        piece = [
            geometry.position_at(display, cumulative, start),
            *display[first:last],
            geometry.position_at(display, cumulative, end),
        ]
        segments.append({"level": _level_name(cp.assessment), "coordinates": _lon_lat(piece, 5)})
    return segments


def _serialize_route(
    route: _Route, metrics: RouteMetrics, rank_index: int, recommended: bool, departure: Departure
) -> dict[str, Any]:
    candidate = route.candidate
    display = geometry.simplify(route.working, DISPLAY_TOLERANCE_MI)
    return {
        "id": rank_index,
        "rank": rank_index + 1,
        "recommended": recommended,
        "drivable": metrics.drivable,
        "complete": metrics.complete,
        "summary": {
            "distance_mi": round(route.cumulative[-1], 1),
            "duration_s": candidate.travel_time_s,
            "traffic_delay_s": candidate.traffic_delay_s,
            "departure_utc": departure.utc.isoformat(timespec="minutes"),
            "arrival_utc": (departure.utc + timedelta(seconds=candidate.travel_time_s)).isoformat(
                timespec="minutes"
            ),
            "no_travel_mi": round(metrics.no_travel_mi, 2),
            "severe_mi": round(metrics.severe_mi, 2),
            "high_mi": round(metrics.high_mi, 2),
            "avg_risk": None if metrics.avg_risk is None else round(metrics.avg_risk, 2),
            "max_level": route.max_level(),
        },
        "geometry": _lon_lat(display, 5),
        "corridor": _lon_lat(geometry.simplify(display, CORRIDOR_TOLERANCE_MI), 4),
        "segments": _segments(route, display),
        "checkpoints": [
            {
                "mile": round(cp.mile, 1),
                "share_mi": round(cp.share_mi, 2),
                "lat": round(cp.position[0], 5),
                "lon": round(cp.position[1], 5),
                "eta_utc": cp.eta.isoformat(timespec="minutes"),
                "forecast_hour_utc": datetime.fromtimestamp(hour_ceil(cp.eta), UTC).isoformat(
                    timespec="minutes"
                ),
                "timezone": cp.forecast.timezone if cp.forecast else departure.timezone,
                "weather": {
                    "wind_mph": _decimal_out(cp.weather.wind_mph if cp.weather else None),
                    "gust_mph": _decimal_out(cp.weather.gust_mph if cp.weather else None),
                    "rain_in_hr": _decimal_out(cp.weather.rain_in_hr if cp.weather else None),
                    "snow_in_hr": _decimal_out(cp.weather.snow_in_hr if cp.weather else None),
                },
                "level": _level_name(cp.assessment),
                "drivers": list(cp.assessment.drivers) if cp.assessment else [],
                "load_escalated": bool(cp.assessment and cp.assessment.load_escalated),
            }
            for cp in route.checkpoints
        ],
    }


def _level_code(assessment: Assessment) -> int:
    """-1 marks unknown weather in the compact heatmap payload."""
    return -1 if assessment.level is None else int(assessment.level)


def build_heatmap(
    routes: list[list[LatLon]], departure_utc: datetime, load_lb: int, now: datetime
) -> dict[str, Any]:
    if departure_utc < now - DEPARTURE_GRACE or departure_utc > now + DEPARTURE_HORIZON:
        raise InvalidTrip("Heatmap departure is outside the supported forecast window.")
    spacing, cells = geometry.corridor_cells(routes, CORRIDOR_BUFFER_MI, settings.HEATMAP_MAX_CELLS)
    stamps = [hour_ceil(departure_utc + timedelta(hours=h)) for h in range(HEATMAP_HOURS + 1)]
    forecasts = open_meteo.forecasts(
        cells, now=now, until=departure_utc + timedelta(hours=HEATMAP_HOURS)
    )

    frames = []
    for stamp in stamps:
        weather = [f.at(stamp) for f in forecasts]
        frames.append(
            {
                "time_utc": datetime.fromtimestamp(stamp, UTC).isoformat(timespec="minutes"),
                "levels": [_level_code(assess(w, load_lb)) for w in weather],
                "wind_mph": [_decimal_out(w.wind_mph) for w in weather],
                "rain_in_hr": [_decimal_out(w.rain_in_hr) for w in weather],
                "snow_in_hr": [_decimal_out(w.snow_in_hr) for w in weather],
            }
        )
    return {
        "spacing_deg": spacing,
        "cells": [[lon, lat] for lat, lon in cells],
        "frames": frames,
    }
