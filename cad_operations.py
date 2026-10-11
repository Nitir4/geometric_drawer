"""Analytic intersections, circular trimming and mitered polyline offsets."""

import itertools
import math

try:
    from .cad_geometry import (
        EPS,
        add,
        angle,
        distance,
        line_intersection,
        mul,
        rotate,
        segment_distance,
        sub,
        unit,
    )
except ImportError:
    from cad_geometry import (
        EPS,
        add,
        angle,
        distance,
        line_intersection,
        mul,
        rotate,
        segment_distance,
        sub,
        unit,
    )


def intersections(a, b):
    """Intersections of infinite lines/circle supports; caller clips arc ranges."""
    if a.kind == b.kind == "line":
        try:
            return [line_intersection(*a.vertices(), *b.vertices())[0]]
        except ValueError:
            return []
    if a.kind == "line" or b.kind == "line":
        line, circle = (a, b) if a.kind == "line" else (b, a)
        p, q = line.vertices()
        direction = unit(sub(q, p))
        along = sum(x * y for x, y in zip(sub((circle.x, circle.y), p), direction))
        closest = add(p, mul(direction, along))
        separation = distance(closest, (circle.x, circle.y))
        radius = circle.data["radius"]
        tolerance = max(
            EPS**2, *(8 * math.ulp(v) for v in (*closest, circle.x, circle.y, radius))
        )
        if separation > radius + tolerance:
            return []
        if abs(separation - radius) <= tolerance:
            return [closest]
        half_chord = math.sqrt(max(0, (radius - separation) * (radius + separation)))
        offset = mul(direction, half_chord)
        return [sub(closest, offset), add(closest, offset)]
    c1, c2 = (a.x, a.y), (b.x, b.y)
    d, r1, r2 = distance(c1, c2), a.data["radius"], b.data["radius"]
    tolerance = max(EPS**2, *(8 * math.ulp(v) for v in (*c1, *c2, d, r1, r2)))
    if d == 0 or d > r1 + r2 + tolerance or d < abs(r1 - r2) - tolerance:
        return []
    # Scaled Heron product avoids subtracting two almost equal radius squares.
    scale = max(d, r1, r2)
    x, y, z = d / scale, r1 / scale, r2 / scale
    along = scale * (x + (y - z) * (y + z) / x) / 2
    factors = (y + z + x, y + z - x, x + y - z, x - y + z)
    h = scale * math.sqrt(max(0, math.prod(factors))) / (2 * x)
    if abs(d - (r1 + r2)) <= tolerance or abs(d - abs(r1 - r2)) <= tolerance:
        h = 0
    u = mul(sub(c2, c1), 1 / d)
    base = add(c1, mul(u, along))
    normal = mul(rotate(u, 90), h)
    return [base] if h <= tolerance else [add(base, normal), sub(base, normal)]


def arc_parameter(e, p):
    degrees = angle(sub(p, (e.x, e.y))) - e.angle - e.data.get("start", 0)
    sign = 1 if e.data.get("sweep", 360) > 0 else -1
    return (degrees * sign) % 360


def on_curve(e, p, tolerance=EPS):
    """Test the actual finite line/circular curve, independent of display meshes."""
    if e.kind == "line":
        return segment_distance(p, *e.vertices()) <= tolerance
    if e.kind in ("ellipse", "bezier"):
        try:
            from .cad_curves import closest_point
        except ImportError:
            from cad_curves import closest_point
        return distance(p, closest_point(e, p)) <= tolerance
    if e.kind not in ("circle", "arc"):
        return False
    radius = e.data["radius"]
    if abs(distance(p, (e.x, e.y)) - radius) > tolerance:
        return False
    if e.kind == "circle":
        return True
    delta = arc_parameter(e, p)
    angular_tolerance = math.degrees(tolerance / radius)
    return (
        delta <= abs(e.data["sweep"]) + angular_tolerance
        or delta >= 360 - angular_tolerance
    )


