import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.cache import cache

from routing.errors import UpstreamBadResponse, UpstreamUnavailable
from routing.geometry import LatLon
from routing.providers.http import ClientError, get_json
from routing.risk import Weather

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SERVICE = "Open-Meteo"
HOURLY_VARIABLES = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
LOCATIONS_PER_REQUEST = 100
MAX_FORECAST_HOURS = 16 * 24
CACHE_SECONDS = 3600


@dataclass(frozen=True)
class Forecast:
    timezone: str
    times: tuple[int, ...]
    wind: tuple[Decimal | None, ...]
    gust: tuple[Decimal | None, ...]
    rain: tuple[Decimal | None, ...]
    snow: tuple[Decimal | None, ...]
    _index: dict[int, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {t: i for i, t in enumerate(self.times)})

    def at(self, stamp: int) -> Weather:
        i = self._index.get(stamp)
        if i is None:
            return Weather(None, None, None, None)
        return Weather(self.wind[i], self.gust[i], self.rain[i], self.snow[i])


def hour_floor(moment: datetime) -> int:
    return int(moment.timestamp()) // 3600 * 3600


def hour_ceil(moment: datetime) -> int:
    return math.ceil(moment.timestamp() / 3600) * 3600


def _rounded(point: LatLon) -> LatLon:
    return (round(point[0], 4), round(point[1], 4))


def forecasts(points: Sequence[LatLon], *, now: datetime, until: datetime) -> list[Forecast]:
    """Hourly forecasts from the hour before `now` through `until`, one per point, in order.
    Hours count from the current UTC hour, so every point and cached series shares stamps."""
    first_stamp = hour_floor(now)
    last_stamp = hour_ceil(until)
    hours = min(MAX_FORECAST_HOURS, (last_stamp - first_stamp) // 3600 + 1)
    rounded = [_rounded(p) for p in points]
    keys = {p: f"om:{p[0]:.4f}:{p[1]:.4f}:{first_stamp}" for p in rounded}

    found: dict[LatLon, Forecast] = {}
    cached_by_key = cache.get_many(list(set(keys.values())))
    for p, key in keys.items():
        forecast = cached_by_key.get(key)
        if forecast is not None and forecast.times and forecast.times[-1] >= last_stamp:
            found[p] = forecast

    missing = sorted({p for p in rounded if p not in found})
    for start in range(0, len(missing), LOCATIONS_PER_REQUEST):
        batch = missing[start : start + LOCATIONS_PER_REQUEST]
        fetched = _fetch(batch, hours)
        found.update(fetched)
        cache.set_many({keys[p]: f for p, f in fetched.items()}, CACHE_SECONDS)

    return [found[p] for p in rounded]


def _fetch(points: Sequence[LatLon], hours: int) -> dict[LatLon, Forecast]:
    params: dict[str, str | int] = {
        "latitude": ",".join(f"{p[0]:.4f}" for p in points),
        "longitude": ",".join(f"{p[1]:.4f}" for p in points),
        "hourly": HOURLY_VARIABLES,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timeformat": "unixtime",
        "timezone": "auto",
        "past_hours": 1,
        "forecast_hours": hours,
    }
    try:
        body = get_json(FORECAST_URL, params, service=SERVICE, exact_decimals=True)
    except ClientError as exc:
        raise UpstreamUnavailable("Open-Meteo could not provide a forecast for this trip.") from exc

    locations = body if isinstance(body, list) else [body]
    if len(locations) != len(points):
        raise UpstreamBadResponse("Open-Meteo returned forecasts for the wrong number of places.")
    try:
        return {p: _parse(loc) for p, loc in zip(points, locations, strict=True)}
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamBadResponse(
            "Open-Meteo returned a forecast in an unexpected format."
        ) from exc


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _parse(location: dict[str, Any]) -> Forecast:
    hourly = location["hourly"]
    rain = [_decimal(v) for v in hourly["rain"]]
    showers = [_decimal(v) for v in hourly["showers"]]
    return Forecast(
        timezone=str(location["timezone"]),
        times=tuple(int(t) for t in hourly["time"]),
        wind=tuple(_decimal(v) for v in hourly["wind_speed_10m"]),
        gust=tuple(_decimal(v) for v in hourly["wind_gusts_10m"]),
        rain=tuple(
            None if r is None or s is None else r + s for r, s in zip(rain, showers, strict=True)
        ),
        snow=tuple(_decimal(v) for v in hourly["snowfall"]),
    )
