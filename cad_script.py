            if len(positional) != n:
                raise ValueError(f"{cmd} requires {n} positional argument(s).")
            return positional

        if cmd == "PARAM":
            self.doc.set_parameter(
                ids()[0],
                take("expression", required=True),
                take("kind", "length"),
                units=take("units", self.doc.units),
            )
        elif cmd == "UNPARAM":
            self.doc.remove_parameter(ids()[0])
        elif cmd == "BIND":
            self.doc.bind(
                ids()[0],
                take("property", required=True),
                take("expression", required=True),
                target=take("target", "entity"),
                units=take("units", self.doc.units),
            )
        elif cmd == "UNBIND":
            self.doc.unbind(
                ids()[0],
                take("property", required=True),
                target=take("target", "entity"),
            )
        elif cmd == "GROUP":
            if len(positional) < 2:
                raise ValueError("GROUP needs a name and geometry IDs.")
            self.doc.group(positional[0], positional[1:])
        elif cmd == "UNGROUP":
            self.doc.ungroup(ids()[0])
        elif cmd == "BLOCK":
            name = ids()[0]
            if "data" in args:
                self.doc.blocks[name] = json.loads(take("data"))
            else:
                members = take("refs", required=True).split(",")
                self.doc.define_block(name, members, base=(num("x"), num("y")))
        elif cmd == "INSERT":
            name = ids()[0]
            self.doc.insert_block(
                name,
                num("x"),
                num("y"),
                num("angle"),
                num("scale", 1),
                layer=take("layer", self.doc.active_layer),
                id=take("id"),
                mirror=boolean("mirror"),
            )
        elif cmd == "UNBLOCK":
            self.doc.remove_block(ids()[0])
        elif cmd == "EXPLODE":
            f = self.doc.feature_for(ids()[0])
            if f is None or f["kind"] != "block":
                raise ValueError("EXPLODE requires a block instance.")
            self.doc.detach_feature(f["id"])
        elif cmd == "PATTERN":
            self.doc.set_region_pattern(
                ids()[0],
                json.loads(take("data", required=True)),
                name=take("name", "CUSTOM"),
            )
        elif cmd == "UNITS":
            self.doc.set_units(ids()[0])
        elif cmd == "LAYER":
            name = ids()[0]
            self.doc.set_layer(
                name,
                color=take("color", "#243e58"),
                width=num("width", 0.25),
                visible=boolean("visible", True),
                locked=boolean("locked"),
            )
        elif cmd == "USE":
            name = ids()[0]
            if name not in self.doc.layers:
                raise ValueError(
                    "Choose an existing layer; unlock it before adding geometry."
                )
            self.doc.active_layer = name
        elif cmd == "CONSTRAINT":
            id = ids()[0]
            kind = take("kind", required=True)
            refs = take("refs", required=True).split(",")
            value = num("value") if "value" in args else None
            state = json.loads(take("state")) if "state" in args else None
            parameters = (
                [self.number(t) for t in take("parameters").split(",")]
                if "parameters" in args
                else None
            )
            self.doc.constrain(
                kind, refs, value, id=id, state=state, parameters=parameters
            )
        elif cmd == "UNCONSTRAIN":
            self.doc.remove_constraint(ids()[0])
        elif cmd == "DRIVE":
            self.doc.set_constraint_value(ids()[0], num("value", required=True))
        elif cmd == "FEATURE":
            id = ids()[0]
            feature = json.loads(take("data", required=True))
            if feature.get("id") != id or id in self.doc.features:
                raise ValueError("Invalid or duplicate feature ID.")
            self.doc.features[id] = feature
        elif cmd == "DETACH":
            self.doc.detach_feature(ids()[0])
        elif cmd == "DRIVE_FEATURE":
            params = {k: num(k) for k in list(args)}
            self.doc.update_feature(ids()[0], **params)
        elif cmd == "ROUND":
            self.doc.round_path(
                ids()[0],
                num("radius", required=True),
                tolerance=num("tolerance", 0.01),
                vertex=num("vertex") if "vertex" in args else None,
                linked=boolean("linked", True),
            )
        elif cmd == "TANGENTS":
            self.doc.common_tangents(
                *ids(2), kind=take("kind", "both"), linked=boolean("linked", True)
            )
        elif cmd in ("UNION", "DIFFERENCE", "INTERSECTION"):
            if not 2 <= len(positional) <= 64:
                raise ValueError("Boolean requires at least two input IDs.")
            self.doc.boolean(
                positional,
                operation=cmd.lower(),
                tolerance=num("tolerance", 0.01),
                linked=boolean("linked", True),
            )
        elif cmd == "CLEANOFFSET":
            self.doc.clean_offset(
                ids()[0],
                num("distance", required=True),
                tolerance=num("tolerance", 0.01),
                join=take("join", "round"),
                as_regions=boolean("regions"),
                linked=boolean("linked", True),
            )
        elif cmd == "REGION":
            self.doc.add(
                "region",
                id=ids()[0],
                x=num("x"),
                y=num("y"),
                angle=num("angle"),
                rings=json.loads(take("rings", required=True)),
                hatch=take("hatch", "solid"),
                spacing=num("spacing", 2),
                hatch_angle=num("hatch_angle", 45),
                layer=take("layer", self.doc.active_layer),
            )
        elif cmd == "ENTITY":
            id = ids()[0]
            kind = take("kind", required=True)
            self.doc.add(
                kind,
                id=id,
                x=num("x"),
                y=num("y"),
                angle=num("angle"),
                layer=take("layer", "0"),
                construction=boolean("construction"),
                **json.loads(take("data", "{}")),
            )
        elif cmd in (
            "POINT",
            "LINE",
            "RECT",
            "RECTANGLE",
            "CIRCLE",
            "ARC",
            "ELLIPSE",
            "POLY",
            "POLYLINE",
            "BEZIER",
            "TEXT",
            "DIM",
            "RDIM",
            "ADIM",
        ):
            id = ids()[0]
            layer = take("layer", self.doc.active_layer)
            construction = boolean("construction")
            x, y, orientation = num("x"), num("y"), num("angle")
            common = {
                "id": id,
                "x": x,
                "y": y,
                "angle": orientation,
                "layer": layer,
                "construction": construction,
            }
            if cmd == "POINT":
                self.doc.add("point", **common)
            elif cmd == "LINE":
                if "length" in args:
                    self.doc.add(
                        "line",
                        points=[(0, 0), (positive(num("length", required=True)), 0)],
                        **common,
                    )
                else:
                    self.doc.add(
                        "line",
                        points=[
                            (0, 0),
                            (
                                num("x2", required=True) - x,
                                num("y2", required=True) - y,
                            ),
                        ],
                        **common,
                    )
            elif cmd in ("RECT", "RECTANGLE"):
                self.doc.add(
                    "rectangle",
                    width=num("width", required=True),
                    height=num("height", required=True),
                    fill=boolean("fill"),
                    **common,
                )
            elif cmd in ("CIRCLE", "ARC"):
                d = {"radius": num("radius", required=True)}
                if cmd == "ARC":
                    d.update(start=num("start"), sweep=num("sweep", 90))
                self.doc.add(cmd.lower(), **d, **common)
            elif cmd == "ELLIPSE":
                self.doc.add(
                    "ellipse",
                    rx=num("rx", required=True),
                    ry=num("ry", required=True),
                    **(
                        {"start": num("start"), "sweep": num("sweep", 360)}
                        if "start" in args or "sweep" in args
                        else {}
                    ),
                    **common,
                )
            elif cmd in ("POLY", "POLYLINE", "BEZIER"):
                points = [
                    tuple(self.number(v) for v in p.split(","))
                    for p in take("points", required=True).split(";")
                ]
                self.doc.add(
                    "bezier" if cmd == "BEZIER" else "polyline",
                    points=points,
                    closed=boolean("closed"),
                    fill=boolean("fill"),
                    **common,
                )
            elif cmd == "TEXT":
                self.doc.add(
                    "text",
                    text=take("text", required=True),
                    height=num("height", 3),
                    **common,
                )
            elif cmd in ("DIM", "RDIM") and "entity" in args:
                self.doc.dimension(
                    take("entity"), offset=num("offset", 8), id=id, layer=layer
                )
            elif cmd == "DIM":
                self.doc.add(
                    "dimension",
                    points=[
                        (0, 0),
                        (num("x2", required=True) - x, num("y2", required=True) - y),
                    ],
                    offset=num("offset", 8),
                    **common,
                )
            elif cmd == "RDIM":
                self.doc.add(
                    "radial_dimension", radius=num("radius", required=True), **common
                )
            else:
                self.doc.add(
                    "angular_dimension",
                    radius=num("radius", 10),
                    start=num("start"),
                    sweep=num("sweep", 90),
                    **common,
                )
        elif cmd in (
            "MOVE",
            "COPY",
            "ROTATE",
            "SCALE",
            "MIRROR",
            "OFFSET",
            "ARRAY",
            "TRIM",
            "EXTEND",
            "FILLET",
            "CHAMFER",
            "DELETE",
        ):
            if cmd == "DELETE":
                if not positional:
                    raise ValueError("DELETE requires entity IDs.")
                self.doc.delete(positional)
            elif cmd in ("FILLET", "CHAMFER"):
                has_pick = "x" in args or "y" in args
                pick = (
                    (num("x", required=True), num("y", required=True))
                    if has_pick
                    else None
                )
                self.doc.corner(
                    *ids(2),
                    num("radius" if cmd == "FILLET" else "distance", required=True),
                    fillet=cmd == "FILLET",
                    pick=pick,
                    linked=boolean("linked", True),
                )
            elif cmd in ("TRIM", "EXTEND"):
                self.doc.trim_extend(
                    ids()[0],
                    take("boundary", required=True),
                    (num("x"), num("y")),
                    cmd == "EXTEND",
                    tolerance=num("tolerance", 0.01),
                    limit=num("limit", 4),
                )
            elif cmd == "OFFSET":
                self.doc.offset(
                    ids()[0],
                    num("distance", required=True),
                    tolerance=num("tolerance", 0.01),
                    linked=boolean("linked", True),
                )
            elif cmd == "MIRROR":
                self.doc.mirror(
                    ids(),
                    (num("x1"), num("y1")),
                    (num("x2", 1), num("y2")),
                    boolean("copy"),
                )
            elif cmd == "ARRAY":
                self.doc.array(
                    ids(),
                    num("count", required=True),
                    num("dx"),
                    num("dy"),
                    num("rotation"),
                    (num("px"), num("py")),
                )
            else:
                self.doc.transform(
                    ids(),
                    dx=num("dx"),
                    dy=num("dy"),
                    rotation=num("angle"),
                    scale=num("factor", 1),
                    pivot=(num("px"), num("py")),
                    copy_entities=cmd == "COPY",
                )
        else:
            raise ValueError(f"Unknown command {cmd}.")
        if args:
            raise ValueError("Unknown parameter(s): " + ", ".join(args))