def curve_tolerance(e, p):
    """Local numerical tolerance; unrelated long edges must not enlarge it."""
    values = [*p, e.x, e.y]
    if e.kind in ("line", "bezier"):
        values.extend(v for endpoint in e.vertices() for v in endpoint)
    elif e.kind == "ellipse":
        values.extend((e.data["rx"], e.data["ry"]))
    else:
        values.append(e.data["radius"])
    return max(EPS, *(8 * math.ulp(v) for v in values))


def finite_intersections(a, b):
    """Actual intersections: exclude line extensions and the missing arc sector."""
    if a.kind not in ("line", "circle", "arc", "ellipse", "bezier") or b.kind not in (
        "line",
        "circle",
        "arc",
        "ellipse",
        "bezier",
    ):
        return []

    if a.kind in ("ellipse", "bezier") or b.kind in ("ellipse", "bezier"):
        try:
            from .cad_curves import curve_intersections
        except ImportError:
            from cad_curves import curve_intersections
        candidates = curve_intersections(a, b)
    else:
        candidates = intersections(a, b)
    return [
        p
        for p in candidates
        if on_curve(a, p, curve_tolerance(a, p))
        and on_curve(b, p, curve_tolerance(b, p))
    ]


def corner_leg(e, intersection, pick=None):
    """Return endpoint to replace, retained ray and available length on that ray."""
    endpoints = e.vertices()
    direction = unit(sub(endpoints[1], endpoints[0]))
    offsets = [
        sum(x * y for x, y in zip(sub(p, intersection), direction)) for p in endpoints
    ]
    sides = {1 if t > 0 else -1 for t in offsets if abs(t) > EPS}
    if not sides:
        raise ValueError(
            "Corner legs are too small at the current geometric tolerance."
        )
    if len(sides) == 2:
        if pick is None:
            raise ValueError("Crossing lines require a corner pick (x, y).")
        projection = sum(x * y for x, y in zip(sub(pick, intersection), direction))
        if abs(projection) <= EPS:
            raise ValueError("Pick inside the intended corner, away from its lines.")
        side = 1 if projection > 0 else -1
    else:
        side = next(iter(sides))
    keep = max(range(2), key=lambda i: side * offsets[i])
    return 1 - keep, mul(direction, side), abs(offsets[keep])


def trim_curve(e, boundary, pick, extend):
    if e.kind not in ("line", "circle", "arc") or boundary.kind not in (
        "line",
        "circle",
        "arc",
    ):
        raise ValueError("Trim/extend supports lines, circles and circular arcs.")
    points = intersections(e, boundary)
    if boundary.kind == "arc":
        points = [
            p
            for p in points
            if arc_parameter(boundary, p) <= abs(boundary.data["sweep"]) + EPS
        ]
    if not points:
        raise ValueError("The curve supports do not intersect.")
    if e.kind == "line":
        a, b = e.vertices()
        u = sub(b, a)
        norm = sum(t * t for t in u)
        candidates = [
            (sum(x * y for x, y in zip(sub(p, a), u)) / norm, p) for p in points
        ]
        if extend:
            candidates = [(t, p) for t, p in candidates if t < -EPS or t > 1 + EPS]
        else:
            candidates = [(t, p) for t, p in candidates if EPS < t < 1 - EPS]
        if not candidates:
            if extend:
                raise ValueError("Boundary already intersects the line; use Trim.")
            raise ValueError(
                "No boundary intersection is available for this trim/extend."
            )
        t, p = min(candidates, key=lambda item: distance(pick, item[1]))
        index = (
            (0 if t < 0 else 1)
            if extend
            else (0 if distance(pick, a) < distance(pick, b) else 1)
        )
        e.data["points"][index] = e.local(p)
        return
    if e.kind == "circle":
        if extend:
            raise ValueError("A complete circle cannot be extended.")
        if len(points) != 2 or distance(*points) <= EPS:
            raise ValueError(
                "Trimming a circle requires two distinct boundary intersections."
            )
        start, end = sorted(angle(sub(p, (e.x, e.y))) % 360 for p in points)
        pick_angle = angle(sub(pick, (e.x, e.y))) % 360
        if start < pick_angle < end:
            start, end = end, start + 360
        e.kind = "arc"
        e.angle = 0
        e.data.update(start=start, sweep=end - start)
        return
    sweep = e.data["sweep"]
    extent, sign = abs(sweep), 1 if sweep > 0 else -1
    cuts = [(arc_parameter(e, p), p) for p in points]
    endpoints = e.paths()[0][:: len(e.paths()[0]) - 1]
    first = distance(pick, endpoints[0]) < distance(pick, endpoints[1])
    if extend:
        cuts = [(t, p) for t, p in cuts if extent + EPS < t < 360 - EPS]
        if not cuts:
            raise ValueError("No intersection lies beyond the arc endpoints.")
        t, _ = min(
            cuts, key=lambda item: (360 - item[0]) if first else (item[0] - extent)
        )
        if first:
            e.data["start"] += sign * (t - 360)
            e.data["sweep"] = sign * (extent + 360 - t)
        else:
            e.data["sweep"] = sign * t
    else:
        cuts = [(t, p) for t, p in cuts if EPS < t < extent - EPS]
        if not cuts:
            raise ValueError("Boundary must cross the arc interior.")
        t, _ = min(cuts, key=lambda item: distance(pick, item[1]))
        if first:
            e.data["start"] += sign * t
            e.data["sweep"] = sign * (extent - t)
        else:
            e.data["sweep"] = sign * t


