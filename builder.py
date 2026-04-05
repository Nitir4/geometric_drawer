from __future__ import annotations

import math
import re

try:
    from .models import ArcSegment, CircleSegment, LineSegment, Point, Segment
except ImportError:  # direct script execution fallback
    from models import ArcSegment, CircleSegment, LineSegment, Point, Segment


class TrackBuilder:
    PARAM_RE = re.compile(r"([A-Za-z]+)\s*=\s*([^\s]+)")

    def __init__(self):
        self.points: dict[str, Point] = {}
        self.segments: list[Segment] = []
        self.errors: list[tuple[int, str]] = []

    def reset(self) -> None:
        self.points.clear()
        self.segments.clear()
        self.errors.clear()

    def parse(self, script: str) -> bool:
        self.reset()
        for lineno, raw in enumerate(script.splitlines(), start=1):
            line = self._strip_comments(raw)
            if not line:
                continue
            try:
                self._dispatch(line)
            except Exception as exc:
                self.errors.append((lineno, str(exc)))
        return not self.errors

    @staticmethod
    def _strip_comments(line: str) -> str:
        line = line.strip()
        if not line or line.startswith("#"):
            return ""
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        return line

    def _dispatch(self, line: str) -> None:
        token = line.split()[0].upper()
        handlers = {
            "POINT": self._cmd_point,
            "LINE": self._cmd_line,
            "CONNECT": self._cmd_connect,
            "CIRCLE": self._cmd_circle,
            "ARC": self._cmd_arc,
        }
        handler = handlers.get(token)
        if not handler:
            raise ValueError(f"Unknown command '{token}'")
        handler(line)

    def _cmd_point(self, line: str) -> None:
        toks = line.split()
        if len(toks) != 4:
            raise ValueError("POINT requires: POINT <name> <x> <y>")
        name = toks[1]
        self._ensure_new_point(name)
        self.points[name] = Point(name, float(toks[2]), float(toks[3]))

    def _cmd_line(self, line: str) -> None:
        params = self._parse_params(line)
        src = self._resolve(self._need(params, "FROM"))
        dst_name = self._need(params, "TO")
        self._ensure_new_point(dst_name)

        length = float(self._need(params, "LEN"))
        angle = float(self._need(params, "ANGLE"))
        if length <= 0:
            raise ValueError("LINE LEN must be positive")

        rad = math.radians(angle)
        dst = Point(dst_name, src.x + length * math.cos(rad), src.y + length * math.sin(rad))
        self.points[dst_name] = dst
        self.segments.append(LineSegment(src, dst))

    def _cmd_connect(self, line: str) -> None:
        toks = line.split()
        if len(toks) == 3:
            p1 = self._resolve(toks[1])
            p2 = self._resolve(toks[2])
        else:
            params = self._parse_params(line)
            p1 = self._resolve(self._need(params, "FROM"))
            p2 = self._resolve(self._need(params, "TO"))
        self.segments.append(LineSegment(p1, p2))

    def _cmd_circle(self, line: str) -> None:
        params = self._parse_params(line)
        center = self._resolve(self._need(params, "CENTER"))
        radius = float(self._need(params, "R"))
        if radius <= 0:
            raise ValueError("CIRCLE R must be positive")
        self.segments.append(CircleSegment(center, radius))

    def _cmd_arc(self, line: str) -> None:
        params = self._parse_params(line)
        src_name = self._need(params, "FROM")
        dst_name = self._need(params, "TO")
        src = self._resolve(src_name)
        self._ensure_new_point(dst_name)

        radius = float(self._need(params, "R"))
        sweep = float(self._need(params, "A"))
        direction = self._need(params, "DIR").upper()

        if radius <= 0:
            raise ValueError("ARC R must be positive")
        if sweep <= 0:
            raise ValueError("ARC A must be positive")
        if direction not in {"CW", "CCW"}:
            raise ValueError("ARC DIR must be CW or CCW")

        ccw = direction == "CCW"
        tangent = float(params["ANGLE"]) if "ANGLE" in params else self._infer_tangent(src_name)

        center_angle = tangent + (90.0 if ccw else -90.0)
        center_rad = math.radians(center_angle)
        cx = src.x + radius * math.cos(center_rad)
        cy = src.y + radius * math.sin(center_rad)

        start_angle = math.degrees(math.atan2(src.y - cy, src.x - cx))
        end_angle = start_angle + (sweep if ccw else -sweep)
        end_rad = math.radians(end_angle)

        dst = Point(dst_name, cx + radius * math.cos(end_rad), cy + radius * math.sin(end_rad))
        self.points[dst_name] = dst
        self.segments.append(ArcSegment(src, dst, cx, cy, radius, start_angle, end_angle, ccw))

    def _infer_tangent(self, point_name: str) -> float:
        p = self.points[point_name]
        for seg in reversed(self.segments):
            if not isinstance(seg, LineSegment):
                continue
            if seg.p1.name == point_name:
                return math.degrees(math.atan2(seg.p2.y - p.y, seg.p2.x - p.x))
            if seg.p2.name == point_name:
                return math.degrees(math.atan2(p.y - seg.p1.y, p.x - seg.p1.x))
        return 0.0

    def _resolve(self, name: str) -> Point:
        p = self.points.get(name)
        if p is None:
            raise ValueError(f"Undefined point '{name}'")
        return p

    def _ensure_new_point(self, name: str) -> None:
        if name in self.points:
            raise ValueError(f"Duplicate point name '{name}'")

    @classmethod
    def _parse_params(cls, line: str) -> dict[str, str]:
        return {m.group(1).upper(): m.group(2) for m in cls.PARAM_RE.finditer(line)}

    @staticmethod
    def _need(params: dict[str, str], key: str) -> str:
        if key not in params:
            raise ValueError(f"Missing parameter {key}")
        return params[key]

    def bounding_box(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []

        if self.segments:
            for seg in self.segments:
                if isinstance(seg, CircleSegment):
                    xs.extend([seg.center.x - seg.radius, seg.center.x + seg.radius])
                    ys.extend([seg.center.y - seg.radius, seg.center.y + seg.radius])
                else:
                    for x, y in seg.polyline_points():
                        xs.append(x)
                        ys.append(y)
        else:
            for p in self.points.values():
                xs.append(p.x)
                ys.append(p.y)

        if not xs:
            return (0.0, 0.0, 1.0, 1.0)
        return (min(xs), min(ys), max(xs), max(ys))
