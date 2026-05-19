"""Compound planar regions, clipped hatch patterns and topology comparison."""

import math

from shapely.geometry import LineString, Point, Polygon


def polygon(e, local=False):
    rings = e.data["rings"]
    return Polygon(
        rings[0] if local else [e.world(p) for p in rings[0]],
        rings[1:] if local else [[e.world(p) for p in ring] for ring in rings[1:]],
    )


def validate_region(e):
    try:
        from .cad_geometry import EPS, finite, positive
    except ImportError:
        from cad_geometry import EPS, finite, positive
    rings = e.data.get("rings")
    if not isinstance(rings, list) or not 1 <= len(rings) <= 128:
        raise ValueError("Region needs an outer ring and up to 127 hole rings.")
    if sum(len(r) for r in rings) > 10000:
        raise ValueError("Region exceeds 10000 vertices.")
    result = []
    for ring in rings:
        points = [tuple(finite(v) for v in p) for p in ring]
        if any(len(p) != 2 for p in points):
            raise ValueError("Region vertices need X,Y.")
        if points and points[0] == points[-1]:
            points.pop()
        if len(points) < 3:
            raise ValueError("Region rings need at least three vertices.")
        result.append(points)
    e.data["rings"] = result
    e.data["fill"] = True
    shape = polygon(e, local=True)
    if not shape.is_valid or shape.is_empty or shape.area <= EPS**2:
        raise ValueError(
            "Region boundaries must be simple; holes must lie inside and not overlap."
        )
    hatch = e.data.setdefault("hatch", "solid")
    if hatch not in ("solid", "lines", "cross", "custom"):
        raise ValueError("Hatch must be solid, lines, cross or custom.")
    e.data["spacing"] = positive(e.data.get("spacing", 2))
    e.data["hatch_angle"] = finite(e.data.get("hatch_angle", 45))
    if hatch == "custom":
        definition = e.data.get("hatch_definition")
        if not isinstance(definition, list) or not 1 <= len(definition) <= 32:
            raise ValueError("Custom hatch needs 1–32 pattern families.")
        for line in definition:
            if (
                len(line) != 4
                or len(line[1]) != 2
                or len(line[2]) != 2
                or len(line[3]) > 128
            ):
                raise ValueError("Invalid hatch definition.")
            for value in [line[0], *line[1], *line[2], *line[3]]:
                finite(value)
            theta = math.radians(line[0])
            normal = (-math.sin(theta), math.cos(theta))
            if abs(sum(x * y for x, y in zip(normal, line[2]))) <= EPS:
                raise ValueError("Hatch family offset must separate parallel lines.")
            if line[3] and sum(abs(v) for v in line[3]) <= EPS:
                raise ValueError("Hatch dash cycle must be nonzero.")
        e.data["hatch_definition"] = [
            [
                float(a),
                tuple(map(float, base)),
                tuple(map(float, offset)),
                list(map(float, dashes)),
            ]
            for a, base, offset, dashes in definition
        ]
    return e


def definition(e, world=False):
    try:
        from .cad_geometry import rotate
    except ImportError:
        from cad_geometry import rotate
    if e.data["hatch"] == "solid":
        return []
    if e.data["hatch"] == "custom":
        lines = e.data["hatch_definition"]
    else:
        angles = [e.data["hatch_angle"]] + (
            [e.data["hatch_angle"] + 90] if e.data["hatch"] == "cross" else []
        )
        lines = [[a, (0, 0), rotate((0, e.data["spacing"]), a), []] for a in angles]
    return (
        [
            [a + e.angle, e.world(base), rotate(offset, e.angle), list(dashes)]
            for a, base, offset, dashes in lines
        ]
        if world
        else lines
    )


