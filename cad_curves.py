"""Polynomial curve contacts and bounded, regular parallel-curve approximations."""

import itertools
import math

from numpy.polynomial import Polynomial as Poly
from scipy.optimize import brentq, least_squares

try:
    from .cad_geometry import EPS, add, distance, mul, positive, rotate, sub
except ImportError:
    from cad_geometry import EPS, add, distance, mul, positive, rotate, sub


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def roots(poly, lo=0.0, hi=1.0):
    """Isolate real roots between derivative roots, retaining repeated contacts.

    Bounded parameters and coefficient normalization reduce scaling sensitivity.
    This is floating-point isolation, not an exact-arithmetic multiplicity proof.
    An identically zero polynomial describes overlap, not isolated contacts.
    """
    scale = max(abs(poly.coef), default=0)
    if scale == 0:
        return []
    p = Poly(poly.coef / scale).trim(tol=2e-14)
    if p.degree() == 0:
        return []
    critical = roots(p.deriv(), lo, hi)
    times = [lo, *[t for t in critical if lo < t < hi], hi]
    crossing = [(a, b) for a, b in itertools.pairwise(times) if p(a) * p(b) < 0]
    result = [
        t
        for t in times
        if abs(p(t)) <= 2e-13 * sum(abs(p.coef))
        and not (any(b == t for a, b in crossing) and any(a == t for a, b in crossing))
    ]
    for a, b in crossing:
        result.append(brentq(p, a, b, xtol=5e-15))
    unique = []
    for t in sorted(result):
        if not unique or abs(t - unique[-1]) > 2e-10:
            unique.append(t)
    return unique


def bezier_polynomials(e):
    result = []
    for axis in (0, 1):
        a, b, c, d = [p[axis] for p in e.data["points"]]
        first, second, third = b - a, c - b, d - c
        result.append(
            Poly([a, 3 * first, 3 * (second - first), third - 2 * second + first])
        )
    return result


def evaluate(e, t):
    """Local position, first derivative and second derivative."""
    if e.kind == "ellipse":
        a, b = e.data["rx"], e.data["ry"]
        c, s = math.cos(t), math.sin(t)
        return (a * c, b * s), (-a * s, b * c), (-a * c, -b * s)
    x, y = bezier_polynomials(e)
    return (x(t), y(t)), (x.deriv()(t), y.deriv()(t)), (x.deriv(2)(t), y.deriv(2)(t))


def ellipse_charts(e):
    """Two bounded tan(theta/2) charts, including the otherwise infinite seam."""
    denominator = Poly([1, 0, 1])
    for sign in (1, -1):
        x = sign * e.data["rx"] * Poly([1, 0, -1])
        y = sign * e.data["ry"] * Poly([0, 2])
        yield x, y, denominator


def contact_parameters(e, point, tangent=False):
    p = e.local(point)
    if e.kind == "bezier":
        x, y = bezier_polynomials(e)
        delta, velocity = (x - p[0], y - p[1]), (x.deriv(), y.deriv())
        equation = cross(delta, velocity) if tangent else dot(delta, velocity)
        return roots(equation)
    result = []
    for x, y, den in ellipse_charts(e):
        delta = x - p[0] * den, y - p[1] * den
        velocity = x.deriv() * den - x * den.deriv(), y.deriv() * den - y * den.deriv()
        equation = cross(delta, velocity) if tangent else dot(delta, velocity)
        for u in roots(equation, -1, 1):
            result.append(math.atan2(y(u) / e.data["ry"], x(u) / e.data["rx"]))
    return result


def ellipse_parameter_on(e, t):
    start = math.radians(e.data.get("start", 0))
    sweep = math.radians(e.data.get("sweep", 360))
    delta = ((t - start) * (1 if sweep > 0 else -1)) % math.tau
    return delta <= abs(sweep) + 1e-10 or delta >= math.tau - 1e-10


def curve_contacts(e, point, *, perpendicular=False, tangent=False):
    result = []
    for enabled, mode in [(perpendicular, "Perpendicular"), (tangent, "Tangent")]:
        if not enabled:
            continue
        for t in contact_parameters(e, point, mode == "Tangent"):
            if e.kind == "ellipse" and not ellipse_parameter_on(e, t):
                continue
            p, v, _ = evaluate(e, t)
            q = e.world(p)
            delta = sub(p, e.local(point))
            size = math.hypot(*v) * math.hypot(*delta)
            tolerance = max(EPS, *(8 * math.ulp(c) for c in (*q, *point)))
            residual = cross(delta, v) if mode == "Tangent" else dot(delta, v)
            if (
                math.hypot(*v) > EPS
                and distance(q, point) > tolerance
                and abs(residual) <= 1e-8 * size
                and not any(
                    distance(q, old) <= tolerance and mode == m for old, m in result
                )
            ):
                result.append((q, mode))
    return result


