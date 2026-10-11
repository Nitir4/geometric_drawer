"""Association, drafting geometry and rollback regressions."""

import copy
import itertools
import json
import math

import pytest

from cad_constraints import residual
from cad_document import Document
from cad_features import parameter_curve, split_bezier
from cad_geometry import distance, sub
from cad_operations import on_curve
from cad_script import ScriptEngine, document_script
from cad_snap import extension_part


def test_linked_offset_chain_detach_and_history(tmp_path):
    d = Document()
    a = d.line(0, 0, 20, 0)
    b = d.offset(a, 2)
    c = d.offset(b, 3)
    d.transform([a], dy=7)
    assert d.entities[c].vertices()[0][1] == pytest.approx(12)
    d.undo()
    assert d.entities[c].vertices()[0][1] == pytest.approx(5)
    d.redo()
    with pytest.raises(ValueError, match="detach"):
        d.transform([b], dy=1)
    d.update_feature(b, amount=4)
    assert d.entities[c].vertices()[0][1] == pytest.approx(14)
    d.detach_feature(b)
    d.transform([b], dy=2)
    assert d.entities[c].vertices()[0][1] == pytest.approx(16)
    path = tmp_path / "linked.gdraw"
    d.save(path)
    assert Document.load(path).snapshot() == d.snapshot()
    clone = Document()
    ScriptEngine(clone).execute(document_script(d), replace=True)
    assert clone.snapshot() == d.snapshot()
    d.delete(a)
    assert b in d.entities and c in d.entities
    d.delete(b)
    assert not d.features and c not in d.entities


def test_linked_units_invalid_radius_and_constraint_source():
    d = Document()
    a = d.circle(0, 0, 10)
    b = d.offset(a, -2)
    rule = d.constrain("radius", [a], 12)
    assert d.entities[b].data["radius"] == pytest.approx(10)
    d.set_units("cm")
    assert d.entities[b].data["radius"] == pytest.approx(1)
    assert d.feature_for(b)["params"]["amount"] == pytest.approx(-0.2)
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_constraint_value(rule, 0.1)
    assert d.snapshot() == before
    with pytest.raises(ValueError, match="source|detach"):
        d.constrain("radius", [b], 2)
    assert d.snapshot() == before


def test_linked_fillets_keep_sources_editable_and_detach():
    d = Document()
    a = d.line(0, 0, 20, 0)
    b = d.line(20, 0, 20, 20)
    arc = d.corner(a, b, 2)
    f = d.feature_for(arc)
    assert d.entities[a].construction and len(f["outputs"]) == 3
    assert d.entities[a].vertices()[1] == (20, 0)
    d.transform([a, b], dx=10)
    assert d.entities[arc].x == pytest.approx(28)
    d.update_feature(arc, amount=3)
    assert d.entities[arc].data["radius"] == 3
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.update_feature(arc, amount=40)
    assert d.snapshot() == before
    d.detach_feature(arc)
    d.transform([arc], dx=2)
    assert not d.features


@pytest.mark.parametrize("fillet", [True, False])
def test_zero_radius_corner_and_parallel_round(fillet):
    d = Document()
    a = d.line(0, 0, 10, 0)
    b = d.line(20, 0, 20, 10)
    assert d.corner(a, b, 0, fillet=fillet, linked=False) is None
    assert d.entities[a].vertices()[1] == (20, 0)
    assert d.entities[b].vertices()[0] == (20, 0)
    d = Document()
    a = d.line(0, 0, 20, 0)
    b = d.line(0, 6, 20, 6)
    arc = d.corner(a, b, 3, linked=False)
    assert abs(d.entities[arc].data["sweep"]) == 180
    assert (
        distance(parameter_curve(d.entities[arc])(0)[0], d.entities[a].vertices()[1])
        < 1e-7
    )


