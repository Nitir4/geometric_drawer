            )
        if k == "region":
            try:
                from .cad_regions import definition
            except ImportError:
                from cad_regions import definition
            for obj in result:
                msp.delete_entity(obj)
            hatch = msp.add_hatch(color=256, dxfattribs=attrs)
            for index, ring in enumerate(e.paths()):
                hatch.paths.add_polyline_path(
                    ring[:-1], is_closed=True, flags=1 if index == 0 else 0
                )
            pattern = definition(e, world=True)
            if pattern:
                hatch.set_pattern_fill(
                    d.get("hatch_name", "USER"), angle=0, scale=1, definition=pattern
                )
            result = [hatch]
        if d.get("fill") and k in ("rectangle", "polyline"):
            if k == "polyline" and not d.get("closed"):
                raise ValueError("DXF fill requires a closed polyline.")
            for obj in result:
                msp.delete_entity(obj)
            hatch = msp.add_hatch(color=256, dxfattribs=attrs)
            hatch.paths.add_polyline_path(e.vertices(), is_closed=True)
            result = [hatch]
        for i, obj in enumerate(result):
            # Metadata does not override external geometry on import.
            obj.set_xdata(
                "GEOMETRIC_DRAWER",
                [
                    (1000, e.id if len(result) == 1 else f"{e.id}_{i + 1}"),
                    (1000, k),
                    (1070, int(e.construction)),
                ],
            )
    if out.audit().has_errors:
        raise ValueError("DXF failed its structural audit.")
    out.saveas(path)


