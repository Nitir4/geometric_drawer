"""Independent regression checks for driving constraints and expanded CAD exchange."""

import json
import math
import subprocess
import sys
from pathlib import Path

import ezdxf
import pytest

from cad_document import Document
from cad_exchange import export_dwg, export_pdf, import_dwg, import_dxf
from cad_geometry import distance
from cad_script import ScriptEngine, ScriptError, document_script


def test_driving_length_with_fixed_anchor_and_associative_measurement(tmp_path):
    d = Document()
    d.line(0, 0, 10, 0, id="edge")
    d.add("point", id="anchor")
    d.dimension("edge", id="measurement")
    with d.transaction():
        d.constrain("fixed", ["anchor"])
        d.constrain("coincident", ["edge@0", "anchor"])
        d.constrain("horizontal", ["edge"])
        d.constrain("length", ["edge"], 20, id="width")
    assert d.entities["edge"].vertices()[0] == pytest.approx((0, 0), abs=1e-7)
    assert d.entities["edge"].vertices()[1] == pytest.approx((20, 0), abs=1e-7)
    assert distance(*d.entities["measurement"].vertices()) == pytest.approx(20)
    state = d.snapshot()
    d.set_constraint_value("width", 35)
    assert d.entities["edge"].vertices()[1] == pytest.approx((35, 0), abs=1e-7)
    d.undo()
    assert d.snapshot() == state
    d.redo()
    d.save(tmp_path / "driven.gdraw")
    assert Document.load(tmp_path / "driven.gdraw").snapshot() == d.snapshot()
    clone = Document()
    ScriptEngine(clone).execute(document_script(d), replace=True)
    assert clone.snapshot() == d.snapshot()
    # A report must not silently alter the model or history.
    before = d.snapshot()
    report = d.constraint_report()
    assert report["dof"] == 0
    assert report["max_residual"] < 1e-7
    assert d.snapshot() == before


def test_conflicts_are_atomic_and_locked_layers_are_constants():
    d = Document()
    d.line(0, 0, 10, 0, id="line")
    d.constrain("length", ["line"], 10, id="length")
    state, history = d.snapshot(), len(d._undo)
    with pytest.raises(ValueError, match="Conflicting|unsolved"):
        d.constrain("length", ["line"], 20)
    assert d.snapshot() == state
    assert len(d._undo) == history
    d.set_layer("0", locked=True)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.set_constraint_value("length", 30)
    assert d.snapshot() == state


@pytest.mark.parametrize("kind", ["parallel", "perpendicular", "equal_length"])
def test_line_relations_including_parallel_stationary_start(kind):
    d = Document()
    d.line(0, 0, 10, 0, id="a")
    d.line(0, 4, 10, 4, id="b")
    d.constrain("fixed", ["a"])
    d.constrain(kind, ["a", "b"])
    a, b = d.entities["b"].vertices()
    if kind == "perpendicular":
        assert a[0] == pytest.approx(b[0], abs=1e-7)
    elif kind == "parallel":
        assert a[1] == pytest.approx(b[1], abs=1e-7)
    else:
        assert distance(a, b) == pytest.approx(10)


def test_radius_concentric_rectangle_and_angle_constraints():
    d = Document()
    d.circle(5, 6, 3, id="a")
    d.circle(20, 30, 7, id="b")
    d.rectangle(0, 0, 10, 15, id="rect")
    d.line(0, 0, 10, 0, id="line")
    with d.transaction():
        d.constrain("fixed", ["a"])
        d.constrain("concentric", ["a", "b"])
        d.constrain("radius", ["b"], 9)
        d.constrain("width", ["rect"], 40)
        d.constrain("height", ["rect"], 20)
        d.constrain("angle", ["line"], 135)
        d.constrain("length", ["line"], 10)
    assert (d.entities["b"].x, d.entities["b"].y) == pytest.approx((5, 6), abs=1e-7)
    assert d.entities["b"].data["radius"] == pytest.approx(9)
    assert d.entities["rect"].data["width"] == pytest.approx(40)
    assert d.entities["rect"].data["height"] == pytest.approx(20)
    a, b = d.entities["line"].vertices()
    assert math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) == pytest.approx(135)


