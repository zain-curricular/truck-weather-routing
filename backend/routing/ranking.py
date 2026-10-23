from collections.abc import Sequence
from dataclasses import dataclass

from routing.risk import Level


@dataclass(frozen=True)
class RouteMetrics:
    no_travel_mi: float
    severe_mi: float
    high_mi: float
    avg_risk: float | None
    duration_s: int
    complete: bool

    @property
    def drivable(self) -> bool:
        return self.complete and self.no_travel_mi == 0

    def sort_key(self) -> tuple[bool, float, float, float, float, int]:
        # Unknown weather can't be compared on miles, so it ranks last. Values are compared at
        # display precision so float noise never decides a tie.
        return (
            not self.complete,
            round(self.no_travel_mi, 2),
            round(self.severe_mi, 2),
            round(self.high_mi, 2),
            round(self.avg_risk, 2) if self.avg_risk is not None else float("inf"),
            self.duration_s,
        )


def route_metrics(
    levels: Sequence[Level | None], shares_mi: Sequence[float], duration_s: int
) -> RouteMetrics:
    def miles_at(level: Level) -> float:
        return sum(share for lvl, share in zip(levels, shares_mi, strict=True) if lvl == level)

    complete = all(level is not None for level in levels)
    total = sum(shares_mi)
    weighted = sum(
        int(lvl) * share for lvl, share in zip(levels, shares_mi, strict=True) if lvl is not None
    )
    avg = weighted / total if complete and total > 0 else None
    return RouteMetrics(
        no_travel_mi=miles_at(Level.NO_TRAVEL),
        severe_mi=miles_at(Level.SEVERE),
        high_mi=miles_at(Level.HIGH),
        avg_risk=avg,
        duration_s=duration_s,
        complete=complete,
    )


def rank(metrics: Sequence[RouteMetrics]) -> list[int]:
    """Indices ordered best first; the sort is stable, so full ties keep routing order."""
    return sorted(range(len(metrics)), key=lambda i: metrics[i].sort_key())


_KEY_REASONS = (
    "it has complete weather data",
    "it has fewer No Travel miles",
    "it has fewer Severe miles",
    "it has fewer High miles",
    "it has a lower average risk",
    "it is faster",
)


def deciding_reason(best: RouteMetrics, runner_up: RouteMetrics | None) -> str:
    if runner_up is None:
        return "it is the only route available"
    for reason, a, b in zip(_KEY_REASONS, best.sort_key(), runner_up.sort_key(), strict=True):
        if a != b:
            return reason
    return "it ties with the next route on every measure and comes first in routing order"
