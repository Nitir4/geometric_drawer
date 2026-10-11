"""Design-intent, material Boolean and analytic trimming acceptance."""

import math
import xml.etree.ElementTree as ET

import ezdxf
import pytest

from cad_document import Document
from cad_exchange import export_dxf, export_pdf, export_svg, import_dxf
from cad_features import parameter_curve
from cad_geometry import distance
from cad_operations import on_curve
from cad_parameters import evaluate
from cad_regions import polygon
from cad_script import ScriptEngine, document_script
from cad_trimming import portion


def replay(d, tmp_path):
    native = tmp_path / "design.gdraw"
    d.save(native)
    assert Document.load(native).snapshot() == d.snapshot()
    other = Document()
    ScriptEngine(other).execute(document_script(d))
    assert other.snapshot() == d.snapshot()


def test_parameters_drive_geometry_dependencies_units_and_replay(tmp_path):
    d = Document()
    circle = d.circle(4, 5, 2)
    d.set_parameter("base", "10")
    d.set_parameter("diameter", "2*base")
    d.bind(circle, "radius", "diameter/2")
    d.bind(circle, "x", "base+4")
    assert d.entities[circle].data["radius"] == 10
    d.set_parameter("base", "15")
    assert d.entities[circle].data["radius"] == 15
    assert d.entities[circle].x == 19
    d.set_units("cm")
    assert d.entities[circle].data["radius"] == pytest.approx(1.5)
    assert d.parameter_values()["diameter"] == pytest.approx(3)
    assert d.parameters["base"]["expression"] == "15"
    d.set_parameter("extra", "base+1", units="cm")
    assert d.parameter_values()["extra"] == pytest.approx(2.5)
    replay(d, tmp_path)
    state = d.snapshot()
    d.unbind(circle, "x")
    assert d.undo() and d.snapshot() == state
    assert d.redo() and len(d.bindings) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "base+1",
        "unknown",
        '__import__("os")',
        "1/0",
        "2**100",
        "sqrt(-1)",
        "True",
        "pi.real",
    ],
)
def test_parameter_failure_is_atomic(expression):
    d = Document()
    d.set_parameter("base", "2")
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_parameter("base", expression)
    assert d.snapshot() == before


def test_parameter_cycle_removal_conflicts_and_locked_targets():
    d = Document()
    d.set_parameter("a", "2")
    d.set_parameter("b", "a*2")
    before = d.snapshot()
    for action in (lambda: d.set_parameter("a", "b"), lambda: d.remove_parameter("a")):
        with pytest.raises(ValueError):
            action()
        assert d.snapshot() == before
    circle = d.circle(0, 0, 2)
    d.constrain("fixed", [circle])
    d.bind(circle, "radius", "a")
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_parameter("a", "3")
    assert d.snapshot() == before
    d.set_layer("0", locked=True)
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_parameter("a", "4")
    assert d.snapshot() == before


def test_driver_constraint_feature_vertex_and_deletion(tmp_path):
    d = Document()
    d.set_parameter("size", "10")
    source = d.circle(0, 0, 5)
    rule = d.constrain("radius", [source], 5)
    d.bind(rule, "value", "size/2", target="constraint")
    child = d.offset(source, 1)
    feature = d.feature_for(child)["id"]
    d.bind(feature, "amount", "size/10", target="feature")
    d.set_parameter("size", "20")
    assert d.entities[source].data["radius"] == pytest.approx(10)
    assert d.entities[child].data["radius"] == pytest.approx(12)
    line = d.line(0, 10, 8, 10)
    d.bind(line, "v1.x", "size")
    assert d.entities[line].vertices()[1][0] == pytest.approx(20)
    replay(d, tmp_path)
    d.delete([source, line])
    assert not d.bindings and not d.constraints and not d.features
    d.clear()
    assert not d.parameters


@pytest.mark.parametrize("degrees", [45, -60, 180, 0])
def test_directed_angle_between_lines(degrees):
    d = Document()
    a = d.line(0, 0, 10, 0)
    b = d.line(0, 2, 10, 2)
    d.constrain("fixed", [a])
    d.constrain("angle_between", [a, b], degrees)
    p, q = d.entities[b].vertices()
    theta = math.atan2(q[1] - p[1], q[0] - p[0])
    assert math.sin(theta) == pytest.approx(math.sin(math.radians(degrees)), abs=1e-7)
    assert math.cos(theta) == pytest.approx(math.cos(math.radians(degrees)), abs=1e-7)
    assert d.constraint_report()["max_residual"] <= 1e-7


