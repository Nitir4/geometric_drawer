"""Native control-panel and gesture acceptance for assemblies and hatch editing."""

import os
from pathlib import Path

import pytest
from test_ui import app as shared_app
from test_ui import button, click, drag
from window_capture import capture

from cad_document import Document
from cad_regions import hatch_segments
from cad_script import ScriptEngine

app = shared_app
pytestmark = pytest.mark.skipif(
    os.environ.get("CAD_GUI_TESTS") != "1", reason="Native GUI needs display"
)


def test_block_gui_define_place_drag_rotate_copy_and_explode(app):
    a = app
    edge = a.doc.line(0, 0, 10, 0)
    circle = a.doc.circle(5, 5, 2)
    a.selection = [edge, circle]
    a.changed()
    a.block_name.set("part")
    button(a.root, "Define block from selection").invoke()
    a.instance_vars["x"].set("40")
    a.instance_vars["y"].set("20")
    button(a.root, "Insert block").invoke()
    b = a.instance_id.get()
    outputs = list(a.doc.features[b]["outputs"])
    drag(a, (45, 20), (50, 25))
    assert a.doc.features[b]["params"]["x"] == pytest.approx(45)
    assert a.doc.features[b]["params"]["y"] == pytest.approx(25)
    a.selection = outputs
    a.changed()
    f = a.doc.features[b]
    handle = a.block_rotation_handle(f)
    pivot = (f["params"]["x"], f["params"]["y"])
    target = (pivot[0] + handle[1] - pivot[1], pivot[1])
    drag(a, handle, target)
    assert a.doc.features[b]["params"]["angle"] == pytest.approx(-90, abs=1)
    a.transform_vars["dx"].set("30")
    a.transform_vars["dy"].set("0")
    button(a.root, "Copy").invoke()
    assert len(a.doc.features) == 2
    a.instance_id.set(b)
    a.instance_select()
    a.instance_vars["angle"].set("30")
    a.instance_vars["scale"].set("2")
    button(a.root, "Apply instance placement").invoke()
    assert a.doc.features[b]["params"]["angle"] == 30
    assert a.doc.entities[outputs[1]].data["radius"] == 4
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()
    button(a.root, "Explode instance").invoke()
    assert b not in a.doc.features
    assert all("block_key" not in a.doc.entities[i].data for i in outputs)


def test_definition_gui_edit_save_updates_every_instance_and_undo(app):
    a = app
    source = a.doc.circle(0, 0, 2)
    a.doc.define_block("circle", [source])
    first = a.doc.insert_block("circle", 20, 20)
    second = a.doc.insert_block("circle", 40, 20, scale=2)
    a.doc.delete([source])
    a.changed()
    a.block_name.set("circle")
    button(a.root, "Edit block geometry").invoke()
    edit = a.selection[0]
    a.props["radius"].set("3")
    button(a.root, "Apply to selection").invoke()
    state = a.doc.snapshot()
    button(a.root, "Save definition geometry").invoke()
    assert edit not in a.doc.entities
    assert a.doc.entities[a.doc.features[first]["outputs"][0]].data["radius"] == 3
    assert a.doc.entities[a.doc.features[second]["outputs"][0]].data["radius"] == 6
    a.undo()
    assert a.doc.snapshot() == state


def test_groups_gui_pick_move_rotate_ungroup(app):
    a = app
    first = a.doc.circle(10, 10, 2)
    second = a.doc.circle(20, 10, 2)
    a.selection = [first, second]
    a.changed()
    a.group_name.set("pair")
    button(a.root, "Group selected geometry").invoke()
    a.selection = []
    a.changed()
    click(a, (12, 10))
    assert set(a.selection) == {first, second}
    click(a, (12, 10), state=1)
    assert not a.selection
    click(a, (12, 10))
    drag(a, (12, 10), (17, 15))
    assert a.doc.entities[first].x == pytest.approx(15)
    assert a.doc.entities[second].x == pytest.approx(25)
    a.transform_vars["pivot x"].set("15")
    a.transform_vars["pivot y"].set("15")
    a.transform_vars["rotation"].set("90")
    button(a.root, "Rotate").invoke()
    assert (a.doc.entities[second].x, a.doc.entities[second].y) == pytest.approx(
        (15, 25)
    )
    button(a.root, "Ungroup geometry").invoke()
    assert not a.doc.groups and len(a.doc.entities) == 2


def test_pattern_gui_families_preview_apply_holes_and_replay(app):
    a = app
    id = a.doc.region(
        [(0, 0), (40, 0), (40, 30), (0, 30)],
        holes=[[(10, 10), (30, 10), (30, 20), (10, 20)]],
    )
    a.selection = [id]
    a.changed()
    a.tabs.select(a.pattern_tab)
    button(a.root, "Load selected region pattern").invoke()
    a.pattern_tree.selection_set("0")
    a.pattern_family_select()
    for k, v in {
        "angle": "0",
        "offset x": "0",
        "offset y": "3",
        "dashes": "2,-1",
    }.items():
        a.pattern_vars[k].set(v)
    button(a.root, "Update pattern family").invoke()
    for k, v in {
        "angle": "90",
        "offset x": "-3",
        "offset y": "0",
        "dashes": "",
    }.items():
        a.pattern_vars[k].set(v)
    button(a.root, "Add pattern family").invoke()
    a.pattern_name.set("DASHED_GRID")
    button(a.root, "Preview pattern").invoke()
    assert a.pattern_canvas.find_all()
    button(a.root, "Apply custom pattern").invoke()
    assert len(a.doc.entities[id].data["hatch_definition"]) == 2
    assert hatch_segments(a.doc.entities[id])
    a.drawing_to_code()
    d = Document()
    ScriptEngine(d).execute(a.editor.get("1.0", "end-1c"))
    assert d.snapshot() == a.doc.snapshot()
    a.root.geometry("1400x1080")
    a.root.update()
    a.fit()
    a.root.update()
    capture(
        a.root,
        Path(
            "/home/nitir505/Ritin/github-review/artifacts/geometric-cad-blocks/patterns-workspace.png"
        ),
    )


def test_definition_save_preserves_preexisting_geometry_and_group_members(app):
    a = app
    source = a.doc.circle(0, 0, 2)
    existing = a.doc.rectangle(30, 0, 10, 10)
    a.doc.define_block("part", [source])
    instance = a.doc.insert_block("part", 20)
    a.changed()
    a.block_name.set("part")
    button(a.root, "Edit block geometry").invoke()
    edit = a.selection[0]
    a.doc.group("editing", [edit, existing])
    a.selection = [existing]
    a.changed()
    button(a.root, "Save definition geometry").invoke()
    assert edit not in a.doc.entities
    assert existing in a.doc.entities
    assert a.doc.groups["editing"] == [existing]
    assert len(a.doc.features[instance]["outputs"]) == 2