def test_distance_vertical_tangent_and_nearby_solution():
    d = Document()
    d.line(0, 0, 10, 0, id="a")
    d.constrain("length", ["a"], 20)
    a, b = d.entities["a"].vertices()
    assert (a[1], b[1]) == pytest.approx((0, 0), abs=1e-4)
    assert ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) == pytest.approx((5, 0), abs=1e-4)
    d.circle(0, 8, 3, id="c")
    d.constrain("fixed", ["a"])
    with d.transaction():
        d.constrain("radius", ["c"], 3)
        d.constrain("tangent", ["a", "c"])
    assert abs(d.entities["c"].y) == pytest.approx(3, abs=1e-5)
    d.add("point", x=0, y=0, id="p")
    d.add("point", x=0, y=1, id="q")
    d.constrain("fixed", ["p"])
    d.constrain("distance", ["p", "q"], 7)
    assert math.hypot(d.entities["q"].x, d.entities["q"].y) == pytest.approx(7)
    d.line(20, 20, 21, 30, id="v")
    d.constrain("vertical", ["v"])
    assert d.entities["v"].vertices()[0][0] == pytest.approx(
        d.entities["v"].vertices()[1][0]
    )


def test_fixed_reprojection_units_delete_and_script_reset(tmp_path):
    d = Document()
    d.rectangle(25.4, 50.8, 25.4, 50.8, angle=30, id="r")
    d.constrain("fixed", ["r"])
    state = d.snapshot()
    d.transform(["r"], dx=100, rotation=50, scale=2)
    for actual, expected in zip(
        d.entities["r"].vertices(), document_from_state(state).entities["r"].vertices()
    ):
        assert actual == pytest.approx(expected)
    d.set_units("in")
    assert (d.entities["r"].x, d.entities["r"].y) == pytest.approx((1, 2))
    assert d.entities["r"].data["width"] == pytest.approx(1)
    assert d.entities["r"].angle == pytest.approx(30)
    d.save(tmp_path / "fixed.gdraw")
    assert Document.load(tmp_path / "fixed.gdraw").snapshot() == d.snapshot()
    d.delete(["r"])
    assert not d.constraints
    d.undo()
    assert len(d.constraints) == 1
    ScriptEngine(d).execute("POINT clean x=1", replace=True)
    assert not d.constraints


def document_from_state(state):
    d = Document()
    d._restore(state)
    return d


def test_native_v1_and_invalid_constraint_files(tmp_path):
    d = Document()
    d.line(0, 0, 10, 0, id="a")
    state = d.snapshot()
    state["version"] = 1
    state.pop("constraints")
    path = tmp_path / "old.gdraw"
    path.write_text(json.dumps(state))
    assert Document.load(path).entities["a"].kind == "line"
    d.constrain("length", ["a"], 10)
    state = d.snapshot()
    state["constraints"][0]["value"] = 99
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="unsatisfied"):
        Document.load(path)
    state["constraints"] *= 2
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Duplicate constraint"):
        Document.load(path)


@pytest.mark.parametrize(
    "command",
    [
        "CONSTRAINT c kind=coincident refs=a@99,a@0",
        "CONSTRAINT c kind=radius refs=a value=2",
        "CONSTRAINT c kind=horizontal refs=a value=2",
        "CONSTRAINT c kind=length refs=missing value=2",
    ],
)
def test_bad_constraint_script_rolls_back(command):
    d = Document()
    ScriptEngine(d).execute("LINE a length=10")
    before = d.snapshot()
    with pytest.raises(ScriptError):
        ScriptEngine(d).execute(command)
    assert d.snapshot() == before


def test_driving_script_and_undo_is_one_edit():
    d = Document()
    ScriptEngine(d).execute(
        "LINE a length=10\nCONSTRAINT long kind=length refs=a value=25\nCONSTRAINT h kind=horizontal refs=a\nDRIVE long value=30\nUNCONSTRAIN h"
    )
    assert distance(*d.entities["a"].vertices()) == pytest.approx(30)
    assert len(d.constraints) == 1
    d.undo()
    assert not d.entities and not d.constraints


def test_circular_trimming_and_extension():
    d = Document()
    d.circle(0, 0, 10, id="circle")
    d.line(0, -20, 0, 20, id="cut")
    d.trim_extend("circle", "cut", (10, 0))
    arc = d.entities["circle"]
    assert arc.kind == "arc" and arc.data["sweep"] == pytest.approx(180)
    assert all(p[0] <= 1e-7 for p in arc.paths()[0])
    d.arc(0, 0, 10, 0, 45, id="arc")
    d.trim_extend("arc", "cut", (7, 7), extend=True)
    assert d.entities["arc"].data["sweep"] == pytest.approx(90)
    d.line(-20, 0, 20, 0, id="target")
    d.circle(0, 0, 5, id="boundary")
    d.trim_extend("target", "boundary", (-20, 0))
    assert d.entities["target"].vertices()[0] == pytest.approx((-5, 0))
    d.arc(0, 0, 10, 0, -180, id="cw")
    d.trim_extend("cw", "cut", (10, 0))
    assert d.entities["cw"].data["start"] == pytest.approx(-90)
    assert d.entities["cw"].data["sweep"] == pytest.approx(-90)


