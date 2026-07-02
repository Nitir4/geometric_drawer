"""Real GUI acceptance for associative drafting controls."""

import os
from pathlib import Path

import pytest
from test_ui import (
    app as shared_app,
)
from test_ui import (
    button,
    drag,
)
from window_capture import capture

from cad_document import Document
from cad_script import ScriptEngine

app = shared_app

pytestmark = pytest.mark.skipif(
    os.environ.get("CAD_GUI_TESTS") != "1", reason="Native GUI needs a display"
)


def test_linked_gui_numeric_manual_detach_and_code(app):
    a = app
    source = a.doc.circle(20, 20, 5)
    a.selection = [source]
    a.changed()
    a.transform_vars["amount"].set("2")
    button(a.root, "Offset").invoke()
    child = a.selection[0]
    assert a.linked_features.get() and a.doc.entities[child].data["radius"] == 7
    button(a.root, "Select sources").invoke()
    a.root.update()
    a.props["radius"].set("8")
    button(a.root, "Apply to selection").invoke()
    a.root.update()
    assert a.doc.entities[child].data["radius"] == 10
    drag(a, (20, 20), (25, 25))
    assert a.doc.entities[child].x == pytest.approx(25)
    a.selection = [child]
    a.changed()
    a.transform_vars["amount"].set("3")
    button(a.root, "Update feature").invoke()
    assert a.doc.entities[child].data["radius"] == 11
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()
    button(a.root, "Detach").invoke()
    assert not a.doc.features
    a.props["radius"].set("12")
    button(a.root, "Apply to selection").invoke()
    assert a.doc.entities[child].data["radius"] == 12


def test_extension_snap_and_tangent_round_controls(app):
    a = app
    a.doc.line(0, 0, 10, 0)
    a.doc.line(20, -10, 20, 10)
    a.object_snap.set(True)
    a.extension_snap.set(True)
    assert a.snap((20.05, 0.03)) == pytest.approx((20, 0))
    assert "Extension" in a.snap_info.get()
    a.doc.clear()
    first = a.doc.circle(0, 0, 4)
    second = a.doc.circle(20, 0, 3)
    a.selection = [first, second]
    a.changed()
    button(a.root, "Tangents").invoke()
    assert len(a.selection) == 4
    p = a.doc.polyline([(0, 20), (20, 20), (20, 40)])
    a.selection = [p]
    a.changed()
    a.transform_vars["amount"].set("2")
    button(a.root, "Round path").invoke()
    assert a.doc.entities[a.selection[0]].kind == "polyline"
    a.root.geometry("1400x1080")
    a.root.update()
    a.fit()
    a.root.update()
    path = Path(
        "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-features/features-workspace.png"
    )
    if path.parent.is_dir():
        capture(a.root, path)


def test_curve_tangent_gui_controls(app):
    a = app
    ellipse = a.doc.add("ellipse", rx=5, ry=3)
    line = a.doc.line(-10, 4, 10, 4)
    a.doc.constrain("fixed", [ellipse])
    a.constraint_kind.set("curve_tangent")
    a.constraint_refs.set(f"{ellipse},{line}")
    a.constraint_parameters.set(".25,.5")
    a.constraint_add()
    assert a.doc.entities[line].vertices()[0][1] == pytest.approx(3)


def test_viewport_culling_keeps_preview_selection_and_arc_centre_snaps(
    app, monkeypatch
):
    import copy

    a = app
    near = a.doc.circle(20, 20, 3)
    far = a.doc.circle(10000, 10000, 3)
    seen = []
    monkeypatch.setattr(a, "draw_entity", lambda e, *args, **kw: seen.append(e.id))
    a.redraw()
    assert near in seen and far not in seen
    a.selection = [far]
    seen.clear()
    a.redraw()
    assert far in seen
    a.selection = []
    ghost = copy.deepcopy(a.doc.entities[far])
    ghost.x = 20
    ghost.y = 20
    a.preview = {far: ghost}
    seen.clear()
    a.redraw()
    assert far in seen
    a.preview = {}
    a.object_snap.set(True)
    arc = a.doc.arc(300, 100, 10, 0, 30)
    assert a.snap((300.01, 100.01)) == pytest.approx((300, 100))
    assert arc in a.doc.entities
