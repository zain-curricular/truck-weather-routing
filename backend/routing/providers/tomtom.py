from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from django.conf import settings

from routing.errors import DepartureRejected, NoRouteFound, UpstreamAuth, UpstreamBadResponse
from routing.geometry import LatLon
from routing.providers.http import ClientError, get_json

ROUTING_URL = "https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
SEARCH_URL = "https://api.tomtom.com/search/2/search/{query}.json"
SERVICE = "TomTom"
MAX_ALTERNATIVES = 5
# Truck routes with five alternatives take TomTom 12-35 s; coast-to-coast trips are the slowest.
ROUTING_TIMEOUT = (3.0, 40.0)


@dataclass(frozen=True)
class RouteCandidate:
    points: list[LatLon]
    length_m: int
    travel_time_s: int
    traffic_delay_s: int
    # (pointIndex, cumulative seconds from departure)
    progress: list[tuple[int, int]]
    countries: frozenset[str]


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float


def _key() -> str:
    if not settings.TOMTOM_API_KEY:
        raise UpstreamAuth("Routing is not configured on the server (missing TomTom API key).")
    return str(settings.TOMTOM_API_KEY)


def calculate_routes(origin: LatLon, destination: LatLon, depart_at: str) -> list[RouteCandidate]:
    """Truck routes with alternatives, in TomTom's order (reference route first).

    `depart_at` is an RFC 3339 time with offset, or "now".
    """
    locations = f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}"
    params: dict[str, str | int | list[str]] = {
        "key": _key(),
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "departAt": depart_at,
        "maxAlternatives": MAX_ALTERNATIVES,
        "alternativeType": "anyRoute",
        "traffic": "true",
        "routeRepresentation": "polyline",
        "extendedRouteRepresentation": ["distance", "travelTime"],
        "sectionType": "country",
        "avoid": "borderCrossings",
        "report": "effectiveSettings",
    }
    try:
        body = get_json(
            ROUTING_URL.format(locations=locations),
            params,
            service=SERVICE,
            timeout=ROUTING_TIMEOUT,
        )
    except ClientError as exc:
        raise _routing_client_error(exc) from None

    _require_border_restriction(body)
    try:
        return [_parse_route(route) for route in body["routes"]]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise UpstreamBadResponse("TomTom returned a route in an unexpected format.") from exc


def _routing_client_error(exc: ClientError) -> Exception:
    detail = exc.body.get("detailedError", {}) if isinstance(exc.body, dict) else {}
    text = f"{detail.get('code', '')} {detail.get('message', '')}".lower()
    if "departat" in text or "departure" in text:
        return DepartureRejected("TomTom rejected the departure time.")
    return NoRouteFound("No truck route could be found between these points.")


def _require_border_restriction(body: dict[str, Any]) -> None:
    settings_used = body.get("report", {}).get("effectiveSettings", [])
    avoided = {
        value
        for item in settings_used
        if item.get("key") == "avoid"
        for value in str(item.get("value", "")).split(",")
    }
    if "borderCrossings" not in avoided:
        raise UpstreamBadResponse("Routing provider did not apply the border restriction.")


def _parse_route(route: dict[str, Any]) -> RouteCandidate:
    summary = route["summary"]
    points = [
        (float(p["latitude"]), float(p["longitude"]))
        for leg in route["legs"]
        for p in leg["points"]
    ]
    progress = [
        (int(entry["pointIndex"]), int(entry["travelTimeInSeconds"])) for entry in route["progress"]
    ]
    country_sections = [s for s in route["sections"] if s.get("sectionType") == "COUNTRY"]
    if not country_sections:
        raise ValueError("route has no country sections")
    if len(points) < 2 or len(progress) < 2:
        raise ValueError("route has too few points")
    return RouteCandidate(
        points=points,
        length_m=int(summary["lengthInMeters"]),
        travel_time_s=int(summary["travelTimeInSeconds"]),
        traffic_delay_s=int(summary.get("trafficDelayInSeconds", 0)),
        progress=progress,
        countries=frozenset(str(s["countryCode"]) for s in country_sections),
    )


def search_places(query: str) -> list[Place]:
    params: dict[str, str | int] = {
        "key": _key(),
        "countrySet": "US",
        "typeahead": "true",
        "limit": 6,
    }
    try:
        body = get_json(SEARCH_URL.format(query=quote(query, safe="")), params, service=SERVICE)
    except ClientError:
        return []
    places = []
    for result in body.get("results", []):
        address = result.get("address", {}).get("freeformAddress", "")
        name = result.get("poi", {}).get("name")
        label = f"{name}, {address}" if name and address else name or address
        position = result.get("position", {})
        if label and "lat" in position and "lon" in position:
            places.append(
                Place(label=label, lat=float(position["lat"]), lon=float(position["lon"]))
            )
    return places
