"""Independent contact geometry and dense parallel-curve error checks."""

import copy
import itertools
import math

import pytest

from cad_document import Document
from cad_geometry import distance, segment_distance
from cad_operations import finite_intersections, on_curve
from cad_script import ScriptEngine, document_script
from cad_snap import nearest_point, reference_points


def parabola(doc, id="bow", **kwargs):
    return doc.add("bezier", id=id, points=[(0, 0), (4, 4), (8, 4), (12, 0)], **kwargs)


def contains(points, expected, tolerance=1e-7):
    return any(distance(p, expected) < tolerance for p in points)


@pytest.mark.parametrize("angle", [0, 37, 90])
def test_ellipse_normal_tangent_and_nearest_in_world_space(angle):
    d = Document()
    d.add("ellipse", id="oval", x=30, y=-20, angle=angle, rx=10, ry=5)
    e = d.entities["oval"]
    theta = math.pi / 3
    q = (10 * math.cos(theta), 5 * math.sin(theta))
    normal = (math.cos(theta) / 10, math.sin(theta) / 5)
    length = math.hypot(*normal)
    normal_start = e.world(tuple(q[i] + 8 * normal[i] / length for i in (0, 1)))
    assert contains(
        [p for p, _ in reference_points(e, normal_start, perpendicular=True)],
        e.world(q),
    )
    assert nearest_point(e, normal_start) == pytest.approx(e.world(q), abs=1e-7)
    velocity = (-10 * math.sin(theta), 5 * math.cos(theta))
    tangent_start = e.world(tuple(q[i] + 2 * velocity[i] for i in (0, 1)))
    candidates = reference_points(e, tangent_start, tangent=True)
    assert len(candidates) == 2
    assert contains([p for p, _ in candidates], e.world(q))
    for p, mode in candidates:
        x, y = e.local(p)
        assert (x / 10) ** 2 + (y / 5) ** 2 == pytest.approx(1, abs=1e-9)
        dx, dy = e.local(tangent_start)
        assert (dx - x) * x / 100 + (dy - y) * y / 25 == pytest.approx(0, abs=1e-8)


def test_ellipse_inside_and_on_curve_do_not_supply_nonzero_tangents():
    d = Document()
    d.add("ellipse", id="oval", rx=10, ry=5)
    e = d.entities["oval"]
    assert reference_points(e, (0, 0), tangent=True) == []
    assert reference_points(e, (10, 0), tangent=True) == []
    assert reference_points(e, (5, 0), tangent=True) == []


def test_bezier_grips_are_not_object_snap_points():
    d = Document()
    parabola(d)
    e = d.entities["bow"]
    assert e.snap_points() == [(0, 0), (12, 0), (6, 3)]
    assert e.handles()[1:3] == [(4, 4), (8, 4)]
    assert not on_curve(e, (4, 4), 0.01)
    assert on_curve(e, (3, 2.25))


@pytest.mark.parametrize("angle", [0, 63])
def test_bezier_contact_roots_and_finite_nearest_endpoint(angle):
    d = Document()
    parabola(d, angle=angle, x=10, y=-4)
    e = d.entities["bow"]
    for mode, start in [("perpendicular", (6, 9)), ("tangent", (15, 3))]:
        result = reference_points(e, e.world(start), **{mode: True})
        assert contains([p for p, _ in result], e.world((6, 3)))
        for p, _ in result:
            x, y = e.local(p)
            assert y == pytest.approx(x * (1 - x / 12), abs=1e-8)
            assert -1e-8 <= x <= 12 + 1e-8
    assert nearest_point(e, e.world((-10, -10))) == pytest.approx(e.world((0, 0)))


@pytest.mark.parametrize("kind", ["line", "circle", "ellipse"])
def test_bezier_repeated_tangent_intersection_is_not_lost(kind):
    d = Document()
    parabola(d)
    if kind == "line":
        d.line(-10, 3, 20, 3, id="cut")
    elif kind == "circle":
        d.circle(6, 0, 3, id="cut")
    else:
        d.add("ellipse", x=6, rx=4, ry=3, id="cut")
    points = finite_intersections(d.entities["bow"], d.entities["cut"])
    assert len(points) == 1
    assert points[0] == pytest.approx((6, 3), abs=1e-7)
    d.line(0, 3, 5, 3, id="short")
    assert finite_intersections(d.entities["bow"], d.entities["short"]) == []


