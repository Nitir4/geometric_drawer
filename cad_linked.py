"""Associative drafting operations evaluated in dependency order."""

import copy
import json

try:
    from .cad_features import cleaned_offset, common_tangents, round_polyline
    from .cad_geometry import Entity, finite, positive
except ImportError:
    from cad_features import cleaned_offset, common_tangents, round_polyline
    from cad_geometry import Entity, finite, positive


class LinkedFeatures:
    def feature_for(self, entity_or_feature):
        if entity_or_feature in self.features:
            return self.features[entity_or_feature]
        return next(
            (f for f in self.features.values() if entity_or_feature in f["outputs"]),
            None,
        )

    def feature_order(self):
        if len(self.features) > 500:
            raise ValueError("Drawing exceeds 500 linked features.")
        owners, remaining, result = {}, dict(self.features), []
        for key, f in remaining.items():
            if (
                set(f)
                - {"id", "kind", "sources", "outputs", "params", "serial", "frame"}
                or not {"id", "kind", "sources", "outputs", "params"} <= set(f)
                or f["id"] != key
                or not isinstance(key, str)
                or not key
            ):
                raise ValueError("Invalid linked feature schema.")
            serial = f.get("serial", 0)
            if type(serial) is not int or not 0 <= serial <= 10**12:
                raise ValueError("Invalid feature serial.")
            if "frame" in f:
                frame = f["frame"]
                if not isinstance(frame, dict) or set(frame) != {"x", "y", "angle"}:
                    raise ValueError("Invalid source frame.")
                for value in frame.values():
                    finite(value)
            if f["kind"] not in (
                "offset",
                "fillet",
                "chamfer",
                "round",
                "tangents",
                "clean_offset",
                "boolean",
                "block",
            ) or not isinstance(f["params"], dict):
                raise ValueError("Invalid linked feature kind/parameters.")
            for role in ("sources", "outputs"):
                ids = f[role]
                if (
                    not isinstance(ids, list)
                    or role == "sources"
                    and not ids
                    and f["kind"] != "block"
                    or len(ids) != len(set(ids))
                    or any(i not in self.entities for i in ids)
                ):
                    raise ValueError(
                        "Linked feature references missing/duplicate geometry."
                    )
            if set(f["sources"]) & set(f["outputs"]):
                raise ValueError("Linked feature cannot own its source.")
            for i in f["outputs"]:
                if i in owners:
                    raise ValueError("Linked output has multiple owners.")
                owners[i] = key
        while remaining:
            ready = [
                k
                for k, f in remaining.items()
                if all(owners.get(i) not in remaining for i in f["sources"])
            ]
            if not ready:
                raise ValueError("Cyclic linked features.")
            for k in ready:
                result.append(remaining.pop(k))
        for c in self.constraints.values():
            if any(r.rsplit("@", 1)[0] in owners for r in c["refs"]):
                raise ValueError(
                    "Constrain the linked source, or detach the output first."
                )
        return result

    def _feature_geometry(self, kind, sources, params):
        if kind == "block":
            if sources:
                raise ValueError(
                    "Block instances reference definitions, not source entities."
                )
            return self.block_geometry(params)
        temp = type(self)()
        temp.units = self.units
        temp.layers = copy.deepcopy(self.layers)
        for layer in temp.layers.values():
            layer.locked = False
        temp.entities = {i: copy.deepcopy(self.entities[i]) for i in sources}
        p = copy.deepcopy(params)
        if (
            kind in ("offset", "clean_offset", "round")
            and len(sources) != 1
            or kind in ("fillet", "chamfer", "tangents")
            and len(sources) != 2
        ):
            raise ValueError("Wrong source count for linked feature.")
        if kind == "boolean":
            try:
                from .cad_boolean import boolean_geometry
            except ImportError:
                from cad_boolean import boolean_geometry
            return boolean_geometry([self.entities[i] for i in sources], **p)
        if kind == "offset":
            id = temp.offset(sources[0], linked=False, **p)
            return [temp.entities[id]]
        if kind in ("fillet", "chamfer"):
            id = temp.corner(*sources, fillet=kind == "fillet", linked=False, **p)
            return [temp.entities[i] for i in sources] + (
                [temp.entities[id]] if id else []
            )
        source = temp.entities[sources[0]]
        if kind == "round":
            return [round_polyline(source, **p)]
        if kind == "clean_offset":
            return cleaned_offset(source, allow_empty=True, **p)
        tangents = common_tangents(
            source, temp.entities[sources[1]], allow_empty=True, **p
        )
        return [
            Entity(
                "tangent",
                "line",
                layer=source.layer,
                data={"points": [a, b], "tangent_branch": key},
            )
            for key, a, b in tangents
        ]

    def regenerate_features(self, *, check=False):
        for f in self.feature_order():
            if f["id"] not in self.features:
                continue
            fingerprint = json.dumps(
                [
                    f,
                    [self.entities[i].to_dict() for i in f["sources"]],
                    [self.entities[i].to_dict() for i in f["outputs"]],
                    self.blocks.get(f["params"].get("name"))
                    if f["kind"] == "block"
                    else None,
                ],
                sort_keys=True,
            )
            if self._feature_cache.get(f["id"]) == fingerprint:
                continue
            geometries = self._feature_geometry(f["kind"], f["sources"], f["params"])
            if check:
                if len(geometries) != len(f["outputs"]):
                    raise ValueError(
                        "Stale linked topology; regenerate through a transaction."
                    )
                for id, e in zip(f["outputs"], geometries):
                    old = self.entities[id]
                    e.id = id
                    if f["kind"] != "block":
                        e.layer, e.construction = old.layer, old.construction
                    if e.to_dict() != old.to_dict():
                        raise ValueError(
                            "Stale linked output; regenerate through a transaction."
                        )
            else:
                try:
                    from .cad_topology import assign_outputs
                except ImportError:
                    from cad_topology import assign_outputs
                assign_outputs(self, f, geometries)
            self._feature_cache[f["id"]] = json.dumps(
                [
                    f,
                    [self.entities[i].to_dict() for i in f["sources"]],
                    [self.entities[i].to_dict() for i in f["outputs"]],
                    self.blocks.get(f["params"].get("name"))
                    if f["kind"] == "block"
                    else None,
                ],
                sort_keys=True,
            )

    def _create_feature(self, kind, sources, params):
        with self.transaction("Linked " + kind):
            self.regenerate_features()
            self.editable(sources, allow_derived=kind not in ("fillet", "chamfer"))
            geometries = self._feature_geometry(kind, sources, params)
            outputs = []
            for e in geometries:
                e.id = self.unique_id(sources[0] + "_" + kind)
                e.construction = False
                self.entities[e.id] = e.validate()
                outputs.append(e.id)
            n = 1
            while f"f{n}" in self.features:
                n += 1
            id = f"f{n}"
            self.features[id] = {
                "id": id,
                "kind": kind,
                "sources": list(sources),
                "outputs": outputs,
                "params": copy.deepcopy(params),
            }
            if kind in ("fillet", "chamfer", "boolean"):
                for i in sources:
                    self.entities[i].construction = True
        return outputs

    def update_feature(self, entity_or_feature, **params):
        with self.transaction("Update linked feature"):
            f = self.feature_for(entity_or_feature)
            if f is None:
                raise ValueError("Select a linked output or feature ID.")
            self.editable(f["outputs"], allow_derived=True)
            if set(params) - set(f["params"]):
                raise ValueError("Unknown feature parameter.")
            f["params"].update(copy.deepcopy(params))

    def detach_feature(self, entity_or_feature):
        with self.transaction("Detach feature"):
            if self.constraints:
                self.solve_constraints()
            self.regenerate_features()
            f = self.feature_for(entity_or_feature)
            if f is None:
                raise ValueError("Select a linked output or feature ID.")
            self.editable(f["outputs"], allow_derived=True)
            del self.features[f["id"]]
            if f["kind"] == "block":
                for id in f["outputs"]:
                    self.entities[id].data.pop("block_key", None)
            self.prune_bindings()
            self._feature_cache.pop(f["id"], None)
            return list(f["outputs"])

    def round_path(self, id, radius, *, tolerance=0.01, vertex=None, linked=True):
        params = {
            "radius": positive(radius),
            "tolerance": positive(tolerance),
            "vertex": vertex,
        }
        if linked:
            return self._create_feature("round", [id], params)[0]
        with self.transaction("Round path"):
            e = round_polyline(self.editable([id])[0], **params)
            self.entities[id] = e
        return id

    def common_tangents(self, first, second, *, kind="both", linked=True):
        if first == second:
            raise ValueError("Select two different circles/arcs.")
        if linked:
            return self._create_feature("tangents", [first, second], {"kind": kind})
        with self.transaction("Common tangents"):
            self.editable([first, second], allow_derived=True)
            outputs = []
            for e in self._feature_geometry(
                "tangents", [first, second], {"kind": kind}
            ):
                e.id = self.unique_id("tangent")
                self.entities[e.id] = e.validate()
                outputs.append(e.id)
            return outputs

    def clean_offset(
        self, id, amount, *, tolerance=0.01, join="round", linked=True, as_regions=False
    ):
        params = {
            "amount": finite(amount),
            "tolerance": positive(tolerance),
            "join": join,
            "as_regions": as_regions,
        }
        if linked:
            return self._create_feature("clean_offset", [id], params)
        with self.transaction("Clean offset"):
            self.editable([id], allow_derived=True)
            result = []
            for e in self._feature_geometry("clean_offset", [id], params):
                e.id = self.unique_id(id + "_clean")
                self.entities[e.id] = e.validate()
                result.append(e.id)
            return result

    def boolean(self, ids, operation="union", *, tolerance=0.01, linked=True):
        ids = list(ids)
        if len(set(ids)) != len(ids):
            raise ValueError("Boolean inputs must be distinct.")
        params = {"operation": operation, "tolerance": positive(tolerance)}
        if linked:
            return self._create_feature("boolean", ids, params)
        with self.transaction("Boolean " + operation):
            self.editable(ids, allow_derived=True)
            result = []
            for e in self._feature_geometry("boolean", ids, params):
                e.id = self.unique_id(ids[0] + "_" + operation)
                self.entities[e.id] = e.validate()
                result.append(e.id)
            return result
