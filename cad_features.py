    # Closed circles/ellipses remain whole tangent reference boundaries.
    return e


def parallel_round(a, b, radius, pick):
    av, bv = a.vertices(), b.vertices()
    u = unit(sub(av[1], av[0]))
    normal = rotate(u, 90)
    signed = sum(x * y for x, y in zip(sub(bv[0], av[0]), normal))
    if abs(signed) <= EPS or abs(abs(signed) - 2 * radius) > 1e-7:
        raise ValueError("Parallel round radius must be half the line separation.")
    positions = [
        [sum(x * y for x, y in zip(sub(p, av[0]), u)) for p in ends]
        for ends in (av, bv)
    ]
    lo, hi = max(min(v) for v in positions), min(max(v) for v in positions)
    if hi - lo <= EPS:
        raise ValueError("Parallel legs need overlapping finite extents.")
    t = (
        hi
        if pick is None
        else max(lo, min(hi, sum(x * y for x, y in zip(sub(pick, av[0]), u))))
    )
    p = add(av[0], mul(u, t))
    q = add(p, mul(normal, signed))
    centre = mul(add(p, q), 0.5)
    keeps = [
        max(range(2), key=lambda i: distance(ends[i], contact))
        for ends, contact in [(av, p), (bv, q)]
    ]
    tail_a = unit(sub(av[keeps[0]], p))
    sweep = (
        180
        if sum(x * y for x, y in zip(rotate(sub(p, centre), 90), tail_a)) < 0
        else -180
    )
    tail_b = unit(sub(bv[keeps[1]], q))
    if (
        sum(
            x * y
            for x, y in zip(
                mul(rotate(sub(q, centre), 90), 1 if sweep > 0 else -1), tail_b
            )
        )
        <= 0
    ):
        raise ValueError("Parallel legs must retain tails on the same side.")
    for e, ends, contact, keep in [(a, av, p, keeps[0]), (b, bv, q, keeps[1])]:
        e.x, e.y, e.angle = *ends[keep], 0
        e.data = {"points": [(0, 0), sub(contact, ends[keep])]}
    return Entity(
        "connector",
        "arc",
        *centre,
        layer=a.layer,
        data={"radius": radius, "start": angle(sub(p, centre)), "sweep": sweep},
    )