def test_ellipse_conic_intersections_and_chart_seam_tangency():
    d = Document()
    d.add("ellipse", rx=10, ry=5, id="wide")
    d.add("ellipse", rx=5, ry=10, id="tall")
    points = finite_intersections(d.entities["wide"], d.entities["tall"])
    assert len(points) == 4
    for x in (-math.sqrt(20), math.sqrt(20)):
        for y in (-math.sqrt(20), math.sqrt(20)):
            assert contains(points, (x, y))
    d.circle(0, 0, 5, id="circle")
    points = finite_intersections(d.entities["wide"], d.entities["circle"])
    assert len(points) == 2
    assert contains(points, (0, 5)) and contains(points, (0, -5))
    d.arc(0, 0, 5, 0, 100, id="sector")
    points = finite_intersections(d.entities["wide"], d.entities["sector"])
    assert len(points) == 1 and contains(points, (0, 5))
    assert finite_intersections(d.entities["wide"], d.entities["wide"]) == []


@pytest.mark.parametrize("angle", [0, 41])
def test_bezier_bezier_intersections_include_crossing_and_tangent(angle):
    d = Document()
    parabola(d, angle=angle, x=20, y=30)
    d.add(
        "bezier",
        id="cut",
        x=20,
        y=30,
        angle=angle,
        points=[(0, 1), (4, 1), (8, 1), (12, 1)],
    )
    e = d.entities["bow"]
    points = finite_intersections(e, d.entities["cut"])
    assert len(points) == 2
    assert contains(points, e.world((6 - math.sqrt(24), 1)))
    assert contains(points, e.world((6 + math.sqrt(24), 1)))
    d.entities["cut"].data["points"] = [(0, 3), (4, 3), (8, 3), (12, 3)]
    points = finite_intersections(e, d.entities["cut"])
    assert len(points) == 1 and contains(points, e.world((6, 3)))


@pytest.mark.parametrize("amount", [2, -2])
def test_ellipse_offset_is_normal_distance_not_enlarged_axes(amount):
    d = Document()
    d.add("ellipse", rx=10, ry=5, angle=31, x=30, y=-20, id="oval")
    source = d.entities["oval"].to_dict()
    id = d.offset("oval", amount, tolerance=0.005, linked=False)
    out = d.entities[id]
    assert out.kind == "polyline" and out.data["closed"]
    assert d.entities["oval"].to_dict() == source
    vertices = out.vertices()
    error = 0
    for i in range(1501):
        theta = 2 * math.pi * i / 1500
        x, y = 10 * math.cos(theta), 5 * math.sin(theta)
        nx, ny = math.cos(theta) / 10, math.sin(theta) / 5
        scale = amount / math.hypot(nx, ny)
        q = d.entities["oval"].world((x + nx * scale, y + ny * scale))
        error = max(
            error,
            min(
                segment_distance(q, a, b)
                for a, b in zip(vertices, vertices[1:] + vertices[:1])
            ),
        )
    assert error <= 0.005
    d.undo()
    assert list(d.entities) == ["oval"]
    d.redo()
    assert d.entities[id].to_dict() == out.to_dict()


@pytest.mark.parametrize("amount", [1, -1])
def test_bezier_offset_dense_chord_error_and_endpoint_normals(amount):
    d = Document()
    parabola(d, angle=27, x=12, y=8)
    source = d.entities["bow"]
    id = d.offset("bow", amount, tolerance=0.002, linked=False)
    vertices = d.entities[id].vertices()
    error = 0
    for i in range(1001):
        t = i / 1000
        x, y = 12 * t, 12 * t * (1 - t)
        vx, vy = 12, 12 - 24 * t
        scale = amount / math.hypot(vx, vy)
        q = source.world((x - vy * scale, y + vx * scale))
        error = max(
            error,
            min(segment_distance(q, a, b) for a, b in itertools.pairwise(vertices)),
        )
        if i in (0, 1000):
            assert q == pytest.approx(vertices[0 if i == 0 else -1])
    assert error <= 0.002
    assert not d.entities[id].data["closed"]