def closest_point(e, point):
    times = contact_parameters(e, point)
    if e.kind == "bezier":
        times += [0, 1]
    else:
        times = [t for t in times if ellipse_parameter_on(e, t)]
        times += [
            math.radians(e.data.get("start", 0)),
            math.radians(e.data.get("start", 0) + e.data.get("sweep", 360)),
        ]
    return min(
        (e.world(evaluate(e, t)[0]) for t in times), key=lambda q: distance(q, point)
    )


def transformed(x, y, denominator, origin, target):
    dx, dy = sub(origin, (target.x, target.y))
    x, y = x + dx * denominator, y + dy * denominator
    c, s = rotate((1, 0), -target.angle)
    return c * x - s * y, s * x + c * y


def implicit_equation(target, x, y, den, origin):
    x, y = transformed(x, y, den, origin, target)
    if target.kind == "line":
        a, b = target.data["points"]
        return cross((x - a[0] * den, y - a[1] * den), sub(b, a))
    rx, ry = (
        (target.data["rx"], target.data["ry"])
        if target.kind == "ellipse"
        else (target.data["radius"], target.data["radius"])
    )
    return (x / rx) ** 2 + (y / ry) ** 2 - den**2


def determinant(matrix):
    """Small polynomial determinant by subset expansion (no matrix inversion)."""
    partial = {0: Poly([1])}
    for row in matrix:
        following = {}
        for mask, value in partial.items():
            for j, entry in enumerate(row):
                if mask & (1 << j) or not any(entry.coef):
                    continue
                sign = -1 if (mask >> (j + 1)).bit_count() % 2 else 1
                key = mask | (1 << j)
                following[key] = following.get(key, Poly([0])) + sign * value * entry
        partial = following
    return partial.get((1 << len(matrix)) - 1, Poly([0]))


def bezier_intersections(a, b):
    controls_a, controls_b = a.vertices(), b.vertices()
    tolerance = max(EPS, *(8 * math.ulp(v) for p in controls_a + controls_b for v in p))
    if any(
        all(distance(p, q) <= tolerance for p, q in zip(controls_a, order))
        for order in (controls_b, controls_b[::-1])
    ):
        return []  # Same/reversed control net has no isolated intersection.
    # Translate and scale before elimination to avoid large absolute coordinates.
    ax, ay = bezier_polynomials(a)
    bx, by = bezier_polynomials(b)
    c, s = rotate((1, 0), b.angle)
    bx, by = c * bx - s * by, s * bx + c * by
    bx, by = transformed(bx, by, Poly([1]), (b.x, b.y), a)
    size = max(1, *(abs(v) for p in (ax, ay, bx, by) for v in p.coef))
    ax, ay, bx, by = [p / size for p in (ax, ay, bx, by)]
    equations = []
    for first, second in [(ax, bx), (ay, by)]:
        second = second.trim(tol=2e-14)
        equations.append(
            [first - second.coef[0], *[Poly([-v]) for v in second.coef[1:]]]
        )
    f, g = equations
    m, n = len(f) - 1, len(g) - 1
    if m + n == 0:
        return []
    matrix = []
    for equation, count in [(f, n), (g, m)]:
        for shift in range(count):
            row = [Poly([0]) for _ in range(m + n)]
            row[shift : shift + len(equation)] = reversed(equation)
            matrix.append(row)
    resultant = determinant(matrix)
    result = []
    axis = bx if max(abs(bx.deriv().coef)) >= max(abs(by.deriv().coef)) else by
    first = ax if axis is bx else ay
    av, bv = (ax.deriv(), ay.deriv()), (bx.deriv(), by.deriv())

    def residual(z):
        return [ax(z[0]) - bx(z[1]), ay(z[0]) - by(z[1])]

    def tangent_residual(z):
        v, w = tuple(p(z[0]) for p in av), tuple(p(z[1]) for p in bv)
        denominator = math.hypot(*v) * math.hypot(*w)
        return [*residual(z), cross(v, w) / denominator if denominator > 0 else 1]

    for t in roots(resultant):
        for u in roots(axis - first(t)):
            z = (t, u)
            if math.hypot(*residual(z)) * size > EPS:
                z = least_squares(
                    residual,
                    z,
                    bounds=([0, 0], [1, 1]),
                    xtol=1e-14,
                    ftol=1e-14,
                    gtol=1e-14,
                    max_nfev=80,
                ).x
            # A multiple resultant root can spread into nearby pseudo-roots.
            # Refine actual tangent contacts using direction as well as position.
            # Keep the position solution when tangency cannot be validated.
            if abs(tangent_residual(z)[-1]) < 1e-3:
                refined = least_squares(
                    tangent_residual,
                    z,
                    bounds=([0, 0], [1, 1]),
                    xtol=1e-14,
                    ftol=1e-14,
                    gtol=1e-14,
                    max_nfev=100,
                ).x
                if (
                    math.hypot(*residual(refined)) * size <= EPS
                    and abs(tangent_residual(refined)[-1]) <= 1e-10
                ):
                    z = refined
            if math.hypot(*residual(z)) * size <= max(EPS, 32 * math.ulp(size)):
                p = a.world(evaluate(a, z[0])[0])
                tolerance = max(EPS, *(16 * math.ulp(v) for v in p))
                if not any(distance(p, q) <= tolerance for q in result):
                    result.append(p)
    return result