def document_script(doc):
    """Lossless editable script snapshot; references resolve at transaction end."""
    q = shlex.quote
    lines = [f"UNITS {doc.units}"]
    for l in doc.layers.values():
        # Lock after creation so entities can first be recreated on the layer.
        lines.append(
            f"LAYER {q(l.name)} color={q(l.color)} width={l.width!r} visible={str(l.visible).lower()}"
        )
    for name, spec in doc.parameters.items():
        lines.append(
            f"PARAM {q(name)} expression={q(spec['expression'])} kind={spec['kind']} units={spec['units']}"
        )
    for name, definition in doc.blocks.items():
        lines.append(
            f"BLOCK {q(name)} data={q(json.dumps(definition, separators=(',', ':')))}"
        )
    for e in doc.entities.values():
        lines.append(
            f"ENTITY {q(e.id)} kind={e.kind} x={e.x!r} y={e.y!r} angle={e.angle!r} layer={q(e.layer)} construction={str(e.construction).lower()} data={q(json.dumps(e.data, separators=(',', ':')))}"
        )
    for c in doc.constraints.values():
        line = f"CONSTRAINT {q(c['id'])} kind={c['kind']} refs={q(','.join(c['refs']))}"
        if "value" in c:
            line += f" value={c['value']!r}"
        if "state" in c:
            line += " state=" + q(json.dumps(c["state"], separators=(",", ":")))
        if "parameters" in c:
            line += " parameters=" + q(",".join(repr(t) for t in c["parameters"]))
        lines.append(line)
    for f in doc.features.values():
        lines.append(
            f"FEATURE {q(f['id'])} data={q(json.dumps(f, separators=(',', ':')))}"
        )
    for name, members in doc.groups.items():
        lines.append("GROUP " + q(name) + " " + " ".join(q(i) for i in members))
    for b in doc.bindings:
        lines.append(
            f"BIND {q(b['id'])} property={q(b['property'])} expression={q(b['expression'])} target={b['target']} units={b['units']}"
        )
    for l in doc.layers.values():
        if l.locked:
            lines.append(
                f"LAYER {q(l.name)} color={q(l.color)} width={l.width!r} visible={str(l.visible).lower()} locked=true"
            )
    lines.append("USE " + q(doc.active_layer))
    return "\n".join(lines) + "\n"


def import_legacy(doc, source):
    try:
        from .builder import TrackBuilder
        from .models import ArcSegment, CircleSegment, LineSegment
    except ImportError:
        from builder import TrackBuilder
        from models import ArcSegment, CircleSegment, LineSegment
    builder = TrackBuilder()
    if not builder.parse(source):
        raise ScriptError("\n".join(f"Line {n}: {e}" for n, e in builder.errors))
    with doc.transaction("Import legacy track"):
        for p in builder.points.values():
            doc.add(
                "point", id=doc.unique_id(p.name + "_"), x=p.x, y=p.y, construction=True
            )
        for s in builder.segments:
            if isinstance(s, LineSegment):
                doc.line(s.p1.x, s.p1.y, s.p2.x, s.p2.y)
            elif isinstance(s, CircleSegment):
                doc.circle(s.center.x, s.center.y, s.radius)
            elif isinstance(s, ArcSegment):
                doc.arc(
                    s.cx, s.cy, s.radius, s.start_angle, s.end_angle - s.start_angle
                )
