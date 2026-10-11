"""Independent geometry, corner selection and finite intersection regressions."""

import math

import pytest

from cad_document import Document
from cad_geometry import distance
from cad_operations import finite_intersections, on_curve
from cad_script import ScriptEngine, ScriptError, document_script


def endpoints_match(actual, expected):
    for wanted in expected:
        assert any(distance(p, wanted) < 1e-7 for p in actual)


@pytest.mark.parametrize("fillet", [True, False])
def test_separated_legs_extend_to_the_connector_and_undo(fillet):
    d = Document()
    d.line(7, 0, 20, 0, id="a")
    d.line(0, 9, 0, 20, id="b")
    before = d.snapshot()
    connector = d.corner("a", "b", 5, fillet=fillet, linked=False)
    endpoints_match(d.entities["a"].vertices(), [(5, 0), (20, 0)])
    endpoints_match(d.entities["b"].vertices(), [(0, 5), (0, 20)])
    e = d.entities[connector]
    if fillet:
        assert (e.x, e.y) == pytest.approx((5, 5))
        assert abs(e.data["sweep"]) == pytest.approx(90)
        endpoints_match(e.handles()[1:], [(5, 0), (0, 5)])
    else:
        endpoints_match(e.vertices(), [(5, 0), (0, 5)])
    d.undo()
    assert d.snapshot() == before
    d.redo()
    assert connector in d.entities


@pytest.mark.parametrize("sx,sy", [(1, 1), (-1, 1), (-1, -1), (1, -1)])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("fillet", [True, False])
def test_crossing_lines_keep_the_picked_corner_for_both_endpoint_orders(
    sx, sy, reverse, fillet
):
    d = Document()
    a, b = [(-20, 0), (20, 0)], [(0, -20), (0, 20)]
    if reverse:
        a.reverse()
        b.reverse()
    d.line(*a[0], *a[1], id="a")
    d.line(*b[0], *b[1], id="b")
    connector = d.corner(
        "a", "b", 5, fillet=fillet, pick=(sx * 10, sy * 10), linked=False
    )
    endpoints_match(d.entities["a"].vertices(), [(sx * 5, 0), (sx * 20, 0)])
    endpoints_match(d.entities["b"].vertices(), [(0, sy * 5), (0, sy * 20)])
    e = d.entities[connector]
    if fillet:
        assert (e.x, e.y) == pytest.approx((sx * 5, sy * 5))
        assert e.data["radius"] == 5
        endpoints_match(e.handles()[1:], [(sx * 5, 0), (0, sy * 5)])
    else:
        endpoints_match(e.vertices(), [(sx * 5, 0), (0, sy * 5)])


def test_oblique_fillet_tangency_and_distance_are_independently_correct():
    d = Document()
    d.line(0, 0, 20, 0, id="a")
    d.line(0, 0, 10, 10 * math.sqrt(3), id="b")
    connector = d.corner("a", "b", 2, linked=False)
    arc = d.entities[connector]
    assert (arc.x, arc.y) == pytest.approx((2 * math.sqrt(3), 2))
    assert abs(arc.data["sweep"]) == pytest.approx(120)
    for line in (d.entities["a"], d.entities["b"]):
        tangent, far = line.vertices()
        assert distance(tangent, (arc.x, arc.y)) == pytest.approx(2)
        radius = tangent[0] - arc.x, tangent[1] - arc.y
        leg = far[0] - tangent[0], far[1] - tangent[1]
        assert sum(x * y for x, y in zip(radius, leg)) == pytest.approx(0, abs=1e-7)


@pytest.mark.parametrize("pick", [None, (0, 10), (10, 0), (0, 0)])
def test_ambiguous_corner_picks_fail_atomically(pick):
    d = Document()
    d.line(-20, 0, 20, 0, id="a")
    d.line(0, -20, 0, 20, id="b")
    before = d.snapshot()
    with pytest.raises(ValueError, match="pick|Pick"):
        d.corner("a", "b", 5, pick=pick, linked=False)
    assert d.snapshot() == before


@pytest.mark.parametrize("kind", ["fixed", "coincident"])
def test_constraint_projection_cannot_disconnect_a_corner(kind):
    d = Document()
    d.line(0, 0, 20, 0, id="a")
    d.line(0, 0, 0, 20, id="b")
    d.constrain(kind, ["a"] if kind == "fixed" else ["a@0", "b@0"])
    before = d.snapshot()
    with pytest.raises(ValueError, match="Driving constraints conflict"):
        d.corner("a", "b", 5, linked=False)
    assert d.snapshot() == before