def test_polyline_offset_geometry_and_collapse_rollback():
    d = Document()
    d.polyline([(0, 0), (10, 0), (10, 10)], id="open")
    id = d.offset("open", 2, linked=False)
    for actual, expected in zip(d.entities[id].vertices(), [(0, 2), (8, 2), (8, 10)]):
        assert actual == pytest.approx(expected)
    d.polyline([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True, id="square")
    id = d.offset("square", 2, linked=False)
    assert d.entities[id].bounds() == pytest.approx((-2, -2, 12, 12))
    before = d.snapshot()
    with pytest.raises(ValueError, match="collapses|reverses"):
        d.offset("square", -6, linked=False)
    assert d.snapshot() == before


def save_import(src, tmp_path):
    src.units = 4
    path = tmp_path / "exchange.dxf"
    src.saveas(path)
    return import_dxf(path)


def test_dxf_nested_blocks_arrays_transform_and_layer_inheritance(tmp_path):
    src = ezdxf.new("R2010")
    src.layers.new("parts", dxfattribs={"color": 1})
    block = src.blocks.new("part")
    block.add_line((0, 0), (10, 0))
    nested = src.blocks.new("assembly")
    nested.add_blockref("part", (0, 5))
    src.modelspace().add_blockref(
        "assembly",
        (100, 20),
        dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2, "layer": "parts"},
    )
    d = save_import(src, tmp_path)
    edge = next(iter(d.entities.values()))
    assert edge.vertices()[0] == pytest.approx((90, 20))
    assert edge.vertices()[1] == pytest.approx((90, 40))
    assert edge.layer == "parts"
    assert d.import_warnings


def test_dxf_mtext_multispan_spline_partial_ellipse_and_dimension(tmp_path):
    src = ezdxf.new("R2010")
    m = src.modelspace()
    m.add_mtext("First\\PSecond", dxfattribs={"insert": (20, 30), "char_height": 3})
    m.add_open_spline([(0, 0), (10, 5), (20, 5), (30, 0), (40, -5)], degree=3)
    m.add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5, start_param=0, end_param=math.pi
    )
    d = save_import(src, tmp_path)
    assert {e.data["text"] for e in d.entities.values() if e.kind == "text"} == {
        "First",
        "Second",
    }
    assert sum(e.kind == "bezier" for e in d.entities.values()) >= 2
    ellipse = next(e for e in d.entities.values() if e.kind == "ellipse")
    assert ellipse.paths()[0][0] == pytest.approx((10, 0))
    assert ellipse.paths()[0][-1] == pytest.approx((-10, 0))
    assert ellipse.data["sweep"] == pytest.approx(180)
    assert d.import_warnings
    assert not any("Partial ellipse" in w for w in d.import_warnings)


def test_dxf_rational_spline_is_reported_approximation(tmp_path):
    src = ezdxf.new("R2010")
    spline = src.modelspace().add_open_spline([(0, 0), (10, 5), (20, 0)], degree=2)
    spline.weights = [1, 0.5, 1]
    d = save_import(src, tmp_path)
    assert next(iter(d.entities.values())).kind == "polyline"
    assert any("rational" in warning for warning in d.import_warnings)


def test_unicode_pdf_embeds_font(tmp_path):
    d = Document()
    d.add("text", text="θ π μ Ω café", height=5)
    path = tmp_path / "unicode.pdf"
    export_pdf(d, path)
    assert b"/FontFile2" in path.read_bytes()


def test_dwg_missing_converter_is_actionable_and_preserves_destination(
    tmp_path, monkeypatch
):
    from ezdxf.addons import odafc

    monkeypatch.setattr(odafc, "is_installed", lambda: False)
    monkeypatch.setattr("cad_dwg.libredwg_tools", lambda: None)
    path = tmp_path / "drawing.dwg"
    path.write_bytes(b"existing drawing")
    for action in (lambda: export_dwg(Document(), path), lambda: import_dwg(path)):
        with pytest.raises(ValueError, match="ODA File Converter"):
            action()
    assert path.read_bytes() == b"existing drawing"


def test_headless_driven_sketch(tmp_path):
    script = tmp_path / "driven.cad"
    script.write_text(
        "LINE a length=10\nCONSTRAINT length kind=length refs=a value=40\nCONSTRAINT horizontal kind=horizontal refs=a"
    )
    output = tmp_path / "part.gdraw"
    r = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--headless",
            "--script",
            str(script),
            "--save",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert distance(*Document.load(output).entities["a"].vertices()) == pytest.approx(
        40
    )


def polygon_area(points):
    return (
        abs(
            sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1])
            )
        )
        / 2
    )


