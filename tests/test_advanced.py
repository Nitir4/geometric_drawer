"""Behavioral coverage for compound regions, topology, free contacts and conditioning."""

import copy
import math

import ezdxf
import pytest
from shapely.geometry import LineString, Polygon

from cad_constraints import residual
from cad_document import Document
from cad_exchange import export_dxf, export_pdf, export_svg, import_dxf
from cad_features import curve_fillet
from cad_geometry import Entity, distance, line_intersection
from cad_operations import intersections
from cad_regions import (
    contains,
    definition,
    hatch_segments,
    polygon,
    rings_from_paths,
    triangles,
)
from cad_script import ScriptEngine, document_script

OUTER = [(0, 0), (20, 0), (20, 16), (0, 16)]
HOLE = [(5, 4), (15, 4), (15, 12), (5, 12)]
BOW = [(0, 0), (10, 10), (0, 10), (10, 0)]


def region_doc(hatch="solid", **kw):
    d = Document()
    r = d.region(OUTER, [HOLE], hatch=hatch, id="material", **kw)
    return d, r


def test_compound_material_hits_and_triangulation():
    d, r = region_doc()
    e = d.entities[r]
    assert polygon(e).area == pytest.approx(240)
    assert contains(e, (1, 1)) and not contains(e, (10, 8))
    assert e.hit_distance((1, 1)) == 0
    assert e.hit_distance((10, 8)) == pytest.approx(4)
    pieces = [Polygon(t) for t in triangles(e)]
    assert sum(p.area for p in pieces) == pytest.approx(240)
    assert all(p.intersection(Polygon(HOLE)).area < 1e-10 for p in pieces)


@pytest.mark.parametrize(
    "holes",
    [
        [[(22, 0), (23, 0), (23, 1)]],
        [HOLE, HOLE],
        [[(0, 2), (8, 2), (8, 8), (0, 8)]],
        [[(4, 4), (12, 12), (4, 12), (12, 4)]],
    ],
)
def test_invalid_region_atomic(holes):
    d = Document()
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.region(OUTER, holes)
    assert d.snapshot() == before


@pytest.mark.parametrize("hatch", ["lines", "cross", "custom"])
def test_patterns_clipped_to_material_and_transformed(hatch):
    kw = (
        {}
        if hatch != "custom"
        else {"hatch_definition": [[30, (1, 2), (-1.5, 3), [2, -1, 0, -1]]]}
    )
    d, r = region_doc(hatch, x=100, y=30, angle=37, spacing=2, **kw)
    e = d.entities[r]
    segments = hatch_segments(e)
    assert len(segments) > 8
    material = polygon(e)
    for a, b in segments:
        assert LineString([a, b]).difference(material.buffer(1e-8)).length < 1e-7
    original_lengths = sorted(distance(a, b) for a, b in segments)
    d.set_units("cm")
    scaled = hatch_segments(d.entities[r])
    assert sorted(distance(a, b) for a, b in scaled) == pytest.approx(
        [v / 10 for v in original_lengths], abs=1e-8
    )
    d.mirror([r], (0, 0), (1, 0))
    assert polygon(d.entities[r]).area == pytest.approx(2.4)
    assert sorted(
        distance(a, b) for a, b in hatch_segments(d.entities[r])
    ) == pytest.approx([v / 10 for v in original_lengths], abs=1e-8)


def test_dense_pattern_rejected_with_bound():
    d, r = region_doc("lines", spacing=1e-5)
    with pytest.raises(ValueError, match="density"):
        hatch_segments(d.entities[r], max_segments=50)


def test_nested_islands_and_crossing_boundaries():
    island = [(7, 6), (9, 6), (9, 8), (7, 8)]
    groups = rings_from_paths([HOLE, island, OUTER])
    assert sorted(len(g) for g in groups) == [1, 2]
    assert sum(Polygon(g[0], g[1:]).area for g in groups) == pytest.approx(244)
    with pytest.raises(ValueError, match="overlap"):
        rings_from_paths([OUTER, [(10, -5), (30, -5), (30, 5), (10, 5)]])