@pytest.mark.parametrize("other", ["circle", "arc", "ellipse", "bezier"])
def test_curved_fillet_contacts(other):
    d = Document()
    a = d.line(-20, 0, 20, 0)
    if other == "circle":
        b = d.circle(0, 8, 5)
    elif other == "arc":
        b = d.arc(0, 8, 5, 180, 180)
    elif other == "ellipse":
        b = d.add("ellipse", x=0, y=8, rx=6, ry=5)
    else:
        b = d.add("bezier", points=[(-5, 7), (-2, 2.5), (2, 2.5), (5, 7)])
    originals = copy.deepcopy(d.entities)
    arc = d.corner(a, b, 2, pick=(0, 1))
    connector = d.entities[arc]
    p, q = parameter_curve(connector)(0)[0], parameter_curve(connector)(1)[0]
    assert on_curve(originals[a], p, 1e-6)
    assert on_curve(originals[b], q, 1e-6)
    centre = connector.x, connector.y
    assert (
        abs(sum(x * y for x, y in zip(sub(p, centre), sub(*originals[a].vertices()))))
        < 1e-5
    )
    assert distance(p, centre) == pytest.approx(2)
    assert distance(q, centre) == pytest.approx(2)
    assert len(d.feature_for(arc)["outputs"]) == 3
    if other in ("circle", "ellipse"):
        trimmed = d.entities[d.feature_for(arc)["outputs"][1]]
        assert trimmed.kind == other and trimmed.data == originals[b].data


def test_bezier_subdivision_preserves_curve():
    d = Document()
    b = d.add("bezier", points=[(0, 0), (2, 8), (9, -2), (12, 0)])
    original = d.entities[b]
    left, right = split_bezier(original.data["points"], 0.37)
    f = parameter_curve(original)
    for points, start, span in ((left, 0, 0.37), (right, 0.37, 0.63)):
        piece = copy.deepcopy(original)
        piece.data["points"] = points
        g = parameter_curve(piece)
        for t in (0, 0.2, 0.7, 1):
            assert distance(f(start + span * t)[0], g(t)[0]) < 1e-10


@pytest.mark.parametrize(
    "kind,expected", [("both", 4), ("external", 2), ("internal", 2)]
)
def test_common_tangents_and_regeneration(kind, expected):
    d = Document()
    a, b = d.circle(0, 0, 4), d.circle(20, 0, 3)
    ids = d.common_tangents(a, b, kind=kind)
    assert len(ids) == expected
    d.transform([b], dy=3)
    for id in ids:
        p, q = d.entities[id].vertices()
        for circle, contact in ((d.entities[a], p), (d.entities[b], q)):
            assert on_curve(circle, contact, 1e-7)
            assert (
                abs(
                    sum(
                        x * y
                        for x, y in zip(sub(q, p), sub(contact, (circle.x, circle.y)))
                    )
                )
                < 1e-6
            )
    feature = d.feature_for(ids[0])["id"]
    d.transform([b], dx=-20, dy=-3)
    assert not d.features[feature]["outputs"]
    assert not set(ids).intersection(d.entities)
    d.transform([b], dx=20)
    assert len(d.features[feature]["outputs"]) == expected


@pytest.mark.parametrize("closed", [True, False])
def test_round_path_radius_error_budget_and_invalid_overlap(closed):
    d = Document()
    a = d.polyline([(0, 0), (20, 0), (20, 20), (0, 20)], closed=closed)
    b = d.round_path(a, 2, tolerance=0.01)
    e = d.entities[b]
    assert e.kind == "polyline" and e.data["closed"] == closed
    assert len(e.vertices()) > 8
    # First round of an open path is centred on (18,2).
    if not closed:
        rounded = [p for p in e.vertices() if p[0] >= 18 and p[1] <= 2]
        for p, q in itertools.pairwise(rounded):
            midpoint = tuple((x + y) / 2 for x, y in zip(p, q))
            assert 2 - distance(midpoint, (18, 2)) <= 0.01000001
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.update_feature(b, radius=12)
    assert d.snapshot() == before
    d.transform([a], dx=4)
    assert d.entities[b].bounds()[0] == pytest.approx(4)


def test_round_selected_vertex():
    d = Document()
    a = d.polyline([(0, 0), (10, 0), (10, 10), (20, 10)])
    b = d.round_path(a, 1, vertex=1)
    assert (10, 10) in d.entities[b].vertices()
    assert (10, 0) not in d.entities[b].vertices()