@pytest.mark.parametrize(
    "case",
    ["ellipse_cusp", "bezier_fold", "stationary", "budget", "precision", "overlap"],
)
def test_invalid_offsets_are_atomic(case):
    d = Document()
    d.add("ellipse", rx=10, ry=5, id="oval")
    parabola(d)
    id, amount, tolerance = "oval", -2.5, 0.01
    if case == "bezier_fold":
        id, amount = "bow", -8
    elif case == "stationary":
        d.entities["bow"].data["points"] = [(0, 0), (0, 0), (1, 1), (2, 0)]
        id, amount = "bow", 1
    elif case == "budget":
        amount, tolerance = 1, 1e-8
    elif case == "precision":
        d.entities["oval"].x = 1e12
        amount, tolerance = 1, 1e-5
    elif case == "overlap":
        d.entities["bow"].data["points"] = [(0, 0), (4, 4), (-4, 4), (0, 0)]
        id, amount = "bow", 0
    before = d.snapshot()
    history = len(d._undo)
    with pytest.raises(ValueError):
        d.offset(id, amount, tolerance=tolerance, linked=False)
    assert d.snapshot() == before and len(d._undo) == history


def test_offset_tolerance_controls_density_and_roundtrips(tmp_path):
    d = Document()
    parabola(d)
    loose = d.offset("bow", 1, tolerance=0.05, linked=False)
    fine = d.offset("bow", 1, tolerance=0.001, linked=False)
    assert len(d.entities[fine].data["points"]) > len(d.entities[loose].data["points"])
    path = tmp_path / "curve.gdraw"
    d.save(path)
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert Document.load(path).snapshot() == clone.snapshot() == d.snapshot()
    scripted = Document()
    ScriptEngine(scripted).execute(
        "ELLIPSE oval rx=10 ry=5\nOFFSET oval distance=1 tolerance=0.02"
    )
    assert (
        scripted.entities["oval_offset1"].data["offset_approximation"]["tolerance"]
        == 0.02
    )
    before = scripted.snapshot()
    with pytest.raises(ValueError):
        ScriptEngine(scripted).execute("OFFSET oval distance=1 tolerance=0")
    assert scripted.snapshot() == before


def test_straight_bezier_offset_and_nearest_are_exact():
    d = Document()
    d.add("bezier", points=[(0, 0), (1, 0), (2, 0), (3, 0)], id="straight")
    out = d.offset("straight", 2, tolerance=0.01, linked=False)
    assert d.entities[out].vertices() == [(0, 2), (3, 2)]
    assert nearest_point(d.entities["straight"], (1.2, 4)) == pytest.approx((1.2, 0))


def test_two_genuine_cubics_have_a_known_transverse_contact():
    d = Document()
    points = [(0, 0), (3, 5), (9, -3), (12, 0)]
    d.add("bezier", points=points, id="first")
    d.add("bezier", points=points, angle=90, x=6.75, y=-5.25, id="second")
    hits = finite_intersections(d.entities["first"], d.entities["second"])
    assert contains(hits, (6, 0.75))
    assert all(
        on_curve(d.entities["first"], p, 1e-7)
        and on_curve(d.entities["second"], p, 1e-7)
        for p in hits
    )


def test_genuine_cubic_pair_tangency_is_an_isolated_contact():
    d = Document()
    d.add("bezier", points=[(0, 0), (3, 5), (9, -3), (12, 0)], id="first")
    # Same monotone X(t); Y2(t)-Y1(t) = 3*(t-1/2)^2.
    d.add("bezier", points=[(0, 0.75), (3, 4.75), (9, -3.25), (12, 0.75)], id="second")
    hits = finite_intersections(d.entities["first"], d.entities["second"])
    assert len(hits) == 1 and contains(hits, (6, 0.75))


