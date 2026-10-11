"""Finite edge decomposition and reference-based geometric drafting snaps."""

import copy
import itertools
import math

try:
    from .cad_curves import closest_point, curve_contacts
    from .cad_geometry import EPS, Entity, add, distance, mul, rotate, sub, unit
    from .cad_operations import curve_tolerance, on_curve
except ImportError:
    from cad_curves import closest_point, curve_contacts
    from cad_geometry import EPS, Entity, add, distance, mul, rotate, sub, unit
    from cad_operations import curve_tolerance, on_curve


def curve_parts(entity):
    """Yield analytic supports without changing or exploding the source entity."""
    if entity.kind in ("line", "circle", "arc", "ellipse", "bezier"):
        yield entity
    elif entity.kind == "region":
        for ring in entity.paths():
            for a, b in itertools.pairwise(ring):
                yield Entity("_snap_edge", "line", data={"points": [a, b]})
    elif entity.kind in ("rectangle", "polyline"):
        vertices = entity.vertices()
        pairs = list(itertools.pairwise(vertices))
        if entity.kind == "rectangle" or entity.data.get("closed"):
            pairs.append((vertices[-1], vertices[0]))
        for a, b in pairs:
            if distance(a, b) > EPS:
                yield Entity(
                    "_snap_edge",
                    "line",
                    x=a[0],
                    y=a[1],
                    data={"points": [(0, 0), sub(b, a)]},
                )


def reference_points(entity, reference, *, perpendicular=False, tangent=False):
    """Return (point, mode) candidates for a segment starting at reference.

    Perpendicular feet are on finite straight edges or circular normals.
    Tangents require a strictly external reference to a circle or arc. These
    are point placements, not saved driving constraints or extended supports.
    """
    result = []
    for part in curve_parts(entity):
        candidates = []
        if part.kind in ("ellipse", "bezier"):
            result.extend(
                curve_contacts(
                    part, reference, perpendicular=perpendicular, tangent=tangent
                )
            )
            continue
        if part.kind == "line":
            if perpendicular:
                a, b = part.vertices()
                direction = unit(sub(b, a))
                along = sum(x * y for x, y in zip(sub(reference, a), direction))
                candidates.append((add(a, mul(direction, along)), "Perpendicular"))
        else:
            centre = part.x, part.y
            radius = part.data["radius"]
            separation = distance(reference, centre)
            tolerance = curve_tolerance(part, reference)
            if separation <= tolerance:
                continue  # No unique circular normal at the centre.
            direction = mul(sub(reference, centre), 1 / separation)
            if perpendicular:
                candidates.extend(
                    (add(centre, mul(direction, sign * radius)), "Perpendicular")
                    for sign in (-1, 1)
                )
            if tangent and separation > radius + tolerance:
                ratio = radius / separation
                normal = rotate(direction, 90)
                height = math.sqrt(max(0, (1 - ratio) * (1 + ratio)))
                candidates.extend(
                    (
                        add(
                            centre,
                            mul(
                                add(mul(direction, ratio), mul(normal, sign * height)),
                                radius,
                            ),
                        ),
                        "Tangent",
                    )
                    for sign in (-1, 1)
                )
        for point, mode in candidates:
            tolerance = curve_tolerance(part, point)
            if distance(point, reference) > tolerance and on_curve(
                part, point, tolerance
            ):
                result.append((point, mode))
    return result


def nearest_point(entity, point):
    """Closest actual finite curve point; independent of rendering resolution."""
    if entity.kind in ("ellipse", "bezier"):
        return closest_point(entity, point)
    if entity.kind == "line":
        a, b = entity.vertices()
        v = sub(b, a)
        t = max(
            0,
            min(
                1, sum(x * y for x, y in zip(sub(point, a), v)) / sum(x * x for x in v)
            ),
        )
        return add(a, mul(v, t))
    centre = entity.x, entity.y
    delta = sub(point, centre)
    if distance(point, centre) <= EPS:
        return (
            entity.world((entity.data["radius"], 0))
            if entity.kind == "circle"
            else entity.handles()[1]
        )
    projected = add(centre, mul(unit(delta), entity.data["radius"]))
    if on_curve(entity, projected, curve_tolerance(entity, projected)):
        return projected
    return min(entity.handles()[1:], key=lambda q: distance(q, point))


def extension_part(e, cursor, tolerance):
    """A local segment of a line's infinite support, or an arc's full circle."""
    if e.kind == "line":
        a, b = e.vertices()
        v = sub(b, a)
        length = distance(a, b)
        if length <= EPS:
            return None
        t = sum(x * y for x, y in zip(sub(cursor, a), v)) / length**2
        q = add(a, mul(v, t))
        if distance(q, cursor) > tolerance or 0 <= t <= 1:
            return None
        out = copy.deepcopy(e)
        out.x = out.y = out.angle = 0
        delta = mul(v, 2 * tolerance / length)
        out.data = {"points": [sub(q, delta), add(q, delta)]}
        return out
    if e.kind == "arc":
        out = copy.deepcopy(e)
        out.kind = "circle"
        out.data = {"radius": e.data["radius"]}
        return (
            out
            if not on_curve(e, cursor, tolerance) and on_curve(out, cursor, tolerance)
            else None
        )
    return None


try:
    from .cad_geometry import EPS, add, mul, sub
    from .cad_operations import on_curve
except ImportError:
    from cad_geometry import EPS, add, mul, sub
    from cad_operations import on_curve
