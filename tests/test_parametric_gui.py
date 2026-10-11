"""Real Tk controls for persisted design parameters and material edits."""

import os
from pathlib import Path

import pytest
from test_ui import app as shared_app
from test_ui import button, drag
from window_capture import capture

from cad_document import Document
from cad_regions import polygon
from cad_script import ScriptEngine

app = shared_app
pytestmark = pytest.mark.skipif(
    os.environ.get("CAD_GUI_TESTS") != "1", reason="Native GUI requires display"
)


def test_gui_parameter_binding_numeric_manual_replay_unbind(app):
    a = app
    circle = a.doc.circle(20, 20, 5)
    a.selection = [circle]
    a.changed()
    a.tabs.select(a.parameter_tab)
    a.parameter_name.set("radius")
    a.parameter_expression.set("5")
    button(a.root, "Set parameter").invoke()
    button(a.root, "Use selected target").invoke()
    a.binding_property.set("radius")
    a.binding_expression.set("radius")
    button(a.root, "Bind expression").invoke()
    a.parameter_expression.set("8")
    button(a.root, "Set parameter").invoke()
    assert a.doc.entities[circle].data["radius"] == 8
    assert a.parameter_tree.item("radius")["values"][0] == 8
    drag(a, (28, 20), (30, 20))
    assert a.doc.entities[circle].data["radius"] == pytest.approx(8)
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()
    button(a.root, "Unbind expression").invoke()
    drag(a, (28, 20), (30, 20))
    assert a.doc.entities[circle].data["radius"] == pytest.approx(10)


def test_gui_boolean_empty_feature_revival_and_parameters_view(app):
    a = app
    first = a.doc.rectangle(0, 0, 40, 30)
    second = a.doc.rectangle(10, 10, 10, 10)
    a.selection = [first, second]
    a.changed()
    button(a.root, "Difference").invoke()
    assert len(a.selection) == 1
    region = a.doc.entities[a.selection[0]]
    assert polygon(region).area == pytest.approx(1100)
    assert len(region.data["rings"]) == 2
    a.parameter_name.set("width")
    a.parameter_expression.set("45")
    button(a.root, "Set parameter").invoke()
    a.binding_id.set(first)
    a.binding_property.set("width")
    a.binding_expression.set("width")
    button(a.root, "Bind expression").invoke()
    assert polygon(a.doc.entities[a.selection[0]]).area == pytest.approx(1250)
    a.root.geometry("1400x1080")
    a.root.update()
    a.fit()
    a.tabs.select(a.parameter_tab)
    a.root.update()
    path = Path(
        "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-parametric/parameters-workspace.png"
    )
    capture(a.root, path)


def test_gui_general_trim_partial_ellipse_and_endpoint_grip(app):
    a = app
    ellipse = a.doc.add("ellipse", x=20, y=20, rx=10, ry=5)
    cutter = a.doc.line(20, 0, 20, 40)
    a.selection = [ellipse, cutter]
    a.changed()
    a.transform_vars["pivot x"].set("30")
    a.transform_vars["pivot y"].set("20")
    button(a.root, "Trim").invoke()
    assert a.selection == [ellipse]
    assert a.doc.entities[ellipse].data["sweep"] == pytest.approx(180)
    assert a.props["sweep"].get() == "180.0"
    end = a.doc.entities[ellipse].handles()[4]
    drag(a, end, (10, 20))
    assert abs(a.doc.entities[ellipse].data["sweep"]) == pytest.approx(90)
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()


def test_gui_new_constraint_values_and_region_vertex_refs(app):
    a = app
    first = a.doc.line(0, 0, 10, 0)
    second = a.doc.line(0, 10, 10, 10)
    a.doc.constrain("fixed", [first])
    a.constraint_kind.set("angle_between")
    a.constraint_refs.set(f"{first},{second}")
    a.constraint_value.set("-45")
    button(a.root, "Add constraint").invoke()
    assert a.doc.constraint_report()["max_residual"] < 1e-7
    rule = next(c for c in a.doc.constraints.values() if c["kind"] == "angle_between")
    assert rule["value"] == -45
    arc = a.doc.arc(40, 0, 5, 0, 90)
    a.constraint_kind.set("arc_sweep")
    a.constraint_refs.set(arc)
    a.constraint_value.set("-120")
    button(a.root, "Add constraint").invoke()
    assert a.doc.entities[arc].data["sweep"] == pytest.approx(-120)
