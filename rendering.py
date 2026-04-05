from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

try:
    from .builder import TrackBuilder
except ImportError:
    from builder import TrackBuilder


@dataclass(frozen=True)
class Settings:
    track_width: float
    track_height: float
    line_width: float
    margin: float


@dataclass(frozen=True)
class OverflowInfo:
    scale_centerline: float
    scale_stroke: float
    overflow_left: float
    overflow_right: float
    overflow_top: float
    overflow_bottom: float


class Renderer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def compute_layout(self, builder: TrackBuilder) -> tuple[float, float, float]:
        bx0, by0, bx1, by1 = builder.bounding_box()
        geom_w = max(1e-9, bx1 - bx0)
        geom_h = max(1e-9, by1 - by0)

        avail_w, avail_h = self._available_area()
        scale = min(avail_w / geom_w, avail_h / geom_h)

        scaled_w = geom_w * scale
        scaled_h = geom_h * scale
        off_x = self.settings.margin + (avail_w - scaled_w) / 2.0 - bx0 * scale
        off_y = self.settings.margin + (avail_h - scaled_h) / 2.0 - by0 * scale
        return scale, off_x, off_y

    def overflow_info(self, builder: TrackBuilder) -> OverflowInfo:
        bx0, by0, bx1, by1 = builder.bounding_box()
        geom_w = max(1e-9, bx1 - bx0)
        geom_h = max(1e-9, by1 - by0)

        avail_w, avail_h = self._available_area()
        needed_w = geom_w + self.settings.line_width
        needed_h = geom_h + self.settings.line_width

        scale_centerline = min(avail_w / geom_w, avail_h / geom_h)
        scale_stroke = min(avail_w / needed_w, avail_h / needed_h)

        overflow_w = max(0.0, needed_w - avail_w)
        overflow_h = max(0.0, needed_h - avail_h)

        return OverflowInfo(
            scale_centerline=scale_centerline,
            scale_stroke=scale_stroke,
            overflow_left=overflow_w / 2.0,
            overflow_right=overflow_w / 2.0,
            overflow_top=overflow_h / 2.0,
            overflow_bottom=overflow_h / 2.0,
        )

    def _available_area(self) -> tuple[float, float]:
        avail_w = self.settings.track_width - 2.0 * self.settings.margin
        avail_h = self.settings.track_height - 2.0 * self.settings.margin
        if avail_w <= 0 or avail_h <= 0:
            raise ValueError("Margin is too large for current track size")
        return avail_w, avail_h

    def to_track_up(self, x: float, y: float, scale: float, off_x: float, off_y: float) -> tuple[float, float]:
        return x * scale + off_x, y * scale + off_y

    def to_track_down(self, x: float, y: float, scale: float, off_x: float, off_y: float) -> tuple[float, float]:
        tx, ty_up = self.to_track_up(x, y, scale, off_x, off_y)
        return tx, self.settings.track_height - ty_up

    def render(self, canvas: tk.Canvas, builder: TrackBuilder, show_markers: bool = False) -> None:
        canvas.delete("all")
        canvas.configure(bg="white")

        if not builder.segments and not builder.points:
            return

        scale, off_x, off_y = self.compute_layout(builder)
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        px_per_mm = min(cw / self.settings.track_width, ch / self.settings.track_height)
        x0 = (cw - self.settings.track_width * px_per_mm) / 2.0
        y0 = (ch - self.settings.track_height * px_per_mm) / 2.0
        stroke_px = max(1.0, self.settings.line_width * px_per_mm)

        for seg in builder.segments:
            pts = seg.polyline_points()
            if len(pts) < 2:
                continue
            flat: list[float] = []
            for x, y in pts:
                tx, ty = self.to_track_down(x, y, scale, off_x, off_y)
                flat.extend([x0 + tx * px_per_mm, y0 + ty * px_per_mm])
            canvas.create_line(
                *flat,
                fill="black",
                width=stroke_px,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                smooth=False,
            )

        if show_markers and builder.points:
            names = list(builder.points)
            for label, color in ((names[0], "green"), (names[-1], "red")):
                p = builder.points[label]
                tx, ty = self.to_track_down(p.x, p.y, scale, off_x, off_y)
                px = x0 + tx * px_per_mm
                py = y0 + ty * px_per_mm
                r = max(3, int(2.5 * px_per_mm))
                canvas.create_oval(px - r, py - r, px + r, py + r, fill=color, outline=color)
