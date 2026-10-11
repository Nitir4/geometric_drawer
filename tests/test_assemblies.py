"""Reusable design geometry, group transforms and patterned material."""

import json

import pytest
from shapely.geometry import LineString

from cad_document import Document
from cad_geometry import distance
from cad_regions import hatch_segments, polygon
from cad_script import ScriptEngine, document_script


def replay(d, tmp_path):
    d.save(tmp_path / "assemblies.gdraw")
    assert Document.load(tmp_path / "assemblies.gdraw").snapshot() == d.snapshot()
    other = Document()
    ScriptEngine(other).execute(document_script(d))
    assert other.snapshot() == d.snapshot()


def test_block_placement_definition_update_copy_units_and_replay(tmp_path):
    d = Document()
    edge = d.line(10, 20, 20, 20)
    circle = d.circle(15, 25, 2)
    d.define_block("bracket", [edge, circle], base=(10, 20))
    block = d.insert_block("bracket", 100, 50, 90, 2)
    ids = d.features[block]["outputs"]
    assert d.entities[ids[0]].vertices()[0] == pytest.approx((100, 50))
    assert d.entities[ids[0]].vertices()[1] == pytest.approx((100, 70))
    assert (d.entities[ids[1]].x, d.entities[ids[1]].y) == pytest.approx((90, 60))
    assert d.entities[ids[1]].data["radius"] == 4
    duplicate = d.transform([ids[0]], dx=30, copy_entities=True)
    assert len(duplicate) == 2
    assert len(d.features) == 2
    second = d.feature_for(duplicate[0])
    d.transform([block], dx=5, rotation=90, pivot=(100, 50))
    assert d.features[block]["params"]["angle"] == 180
    assert d.entities[ids[0]].vertices()[0] == pytest.approx((105, 50))
    edits = d.block_edit_copies("bracket")
    with d.transaction("edit definition"):
        d.entities[edits[1]].data["radius"] = 3
    d.define_block("bracket", edits)
    assert d.entities[ids[1]].data["radius"] == 6
    assert d.entities[duplicate[1]].data["radius"] == 6
    d.delete(edits)
    d.set_units("cm")
    assert d.entities[ids[1]].data["radius"] == pytest.approx(0.6)
    assert second["params"]["x"] == pytest.approx(13)
    replay(d, tmp_path)


def test_block_stable_keys_reorder_retirement_and_dependent_feature(tmp_path):
    d = Document()
    a = d.circle(0, 0, 3)
    b = d.rectangle(10, 0, 4, 5)
    d.define_block("shape", [a, b])
    instance = d.insert_block("shape", 20, 20)
    old = list(d.features[instance]["outputs"])
    child = d.offset(old[0], 1)
    edits = d.block_edit_copies("shape")
    d.define_block("shape", list(reversed(edits)))
    assert d.features[instance]["outputs"] == list(reversed(old))
    assert d.entities[child].data["radius"] == 4
    d.define_block("shape", [edits[1]])
    assert d.features[instance]["outputs"] == [old[1]]
    assert child not in d.entities
    assert not any(f["kind"] == "offset" for f in d.features.values())
    replay(d, tmp_path)


def test_block_drivers_locks_explode_and_deletion(tmp_path):
    d = Document()
    c = d.circle(0, 0, 2)
    d.define_block("unit", [c])
    b = d.insert_block("unit", 10, 20)
    d.set_parameter("pitch", "10")
    d.bind(b, "x", "pitch", target="feature")
    d.bind(b, "scale", "2", target="feature")
    d.set_parameter("pitch", "30")
    id = d.features[b]["outputs"][0]
    assert d.entities[id].x == 30 and d.entities[id].data["radius"] == 4
    d.set_layer("0", locked=True)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.set_parameter("pitch", "40")
    assert d.snapshot() == state
    d.set_layer("0", locked=False)
    d.detach_feature(b)
    assert not d.features and not d.bindings and "block_key" not in d.entities[id].data
    d.remove_block("unit")
    replay(d, tmp_path)


def test_group_atomic_transforms_copy_delete_and_native(tmp_path):
    d = Document()
    a = d.line(0, 0, 5, 0)
    b = d.circle(5, 5, 1)
    assert d.group("part", [a, b]) == [a, b]
    d.transform([a], dx=10)
    assert d.entities[a].x == 10 and d.entities[b].x == 15
    copy = d.transform(["part"], dy=20, copy_entities=True)
    assert len(copy) == 2 and len(d.groups) == 2
    assert d.groups["part_copy"] == copy
    d.constrain("fixed", [a])
    state = d.snapshot()
    # Constraints project the group transform; no fixed source can move.
    d.transform(["part"], dx=3)
    assert d.entities[a].x == 10
    assert d.entities[b].x == 18
    d.undo()
    assert d.snapshot() == state
    replay(d, tmp_path)
    d.delete(["part"])
    assert "part" not in d.groups and a not in d.entities and b not in d.entities


