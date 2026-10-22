import math

import pytest

from routing.geometry import (
    MI_PER_DEG_LAT,
    attribute_miles,
    corridor_cells,
    cumulative_mi,
    distinct_routes,
    haversine_mi,
    interpolate,
    position_at,
    sample_miles,
    simplify,
)


def line(miles: float, lat_offset_mi: float = 0.0, start_mi: float = 0.0, step_mi: float = 0.1):
    """A straight east-west route on the equator, where one degree is exactly MI_PER_DEG_LAT."""
    n = max(1, round(miles / step_mi))
    lat = lat_offset_mi / MI_PER_DEG_LAT
    return [(lat, (start_mi + miles * i / n) / MI_PER_DEG_LAT) for i in range(n + 1)]


def test_haversine_chicago_to_denver_great_circle():
    assert haversine_mi((41.8781, -87.6298), (39.7392, -104.9903)) == pytest.approx(918.2, abs=0.1)


@pytest.mark.parametrize(
    ("total", "interval", "expected"),
    [
        (100, 25, [0, 25, 50, 75, 100]),
        (110, 25, [0, 25, 50, 75, 100, 110]),
        (100, 50, [0, 50, 100]),
        (0.3, 0.5, [0, 0.3]),
        (0, 25, [0]),
    ],
)
def test_sample_miles_includes_start_and_end_once(total, interval, expected):
    assert sample_miles(total, interval) == expected


@pytest.mark.parametrize(("interval", "count"), [(10, 13), (25, 6), (50, 4)])
def test_each_interval_gives_expected_checkpoint_count_for_120_miles(interval, count):
    assert len(sample_miles(120, interval)) == count


def test_checkpoints_land_on_exact_mileposts():
    route = line(60)
    cumulative = cumulative_mi(route)

    positions = [position_at(route, cumulative, m) for m in sample_miles(cumulative[-1], 25)]

    assert [round(lon * MI_PER_DEG_LAT, 6) for _, lon in positions] == [0, 25, 50, 60]


def test_attributed_miles_split_at_midpoints_and_sum_to_route_length():
    shares = attribute_miles([0, 25, 50, 60])

    assert shares == [12.5, 25.0, 17.5, 5.0]
    assert sum(shares) == 60


def test_interpolate_is_linear_between_anchors_and_clamped_outside():
    xs, ys = [0, 10, 30], [0, 600, 3000]

    assert [interpolate(xs, ys, x) for x in (-5, 5, 20, 30, 40)] == [0, 300, 1800, 3000, 3000]


def test_simplify_drops_collinear_points_and_keeps_real_bends():
    assert simplify(line(10), 0.01) == [line(10)[0], line(10)[-1]]

    bend = [(0.0, 0.0), (1 / MI_PER_DEG_LAT, 5 / MI_PER_DEG_LAT), (0.0, 10 / MI_PER_DEG_LAT)]
    assert simplify(bend, 0.5) == bend


class TestDistinctRoutes:
    def test_identical_route_is_a_duplicate(self):
        assert distinct_routes([line(20), line(20)]) == [0]

    def test_route_69_miles_away_is_distinct(self):
        assert distinct_routes([line(20), line(20, lat_offset_mi=69)]) == [0, 1]

    def test_exactly_90_percent_overlap_is_a_duplicate(self):
        # 20 samples over 9.5 mi; the kept route covers the first 18 (0 to 8.5 mi).
        assert distinct_routes([line(8.5), line(9.5)]) == [0]

    def test_just_under_90_percent_overlap_is_distinct(self):
        # 19 samples over 9.0 mi; 17 covered is 89.5%.
        assert distinct_routes([line(8.0), line(9.0)]) == [0, 1]

    def test_sample_exactly_at_tolerance_is_covered(self):
        assert distinct_routes([line(5), line(5, lat_offset_mi=0.25)]) == [0]

    def test_sample_just_beyond_tolerance_is_not_covered(self):
        assert distinct_routes([line(5), line(5, lat_offset_mi=0.26)]) == [0, 1]

    def test_route_shorter_than_one_sample_step_is_still_compared(self):
        assert distinct_routes([line(0.3, step_mi=0.3), line(0.3, step_mi=0.3)]) == [0]

    def test_earlier_candidate_wins_between_near_identical_routes(self):
        a, a_close, b = line(20), line(20, lat_offset_mi=0.1), line(20, lat_offset_mi=69)

        assert distinct_routes([a, a_close, b]) == [0, 2]
        assert distinct_routes([a_close, a, b]) == [0, 2]


class TestCorridorCells:
    def test_cells_are_snapped_so_overlapping_trips_share_points(self):
        spacing_a, cells_a = corridor_cells([line(100)], buffer_mi=25, max_cells=10_000)
        spacing_b, cells_b = corridor_cells(
            [line(100, start_mi=50)], buffer_mi=25, max_cells=10_000
        )

        assert spacing_a == spacing_b == 0.1
        overlap_lon = (60 / MI_PER_DEG_LAT, 90 / MI_PER_DEG_LAT)
        in_overlap = lambda cells: {c for c in cells if overlap_lon[0] <= c[1] <= overlap_lon[1]}  # noqa: E731
        assert in_overlap(cells_a) == in_overlap(cells_b) != set()

    def test_coast_to_coast_corridor_respects_the_cap(self):
        la_to_ny = [
            (34.05 + (40.71 - 34.05) * i / 300, -118.24 + 44.24 * i / 300) for i in range(301)
        ]

        spacing, cells = corridor_cells([la_to_ny], buffer_mi=25, max_cells=300)

        assert len(cells) <= 300
        assert spacing == 0.5

    def test_coarse_spacing_still_covers_a_route_between_lattice_rows(self):
        # At 1 degree the route runs 34.5 mi from either lattice row, beyond the 25 mi buffer.
        route = [(0.5, lon / 10) for lon in range(0, 101)]

        spacing, cells = corridor_cells([route], buffer_mi=25, max_cells=20)

        assert spacing == 1.0
        assert len(cells) == 22
        reach = 0.75 * spacing * MI_PER_DEG_LAT
        for point in route:
            assert min(haversine_mi(point, cell) for cell in cells) <= reach + 1

    def test_every_cell_lies_on_the_lattice(self):
        spacing, cells = corridor_cells([line(300)], buffer_mi=25, max_cells=300)

        for lat, lon in cells:
            assert math.isclose(lat / spacing, round(lat / spacing), abs_tol=1e-6)
            assert math.isclose(lon / spacing, round(lon / spacing), abs_tol=1e-6)