def curve_intersections(a, b):
    """Isolated contacts for pairs containing an ellipse or cubic Bezier."""
    if a.kind == b.kind == "bezier":
        return bezier_intersections(a, b)
    if a.kind in ("ellipse", "circle", "arc") and b.kind in (
        "ellipse",
        "circle",
        "arc",
    ):

        def conic(e):
            rx, ry = (
                (e.data["rx"], e.data["ry"])
                if e.kind == "ellipse"
                else (e.data["radius"], e.data["radius"])
            )
            c, s = rotate((1, 0), e.angle)
            return (
                c * c / rx**2 + s * s / ry**2,
                c * s * (1 / rx**2 - 1 / ry**2),
                s * s / rx**2 + c * c / ry**2,
            )

        qa, qb = conic(a), conic(b)
        if distance((a.x, a.y), (b.x, b.y)) <= EPS and max(
            abs(x - y) for x, y in zip(qa, qb)
        ) <= 2e-14 * max(*map(abs, qa), *map(abs, qb)):
            return []  # Coincident conic supports, including rotated/swap-axis forms.
    source, target = (a, b) if a.kind == "bezier" else (b, a)
    if source.kind != "bezier":
        source, target = (a, b) if a.kind == "ellipse" else (b, a)
    result = []
    if source.kind == "bezier":
        x, y = bezier_polynomials(source)
        c, s = rotate((1, 0), source.angle)
        equation = implicit_equation(
            target, c * x - s * y, s * x + c * y, Poly([1]), (source.x, source.y)
        )
        result = [source.world(evaluate(source, t)[0]) for t in roots(equation)]
    else:
        for x, y, den in ellipse_charts(source):
            c, s = rotate((1, 0), source.angle)
            equation = implicit_equation(
                target, c * x - s * y, s * x + c * y, den, (source.x, source.y)
            )
            result.extend(
                source.world((x(t) / den(t), y(t) / den(t)))
                for t in roots(equation, -1, 1)
            )
    unique = []
    for p in result:
        tolerance = max(EPS, *(16 * math.ulp(v) for v in p))
        if not any(distance(p, q) <= tolerance for q in unique):
            unique.append(p)
    return unique


def simple_polyline(points, closed):
    """Reject nonadjacent segment contacts, with a bounded broad-phase scan."""
    pairs = list(zip(points, points[1:] + (points[:1] if closed else [])))
    ordered = sorted(
        (min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), i, a, b)
        for i, (a, b) in enumerate(pairs)
    )
    active, checks = [], 0
    for low, high, bottom, top, i, a, b in ordered:
        active = [entry for entry in active if entry[1] >= low - EPS]
        for _, _, y0, y1, j, c, d in active:
            if abs(i - j) == 1 or (closed and {i, j} == {0, len(pairs) - 1}):
                continue
            if y1 < bottom - EPS or top < y0 - EPS:
                continue
            checks += 1
            if checks > 200000:
                raise ValueError(
                    "Offset topology check budget exceeded; simplify the curve."
                )
            r, s = sub(b, a), sub(d, c)
            den = cross(r, s)
            if abs(den) > EPS * max(EPS, math.hypot(*r) * math.hypot(*s)):
                t, u = cross(sub(c, a), s) / den, cross(sub(c, a), r) / den
                if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
                    raise ValueError(
                        "Offset is self-intersecting; choose a smaller distance."
                    )
            else:
                try:
                    from .cad_geometry import segment_distance
                except ImportError:
                    from cad_geometry import segment_distance
                if (
                    min(
                        segment_distance(a, c, d),
                        segment_distance(b, c, d),
                        segment_distance(c, a, b),
                        segment_distance(d, a, b),
                    )
                    <= EPS
                ):
                    raise ValueError("Offset contains overlapping segments.")
        active.append((low, high, bottom, top, i, a, b))