def test_group_locks_and_overlap_rollback():
    d = Document()
    d.set_layer("locked")
    a = d.circle(0, 0, 1)
    b = d.circle(5, 0, 1, layer="locked")
    d.group("both", [a, b])
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.group("overlap", [a])
    assert d.snapshot() == state
    d.set_layer("locked", locked=True)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.transform([a], dx=5)
    assert d.snapshot() == state
    assert d.ungroup("both") == [a, b]
    assert a in d.entities and b in d.entities


def test_pattern_api_holes_units_and_rollback(tmp_path):
    d = Document()
    r = d.region(
        [(0, 0), (20, 0), (20, 20), (0, 20)],
        holes=[[(5, 5), (15, 5), (15, 15), (5, 15)]],
    )
    families = [[0, (0, 0), (0, 3), [2, -1]], [90, (0, 0), (-3, 0), []]]
    d.set_region_pattern(r, families, name="DASHED_GRID")
    segments = hatch_segments(d.entities[r])
    shape = polygon(d.entities[r])
    assert len(segments) > 10
    assert all(
        LineString([a, b]).difference(shape.buffer(1e-8)).length < 1e-7
        for a, b in segments
    )
    d.set_units("cm")
    after = hatch_segments(d.entities[r])
    assert sorted(distance(a, b) for a, b in after) == pytest.approx(
        sorted(distance(a, b) / 10 for a, b in segments), abs=1e-8
    )
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.set_region_pattern(r, [[0, (0, 0), (2, 0), []]])
    assert d.snapshot() == state
    replay(d, tmp_path)


def test_assembly_dsl_and_old_document_defaults(tmp_path):
    d = Document()
    ScriptEngine(d).execute("""LINE edge length=10
CIRCLE hole x=5 y=5 radius=2
BLOCK part refs=edge,hole
INSERT part id=one x=20 angle=90 scale=2
INSERT part id=two x=60
GROUP source edge hole
MOVE source dx=5
""")
    assert len(d.features) == 2 and len(d.blocks) == 1
    replay(d, tmp_path)
    ScriptEngine(d).execute("EXPLODE one\nUNGROUP source")
    assert "one" not in d.features and not d.groups
    d.clear()
    assert not d.blocks and not d.groups
    state = d.snapshot()
    state.pop("blocks")
    state.pop("groups")
    (tmp_path / "old.gdraw").write_text(json.dumps(state))
    assert Document.load(tmp_path / "old.gdraw").blocks == {}


@pytest.mark.parametrize("name", ["", "bad name", "1part", "bad/name"])
def test_invalid_block_names_atomic(name):
    d = Document()
    id = d.circle(0, 0, 1)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.define_block(name, [id])
    assert d.snapshot() == state


def test_reflected_blocks_preserve_regions_arcs_and_patterns(tmp_path):
    d = Document()
    r = d.region(
        [(0, 0), (10, 0), (10, 8), (0, 8)],
        holes=[[(2, 2), (4, 2), (4, 4), (2, 4)]],
        hatch="custom",
        hatch_definition=[[30, (1, 2), (-2, 3), [2, -1]]],
    )
    arc = d.arc(20, 5, 3, 20, 100)
    rect = d.rectangle(0, 20, 5, 10, angle=30)
    d.define_block("material", [r, arc, rect])
    b = d.insert_block("material", 50, 20, angle=35)
    ids = list(d.features[b]["outputs"])
    before = {id: d.entities[id].paths() for id in ids}
    d.mirror([ids[0]], (0, 0), (1, 0))
    assert d.features[b]["params"]["mirror"]
    for id in ids:
        expected = [[(x, -y) for x, y in ring] for ring in before[id]]
        actual = d.entities[id].paths()
        if d.entities[id].kind == "rectangle":
            assert all(
                any(distance(p, q) < 1e-7 for q in actual[0]) for p in expected[0]
            )
        else:
            for old, new in zip(expected, actual):
                assert len(old) == len(new)
                for a, c in zip(old, new):
                    assert a == pytest.approx(c, abs=1e-7)
    assert polygon(d.entities[ids[0]]).area == pytest.approx(76)
    segments = hatch_segments(d.entities[ids[0]])
    assert segments
    replay(d, tmp_path)
    d.mirror([b], (0, 0), (1, 0))
    assert not d.features[b]["params"]["mirror"]
    for id in ids:
        for old, new in zip(before[id], d.entities[id].paths()):
            for a, c in zip(old, new):
                assert a == pytest.approx(c, abs=1e-7)


