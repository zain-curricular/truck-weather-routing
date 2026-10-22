import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence

LatLon = tuple[float, float]

EARTH_RADIUS_MI = 3958.7613
MI_PER_DEG_LAT = EARTH_RADIUS_MI * math.pi / 180

# Absorbs float noise when a computed mileage or distance should equal a boundary exactly.
EPSILON_MI = 1e-6


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_mi(points: Sequence[LatLon]) -> list[float]:
    totals = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        totals.append(totals[-1] + haversine_mi(a, b))
    return totals


def position_at(points: Sequence[LatLon], cumulative: Sequence[float], mile: float) -> LatLon:
    if mile <= 0:
        return points[0]
    if mile >= cumulative[-1]:
        return points[-1]
    i = bisect_right(cumulative, mile) - 1
    span = cumulative[i + 1] - cumulative[i]
    t = (mile - cumulative[i]) / span if span else 0.0
    (lat1, lon1), (lat2, lon2) = points[i], points[i + 1]
    return (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)


def sample_miles(total_mi: float, interval_mi: float) -> list[float]:
    """Mileposts at 0, every interval, and the end; the end is never duplicated."""
    miles = [0.0]
    k = 1
    while k * interval_mi < total_mi - EPSILON_MI:
        miles.append(k * interval_mi)
        k += 1
    if total_mi > 0:
        miles.append(total_mi)
    return miles


def interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise-linear y(x) over ascending xs, clamped to the end values."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    span = xs[i + 1] - xs[i]
    t = (x - xs[i]) / span if span else 0.0
    return ys[i] + (ys[i + 1] - ys[i]) * t


def attribute_miles(checkpoint_miles: Sequence[float]) -> list[float]:
    """Each checkpoint covers half the gap to each neighbour, so the shares sum to the route."""
    n = len(checkpoint_miles)
    shares = []
    for i, mile in enumerate(checkpoint_miles):
        left = (mile - checkpoint_miles[i - 1]) / 2 if i > 0 else 0.0
        right = (checkpoint_miles[i + 1] - mile) / 2 if i < n - 1 else 0.0
        shares.append(left + right)
    return shares


def _xy(point: LatLon, ref_lat: float) -> tuple[float, float]:
    return (
        point[1] * MI_PER_DEG_LAT * math.cos(math.radians(ref_lat)),
        point[0] * MI_PER_DEG_LAT,
    )


def point_segment_mi(p: LatLon, a: LatLon, b: LatLon) -> float:
    """Flat-earth distance around p; well under 1% error at the sub-60-mile range used here."""
    px, py = _xy(p, p[0])
    ax, ay = _xy(a, p[0])
    bx, by = _xy(b, p[0])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class SegmentIndex:
    """Grid buckets of a polyline's segments so nearest-distance queries stay local."""

    def __init__(self, points: Sequence[LatLon], cell_deg: float = 0.1) -> None:
        self.cell_deg = cell_deg
        self.points = points
        self.buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i in range(max(len(points) - 1, 1)):
            a, b = points[i], points[min(i + 1, len(points) - 1)]
            for cell in self._cells_between(
                min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
            ):
                self.buckets[cell].append(i)

    def _cells_between(
        self, lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float
    ) -> list[tuple[int, int]]:
        size = self.cell_deg
        return [
            (r, c)
            for r in range(math.floor(lat_lo / size), math.floor(lat_hi / size) + 1)
            for c in range(math.floor(lon_lo / size), math.floor(lon_hi / size) + 1)
        ]

    def distance_mi(self, p: LatLon, within_mi: float) -> float:
        """Nearest distance to the polyline, or inf when nothing lies within `within_mi`."""
        dlat = within_mi / MI_PER_DEG_LAT
        dlon = within_mi / (MI_PER_DEG_LAT * max(math.cos(math.radians(p[0])), 0.01))
        seen: set[int] = set()
        best = math.inf
        for cell in self._cells_between(p[0] - dlat, p[0] + dlat, p[1] - dlon, p[1] + dlon):
            for i in self.buckets.get(cell, ()):
                if i in seen:
                    continue
                seen.add(i)
                a, b = self.points[i], self.points[min(i + 1, len(self.points) - 1)]
                best = min(best, point_segment_mi(p, a, b))
        return best if best <= within_mi + EPSILON_MI else math.inf


