from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


@dataclass(frozen=True)
class Weather:
    wind_mph: Decimal | None
    gust_mph: Decimal | None
    rain_in_hr: Decimal | None
    snow_in_hr: Decimal | None


@dataclass(frozen=True)
class Assessment:
    """`level` is None when any scored input is missing; unknown weather is never treated as Low."""

    level: Level | None
    drivers: tuple[str, ...]
    load_escalated: bool


# Bands are half-open [low, high). The No Travel edges for rain and snow are written as
# strict ">" in the assignment, so 1.00 in/hr rain and 3.0 in/hr snow stay Severe.
def classify_wind(mph: Decimal, load_lb: int) -> tuple[Level, bool]:
    if mph >= 55:
        return Level.NO_TRAVEL, False
    if mph >= 45:
        return (Level.NO_TRAVEL, True) if load_lb > 30_000 else (Level.SEVERE, False)
    if mph >= 35:
        return (Level.SEVERE, True) if load_lb > 40_000 else (Level.HIGH, False)
    if mph >= 25:
        return Level.MODERATE, False
    return Level.LOW, False


def classify_rain(in_hr: Decimal) -> Level:
    if in_hr > Decimal("1.00"):
        return Level.NO_TRAVEL
    if in_hr >= Decimal("0.50"):
        return Level.SEVERE
    if in_hr >= Decimal("0.25"):
        return Level.HIGH
    if in_hr >= Decimal("0.10"):
        return Level.MODERATE
    return Level.LOW


def classify_snow(in_hr: Decimal) -> Level:
    if in_hr > Decimal("3.0"):
        return Level.NO_TRAVEL
    if in_hr >= Decimal("2.0"):
        return Level.SEVERE
    if in_hr >= Decimal("1.0"):
        return Level.HIGH
    if in_hr >= Decimal("0.5"):
        return Level.MODERATE
    return Level.LOW


def assess(weather: Weather, load_lb: int) -> Assessment:
    if weather.wind_mph is None or weather.rain_in_hr is None or weather.snow_in_hr is None:
        return Assessment(level=None, drivers=(), load_escalated=False)

    wind, escalated = classify_wind(weather.wind_mph, load_lb)
    factors = {
        "wind": wind,
        "rain": classify_rain(weather.rain_in_hr),
        "snow": classify_snow(weather.snow_in_hr),
    }
    level = max(factors.values())
    drivers = tuple(name for name, value in factors.items() if value == level and level > Level.LOW)
    return Assessment(level=level, drivers=drivers, load_escalated=escalated and "wind" in drivers)
