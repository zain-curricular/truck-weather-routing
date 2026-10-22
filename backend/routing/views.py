import hashlib
from typing import Any

from django.core.cache import cache
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import exception_handler as drf_exception_handler

from routing import services
from routing.errors import TripError
from routing.providers import tomtom
from routing.serializers import (
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)

GEOCODE_CACHE_SECONDS = 24 * 3600


class _PerClientThrottle(SimpleRateThrottle):
    def get_cache_key(self, request: Request, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PlanThrottle(_PerClientThrottle):
    scope = "plan"


class HeatmapThrottle(_PerClientThrottle):
    scope = "heatmap"


class GeocodeThrottle(_PerClientThrottle):
    scope = "geocode"


@api_view(["GET"])
def health(request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
@throttle_classes([GeocodeThrottle])
def geocode(request: Request) -> Response:
    serializer = GeocodeQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = " ".join(serializer.validated_data["q"].lower().split())
    key = f"geocode:{hashlib.sha256(query.encode()).hexdigest()}"
    places = cache.get(key)
    if places is None:
        places = [
            {"label": p.label, "lat": p.lat, "lon": p.lon} for p in tomtom.search_places(query)
        ]
        cache.set(key, places, GEOCODE_CACHE_SECONDS)
    return Response({"results": places})


@api_view(["POST"])
@throttle_classes([PlanThrottle])
def plan(request: Request) -> Response:
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response(services.plan_trip(serializer.to_trip(), now=timezone.now()))


@api_view(["POST"])
@throttle_classes([HeatmapThrottle])
def heatmap(request: Request) -> Response:
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    return Response(
        services.build_heatmap(
            data["routes"], data["departure_utc"], data["load_weight_lb"], now=timezone.now()
        )
    )


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, TripError):
        return Response({"detail": exc.message}, status=exc.status_code)
    return drf_exception_handler(exc, context)
