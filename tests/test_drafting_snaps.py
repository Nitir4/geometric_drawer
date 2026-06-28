"""Finite edge, perpendicular and tangent snap math independent of the GUI."""

import math

import pytest

from cad_document import Document
from cad_geometry import distance
from cad_operations import finite_intersections
from cad_script import ScriptEngine, document_script
from cad_snap import curve_parts, reference_points


def test_rotated_rectangle_edges_intersect_without_mutating_document():
    d = Document()
    d.rectangle(0, 0, 10, 6, angle=90, id="box")
    d.line(-10, 3, 4, 3, id="cut")
    before = d.snapshot()
    edges = list(curve_parts(d.entities["box"]))
    assert len(edges) == 4
    points = [
        p for edge in edges for p in finite_intersections(edge, d.entities["cut"])
    ]
    assert len(points) == 2
    assert any(p == pytest.approx((0, 3)) for p in points)
    assert any(p == pytest.approx((-6, 3)) for p in points)
    assert d.snapshot() == before


@pytest.mark.parametrize("closed", [False, True])
def test_polyline_closing_edge_and_repeated_vertex_handling(closed):
    d = Document()
    d.polyline([(0, 0), (0, 0), (10, 0), (10, 10)], closed=closed, id="poly")
    d.line(1, 5, 9, 5, id="cut")
    edges = list(curve_parts(d.entities["poly"]))
    assert len(edges) == (3 if closed else 2)
    points = [
        p for edge in edges for p in finite_intersections(edge, d.entities["cut"])
    ]
    assert points == [(5, 5)] if closed else points == []
    d.polyline([(0, 0), (10, 0), (10, 10), (0, 0)], closed=True, id="duplicate")
    assert len(list(curve_parts(d.entities["duplicate"]))) == 3


def test_perpendicular_foot_dot_product_and_finite_endpoints():
    d = Document()
    d.line(0, 0, 10, 10, id="diagonal")
    line = d.entities["diagonal"]
    result = reference_points(line, (6, 0), perpendicular=True)
    assert len(result) == 1
    q, mode = result[0]
    assert q == pytest.approx((3, 3))
    assert mode == "Perpendicular"
    assert sum(v * 10 for v in (q[0] - 6, q[1])) == pytest.approx(0, abs=1e-8)
    assert reference_points(line, (30, 0), perpendicular=True) == []
    assert reference_points(line, (3, 3), perpendicular=True) == []
    endpoint = reference_points(line, (20, 0), perpendicular=True)
    assert endpoint[0][0] == pytest.approx((10, 10))


def test_rectangle_perpendicular_candidates_follow_world_orientation():
    d = Document()
    d.rectangle(0, 0, 10, 6, angle=90, id="box")
    result = reference_points(d.entities["box"], (3, 4), perpendicular=True)
    assert len(result) == 2
    assert any(q == pytest.approx((0, 4)) for q, mode in result)
    assert any(q == pytest.approx((-6, 4)) for q, mode in result)


@pytest.mark.parametrize("reference", [(0, 0), (3, 0), (5, 0)])
def test_inside_on_circle_references_do_not_create_tangent_segments(reference):
    d = Document()
    d.circle(0, 0, 5, id="circle")
    assert reference_points(d.entities["circle"], reference, tangent=True) == []


def test_external_tangent_points_radius_and_right_angle():
    d = Document()
    d.circle(0, 0, 5, id="circle")
    reference = (10, 0)
    result = reference_points(d.entities["circle"], reference, tangent=True)
    assert len(result) == 2
    for q, mode in result:
        assert mode == "Tangent"
        assert q[0] == pytest.approx(2.5)
        assert abs(q[1]) == pytest.approx(math.sqrt(18.75))
        assert distance(q, (0, 0)) == pytest.approx(5)
        assert sum(
            a * b for a, b in zip(q, (reference[0] - q[0], -q[1]))
        ) == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("sweep,sign", [(90, 1), (-90, -1)])
def test_arc_tangent_candidates_clip_to_signed_sweep(sweep, sign):
    d = Document()
    d.arc(0, 0, 5, 0, sweep, id="arc")
    result = reference_points(d.entities["arc"], (10, 0), tangent=True)
    assert len(result) == 1
    assert result[0][0] == pytest.approx((2.5, sign * math.sqrt(18.75)))


def test_circular_normal_and_wrapped_arc_perpendicular():
    d = Document()
    d.circle(0, 0, 5, id="circle")
    result = reference_points(d.entities["circle"], (10, 0), perpendicular=True)
    assert [q for q, mode in result] == [(-5, 0), (5, 0)]
    assert reference_points(d.entities["circle"], (0, 0), perpendicular=True) == []
    d.arc(0, 0, 5, 0, 30, angle=350, id="wrapped")
    assert reference_points(d.entities["wrapped"], (10, 0), perpendicular=True) == [
        ((5, 0), "Perpendicular")
    ]


def test_tangent_placement_roundtrips_without_adding_hidden_constraints(tmp_path):
    d = Document()
    d.circle(0, 0, 5, id="circle")
    before = d.snapshot()
    points = reference_points(d.entities["circle"], (10, 0), tangent=True)
    assert d.snapshot() == before
    for q, mode in points:
        d.line(10, 0, *q)
    assert not d.constraints
    path = tmp_path / "tangents.gdraw"
    d.save(path)
    scripted = Document()
    ScriptEngine(scripted).execute(document_script(d))
    assert Document.load(path).snapshot() == scripted.snapshot() == d.snapshot()
