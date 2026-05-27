"""Finite path trimming and bounded analytic support extension."""

import copy
import itertools
import math

from shapely.geometry import LineString, Point
from shapely.ops import split

try:
    from .cad_boolean import material, region_outputs
    from .cad_curves import bezier_polynomials, contact_parameters
    from .cad_features import parameter_curve
    from .cad_geometry import EPS, Entity, add, distance, mul, sub, unit
    from .cad_operations import finite_intersections
    from .cad_snap import curve_parts
except ImportError:
    from cad_boolean import material, region_outputs
    from cad_curves import bezier_polynomials, contact_parameters
    from cad_features import parameter_curve
    from cad_geometry import EPS, Entity, add, distance, mul, sub, unit
    from cad_operations import finite_intersections
    from cad_snap import curve_parts


def curve_parameter(e, p, lo=0.0, hi=1.0):
    if e.kind == "line":
        a, b = e.vertices()
        v = sub(b, a)
        return sum(x * y for x, y in zip(sub(p, a), v)) / sum(x * x for x in v)
    if e.kind == "bezier":
        from numpy.polynomial import Polynomial

        try:
            from .cad_curves import roots
        except ImportError:
            from cad_curves import roots
        x, y = bezier_polynomials(e)
        q = e.local(p)
        equation = (x - Polynomial([q[0]])) * x.deriv() + (
            y - Polynomial([q[1]])
        ) * y.deriv()
        times = [lo, hi, *roots(equation, lo, hi)]
        return min(times, key=lambda t: distance(e.world((x(t), y(t))), p))
    q = e.local(p)
    if e.kind == "ellipse":
        theta = math.degrees(math.atan2(q[1] / e.data["ry"], q[0] / e.data["rx"]))
    else:
        theta = math.degrees(math.atan2(q[1], q[0]))
    start, sweep = e.data.get("start", 0), e.data.get("sweep", 360)
    delta = ((theta - start) * (1 if sweep > 0 else -1)) % 360
    if abs(delta - 360) < 1e-7:
        delta = 0
    return delta / abs(sweep)


def portion(e, start, end):
    result = copy.deepcopy(e)
    if end - start <= 1e-10:
        raise ValueError("Trim interval has no usable length.")
    if e.kind == "line":
        f = parameter_curve(e)
        a, b = f(start)[0], f(end)[0]
        result.x, result.y, result.angle = *a, 0
        result.data = {"points": [(0, 0), sub(b, a)]}
    elif e.kind == "bezier":
        x, y = bezier_polynomials(e)
        h = (end - start) / 3
        a, b = (x(start), y(start)), (x(end), y(end))
        result.data = {
            "points": [
                a,
                add(a, mul((x.deriv()(start), y.deriv()(start)), h)),
                sub(b, mul((x.deriv()(end), y.deriv()(end)), h)),
                b,
            ]
        }
    elif e.kind in ("circle", "arc", "ellipse"):
        span = e.data.get("sweep", 360)
        if e.kind == "circle":
            result.kind = "arc"
        result.data["start"] = e.data.get("start", 0) + span * start
        result.data["sweep"] = span * (end - start)
    else:
        raise ValueError("Unsupported curve portion.")
    return result.validate()


