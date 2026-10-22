from routing.ranking import RouteMetrics, deciding_reason, rank, route_metrics
from routing.risk import Level

L, M, H, S, NT = Level.LOW, Level.MODERATE, Level.HIGH, Level.SEVERE, Level.NO_TRAVEL


def metrics(no_travel=0.0, severe=0.0, high=0.0, avg=0.0, duration=3600, complete=True):
    return RouteMetrics(no_travel, severe, high, avg if complete else None, duration, complete)


def test_route_metrics_sum_miles_by_level_and_weight_the_average_by_distance():
    result = route_metrics([L, S, H, S], [12.5, 25.0, 17.5, 5.0], duration_s=3600)

    assert (result.severe_mi, result.high_mi, result.no_travel_mi) == (30.0, 17.5, 0.0)
    assert result.avg_risk == (0 * 12.5 + 3 * 25 + 2 * 17.5 + 3 * 5) / 60
    assert result.complete and result.drivable


def test_unknown_checkpoint_makes_route_incomplete_and_not_drivable():
    result = route_metrics([L, None], [5.0, 5.0], duration_s=600)

    assert result.avg_risk is None
    assert not result.complete
    assert not result.drivable


def test_no_travel_miles_make_route_not_drivable():
    assert not route_metrics([L, NT], [5.0, 5.0], duration_s=600).drivable


def test_fewer_no_travel_miles_beats_fewer_severe_miles():
    assert rank([metrics(no_travel=5, severe=0), metrics(no_travel=0, severe=10)]) == [1, 0]


def test_severe_miles_decide_before_high_miles():
    assert rank([metrics(severe=10, high=0), metrics(severe=5, high=200)]) == [1, 0]


def test_high_miles_decide_when_severe_ties():
    assert rank([metrics(severe=5, high=30), metrics(severe=5, high=20)]) == [1, 0]


def test_average_risk_decides_when_miles_tie():
    assert rank([metrics(avg=1.2), metrics(avg=0.8)]) == [1, 0]


def test_travel_time_only_breaks_a_full_tie():
    assert rank([metrics(duration=9000), metrics(duration=7200)]) == [1, 0]
    assert rank([metrics(severe=1, duration=60), metrics(severe=2, duration=99999)]) == [0, 1]


def test_average_risk_float_noise_does_not_decide():
    assert rank([metrics(avg=0.30000000000000004, duration=10), metrics(avg=0.3, duration=5)]) == [
        1,
        0,
    ]


def test_incomplete_route_ranks_after_every_complete_route():
    incomplete = metrics(complete=False)

    assert rank([incomplete, metrics(no_travel=50, severe=50)]) == [1, 0]


def test_full_tie_keeps_routing_order():
    assert rank([metrics(), metrics(), metrics()]) == [0, 1, 2]


def test_deciding_reason_names_the_first_key_that_differs():
    assert deciding_reason(metrics(severe=0, high=9), metrics(severe=3)) == (
        "it has fewer Severe miles"
    )
    assert deciding_reason(metrics(duration=10), metrics(duration=20)) == "it is faster"
    assert deciding_reason(metrics(), None) == "it is the only route available"


def test_deciding_reason_for_a_full_tie_names_routing_order():
    assert deciding_reason(metrics(), metrics()) == (
        "it ties with the next route on every measure and comes first in routing order"
    )
