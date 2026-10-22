import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses
from django.core.cache import cache

from routing.errors import (
    DepartureRejected,
    NoRouteFound,
    UpstreamAuth,
    UpstreamBadResponse,
    UpstreamUnavailable,
)
from routing.providers import http, open_meteo, tomtom
from routing.risk import Level, assess
from routing.tests.builders import east_west, open_meteo_location, tomtom_body, tomtom_route

ROUTE_URL = re.compile(r"https://api\.tomtom\.com/routing/1/calculateRoute/.*")
KEY = "test-key-not-real"


@pytest.fixture(autouse=True)
def no_backoff_and_empty_cache(monkeypatch):
    monkeypatch.setattr(http, "RETRY_BACKOFF_SECONDS", 0)
    cache.clear()


def query(call):
    return parse_qs(urlparse(str(call.request.url)).query)


def add_route_response(body, status=200):
    responses.add(
        responses.GET,
        ROUTE_URL,
        json=body,
        status=status,
    )


class TestCalculateRoutes:
    @responses.activate
    def test_parses_routes_in_tomtom_order_with_progress_and_countries(self):
        first, second = east_west(10), east_west(12, lat=0.1)
        add_route_response(tomtom_body(tomtom_route(first), tomtom_route(second)))

        routes = tomtom.calculate_routes((0, 0), (0, 0.14), "2026-10-22T09:00:00-05:00")

        assert [len(r.points) for r in routes] == [11, 13]
        assert routes[0].progress[0] == (0, 0)
        assert routes[0].progress[-1] == (10, 600)
        assert routes[0].countries == frozenset({"USA"})

    @responses.activate
    def test_requests_truck_routing_with_border_avoidance_and_progress(self):
        add_route_response(tomtom_body(tomtom_route(east_west(10))))

        tomtom.calculate_routes((41.88, -87.63), (39.74, -104.99), "2026-10-22T09:00:00-05:00")

        sent = query(responses.calls[0])
        assert urlparse(str(responses.calls[0].request.url)).path.endswith(
            "/41.88,-87.63:39.74,-104.99/json"
        )
        assert sent["travelMode"] == ["truck"]
        assert sent["vehicleCommercial"] == ["true"]
        assert sent["avoid"] == ["borderCrossings"]
        assert sent["sectionType"] == ["country"]
        assert sent["report"] == ["effectiveSettings"]
        assert sent["extendedRouteRepresentation"] == ["distance", "travelTime"]
        assert sent["maxAlternatives"] == ["5"]
        assert sent["departAt"] == ["2026-10-22T09:00:00-05:00"]
        assert "vehicleWeight" not in sent

    @responses.activate
    def test_border_restriction_missing_from_effective_settings_fails_closed(self):
        add_route_response(tomtom_body(tomtom_route(east_west(10)), avoid=None))

        with pytest.raises(UpstreamBadResponse, match="did not apply the border restriction"):
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")

    @responses.activate
    def test_route_without_country_sections_is_rejected(self):
        route = tomtom_route(east_west(10), countries=())
        add_route_response(tomtom_body(route))

        with pytest.raises(UpstreamBadResponse):
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")

    @responses.activate
    def test_rejected_departure_time_is_reported_as_such(self):
        add_route_response(
            {"detailedError": {"code": "INVALID_REQUEST", "message": "departAt is in the past"}},
            status=400,
        )

        with pytest.raises(DepartureRejected):
            tomtom.calculate_routes((0, 0), (0, 0.14), "2026-10-22T08:00:00-05:00")

    @responses.activate
    def test_other_bad_request_means_no_route(self):
        add_route_response(
            {"detailedError": {"code": "NO_ROUTE_FOUND", "message": "Unable to find a route"}},
            status=400,
        )

        with pytest.raises(NoRouteFound):
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")

    @responses.activate
    def test_refused_key_becomes_auth_error_without_leaking_the_key(self, caplog):
        add_route_response({"error": "forbidden"}, status=403)

        with caplog.at_level(logging.INFO), pytest.raises(UpstreamAuth) as raised:
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")

        assert KEY not in raised.value.message
        assert KEY not in caplog.text

    @responses.activate
    def test_connection_failure_is_retried_once_then_unavailable_without_the_key(self, caplog):
        error = requests.ConnectionError(f"Max retries exceeded with url: /x?key={KEY}&a=1")
        responses.add(responses.GET, ROUTE_URL, body=error)
        responses.add(responses.GET, ROUTE_URL, body=error)

        with caplog.at_level(logging.INFO), pytest.raises(UpstreamUnavailable) as raised:
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")

        assert len(responses.calls) == 2
        assert KEY not in raised.value.message
        assert KEY not in caplog.text
        assert "key=[REDACTED]" in caplog.text

    @responses.activate
    def test_transient_503_is_retried_and_then_succeeds(self):
        add_route_response({}, status=503)
        add_route_response(tomtom_body(tomtom_route(east_west(10))))

        routes = tomtom.calculate_routes((0, 0), (0, 0.14), "now")

        assert len(routes) == 1
        assert len(responses.calls) == 2

    def test_missing_key_is_a_configuration_error(self, settings):
        settings.TOMTOM_API_KEY = ""

        with pytest.raises(UpstreamAuth, match="not configured"):
            tomtom.calculate_routes((0, 0), (0, 0.14), "now")