DEDUPE_SAMPLE_MI = 0.5
DEDUPE_TOLERANCE_MI = 0.25


def distinct_routes(candidates: Sequence[Sequence[LatLon]]) -> list[int]:
    """Indices of candidates kept, in input order.

    A candidate is a duplicate when at least 90% of its 0.5-mile samples lie within 0.25 mi
    of a single route already kept.
    """
    kept: list[int] = []
    indexes: list[SegmentIndex] = []
    for i, route in enumerate(candidates):
        cumulative = cumulative_mi(route)
        samples = [
            position_at(route, cumulative, m)
            for m in sample_miles(cumulative[-1], DEDUPE_SAMPLE_MI)
        ] or [route[0]]
        duplicate = False
        for index in indexes:
            covered = sum(
                1 for s in samples if index.distance_mi(s, DEDUPE_TOLERANCE_MI) != math.inf
            )
            if covered * 10 >= len(samples) * 9:
                duplicate = True
                break
        if not duplicate:
            kept.append(i)
            indexes.append(SegmentIndex(route))
    return kept


def simplify(points: Sequence[LatLon], tolerance_mi: float) -> list[LatLon]:
    """Douglas-Peucker, iterative; endpoints are always kept.

    Points are projected once with each point's own longitude scale, which is accurate
    between neighbouring points and keeps the inner loop free of trigonometry.
    """
    if len(points) < 3:
        return list(points)
    ys = [lat * MI_PER_DEG_LAT for lat, _ in points]
    xs = [lon * MI_PER_DEG_LAT * math.cos(math.radians(lat)) for lat, lon in points]
    tolerance_sq = tolerance_mi * tolerance_mi
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        ax, ay = xs[start], ys[start]
        dx, dy = xs[end] - ax, ys[end] - ay
        length_sq = dx * dx + dy * dy
        worst, worst_i = 0.0, -1
        for i in range(start + 1, end):
            px, py = xs[i] - ax, ys[i] - ay
            t = (px * dx + py * dy) / length_sq if length_sq else 0.0
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            ex, ey = px - t * dx, py - t * dy
            d = ex * ex + ey * ey
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance_sq:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [p for p, k in zip(points, keep, strict=True) if k]


CORRIDOR_SPACINGS_DEG = (0.1, 0.25, 0.5, 1.0)


def corridor_cells(
    routes: Sequence[Sequence[LatLon]], buffer_mi: float, max_cells: int
) -> tuple[float, list[LatLon]]:
    """Lattice points near any route, at the finest spacing that stays within `max_cells`.

    The lattice is snapped to multiples of the spacing so overlapping trips reuse the same
    points, which keeps the weather cache warm. The buffer grows with coarse spacings so a
    route running between lattice points is never left uncovered, and the coarsest spacing
    is returned whole even above the cap rather than cutting coverage short.
    """
    simplified = [simplify(r, 0.05) for r in routes]
    indexes = [SegmentIndex(r, cell_deg=0.5) for r in simplified]
    cells: list[LatLon] = []
    for spacing in CORRIDOR_SPACINGS_DEG:
        reach_mi = max(buffer_mi, 0.75 * spacing * MI_PER_DEG_LAT)
        candidates: set[tuple[int, int]] = set()
        for route in simplified:
            cumulative = cumulative_mi(route)
            for mile in sample_miles(cumulative[-1], min(reach_mi, spacing * MI_PER_DEG_LAT) / 2):
                lat, lon = position_at(route, cumulative, mile)
                dlat = reach_mi / MI_PER_DEG_LAT
                dlon = reach_mi / (MI_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
                for r in range(
                    math.floor((lat - dlat) / spacing), math.ceil((lat + dlat) / spacing) + 1
                ):
                    for c in range(
                        math.floor((lon - dlon) / spacing), math.ceil((lon + dlon) / spacing) + 1
                    ):
                        candidates.add((r, c))
        cells = []
        for r, c in candidates:
            point = (round(r * spacing, 4), round(c * spacing, 4))
            if any(ix.distance_mi(point, reach_mi) != math.inf for ix in indexes):
                cells.append(point)
        cells.sort()
        if len(cells) <= max_cells:
            return spacing, cells
    return CORRIDOR_SPACINGS_DEG[-1], cells
