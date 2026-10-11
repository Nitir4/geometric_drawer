"""Opt-in real Tk event tests. Run with CAD_GUI_TESTS=1 on a display."""

import os
import tkinter as tk
from pathlib import Path

import pytest

from cad_document import Document
from cad_script import ScriptEngine
from cad_ui import EXAMPLE, App

pytestmark = pytest.mark.skipif(
    os.environ.get("CAD_GUI_TESTS") != "1",
    reason="Native GUI tests require CAD_GUI_TESTS=1 and a display",
)


@pytest.fixture
def app(monkeypatch):
    root = tk.Tk()
    # Request a floating test window so a tiling WM does not override the test size.
    if root.tk.call("tk", "windowingsystem") == "x11":
        root.wm_attributes("-type", "dialog")
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(repr(exc))
    monkeypatch.setattr(
        "cad_ui.messagebox.showerror",
        lambda title, message, **kw: errors.append(message),
    )
    a = App(root, load_example=False)
    root.update()
    root.focus_force()
    for id in root.tk.call("after", "info"):
        root.after_cancel(id)
    a.view.scale, a.view.ox, a.view.oy = 4, 80, 450
    a.object_snap.set(False)
    a.grid_snap.set(False)
    a.redraw()
    yield a
    root.destroy()
    assert not errors, errors


def button(widget, text):
    for child in widget.winfo_children():
        if (
            child.winfo_class() in ("TButton", "Button", "TCheckbutton")
            and child.cget("text") == text
        ):
            return child
        found = button(child, text)
        if found:
            return found


def event(a, name, p, **kw):
    x, y = a.view.screen(p)
    a.canvas.event_generate(name, x=round(x), y=round(y), **kw)
    a.root.update()


def click(a, p, **kw):
    event(a, "<ButtonPress-1>", p, **kw)
    event(a, "<ButtonRelease-1>", p, **kw)


def drag(a, p, q):
    event(a, "<ButtonPress-1>", p)
    event(a, "<B1-Motion>", q)
    event(a, "<ButtonRelease-1>", q)


def test_numeric_panel_creation_orientation_apply_and_undo(app):
    a = app
    a.kind_var.set("rectangle")
    a.property_form()
    for k, v in {
        "id": "plate",
        "x": "100",
        "y": "50",
        "orientation": "90",
        "width": "40",
        "height": "20",
    }.items():
        a.props[k].set(v)
    button(a.root, "Create").invoke()
    a.root.update()
    e = a.doc.entities["plate"]
    assert e.vertices()[2] == pytest.approx((80, 90))
    a.props["orientation"].set("0")
    a.props["x"].set("30")
    button(a.root, "Apply to selection").invoke()
    a.root.update()
    assert a.doc.entities["plate"].vertices()[2] == pytest.approx((70, 70))
    a.undo()
    assert a.doc.entities["plate"].vertices()[2] == pytest.approx((80, 90))
    a.redo()
    assert a.doc.entities["plate"].x == 30


def test_code_run_and_manual_edit_share_document(app):
    a = app
    a.editor.insert(
        "1.0", "LINE edge x=0 y=0 length=40\nCIRCLE hole x=20 y=20 radius=5"
    )
    button(a.root, "Run").invoke()
    a.root.update()
    drag(a, (20, 0), (30, 10))
    assert a.doc.entities["edge"].vertices()[0] == pytest.approx((10, 10))
    assert a.doc.entities["edge"].vertices()[1] == pytest.approx((50, 10))
    a.drawing_to_code()
    text = a.editor.get("1.0", "end-1c")
    clone = Document()
    ScriptEngine(clone).execute(text, replace=True)
    assert clone.snapshot() == a.doc.snapshot()


def test_canvas_line_creation_endpoint_handle_and_history(app):
    a = app
    a.tool.set("Line")
    click(a, (5, 5))
    click(a, (45, 5))
    id = next(iter(a.doc.entities))
    a.tool.set("Select")
    old = a.doc.snapshot()
    event(a, "<ButtonPress-1>", (45, 5))
    event(a, "<B1-Motion>", (60, 15))
    assert a.doc.snapshot() == old  # previews do not mutate the document
    event(a, "<ButtonRelease-1>", (60, 15))
    assert a.doc.entities[id].vertices()[1] == pytest.approx((60, 15))
    a.undo()
    assert a.doc.snapshot() == old


