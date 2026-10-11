"""Deterministic component matching and reference propagation on regeneration."""

import json
import math

from scipy.optimize import linear_sum_assignment
from shapely.geometry import LineString, Polygon

try:
    from .cad_geometry import Entity
except ImportError:
    from cad_geometry import Entity


def shape(e, frame):
    paths = [[frame.local(p) for p in path] for path in e.paths()]
    if e.kind == "region":
        return Polygon(paths[0], paths[1:])
    if e.kind == "polyline" and e.data.get("closed"):
        return Polygon(paths[0])
    return LineString(paths[0]) if paths else None


def assign_outputs(doc, feature, geometries):
    old_ids = list(feature["outputs"])
    kind = feature["kind"]
    old = [doc.entities[i] for i in old_ids]
    matches = {}
    aliases = {}
    if kind == "block":
        keys = {e.data["block_key"]: i for i, e in enumerate(old)}
        matches = {
            j: keys[e.data["block_key"]]
            for j, e in enumerate(geometries)
            if e.data["block_key"] in keys
            and old[keys[e.data["block_key"]]].kind == e.kind
        }
    elif kind == "tangents":
        keys = {e.data["tangent_branch"]: i for i, e in enumerate(old)}
        matches = {
            j: keys[e.data["tangent_branch"]]
            for j, e in enumerate(geometries)
            if e.data["tangent_branch"] in keys
        }
    elif kind not in ("clean_offset", "boolean"):
        matches = {i: i for i in range(min(len(old), len(geometries)))}
    elif old and geometries:
        current = doc.entities[feature["sources"][0]]
        previous = (
            Entity("frame", "point", **feature["frame"])
            if "frame" in feature
            else current
        )
        cached = doc._feature_cache.get(feature["id"])
        if cached and "frame" not in feature:
            previous = Entity(**json.loads(cached)[1][0])
        a = [shape(e, previous) for e in old]
        b = [shape(e, current) for e in geometries]
        costs = []
        overlap = []
        for first in a:
            row = []
            crossings = []
            for second in b:
                common = first.intersection(second)
                area = (
                    common.area
                    if first.geom_type == "Polygon" and second.geom_type == "Polygon"
                    else common.length
                )
                polygon_pair = first.geom_type == second.geom_type == "Polygon"
                union = max(
                    (first.area + second.area - common.area)
                    if polygon_pair
                    else (first.length + second.length - common.length),
                    1e-15,
                )
                scale = max(
                    math.sqrt(max(first.area, second.area)),
                    first.length,
                    second.length,
                    1e-9,
                )
                proximity = first.hausdorff_distance(second) / scale
                same_role = old[len(costs)].data.get("cleanup", {}).get(
                    "role"
                ) == geometries[len(row)].data.get("cleanup", {}).get("role")
                eligible = same_role and (area > 1e-15 or proximity <= 0.25)
                row.append(
                    -area / union + min(proximity, 10) * 0.001 if eligible else 100
                )
                crossings.append(area if same_role else 0)
            costs.append(row)
            overlap.append(crossings)
        rows, cols = linear_sum_assignment(costs)
        matches = {int(j): int(i) for i, j in zip(rows, cols) if costs[i][j] < 100}
        survivors = set(matches.values())
        for i in range(len(old)):
            if i not in survivors:
                j = max(range(len(b)), key=lambda j: overlap[i][j])
                if overlap[i][j] > 1e-15:
                    aliases[old_ids[i]] = j
    result = []
    feature.setdefault("serial", 0)
    for j, e in enumerate(geometries):
        if j in matches:
            prior = old[matches[j]]
            e.id = prior.id
            if kind != "block":
                e.layer = prior.layer
                e.construction = prior.construction
            elif doc.layers[e.layer].locked and e.to_dict() != prior.to_dict():
                raise ValueError("Unlock the insertion layer before changing a block.")
            if doc.layers[prior.layer].locked and e.to_dict() != prior.to_dict():
                raise ValueError(
                    "Unlock the linked output layer before changing its source."
                )
        else:
            feature["serial"] += 1
            e.id = doc.unique_id(feature["id"] + "_out" + str(feature["serial"]) + "_")
            if kind != "block":
                e.layer = doc.entities[feature["sources"][0]].layer
                e.construction = False
            if doc.layers[e.layer].locked:
                raise ValueError("Unlock the output layer before creating a component.")
        doc.entities[e.id] = e.validate()
        result.append(e.id)
    rename = {id: result[j] for id, j in aliases.items()}
    retired = set(old_ids) - set(result)
    if retired:
        doc.editable(list(retired), allow_derived=True)
    for f in doc.features.values():
        f["sources"] = [rename.get(id, id) for id in f["sources"]]
    # A vanished component has no meaningful descendant input; remove its branch.
    lost = retired - set(rename)
    while True:
        affected = [
            f
            for f in doc.features.values()
            if f["id"] != feature["id"] and lost.intersection(f["sources"])
        ]
        if not affected:
            break
        for f in affected:
            doc.editable(f["outputs"], allow_derived=True)
            lost.update(f["outputs"])
            del doc.features[f["id"]]
    deleted = retired | lost
    for e in doc.entities.values():
        ref = e.data.get("ref")
        if ref in rename:
            e.data["ref"] = rename[ref]
        elif ref in deleted:
            e.data.pop("ref", None)
    doc.constraints = {
        id: c
        for id, c in doc.constraints.items()
        if not any(r.rsplit("@", 1)[0] in deleted for r in c["refs"])
    }
    for id in deleted:
        doc.entities.pop(id, None)
    doc.prune_bindings()
    doc.prune_groups(rename)
    feature["outputs"] = result
    if kind == "block":
        feature["frame"] = {k: feature["params"][k] for k in ("x", "y", "angle")}
    else:
        source = doc.entities[feature["sources"][0]]
        feature["frame"] = {"x": source.x, "y": source.y, "angle": source.angle}
    if set(old_ids) != set(result):
        doc.topology_events.append(
            {
                "feature": feature["id"],
                "created": [i for i in result if i not in old_ids],
                "retired": sorted(retired),
                "merged": rename,
            }
        )
    return result