class TestSearchPlaces:
    @responses.activate
    def test_returns_labelled_us_places(self):
        responses.add(
            responses.GET,
            "https://api.tomtom.com/search/2/search/denver.json",
            json={
                "results": [
                    {
                        "address": {"freeformAddress": "Denver, CO"},
                        "position": {"lat": 39.74, "lon": -104.99},
                    },
                    {
                        "poi": {"name": "Union Station"},
                        "address": {"freeformAddress": "1701 Wynkoop St, Denver, CO 80202"},
                        "position": {"lat": 39.75, "lon": -105.0},
                    },
                    {"address": {"freeformAddress": "No position"}},
                ]
            },
        )

        places = tomtom.search_places("denver")

        assert [(p.label, p.lat, p.lon) for p in places] == [
            ("Denver, CO", 39.74, -104.99),
            ("Union Station, 1701 Wynkoop St, Denver, CO 80202", 39.75, -105.0),
        ]
        assert query(responses.calls[0])["countrySet"] == ["US"]


NOW = datetime(2026, 10, 22, 14, 20, tzinfo=UTC)
HOUR = 3600
FIRST = int(datetime(2026, 10, 22, 14, 0, tzinfo=UTC).timestamp())


def add_weather(body):
    responses.add(responses.GET, open_meteo.FORECAST_URL, json=body)


class TestForecasts:
    @responses.activate
    def test_requests_the_window_from_the_current_hour_through_the_hour_after_until(self):
        times = [FIRST - HOUR + i * HOUR for i in range(7)]
        add_weather(open_meteo_location(times))

        open_meteo.forecasts(
            [(41.0, -87.0)], now=NOW, until=datetime(2026, 10, 22, 18, 5, tzinfo=UTC)
        )

        sent = query(responses.calls[0])
        assert sent["past_hours"] == ["1"]
        assert sent["forecast_hours"] == ["6"]
        assert sent["timezone"] == ["auto"]
        assert sent["precipitation_unit"] == ["inch"]
        assert sent["wind_speed_unit"] == ["mph"]

    @responses.activate
    def test_rain_and_showers_are_summed_exactly(self):
        # As floats, 0.01 + 0.09 is 0.09999..., which would read as Low.
        responses.add(
            responses.GET,
            open_meteo.FORECAST_URL,
            body=json.dumps(open_meteo_location([FIRST], rain=0.01, showers=0.09)),
            content_type="application/json",
        )

        [forecast] = open_meteo.forecasts([(41.0, -87.0)], now=NOW, until=NOW)

        assert assess(forecast.at(FIRST), load_lb=0).level == Level.MODERATE

    @responses.activate
    def test_null_value_makes_that_hour_unknown(self):
        add_weather(open_meteo_location([FIRST], showers=[None]))

        [forecast] = open_meteo.forecasts([(41.0, -87.0)], now=NOW, until=NOW)

        assert assess(forecast.at(FIRST), load_lb=0).level is None

    @responses.activate
    def test_hour_outside_the_series_is_unknown(self):
        add_weather(open_meteo_location([FIRST]))

        [forecast] = open_meteo.forecasts([(41.0, -87.0)], now=NOW, until=NOW)

        assert forecast.at(FIRST + HOUR).wind_mph is None

    @responses.activate
    def test_batches_of_one_hundred_and_results_keep_input_order(self):
        points = [(30 + i * 0.01, -90.0) for i in range(150)]
        responses.add(
            responses.GET,
            open_meteo.FORECAST_URL,
            json=[open_meteo_location([FIRST], tz=f"zone-{i}") for i in range(100)],
        )
        responses.add(
            responses.GET,
            open_meteo.FORECAST_URL,
            json=[open_meteo_location([FIRST], tz=f"zone-{i}") for i in range(100, 150)],
        )

        result = open_meteo.forecasts(points, now=NOW, until=NOW)

        assert len(responses.calls) == 2
        assert [f.timezone for f in result] == [f"zone-{i}" for i in range(150)]

    @responses.activate
    def test_single_location_object_and_cache_hit_on_second_call(self):
        add_weather(open_meteo_location([FIRST - HOUR, FIRST, FIRST + HOUR], tz="America/Denver"))

        first = open_meteo.forecasts([(39.74, -104.99)], now=NOW, until=NOW)
        second = open_meteo.forecasts([(39.74, -104.99)], now=NOW, until=NOW)

        assert first[0].timezone == second[0].timezone == "America/Denver"
        assert len(responses.calls) == 1

    @responses.activate
    def test_cached_series_that_ends_too_early_is_fetched_again(self):
        add_weather(open_meteo_location([FIRST - HOUR, FIRST, FIRST + HOUR]))
        add_weather(open_meteo_location([FIRST - HOUR + i * HOUR for i in range(5)]))

        open_meteo.forecasts([(39.74, -104.99)], now=NOW, until=NOW)
        later = datetime(2026, 10, 22, 16, 30, tzinfo=UTC)
        [forecast] = open_meteo.forecasts([(39.74, -104.99)], now=NOW, until=later)

        assert len(responses.calls) == 2
        assert forecast.times[-1] == FIRST + 3 * HOUR

    @responses.activate
    def test_wrong_number_of_locations_is_a_bad_response(self):
        add_weather([open_meteo_location([FIRST])])

        with pytest.raises(UpstreamBadResponse):
            open_meteo.forecasts([(1.0, 1.0), (2.0, 2.0)], now=NOW, until=NOW)

    @responses.activate
    def test_rate_limit_is_unavailable(self):
        responses.add(responses.GET, open_meteo.FORECAST_URL, status=429)
        responses.add(responses.GET, open_meteo.FORECAST_URL, status=429)

        with pytest.raises(UpstreamUnavailable, match="rate limit"):
            open_meteo.forecasts([(1.0, 1.0)], now=NOW, until=NOW)