@pytest.mark.parametrize("join", ["round", "mitre", "bevel"])
def test_clean_offset_repairs_and_retains_components(join):
    d = Document()
    a = d.polyline([(0, 0), (10, 10), (0, 10), (10, 0)], closed=True)
    ids = d.clean_offset(a, 0, join=join)
    assert len(ids) == 2
    assert all(d.entities[i].data["cleanup"]["role"] == "outer" for i in ids)
    d.transform([a], dx=3)
    assert min(d.entities[i].bounds()[0] for i in ids) == pytest.approx(3)
    feature = d.feature_for(ids[0])["id"]
    d.update_feature(feature, amount=10)
    assert len(d.features[feature]["outputs"]) == 1
    assert set(ids).intersection(d.features[feature]["outputs"])
    d.update_feature(feature, amount=0)
    assert len(d.features[feature]["outputs"]) == 2


def test_clean_offset_open_bezier_and_closed_ellipse():
    d = Document()
    a = d.add("bezier", points=[(0, 0), (3, 2), (8, 2), (12, 0)])
    assert d.clean_offset(a, 1)
    b = d.add("ellipse", x=20, rx=8, ry=4)
    assert d.clean_offset(b, 1)


def test_curve_tangent_contacts_persistence_and_invalid_parameters(tmp_path):
    d = Document()
    ellipse = d.add("ellipse", rx=5, ry=3)
    line = d.line(-10, 4, 10, 4)
    d.constrain("fixed", [ellipse])
    c = d.constrain("curve_tangent", [ellipse, line], parameters=[0.25, 0.5])
    assert max(abs(v) for v in residual(d, d.constraints[c])) < 1e-7
    assert d.entities[line].vertices()[0][1] == pytest.approx(3)
    before = d.snapshot()
    with pytest.raises(ValueError):
        d.set_constraint_parameters(c, [2, 0.5])
    assert d.snapshot() == before
    path = tmp_path / "contact.gdraw"
    d.save(path)
    assert Document.load(path).snapshot() == d.snapshot()
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert clone.constraints[c]["parameters"] == [0.25, 0.5]


@pytest.mark.parametrize("kind", ["line", "arc"])
def test_support_extensions(kind):
    d = Document()
    if kind == "line":
        a = d.line(0, 0, 10, 0)
        cursor = (20, 0.02)
        expected = (20, 0)
    else:
        a = d.arc(0, 0, 10, 0, 90)
        cursor = (-10, 0.02)
        expected = (-10, 0)
    part = extension_part(d.entities[a], cursor, 0.1)
    assert part is not None and on_curve(part, expected, 1e-7)
    assert extension_part(d.entities[a], (100, 100), 0.1) is None


def test_feature_graph_cycle_and_stale_output_rejected(tmp_path):
    d = Document()
    a = d.circle(0, 0, 5)
    b = d.offset(a, 2)
    before = d.snapshot()
    with pytest.raises(ValueError, match="Cyclic"), d.transaction():
        d.features["bad"] = {
            "id": "bad",
            "kind": "offset",
            "sources": [b],
            "outputs": [a],
            "params": {"amount": 1, "tolerance": 0.01},
        }
    assert d.snapshot() == before
    state = d.snapshot()
    state["entities"][1]["data"]["radius"] = 100
    path = tmp_path / "stale.gdraw"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Stale"):
        Document.load(path)


def test_feature_commands_replace_and_detach():
    d = Document()
    s = ScriptEngine(d)
    s.execute("LINE a x=0 y=0 length=20\nOFFSET a distance=2")
    child = next(iter(d.features.values()))["outputs"][0]
    s.execute(f"DRIVE_FEATURE {child} amount=3\nDETACH {child}\nMOVE {child} dy=2")
    assert d.entities[child].vertices()[0][1] == pytest.approx(5)
    s.execute('POLYLINE p points="0,0;20,0;20,20"\nROUND p radius=2', replace=True)
    assert len(d.features) == 1
    assert "a" not in d.entities


def test_feature_source_scale_mirror_lock_and_copy():
    d = Document()
    source = d.line(0, 0, 20, 0)
    out = d.offset(source, 2)
    d.transform([source], scale=2)
    assert d.entities[out].vertices()[0][1] == pytest.approx(4)
    d.mirror([source], (0, 0), (1, 0))
    assert d.entities[out].vertices()[0][1] == pytest.approx(-4)
    copied = d.transform([out], dx=10, copy_entities=True)[0]
    assert d.feature_for(copied) is None
    d.transform([copied], dy=1)
    d.set_layer("results")
    d.entities[out].layer = "results"
    d.set_layer("results", locked=True)
    before = d.snapshot()
    with pytest.raises(ValueError, match="Unlock"):
        d.transform([source], dy=3)
    assert d.snapshot() == before