def _local_curve_fillet(a, b, radius, pick=None):
    """Solve equal-radius offset supports and retain G1-connected finite tails.

    Analytic primitive candidates or bounded multistart refinement; not a global
    existence proof. Closed input curves remain whole, open inputs are trimmed.
    """
    radius = positive(radius)
    fa, fb = parameter_curve(a), parameter_curve(b)
    closed_a = (
        (
            a.kind == "circle"
            or a.kind == "ellipse"
            and abs(a.data.get("sweep", 360)) >= 360 - EPS
        )
        or a.kind == "arc"
        and abs(a.data["sweep"]) == 360
    )
    closed_b = (
        (
            b.kind == "circle"
            or b.kind == "ellipse"
            and abs(b.data.get("sweep", 360)) >= 360 - EPS
        )
        or b.kind == "arc"
        and abs(b.data["sweep"]) == 360
    )
    if pick is None:
        pick = mul(add(fa(0.5)[0], fb(0.5)[0]), 0.5)
    candidates = []
    scale = max(
        EPS * 100,
        radius,
        *(abs(e.bounds()[i + 2] - e.bounds()[i]) for e in (a, b) for i in (0, 1)),
    )

    def centre(sample, t, side):
        p, v = sample(t)
        return add(p, mul(rotate(unit(v), 90), side * radius))

    def primitive(e, side):
        result = copy.deepcopy(e)
        if e.kind == "line":
            _, v = parameter_curve(e)(0)
            result.x, result.y = add(
                (e.x, e.y), mul(rotate(unit(v), 90), side * radius)
            )
        else:
            r = (
                e.data["radius"]
                - side * (1 if e.data.get("sweep", 360) > 0 else -1) * radius
            )
            if abs(r) <= EPS:
                return None
            result.kind, result.data = "circle", {"radius": abs(r)}
        return result

    def parameter(e, c, side):
        if e.kind == "line":
            p, v = parameter_curve(e)(0)
            q = sub(c, mul(rotate(unit(v), 90), side * radius))
            return sum(x * y for x, y in zip(sub(q, p), v)) / sum(x * x for x in v)
        r = (
            e.data["radius"]
            - side * (1 if e.data.get("sweep", 360) > 0 else -1) * radius
        )
        q = mul(sub(c, (e.x, e.y)), 1 if r > 0 else -1)
        start = e.angle + e.data.get("start", 0)
        sweep = e.data.get("sweep", 360)
        return ((angle(q) - start) * (1 if sweep > 0 else -1) % 360) / abs(sweep)

    for sa, sb in itertools.product((-1, 1), repeat=2):
        parameters = []
        if a.kind in ("line", "circle", "arc") and b.kind in ("line", "circle", "arc"):
            pa, pb = primitive(a, sa), primitive(b, sb)
            if pa is not None and pb is not None:
                parameters = [
                    (parameter(a, c, sa), parameter(b, c, sb))
                    for c in intersections(pa, pb)
                ]
        else:
            for seed in itertools.product((0.02, 0.25, 0.5, 0.75, 0.98), repeat=2):
                try:
                    solve = least_squares(
                        lambda z, sa=sa, sb=sb: [
                            v / scale
                            for v in sub(centre(fa, z[0], sa), centre(fb, z[1], sb))
                        ],
                        seed,
                        bounds=([0, 0], [1, 1]),
                        xtol=1e-12,
                        ftol=1e-12,
                        gtol=1e-12,
                        max_nfev=80,
                    )
                    parameters.append(tuple(solve.x))
                except ValueError:
                    continue
        for ta, tb in parameters:
            if not -1e-9 <= ta <= 1 + 1e-9 or not -1e-9 <= tb <= 1 + 1e-9:
                continue
            ta, tb = max(0, min(1, ta)), max(0, min(1, tb))
            try:
                ca, cb = centre(fa, ta, sa), centre(fb, tb, sb)
                if distance(ca, cb) > max(EPS, *(64 * math.ulp(v) for v in (*ca, *cb))):
                    continue
                p, va = fa(ta)
                q, vb = fb(tb)
                if distance(p, q) <= EPS:
                    continue
                start = angle(sub(p, ca))
                sweep = (angle(sub(q, ca)) - start + 180) % 360 - 180
                if abs(sweep) <= EPS:
                    continue
                direction = 1 if sweep > 0 else -1
                keep_a = (
                    sum(
                        x * y
                        for x, y in zip(mul(rotate(sub(p, ca), 90), direction), va)
                    )
                    > 0
                )
                keep_b = (
                    sum(
                        x * y
                        for x, y in zip(mul(rotate(sub(q, ca), 90), direction), vb)
                    )
                    < 0
                )
                aa, bb = copy.deepcopy(a), copy.deepcopy(b)
                if not closed_a:
                    trim_contact(aa, ta, keep_a)
                if not closed_b:
                    trim_contact(bb, tb, keep_b)
                connector = Entity(
                    "connector",
                    "arc",
                    *ca,
                    layer=a.layer,
                    data={"radius": radius, "start": start, "sweep": sweep},
                )
                score = distance(p, pick) + distance(q, pick) + distance(ca, pick)
                candidates.append((score, aa, bb, connector))
            except ValueError:
                continue
    if not candidates:
        raise ValueError(
            "No verified finite curve fillet found; change radius/pick or source geometry."
        )
    _, aa, bb, connector = min(candidates, key=lambda item: item[0])
    return aa, bb, connector