def offset_polyline(e, amount):
    points, closed = e.vertices(), e.data.get("closed", False)
    if closed and distance(points[0], points[-1]) <= EPS:
        points = points[:-1]
    if len(points) > 2000:
        raise ValueError("Polyline offset supports up to 2000 vertices per operation.")
    if closed and len(points) < 3:
        raise ValueError("Closed offset needs at least three vertices.")
    area = (
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        / 2
    )
    signed = (-amount if area > 0 else amount) if closed else amount
    pairs = (
        list(zip(points, points[1:] + points[:1]))
        if closed
        else list(itertools.pairwise(points))
    )
    edges = []
    for a, b in pairs:
        normal = mul(rotate(unit(sub(b, a)), 90), signed)
        edges.append((add(a, normal), add(b, normal)))
    result = [] if closed else [edges[0][0]]
    for i in range(len(points) if closed else len(points) - 2):
        before, after = (edges[i - 1], edges[i]) if closed else (edges[i], edges[i + 1])
        try:
            p = line_intersection(*before, *after)[0]
        except ValueError:
            if distance(before[1], after[0]) > 1e-7:
                raise ValueError(
                    "Offset has a reversing or degenerate corner."
                ) from None
            p = before[1]
        if (
            abs(amount) > EPS
            and distance(p, points[i if closed else i + 1]) > abs(amount) * 100
        ):
            raise ValueError(
                "Offset miter exceeds 100 times the offset; simplify the corner."
            )
        result.append(p)
    if not closed:
        result.append(edges[-1][1])
    # Reject edge reversal/collapse instead of returning a spurious inner loop.
    out_pairs = (
        list(zip(result, result[1:] + result[:1]))
        if closed
        else list(itertools.pairwise(result))
    )
    for (a, b), (c, d) in zip(pairs, out_pairs):
        u, v = sub(b, a), sub(d, c)
        if sum(x * y for x, y in zip(u, v)) <= EPS:
            raise ValueError("Offset collapses or reverses a segment.")
    for i, edge in enumerate(out_pairs):
        for j in range(i + 2, len(out_pairs)):
            if closed and i == 0 and j == len(out_pairs) - 1:
                continue
            try:
                _, t, u = line_intersection(*edge, *out_pairs[j])
            except ValueError:
                continue
            if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
                raise ValueError(
                    "Offset creates a self-intersection; reduce the distance."
                )
    e.x = e.y = e.angle = 0
    e.data["points"] = result
