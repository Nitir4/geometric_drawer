from __future__ import annotations

import svgwrite
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

try:
    from .builder import TrackBuilder
    from .models import CircleSegment
    from .rendering import Renderer
except ImportError:
    from builder import TrackBuilder
    from models import CircleSegment
    from rendering import Renderer


class Exporter:
    def __init__(self, renderer: Renderer):
        self.renderer = renderer

    def export_svg(self, builder: TrackBuilder, path: str) -> None:
        s = self.renderer.settings
        scale, off_x, off_y = self.renderer.compute_layout(builder)

        drawing = svgwrite.Drawing(
            path,
            size=(f"{s.track_width}mm", f"{s.track_height}mm"),
            viewBox=f"0 0 {s.track_width} {s.track_height}",
        )

        style = {
            "stroke": "black",
            "fill": "none",
            "stroke_width": s.line_width,
            "stroke_linecap": "round",
            "stroke_linejoin": "round",
        }

        for seg in builder.segments:
            if isinstance(seg, CircleSegment):
                cx, cy = self.renderer.to_track_down(seg.center.x, seg.center.y, scale, off_x, off_y)
                drawing.add(drawing.circle(center=(cx, cy), r=seg.radius * scale, **style))
            else:
                points = [self.renderer.to_track_down(x, y, scale, off_x, off_y) for x, y in seg.polyline_points()]
                drawing.add(drawing.polyline(points=points, **style))

        drawing.save()

    def export_pdf(self, builder: TrackBuilder, path: str) -> None:
        s = self.renderer.settings
        scale, off_x, off_y = self.renderer.compute_layout(builder)

        pdf = pdf_canvas.Canvas(path, pagesize=(s.track_width * mm, s.track_height * mm))
        pdf.setStrokeColor(colors.black)
        pdf.setLineWidth(s.line_width * mm)
        pdf.setLineCap(1)
        pdf.setLineJoin(1)

        for seg in builder.segments:
            if isinstance(seg, CircleSegment):
                cx, cy = self.renderer.to_track_up(seg.center.x, seg.center.y, scale, off_x, off_y)
                pdf.circle(cx * mm, cy * mm, seg.radius * scale * mm, stroke=1, fill=0)
                continue

            points = [self.renderer.to_track_up(x, y, scale, off_x, off_y) for x, y in seg.polyline_points()]
            if len(points) < 2:
                continue
            path_obj = pdf.beginPath()
            path_obj.moveTo(points[0][0] * mm, points[0][1] * mm)
            for x, y in points[1:]:
                path_obj.lineTo(x * mm, y * mm)
            pdf.drawPath(path_obj, stroke=1, fill=0)

        pdf.showPage()
        pdf.save()