def test_symmetry_arc_endpoints_signed_sweep_equal_radii(tmp_path):
    d = Document()
    axis = d.line(0, -20, 0, 20)
    p = d.add("point", x=4, y=3)
    q = d.add("point", x=-2, y=2)
    d.constrain("fixed", [axis])
    d.constrain("fixed", [p])
    d.constrain("symmetry", [p, q, axis])
    assert (d.entities[q].x, d.entities[q].y) == pytest.approx((-4, 3), abs=1e-7)
    arc = d.arc(30, 0, 5, 0, 90)
    d.constrain("arc_start", [arc], 20)
    d.constrain("arc_sweep", [arc], -60)
    endpoint = d.add("point", x=35, y=0)
    d.constrain("coincident", [f"{arc}@2", endpoint])
    assert (d.entities[endpoint].x, d.entities[endpoint].y) == pytest.approx(
        d.entities[arc].handles()[2], abs=1e-7
    )
    circle = d.circle(50, 0, 6)
    d.constrain("equal_radius", [arc, circle])
    assert d.entities[arc].data["radius"] == pytest.approx(
        d.entities[circle].data["radius"], abs=1e-7
    )
    replay(d, tmp_path)


def test_region_vertex_constraints_and_ellipse_axes(tmp_path):
    d = Document()
    region = d.region([(0, 0), (10, 0), (10, 10), (0, 10)])
    point = d.add("point", x=-1, y=0)
    d.constrain("fixed", [point])
    d.constrain("coincident", [f"{region}@0", point])
    assert d.entities[region].vertices()[0] == pytest.approx((-1, 0), abs=1e-7)
    assert polygon(d.entities[region]).is_valid
    ellipse = d.add("ellipse", x=30, rx=8, ry=3)
    d.constrain("rx", [ellipse], 10)
    d.constrain("ry", [ellipse], 4)
    assert d.entities[ellipse].data["rx"] == pytest.approx(10, abs=1e-7)
    replay(d, tmp_path)


@pytest.mark.parametrize(
    "operation,area", [("union", 150), ("intersection", 50), ("difference", 50)]
)
def test_boolean_area_regeneration_native_code_and_units(operation, area, tmp_path):
    d = Document()
    a = d.rectangle(0, 0, 10, 10)
    b = d.rectangle(5, 0, 10, 10)
    result = d.boolean([a, b], operation)
    assert sum(polygon(d.entities[i]).area for i in result) == pytest.approx(area)
    assert all(d.entities[i].construction for i in (a, b))
    assert len(d.features) == 1
    replay(d, tmp_path)
    with d.transaction("source change"):
        d.entities[b].x = 20
    feature = next(iter(d.features.values()))
    expected = 200 if operation == "union" else 100 if operation == "difference" else 0
    assert sum(
        polygon(d.entities[i]).area for i in feature["outputs"]
    ) == pytest.approx(expected)
    d.set_units("cm")
    assert sum(
        polygon(d.entities[i]).area for i in feature["outputs"]
    ) == pytest.approx(expected / 100)
    replay(d, tmp_path)


def test_boolean_holes_islands_empty_revival_and_locked_rollback():
    d = Document()
    a = d.rectangle(0, 0, 20, 20)
    b = d.rectangle(5, 5, 10, 10)
    child = d.boolean([a, b], "difference")[0]
    assert len(d.entities[child].data["rings"]) == 2
    assert polygon(d.entities[child]).area == pytest.approx(300)
    d.detach_feature(child)
    assert not d.features
    a2 = d.rectangle(50, 0, 2, 2)
    b2 = d.rectangle(60, 0, 2, 2)
    assert len(d.boolean([a2, b2], linked=False)) == 2
    feature_outputs = d.boolean([a2, b2], "intersection")
    assert not feature_outputs
    feature = next(iter(d.features.values()))
    with d.transaction("revive"):
        d.entities[b2].x = 51
    assert len(feature["outputs"]) == 1
    d.set_layer("0", locked=True)
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.boolean([a, b])
    assert d.snapshot() == before


def test_boolean_curves_tolerance_and_invalid_inputs():
    d = Document()
    a = d.circle(0, 0, 10)
    b = d.rectangle(-20, -20, 40, 40)
    result = d.boolean([a, b], "intersection", tolerance=0.001, linked=False)
    area = polygon(d.entities[result[0]]).area
    assert abs(area - math.pi * 100) < 0.1
    line = d.line(0, 0, 10, 0)
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.boolean([a, line])
    assert d.snapshot() == before