def test_compatible_direction_constraints_and_native_script_roundtrip(tmp_path):
    d = Document()
    d.line(-20, 0, 20, 0, id="a")
    d.line(0, -20, 0, 20, id="b")
    d.constrain("horizontal", ["a"])
    d.constrain("vertical", ["b"])
    ScriptEngine(d).execute("FILLET a b radius=5 x=-10 y=10 linked=false")
    endpoints_match(d.entities["a"].vertices(), [(-5, 0), (-20, 0)])
    path = tmp_path / "corner.gdraw"
    d.save(path)
    clone = Document.load(path)
    scripted = Document()
    ScriptEngine(scripted).execute(document_script(d))
    assert clone.snapshot() == scripted.snapshot() == d.snapshot()


@pytest.mark.parametrize(
    "command", ["FILLET a b radius=5 x=10", "CHAMFER a b distance=5 y=10"]
)
def test_incomplete_script_pick_rolls_back_prior_edits(command):
    d = Document()
    d.line(0, 0, 20, 0, id="a")
    d.line(0, 0, 0, 20, id="b")
    before = d.snapshot()
    with pytest.raises(ScriptError):
        ScriptEngine(d).execute("MOVE a dx=3\n" + command)
    assert d.snapshot() == before


def test_finite_line_circle_intersections_clip_the_line_and_tangency():
    d = Document()
    d.circle(0, 0, 5, id="circle")
    d.line(-10, 3, 10, 3, id="line")
    endpoints_match(
        finite_intersections(d.entities["line"], d.entities["circle"]),
        [(-4, 3), (4, 3)],
    )
    d.line(-2, 3, 2, 3, id="short")
    assert finite_intersections(d.entities["short"], d.entities["circle"]) == []
    d.line(-10, 5, 10, 5, id="tangent")
    assert finite_intersections(d.entities["tangent"], d.entities["circle"]) == [(0, 5)]
    d.line(-10, 5.001, 10, 5.001, id="miss")
    assert finite_intersections(d.entities["miss"], d.entities["circle"]) == []


def test_long_line_small_circle_does_not_lose_chord_to_cancellation():
    d = Document()
    d.circle(0, 0, 5, id="circle")
    d.line(-1e9, 3, 1e9, 3, id="line")
    points = finite_intersections(d.entities["line"], d.entities["circle"])
    assert len(points) == 2
    endpoints_match(points, [(-4, 3), (4, 3)])


@pytest.mark.parametrize("orientation,sweep", [(350, 30), (10, -30)])
def test_wrapped_arc_intersections_clip_missing_sector_and_include_endpoints(
    orientation, sweep
):
    d = Document()
    d.arc(0, 0, 5, 0, sweep, angle=orientation, id="arc")
    d.line(-10, 0, 10, 0, id="line")
    points = finite_intersections(d.entities["arc"], d.entities["line"])
    assert points == [(5, 0)]
    for endpoint in d.entities["arc"].handles()[1:]:
        assert on_curve(d.entities["arc"], endpoint)
    assert not on_curve(d.entities["arc"], (-5, 0))


def test_circle_circle_arc_and_coincident_supports():
    d = Document()
    d.circle(0, 0, 5, id="a")
    d.circle(6, 0, 5, id="b")
    endpoints_match(
        finite_intersections(d.entities["a"], d.entities["b"]), [(3, 4), (3, -4)]
    )
    d.arc(0, 0, 5, 0, 180, id="arc")
    points = finite_intersections(d.entities["arc"], d.entities["b"])
    assert len(points) == 1
    assert points[0] == pytest.approx((3, 4))
    assert finite_intersections(d.entities["a"], d.entities["a"]) == []


def test_long_line_does_not_enlarge_an_arcs_missing_sector():
    d = Document()
    d.arc(0, 0, 5, 0, 20, id="arc")
    d.line(-1e9, 3, 1e9, 3, id="line")
    assert finite_intersections(d.entities["line"], d.entities["arc"]) == []


def test_large_radius_near_tangent_retains_two_distinct_intersections():
    from decimal import Decimal, localcontext

    d = Document()
    radius, y = 1e9, 1e9 - 0.1
    d.circle(0, 0, radius, id="circle")
    d.line(-1e6, y, 1e6, y, id="line")
    points = finite_intersections(d.entities["line"], d.entities["circle"])
    with localcontext() as context:
        context.prec = 50
        chord = float(
            (Decimal.from_float(radius) ** 2 - Decimal.from_float(y) ** 2).sqrt()
        )
    assert len(points) == 2
    assert points[0] == pytest.approx((-chord, y), rel=1e-12, abs=1e-7)
    assert points[1] == pytest.approx((chord, y), rel=1e-12, abs=1e-7)