def test_approximation_metadata_scales_and_expires_after_reshaping():
    d = Document()
    parabola(d)
    id = d.offset("bow", 1, tolerance=0.01, linked=False)
    d.transform([id], scale=2)
    assert d.entities[id].data["offset_approximation"]["tolerance"] == 0.02
    d.set_units("cm")
    assert d.entities[id].data["offset_approximation"]["distance"] == pytest.approx(0.2)
    e = copy.deepcopy(d.entities[id])
    e.data["points"][0] = (-1, 0)
    d.replace(e)
    assert "offset_approximation" not in d.entities[id].data
    d.undo()
    assert d.entities[id].data["offset_approximation"]["tolerance"] == pytest.approx(
        0.002
    )
    with d.transaction("Drive approximated vertex"):
        d.constrain("coincident", [id + "@0", "bow@0"])
    assert "offset_approximation" not in d.entities[id].data


def test_locked_curve_offset_and_bad_metadata_are_rejected():
    d = Document()
    parabola(d)
    d.set_layer("0", locked=True)
    before = d.snapshot()
    with pytest.raises(ValueError, match="Unlock"):
        d.offset("bow", 1, linked=False)
    assert d.snapshot() == before
    d.set_layer("0", locked=False)
    with pytest.raises(ValueError, match="metadata"):
        d.add("polyline", points=[(0, 0), (1, 1)], offset_approximation="invalid")
    with pytest.raises(ValueError, match="metadata"):
        d.add("polyline", points=[(0, 0), (1, 1)], offset_approximation=None)


@pytest.mark.parametrize("t", [0, 0.2, 0.7, 1])
def test_cubic_intersections_at_known_parameters_and_endpoints(t):
    d = Document()
    points = [(0, 0), (3, 5), (9, -3), (12, 0)]
    q = tuple(
        sum(
            (1 - t) ** (3 - i) * t**i * (1, 3, 3, 1)[i] * points[i][j] for i in range(4)
        )
        for j in (0, 1)
    )
    from cad_geometry import rotate

    rotated = rotate(q, 137)
    d.add("bezier", points=points, id="a", x=50, y=-30)
    d.add(
        "bezier",
        points=points,
        id="b",
        x=50 + q[0] - rotated[0],
        y=-30 + q[1] - rotated[1],
        angle=137,
    )
    hits = finite_intersections(d.entities["a"], d.entities["b"])
    assert contains(hits, (50 + q[0], -30 + q[1]))


def test_eccentric_ellipse_uses_local_bounds_and_meets_chord_tolerance():
    d = Document()
    d.add("ellipse", rx=1000, ry=1, id="thin")
    id = d.offset("thin", 1, tolerance=0.1, linked=False)
    vertices = d.entities[id].vertices()
    assert len(vertices) < 8192
    angles = [2 * math.pi * i / 400 for i in range(401)] + [
        0.01 * i / 400 for i in range(401)
    ]
    for theta in angles:
        x, y = 1000 * math.cos(theta), math.sin(theta)
        nx, ny = math.cos(theta) / 1000, math.sin(theta)
        length = math.hypot(nx, ny)
        q = (x + nx / length, y + ny / length)
        assert (
            min(
                segment_distance(q, a, b)
                for a, b in zip(vertices, vertices[1:] + vertices[:1])
            )
            <= 0.1
        )


def test_coincident_curve_supports_do_not_create_pseudo_intersections():
    d = Document()
    points = [(0, 0), (3, 5), (9, -3), (12, 0)]
    d.add("bezier", points=points, id="a")
    d.add("bezier", points=points, id="b")
    assert finite_intersections(d.entities["a"], d.entities["b"]) == []
    d.entities["b"].data["points"] = points[::-1]
    assert finite_intersections(d.entities["a"], d.entities["b"]) == []
    d.add("ellipse", rx=10, ry=5, id="wide")
    d.add("ellipse", rx=5, ry=10, angle=90, id="same")
    assert finite_intersections(d.entities["wide"], d.entities["same"]) == []
    d.entities["same"].data.update(rx=10, ry=5)
    d.entities["same"].angle = 180
    assert finite_intersections(d.entities["wide"], d.entities["same"]) == []