def test_exact_cubic_trim_and_general_polyline_cut():
    d = Document()
    b = d.add("bezier", points=[(0, 0), (0, 4), (4, 4), (4, 0)])
    original = parameter_curve(d.entities[b])
    cutter = d.line(2, -10, 2, 10)
    result = d.trim_extend(b, cutter, (0, 0))
    assert result == [b]
    retained = parameter_curve(d.entities[b])
    for i in range(21):
        assert retained(i / 20)[0] == pytest.approx(
            original(0.5 + 0.5 * i / 20)[0], abs=1e-8
        )
    poly = d.polyline([(0, 10), (10, 10), (20, 10), (30, 10)])
    box = d.rectangle(8, 5, 14, 10)
    outputs = d.trim_extend(poly, box, (15, 10))
    assert len(outputs) == 2
    assert d.entities[outputs[0]].vertices()[-1] == pytest.approx((8, 10))
    assert d.entities[outputs[1]].vertices()[0] == pytest.approx((22, 10))


@pytest.mark.parametrize(
    "ry,orientation,sweep", [(3, 0, 180), (12, 35, -180), (3, 75, -270)]
)
def test_partial_ellipse_trim_bounds_contacts_and_exchange(
    ry, orientation, sweep, tmp_path
):
    d = Document()
    ellipse = d.add("ellipse", rx=8, ry=ry, angle=orientation, start=20, sweep=sweep)
    e = d.entities[ellipse]
    p = portion(e, 0.2, 0.8)
    d.entities[ellipse] = p
    p.id = ellipse
    points = p.paths(10000)[0]
    bbox = p.bounds()
    assert all(
        bbox[0] - 1e-8 <= x <= bbox[2] + 1e-8 and bbox[1] - 1e-8 <= y <= bbox[3] + 1e-8
        for x, y in points
    )
    assert all(
        on_curve(p, q, 1e-7) for q in p.snap_points() if distance(q, (p.x, p.y)) > 1e-8
    )
    export_svg(d, tmp_path / "curve.svg")
    root = ET.parse(tmp_path / "curve.svg").getroot()
    assert not any(n.tag.endswith("ellipse") for n in root.iter())
    assert any(" A " in n.attrib.get("d", "") for n in root.iter())
    export_pdf(d, tmp_path / "curve.pdf")
    assert (tmp_path / "curve.pdf").read_bytes().startswith(b"%PDF")
    export_dxf(d, tmp_path / "curve.dxf")
    src = ezdxf.readfile(tmp_path / "curve.dxf")
    assert len(src.modelspace().query("ELLIPSE")) == 1
    loaded = import_dxf(tmp_path / "curve.dxf")
    other = next(e for e in loaded.entities.values() if e.kind == "ellipse")
    # DXF traverses counterclockwise; comparing the material locus permits reversal.
    assert other.bounds() == pytest.approx(p.bounds(), abs=1e-7)
    a, b = other.paths(200)[0][0], other.paths(200)[0][-1]
    ends = (points[0], points[-1])
    assert min(distance(a, q) for q in ends) < 1e-7
    assert min(distance(b, q) for q in ends) < 1e-7
    replay(d, tmp_path)


def test_full_ellipse_trim_and_extend_path():
    d = Document()
    ellipse = d.add("ellipse", rx=10, ry=5)
    cutter = d.line(0, -20, 0, 20)
    assert d.trim_extend(ellipse, cutter, (10, 0)) == [ellipse]
    e = d.entities[ellipse]
    assert e.kind == "ellipse" and e.data["sweep"] == pytest.approx(180)
    assert e.bounds() == pytest.approx((-10, -5, 0, 5), abs=1e-7)
    poly = d.polyline([(0, 10), (10, 10), (15, 15)])
    boundary = d.line(30, 0, 30, 40)
    d.trim_extend(poly, boundary, (15, 15), True)
    assert d.entities[poly].vertices()[-1] == pytest.approx((30, 30))
    cubic = d.add("bezier", points=[(0, 40), (1, 40), (2, 40), (3, 40)])
    boundary = d.line(6, 30, 6, 50)
    d.trim_extend(cubic, boundary, (3, 40), True)
    assert d.entities[cubic].vertices()[-1] == pytest.approx((6, 40))


def test_region_trim_closes_material_and_preserves_hole():
    d = Document()
    region = d.region(
        [(0, 0), (20, 0), (20, 20), (0, 20)], holes=[[(2, 2), (4, 2), (4, 4), (2, 4)]]
    )
    cutter = d.line(10, -5, 10, 25)
    result = d.trim_extend(region, cutter, (18, 10))
    assert result == [region]
    e = d.entities[region]
    assert len(e.data["rings"]) == 2
    assert polygon(e).area == pytest.approx(196)


