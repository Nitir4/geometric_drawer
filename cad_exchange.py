"""Model-space DXF exchange and true-size SVG/PDF output."""

from __future__ import annotations

import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from .cad_document import UNIT_MM, Document
    from .cad_geometry import EPS, add, angle, distance, polar, sub
except ImportError:
    from cad_document import UNIT_MM, Document
    from cad_geometry import EPS, add, angle, distance, polar, sub


def plotted(doc, construction=False):
    return [
        e
        for e in doc.entities.values()
        if doc.layers[e.layer].visible and (construction or not e.construction)
    ]


def sheet(doc, construction=False):
    entities = plotted(doc, construction)
    boxes = [e.bounds() for e in entities]
    if not boxes:
        return (0, 0, 100, 100)
    # Five physical millimetres of margin, regardless of document units.
    margin = 5 / UNIT_MM[doc.units]
    return (
        min(b[0] for b in boxes) - margin,
        min(b[1] for b in boxes) - margin,
        max(b[2] for b in boxes) + margin,
        max(b[3] for b in boxes) + margin,
    )


def export_svg(doc, path, construction=False):
    doc.validate()
    x0, y0, x1, y1 = sheet(doc, construction)
    w, h, mm = x1 - x0, y1 - y0, UNIT_MM[doc.units]
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.Element(
        f"{{{ns}}}svg",
        width=f"{w * mm:.12g}mm",
        height=f"{h * mm:.12g}mm",
        viewBox=f"{x0:.12g} {-y1:.12g} {w:.12g} {h:.12g}",
    )
    ET.SubElement(
        root, f"{{{ns}}}title"
    ).text = "Geometric Drawer — model-space drawing"

    def node(tag, attributes, parent=root):
        return ET.SubElement(
            parent, f"{{{ns}}}{tag}", {k: str(v) for k, v in attributes.items()}
        )

    for e in plotted(doc, construction):
        l, d, k = doc.layers[e.layer], e.data, e.kind
        attrs = {
            "stroke": l.color if d.get("outline", True) else "none",
            "stroke-width": l.width,
            "fill": l.color if d.get("fill") else "none",
            "stroke-linejoin": "round",
        }
        if e.construction:
            attrs["stroke-dasharray"] = f"{l.width * 8} {l.width * 5}"
        g = node("g", {"id": e.id, "data-layer": e.layer})
        if k == "region":
            try:
                from .cad_regions import hatch_segments
            except ImportError:
                from cad_regions import hatch_segments
            pathdata = " ".join(
                "M " + " L ".join(f"{x} {-y}" for x, y in ring) + " Z"
                for ring in e.paths()
            )
            region_attrs = dict(attrs, d=pathdata)
            region_attrs["fill-rule"] = "evenodd"
            region_attrs["fill"] = l.color if d["hatch"] == "solid" else "none"
            node("path", region_attrs, g)
            for a, b in hatch_segments(e):
                node(
                    "line",
                    dict(attrs, x1=a[0], y1=-a[1], x2=b[0], y2=-b[1], fill="none"),
                    g,
                )
        elif k == "circle":
            node("circle", dict(attrs, cx=e.x, cy=-e.y, r=d["radius"]), g)
        elif k == "ellipse":
            if abs(d.get("sweep", 360)) >= 360 - EPS:
                node(
                    "ellipse",
                    dict(
                        attrs,
                        cx=e.x,
                        cy=-e.y,
                        rx=d["rx"],
                        ry=d["ry"],
                        transform=f"rotate({-e.angle} {e.x} {-e.y})",
                    ),
                    g,
                )
            else:
                from math import cos, radians, sin

                start, sweep = d.get("start", 0), d["sweep"]

                def endpoint(t, e=e, d=d):
                    return e.world(
                        (d["rx"] * cos(radians(t)), d["ry"] * sin(radians(t)))
                    )

                a, b = endpoint(start), endpoint(start + sweep)
                pathdata = f"M {a[0]} {-a[1]} A {d['rx']} {d['ry']} {-e.angle} {int(abs(sweep) > 180)} {int(sweep < 0)} {b[0]} {-b[1]}"
                node("path", dict(attrs, d=pathdata), g)
        elif k == "arc":
            start, sweep = d["start"] + e.angle, d["sweep"]
            pieces = 2 if abs(sweep) >= 360 - EPS else 1
            a = add((e.x, e.y), polar(d["radius"], start))
            pathdata = f"M {a[0]} {-a[1]}"
            for i in range(1, pieces + 1):
                b = add((e.x, e.y), polar(d["radius"], start + sweep * i / pieces))
                pathdata += f" A {d['radius']} {d['radius']} 0 {int(abs(sweep / pieces) > 180)} {int(sweep < 0)} {b[0]} {-b[1]}"
            node("path", dict(attrs, d=pathdata), g)
        elif k == "bezier":
            p = e.vertices()
            text = f"M {p[0][0]} {-p[0][1]} C " + " ".join(
                f"{x} {-y}" for x, y in p[1:]
            )
            node("path", dict(attrs, d=text), g)
        elif k == "point":
            node("circle", dict(attrs, cx=e.x, cy=-e.y, r=l.width * 2), g)
        else:
            for p in e.paths():
                node(
                    "polyline",
                    dict(attrs, points=" ".join(f"{x},{-y}" for x, y in p)),
                    g,
                )
        label = e.label()
        if label:
            (x, y), text, height = label
            n = node(
                "text",
                {
                    "x": x,
                    "y": -y,
                    "font-size": height,
                    "font-family": "sans-serif",
                    "fill": l.color,
                    "transform": f"rotate({-e.angle} {x} {-y})",
                },
                g,
            )
            n.text = text
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def export_pdf(doc, path, construction=False, print_scale=1):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    doc.validate()
    labels = [e.label()[1] for e in plotted(doc, construction) if e.label()]
    font = "Helvetica"
    if any(ord(ch) > 127 for text in labels for ch in text):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            os.environ.get("CAD_FONT_PATH", ""),
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        selected = next((p for p in candidates if p and Path(p).is_file()), None)
        if not selected:
            raise ValueError(
                "Unicode PDF text requires a TrueType font; set CAD_FONT_PATH to its file."
            )
        font = "CADUnicode_" + str(abs(hash(selected)))
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, selected))
        available = pdfmetrics.getFont(font).face.charToGlyph
        missing = sorted(
            {
                ch
                for text in labels
                for ch in text
                if ord(ch) not in available and not ch.isspace()
            }
        )
        if missing:
            raise ValueError(
                "PDF font lacks glyphs: "
                + " ".join(missing)
                + "; choose CAD_FONT_PATH with coverage."
            )

    if not math.isfinite(print_scale) or print_scale <= 0:
        raise ValueError("Print scale must be positive.")
    x0, y0, x1, y1 = sheet(doc, construction)
    factor = UNIT_MM[doc.units] * 72 / 25.4 * print_scale
    c = canvas.Canvas(str(path), pagesize=((x1 - x0) * factor, (y1 - y0) * factor))
    c.setTitle("Geometric Drawer — 2-D CAD")
    c.translate(-x0 * factor, -y0 * factor)
    c.scale(factor, factor)
    for e in plotted(doc, construction):
        l, d, k = doc.layers[e.layer], e.data, e.kind
        c.setStrokeColor(HexColor(l.color))
        c.setFillColor(HexColor(l.color))
        c.setLineWidth(l.width)
        c.setDash(l.width * 8, l.width * 5) if e.construction else c.setDash()
        if k == "region":
            try:
                from .cad_regions import hatch_segments
            except ImportError:
                from cad_regions import hatch_segments
            obj = c.beginPath()
            for ring in e.paths():
                obj.moveTo(*ring[0])
                for p in ring[1:]:
                    obj.lineTo(*p)
                obj.close()
            c.drawPath(
                obj,
                stroke=int(d.get("outline", True)),
                fill=int(d["hatch"] == "solid"),
                fillMode=0,
            )
            for a, b in hatch_segments(e):
                c.line(*a, *b)
        elif k == "circle":
            c.circle(e.x, e.y, d["radius"], fill=int(bool(d.get("fill"))))
        elif k == "arc":
            r = d["radius"]
            c.arc(
                e.x - r,
                e.y - r,
                e.x + r,
                e.y + r,
                startAng=d["start"] + e.angle,
                extent=d["sweep"],
            )
        elif k == "ellipse":
            c.saveState()
            c.translate(e.x, e.y)
            c.rotate(e.angle)
            if abs(d.get("sweep", 360)) >= 360 - EPS:
                c.ellipse(-d["rx"], -d["ry"], d["rx"], d["ry"])
            else:
                c.arc(
                    -d["rx"],
                    -d["ry"],
                    d["rx"],
                    d["ry"],
                    startAng=d.get("start", 0),
                    extent=d["sweep"],
                )
            c.restoreState()
        elif k == "bezier":
            p = e.vertices()
            obj = c.beginPath()
            obj.moveTo(*p[0])
            obj.curveTo(*(v for q in p[1:] for v in q))
            c.drawPath(obj)
        elif k == "point":
            c.circle(e.x, e.y, l.width * 2, fill=1)
        else:
            for p in e.paths():
                obj = c.beginPath()
                obj.moveTo(*p[0])
                for q in p[1:]:
                    obj.lineTo(*q)
                c.drawPath(
                    obj,
                    stroke=int(d.get("outline", True)),
                    fill=int(bool(d.get("fill"))),
                )
        label = e.label()
        if label:
            (x, y), text, height = label
            c.saveState()
            c.translate(x, y)
            c.rotate(e.angle)
            c.setFont(font, height)
            c.drawString(0, 0, text)
            c.restoreState()
    c.showPage()
    c.save()