def test_rectangle_handle_resize_and_round_grip_rotation(app):
    a = app
    id = a.doc.rectangle(20, 20, 20, 10)
    a.selection = [id]
    a.changed()
    drag(a, (40, 30), (50, 40))
    assert a.doc.entities[id].data["width"] == pytest.approx(30)
    assert a.doc.entities[id].data["height"] == pytest.approx(20)
    grip = a.rotation_handle(a.doc.entities[id])
    drag(a, grip, (20 - (grip[1] - 20), 20 + (grip[0] - 20)))
    assert a.doc.entities[id].angle == pytest.approx(90, abs=0.5)
    a.undo()
    assert a.doc.entities[id].angle == 0


def test_direct_circle_arc_ellipse_polyline_and_bezier(app):
    a = app
    for tool, points, kind in [
        ("Circle", [(10, 10), (15, 10)], "circle"),
        ("Arc", [(30, 30), (40, 30), (30, 40)], "arc"),
        ("Ellipse", [(50, 10), (70, 30)], "ellipse"),
        ("Bezier", [(0, 50), (10, 70), (30, 70), (40, 50)], "bezier"),
    ]:
        a.tool.set(tool)
        for p in points:
            click(a, p)
        assert a.doc.entities[a.selection[0]].kind == kind
    a.tool.set("Polyline")
    for p in [(60, 50), (80, 50), (80, 70)]:
        click(a, p)
    a.canvas.event_generate("<Return>")
    a.root.update()
    assert a.doc.entities[a.selection[0]].kind == "polyline"
    a.tool.set("Line")
    click(a, (0, 0))
    a.canvas.event_generate("<Escape>")
    a.root.update()
    assert not a.pending and a.tool.get() == "Select"


def test_object_grid_ortho_snaps_layer_lock_and_window_selection(app):
    a = app
    a.doc.line(0, 0, 10, 10, id="one")
    a.doc.line(0, 10, 10, 0, id="two")
    a.object_snap.set(True)
    assert a.snap((5.2, 4.9)) == pytest.approx((5, 5))
    a.object_snap.set(False)
    a.grid_snap.set(True)
    a.spacing.set("5")
    assert a.snap((13, 7)) == (15, 5)
    a.ortho.set(True)
    assert a.snap((13, 7), (0, 0)) == (15, 0)
    a.ortho.set(False)
    a.grid_snap.set(False)
    a.changed()
    drag(a, (-2, -2), (12, 12))
    assert set(a.selection) == {"one", "two"}
    a.doc.set_layer("0", locked=True)
    a.changed()
    assert not a.selection
    assert a.hit((5, 5)) is None


def test_save_reopen_dimensions_and_unit_conversion(app, tmp_path, monkeypatch):
    a = app
    line = a.doc.line(0, 0, 100, 0)
    a.selection = [line]
    a.dimension_selection()
    dim = a.selection[0]
    assert a.doc.entities[dim].data["ref"] == line
    path = tmp_path / "part.gdraw"
    monkeypatch.setattr("cad_ui.filedialog.asksaveasfilename", lambda **kw: str(path))
    assert a.save_file()
    saved = a.doc.snapshot()
    a.new_file()
    assert not a.doc.entities
    monkeypatch.setattr("cad_ui.filedialog.askopenfilename", lambda **kw: str(path))
    a.open_file()
    assert a.doc.snapshot() == saved
    a.unit_var.set("in")
    a.change_units()
    assert a.doc.entities[line].vertices()[1][0] == pytest.approx(100 / 25.4)
    a.doc.transform([line], scale=2)
    a.changed()
    assert a.doc.entities[dim].label()[1] == f"{200 / 25.4:.3f}"


def test_dimension_drag_detaches_source_and_remains_undoable(app):
    a = app
    line = a.doc.line(0, 0, 40, 0)
    dim = a.doc.dimension(line, offset=8)
    a.selection = [dim]
    a.changed()
    old = a.doc.snapshot()
    drag(a, (20, 8), (20, 18))
    assert "ref" not in a.doc.entities[dim].data
    assert a.doc.entities[dim].y == pytest.approx(10)
    assert a.doc.entities[line].vertices()[0] == (0, 0)
    a.undo()
    assert a.doc.snapshot() == old


