"""Native GUI checks for compound editing, topology recovery and free contacts."""

import json
import os
from pathlib import Path

import pytest
from test_ui import app as shared_app
from test_ui import button, drag
from window_capture import capture

from cad_constraints import residual
from cad_document import Document
from cad_regions import contains
from cad_script import ScriptEngine

app = shared_app
pytestmark = pytest.mark.skipif(
    os.environ.get("CAD_GUI_TESTS") != "1", reason="Native GUI requires display"
)


def test_region_numeric_manual_code_and_hole_snaps(app):
    a = app
    a.kind_var.set("region")
    a.property_form()
    for k, v in {
        "id": "plate",
        "x": "20",
        "y": "20",
        "orientation": "0",
        "hatch": "cross",
        "spacing": "3",
    }.items():
        a.props[k].set(v)
    button(a.root, "Create").invoke()
    a.root.update()
    assert a.selection == ["plate"]
    assert not contains(a.doc.entities["plate"], (35, 35))
    # Reopen an existing tuple-backed entity and apply a numeric pattern edit.
    a.props["spacing"].set("4")
    button(a.root, "Apply to selection").invoke()
    a.root.update()
    assert a.doc.entities["plate"].data["spacing"] == 4
    drag(a, (20, 20), (18, 20))
    assert a.doc.entities["plate"].vertices()[0] == pytest.approx((18, 20))
    assert len(json.loads(a.props["rings"].get())) == 2
    a.object_snap.set(True)
    assert a.snap((30.02, 30.01)) == pytest.approx((30, 30))
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()


def test_gui_cleanup_split_merge_empty_revival_detach(app):
    a = app
    root = a.doc.polyline([(0, 0), (10, 10), (0, 10), (10, 0)], closed=True)
    a.selection = [root]
    a.changed()
    a.transform_vars["amount"].set("0")
    button(a.root, "Clean offset").invoke()
    assert len(a.selection) == 2
    assert all(a.doc.entities[i].kind == "region" for i in a.selection)
    f = a.doc.feature_for(a.selection[0])["id"]
    a.feature_target.set(f)
    a.transform_vars["amount"].set("2")
    button(a.root, "Update feature").invoke()
    assert len(a.selection) == 1 and "topology" in a.status.get()
    a.transform_vars["amount"].set("-20")
    button(a.root, "Update feature").invoke()
    assert not a.selection and a.feature_target.get() == f
    assert f in a.feature_box.cget("values")
    a.transform_vars["amount"].set("0")
    button(a.root, "Update feature").invoke()
    assert len(a.selection) == 2
    button(a.root, "Detach").invoke()
    assert f not in a.doc.features and len(a.selection) == 2


def test_gui_free_tangent_saved_parameters(app):
    a = app
    ellipse = a.doc.add("ellipse", x=30, y=20, rx=10, ry=6)
    line = a.doc.line(10, 28, 50, 28)
    a.doc.constrain("fixed", [ellipse])
    a.doc.constrain("horizontal", [line])
    a.constraint_kind.set("free_tangent")
    a.constraint_refs.set(f"{ellipse},{line}")
    a.constraint_parameters.set(".1,.7")
    a.constraint_add()
    c = next(c for c in a.doc.constraints.values() if c["kind"] == "free_tangent")
    assert max(abs(v) for v in residual(a.doc, c)) < 1e-7
    assert c["parameters"][0] == pytest.approx(0.25, abs=1e-7)
    assert a.doc.entities[line].vertices()[0][1] == pytest.approx(26)


def test_compound_workspace_render_and_dense_preview(app):
    a = app
    outer = [(0, 0), (60, 0), (60, 40), (0, 40)]
    holes = [[(15, 10), (45, 10), (45, 30), (15, 30)]]
    a.doc.region(outer, holes, x=10, y=10, hatch="cross", spacing=4, id="hatched_plate")
    a.doc.region(outer, holes, x=85, y=10, hatch="solid", id="solid_plate")
    a.changed()
    a.root.geometry("1400x1080")
    a.root.update()
    a.fit()
    a.root.update()
    destination = Path(
        "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-advanced/regions-workspace.png"
    )
    if destination.parent.exists():
        capture(a.root, destination)
    assert len(a.canvas.find_all()) > 30
    dense = a.doc.region(outer, holes, hatch="lines", spacing=1e-5)
    a.changed()
    assert "Hatch preview unavailable" in a.status.get()
    a.doc.delete([dense])
    a.changed()