def test_topology_drivers_and_failed_extend_are_atomic():
    d = Document()
    path = d.polyline([(0, 0), (10, 0), (20, 0)])
    box = d.rectangle(5, -5, 10, 10)
    d.bind(path, "v1.x", "10")
    before = d.snapshot()
    with pytest.raises(ValueError, match="topology"):
        d.trim_extend(path, box, (10, 0))
    assert d.snapshot() == before
    with pytest.raises(ValueError):
        d.trim_extend(box, path, (0, 0), True)
    assert d.snapshot() == before


def test_dsl_new_commands_are_programmable(tmp_path):
    d = Document()
    ScriptEngine(d).execute("""PARAM size expression=10 kind=length
RECT a x=0 y=0 width=10 height=10
RECT b x=5 y=0 width=10 height=10
BIND a property=width expression=size
DIFFERENCE a b tolerance=0.01
ELLIPSE e x=40 rx=10 ry=5 start=0 sweep=180
LINE cut x=40 y=-10 x2=40 y2=10
TRIM e boundary=cut x=50 y=0 tolerance=.01
""")
    assert d.parameters["size"]["expression"] == "10"
    assert any(e.kind == "region" for e in d.entities.values())
    replay(d, tmp_path)


def test_numeric_expression_trig_and_safety():
    assert evaluate("sin(radians(a))+sqrt(4)", {"a": 90}) == pytest.approx(3)
    with pytest.raises(ValueError):
        evaluate("(1).__class__", {})


def test_feature_only_binding_and_driver_collision(tmp_path):
    d = Document()
    root = d.circle(0, 0, 5)
    child = d.offset(root, 1)
    fid = d.feature_for(child)["id"]
    d.set_parameter("thickness", "2")
    d.bind(fid, "amount", "thickness", target="feature")
    d.set_parameter("thickness", "3")
    assert d.entities[child].data["radius"] == 8
    d.constrain("radius", [root], 5, id="@driver0_")
    d.bind(root, "x", "10")
    assert d.entities[root].x == 10
    replay(d, tmp_path)


def test_partial_ellipse_driver_fixed_span_and_offset(tmp_path):
    d = Document()
    ellipse = d.add("ellipse", rx=10, ry=5, start=20, sweep=120)
    d.set_parameter("extent", "120", kind="angle")
    d.bind(ellipse, "sweep", "extent")
    d.constrain("rx", [ellipse], 12)
    d.constrain("fixed", [ellipse])
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_parameter("extent", "90", kind="angle")
    assert d.snapshot() == before
    replay(d, tmp_path)
    offset = d.offset(ellipse, 1, tolerance=0.01, linked=False)
    assert not d.entities[offset].data["closed"]
    assert len(d.entities[offset].vertices()) > 2
    d.set_units("cm")
    replay(d, tmp_path)


def test_curved_rotated_bezier_extension_and_closed_rectangle_trim():
    d = Document()
    cubic = d.add(
        "bezier", x=20, y=30, angle=30, points=[(0, 0), (1, 0), (2, 1), (3, 3)]
    )
    original = parameter_curve(d.entities[cubic])
    target = original(2)[0]
    # A horizontal cutter through the extrapolated endpoint.
    cutter = d.line(target[0] - 1, target[1], target[0] + 1, target[1])
    d.trim_extend(cubic, cutter, original(1)[0], True)
    assert d.entities[cubic].vertices()[-1] == pytest.approx(target, abs=1e-7)
    rect = d.rectangle(0, 0, 10, 10)
    cut = d.line(5, -5, 5, 15)
    d.trim_extend(rect, cut, (10, 5))
    e = d.entities[rect]
    assert e.kind == "polyline" and not e.data["closed"]
    assert e.vertices()[0] == pytest.approx((5, 10))
    assert e.vertices()[-1] == pytest.approx((5, 0))


def test_primitive_trim_rejects_driver_undo_and_locked_cutter_is_read_only():
    d = Document()
    line = d.line(0, 0, 10, 0)
    d.set_layer("reference")
    cutter = d.line(5, -10, 5, 10, layer="reference")
    d.set_layer("reference", locked=True)
    d.bind(line, "length", "10")
    before = d.snapshot()
    with pytest.raises(ValueError, match="conflicts"):
        d.trim_extend(line, cutter, (10, 0))
    assert d.snapshot() == before
    d.unbind(line, "length")
    d.trim_extend(line, cutter, (10, 0))
    assert distance(*d.entities[line].vertices()) == pytest.approx(5)