def offset_curve(e, amount, tolerance=0.01):
    """Approximate regular F=C+d*N by chords using a bound on |F''| h²/8.

    Positive ellipse distance is outward; positive Bezier distance is left.
    Failed accuracy, regularity or topology checks raise before document mutation.
    """
    tolerance = positive(tolerance)
    if tolerance < max(EPS * 10, *(32 * math.ulp(v) for v in (e.x, e.y))):
        raise ValueError("Offset tolerance is below coordinate precision.")
    ellipse = e.kind == "ellipse"
    signed = -amount if ellipse else amount
    if ellipse:
        minor, major = sorted([e.data["rx"], e.data["ry"]])
        if amount < 0 and -amount >= minor * (minor / major):
            raise ValueError("Inward ellipse offset reaches a curvature cusp.")
        first = math.radians(e.data.get("start", 0))
        last = first + math.radians(e.data.get("sweep", 360))
        begin, end = sorted((first, last))
    else:
        x, y = bezier_polynomials(e)
        vx, vy = x.deriv(), y.deriv()
        ax, ay = x.deriv(2), y.deriv(2)
        speed2 = vx * vx + vy * vy
        if min(speed2(t) for t in [0, 1, *roots(speed2.deriv())]) <= EPS**2:
            raise ValueError("Bezier offset needs a nonstationary tangent everywhere.")
        begin, end = 0.0, 1.0

    def point(t):
        p, v, _ = evaluate(e, t)
        speed = math.hypot(*v)
        if speed <= EPS:
            raise ValueError("Offset reaches a stationary tangent.")
        return add(p, mul((-v[1], v[0]), signed / speed))

    points = [point(begin)]
    segments = 0

    def visit(lo, hi, depth):
        nonlocal segments
        h = hi - lo
        if ellipse:
            a, b = e.data["rx"], e.data["ry"]
            extrema = [
                lo,
                hi,
                *[
                    i * math.pi / 2
                    for i in range(
                        math.ceil(2 * lo / math.pi), math.floor(2 * hi / math.pi) + 1
                    )
                ],
            ]
            speed = min(math.hypot(a * math.sin(t), b * math.cos(t)) for t in extrema)
            acceleration = max(
                math.hypot(a * math.cos(t), b * math.sin(t)) for t in extrema
            )
            jerk = max(math.hypot(a * math.sin(t), b * math.cos(t)) for t in extrema)
            regular = True  # Proven globally by the inward curvature-radius guard.
        else:
            v0, v1 = (vx(lo), vy(lo)), (vx(hi), vy(hi))
            vm = add(v0, mul((ax(lo), ay(lo)), h / 2))
            box = [(min(v0[i], vm[i], v1[i]), max(v0[i], vm[i], v1[i])) for i in (0, 1)]
            speed = math.hypot(*(max(0, a, -b) for a, b in box))
            acceleration = max(math.hypot(ax(t), ay(t)) for t in (lo, hi))
            jerk = math.hypot(x.deriv(3)(0), y.deriv(3)(0))
            curvature_numerator = signed * (vx * ay - vy * ax)
            maximum = max(
                curvature_numerator(t)
                for t in [lo, hi, *roots(curvature_numerator.deriv(), lo, hi)]
            )
            regular = speed > EPS and maximum < speed**3 * (1 - 1e-10)
            for t in (lo, (lo + hi) / 2, hi):
                v, a = (vx(t), vy(t)), (ax(t), ay(t))
                if signed * cross(v, a) >= math.hypot(*v) ** 3 * (1 - 1e-10):
                    raise ValueError("Bezier offset reaches a curvature fold/cusp.")
        bound = (
            (
                acceleration
                + abs(signed) * (jerk / speed + 3 * (acceleration / speed) ** 2)
            )
            if speed > EPS
            else math.inf
        )
        if regular and bound * h * h / 8 <= tolerance:
            segments += 1
            if segments > 8192:
                raise ValueError("Offset exceeds 8192 segments; increase tolerance.")
            points.append(point(hi))
        else:
            if depth >= 24:
                raise ValueError(
                    "Cannot certify offset accuracy/regularity; simplify the curve."
                )
            mid = (lo + hi) / 2
            visit(lo, mid, depth + 1)
            visit(mid, hi, depth + 1)

    visit(begin, end, 0)
    closed = ellipse and abs(e.data.get("sweep", 360)) >= 360 - EPS
    if ellipse and e.data.get("sweep", 360) < 0:
        points.reverse()
    if closed:
        points.pop()  # Use a closed polyline rather than a repeated endpoint.
    simple_polyline(points, closed)
    e.kind = "polyline"
    e.data = {
        "points": points,
        "closed": closed,
        "offset_approximation": {
            "distance": amount,
            "tolerance": tolerance,
            "method": "bounded-normal-chords",
        },
    }
    return e