@pytest.mark.parametrize("hatch", ["solid", "lines", "cross", "custom"])
def test_region_native_code_dxf_svg_pdf(tmp_path, hatch):
    kw = (
        {}
        if hatch != "custom"
        else {"hatch_definition": [[0, (2, 1), (1, 3), [2, -1]]]}
    )
    d, r = region_doc(hatch, x=50, y=20, angle=30, spacing=3, **kw)
    native = tmp_path / "region.gdraw"
    d.save(native)
    assert Document.load(native).snapshot() == d.snapshot()
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert clone.snapshot() == d.snapshot()
    svg, pdf, dxf = [tmp_path / f"region.{ext}" for ext in ("svg", "pdf", "dxf")]
    export_svg(d, svg)
    export_pdf(d, pdf)
    export_dxf(d, dxf)
    assert 'fill-rule="evenodd"' in svg.read_text()
    assert pdf.read_bytes().startswith(b"%PDF")
    external = ezdxf.readfile(dxf)
    assert not external.audit().has_errors
    h = external.modelspace().query("HATCH")[0]
    assert len(h.paths) == 2
    h.discard_xdata("GEOMETRIC_DRAWER")
    external.saveas(dxf)
    loaded = import_dxf(dxf)
    restored = next(iter(loaded.entities.values()))
    assert restored.kind == "region"
    assert polygon(restored).symmetric_difference(polygon(d.entities[r])).area < 1e-8
    if hatch != "solid":
        assert len(definition(restored)) == len(definition(d.entities[r]))
        assert sum(
            distance(a, b) for a, b in hatch_segments(restored)
        ) == pytest.approx(
            sum(distance(a, b) for a, b in hatch_segments(d.entities[r])), abs=1e-6
        )


def test_cleanup_preserves_holes_pattern_and_pose():
    d, r = region_doc("cross", x=100, y=20, angle=30)
    ids = d.clean_offset(r, 1, as_regions=True)
    assert len(ids) == 1
    e = d.entities[ids[0]]
    assert len(e.data["rings"]) == 2 and definition(e, world=True) == definition(
        d.entities[r], world=True
    )
    assert not contains(e, d.entities[r].world((10, 8)))
    d.transform([r], dx=30, rotation=17)
    assert definition(d.entities[ids[0]], world=True) == definition(
        d.entities[r], world=True
    )


def test_topology_merge_remaps_descendants_and_split_ids(tmp_path):
    d = Document()
    root = d.polyline(BOW, closed=True, id="root")
    outputs = d.clean_offset(root, 0, as_regions=True)
    feature = d.feature_for(outputs[0])["id"]
    children = [d.clean_offset(i, 0.1, as_regions=True)[0] for i in outputs]
    child_features = [d.feature_for(i)["id"] for i in children]
    d.update_feature(feature, amount=2)
    merged = d.features[feature]["outputs"]
    assert len(merged) == 1 and merged[0] in outputs
    assert all(d.features[f]["sources"] == merged for f in child_features)
    assert any(e["merged"] for e in d.topology_events)
    d.undo()
    assert d.features[feature]["outputs"] == outputs
    d.redo()
    native = tmp_path / "topology.gdraw"
    d.save(native)
    d = Document.load(native)
    d.update_feature(feature, amount=0)
    split = d.features[feature]["outputs"]
    assert len(split) == 2 and merged[0] in split
    assert len(set(split)) == 2
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert clone.snapshot() == d.snapshot()
    d.set_units("cm")
    before_ids = list(d.features[feature]["outputs"])
    d.transform([root], dx=20, dy=15, rotation=80)
    assert d.features[feature]["outputs"] == before_ids
    d.validate()


def test_empty_cleanup_revival_and_retired_descendants():
    d = Document()
    root = d.rectangle(0, 0, 10, 10)
    out = d.clean_offset(root, 0, as_regions=True)[0]
    feature = d.feature_for(out)["id"]
    child = d.clean_offset(out, 1, as_regions=True)[0]
    child_feature = d.feature_for(child)["id"]
    d.update_feature(feature, amount=-10)
    assert d.features[feature]["outputs"] == []
    assert (
        out not in d.entities
        and child not in d.entities
        and child_feature not in d.features
    )
    d.update_feature(feature, amount=0)
    assert len(d.features[feature]["outputs"]) == 1
    assert d.features[feature]["outputs"][0] != out
    assert (
        child_feature not in d.features
    )  # retired branches are not silently recreated