def test_capture_rendered_workspace(app):
    from window_capture import capture

    a = app
    if a.root.tk.call("tk", "windowingsystem") != "x11":
        pytest.skip("Application-only capture currently requires X11/XWayland.")
    ScriptEngine(a.doc).execute(EXAMPLE)
    a.selection = ["plate"]
    a.changed()
    a.fit()
    a.root.update()
    gx, gy = a.view.screen(a.rotation_handle(a.doc.entities["plate"]))
    assert 0 < gx < a.canvas.winfo_width()
    assert 0 < gy < a.canvas.winfo_height()
    directory = (
        Path(__file__).resolve().parents[3]
        / "artifacts"
        / "geometric-cad-geometric-only"
    )
    directory.mkdir(exist_ok=True, parents=True)
    capture(a.root, directory / "workspace.png")
    a.tabs.select(1)
    a.drawing_to_code()
    a.root.update()
    capture(a.root, directory / "code-workspace.png")
    assert len(a.canvas.find_all()) > 30


def test_constraint_panel_drives_canvas_code_and_undo(app):
    a = app
    a.doc.line(0, 0, 20, 0, id="edge")
    a.changed()
    a.tabs.select(a.constraint_tab)
    a.constraint_kind.set("length")
    a.constraint_refs.set("edge")
    a.constraint_value.set("40")
    button(a.root, "Add constraint").invoke()
    a.root.update()
    from cad_geometry import distance

    assert distance(*a.doc.entities["edge"].vertices()) == pytest.approx(40)
    id = next(iter(a.doc.constraints))
    a.constraint_tree.selection_set(id)
    a.root.update()
    a.constraint_value.set("55")
    button(a.root, "Update driving value").invoke()
    a.root.update()
    assert distance(*a.doc.entities["edge"].vertices()) == pytest.approx(55)
    a.undo()
    assert distance(*a.doc.entities["edge"].vertices()) == pytest.approx(40)
    # Direct edits also respect saved driving values.
    drag(a, (25, 0), (45, 10))
    assert distance(*a.doc.entities["edge"].vertices()) == pytest.approx(40)
    a.drawing_to_code()
    clone = Document()
    ScriptEngine(clone).execute(a.editor.get("1.0", "end-1c"), replace=True)
    assert clone.snapshot() == a.doc.snapshot()
    a.constraint_tree.selection_set(id)
    button(a.root, "Remove constraint").invoke()
    a.root.update()
    assert not a.doc.constraints


def test_intersection_snap_with_more_than_eighty_lines(app):
    a = app
    for i in range(100):
        a.doc.line(200 + i, 200, 200 + i, 300)
    a.doc.line(0, 0, 40, 40)
    a.doc.line(0, 40, 40, 0)
    a.object_snap.set(True)
    assert a.snap((20.7, 20.3)) == pytest.approx((20, 20))


