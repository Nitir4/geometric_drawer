import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import ezdxf
import pytest

from cad_document import Document
from cad_exchange import export_dxf, export_pdf, export_svg, import_dxf
from cad_geometry import Entity, distance, line_intersection
from cad_script import ScriptEngine, ScriptError, document_script, import_legacy
from cad_ui import EXAMPLE, App, Viewport


def assert_points(actual, expected):
    assert len(actual) == len(expected)
    for a, b in zip(actual, expected):
        assert a == pytest.approx(b, abs=1e-8)


def test_oriented_rectangle_independent_corner_coordinates():
    d = Document()
    id = d.rectangle(100, 50, 40, 20, 90)
    e = d.entities[id]
    assert_points(e.vertices(), [(100, 50), (100, 90), (80, 90), (80, 50)])
    assert e.bounds() == pytest.approx((80, 50, 100, 90))
    for p in [(2, 7), (-3, 4)]:
        assert e.local(e.world(p)) == pytest.approx(p)


@pytest.mark.parametrize("angle", [0, 30, 90, 157, -75])
def test_ellipse_bounds_enclose_dense_curve(angle):
    e = Entity("ellipse", "ellipse", 7, 9, angle, data={"rx": 20, "ry": 4}).validate()
    x0, y0, x1, y1 = e.bounds()
    p = e.paths(20000)[0]
    assert min(x for x, y in p) >= x0 - 1e-9
    assert max(x for x, y in p) <= x1 + 1e-9
    assert min(y for x, y in p) >= y0 - 1e-9
    assert max(y for x, y in p) <= y1 + 1e-9
    assert max(x for x, y in p) == pytest.approx(x1, abs=1e-5)


@pytest.mark.parametrize(
    "start,sweep", [(350, 30), (20, -50), (90, 180), (180, -270), (10, 360)]
)
def test_arc_bounds_and_endpoints(start, sweep):
    e = Entity(
        "arc", "arc", 2, 3, 20, data={"radius": 5, "start": start, "sweep": sweep}
    ).validate()
    p = e.paths(10000)[0]
    box = e.bounds()
    assert p[0] == pytest.approx(e.handles()[1])
    assert p[-1] == pytest.approx(e.handles()[2])
    assert all(
        box[0] - 1e-9 <= x <= box[2] + 1e-9 and box[1] - 1e-9 <= y <= box[3] + 1e-9
        for x, y in p
    )


def test_bezier_endpoints_and_known_midpoint():
    e = Entity(
        "b", "bezier", data={"points": [(0, 0), (0, 4), (4, 4), (4, 0)]}
    ).validate()
    p = e.paths(100)[0]
    assert_points([p[0], p[50], p[-1]], [(0, 0), (2, 3), (4, 0)])
    assert e.bounds() == pytest.approx((0, 0, 4, 3))


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 1e13])
def test_invalid_radius_transaction_restores_state(value):
    d = Document()
    d.line(0, 0, 2, 0)
    state = d.snapshot()
    history = len(d._undo)
    with pytest.raises(ValueError), d.transaction("Invalid batch"):
        d.rectangle(0, 0, 10, 10)
        d.circle(2, 2, value)
    assert d.snapshot() == state
    assert len(d._undo) == history


def test_document_history_groups_batch_and_clears_redo():
    d = Document()
    empty = d.snapshot()
    with d.transaction("Part"):
        d.line(0, 0, 10, 0)
        d.circle(5, 0, 2)
    part = d.snapshot()
    assert d.undo() == "Part"
    assert d.snapshot() == empty
    d.redo()
    assert d.snapshot() == part
    d.undo()
    d.circle(0, 0, 1)
    assert d.redo() is None


def test_transform_pivot_copy_scale_and_mirror():
    d = Document()
    id = d.line(10, 0, 20, 0)
    clone = d.transform([id], rotation=90, pivot=(10, 0), copy_entities=True)[0]
    assert_points(d.entities[id].vertices(), [(10, 0), (20, 0)])
    assert_points(d.entities[clone].vertices(), [(10, 0), (10, 10)])
    d.transform([clone], scale=2, pivot=(10, 0), dx=5)
    assert_points(d.entities[clone].vertices(), [(15, 0), (15, 20)])
    d.mirror([clone], (0, 0), (0, 1))
    assert_points(d.entities[clone].vertices(), [(-15, 0), (-15, 20)])


def test_mirror_oriented_rectangle_preserves_reflected_shape():
    d = Document()
    id = d.rectangle(3, 2, 10, 4, 30)
    points = d.entities[id].vertices()
    d.mirror([id], (0, 0), (1, 0))
    actual = d.entities[id].vertices()
    for x, y in points:
        assert min(distance((x, -y), q) for q in actual) < 1e-8


