from datetime import datetime
from typing import Any

from rest_framework import serializers

from routing.services import TripRequest

MAX_LOAD_LB = 80_000
MAX_HEATMAP_ROUTES = 3
MAX_HEATMAP_POINTS = 2_000


class PointSerializer(serializers.Serializer[dict[str, Any]]):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer[dict[str, Any]]):
    origin = PointSerializer()
    destination = PointSerializer()
    departure_local = serializers.CharField(max_length=16)
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=[10, 25, 50])

    def validate_departure_local(self, value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError as exc:
            raise serializers.ValidationError("Use the format YYYY-MM-DDTHH:MM.") from exc

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        o, d = attrs["origin"], attrs["destination"]
        if (round(o["lat"], 4), round(o["lon"], 4)) == (round(d["lat"], 4), round(d["lon"], 4)):
            raise serializers.ValidationError("Origin and destination must be different places.")
        return attrs

    def to_trip(self) -> TripRequest:
        data = self.validated_data
        return TripRequest(
            origin=(data["origin"]["lat"], data["origin"]["lon"]),
            destination=(data["destination"]["lat"], data["destination"]["lon"]),
            departure_local=data["departure_local"],
            load_weight_lb=data["load_weight_lb"],
            interval_miles=int(data["interval_miles"]),
        )


class HeatmapRequestSerializer(serializers.Serializer[dict[str, Any]]):
    routes = serializers.ListField(
        child=serializers.ListField(
            child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
            min_length=2,
            max_length=MAX_HEATMAP_POINTS,
        ),
        min_length=1,
        max_length=MAX_HEATMAP_ROUTES,
    )
    departure_utc = serializers.DateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)

    def validate_routes(self, routes: list[list[list[float]]]) -> list[list[tuple[float, float]]]:
        """Routes arrive as GeoJSON-ordered [lon, lat] pairs, as the plan response sends them."""
        converted = []
        for route in routes:
            points = []
            for lon, lat in route:
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise serializers.ValidationError("Route coordinates are out of range.")
                points.append((lat, lon))
            converted.append(points)
        return converted


class GeocodeQuerySerializer(serializers.Serializer[dict[str, Any]]):
    q = serializers.CharField(min_length=3, max_length=100, trim_whitespace=True)