def test_constraint_workspace_capture(app):
    from window_capture import capture

    a = app
    ScriptEngine(a.doc).execute(
        "LINE edge length=80\nCIRCLE hole x=40 y=25 radius=8\nCONSTRAINT width kind=length refs=edge value=80\nCONSTRAINT level kind=horizontal refs=edge\nCONSTRAINT bore kind=radius refs=hole value=8"
    )
    a.changed()
    a.tabs.select(a.constraint_tab)
    a.fit()
    a.root.update()
    output = Path(
        "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-geometric-only/constraints-workspace.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if a.root.tk.call("tk", "windowingsystem") != "x11":
        pytest.skip("App-only capture requires X11/XWayland")
    capture(a.root, output)
    assert output.stat().st_size > 10000


def test_geometric_only_controls_and_native_state(app):
    from cad_geometry import KINDS
    from cad_ui import DEFAULTS, TOOLS

    a = app
    assert [a.tabs.tab(tab, "text") for tab in a.tabs.tabs()] == [
        "Control panel",
        "Code",
        "Parameters",
        "Constraints",
        "Assemblies",
        "Patterns",
        "Guide",
    ]
    assert set(DEFAULTS) == set(KINDS)
    assert set(TOOLS) == {
        "Select",
        "Line",
        "Rectangle",
        "Circle",
        "Arc",
        "Ellipse",
        "Polyline",
        "Bezier",
        "Point",
        "Text",
        "Dimension",
        "Radial dimension",
        "Angular dimension",
    }
    a.tool.set("Line")
    click(a, (0, 0))
    click(a, (20, 0))
    assert next(iter(a.doc.entities.values())).data == {"points": [(0, 0), (20, 0)]}
    assert "probes" not in a.doc.snapshot()
    assert not hasattr(a, "experiments")


def test_native_corner_controls_pick_crossing_side_and_undo(app):
    a = app
    a.linked_features.set(False)
    a.doc.line(-20, 0, 20, 0, id="horizontal")
    a.doc.line(0, -20, 0, 20, id="vertical")
    a.selection = ["horizontal", "vertical"]
    a.changed()
    before = a.doc.snapshot()
    a.transform_vars["pivot x"].set("-10")
    a.transform_vars["pivot y"].set("10")
    a.transform_vars["amount"].set("5")
    button(a.root, "Fillet").invoke()
    a.root.update()
    arc = next(e for e in a.doc.entities.values() if e.kind == "arc")
    assert (arc.x, arc.y) == pytest.approx((-5, 5))
    a.fit()
    a.root.update()
    if a.root.tk.call("tk", "windowingsystem") == "x11":
        from window_capture import capture

        output = Path(
            "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-corners-snaps/corner-workspace.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        capture(a.root, output)
    a.undo()
    assert a.doc.snapshot() == before
    button(a.root, "Chamfer").invoke()
    a.root.update()
    connector = next(
        e for id, e in a.doc.entities.items() if id not in {"horizontal", "vertical"}
    )
    assert connector.vertices()[0] == pytest.approx((-5, 0))
    assert connector.vertices()[1] == pytest.approx((0, 5))


def test_native_circle_arc_intersection_snaps_and_visibility(app):
    a = app
    a.doc.arc(0, 0, 5, 0, 180, id="upper")
    a.doc.circle(6, 0, 5, id="circle")
    a.object_snap.set(True)
    assert a.snap((3.1, 4.1)) == pytest.approx((3, 4))
    assert a.snap((3.1, -4.1)) == (3.1, -4.1)
    a.doc.set_layer("hidden", visible=False)
    circle = a.doc.entities["circle"]
    circle.layer = "hidden"
    assert a.snap((3.1, 4.1)) == (3.1, 4.1)


def test_native_high_zoom_circle_snap_does_not_depend_on_mesh(app):
    import math

    a = app
    a.doc.circle(0, 0, 10, id="circle")
    a.doc.line(-20, 5, 20, 5, id="line")
    a.object_snap.set(True)
    a.view.scale = 100000
    x = math.sqrt(75)
    assert a.snap((x + 1e-5, 5 + 1e-5)) == pytest.approx((x, 5), abs=1e-9)


def test_native_rectangle_polyline_edge_snaps_and_preview_exclusion(app):
    a = app
    a.doc.rectangle(0, 0, 10, 6, angle=90, id="box")
    a.doc.line(-10, 3, 4, 3, id="cut")
    a.object_snap.set(True)
    a.view.scale = 20
    before = a.doc.snapshot()
    assert a.snap((-0.1, 3.1)) == pytest.approx((0, 3))
    assert a.snap_info.get() == "Snap: Intersection"
    a.preview["box"] = a.doc.entities["box"]
    assert a.snap((-0.1, 3.1)) == (-0.1, 3.1)
    a.preview.clear()
    a.doc.polyline([(20, 0), (32, 12), (20, 12), (26, 0)], id="cross")
    assert a.snap((24.1, 4.1)) == pytest.approx((24, 4))
    assert all(e.kind != "_snap_edge" for e in a.doc.entities.values())
    assert before["entities"] == a.doc.snapshot()["entities"][:2]


def test_native_perpendicular_line_creation_and_ortho_priority(app):
    a = app
    a.doc.line(0, 0, 20, 20, id="target")
    a.changed()
    assert not a.perpendicular_snap.get() and not a.tangent_snap.get()
    a.object_snap.set(True)
    a.ortho.set(True)
    button(a.root, "Perpendicular").invoke()
    assert a.perpendicular_snap.get()
    a.tool.set("Line")
    click(a, (12, 0))
    event(a, "<Motion>", (6.25, 6.25))
    assert a.snap_info.get() == "Snap: Perpendicular"
    click(a, (6.25, 6.25))
    line = a.doc.entities[a.selection[0]]
    assert line.vertices()[0] == pytest.approx((12, 0))
    assert line.vertices()[1] == pytest.approx((6, 6))
    a.undo()
    assert list(a.doc.entities) == ["target"]


def test_native_tangent_drafting_capture_and_master_toggle(app):
    import math

    a = app
    a.doc.circle(0, 0, 5, id="circle")
    a.doc.add("point", x=10, y=0, id="start")
    a.changed()
    a.fit()
    a.object_snap.set(True)
    a.ortho.set(True)
    button(a.root, "Tangent").invoke()
    a.tool.set("Line")
    click(a, (10, 0))
    q = 2.5, math.sqrt(18.75)
    event(a, "<Motion>", q)
    assert a.snap_info.get() == "Snap: Tangent"
    if a.root.tk.call("tk", "windowingsystem") == "x11":
        from window_capture import capture

        output = Path(
            "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-drafting-snaps/tangent-workspace.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        capture(a.root, output)
    click(a, q)
    line = a.doc.entities[a.selection[0]]
    assert line.vertices()[1] == pytest.approx(q)
    a.object_snap.set(False)
    assert a.snap((2.6, 4.4), (10, 0)) == (2.6, 0)  # ordinary Ortho fallback
    a.snap_settings_changed()
    assert a.snap_info.get() == "Snap: —"


def test_native_exact_intersection_survives_ortho(app):
    a = app
    a.doc.circle(0, 0, 5, id="circle")
    a.doc.line(-10, 3, 10, 3, id="line")
    a.object_snap.set(True)
    a.ortho.set(True)
    assert a.snap((4.1, 3.1), (10, 0)) == pytest.approx((4, 3))


def test_native_ellipse_tangent_clicks_with_ortho(app):
    import math

    a = app
    a.doc.add("ellipse", rx=10, ry=5, id="oval")
    a.doc.add("point", x=20, y=0, id="start")
    a.changed()
    a.fit()
    a.object_snap.set(True)
    a.ortho.set(True)
    button(a.root, "Tangent").invoke()
    a.tool.set("Line")
    click(a, (20, 0))
    q = 5, math.sqrt(18.75)
    event(a, "<Motion>", q)
    assert a.snap_info.get() == "Snap: Tangent"
    click(a, q)
    assert a.doc.entities[a.selection[0]].vertices()[1] == pytest.approx(q)
    a.undo()
    assert list(a.doc.entities) == ["oval", "start"]


def test_native_bezier_nearest_and_high_zoom_intersections(app):
    a = app
    a.doc.add("bezier", id="bow", points=[(0, 0), (4, 4), (8, 4), (12, 0)])
    a.doc.line(0, 2.25, 12, 2.25, id="cut")
    a.object_snap.set(True)
    a.view.scale = 1e6
    assert a.snap((3 + 1e-6, 2.25 + 1e-6)) == pytest.approx((3, 2.25), abs=1e-8)
    assert a.snap_info.get() == "Snap: Intersection"
    a.view.scale = 40
    button(a.root, "Nearest").invoke()
    assert a.nearest_snap.get()
    a.doc.delete(["cut"])
    expected = (4, 8 / 3)
    # Cursor displaced outward along the parabola normal at X=4.
    cursor = expected[0] - 0.03, expected[1] + 0.09
    assert a.snap(cursor) == pytest.approx(expected, abs=1e-7)
    assert a.snap_info.get() == "Snap: Nearest"
    a.object_snap.set(False)
    assert a.snap(cursor) == cursor


def test_native_curve_offset_control_code_and_manual_vertex_edit(app):
    a = app
    a.linked_features.set(False)
    a.editor.insert("1.0", "ELLIPSE oval rx=10 ry=5")
    button(a.root, "Run").invoke()
    a.selection = ["oval"]
    a.changed()
    a.transform_vars["amount"].set("1")
    a.transform_vars["curve tol"].set("0.02")
    button(a.root, "Offset").invoke()
    id = a.selection[0]
    e = a.doc.entities[id]
    assert e.kind == "polyline"
    assert e.data["offset_approximation"]["tolerance"] == 0.02
    a.drawing_to_code()
    clone = Document()
    ScriptEngine(clone).execute(a.editor.get("1.0", "end-1c"))
    assert clone.snapshot() == a.doc.snapshot()
    first = e.vertices()[0]
    drag(a, first, (first[0] + 2, first[1]))
    assert a.doc.entities[id].vertices()[0] == pytest.approx((first[0] + 2, first[1]))
    assert "offset_approximation" not in a.doc.entities[id].data
    a.undo()
    assert a.doc.entities[id].data["offset_approximation"]["tolerance"] == 0.02
    a.undo()
    assert list(a.doc.entities) == ["oval"]


def test_native_curve_workspace_capture(app):
    import math

    a = app
    ScriptEngine(a.doc).execute(
        (Path(__file__).resolve().parents[1] / "examples/curves.cad").read_text()
    )
    a.changed()
    a.fit()
    a.object_snap.set(True)
    button(a.root, "Tangent").invoke()
    a.transform_vars["curve tol"].set("0.02")
    a.tool.set("Line")
    click(a, (40, 0))
    event(a, "<Motion>", (10, math.sqrt(75)))
    assert a.snap_info.get() == "Snap: Tangent"
    if a.root.tk.call("tk", "windowingsystem") == "x11":
        from window_capture import capture

        output = Path(
            "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-curves/curves-workspace.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        capture(a.root, output)