def test_associative_dimensions_follow_freeze_copy_and_units():
    d = Document()
    line = d.line(0, 0, 100, 0)
    dim = d.dimension(line)
    radius = d.circle(20, 20, 10)
    rdim = d.dimension(radius)
    d.transform([line], scale=2)
    assert d.entities[dim].label()[1] == "200.000"
    d.transform([radius], scale=2)
    assert d.entities[rdim].data["radius"] == 20
    copies = d.transform([line, dim], dx=10, copy_entities=True)
    assert d.entities[copies[1]].data["ref"] == copies[0]
    d.transform([copies[1]], dy=5)
    assert "ref" not in d.entities[copies[1]].data
    text_mm = d.entities[dim].label()[2]
    d.set_units("in")
    assert d.entities[dim].label()[2] * 25.4 == pytest.approx(text_mm)
    assert d.entities[line].vertices()[-1][0] == pytest.approx(200 / 25.4)
    d.delete([line])
    assert "ref" not in d.entities[dim].data


def test_layer_lock_and_visibility_persistence(tmp_path):
    d = Document()
    d.set_layer("parts", color="#112233", width=0.5)
    id = d.circle(3, 4, 2, layer="parts")
    d.set_layer("parts", locked=True, visible=False)
    state = d.snapshot()
    for fn in [
        lambda: d.transform([id], dx=1),
        lambda: d.delete([id]),
        lambda: d.offset(id, 1, linked=False),
        lambda: d.circle(0, 0, 1, layer="parts"),
    ]:
        with pytest.raises(ValueError):
            fn()
        assert d.snapshot() == state
    path = tmp_path / "part.gdraw"
    d.save(path)
    assert Document.load(path).snapshot() == state
    assert d.bounds() == (-10, -10, 110, 90)


def test_json_rejects_duplicates_and_unknown_versions(tmp_path):
    d = Document()
    d.circle(0, 0, 1)
    state = d.snapshot()
    state["entities"] *= 2
    p = tmp_path / "bad.gdraw"
    p.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Duplicate"):
        Document.load(p)
    state["version"] = 9
    p.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="version"):
        Document.load(p)


def test_offset_signed_and_invalid_are_atomic():
    d = Document()
    line = d.line(0, 0, 10, 0)
    rect = d.rectangle(2, 3, 10, 8, 90)
    offset = d.offset(line, 3, linked=False)
    assert_points(d.entities[offset].vertices(), [(0, 3), (10, 3)])
    r = d.offset(rect, 2, linked=False)
    assert d.entities[r].data == {"width": 14.0, "height": 12.0}
    circle = d.circle(0, 0, 2)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.offset(circle, -3, linked=False)
    assert d.snapshot() == state


def test_trim_and_extend_analytic_intersections():
    d = Document()
    target = d.line(0, 0, 10, 0)
    cutter = d.line(4, -5, 4, 5)
    d.trim_extend(target, cutter, (0, 0))
    assert_points(d.entities[target].vertices(), [(4, 0), (10, 0)])
    farther = d.line(15, -2, 15, 2)
    d.trim_extend(target, farther, (10, 0), extend=True)
    assert_points(d.entities[target].vertices(), [(4, 0), (15, 0)])
    with pytest.raises(ValueError, match="already"):
        d.trim_extend(target, cutter, (0, 0), extend=True)


@pytest.mark.parametrize("fillet", [True, False])
def test_corner_is_tangent_and_rejects_overlarge_amount(fillet):
    d = Document()
    a = d.line(0, 0, 20, 0)
    b = d.line(0, 0, 0, 20)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.corner(a, b, 30, fillet=fillet, linked=False)
    assert d.snapshot() == state
    id = d.corner(a, b, 5, fillet=fillet, linked=False)
    assert d.entities[a].vertices()[0] == pytest.approx((5, 0))
    assert d.entities[b].vertices()[0] == pytest.approx((0, 5))
    if fillet:
        e = d.entities[id]
        assert (e.x, e.y) == pytest.approx((5, 5))
        for p in [e.handles()[1], e.handles()[2]]:
            assert distance(p, (5, 5)) == pytest.approx(5)
        assert abs(e.data["sweep"]) == pytest.approx(90)
    else:
        assert_points(d.entities[id].vertices(), [(5, 0), (0, 5)])