def export_dxf(doc, path):
    import ezdxf

    doc.validate()
    out = ezdxf.new("R2010")
    out.units = {"mm": 4, "cm": 5, "m": 6, "in": 1}[doc.units]
    out.appids.new("GEOMETRIC_DRAWER")
    for l in doc.layers.values():
        layer = (
            out.layers.get(l.name) if l.name in out.layers else out.layers.new(l.name)
        )
        layer.rgb = tuple(int(l.color[i : i + 2], 16) for i in (1, 3, 5))
        layer.dxf.lineweight = min(
            211, max(0, round(l.width * UNIT_MM[doc.units] * 100))
        )
        layer.lock() if l.locked else layer.unlock()
        layer.on() if l.visible else layer.off()
    msp = out.modelspace()
    for e in doc.entities.values():
        attrs, d, k = {"layer": e.layer}, e.data, e.kind
        result = []
        if k == "point":
            result = [msp.add_point((e.x, e.y), dxfattribs=attrs)]
        elif k == "line":
            result = [msp.add_line(*e.vertices(), dxfattribs=attrs)]
        elif k in ("polyline", "rectangle"):
            result = [
                msp.add_lwpolyline(
                    e.vertices(),
                    close=k == "rectangle" or d.get("closed", False),
                    dxfattribs=attrs,
                )
            ]
        elif k == "circle":
            result = [msp.add_circle((e.x, e.y), d["radius"], dxfattribs=attrs)]
        elif k == "arc":
            if abs(d["sweep"]) >= 360 - EPS:
                result = [msp.add_circle((e.x, e.y), d["radius"], dxfattribs=attrs)]
            else:
                start = e.angle + d["start"]
                end = start + d["sweep"]
                if d["sweep"] < 0:
                    start, end = end, start
                result = [
                    msp.add_arc((e.x, e.y), d["radius"], start, end, dxfattribs=attrs)
                ]
        elif k == "ellipse":
            rx, ry, orientation = d["rx"], d["ry"], e.angle
            start, sweep = d.get("start", 0), d.get("sweep", 360)
            if ry > rx:
                rx, ry, orientation = ry, rx, orientation + 90
                start -= 90
            end = start + sweep
            if sweep < 0:
                start, end = end, start
            result = [
                msp.add_ellipse(
                    (e.x, e.y),
                    major_axis=polar(rx, orientation),
                    ratio=ry / rx,
                    start_param=math.radians(start),
                    end_param=math.radians(end),
                    dxfattribs=attrs,
                )
            ]
        elif k == "bezier":
            result = [msp.add_open_spline(e.vertices(), degree=3, dxfattribs=attrs)]
        else:
            for p in e.paths():
                result.append(msp.add_lwpolyline(p, dxfattribs=attrs))
        label = e.label()
        if label:
            (x, y), text, height = label
            result.append(
                msp.add_text(
                    text,
                    dxfattribs=dict(
                        attrs, insert=(x, y), height=height, rotation=e.angle
                    ),
                )
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
