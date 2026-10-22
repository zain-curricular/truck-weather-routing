import re
from datetime import UTC, datetime

import pytest
import responses
from django.core.cache import cache
from django.test import Client

from routing.providers import http, open_meteo
from routing.tests.builders import east_west, fake_open_meteo, tomtom_body, tomtom_route

NOW = datetime(2026, 10, 22, 14, 20, tzinfo=UTC)
FIRST_STAMP = int(datetime(2026, 10, 22, 14, 0, tzinfo=UTC).timestamp())
ROUTE_URL = re.compile(r"https://api\.tomtom\.com/routing/1/calculateRoute/.*")
SEARCH_URL = re.compile(r"https://api\.tomtom\.com/search/2/search/.*")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(http, "RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr("routing.views.timezone.now", lambda: NOW)
    cache.clear()


def plan_body(**overrides):
    body = {
        "origin": {"lat": 0.0, "lon": 0.0, "label": "A"},
        "destination": {"lat": 0.0, "lon": 1.5, "label": "B"},
        "departure_local": "2026-10-22T10:00",
        "load_weight_lb": 20000,
        "interval_miles": 25,
    }
    return body | overrides


def post(path, body):
    return Client().post(path, body, content_type="application/json")


class TestPlanEndpoint:
    @pytest.mark.parametrize(
        ("departure_local", "resolved"),
        [("2026-10-22T10:00", "2026-10-22T10:00-05:00"), (None, "2026-10-22T09:20-05:00")],
    )
    @responses.activate
    def test_plans_a_trip_end_to_end(self, departure_local, resolved):
        responses.add_callback(
            responses.GET,
            open_meteo.FORECAST_URL,
            callback=fake_open_meteo(lambda *a: {}, first_stamp=FIRST_STAMP),
        )
        responses.add(
            responses.GET, ROUTE_URL, json=tomtom_body(tomtom_route(east_west(100, lat=0.0)))
        )

        response = post("/api/plan", plan_body(departure_local=departure_local))

        assert response.status_code == 200
        data = response.json()
        assert data["departure"]["local"] == resolved
        assert data["recommendation"]["route_id"] == 0
        assert data["routes"][0]["checkpoints"][0]["timezone"] == "America/Chicago"

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"interval_miles": 30}, "interval_miles"),
            ({"load_weight_lb": 80001}, "load_weight_lb"),
            ({"load_weight_lb": -1}, "load_weight_lb"),
            ({"departure_local": "22/10/2026 10:00"}, "departure_local"),
            ({"origin": {"lat": 91, "lon": 0}}, "origin"),
        ],
    )
    def test_invalid_fields_are_rejected_by_name(self, overrides, field):
        response = post("/api/plan", plan_body(**overrides))

        assert response.status_code == 400
        assert field in response.json()

    def test_missing_fields_are_rejected(self):
        response = post("/api/plan", {})

        assert response.status_code == 400
        errors = response.json()
        assert set(errors) >= {"origin", "destination"}
        assert "departure_local" not in errors

    def test_same_origin_and_destination_is_rejected(self):
        response = post("/api/plan", plan_body(destination={"lat": 0.0, "lon": 0.0}))

        assert response.status_code == 400
        assert response.json()["non_field_errors"] == [
            "Origin and destination must be different places."
        ]

    @responses.activate
    def test_service_errors_return_their_message_and_status(self):
        responses.add_callback(
            responses.GET,
            open_meteo.FORECAST_URL,
            callback=fake_open_meteo(lambda *a: {}, first_stamp=FIRST_STAMP),
        )

        response = post("/api/plan", plan_body(departure_local="2026-10-30T10:00"))

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Departure must be within the next 7 days, the reliable forecast range."
        }

    @responses.activate
    def test_upstream_outage_is_503_with_readable_message(self):
        responses.add(responses.GET, open_meteo.FORECAST_URL, status=503)
        responses.add(responses.GET, open_meteo.FORECAST_URL, status=503)

        response = post("/api/plan", plan_body())

        assert response.status_code == 503
        assert response.json()["detail"] == "Open-Meteo is having problems (HTTP 503)."


class TestGeocodeEndpoint:
    def test_query_shorter_than_three_characters_is_rejected(self):
        assert Client().get("/api/geocode", {"q": "ab"}).status_code == 400

    @responses.activate
    def test_results_are_cached_by_normalised_query(self):
        responses.add(
            responses.GET,
            SEARCH_URL,
            json={
                "results": [
                    {"address": {"freeformAddress": "Denver, CO"}, "position": {"lat": 1, "lon": 2}}
                ]
            },
        )

        first = Client().get("/api/geocode", {"q": "Denver  CO"})
        second = Client().get("/api/geocode", {"q": "denver co"})

        assert (
            first.json()
            == second.json()
            == {"results": [{"label": "Denver, CO", "lat": 1.0, "lon": 2.0}]}
        )
        assert len(responses.calls) == 1


class TestHeatmapEndpoint:
    def test_more_than_three_routes_is_rejected(self):
        route = [[0.0, 0.0], [1.0, 0.0]]
        body = {"routes": [route] * 4, "departure_utc": NOW.isoformat(), "load_weight_lb": 0}

        assert post("/api/heatmap", body).status_code == 400

    def test_oversized_route_is_rejected(self):
        route = [[i / 1000, 0.0] for i in range(2001)]
        body = {"routes": [route], "departure_utc": NOW.isoformat(), "load_weight_lb": 0}

        assert post("/api/heatmap", body).status_code == 400

    def test_out_of_range_coordinates_are_rejected(self):
        body = {
            "routes": [[[0.0, 0.0], [200.0, 0.0]]],
            "departure_utc": NOW.isoformat(),
            "load_weight_lb": 0,
        }

        response = post("/api/heatmap", body)

        assert response.status_code == 400
        assert response.json()["routes"] == ["Route coordinates are out of range."]

    @responses.activate
    def test_returns_cells_as_lon_lat_and_frames(self):
        responses.add_callback(
            responses.GET,
            open_meteo.FORECAST_URL,
            callback=fake_open_meteo(lambda *a: {}, first_stamp=FIRST_STAMP),
        )
        body = {
            "routes": [[[0.0, 40.0], [1.0, 40.0]]],
            "departure_utc": NOW.isoformat(),
            "load_weight_lb": 0,
        }

        data = post("/api/heatmap", body).json()

        assert len(data["frames"]) == 49
        assert all(39 < lat < 41 and -1 < lon < 2 for lon, lat in data["cells"])


def test_plan_requests_over_the_rate_limit_are_refused(monkeypatch):
    monkeypatch.setattr("routing.views.PlanThrottle.rate", "2/min", raising=False)

    statuses = [post("/api/plan", {}).status_code for _ in range(3)]

    assert statuses == [400, 400, 429]
