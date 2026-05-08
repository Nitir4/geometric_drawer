    if abs(den) <= uncertainty:
        # Exact rational arithmetic on the represented binary inputs is cheap
        # for these few values, and avoids a fixed decimal precision assumption.
        from fractions import Fraction

        aa, bb, cc, dd = [[Fraction(float(v)) for v in p] for p in (a, b, c, d)]
        rr = [bb[i] - aa[i] for i in (0, 1)]
        ss = [dd[i] - cc[i] for i in (0, 1)]
        qq = [cc[i] - aa[i] for i in (0, 1)]
        determinant = rr[0] * ss[1] - rr[1] * ss[0]
        if determinant == 0:
            raise ValueError("Lines are parallel or coincident.")
        t = (qq[0] * ss[1] - qq[1] * ss[0]) / determinant
        u = (qq[0] * rr[1] - qq[1] * rr[0]) / determinant
        point = tuple(float(aa[i] + rr[i] * t) for i in (0, 1))
        return point, float(t), float(u)
    t = math.fsum((q[0] * s[1], -q[1] * s[0])) / den
    u = math.fsum((q[0] * r[1], -q[1] * r[0])) / den
    return add(a, mul(r, t)), t, u


def segment_distance(p, a, b):
    v = sub(b, a)
    n = v[0] ** 2 + v[1] ** 2
    t = max(0, min(1, sum(x * y for x, y in zip(sub(p, a), v)) / n)) if n else 0
    return distance(p, add(a, mul(v, t)))


