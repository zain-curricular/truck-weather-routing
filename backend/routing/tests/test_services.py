import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from django.core.cache import cache

from routing.errors import DepartureRejected, InvalidTrip, NoRouteFound, UpstreamUnavailable
from routing.providers import http, open_meteo
from routing.services import TripRequest, build_heatmap, plan_trip, resolve_departure
from routing.tests.builders import east_west, fake_open_meteo, tomtom_body, tomtom_route

NOW = datetime(2026, 10, 22, 14, 20, tzinfo=UTC)
FIRST_STAMP = int(datetime(2026, 10, 22, 14, 0, tzinfo=UTC).timestamp())
ROUTE_URL = re.compile(r"https://api\.tomtom\.com/routing/1/calculateRoute/.*")

SHORT_SNOWY = east_west(100, lat=0.0)
LONG_CLEAR = east_west(130, lat=1.0)


def snow_on_southern_route(lat, lon, stamp):
    return {"snow": 2.5} if lat < 0.5 and lon > 0.3 else {}


def trip(departure="2026-10-22T10:00", load=20_000, interval=25):
    return TripRequest(
        origin=(0.0, 0.0),
        destination=(0.0, 1.5),
        departure_local=datetime.strptime(departure, "%Y-%m-%dT%H:%M"),
        load_weight_lb=load,
        interval_miles=interval,
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(http, "RETRY_BACKOFF_SECONDS", 0)
    cache.clear()


def weather(fn=lambda lat, lon, stamp: {}):
    responses.add_callback(
        responses.GET,
        open_meteo.FORECAST_URL,
        callback=fake_open_meteo(fn, first_stamp=FIRST_STAMP),
    )


def routes_respond(*routes, status=200, body=None):
    responses.add(responses.GET, ROUTE_URL, json=body or tomtom_body(*routes), status=status)


def tomtom_calls():
    return [c for c in responses.calls if "calculateRoute" in str(c.request.url)]


class TestResolveDeparture:
    def test_no_departure_means_now_in_whole_minutes_at_the_origin(self):
        now = datetime(2026, 10, 22, 17, 7, 42, 500, tzinfo=UTC)

        result = resolve_departure(None, "America/Chicago", now)

        assert result.utc == datetime(2026, 10, 22, 17, 7, tzinfo=UTC)
        assert result.local.isoformat() == "2026-10-22T12:07:00-05:00"

    def test_repeated_fall_back_hour_resolves_to_first_occurrence(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

        result = resolve_departure(datetime(2026, 11, 1, 1, 30), "America/Chicago", now)

        assert result.utc == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
        assert result.local.strftime("%Z %z") == "CDT -0500"

    def test_skipped_spring_forward_hour_is_rejected(self):
        now = datetime(2027, 3, 13, 12, 0, tzinfo=UTC)

        with pytest.raises(InvalidTrip, match="does not exist in America/Chicago"):
            resolve_departure(datetime(2027, 3, 14, 2, 30), "America/Chicago", now)

    @pytest.mark.parametrize(
        ("local", "now", "offset"),
        [
            (datetime(2026, 11, 1, 0, 59), datetime(2026, 10, 31, 12, tzinfo=UTC), "-0500"),
            (datetime(2026, 11, 1, 2, 0), datetime(2026, 10, 31, 12, tzinfo=UTC), "-0600"),
            (datetime(2027, 3, 14, 1, 59), datetime(2027, 3, 13, 12, tzinfo=UTC), "-0600"),
            (datetime(2027, 3, 14, 3, 0), datetime(2027, 3, 13, 12, tzinfo=UTC), "-0500"),
        ],
    )
    def test_times_either_side_of_each_transition_get_the_right_offset(self, local, now, offset):
        assert resolve_departure(local, "America/Chicago", now).local.strftime("%z") == offset

    def test_departure_window_is_fifteen_minutes_back_to_seven_days_ahead(self):
        ok_past = (NOW - timedelta(minutes=14)).astimezone(UTC).replace(tzinfo=None)
        too_past = (NOW - timedelta(minutes=16)).replace(tzinfo=None)
        too_far = (NOW + timedelta(days=7, minutes=1)).replace(tzinfo=None)

        assert resolve_departure(ok_past, "UTC", NOW).utc == NOW - timedelta(minutes=14)
        with pytest.raises(InvalidTrip, match="15 minutes in the past"):
            resolve_departure(too_past, "UTC", NOW)
        with pytest.raises(InvalidTrip, match="next 7 days"):
            resolve_departure(too_far, "UTC", NOW)


class TestPlanTrip:
    @responses.activate
    def test_longer_clear_route_beats_shorter_route_with_severe_snow(self):
        weather(snow_on_southern_route)
        routes_respond(tomtom_route(SHORT_SNOWY), tomtom_route(LONG_CLEAR))

        result = plan_trip(trip(), NOW)

        first, second = result["routes"]
        assert first["summary"]["distance_mi"] == 130.0
        assert (first["recommended"], first["summary"]["severe_mi"]) == (True, 0)
        assert (second["recommended"], second["summary"]["severe_mi"]) == (False, 87.5)
        assert result["recommendation"] == {
            "route_id": 0,
            "reason": "Recommended because it has fewer Severe miles.",
        }

    @responses.activate
    def test_checkpoints_use_interval_and_eta_anchored_to_departure(self):
        weather()
        routes_respond(tomtom_route(SHORT_SNOWY))

        result = plan_trip(trip(), NOW)

        [route] = result["routes"]
        assert result["departure"]["utc"] == "2026-10-22T15:00+00:00"
        assert result["departure"]["utc_offset"] == "-0500"
        assert [cp["mile"] for cp in route["checkpoints"]] == [0, 25, 50, 75, 100]
        assert [cp["eta_utc"][11:16] for cp in route["checkpoints"]] == [
            "15:00",
            "15:25",
            "15:50",
            "16:15",
            "16:40",
        ]
        assert [cp["forecast_hour_utc"][11:16] for cp in route["checkpoints"]] == [
            "15:00",
            "16:00",
            "16:00",
            "17:00",
            "17:00",
        ]
        assert sum(cp["share_mi"] for cp in route["checkpoints"]) == 100

    @responses.activate
    def test_changing_the_interval_reuses_the_cached_routes(self):
        weather()
        routes_respond(tomtom_route(SHORT_SNOWY))

        plan_trip(trip(interval=25), NOW)
        ten = plan_trip(trip(interval=10), NOW)

        assert len(tomtom_calls()) == 1
        assert len(ten["routes"][0]["checkpoints"]) == 11

    @responses.activate
    def test_no_route_recommended_when_every_route_has_no_travel(self):
        weather(lambda lat, lon, stamp: {"wind": 60.0})
        routes_respond(tomtom_route(SHORT_SNOWY), tomtom_route(LONG_CLEAR))

        result = plan_trip(trip(), NOW)

        assert result["recommendation"]["route_id"] is None
        assert "No Travel" in result["recommendation"]["reason"]
        assert not any(r["recommended"] or r["drivable"] for r in result["routes"])

    @responses.activate
    def test_load_rule_changes_the_outcome(self):
        weather(lambda lat, lon, stamp: {"wind": 48.0} if lat < 0.5 else {})
        routes_respond(tomtom_route(SHORT_SNOWY), tomtom_route(LONG_CLEAR))

        light = plan_trip(trip(load=30_000), NOW)
        heavy = plan_trip(trip(load=30_001), NOW)

        assert light["routes"][1]["checkpoints"][1]["level"] == "severe"
        assert heavy["routes"][1]["checkpoints"][1]["level"] == "no_travel"
        assert heavy["routes"][1]["checkpoints"][1]["load_escalated"] is True

    @responses.activate
    def test_routes_leaving_the_us_are_removed(self):
        weather()
        routes_respond(
            tomtom_route(SHORT_SNOWY, countries=("USA", "CAN")), tomtom_route(LONG_CLEAR)
        )

        result = plan_trip(trip(), NOW)

        assert [r["summary"]["distance_mi"] for r in result["routes"]] == [130.0]

    @responses.activate
    def test_no_domestic_route_is_an_error_not_a_crossing_route(self):
        weather()
        routes_respond(tomtom_route(SHORT_SNOWY, countries=("USA", "CAN")))

        with pytest.raises(NoRouteFound, match="stays within the United States"):
            plan_trip(trip(), NOW)

    @responses.activate
    def test_duplicates_are_dropped_and_shortfall_is_reported(self):
        weather()
        routes_respond(
            tomtom_route(SHORT_SNOWY),
            tomtom_route(east_west(100, lat=0.001)),
            tomtom_route(LONG_CLEAR),
        )

        result = plan_trip(trip(), NOW)

        assert len(result["routes"]) == 2
        assert "Only 2 distinct routes" in result["warnings"][0]

    @responses.activate
    def test_better_fourth_distinct_route_replaces_the_third(self):
        weather(lambda lat, lon, stamp: {"snow": 2.5} if lat < 2.5 else {})
        candidates = [east_west(100, lat=lat) for lat in (0.0, 1.0, 2.0, 3.0)]
        routes_respond(*(tomtom_route(c) for c in candidates))

        result = plan_trip(trip(), NOW)

        assert len(result["routes"]) == 3
        assert result["routes"][0]["checkpoints"][0]["lat"] == 3.0
        assert result["routes"][0]["recommended"] is True

    @responses.activate
    def test_rejected_past_departure_is_retried_with_now_and_disclosed(self):
        weather()
        routes_respond(
            body={"detailedError": {"code": "INVALID", "message": "departAt in the past"}},
            status=400,
        )
        routes_respond(tomtom_route(SHORT_SNOWY))

        result = plan_trip(trip(departure="2026-10-22T09:10"), NOW)

        sent = [parse_qs(urlparse(str(c.request.url)).query)["departAt"][0] for c in tomtom_calls()]
        assert sent == ["2026-10-22T09:10:00-05:00", "now"]
        assert result["departure"]["substituted_now"] is True
        assert "traffic was modelled from the current time" in result["warnings"][-1]
        assert result["routes"][0]["checkpoints"][0]["eta_utc"] == "2026-10-22T14:10+00:00"

    @responses.activate
    def test_accepted_past_departure_is_sent_as_entered(self):
        weather()
        routes_respond(tomtom_route(SHORT_SNOWY))

        result = plan_trip(trip(departure="2026-10-22T09:10"), NOW)

        assert len(tomtom_calls()) == 1
        assert result["departure"]["substituted_now"] is False

    @responses.activate
    def test_future_departure_rejection_is_not_retried(self):
        weather()
        routes_respond(
            body={"detailedError": {"code": "INVALID", "message": "bad departAt"}}, status=400
        )

        with pytest.raises(DepartureRejected):
            plan_trip(trip(), NOW)
        assert len(tomtom_calls()) == 1

    @responses.activate
    def test_weather_outage_after_routing_shows_routes_without_a_recommendation(self, monkeypatch):
        weather()
        routes_respond(tomtom_route(SHORT_SNOWY))
        plan_origin_lookup = open_meteo.forecasts

        def fail_after_origin(points, **kwargs):
            if len(points) == 1:
                return plan_origin_lookup(points, **kwargs)
            raise UpstreamUnavailable("Open-Meteo rate limit reached.")

        monkeypatch.setattr(open_meteo, "forecasts", fail_after_origin)

        result = plan_trip(trip(), NOW)

        assert result["recommendation"]["route_id"] is None
        assert {cp["level"] for cp in result["routes"][0]["checkpoints"]} == {"unknown"}
        assert "Open-Meteo rate limit reached." in result["warnings"][0]

    @responses.activate
    def test_segments_cover_the_route_coloured_by_checkpoint(self):
        weather(snow_on_southern_route)
        routes_respond(tomtom_route(SHORT_SNOWY))

        [route] = plan_trip(trip(), NOW)["routes"]

        assert [s["level"] for s in route["segments"]] == [
            "low",
            "severe",
            "severe",
            "severe",
            "severe",
        ]
        assert route["segments"][0]["coordinates"][0] == route["geometry"][0]
        assert route["segments"][-1]["coordinates"][-1] == route["geometry"][-1]


class TestBuildHeatmap:
    @responses.activate
    def test_forty_nine_frames_starting_at_the_departure_hour(self):
        weather()

        result = build_heatmap([LONG_CLEAR], NOW + timedelta(minutes=40), load_lb=0, now=NOW)

        assert len(result["frames"]) == 49
        assert result["frames"][0]["time_utc"] == "2026-10-22T15:00+00:00"
        assert result["frames"][48]["time_utc"] == "2026-10-24T15:00+00:00"
        assert all(len(f["levels"]) == len(result["cells"]) for f in result["frames"])

    @responses.activate
    def test_load_rule_applies_to_heatmap_cells(self):
        weather(lambda lat, lon, stamp: {"wind": 36.0})

        light = build_heatmap([LONG_CLEAR], NOW, load_lb=40_000, now=NOW)
        heavy = build_heatmap([LONG_CLEAR], NOW, load_lb=40_001, now=NOW)

        assert set(light["frames"][0]["levels"]) == {2}
        assert set(heavy["frames"][0]["levels"]) == {3}

    def test_departure_outside_the_window_is_rejected(self):
        with pytest.raises(InvalidTrip):
            build_heatmap([LONG_CLEAR], NOW + timedelta(days=8), load_lb=0, now=NOW)