def trim_curve_parts(e, boundary, pick):
    times = []
    for cutter in curve_parts(boundary):
        for p in finite_intersections(e, cutter):
            t = curve_parameter(e, p)
            if 1e-9 < t < 1 - 1e-9 and not any(abs(t - u) < 1e-8 for u in times):
                times.append(t)
    closed = (
        e.kind == "circle"
        or e.kind in ("arc", "ellipse")
        and abs(e.data.get("sweep", 360)) >= 360 - EPS
    )
    if closed:
        # Parameter seam is not a physical endpoint; include seam contacts.
        for cutter in curve_parts(boundary):
            for p in finite_intersections(e, cutter):
                t = curve_parameter(e, p) % 1
                if not any(abs(t - u) < 1e-8 for u in times):
                    times.append(t)
        times.sort()
        if len(times) < 2:
            raise ValueError("Closed-curve trim needs two distinct crossings.")
        # Projection onto ellipse is not a radial projection for an off-curve pick.
        nearest_t = curve_parameter(e, pick)
        if e.kind == "ellipse":
            candidates = contact_parameters(e, pick)
            if candidates:
                nearest_t = curve_parameter(
                    e,
                    min(
                        (
                            e.world(
                                (e.data["rx"] * math.cos(t), e.data["ry"] * math.sin(t))
                            )
                            for t in candidates
                        ),
                        key=lambda p: distance(p, pick),
                    ),
                )
        intervals = list(itertools.pairwise(times + [times[0] + 1]))
        chosen = next(
            (
                (a, b)
                for a, b in intervals
                if a <= nearest_t + (1 if nearest_t < times[0] else 0) <= b
            ),
            None,
        )
        if chosen is None:
            raise ValueError("Pick a removable curve portion.")
        a, b = chosen
        return [
            portion(e, b, a + 1)
        ]  # Keep the cyclic complement, including all other cuts.
    times = sorted([0.0, *times, 1.0])
    if len(times) < 3:
        raise ValueError("No interior boundary crossing for Trim.")
    t = curve_parameter(e, pick)
    intervals = list(itertools.pairwise(times))
    chosen = min(
        range(len(intervals)),
        key=lambda i: (
            0
            if intervals[i][0] <= t <= intervals[i][1]
            else min(abs(t - intervals[i][0]), abs(t - intervals[i][1]))
        ),
    )
    a, b = intervals[chosen]
    result = []
    if a > 1e-10:
        result.append(portion(e, 0, a))
    if b < 1 - 1e-10:
        result.append(portion(e, b, 1))
    return result


def trim_path(e, boundary, pick, tolerance=0.01):
    if e.kind == "region":
        shape = material(e, tolerance)
        if boundary.kind == "line":
            a, b = boundary.vertices()
            u = unit(sub(b, a))
            box = shape.bounds
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            v = sub(centre, a)
            along = sum(x * y for x, y in zip(v, u))
            anchor = add(a, mul(u, along))
            extent = 2 * max(distance((box[0], box[1]), (box[2], box[3])), EPS)
            cut = LineString([sub(anchor, mul(u, extent)), add(anchor, mul(u, extent))])
            pieces = [g for g in split(shape, cut).geoms if g.geom_type == "Polygon"]
            if len(pieces) < 2:
                raise ValueError("Cutter does not split the region.")
            discard = min(
                range(len(pieces)), key=lambda i: pieces[i].distance(Point(pick))
            )
            from shapely.ops import unary_union

            result = unary_union([g for i, g in enumerate(pieces) if i != discard])
        else:
            cutter = material(boundary, tolerance)
            inside = shape.intersection(cutter)
            outside = shape.difference(cutter)
            if inside.area <= EPS**2 or outside.area <= EPS**2:
                raise ValueError("Cutter does not divide region material.")
            result = (
                outside
                if inside.distance(Point(pick)) <= outside.distance(Point(pick))
                else inside
            )
        return region_outputs(result, e, tolerance)
    if e.kind in ("polyline", "rectangle"):
        vertices = e.vertices()
        closed = e.kind == "rectangle" or e.data.get("closed", False)
        edges = list(itertools.pairwise(vertices + ([vertices[0]] if closed else [])))
        cuts = []
        for index, (a, b) in enumerate(edges):
            part = Entity("part", "line", data={"points": [a, b]})
            for cutter in curve_parts(boundary):
                for p in finite_intersections(part, cutter):
                    t = index + curve_parameter(part, p)
                    if not any(abs(t - u) < 1e-8 for u in cuts):
                        cuts.append(t)
        extent = len(edges)
        if not cuts:
            raise ValueError("No path crossing for Trim.")
        pick_t = min(
            range(extent), key=lambda i: LineString(edges[i]).distance(Point(pick))
        )
        a, b = edges[pick_t]
        p = Entity("pick", "line", data={"points": [a, b]})
        pick_t += max(0, min(1, curve_parameter(p, pick)))
        if closed:
            cuts = sorted(t % extent for t in cuts)
            if len(cuts) < 2:
                raise ValueError("Closed path trim needs two crossings.")
            intervals = list(itertools.pairwise(cuts + [cuts[0] + extent]))
            t = pick_t + (extent if pick_t < cuts[0] else 0)
        else:
            intervals = list(itertools.pairwise(sorted({0.0, float(extent), *cuts})))
            t = pick_t
        remove = next(((a, b) for a, b in intervals if a - 1e-9 <= t <= b + 1e-9), None)
        if remove is None:
            raise ValueError("Pick a removable path portion.")
        a, b = remove
        ranges = (
            [(b, a + extent)]
            if closed
            else ([(0, a)] if a > 1e-9 else [])
            + ([(b, extent)] if b < extent - 1e-9 else [])
        )

        def at(t):
            index = min(extent - 1, int(t % extent))
            fraction = t % extent - index
            if not closed and abs(t - extent) < 1e-9:
                return vertices[-1]
            return add(edges[index][0], mul(sub(*edges[index][::-1]), fraction))

        result = []
        for lo, hi in ranges:
            points = [
                at(lo),
                *[at(i) for i in range(math.floor(lo) + 1, math.ceil(hi))],
                at(hi),
            ]
            points = [
                p
                for i, p in enumerate(points)
                if i == 0 or distance(p, points[i - 1]) > EPS
            ]
            result.append(
                Entity(
                    "trim",
                    "polyline",
                    data={"points": points, "closed": False},
                    layer=e.layer,
                    construction=e.construction,
                ).validate()
            )
        return result
    return trim_curve_parts(e, boundary, pick)