def test_array_count_units_and_single_undo():
    d = Document()
    id = d.circle(10, 10, 2)
    ids = d.array([id], 4, dx=30)
    assert [d.entities[i].x for i in ids] == [40, 70, 100]
    d.undo()
    assert list(d.entities) == [id]
    with pytest.raises(ValueError):
        d.array([id], 1.5)


def test_script_example_and_lossless_generated_script():
    d = Document()
    ScriptEngine(d).execute(EXAMPLE)
    d.set_layer("holes", locked=True)
    clone = Document()
    ScriptEngine(clone).execute(document_script(d), replace=True)
    assert clone.snapshot() == d.snapshot()
    assert len(d.entities) == 9


def test_script_snapshot_keeps_locked_active_layer():
    d = Document()
    d.set_layer("parts")
    d.active_layer = "parts"
    d.circle(0, 0, 5)
    d.set_layer("parts", locked=True)
    clone = Document()
    ScriptEngine(clone).execute(document_script(d), replace=True)
    assert clone.snapshot() == d.snapshot()


def test_deferred_script_reference_validation_is_line_numbered():
    d = Document()
    initial = d.snapshot()
    with pytest.raises(ScriptError, match="Line 1"):
        ScriptEngine(d).execute("DIM broken entity=missing")
    assert d.snapshot() == initial