def import_dxf(path, *, curve_tolerance=0.01):
    """Reject unsupported/3-D content atomically rather than silently lose it."""
    import ezdxf
    from ezdxf.colors import aci2rgb
    from ezdxf.path import make_path

    if not math.isfinite(curve_tolerance) or curve_tolerance <= 0:
        raise ValueError("Curve tolerance must be positive, in drawing units.")

    try:
        source = ezdxf.readfile(path)
    except ezdxf.DXFError as exc:
        raise ValueError(f"Cannot read DXF: {exc}") from exc
    if source.audit().has_errors:
        raise ValueError("DXF has structural errors; repair it before importing.")
    units = {4: "mm", 5: "cm", 6: "m", 1: "in"}.get(source.units)
    if not units:
        raise ValueError("DXF must declare mm, cm, m or inch units ($INSUNITS).")
    doc = Document()
    doc.units = units
    doc.import_warnings = []

    def warn(message):
        if message not in doc.import_warnings:
            doc.import_warnings.append(message)

    def xy(p):
        if len(p) > 2 and abs(p[2]) > EPS:
            raise ValueError("Only planar XY geometry at Z=0 can be imported.")
        return p[0], p[1]

    def import_path(obj, common):
        path = make_path(obj)
        previous = xy(path.start)
        for command in path:
            end = xy(command.end)
            child = dict(common, id=None)
            if command.type.name == "LINE_TO":
                if distance(previous, end) > EPS:
                    doc.line(*previous, *end, **child)
            elif command.type.name == "CURVE4_TO":
                doc.add(
                    "bezier",
                    points=[previous, xy(command.ctrl1), xy(command.ctrl2), end],
                    **child,
                )
            elif command.type.name == "CURVE3_TO":
                control = xy(command.ctrl)
                a = tuple(
                    previous[i] + 2 / 3 * (control[i] - previous[i]) for i in range(2)
                )
                b = tuple(end[i] + 2 / 3 * (control[i] - end[i]) for i in range(2))
                doc.add("bezier", points=[previous, a, b, end], **child)
            else:
                raise ValueError("Unsupported disconnected curve path.")
            previous = end

    def import_entity(obj, depth=0, inherited_layer=None):
        if depth > 32:
            raise ValueError("Nested block depth exceeds 32 (possibly cyclic).")
        kind, layer = obj.dxftype(), obj.dxf.layer
        if layer == "0" and inherited_layer:
            layer = inherited_layer
        if obj.dxf.get("color", 256) != 256 or obj.dxf.hasattr("true_color"):
            warn("Per-entity colour overrides were replaced by layer colours.")
        if kind == "INSERT":
            xy(obj.dxf.insert)
            if abs(obj.dxf.get("zscale", 1) - 1) > EPS:
                raise ValueError("3-D block scaling is unsupported.")

            def skipped(entity, reason):
                raise ValueError(
                    f"Block contains unsupported {entity.dxftype()}: {reason}"
                )

            inserts = obj.multi_insert() if obj.mcount > 1 else [obj]
            for insert in inserts:
                for child in insert.virtual_entities(skipped_entity_callback=skipped):
                    import_entity(child, depth + 1, layer)
                for attribute in insert.attribs:
                    import_entity(attribute, depth + 1, layer)
            warn("Block references were expanded into editable world-space geometry.")
            return
        if kind in ("DIMENSION", "LEADER"):
            for child in obj.virtual_entities():
                import_entity(child, depth + 1, layer)
            warn(
                "DXF dimensions/leaders were expanded into standalone geometry and text."
            )
            return
        if obj.dxf.hasattr("extrusion") and tuple(obj.dxf.extrusion) != (0.0, 0.0, 1.0):
            raise ValueError("Non-XY extrusion is not supported.")
        if obj.dxf.hasattr("thickness") and abs(obj.dxf.thickness) > EPS:
            raise ValueError("3-D thickness is not supported.")
        id, original, construction = None, "", False
        if obj.has_xdata("GEOMETRIC_DRAWER"):
            data = obj.get_xdata("GEOMETRIC_DRAWER")
            if len(data) < 3:
                raise ValueError("Malformed GEOMETRIC_DRAWER DXF metadata.")
            id, original, construction = (
                data[0].value,
                data[1].value,
                bool(data[2].value),
            )
        if id in doc.entities:
            id = None
        common = {"layer": layer, "id": id, "construction": construction}
        if kind == "LINE":
            doc.line(*xy(obj.dxf.start), *xy(obj.dxf.end), **common)
        elif kind == "POINT":
            doc.add("point", x=obj.dxf.location.x, y=obj.dxf.location.y, **common)
            xy(obj.dxf.location)
        elif kind in ("CIRCLE", "ARC"):
            x, y = xy(obj.dxf.center)
            if kind == "CIRCLE":
                doc.circle(x, y, obj.dxf.radius, **common)
            else:
                sweep = (obj.dxf.end_angle - obj.dxf.start_angle) % 360
                doc.arc(
                    x, y, obj.dxf.radius, obj.dxf.start_angle, sweep or 360, **common
                )
        elif kind == "LWPOLYLINE":
            if abs(obj.dxf.elevation) > EPS:
                raise ValueError("Polyline elevation must be zero.")
            if any(abs(p[4]) > EPS for p in obj.get_points()):
                for child in obj.virtual_entities():
                    import_entity(child)
                return
            p = list(obj.get_points("xy"))
            if original == "rectangle" and len(p) == 4 and obj.closed:
                u, v = sub(p[1], p[0]), sub(p[3], p[0])
                if (
                    abs(u[0] * v[0] + u[1] * v[1]) < 1e-6
                    and distance(add(p[1], v), p[2]) < 1e-6
                    and u[0] * v[1] - u[1] * v[0] > 0
                ):
                    doc.rectangle(
                        *p[0],
                        distance(p[0], p[1]),
                        distance(p[0], p[3]),
                        angle(u),
                        **common,
                    )
                    return
            doc.polyline(p, closed=obj.closed, **common)
        elif kind == "ELLIPSE":
            xy(obj.dxf.center)
            u = xy(obj.dxf.major_axis)
            rx = math.hypot(*u)
            data = {"rx": rx, "ry": rx * obj.dxf.ratio}
            span = obj.dxf.end_param - obj.dxf.start_param
            if abs(abs(span) - math.tau) > 1e-7:
                data.update(
                    start=math.degrees(obj.dxf.start_param),
                    sweep=math.degrees(span % math.tau) or 360,
                )
            doc.add(
                "ellipse",
                x=obj.dxf.center.x,
                y=obj.dxf.center.y,
                angle=angle(u),
                **data,
                **common,
            )
        elif kind == "SPLINE":
            for vertex in obj.control_points:
                xy(vertex)
            for vertex in obj.fit_points:
                xy(vertex)
            knots = list(obj.knots)
            controls = list(obj.control_points)
            rational = any(abs(w - 1) > EPS for w in obj.weights)
            if obj.dxf.degree == 3 and not rational:
                if (
                    len(controls) == 4
                    and len(knots) == 8
                    and len(set(knots[:4])) == 1
                    and len(set(knots[4:])) == 1
                ):
                    doc.add("bezier", points=[xy(v) for v in controls], **common)
                else:
                    import_path(obj, common)
            else:
                points = [
                    xy(v) for v in obj.construction_tool().flattening(curve_tolerance)
                ]
                doc.polyline(points, closed=obj.closed, **common)
                warn(
                    f"Non-cubic/rational splines were flattened at {curve_tolerance:g} {units} tolerance."
                )
        elif kind == "POLYLINE":
            if not obj.is_2d_polyline:
                raise ValueError("Only 2-D POLYLINE is supported.")
            for child in obj.virtual_entities():
                import_entity(child, depth + 1, layer)
        elif kind in ("SOLID", "TRACE", "3DFACE"):
            vertices = [xy(v) for v in obj.wcs_vertices(close=False)]
            if len(vertices) >= 3:
                doc.polyline(vertices, closed=True, fill=True, outline=False, **common)
        elif kind == "HATCH":
            if abs(obj.dxf.elevation.z) > EPS:
                raise ValueError("Hatch elevation must be zero.")
            from ezdxf.path import from_hatch

            try:
                from .cad_regions import rings_from_paths
            except ImportError:
                from cad_regions import rings_from_paths
            paths = list(from_hatch(obj))
            rings = [
                [xy(v) for v in path.flattening(curve_tolerance)] for path in paths
            ]
            if obj.gradient is not None:
                raise ValueError(
                    "Gradient hatches are unsupported; convert to solid or line patterns."
                )
            groups = rings_from_paths(rings, style=obj.dxf.hatch_style)
            if not groups:
                raise ValueError("Empty hatch boundary.")
            data = {"hatch": "solid"}
            if not obj.dxf.solid_fill:
                if obj.dxf.pattern_double:
                    raise ValueError(
                        "Double pattern hatches are unsupported; expand the pattern definition first."
                    )
                if obj.pattern is None:
                    raise ValueError("Pattern hatch has no definition.")
                data = {
                    "hatch": "custom",
                    "hatch_name": obj.dxf.pattern_name,
                    "hatch_definition": [
                        [
                            line.angle,
                            tuple(line.base_point),
                            tuple(line.offset),
                            list(line.dash_length_items),
                        ]
                        for line in obj.pattern.lines
                    ],
                }
            for index, rings in enumerate(groups):
                doc.add(
                    "region",
                    rings=rings,
                    **data,
                    **dict(common, id=common["id"] if index == 0 else None),
                )
            if any(path.has_curves for path in paths):
                warn(
                    "Curved hatch boundaries sampled at import tolerance; holes/islands preserved as regions."
                )
        elif kind == "MTEXT":
            # Plain text remains editable; rich formatting is explicitly reported.
            x, y = xy(obj.dxf.insert)
            direction = obj.dxf.get("text_direction")
            rotation = angle(xy(direction)) if direction else obj.dxf.get("rotation", 0)
            attachment = obj.dxf.get("attachment_point", 1)
            lines = obj.plain_text().splitlines() or [""]
            height = obj.dxf.char_height
            spacing = 1.667 * height * obj.dxf.get("line_spacing_factor", 1)
            # Tk/native TEXT uses a baseline origin. Preserve the insertion anchor
            # approximately while making every text line editable.
            row, col = divmod(attachment - 1, 3)
            width = obj.dxf.get("width", 0)
            for i, text in enumerate(lines):
                if text:
                    from math import cos, radians, sin

                    dx = -col * width / 2
                    dy = (
                        row * max(0, len(lines) - 1) * spacing / 2
                        - height
                        - i * spacing
                    )
                    t = radians(rotation)
                    doc.add(
                        "text",
                        x=x + dx * cos(t) - dy * sin(t),
                        y=y + dx * sin(t) + dy * cos(t),
                        angle=rotation,
                        height=height,
                        text=text,
                        **dict(common, id=None),
                    )
            warn(
                "MTEXT was converted to editable plain text; rich formatting, wrapping and exact font metrics are not retained."
            )
        elif kind in ("TEXT", "ATTRIB"):
            if (
                obj.dxf.get("text_generation_flag", 0)
                or obj.dxf.get("halign", 0)
                or obj.dxf.get("valign", 0)
            ):
                from ezdxf.addons import text2path

                for text_path in text2path.make_paths_from_entity(obj):
                    vertices = [xy(v) for v in text_path.flattening(curve_tolerance)]
                    if len(vertices) > 1:
                        doc.polyline(
                            vertices,
                            closed=text_path.is_closed,
                            **dict(common, id=None),
                        )
                warn(
                    "Aligned/mirrored DXF text was converted to font outlines; exact appearance depends on available fonts."
                )
                return
            x, y = xy(obj.dxf.insert)
            doc.add(
                "text",
                x=x,
                y=y,
                angle=obj.dxf.rotation,
                height=obj.dxf.height,
                text=obj.dxf.text,
                **common,
            )
        else:
            raise ValueError(
                f"Unsupported DXF entity: {kind}. No drawing was imported."
            )

    with doc.transaction("Import DXF"):
        for src in source.layers:
            rgb = src.rgb or aci2rgb(abs(src.dxf.color) or 7)
            color = "#{:02x}{:02x}{:02x}".format(*tuple(rgb))
            width = (
                src.dxf.lineweight / 100 / UNIT_MM[units]
                if src.dxf.lineweight > 0
                else 0.25 / UNIT_MM[units]
            )
            doc.set_layer(
                src.dxf.name,
                color=color,
                width=width,
                visible=src.is_on(),
                locked=False,
            )
        for obj in source.modelspace():
            import_entity(obj)
        for src in source.layers:
            doc.layers[src.dxf.name].locked = src.is_locked()
    doc._undo.clear()
    return doc