def extend_path(e, boundary, pick, limit=4.0):
    if not 0 < limit <= 32:
        raise ValueError("Bezier extension search limit must be in (0,32].")
    if (
        e.kind in ("region", "rectangle", "circle")
        or e.kind == "polyline"
        and e.data.get("closed")
        or e.kind == "ellipse"
        and abs(e.data.get("sweep", 360)) >= 360 - EPS
    ):
        raise ValueError(
            "Closed geometry has no endpoint to extend; trim or use a Boolean."
        )
    if e.kind == "polyline":
        vertices = e.vertices()
        first = distance(pick, vertices[0]) < distance(pick, vertices[-1])
        edge = Entity(
            "edge", "line", data={"points": vertices[:2] if first else vertices[-2:]}
        )
        candidate = extend_path(edge, boundary, pick, limit)[0]
        result = copy.deepcopy(e)
        index = 0 if first else -1
        result.data["points"][index] = e.local(candidate.vertices()[index])
        return [result.validate()]
    if e.kind not in ("line", "arc", "ellipse", "bezier"):
        raise ValueError("Unsupported extension target.")
    f = parameter_curve(e)
    first = distance(pick, f(0)[0]) < distance(pick, f(1)[0])
    support = copy.deepcopy(e)
    lo, hi = 0.0, 1.0
    if e.kind == "line":
        candidates = []
        for cutter in curve_parts(boundary):
            if cutter.kind in ("line", "circle", "arc"):
                try:
                    from .cad_operations import curve_tolerance, intersections, on_curve
                except ImportError:
                    from cad_operations import curve_tolerance, intersections, on_curve
                candidates.extend(
                    p
                    for p in intersections(e, cutter)
                    if on_curve(cutter, p, curve_tolerance(cutter, p))
                )
            else:
                try:
                    from .cad_curves import curve_intersections
                except ImportError:
                    from cad_curves import curve_intersections
                try:
                    from .cad_operations import curve_tolerance, on_curve
                except ImportError:
                    from cad_operations import curve_tolerance, on_curve
                candidates.extend(
                    p
                    for p in curve_intersections(cutter, e)
                    if on_curve(cutter, p, curve_tolerance(cutter, p))
                )
        times = [curve_parameter(e, p) for p in candidates]
    else:
        if e.kind == "bezier":
            lo, hi = -limit, 1 + limit
            support = portion(e, lo, hi)
        else:
            support.data["start"] = 0
            support.data["sweep"] = 360
        candidates = [
            p
            for cutter in curve_parts(boundary)
            for p in finite_intersections(support, cutter)
        ]
        times = [curve_parameter(e, p, lo, hi) for p in candidates]
        if e.kind in ("arc", "ellipse"):
            revolution = 360 / abs(e.data["sweep"])
            times = [t - revolution if first else t for t in times]
    times = (
        [t for t in times if t < -1e-8] if first else [t for t in times if t > 1 + 1e-8]
    )
    if not times:
        raise ValueError(
            "No intersection beyond selected endpoint within the extension search."
        )
    t = max(times) if first else min(times)
    return [portion(e, t, 1) if first else portion(e, 0, t)]