def round_polyline(e, radius, tolerance=0.01, vertex=None):
    radius, tolerance = positive(radius), positive(tolerance)
    if e.kind not in ("polyline", "rectangle"):
        raise ValueError("Round polyline requires a polyline or rectangle.")
    points = e.vertices()
    closed = e.kind == "rectangle" or e.data.get("closed", False)
    if closed and distance(points[0], points[-1]) <= EPS:
        points.pop()
    if len(points) > 2000:
        raise ValueError("Rounding supports at most 2000 input vertices.")
    indices = list(range(len(points))) if closed else list(range(1, len(points) - 1))
    if vertex is not None:
        if (
            isinstance(vertex, bool)
            or int(vertex) != vertex
            or int(vertex) not in indices
        ):
            raise ValueError("Choose an interior vertex, or a closed-path vertex.")
        indices = [int(vertex)]
    if not indices:
        raise ValueError("Path has no roundable interior vertex.")
    corners = {}
    for i in indices:
        a, p, b = points[i - 1], points[i], points[(i + 1) % len(points)]
        u, v = unit(sub(a, p)), unit(sub(b, p))
        theta = math.acos(max(-1, min(1, sum(x * y for x, y in zip(u, v)))))
        if math.pi - theta < 1e-8:
            continue
        if theta < 1e-8:
            raise ValueError("Cannot round a reversing vertex.")
        setback = radius / math.tan(theta / 2)
        first, last = add(p, mul(u, setback)), add(p, mul(v, setback))
        c = add(p, mul(unit(add(u, v)), radius / math.sin(theta / 2)))
        start = angle(sub(first, c))
        sweep = (angle(sub(last, c)) - start + 180) % 360 - 180
        corners[i] = (setback, first, last, c, start, sweep)
    pairs = list(
        zip(range(len(points)), list(range(1, len(points))) + ([0] if closed else []))
    )
    for i, j in pairs:
        if (
            corners.get(i, (0,))[0] + corners.get(j, (0,))[0]
            >= distance(points[i], points[j]) - EPS
        ):
            raise ValueError("Rounded corners overlap or consume an entire edge.")
    result = []
    for i, p in enumerate(points):
        if i not in corners:
            result.append(p)
            continue
        _, first, last, c, start, sweep = corners[i]
        step = 2 * math.acos(max(-1, min(1, 1 - min(tolerance / radius, 1))))
        n = max(1, math.ceil(abs(math.radians(sweep)) / step))
        if len(result) + n + 1 > 8192:
            raise ValueError("Rounded path exceeds 8192 vertices; increase tolerance.")
        result.extend(
            add(c, polar(radius, start + sweep * j / n)) for j in range(n + 1)
        )
        result[-n - 1], result[-1] = first, last
    simple_polyline(result, closed)
    out = copy.deepcopy(e)
    out.kind, out.x, out.y, out.angle = "polyline", 0, 0, 0
    out.data = {"points": result, "closed": closed}
    return out