def _dwg_converter():
    try:
        from .cad_dwg import converter
    except ImportError:
        from cad_dwg import converter
    return converter()


def import_dwg(path, *, curve_tolerance=0.01):
    """Use ODA conversion, then the same validated planar DXF importer."""
    converter = _dwg_converter()
    with tempfile.TemporaryDirectory(prefix="geometric-dwg-") as directory:
        target = Path(directory) / "converted.dxf"
        try:
            converter.convert(path, target, audit=True)
        except Exception as exc:
            raise ValueError(f"DWG conversion failed: {exc}") from exc
        doc = import_dxf(target, curve_tolerance=curve_tolerance)
        doc.import_warnings.extend(getattr(converter, "notes", []))
        if type(converter).__name__ == "LibreDWG":
            doc.import_warnings.append(
                "DWG converted by GNU LibreDWG; complex/proxy objects and vendor-specific data may require ODA conversion."
            )
        return doc


def export_dwg(doc, path):
    converter = _dwg_converter()
    # Convert outside the destination; publish only a successfully produced file.
    with tempfile.TemporaryDirectory(prefix="geometric-dwg-") as directory:
        source, target = (
            Path(directory) / "drawing.dxf",
            Path(directory) / "drawing.dwg",
        )
        export_dxf(doc, source)
        try:
            converter.convert(source, target, audit=True)
        except Exception as exc:
            raise ValueError(f"DWG conversion failed: {exc}") from exc
        if not target.is_file():
            raise ValueError("DWG converter did not produce a drawing.")
        destination = Path(path)
        fd, temporary = tempfile.mkstemp(
            prefix=destination.name + ".", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(target.read_bytes())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
