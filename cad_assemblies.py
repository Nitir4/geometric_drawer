"""Flat selection groups and linked, reusable geometry definitions."""

import copy
import re

try:
    from .cad_geometry import Entity, add, finite, mul, positive, rotate, sub
except ImportError:
    from cad_geometry import Entity, add, finite, mul, positive, rotate, sub


def assembly_name(name):
    if not isinstance(name, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.-]{0,119}", name
    ):
        raise ValueError(
            "Use an assembly name starting with a letter/underscore, up to120 characters."
        )
    return name


class Assemblies:
    def validate_assemblies(self):
        if not isinstance(self.blocks, dict) or len(self.blocks) > 256:
            raise ValueError("At most256 block definitions are supported.")
        if not isinstance(self.groups, dict) or len(self.groups) > 1000:
            raise ValueError("At most1000 groups are supported.")
        count = 0
        for name, definition in self.blocks.items():
            assembly_name(name)
            if not isinstance(definition, list) or not 1 <= len(definition) <= 1000:
                raise ValueError("Block definitions need1–1000 geometry templates.")
            keys = set()
            for state in definition:
                e = Entity(**copy.deepcopy(state)).validate()
                if (
                    e.id in keys
                    or e.layer != "0"
                    or "ref" in e.data
                    or "block_key" in e.data
                ):
                    raise ValueError(
                        "Invalid/duplicate block template or live reference."
                    )
                keys.add(e.id)
                state.update(e.to_dict())
            count += len(definition)
        if count > 20000:
            raise ValueError("Block library exceeds20000 templates.")
        members = set()
        for name, ids in self.groups.items():
            assembly_name(name)
            if name in self.entities or name in self.features:
                raise ValueError("Group names must differ from entity and feature IDs.")
            if (
                not isinstance(ids, list)
                or not ids
                or len(ids) != len(set(ids))
                or any(i not in self.entities for i in ids)
            ):
                raise ValueError("Groups need distinct existing entity IDs.")
            if members.intersection(ids):
                raise ValueError("An entity can belong to only one selection group.")
            members.update(ids)

    def expand_selection(self, ids, *, groups=True, blocks=True):
        result = []
        for id in ids:
            if groups and id in self.groups:
                result.extend(self.groups[id])
            elif (
                blocks and id in self.features and self.features[id]["kind"] == "block"
            ):
                result.extend(self.features[id]["outputs"])
            elif id in self.entities:
                result.append(id)
            else:
                raise ValueError(f"Unknown selection ID: {id}")
        result = list(dict.fromkeys(result))
        while True:
            before = len(result)
            selected = set(result)
            sets = (list(self.groups.values()) if groups else []) + (
                [f["outputs"] for f in self.features.values() if f["kind"] == "block"]
                if blocks
                else []
            )
            for members in sets:
                if selected.intersection(members):
                    result.extend(i for i in members if i not in result)
            if len(result) == before:
                return result

    def group(self, name, ids):
        with self.transaction("Create group"):
            assembly_name(name)
            members = self.expand_selection(ids)
            if not members:
                raise ValueError("Select geometry to group.")
            self.groups[name] = members
        return list(members)

    def ungroup(self, name):
        with self.transaction("Ungroup"):
            if name not in self.groups:
                raise ValueError("Unknown group.")
            return self.groups.pop(name)

    def prune_groups(self, rename=None):
        rename = rename or {}
        self.groups = {
            name: list(
                dict.fromkeys(
                    rename.get(i, i) for i in ids if rename.get(i, i) in self.entities
                )
            )
            for name, ids in self.groups.items()
        }
        self.groups = {name: ids for name, ids in self.groups.items() if ids}

    def define_block(self, name, ids, *, base=(0, 0)):
        """Freeze a geometry snapshot in a local frame; existing definitions update."""
        with self.transaction("Define block"):
            assembly_name(name)
            base = tuple(finite(v) for v in base)
            if len(base) != 2:
                raise ValueError("Block base needs X,Y.")
            ids = list(dict.fromkeys(ids))
            if not ids or any(i not in self.entities for i in ids):
                raise ValueError("Select existing geometry for a block definition.")
            templates = []
            old = self.blocks.get(name, [])
            # Editable copies retain the template IDs for intentional reorder/update.
            for id in ids:
                e = copy.deepcopy(self.entities[id])
                key = e.data.pop("block_edit_key", e.id)
                e.id, e.layer = key, "0"
                e.data.pop("ref", None)
                e.data.pop("block_key", None)
                e.x, e.y = sub((e.x, e.y), base)
                templates.append(e.validate().to_dict())
            self.blocks[name] = templates
            if old != templates:
                self._feature_cache.clear()
        return name

    def remove_block(self, name):
        with self.transaction("Remove block definition"):
            if any(
                f["kind"] == "block" and f["params"]["name"] == name
                for f in self.features.values()
            ):
                raise ValueError(
                    "Delete or explode every instance before removing its definition."
                )
            if name not in self.blocks:
                raise ValueError("Unknown block definition.")
            del self.blocks[name]

    def block_geometry(self, params):
        if not isinstance(params, dict) or set(params) != {
            "name",
            "x",
            "y",
            "angle",
            "scale",
            "layer",
            "mirror",
        }:
            raise ValueError("Invalid block placement parameters.")
        if params["name"] not in self.blocks:
            raise ValueError("Missing block definition.")
        if params["layer"] not in self.layers:
            raise ValueError("Missing block insertion layer.")
        x, y, angle = (finite(params[k]) for k in ("x", "y", "angle"))
        scale = positive(params["scale"])
        if type(params["mirror"]) is not bool:
            raise ValueError("Block reflection must be boolean.")
        result = []
        for state in self.blocks[params["name"]]:
            e = Entity(**copy.deepcopy(state))
            if params["mirror"]:
                self.reflect_block_template(e)
            self._scale_entity(e, scale, (0, 0))
            e.x, e.y = add(rotate((e.x, e.y), angle), (x, y))
            e.angle += angle
            e.layer = params["layer"]
            e.data["block_key"] = state["id"]
            result.append(e.validate())
        return result

    @staticmethod
    def reflect_block_template(e):
        e.y *= -1
        e.angle *= -1
        if "points" in e.data:
            e.data["points"] = [(x, -y) for x, y in e.data["points"]]
        if e.kind == "region":
            e.data["rings"] = [[(x, -y) for x, y in ring] for ring in e.data["rings"]]
            e.data["hatch_angle"] *= -1
            for line in e.data.get("hatch_definition", []):
                line[0] *= -1
                line[1] = (line[1][0], -line[1][1])
                line[2] = (line[2][0], -line[2][1])
        if e.kind == "rectangle":
            e.x, e.y = e.world((0, -e.data["height"]))
        if "start" in e.data:
            e.data["start"] *= -1
            e.data["sweep"] *= -1

    def insert_block(
        self, name, x=0, y=0, angle=0, scale=1, *, layer=None, id=None, mirror=False
    ):
        with self.transaction("Insert block"):
            params = {
                "name": name,
                "x": finite(x),
                "y": finite(y),
                "angle": finite(angle),
                "scale": positive(scale),
                "layer": layer or self.active_layer,
                "mirror": mirror,
            }
            if (
                params["layer"] not in self.layers
                or self.layers[params["layer"]].locked
            ):
                raise ValueError("Choose an existing unlocked insertion layer.")
            geometries = self.block_geometry(params)
            if id is None:
                n = 1
                while (
                    f"b{n}" in self.features
                    or f"b{n}" in self.entities
                    or f"b{n}" in self.groups
                ):
                    n += 1
                id = f"b{n}"
            assembly_name(id)
            if id in self.features or id in self.entities or id in self.groups:
                raise ValueError("Duplicate block instance ID.")
            self.features[id] = {
                "id": id,
                "kind": "block",
                "sources": [],
                "outputs": [],
                "params": params,
            }
            try:
                from .cad_topology import assign_outputs
            except ImportError:
                from cad_topology import assign_outputs
            assign_outputs(self, self.features[id], geometries)
        return id

    def block_edit_copies(self, name, *, layer=None):
        """Create editable local geometry; define_block saves it back explicitly."""
        with self.transaction("Edit block geometry"):
            if name not in self.blocks:
                raise ValueError("Unknown block definition.")
            ids = []
            for state in self.blocks[name]:
                e = Entity(**copy.deepcopy(state))
                key = e.id
                id = self.add(
                    e.kind,
                    x=e.x,
                    y=e.y,
                    angle=e.angle,
                    layer=layer or self.active_layer,
                    construction=e.construction,
                    **e.data,
                )
                self.entities[id].data["block_edit_key"] = key
                ids.append(id)
        return ids

    def transform_blocks(self, ids, *, dx, dy, rotation, scale, pivot, copy_entities):
        """Transform placements once; ordinary geometry stays with Document.transform."""
        owners = [
            f
            for f in list(self.features.values())
            if f["kind"] == "block" and set(ids).intersection(f["outputs"])
        ]
        ordinary = [i for i in ids if not any(i in f["outputs"] for f in owners)]
        results = []
        mapping = {}
        for f in owners:
            self.editable(f["outputs"], allow_derived=True)
            p = copy.deepcopy(f["params"])
            origin = add(pivot, mul(sub((p["x"], p["y"]), pivot), scale))
            p["x"], p["y"] = add(
                add(pivot, rotate(sub(origin, pivot), rotation)), (dx, dy)
            )
            p["angle"] += rotation
            p["scale"] *= scale
            if copy_entities:
                name = p.pop("name")
                new = self.insert_block(name, **p)
                outputs = self.features[new]["outputs"]
                mapping.update(zip(f["outputs"], outputs))
                results.extend(outputs)
            else:
                f["params"] = p
                results.extend(f["outputs"])
        return ordinary, results, mapping

    def set_region_pattern(self, id, families, *, name="CUSTOM"):
        with self.transaction("Edit region pattern"):
            e = copy.deepcopy(self.editable([id])[0])
            if e.kind != "region":
                raise ValueError("Choose an editable region for a pattern.")
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError("Pattern name must contain1–80 characters.")
            e.data.update(
                hatch="custom",
                hatch_name=name,
                hatch_definition=copy.deepcopy(families),
            )
            self.entities[id] = e.validate()