def test_grouped_block_copy_and_definition_update_remaps_all_members(tmp_path):
    d = Document()
    source = d.circle(0, 0, 1)
    d.define_block("symbol", [source])
    b = d.insert_block("symbol", 20)
    text = d.add("text", x=30, y=0, text="A", height=3)
    output = d.features[b]["outputs"][0]
    d.group("assembly", [output, text])
    copies = d.transform(["assembly"], dy=20, copy_entities=True)
    assert len(copies) == 2 and d.groups["assembly_copy"] == copies
    assert sum(f["kind"] == "block" for f in d.features.values()) == 2
    d.transform([text], dx=5)
    assert d.features[b]["params"]["x"] == 25
    assert d.entities[text].x == 35
    replay(d, tmp_path)


def test_definition_lock_rollback_and_missing_library_validation(tmp_path):
    d = Document()
    a = d.circle(0, 0, 2)
    d.define_block("part", [a])
    d.insert_block("part", 10)
    d.set_layer("0", locked=True)
    state = d.snapshot()
    with pytest.raises(ValueError):
        d.define_block("part", [a], base=(1, 0))
    assert d.snapshot() == state
    with pytest.raises(ValueError):
        d.remove_block("part")
    assert d.snapshot() == state
    path = tmp_path / "invalid.gdraw"
    state["blocks"] = {}
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        Document.load(path)


def test_assembly_external_exports_keep_visible_geometry(tmp_path):
    from cad_exchange import export_dxf, export_pdf, export_svg, import_dxf

    d = Document()
    circle = d.circle(0, 0, 2)
    d.define_block("unit", [circle])
    d.insert_block("unit", 20, 10, scale=2)
    d.insert_block("unit", 40, 10, scale=3, mirror=True)
    d.delete([circle])
    for ext, writer in (("dxf", export_dxf), ("svg", export_svg), ("pdf", export_pdf)):
        writer(d, tmp_path / ("blocks." + ext))
    other = import_dxf(tmp_path / "blocks.dxf")
    circles = sorted(
        (e.x, e.y, e.data["radius"])
        for e in other.entities.values()
        if e.kind == "circle"
    )
    assert circles == [(20, 10, 4), (40, 10, 6)]


def test_pattern_dsl_and_reflected_insert(tmp_path):
    d = Document()
    ScriptEngine(d).execute("""REGION plate rings="[[[0,0],[20,0],[20,20],[0,20]]]"
PATTERN plate name=DASHES data="[[0,[0,0],[0,2],[3,-1]]]"
BLOCK panel refs=plate
INSERT panel id=mirrored x=30 mirror=true
""")
    assert d.features["mirrored"]["params"]["mirror"]
    assert hatch_segments(d.entities[d.features["mirrored"]["outputs"][0]])
    replay(d, tmp_path)


def test_copying_definition_member_creates_a_new_template_key():
    d = Document()
    source = d.circle(0, 0, 2)
    d.define_block("part", [source])
    b = d.insert_block("part", 20)
    originals = d.block_edit_copies("part")
    copied = d.transform(originals, dy=5, copy_entities=True)
    d.define_block("part", originals + copied)
    assert len(d.blocks["part"]) == 2
    assert len({e["id"] for e in d.blocks["part"]}) == 2
    assert len(d.features[b]["outputs"]) == 2


def test_template_kind_change_retires_identity_and_freezes_measurement():
    d = Document()
    source = d.circle(0, 0, 2)
    d.define_block("part", [source])
    b = d.insert_block("part", 20)
    old = d.features[b]["outputs"][0]
    dimension = d.dimension(old)
    child = d.offset(old, 1)
    edit = d.block_edit_copies("part")[0]
    with d.transaction("new template kind"):
        e = d.entities[edit]
        key = e.data["block_edit_key"]
        e.kind = "line"
        e.data = {"points": [(0, 0), (5, 0)], "block_edit_key": key}
    d.define_block("part", [edit])
    assert old not in d.entities and child not in d.entities
    assert d.entities[d.features[b]["outputs"][0]].kind == "line"
    assert "ref" not in d.entities[dimension].data