def test_headless_cli_real_example_exports_and_failure_status(tmp_path):
    source = Path(__file__).resolve().parents[1]
    p = subprocess.run(
        [
            sys.executable,
            str(source / "main.py"),
            "--headless",
            "--script",
            str(source / "examples/plate.cad"),
            "--save",
            str(tmp_path / "plate.gdraw"),
            "--export",
            str(tmp_path / "plate.svg"),
            "--export",
            str(tmp_path / "plate.pdf"),
            "--export",
            str(tmp_path / "plate.dxf"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    assert "9 entities; units mm" in p.stdout
    assert len(Document.load(tmp_path / "plate.gdraw").entities) == 9
    bad = tmp_path / "bad.cad"
    bad.write_text("CIRCLE hole radius=-2")
    p = subprocess.run(
        [sys.executable, str(source / "main.py"), "--headless", "--script", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 2
    assert "Line 1" in p.stderr


@pytest.mark.parametrize(
    "source",
    [
        "CIRCLE a radius=3\nLINE b length=-2",
        "CIRCLE a radius=3 typo=4",
        "LET r=2\nCIRCLE a radius=r\nNONSENSE",
        'LET r=__import__("os")',
        "LET r=2**9999999",
        "LINE a length=nan",
    ],
)
def test_script_errors_are_atomic_and_line_numbered(source):
    d = Document()
    d.rectangle(0, 0, 5, 5)
    state = d.snapshot()
    engine = ScriptEngine(d)
    with pytest.raises(ScriptError, match="Line "):
        engine.execute(source, replace=True)
    assert d.snapshot() == state
    assert "r" not in engine.variables


def test_script_math_color_text_and_transform():
    d = Document()
    engine = ScriptEngine(d)
    engine.execute(
        'LET l=sqrt(9)*10\nLAYER parts color=#123abc\nUSE parts\nLINE a length=l angle=90\nTEXT t text="Part #1" height=3\nMOVE a dx=2 dy=4'
    )
    assert_points(d.entities["a"].vertices(), [(2, 4), (2, 34)])
    assert d.entities["t"].data["text"] == "Part #1"
    assert d.layers["parts"].color == "#123abc"
    assert engine.number("sin(pi/2)") == pytest.approx(1)
    engine.execute("LET Radius=5\nCIRCLE capitalized radius=Radius")
    assert d.entities["capitalized"].data["radius"] == 5


def test_legacy_import_preserves_original_track_coordinates():
    d = Document()
    import_legacy(
        d, "POINT A 0 0\nLINE FROM=A LEN=40 ANGLE=90 TO=B\nCIRCLE CENTER=B R=10"
    )
    line = next(e for e in d.entities.values() if e.kind == "line")
    assert_points(line.vertices(), [(0, 0), (0, 40)])
    assert next(
        e for e in d.entities.values() if e.kind == "circle"
    ).y == pytest.approx(40)
    state = d.snapshot()
    with pytest.raises(ScriptError):
        import_legacy(d, "POINT A 0 0\nCIRCLE CENTER=unknown R=2")
    assert d.snapshot() == state


def test_true_size_svg_and_pdf_independent_of_viewport(tmp_path):
    d = Document()
    d.line(0, 0, 100, 0, id="reference")
    d.circle(25, 10, 5)
    svg = tmp_path / "part.svg"
    pdf = tmp_path / "part.pdf"
    export_svg(d, svg)
    before = svg.read_bytes()
    v = Viewport()
    v.zoom(20, 100, 100)
    export_svg(d, svg)
    assert svg.read_bytes() == before
    root = ET.parse(svg).getroot()
    assert root.attrib["width"] == "110mm"
    poly = root.find(".//{http://www.w3.org/2000/svg}polyline")
    assert poly.attrib["points"] == "0.0,-0.0 100.0,-0.0"
    d.set_units("in")
    export_svg(d, svg)
    assert ET.parse(svg).getroot().attrib["width"] == "110mm"
    export_pdf(d, pdf)
    assert pdf.read_bytes().startswith(b"%PDF")
    media = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]", pdf.read_bytes()
    )
    assert media is not None
    assert float(media[1]) == pytest.approx(110 * 72 / 25.4, abs=1e-3)
    assert float(media[2]) == pytest.approx(25 * 72 / 25.4, abs=1e-3)


def test_svg_curves_remain_analytic_and_text_is_escaped(tmp_path):
    d = Document()
    d.arc(0, 0, 5, 30, -220)
    d.add("ellipse", x=20, rx=8, ry=3, angle=45)
    d.add("bezier", points=[(0, 0), (0, 5), (5, 5), (5, 0)])
    d.add("text", text="A < B & C", height=3)
    path = tmp_path / "a.svg"
    export_svg(d, path)
    root = ET.parse(path).getroot()
    assert root.find(".//{http://www.w3.org/2000/svg}ellipse") is not None
    paths = root.findall(".//{http://www.w3.org/2000/svg}path")
    assert any(" A " in p.attrib["d"] for p in paths)
    assert any(" C " in p.attrib["d"] for p in paths)
    assert root.find(".//{http://www.w3.org/2000/svg}text").text == "A < B & C"


def test_dxf_analytic_exchange_audit_dimensions_and_layers(tmp_path):
    d = Document()
    ScriptEngine(d).execute(EXAMPLE)
    d.arc(140, 20, 10, 30, -120, id="arc")
    d.add("ellipse", x=150, y=50, rx=4, ry=10, angle=30, id="ellipse")
    d.add("bezier", points=[(130, 0), (140, 10), (150, 10), (160, 0)], id="bezier")
    d.set_layer("holes", locked=True)
    p = tmp_path / "part.dxf"
    export_dxf(d, p)
    src = ezdxf.readfile(p)
    assert not src.audit().has_errors
    assert src.units == 4
    assert len(src.modelspace().query("CIRCLE")) == 4
    assert len(src.modelspace().query("ARC")) == 1
    assert len(src.modelspace().query("SPLINE")) == 1
    r = import_dxf(p)
    assert_points(r.entities["plate"].vertices(), d.entities["plate"].vertices())
    assert r.entities["hole"].data["radius"] == 5
    assert r.layers["holes"].locked
    assert_points(r.entities["bezier"].vertices(), d.entities["bezier"].vertices())
    # DXF ARC is CCW: CW paths preserve the same geometric locus.
    assert_points(
        [r.entities["arc"].handles()[1], r.entities["arc"].handles()[2]],
        [d.entities["arc"].handles()[2], d.entities["arc"].handles()[1]],
    )


@pytest.mark.parametrize("content", ["3d", "unsupported", "units"])
def test_dxf_import_rejects_unsupported_content(tmp_path, content):
    src = ezdxf.new("R2010")
    src.units = 4
    if content == "3d":
        src.modelspace().add_line((0, 0, 3), (10, 0, 3))
    elif content == "unsupported":
        src.modelspace().add_xline((0, 0), (1, 0))
    else:
        src.units = 0
    p = tmp_path / "bad.dxf"
    src.saveas(p)
    with pytest.raises(ValueError):
        import_dxf(p)


def test_view_zoom_anchor_and_rotation_grip_arc_edit():
    v = Viewport()
    anchor = v.world(133, 201)
    v.zoom(4, 133, 201)
    assert v.world(133, 201) == pytest.approx(anchor)
    e = Entity("arc", "arc", data={"radius": 10, "start": 0, "sweep": -90}).validate()
    App.edit_handle(e, 1, (0, 10))
    assert e.data["start"] == pytest.approx(90)
    assert e.data["sweep"] == pytest.approx(-180)


def test_intersection_parallel_and_exact_crossing():
    p, t, u = line_intersection((0, 0), (10, 10), (0, 10), (10, 0))
    assert p == (5, 5)
    assert t == u == 0.5
    with pytest.raises(ValueError):
        line_intersection((0, 0), (1, 0), (0, 1), (1, 1))