def test_selected_round_and_cleanup_commands_snapshot():
    d = Document()
    ScriptEngine(d).execute(
        'POLYLINE path points="0,0;20,0;20,20;0,20" closed=true\nROUND path radius=2 vertex=1\nCLEANOFFSET path distance=1 join=bevel'
    )
    clone = Document()
    ScriptEngine(clone).execute(document_script(d))
    assert clone.snapshot() == d.snapshot()


def test_fillet_source_pose_and_units_roundtrip(tmp_path):
    d = Document()
    a = d.line(0, 0, 20, 0)
    b = d.line(20, 0, 20, 20)
    arc = d.corner(a, b, 2, pick=(10, 10))
    d.transform([a, b], dx=30, dy=20, scale=2)
    assert d.entities[arc].data["radius"] == 4
    assert d.feature_for(arc)["params"]["pick"] == pytest.approx((50, 40))
    d.set_units("cm")
    path = tmp_path / "fillet.gdraw"
    d.save(path)
    assert Document.load(path).snapshot() == d.snapshot()


def test_atomic_detach_after_source_move_inside_script():
    d = Document()
    source = d.circle(0, 0, 5, id="source")
    out = d.offset(source, 2)
    ScriptEngine(d).execute(f"MOVE source dx=10\nDETACH {out}")
    assert d.entities[out].x == 10


@pytest.mark.parametrize("pair", ["circles", "ellipses", "beziers"])
def test_curve_pair_fillet_finite_join_and_tangency(pair):
    d = Document()
    if pair == "circles":
        a = d.circle(0, 0, 5)
        b = d.circle(12, 0, 5)
    elif pair == "ellipses":
        a = d.add("ellipse", rx=5, ry=4)
        b = d.add("ellipse", x=12, rx=5, ry=4)
    else:
        a = d.add("bezier", points=[(0, 0), (6, 0), (14, 0), (20, 0)])
        b = d.add("bezier", points=[(20, 0), (20, 6), (20, 14), (20, 20)])
    sources = copy.deepcopy(d.entities)
    arc = d.corner(a, b, 2, pick=(10, 3))
    f = parameter_curve(d.entities[arc])
    for id, t, output in zip((a, b), (0, 1), d.feature_for(arc)["outputs"][:2]):
        contact, velocity = f(t)
        assert on_curve(sources[id], contact, 1e-6)
        piece = d.entities[output]
        if pair == "beziers":
            g = parameter_curve(piece)
            u, tu = g(0)
            v, tv = g(1)
            tangent = tu if distance(u, contact) < distance(v, contact) else tv
            assert min(distance(u, contact), distance(v, contact)) < 1e-7
            assert (
                abs(
                    (velocity[0] * tangent[1] - velocity[1] * tangent[0])
                    / (math.hypot(*velocity) * math.hypot(*tangent))
                )
                < 1e-7
            )


def test_detached_cleanup_metadata_scales_and_clears_after_reshape():
    d = Document()
    source = d.polyline([(0, 0), (20, 0), (20, 20)], closed=False)
    out = d.clean_offset(source, 2, linked=False)[0]
    d.set_units("cm")
    assert d.entities[out].data["cleanup"]["tolerance"] == pytest.approx(0.001)
    e = copy.deepcopy(d.entities[out])
    e.data["points"][0] = (100, 100)
    d.replace(e)
    assert "cleanup" not in d.entities[out].data


def test_fifty_feature_chain_keeps_bounded_ids_and_regenerates():
    d = Document()
    source = d.circle(0, 0, 5)
    output = source
    for _ in range(50):
        output = d.offset(output, 0.1)
    assert max(len(id) for id in d.entities) <= 120
    d.transform([source], dx=5)
    assert d.entities[output].x == 5
    assert d.entities[output].data["radius"] == pytest.approx(10)


def test_sharp_join_rejects_constraint_projection_that_reopens_corner():
    d = Document()
    a = d.line(0, 0, 10, 0)
    b = d.line(20, 0, 20, 10)
    d.constrain("fixed", [a])
    before = d.snapshot()
    with pytest.raises(ValueError, match="conflict"):
        d.corner(a, b, 0, linked=False)
    assert d.snapshot() == before