@dataclass
class Entity:
    id: str
    kind: str
    x: float = 0
    y: float = 0
    angle: float = 0
    layer: str = "0"
    data: dict = field(default_factory=dict)
    construction: bool = False

    def validate(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unsupported entity: {self.kind}")
        if (
            not isinstance(self.id, str)
            or not self.id
            or len(self.id) > 120
            or not isinstance(self.layer, str)
            or not self.layer
        ):
            raise ValueError("Entity ID and layer must be present.")
        self.x, self.y, self.angle = finite(self.x), finite(self.y), finite(self.angle)
        d = self.data
        if "circuit_wire" in d:
            raise ValueError("Circuit metadata is unsupported in geometric CAD.")
        if type(self.construction) is not bool:
            raise ValueError("Construction flag must be a boolean.")
        required = {
            "point": (),
            "line": ("points",),
            "polyline": ("points",),
            "region": ("rings",),
            "rectangle": ("width", "height"),
            "circle": ("radius",),
            "arc": ("radius", "start", "sweep"),
            "ellipse": ("rx", "ry"),
            "bezier": ("points",),
            "text": ("text", "height"),
            "dimension": ("points", "offset"),
            "radial_dimension": ("radius",),
            "angular_dimension": ("start", "sweep", "radius"),
        }[self.kind]
        if any(k not in d for k in required):
            raise ValueError(f"{self.kind} requires {', '.join(required)}.")
        for k in ("width", "height", "radius", "rx", "ry", "text_height"):
            if k in d:
                d[k] = positive(d[k])
        for k in ("start", "sweep", "offset"):
            if k in d:
                d[k] = finite(d[k])
        if "sweep" in d and not EPS < abs(d["sweep"]) <= 360:
            raise ValueError("Arc/angle sweep must be nonzero and within ±360 degrees.")
        if "points" in d:
            d["points"] = [tuple(finite(v) for v in p) for p in d["points"]]
            if any(len(p) != 2 for p in d["points"]):
                raise ValueError("Each vertex must have two coordinates.")
            n = len(d["points"])
            if (
                n > 10000
                or n < 2
                or (self.kind in ("line", "dimension") and n != 2)
                or (self.kind == "bezier" and n != 4)
            ):
                raise ValueError(
                    "Line/dimension needs 2 points; Bezier needs 4; polyline needs 2–10000."
                )
            if self.kind in ("line", "dimension") and distance(*d["points"]) <= EPS:
                raise ValueError("Endpoints must differ.")
        if self.kind == "text" and (
            not isinstance(d["text"], str) or not d["text"] or len(d["text"]) > 10000
        ):
            raise ValueError("Text must contain 1–10000 characters.")
        info = d.get("offset_approximation")
        if "offset_approximation" in d:
            if (
                self.kind != "polyline"
                or not isinstance(info, dict)
                or info.get("method") != "bounded-normal-chords"
                or not {"distance", "tolerance"} <= info.keys()
            ):
                raise ValueError("Invalid offset approximation metadata.")
            info["distance"] = finite(info["distance"])
            info["tolerance"] = positive(info["tolerance"])
        if self.kind == "region":
            try:
                from .cad_regions import validate_region
            except ImportError:
                from cad_regions import validate_region
            validate_region(self)
        return self

    def world(self, p):
        return add((self.x, self.y), rotate(p, self.angle))

    def local(self, p):
        return rotate(sub(p, (self.x, self.y)), -self.angle)

    def vertices(self):
        d = self.data
        if self.kind == "region":
            return [self.world(p) for ring in d["rings"] for p in ring]
        if self.kind == "rectangle":
            w, h = d["width"], d["height"]
            points = [(0, 0), (w, 0), (w, h), (0, h)]
        else:
            points = d.get("points", [(0, 0)])
        return [self.world(p) for p in points]

    def paths(self, resolution=128):
        """Display tessellation only; analytic curves stay analytic in the model."""
        d, kind = self.data, self.kind
        if kind == "region":
            return [[self.world(p) for p in ring + [ring[0]]] for ring in d["rings"]]
        if kind in ("point", "text"):
            return []
        if kind in ("line", "polyline", "rectangle"):
            p = self.vertices()
            if kind == "rectangle" or d.get("closed"):
                p = p + [p[0]]
            return [p]
        if kind in ("circle", "arc", "ellipse", "angular_dimension"):
            start = d.get("start", 0)
            sweep = d.get("sweep", 360)
            n = max(16, int(resolution * abs(sweep) / 360))
            rx, ry = (
                (d["rx"], d["ry"]) if kind == "ellipse" else (d["radius"], d["radius"])
            )
            p = [
                self.world(
                    (
                        rx * math.cos(math.radians(start + sweep * i / n)),
                        ry * math.sin(math.radians(start + sweep * i / n)),
                    )
                )
                for i in range(n + 1)
            ]
            if kind == "angular_dimension":
                return [p, [(self.x, self.y), p[0]], [(self.x, self.y), p[-1]]]
            return [p]
        if kind == "bezier":
            p = self.vertices()
            return [
                [
                    tuple(
                        sum(
                            (1 - t) ** (3 - i) * t**i * (1, 3, 3, 1)[i] * p[i][j]
                            for i in range(4)
                        )
                        for j in (0, 1)
                    )
                    for t in [i / resolution for i in range(resolution + 1)]
                ]
            ]
        if kind == "dimension":
            a, b = self.vertices()
            normal = rotate(unit(sub(b, a)), 90)
            v = mul(normal, d["offset"])
            return [[a, add(a, v)], [b, add(b, v)], [add(a, v), add(b, v)]]
        if kind == "radial_dimension":
            return [[(self.x, self.y), self.world((d["radius"], 0))]]
        return []

    def label(self):
        if self.kind == "text":
            return (self.x, self.y), self.data["text"], self.data["height"]
        if self.kind == "dimension":
            a, b = self.paths()[-1]
            return (
                mul(add(a, b), 0.5),
                f"{distance(*self.vertices()):.3f}",
                self.data.get("text_height", 2.5),
            )
        if self.kind == "radial_dimension":
            return (
                self.world(
                    (self.data["radius"] * 0.6, self.data.get("text_height", 2.5) * 0.6)
                ),
                f"R{self.data['radius']:.3f}",
                self.data.get("text_height", 2.5),
            )
        if self.kind == "angular_dimension":
            return (
                self.world(
                    polar(
                        self.data["radius"] * 1.15,
                        self.data["start"] + self.data["sweep"] / 2,
                    )
                ),
                f"{abs(self.data['sweep']):.2f}°",
                self.data.get("text_height", 2.5),
            )
        return None

    def handles(self):
        if self.kind in (
            "line",
            "polyline",
            "region",
            "rectangle",
            "bezier",
            "dimension",
        ):
            return self.vertices()
        if self.kind in ("circle", "ellipse", "radial_dimension"):
            return (
                [
                    (self.x, self.y),
                    self.world((self.data.get("radius", self.data.get("rx")), 0)),
                ]
                + ([self.world((0, self.data["ry"]))] if self.kind == "ellipse" else [])
                + (
                    self.paths(1)[0][:: len(self.paths(1)[0]) - 1]
                    if self.kind == "ellipse"
                    and abs(self.data.get("sweep", 360)) < 360 - EPS
                    else []
                )
            )
        if self.kind in ("arc", "angular_dimension"):
            return [
                (self.x, self.y),
                self.world(polar(self.data["radius"], self.data["start"])),
                self.world(
                    polar(self.data["radius"], self.data["start"] + self.data["sweep"])
                ),
            ]
        return [(self.x, self.y)]

    def snap_points(self):
        p = self.handles()
        if self.kind == "ellipse" and abs(self.data.get("sweep", 360)) < 360 - EPS:
            d = self.data
            angles = [d.get("start", 0), d.get("start", 0) + d["sweep"]]
            for t in (0, 90, 180, 270):
                if (
                    (t - d.get("start", 0)) * (1 if d["sweep"] > 0 else -1)
                ) % 360 <= abs(d["sweep"]) + EPS:
                    angles.append(t)
            return [
                (self.x, self.y),
                *[
                    self.world(
                        (
                            d["rx"] * math.cos(math.radians(t)),
                            d["ry"] * math.sin(math.radians(t)),
                        )
                    )
                    for t in angles
                ],
            ]
        if self.kind == "bezier":
            # Control grips stay editable, but they are not points on the curve.
            vertices = self.vertices()
            return [
                vertices[0],
                vertices[-1],
                tuple(
                    sum(v[i] * w for v, w in zip(vertices, (1, 3, 3, 1))) / 8
                    for i in (0, 1)
                ),
            ]
        if self.kind in ("line", "polyline", "rectangle"):
            p += [
                mul(add(a, b), 0.5)
                for a, b in zip(self.vertices(), self.vertices()[1:])
            ]
            if self.kind == "rectangle" or self.data.get("closed"):
                p += [mul(add(self.vertices()[-1], self.vertices()[0]), 0.5)]
        if self.kind in ("circle", "ellipse"):
            rx, ry = (
                self.data.get("radius", self.data.get("rx")),
                self.data.get("radius", self.data.get("ry")),
            )
            p += [self.world(v) for v in [(rx, 0), (-rx, 0), (0, ry), (0, -ry)]]
        return p

    def bounds(self):
        # Exact circular/elliptic extrema; arcs only include extrema on their sweep.
        if self.kind in ("circle", "arc", "ellipse"):
            d = self.data
            if self.kind == "ellipse":
                c, s = (
                    math.cos(math.radians(self.angle)),
                    math.sin(math.radians(self.angle)),
                )
                if abs(d.get("sweep", 360)) >= 360 - EPS:
                    hx = math.hypot(d["rx"] * c, d["ry"] * s)
                    hy = math.hypot(d["rx"] * s, d["ry"] * c)
                    return self.x - hx, self.y - hy, self.x + hx, self.y + hy
                start, sweep = d.get("start", 0), d.get("sweep", 360)
                critical = [
                    math.degrees(math.atan2(-d["ry"] * s, d["rx"] * c)),
                    math.degrees(math.atan2(d["ry"] * c, d["rx"] * s)),
                ]
                angles = [start, start + sweep]
                for t in [*critical, *[t + 180 for t in critical]]:
                    if ((t - start) * (1 if sweep > 0 else -1)) % 360 <= abs(
                        sweep
                    ) + EPS:
                        angles.append(t)
                p = [
                    self.world(
                        (
                            d["rx"] * math.cos(math.radians(t)),
                            d["ry"] * math.sin(math.radians(t)),
                        )
                    )
                    for t in angles
                ]
                return (
                    min(q[0] for q in p),
                    min(q[1] for q in p),
                    max(q[0] for q in p),
                    max(q[1] for q in p),
                )
            if self.kind == "circle":
                r = d["radius"]
                return self.x - r, self.y - r, self.x + r, self.y + r
            start, sweep = d["start"] + self.angle, d["sweep"]
            angles = [start, start + sweep]
            for a in (0, 90, 180, 270):
                delta = ((a - start) if sweep > 0 else (start - a)) % 360
                if delta <= abs(sweep) + EPS:
                    angles.append(a)
            p = [add((self.x, self.y), polar(d["radius"], a)) for a in angles]
        elif self.kind == "bezier":
            points = self.vertices()
            times = {0.0, 1.0}
            for axis in (0, 1):
                v = [q[axis] for q in points]
                a, b, c = (
                    -v[0] + 3 * v[1] - 3 * v[2] + v[3],
                    2 * (v[0] - 2 * v[1] + v[2]),
                    v[1] - v[0],
                )
                if abs(a) < EPS:
                    roots = [-c / b] if abs(b) > EPS else []
                else:
                    disc = b * b - 4 * a * c
                    roots = (
                        [
                            (-b + math.sqrt(disc)) / (2 * a),
                            (-b - math.sqrt(disc)) / (2 * a),
                        ]
                        if disc >= 0
                        else []
                    )
                times.update(t for t in roots if 0 < t < 1)
            p = [
                tuple(
                    sum(
                        (1 - t) ** (3 - i) * t**i * (1, 3, 3, 1)[i] * points[i][j]
                        for i in range(4)
                    )
                    for j in (0, 1)
                )
                for t in times
            ]
        else:
            p = [v for path in self.paths() for v in path] or [(self.x, self.y)]
            if self.label():
                pos, text, h = self.label()
                p += [
                    add(pos, rotate(v, self.angle))
                    for v in [
                        (0, -h * 0.25),
                        (len(text) * h * 0.8, -h * 0.25),
                        (len(text) * h * 0.8, h),
                        (0, h),
                    ]
                ]
        return (
            min(v[0] for v in p),
            min(v[1] for v in p),
            max(v[0] for v in p),
            max(v[1] for v in p),
        )

    def hit_distance(self, p):
        if self.kind == "region":
            try:
                from .cad_regions import contains
            except ImportError:
                from cad_regions import contains
            if contains(self, p):
                return 0
        if self.kind == "circle":
            return abs(distance(p, (self.x, self.y)) - self.data["radius"])
        if self.kind == "text":
            x, y = self.local(p)
            w, h = (
                len(self.data["text"]) * self.data["height"] * 0.7,
                self.data["height"],
            )
            return math.hypot(max(0, -x, x - w), max(0, -h * 0.25 - y, y - h))
        paths = self.paths()
        result = min(
            (
                segment_distance(p, a, b)
                for path in paths
                for a, b in itertools.pairwise(path)
            ),
            default=math.inf,
        )
        return (
            min(result, distance(p, (self.x, self.y)))
            if self.kind in ("point", "text")
            else result
        )

    def to_dict(self):
        return asdict(self)
