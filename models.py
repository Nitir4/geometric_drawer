from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    name: str
    x: float
    y: float


class Segment:
    def polyline_points(self, resolution: int = 180) -> list[tuple[float, float]]:
        raise NotImplementedError


@dataclass
class LineSegment(Segment):
    p1: Point
    p2: Point

    def polyline_points(self, resolution: int = 180) -> list[tuple[float, float]]:
        return [(self.p1.x, self.p1.y), (self.p2.x, self.p2.y)]


@dataclass
class CircleSegment(Segment):
    center: Point
    radius: float

    def polyline_points(self, resolution: int = 180) -> list[tuple[float, float]]:
        steps = max(36, resolution)
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            angle = 2.0 * math.pi * i / steps
            points.append(
                (
                    self.center.x + self.radius * math.cos(angle),
                    self.center.y + self.radius * math.sin(angle),
                )
            )
        return points


@dataclass
class ArcSegment(Segment):
    p_from: Point
    p_to: Point
    cx: float
    cy: float
    radius: float
    start_angle: float
    end_angle: float
    ccw: bool

    def polyline_points(self, resolution: int = 180) -> list[tuple[float, float]]:
        sweep_deg = abs(self.end_angle - self.start_angle)
        steps = max(12, int(max(1.0, sweep_deg) * (resolution / 360.0)))
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            angle = math.radians(self.start_angle + (self.end_angle - self.start_angle) * t)
            points.append((self.cx + self.radius * math.cos(angle), self.cy + self.radius * math.sin(angle)))
        return points