def test_vanished_component_not_matched_to_distant_new_component():
    d = Document()
    root = d.polyline(BOW, closed=True)
    outputs = d.clean_offset(root, 0, as_regions=True)
    f = d.feature_for(outputs[0])["id"]
    with d.transaction():
        d.entities[root].data["points"] = [(1000, 0), (1010, 0), (1010, 10), (1000, 10)]
    assert not set(outputs).intersection(d.features[f]["outputs"])


def test_locked_topology_rolls_back_and_serial_validation():
    d = Document()
    root = d.polyline(BOW, closed=True)
    outputs = d.clean_offset(root, 0, as_regions=True)
    f = d.feature_for(outputs[0])["id"]
    d.set_layer("results")
    for i in outputs:
        d.entities[i].layer = "results"
    d.set_layer("results", locked=True)
    before = d.snapshot()
    with pytest.raises(ValueError, match="Unlock"):
        d.update_feature(f, amount=2)
    assert d.snapshot() == before
    with pytest.raises(ValueError, match="serial"), d.transaction():
        d.features[f]["serial"] = -1
    assert d.snapshot() == before


def test_free_tangent_finds_contacts_on_fixed_curves_and_report_is_readonly(tmp_path):
    d = Document()
    e = d.add("ellipse", rx=5, ry=3)
    line = d.line(-10, 3, 10, 3)
    d.constrain("fixed", [e])
    d.constrain("fixed", [line])
    c = d.constrain("free_tangent", [e, line], parameters=[0.08, 0.2])
    assert d.constraints[c]["parameters"] == pytest.approx([0.25, 0.5], abs=1e-7)
    assert max(abs(v) for v in residual(d, d.constraints[c])) < 1e-7
    before = d.snapshot()
    report = d.constraint_report()
    assert report["variables"] == 2 and report["dof"] == 0
    assert d.snapshot() == before
    path = tmp_path / "free.gdraw"
    d.save(path)
    assert Document.load(path).snapshot() == before
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert clone.snapshot() == before


@pytest.mark.parametrize("kind", ["ellipse", "arc", "bezier"])
def test_free_tangent_moves_line_and_keeps_finite_contact(kind):
    d = Document()
    if kind == "ellipse":
        e = d.add(kind, rx=5, ry=3)
    elif kind == "arc":
        e = d.arc(0, 0, 3, start=0, sweep=180)
    else:
        e = d.add(kind, points=[(-5, 0), (-2, 4), (2, 4), (5, 0)])
    line = d.line(-10, 4, 10, 4)
    d.constrain("fixed", [e])
    d.constrain("horizontal", [line])
    d.constrain("length", [line], value=20)
    c = d.constrain("free_tangent", [e, line], parameters=[0.1, 0.8])
    assert max(abs(v) for v in residual(d, d.constraints[c])) < 1e-7
    assert all(0 <= t <= 1 for t in d.constraints[c]["parameters"])
    assert distance(*d.entities[line].vertices()) == pytest.approx(20)
    assert not math.isclose(d.constraints[c]["parameters"][0], 0.1, abs_tol=1e-3)


def test_free_tangent_impossible_and_invalid_parameters_atomic():
    d = Document()
    a = d.circle(0, 0, 3)
    b = d.line(-10, 10, 10, 10)
    d.constrain("fixed", [a])
    d.constrain("fixed", [b])
    before = d.snapshot()
    with pytest.raises(ValueError, match="Conflicting"):
        d.constrain("free_tangent", [a, b])
    assert d.snapshot() == before
    with pytest.raises(ValueError, match="parameters"):
        d.constrain("free_tangent", [a, b], parameters=[-1, 0.5])
    assert d.snapshot() == before


@pytest.mark.parametrize("origin", [0, 1e9])
def test_nearly_parallel_line_intersection(origin):
    a, b = (origin, origin), (origin + 1, origin + 1)
    c, d = (origin, origin + 1), (origin + 1, origin + 2 + 1e-6)
    point, t, u = line_intersection(a, b, c, d)
    assert math.isfinite(t) and t == pytest.approx(u)
    assert distance(point, (a[0] + t, a[1] + t)) < 1e-5
    with pytest.raises(ValueError):
        line_intersection((0, 0), (1, 1), (0, 1), (1, 2))


