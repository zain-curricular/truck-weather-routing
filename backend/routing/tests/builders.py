"""Response builders shaped like the documented TomTom and Open-Meteo payloads."""

import json
from urllib.parse import parse_qs, urlparse

from routing.geometry import MI_PER_DEG_LAT, cumulative_mi


def east_west(miles: float, lat: float = 0.0, step_mi: float = 1.0, start_lon: float = 0.0):
    n = max(1, round(miles / step_mi))
    return [(lat, start_lon + miles * i / n / MI_PER_DEG_LAT) for i in range(n + 1)]


def tomtom_route(points, *, mph: float = 60.0, countries=("USA",), progress_every: int = 5):
    cumulative = cumulative_mi(points)
    seconds = [round(m / mph * 3600) for m in cumulative]
    indexes = sorted(set(range(0, len(points), progress_every)) | {len(points) - 1})
    return {
        "summary": {
            "lengthInMeters": round(cumulative[-1] * 1609.344),
            "travelTimeInSeconds": seconds[-1],
            "trafficDelayInSeconds": 0,
        },
        "legs": [{"points": [{"latitude": lat, "longitude": lon} for lat, lon in points]}],
        "sections": [
            {"startPointIndex": 0, "endPointIndex": len(points) - 1, "sectionType": "TRAVEL_MODE"},
            *(
                {
                    "startPointIndex": 0,
                    "endPointIndex": len(points) - 1,
                    "sectionType": "COUNTRY",
                    "countryCode": code,
                }
                for code in countries
            ),
        ],
        "progress": [
            {
                "pointIndex": i,
                "distanceInMeters": round(cumulative[i] * 1609.344),
                "travelTimeInSeconds": seconds[i],
            }
            for i in indexes
        ],
    }


def tomtom_body(*routes, avoid: str | None = "borderCrossings"):
    settings = [{"key": "travelMode", "value": "truck"}]
    if avoid is not None:
        settings.append({"key": "avoid", "value": avoid})
    return {"routes": list(routes), "report": {"effectiveSettings": settings}}


def open_meteo_location(
    times, *, wind=10.0, gust=15.0, rain=0.0, showers=0.0, snow=0.0, tz="America/Chicago"
):
    def series(value):
        return value if isinstance(value, list) else [value] * len(times)

    return {
        "timezone": tz,
        "hourly": {
            "time": list(times),
            "wind_speed_10m": series(wind),
            "wind_gusts_10m": series(gust),
            "rain": series(rain),
            "showers": series(showers),
            "snowfall": series(snow),
        },
    }


CALM = {"wind": 5.0, "gust": 8.0, "rain": 0.0, "showers": 0.0, "snow": 0.0}


def fake_open_meteo(weather_at, *, first_stamp: int, tz="America/Chicago"):
    """A `responses` callback answering any batch of points with `weather_at(lat, lon, stamp)`.

    `weather_at` returns a dict of overrides for wind/gust/rain/showers/snow.
    """

    def callback(request):
        params = parse_qs(urlparse(request.url).query)
        lats = [float(v) for v in params["latitude"][0].split(",")]
        lons = [float(v) for v in params["longitude"][0].split(",")]
        hours = int(params["forecast_hours"][0]) + int(params["past_hours"][0])
        times = [first_stamp - 3600 + i * 3600 for i in range(hours)]
        body = []
        for lat, lon in zip(lats, lons, strict=True):
            rows = [CALM | weather_at(lat, lon, t) for t in times]
            location = open_meteo_location(
                times,
                wind=[r["wind"] for r in rows],
                gust=[r["gust"] for r in rows],
                rain=[r["rain"] for r in rows],
                showers=[r["showers"] for r in rows],
                snow=[r["snow"] for r in rows],
                tz=tz,
            )
            body.append(location)
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps(body if len(body) > 1 else body[0]),
        )

    return callback
