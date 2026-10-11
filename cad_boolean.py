"""Planar material Boolean operations with explicit sampled-curve tolerance."""

import copy

from shapely.geometry import Polygon
from shapely.ops import unary_union

try:
    from .cad_geometry import EPS, Entity, positive
    from .cad_regions import polygon
except ImportError:
    from cad_geometry import EPS, Entity, positive
    from cad_regions import polygon


def material(e, tolerance=0.01):
    if e.kind == "region":
        shape = polygon(e)
    elif e.kind == "rectangle" or e.kind == "polyline" and e.data.get("closed"):
        shape = Polygon(e.vertices())
    elif e.kind in ("circle", "ellipse") and abs(e.data.get("sweep", 360)) >= 360 - EPS:
        try:
            from .cad_features import cleaned_offset
        except ImportError:
            from cad_features import cleaned_offset
        return polygon(cleaned_offset(e, 0, tolerance, as_regions=True)[0])
    else:
        raise ValueError(
            "Material needs a region or closed rectangle/polyline/circle/ellipse."
        )
    if not shape.is_valid or shape.is_empty or shape.area <= EPS**2:
        raise ValueError(
            "Invalid material boundary; use Clean offset to repair it first."
        )
    return shape


def region_outputs(geometry, frame, tolerance=0.01):
    """Keep all material islands and holes; discard zero-area intersection contacts."""
    positive(tolerance)
    parts = []

    def collect(g):
        if g.is_empty:
            return
        if g.geom_type == "Polygon":
            parts.append(g)
        elif hasattr(g, "geoms"):
            for child in g.geoms:
                collect(child)

    collect(geometry)
    if (
        len(parts) > 128
        or sum(
            len(g.exterior.coords) + sum(len(r.coords) for r in g.interiors)
            for g in parts
        )
        > 10000
    ):
        raise ValueError("Boolean output exceeds 128 components/10000 vertices.")
    parts.sort(key=lambda g: frame.local(g.representative_point().coords[0]))
    style = {
        k: copy.deepcopy(v)
        for k, v in frame.data.items()
        if k in ("hatch", "hatch_angle", "spacing", "hatch_definition", "hatch_name")
    }
    result = []
    for g in parts:
        data = dict(
            style,
            rings=[
                [frame.local(p) for p in list(g.exterior.coords)[:-1]],
                *[[frame.local(p) for p in list(r.coords)[:-1]] for r in g.interiors],
            ],
            boolean_tolerance=tolerance,
        )
        result.append(
            Entity(
                "boolean", "region", frame.x, frame.y, frame.angle, frame.layer, data
            ).validate()
        )
    return result


def boolean_geometry(sources, operation="union", tolerance=0.01):
    tolerance = positive(tolerance)
    if (
        operation not in ("union", "difference", "intersection")
        or not 2 <= len(sources) <= 64
    ):
        raise ValueError(
            "Boolean needs 2–64 closed inputs and union/difference/intersection."
        )
    shapes = [material(e, tolerance) for e in sources]
    if operation == "union":
        result = unary_union(shapes)
    elif operation == "difference":
        result = shapes[0].difference(unary_union(shapes[1:]))
    else:
        result = shapes[0]
        for g in shapes[1:]:
            result = result.intersection(g)
    return region_outputs(result, sources[0], tolerance)