@pytest.mark.parametrize("radius", [1e-5, 1, 1e9])
def test_circle_contacts_near_tangency(radius):
    a = Entity("a", "circle", data={"radius": radius})
    b = Entity("b", "circle", x=2 * radius, data={"radius": radius})
    contacts = intersections(a, b)
    assert len(contacts) == 1 and distance(contacts[0], (radius, 0)) <= max(
        1e-9, radius * 1e-14
    )
    b.x += max(1e-7, radius * 1e-7)
    assert not intersections(a, b)
    b.x = 2 * radius - radius * 1e-4
    contacts = intersections(a, b)
    assert len(contacts) == 2
    assert all(
        abs(distance(p, (0, 0)) - radius) <= max(1e-9, radius * 1e-14) for p in contacts
    )


@pytest.mark.parametrize("origin,radius", [(0, 1e-5), (0, 2), (1e9, 2)])
def test_curve_fillet_translated_and_small(origin, radius):
    line = Entity(
        "line", "line", x=origin, y=origin, data={"points": [(0, 0), (10 * radius, 0)]}
    )
    ellipse = Entity(
        "oval",
        "ellipse",
        x=origin + 5 * radius,
        y=origin + 5 * radius,
        data={"rx": 4 * radius, "ry": 4 * radius},
    )
    original = copy.deepcopy((line.to_dict(), ellipse.to_dict()))
    legs = curve_fillet(
        line, ellipse, radius, pick=(origin + 5 * radius, origin + radius)
    )
    arc = legs[2]
    assert arc.data["radius"] == radius
    assert abs(arc.y - origin - radius) <= max(1e-8, 8 * math.ulp(origin))
    assert (line.to_dict(), ellipse.to_dict()) == original


@pytest.mark.parametrize("style,area", [(0, 244), (1, 240), (2, 320)])
def test_external_hatch_island_styles(tmp_path, style, area):
    drawing = ezdxf.new("R2010")
    drawing.units = 4
    h = drawing.modelspace().add_hatch(dxfattribs={"hatch_style": style})
    island = [(7, 6), (9, 6), (9, 8), (7, 8)]
    for index, ring in enumerate((OUTER, HOLE, island)):
        h.paths.add_polyline_path(ring, is_closed=True, flags=1 if index == 0 else 0)
    path = tmp_path / "islands.dxf"
    drawing.saveas(path)
    result = import_dxf(path)
    assert sum(polygon(e).area for e in result.entities.values()) == pytest.approx(area)


def test_close_polynomial_contacts_do_not_add_phantom_middle_root():
    from numpy.polynomial import Polynomial

    from cad_curves import roots

    p = Polynomial.fromroots([0.5 - 1e-7, 0.5 + 1e-7])
    result = roots(p)
    assert len(result) == 2
    assert result == pytest.approx([0.5 - 1e-7, 0.5 + 1e-7], abs=2e-9)
    assert roots(Polynomial.fromroots([0.5, 0.5])) == [0.5]


def test_bezier_coefficients_invariant_under_large_local_translation():
    from cad_curves import bezier_polynomials

    origin = 1e9
    a = Entity("a", "bezier", data={"points": [(0, 0), (1, 2), (3, -2), (4, 0)]})
    b = copy.deepcopy(a)
    b.data["points"] = [(x + origin, y + origin) for x, y in a.data["points"]]
    first, second = bezier_polynomials(a), bezier_polynomials(b)
    for p, q in zip(first, second):
        assert list(p.coef[1:]) == list(q.coef[1:])
        for t in (0, 0.17, 0.5, 0.83, 1):
            assert q(t) - origin == pytest.approx(p(t), abs=2 * math.ulp(origin))


def test_sharp_fillet_topology_retires_and_recreates_connector():
    d = Document()
    a, b = d.line(0, 0, 20, 0), d.line(20, 0, 20, 20)
    arc = d.corner(a, b, 2)
    f = d.feature_for(arc)["id"]
    dimension = d.dimension(arc)
    d.update_feature(f, amount=0)
    assert len(d.features[f]["outputs"]) == 2 and arc not in d.entities
    assert "ref" not in d.entities[dimension].data
    d.update_feature(f, amount=2)
    assert len(d.features[f]["outputs"]) == 3
    assert d.features[f]["outputs"][-1] != arc
