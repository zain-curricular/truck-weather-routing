from decimal import Decimal

import pytest

from routing.risk import Level, Weather, assess, classify_rain, classify_snow, classify_wind

L, M, H, S, NT = Level.LOW, Level.MODERATE, Level.HIGH, Level.SEVERE, Level.NO_TRAVEL


@pytest.mark.parametrize(
    ("mph", "expected"),
    [
        ("24.99", L),
        ("25", M),
        ("34.99", M),
        ("35", H),
        ("44.99", H),
        ("45", S),
        ("54.99", S),
        ("55", NT),
    ],
)
def test_wind_band_edges_with_no_load(mph, expected):
    assert classify_wind(Decimal(mph), 0) == (expected, False)


@pytest.mark.parametrize(
    ("in_hr", "expected"),
    [
        ("0.099", L),
        ("0.10", M),
        ("0.249", M),
        ("0.25", H),
        ("0.499", H),
        ("0.50", S),
        ("1.00", S),
        ("1.001", NT),
    ],
)
def test_rain_band_edges(in_hr, expected):
    assert classify_rain(Decimal(in_hr)) == expected


@pytest.mark.parametrize(
    ("in_hr", "expected"),
    [
        ("0.49", L),
        ("0.5", M),
        ("0.99", M),
        ("1.0", H),
        ("1.99", H),
        ("2.0", S),
        ("3.0", S),
        ("3.01", NT),
    ],
)
def test_snow_band_edges(in_hr, expected):
    assert classify_snow(Decimal(in_hr)) == expected


@pytest.mark.parametrize(
    ("mph", "load_lb", "expected"),
    [
        ("45", 30_000, (S, False)),
        ("45", 30_001, (NT, True)),
        ("54.99", 30_001, (NT, True)),
        ("35", 40_000, (H, False)),
        ("35", 40_001, (S, True)),
        ("44.99", 40_001, (S, True)),
        ("34.99", 80_000, (M, False)),
        ("55", 0, (NT, False)),
    ],
)
def test_load_rules_escalate_only_above_their_weight(mph, load_lb, expected):
    assert classify_wind(Decimal(mph), load_lb) == expected


def weather(wind="0", rain="0", snow="0"):
    return Weather(
        wind_mph=None if wind is None else Decimal(wind),
        gust_mph=Decimal("0"),
        rain_in_hr=None if rain is None else Decimal(rain),
        snow_in_hr=None if snow is None else Decimal(snow),
    )


def test_checkpoint_takes_the_worst_factor():
    result = assess(weather(wind="26", rain="0.30", snow="0.6"), load_lb=0)

    assert (result.level, result.drivers, result.load_escalated) == (H, ("rain",), False)


def test_heavy_load_with_calm_wind_stays_driven_by_snow():
    result = assess(weather(wind="10", snow="2.5"), load_lb=80_000)

    assert (result.level, result.drivers, result.load_escalated) == (S, ("snow",), False)


def test_load_escalation_is_reported_when_it_sets_the_level():
    result = assess(weather(wind="36"), load_lb=45_000)

    assert (result.level, result.drivers, result.load_escalated) == (S, ("wind",), True)


def test_escalation_not_reported_when_another_factor_is_worse():
    result = assess(weather(wind="36", rain="1.5"), load_lb=45_000)

    assert (result.level, result.drivers, result.load_escalated) == (NT, ("rain",), False)


def test_ties_list_every_driver():
    result = assess(weather(wind="40", rain="0.30"), load_lb=0)

    assert result.drivers == ("wind", "rain")


def test_calm_weather_is_low_with_no_drivers():
    result = assess(weather(), load_lb=0)

    assert (result.level, result.drivers) == (L, ())


@pytest.mark.parametrize("missing", ["wind", "rain", "snow"])
def test_missing_scored_input_is_unknown_not_low(missing):
    result = assess(weather(**{missing: None}), load_lb=0)

    assert result.level is None


def test_missing_gust_does_not_make_weather_unknown():
    result = assess(
        Weather(Decimal("10"), None, Decimal("0"), Decimal("0")),
        load_lb=0,
    )

    assert result.level == L