def hatch_segments(e, max_segments=20000):
    """Clip infinite hatch families against material, excluding every hole."""
    try:
        from .cad_geometry import EPS, add, mul, sub
    except ImportError:
        from cad_geometry import EPS, add, mul, sub
    shape = polygon(e, local=True)
    x0, y0, x1, y1 = shape.bounds
    corners = [(x, y) for x in (x0, x1) for y in (y0, y1)]
    # Resolve boundary-collinear hatch lines consistently after rotated DXF
    # round-trips. This ULP-sized margin affects pattern clipping only; stored
    # material boundaries and solid fills remain unchanged.
    clip_tolerance = max(1e-15, 32 * max(math.ulp(v) for v in shape.bounds))
    clip_shape = shape.buffer(clip_tolerance, join_style="mitre")
    result = []
    min_length = max(1e-15, 128 * math.ulp(max(x1 - x0, y1 - y0)), 4 * clip_tolerance)
    attempts = 0
    for degrees, base, offset, dashes in definition(e):
        theta = math.radians(degrees)
        u = (math.cos(theta), math.sin(theta))
        n = (-u[1], u[0])
        pitch = sum(x * y for x, y in zip(n, offset))
        projections = [
            sum(x * y for x, y in zip(sub(p, base), n)) / pitch for p in corners
        ]
        for index in range(
            math.floor(min(projections)) - 1, math.ceil(max(projections)) + 2
        ):
            attempts += 1
            if attempts > max_segments:
                raise ValueError("Hatch density exceeds 20000 lines; increase spacing.")
            origin = add(base, mul(offset, index))
            extent = [sum(x * y for x, y in zip(sub(p, origin), u)) for p in corners]
            lo, hi = min(extent) - 1, max(extent) + 1
            cut = clip_shape.intersection(
                LineString([add(origin, mul(u, lo)), add(origin, mul(u, hi))])
            )
            parts = (
                [cut]
                if cut.geom_type == "LineString"
                else list(cut.geoms)
                if hasattr(cut, "geoms")
                else []
            )
            for part in parts:
                if part.geom_type != "LineString" or part.is_empty:
                    continue
                first, last = part.coords[0], part.coords[-1]
                start, end = sorted(
                    sum(x * y for x, y in zip(sub(p, origin), u)) for p in (first, last)
                )
                if end - start <= min_length:
                    continue
                if not dashes:
                    result.append((e.world(first), e.world(last)))
                else:
                    cycle = sum(abs(v) for v in dashes)
                    cursor = math.floor(start / cycle) * cycle
                    steps = 0
                    while cursor < end:
                        for dash in dashes:
                            steps += 1
                            if steps > max_segments:
                                raise ValueError("Hatch dash budget exceeded.")
                            a, b = max(start, cursor), min(end, cursor + abs(dash))
                            if dash >= 0 and b >= a:
                                if dash == 0:
                                    b = min(end, a + max(EPS, e.data["spacing"] * 0.02))
                                if b - a > min_length:
                                    result.append(
                                        (
                                            e.world(add(origin, mul(u, a))),
                                            e.world(add(origin, mul(u, b))),
                                        )
                                    )
                            cursor += abs(dash)
                if len(result) > max_segments:
                    raise ValueError("Hatch segment budget exceeded.")
    return result


def triangles(e):
    from ezdxf.path import Path, triangulate

    paths = []
    for ring in e.data["rings"]:
        p = Path(e.world(ring[0]))
        for vertex in ring[1:]:
            p.line_to(e.world(vertex))
        p.close()
        paths.append(p)
    return [tuple((v.x, v.y) for v in triangle) for triangle in triangulate(paths)]


def contains(e, point):
    return polygon(e, local=True).covers(Point(e.local(point)))


def rings_from_paths(paths, style=0):
    """Recover nested polygon rings by containment parity, including islands."""
    if style not in (0, 1, 2):
        raise ValueError("Unsupported hatch island style.")
    rings = [list(p) for p in paths]
    if len(rings) > 128 or sum(len(r) for r in rings) > 10000:
        raise ValueError("Hatch exceeds boundary/vertex budgets.")
    polys = [Polygon(p) for p in rings]
    if any(not p.is_valid or p.is_empty for p in polys):
        raise ValueError("Invalid region boundary.")
    for i, first in enumerate(polys):
        for second in polys[i + 1 :]:
            if first.equals(second) or (
                first.intersects(second)
                and not first.contains(second)
                and not second.contains(first)
            ):
                raise ValueError("Hatch boundaries overlap or cross.")
    parents = []
    for i, p in enumerate(polys):
        containers = [
            j
            for j, q in enumerate(polys)
            if j != i and q.area > p.area and q.contains(p)
        ]
        parents.append(
            min(containers, key=lambda j: polys[j].area) if containers else None
        )

    def depth(i):
        return 0 if parents[i] is None else 1 + depth(parents[i])

    result = []
    for i in sorted(range(len(rings)), key=lambda i: -polys[i].area):
        if depth(i) % 2 == 0 and (style == 0 or depth(i) == 0):
            result.append(
                [
                    rings[i],
                    *[
                        rings[j]
                        for j in range(len(rings))
                        if parents[j] == i and style != 2
                    ],
                ]
            )
    return result