def test_solid_hatch_holes_and_filled_export(tmp_path):
    from cad_exchange import export_dxf

    src = ezdxf.new("R2010")
    h = src.modelspace().add_hatch()
    h.paths.add_polyline_path(
        [(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True, flags=1
    )
    h.paths.add_polyline_path([(2, 2), (8, 2), (8, 8), (2, 8)], is_closed=True, flags=0)
    d = save_import(src, tmp_path)
    from cad_regions import contains, polygon

    assert len(d.entities) == 1
    region = next(iter(d.entities.values()))
    assert region.kind == "region" and polygon(region).area == pytest.approx(64)
    assert region.data["fill"] and contains(region, (1, 1))
    assert not contains(region, (5, 5))
    drawing = Document()
    drawing.rectangle(0, 0, 10, 8, fill=True)
    path = tmp_path / "filled.dxf"
    export_dxf(drawing, path)
    result = ezdxf.readfile(path)
    assert len(result.modelspace().query("HATCH")) == 1
    roundtrip = import_dxf(path)
    assert sum(
        polygon_area(e.vertices()) for e in roundtrip.entities.values()
    ) == pytest.approx(80)


def test_rendered_dxf_dimensions_and_arrowheads_import(tmp_path):
    src = ezdxf.new("R2010")
    dim = src.modelspace().add_linear_dim(base=(0, 8), p1=(0, 0), p2=(20, 0), angle=0)
    dim.render()
    d = save_import(src, tmp_path)
    assert any(e.kind == "line" for e in d.entities.values())
    assert any("dimensions" in warning for warning in d.import_warnings)


def test_dwg_adapter_routes_through_planar_exchange(tmp_path, monkeypatch):
    # This checks adapter plumbing, not actual DWG encoding; real ODA is absent.
    from ezdxf.addons import odafc

    calls = []
    monkeypatch.setattr(odafc, "is_installed", lambda: True)

    def convert(source, dest, **kwargs):
        calls.append((str(source), str(dest)))
        Path(dest).write_bytes(Path(source).read_bytes())

    from pathlib import Path

    monkeypatch.setattr(odafc, "convert", convert)
    d = Document()
    d.circle(10, 20, 3)
    path = tmp_path / "adapter.dwg"
    export_dwg(d, path)
    result = import_dwg(path)
    assert len(calls) == 2
    assert next(iter(result.entities.values())).data["radius"] == pytest.approx(3)


def test_fixed_arc_preserves_full_pose_and_sweep():
    d = Document()
    d.arc(10, 20, 5, start=30, sweep=-120, angle=15, id="arc")
    d.constrain("fixed", ["arc"])
    before = d.entities["arc"].to_dict()
    d.transform(["arc"], dx=25, rotation=50, scale=2)
    assert d.entities["arc"].to_dict() == before
    d.set_units("in")
    assert d.entities["arc"].angle == 15
    assert d.entities["arc"].data["start"] == 30
    assert d.entities["arc"].data["sweep"] == -120
    assert d.entities["arc"].data["radius"] == pytest.approx(5 / 25.4)


def test_external_circle_tangency_with_fixed_radius():
    d = Document()
    d.circle(0, 0, 4, id="a")
    d.circle(20, 0, 6, id="b")
    with d.transaction():
        d.constrain("fixed", ["a"])
        d.constrain("radius", ["b"], 6)
        d.constrain("tangent", ["a", "b"])
    assert math.hypot(d.entities["b"].x, d.entities["b"].y) == pytest.approx(10)


def test_non_fixed_saved_state_is_rejected_atomically():
    d = Document()
    d.line(0, 0, 10, 0, id="a")
    before = d.snapshot()
    with pytest.raises(ValueError, match="Only fixed"):
        d.constrain("length", ["a"], 10, state=[0, 0, 10, 0])
    assert d.snapshot() == before


def test_real_libredwg_primitive_roundtrip(tmp_path):
    from cad_dwg import libredwg_tools
    from cad_exchange import export_dwg, import_dwg

    if not libredwg_tools():
        pytest.skip("Optional GNU LibreDWG tools are not installed")
    d = Document()
    d.line(10, 20, 30, 40, id="edge")
    d.circle(50, 60, 7, id="hole")
    d.arc(0, 0, 12, 30, 80, id="arc")
    d.rectangle(100, 50, 40, 20, angle=25, id="plate")
    path = tmp_path / "real.dwg"
    export_dwg(d, path)
    assert path.read_bytes()[:6] in (b"AC1015", b"AC1024", b"AC1032")
    result = import_dwg(path)
    assert result.units == d.units
    assert set(result.entities) == set(d.entities)
    for id in d.entities:
        assert result.entities[id].bounds() == pytest.approx(
            d.entities[id].bounds(), abs=1e-7
        )


@pytest.mark.parametrize(
    "example", list(Path("examples").glob("*.cad")), ids=lambda p: p.name
)
def test_all_shipped_examples_execute(example):
    d = Document()
    ScriptEngine(d).execute(example.read_text())
    d.validate()
    assert d.entities