def cleaned_offset(
    e, amount, tolerance=0.01, join="round", as_regions=False, allow_empty=False
):
    """GEOS planar region/line offset; return all boundary components, including holes."""
    from shapely import make_valid
    from shapely.geometry import LineString, Polygon

    tolerance = positive(tolerance)
    if join not in ("round", "mitre", "bevel"):
        raise ValueError("Offset join must be round, mitre or bevel.")
    closed = (
        e.kind in ("rectangle", "circle", "region")
        or e.kind == "ellipse"
        and abs(e.data.get("sweep", 360)) >= 360 - EPS
        or e.kind == "polyline"
        and e.data.get("closed", False)
    )
    if e.kind == "region":
        points = e.paths()[0][:-1]
    elif e.kind in ("ellipse", "bezier"):
        try:
            from .cad_curves import offset_curve
        except ImportError:
            from cad_curves import offset_curve
        source = offset_curve(copy.deepcopy(e), 0, tolerance / 2)
        points = source.vertices()
    elif e.kind == "circle":
        r = e.data["radius"]
        n = max(
            16, math.ceil(math.pi / math.acos(max(-1, 1 - min(tolerance / (2 * r), 1))))
        )
        if n > 8192:
            raise ValueError("Cleanup source sampling budget exceeded.")
        points = [e.world(polar(r, 360 * i / n)) for i in range(n)]
    elif e.kind in ("line", "polyline", "rectangle"):
        points = e.vertices()
    else:
        raise ValueError("Clean offset supports planar paths, circles and ellipses.")
    step = 2 * math.acos(
        max(-1, 1 - min(tolerance / (2 * max(abs(amount), tolerance)), 1))
    )
    quadrants = max(1, math.ceil((math.pi / 2) / step))
    if quadrants > 2048:
        raise ValueError("Cleanup arc sampling budget exceeded.")
    if closed:
        region = make_valid(
            Polygon(
                points, [p[:-1] for p in e.paths()[1:]] if e.kind == "region" else []
            )
        )
        if region.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Closed path does not define an area.")
        geometry = region.buffer(amount, quad_segs=quadrants, join_style=join)
    else:
        geometry = LineString(points).offset_curve(
            amount, quad_segs=quadrants, join_style=join
        )
    if geometry.is_empty:
        if allow_empty:
            return []
        raise ValueError("Offset removes the entire path/region.")
    if as_regions and closed:
        components = (
            [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
        )
        if len(components) > 128:
            raise ValueError("Clean offset exceeds 128 regions.")
        components.sort(key=lambda g: e.local(g.representative_point().coords[0]))
        if (
            sum(
                len(g.exterior.coords) + sum(len(r.coords) for r in g.interiors)
                for g in components
            )
            > 10000
        ):
            raise ValueError("Clean offset exceeds 10000 vertices.")
        return [
            Entity(
                "clean",
                "region",
                x=e.x,
                y=e.y,
                angle=e.angle,
                layer=e.layer,
                data={
                    "rings": [
                        [e.local(p) for p in list(g.exterior.coords)[:-1]],
                        *[
                            [e.local(p) for p in list(r.coords)[:-1]]
                            for r in g.interiors
                        ],
                    ],
                    "hatch": e.data.get("hatch", "solid"),
                    "spacing": e.data.get("spacing", 2),
                    "hatch_angle": e.data.get("hatch_angle", 45),
                    "cleanup": {"role": "region", "join": join, "tolerance": tolerance},
                    **(
                        {"hatch_definition": copy.deepcopy(e.data["hatch_definition"])}
                        if "hatch_definition" in e.data
                        else {}
                    ),
                },
            ).validate()
            for g in components
        ]
    result = []

    def extract(g):
        if g.geom_type == "Polygon":
            for role, ring in [
                ("outer", g.exterior),
                *[("hole", r) for r in g.interiors],
            ]:
                coordinates = list(ring.coords)[:-1]
                result.append((coordinates, True, role))
        elif g.geom_type == "LineString":
            result.append((list(g.coords), False, "path"))
        else:
            for child in g.geoms:
                extract(child)

    extract(geometry)
    if len(result) > 128 or sum(len(p) for p, _, _ in result) > 10000:
        raise ValueError("Clean offset exceeds component/vertex budgets.")
    result.sort(
        key=lambda component: (
            component[2],
            min(e.local(p)[0] for p in component[0]),
            min(e.local(p)[1] for p in component[0]),
        )
    )
    return [
        Entity(
            "clean",
            "polyline",
            layer=e.layer,
            data={
                "points": p,
                "closed": closed,
                "cleanup": {"role": role, "join": join, "tolerance": tolerance},
            },
        ).validate()
        for p, closed, role in result
    ]


def curve_fillet(a, b, radius, pick=None):
    """Solve in a shared local frame to avoid cancelling large world origins."""
    anchor = (a.x + (b.x - a.x) / 2, a.y + (b.y - a.y) / 2)
    aa, bb = copy.deepcopy(a), copy.deepcopy(b)
    for e in (aa, bb):
        if e.kind in ("line", "bezier"):
            points = [sub(p, anchor) for p in e.vertices()]
            e.x = e.y = e.angle = 0
            e.data["points"] = points
        else:
            e.x, e.y = sub((e.x, e.y), anchor)
    result = _local_curve_fillet(
        aa, bb, radius, sub(pick, anchor) if pick is not None else None
    )
    for e in result:
        e.x, e.y = add((e.x, e.y), anchor)
    return result
