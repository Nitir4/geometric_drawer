                "bindings": self.bindings,
                "blocks": self.blocks,
                "groups": self.groups,
            }
        )

    def _restore(self, state):
        self.blocks = copy.deepcopy(state.get("blocks", {}))
        self.groups = copy.deepcopy(state.get("groups", {}))
        self.parameters = copy.deepcopy(state.get("parameters", {}))
        self.bindings = copy.deepcopy(state.get("bindings", []))
        self.features = {f["id"]: copy.deepcopy(f) for f in state.get("features", [])}
        self._feature_cache = {}
        self.topology_events = []
        self.constraints = {
            c["id"]: copy.deepcopy(c) for c in state.get("constraints", [])
        }
        self.units = state["units"]
        self.active_layer = state["active_layer"]
        self.layers = {v["name"]: Layer(**copy.deepcopy(v)) for v in state["layers"]}
        self.entities = {v["id"]: Entity(**copy.deepcopy(v)) for v in state["entities"]}

    def validate(self):
        if (
            self.units not in UNIT_MM
            or "0" not in self.layers
            or self.active_layer not in self.layers
        ):
            raise ValueError("Invalid units, default layer or active layer.")
        if len(self.entities) > 20000:
            raise ValueError("Drawing exceeds 20000 entities.")
        if len(self.constraints) > 5000:
            raise ValueError("Drawing exceeds 5000 constraints.")
        for layer in self.layers.values():
            layer.validate()
        for e in self.entities.values():
            e.validate()
            if e.layer not in self.layers:
                raise ValueError(f"Missing layer: {e.layer}")
            ref = e.data.get("ref")
            if ref and (
                ref not in self.entities
                or self.entities[ref].kind not in ("line", "circle", "arc")
            ):
                raise ValueError("Dimension reference must name a line, circle or arc.")
        try:
            from .cad_constraints import residual, validate_constraint
        except ImportError:
            from cad_constraints import residual, validate_constraint
        for c in self.constraints.values():
            validate_constraint(self, c)
            if max(abs(v) for v in residual(self, c)) > 1e-7:
                raise ValueError("Drawing contains unsatisfied constraints.")
        self.validate_assemblies()
        self.apply_parameters(check=True)
        self.regenerate_features(check=True)
        self.refresh_dimensions()

    def refresh_dimensions(self):
        for e in self.entities.values():
            ref = self.entities.get(e.data.get("ref"))
            if ref is None:
                continue
            if e.kind == "dimension" and ref.kind == "line":
                a, b = ref.vertices()
                e.x, e.y, e.angle = *a, 0
                e.data["points"] = [(0, 0), sub(b, a)]
            elif e.kind == "radial_dimension" and ref.kind in ("circle", "arc"):
                e.x, e.y = ref.x, ref.y
                e.data["radius"] = ref.data["radius"]
            else:
                raise ValueError("Dimension type does not match its referenced entity.")

    @contextmanager
    def transaction(self, label="Edit"):
        before = self.snapshot()
        outer = self._depth == 0
        if outer:
            self.topology_events = []
        self._depth += 1
        try:
            yield self
            if outer:
                self.apply_parameters()
                if self.constraints or self.bindings:
                    self.solve_constraints()
                self.regenerate_features()
                self.validate()
        except Exception:
            self._restore(before)
            raise
        else:
            if outer and before != self.snapshot():
                self._undo.append((label, before))
                self._undo = self._undo[-100:]
                self._redo.clear()
        finally:
            self._depth -= 1

    def undo(self):
        if self._undo:
            label, state = self._undo.pop()
            self._redo.append((label, self.snapshot()))
            self._restore(state)
            return label

    def redo(self):
        if self._redo:
            label, state = self._redo.pop()
            self._undo.append((label, self.snapshot()))
            self._restore(state)
            return label

    def constrain(
        self, kind, refs, value=None, *, id=None, state=None, parameters=None
    ):
        """Create a driving constraint and solve the sketch as one undoable edit."""
        try:
            from .cad_constraints import coordinates
        except ImportError:
            from cad_constraints import coordinates
        with self.transaction("Add constraint"):
            id = id or self.unique_constraint_id()
            if id in self.constraints:
                raise ValueError(f"Duplicate constraint ID: {id}")
            if state is not None and kind != "fixed":
                raise ValueError("Only fixed constraints accept saved state.")
            c = {"id": id, "kind": kind, "refs": list(refs)}
            if kind == "free_tangent" and parameters is None:
                parameters = [0.5, 0.5]
            if parameters is not None:
                c["parameters"] = [finite(t) for t in parameters]
            if value is not None:
                c["value"] = finite(value)
            if kind == "fixed":
                c["state"] = (
                    copy.deepcopy(state)
                    if state is not None
                    else coordinates(self.entities[c["refs"][0]])
                )
            self.constraints[id] = c
        return id

    def unique_constraint_id(self):
        n = 1
        while f"c{n}" in self.constraints:
            n += 1
        return f"c{n}"

    def remove_constraint(self, id):
        with self.transaction("Remove constraint"):
            del self.constraints[id]
            self.prune_bindings()

    def set_constraint_value(self, id, value):
        with self.transaction("Edit driving value"):
            self.constraints[id]["value"] = finite(value)

    def set_constraint_parameters(self, id, parameters):
        with self.transaction("Edit contact parameters"):
            self.constraints[id]["parameters"] = [finite(t) for t in parameters]

    def solve_constraints(self):
        try:
            from .cad_constraints import solve
        except ImportError:
            from cad_constraints import solve
        shapes = {
            e.id: list(e.data["points"])
            for e in self.entities.values()
            if "offset_approximation" in e.data
        }
        report = solve(self)
        for id, points in shapes.items():
            if self.entities[id].data["points"] != points:
                self.entities[id].data.pop("offset_approximation", None)
        return report

    def constraint_report(self):
        try:
            from .cad_constraints import solve
        except ImportError:
            from cad_constraints import solve
        return solve(self, apply=False)

    def unique_id(self, prefix="e"):
        # Reserve room for numeric suffixes even through long feature/copy chains.
        prefix = prefix[:110]
        n = 1
        while f"{prefix}{n}" in self.entities:
            n += 1
        return f"{prefix}{n}"

    def editable(self, ids, *, allow_derived=False):
        entities = [self.entities[i] for i in ids]
        if not allow_derived and any(self.feature_for(e.id) for e in entities):
            raise ValueError("Edit the linked source, or detach the output first.")
        if any(self.layers[e.layer].locked for e in entities):
            raise ValueError("Unlock the layer before editing its geometry.")
        return entities

    def add(
        self, kind, id=None, x=0, y=0, angle=0, layer=None, construction=False, **data
    ):
        with self.transaction("Create " + kind):
            id = id or self.unique_id(kind)
            if id in self.entities:
                raise ValueError(f"Duplicate entity ID: {id}")
            layer = layer or self.active_layer
            if layer not in self.layers or self.layers[layer].locked:
                raise ValueError("Choose an existing unlocked layer.")
            if kind in ("dimension", "radial_dimension", "angular_dimension"):
                data.setdefault("text_height", 2.5 / UNIT_MM[self.units])
            e = Entity(
                id, kind, x, y, angle, layer, copy.deepcopy(data), construction
            ).validate()
            self.entities[id] = e
        return id

    def line(self, x1, y1, x2=None, y2=None, *, length=None, angle=0, **kwargs):
        if length is not None:
            return self.add(
                "line",
                x=x1,
                y=y1,
                angle=angle,
                points=[(0, 0), (positive(length), 0)],
                **kwargs,
            )
        if x2 is None or y2 is None:
            raise ValueError("Provide both endpoint coordinates or length/angle.")
        return self.add(
            "line", x=x1, y=y1, points=[(0, 0), (x2 - x1, y2 - y1)], **kwargs
        )

    def rectangle(self, x, y, width, height, angle=0, **kwargs):
        return self.add(
            "rectangle", x=x, y=y, angle=angle, width=width, height=height, **kwargs
        )

    def circle(self, x, y, radius, **kwargs):
        return self.add("circle", x=x, y=y, radius=radius, **kwargs)

    def arc(self, x, y, radius, start=0, sweep=90, **kwargs):
        return self.add(
            "arc", x=x, y=y, radius=radius, start=start, sweep=sweep, **kwargs
        )

    def polyline(self, points, closed=False, **kwargs):
        return self.add("polyline", points=points, closed=closed, **kwargs)

    def region(
        self, outer, holes=(), *, hatch="solid", spacing=2, hatch_angle=45, **kwargs
    ):
        return self.add(
            "region",
            rings=[outer, *holes],
            hatch=hatch,
            spacing=spacing,
            hatch_angle=hatch_angle,
            **kwargs,
        )

    def dimension(self, entity_id, offset=8, **kwargs):
        ref = self.entities[entity_id]
        if ref.kind == "line":
            a, b = ref.vertices()
            return self.add(
                "dimension",
                x=a[0],
                y=a[1],
                points=[(0, 0), sub(b, a)],
                offset=offset,
                ref=entity_id,
                **kwargs,
            )
        if ref.kind in ("circle", "arc"):
            return self.add(
                "radial_dimension",
                x=ref.x,
                y=ref.y,
                radius=ref.data["radius"],
                ref=entity_id,
                **kwargs,
            )
        raise ValueError("Associative dimensions support lines, circles and arcs.")

    def replace(self, e):
        with self.transaction("Edit properties"):
            original = self.editable([e.id])[0]
            if e.layer not in self.layers or self.layers[e.layer].locked:
                raise ValueError("Target layer must exist and be unlocked.")
            replacement = copy.deepcopy(e)
            if original.data.get("points") != replacement.data.get(
                "points"
            ) or original.data.get("closed") != replacement.data.get("closed"):
                replacement.data.pop("offset_approximation", None)
                replacement.data.pop("cleanup", None)
            self.entities[e.id] = replacement.validate()

    def delete(self, ids, *, expand=True):
        ids = [ids] if isinstance(ids, str) else list(ids)
        with self.transaction("Delete"):
            ids = self.expand_selection(ids) if expand else list(dict.fromkeys(ids))
            self.editable(ids, allow_derived=True)
            removed = set(ids)
            while True:
                affected = [
                    f
                    for f in self.features.values()
                    if removed.intersection(f["sources"] + f["outputs"])
                ]
                if not affected:
                    break
                for f in affected:
                    removed.update(f["outputs"])
                    del self.features[f["id"]]
            ids = list(removed)
            self.editable(ids, allow_derived=True)
            # Freeze dependent dimensions at their last measured geometry.
            for e in self.entities.values():
                if e.data.get("ref") in ids:
                    e.data.pop("ref")
            self.constraints = {
                k: c
                for k, c in self.constraints.items()
                if not any(r.rsplit("@", 1)[0] in ids for r in c["refs"])
            }
            for id in ids:
                del self.entities[id]
            self.prune_bindings()
            self.prune_groups()

    def clear(self):
        with self.transaction("Clear drawing"):
            self.entities.clear()
            self.constraints.clear()
            self.features.clear()
            self._feature_cache.clear()
            self.parameters.clear()
            self.bindings.clear()
            self.blocks.clear()
            self.groups.clear()

    def set_layer(self, name, **changes):
        with self.transaction("Edit layer"):
            layer = copy.deepcopy(self.layers.get(name, Layer(name)))
            for k, v in changes.items():
                if k not in ("color", "visible", "locked", "width"):
                    raise ValueError(f"Unknown layer property: {k}")
                setattr(layer, k, v)
            layer.validate()
            self.layers[name] = layer

    def set_units(self, units):
        if units not in UNIT_MM:
            raise ValueError("Units must be mm, cm, m or in.")
        with self.transaction("Convert drawing units"):
            factor = UNIT_MM[self.units] / UNIT_MM[units]
            for e in self.entities.values():
                self._scale_entity(e, factor, (0, 0))
            for definition in self.blocks.values():
                for state in definition:
                    e = Entity(**copy.deepcopy(state))
                    self._scale_entity(e, factor, (0, 0))
                    state.update(e.to_dict())
            for l in self.layers.values():
                l.width *= factor
            try:
                from .cad_constraints import coordinates
            except ImportError:
                from cad_constraints import coordinates
            for c in self.constraints.values():
                if c["kind"] in (
                    "length",
                    "radius",
                    "width",
                    "height",
                    "distance",
                    "rx",
                    "ry",
                ):
                    c["value"] *= factor
                elif c["kind"] == "fixed":
                    e = copy.deepcopy(self.entities[c["refs"][0]])
                    # Fixed targets are converted independently of current geometry.
                    try:
                        from .cad_constraints import assign
                    except ImportError:
                        from cad_constraints import assign
                    assign(e, c["state"])
                    self._scale_entity(e, factor, (0, 0))
                    c["state"] = coordinates(e)
            for f in self.features.values():
                if f["kind"] == "block":
                    f["params"]["x"] *= factor
                    f["params"]["y"] *= factor
                if "frame" in f:
                    f["frame"]["x"] *= factor
                    f["frame"]["y"] *= factor
                for key in ("amount", "radius", "tolerance"):
                    if key in f["params"]:
                        f["params"][key] *= factor
                if f["params"].get("pick") is not None:
                    f["params"]["pick"] = [v * factor for v in f["params"]["pick"]]
            self.units = units

    def transform(
        self, ids, *, dx=0, dy=0, rotation=0, scale=1, pivot=(0, 0), copy_entities=False
    ):
        dx, dy, rotation, scale = (
            finite(dx),
            finite(dy),
            finite(rotation),
            positive(scale),
        )
        pivot = tuple(finite(v) for v in pivot)
        if len(pivot) != 2:
            raise ValueError("Pivot needs exactly two coordinates.")
        with self.transaction("Copy" if copy_entities else "Transform"):
            ids = self.expand_selection(ids)
            source_groups = {
                name: list(members)
                for name, members in self.groups.items()
                if set(members).issubset(ids)
            }
            plain, result, mapping = self.transform_blocks(
                ids,
                dx=dx,
                dy=dy,
                rotation=rotation,
                scale=scale,
                pivot=pivot,
                copy_entities=copy_entities,
            )
            originals = self.editable(plain, allow_derived=copy_entities)
            selected = set(ids)
            for original in originals:
                e = copy.deepcopy(original)
                if e.data.get("ref") and e.data["ref"] not in selected:
                    e.data.pop("ref")
                if copy_entities:
                    e.id = self.unique_id(original.id + "_")
                    e.data.pop("block_edit_key", None)
                    mapping[original.id] = e.id
                self._scale_entity(e, scale, pivot)
                e.x, e.y = add(
                    add(pivot, rotate(sub((e.x, e.y), pivot), rotation)), (dx, dy)
                )
                e.angle += rotation
                self.entities[e.id] = e
                result.append(e.id)
            if not copy_entities:
                for f in self.features.values():
                    if f["kind"] != "block" and set(f["sources"]).issubset(selected):
                        if f["params"].get("pick") is not None:
                            p = add(pivot, mul(sub(f["params"]["pick"], pivot), scale))
                            f["params"]["pick"] = add(
                                add(pivot, rotate(sub(p, pivot), rotation)), (dx, dy)
                            )
                        for key in ("amount", "radius", "tolerance"):
                            if key in f["params"]:
                                f["params"][key] *= scale
            if copy_entities:
                for id in result:
                    e = self.entities[id]
                    if "ref" in e.data:
                        ref = mapping.get(e.data["ref"])
                        if ref:
                            e.data["ref"] = ref
                        else:
                            e.data.pop("ref")
                for name, members in source_groups.items():
                    newname = name[:100] + "_copy"
                    n = 1
                    while (
                        newname in self.groups
                        or newname in self.entities
                        or newname in self.features
                    ):
                        newname = name[:100] + f"_copy{n}"
                        n += 1
                    self.groups[newname] = [mapping[i] for i in members]
            return result

    @staticmethod
    def _scale_entity(e, factor, pivot):
        e.x, e.y = add(pivot, mul(sub((e.x, e.y), pivot), factor))
        for key in (
            "width",
            "height",
            "radius",
            "rx",
            "ry",
            "offset",
            "text_height",
        ):
            if key in e.data:
                e.data[key] *= factor
        if "points" in e.data:
            e.data["points"] = [mul(p, factor) for p in e.data["points"]]
        if "rings" in e.data:
            e.data["rings"] = [
                [mul(p, factor) for p in ring] for ring in e.data["rings"]
            ]
            e.data["spacing"] *= factor
            for line in e.data.get("hatch_definition", []):
                line[1], line[2], line[3] = (
                    mul(line[1], factor),
                    mul(line[2], factor),
                    [v * factor for v in line[3]],
                )
        if "boolean_tolerance" in e.data:
            e.data["boolean_tolerance"] *= factor
        if "cleanup" in e.data:
            e.data["cleanup"]["tolerance"] *= factor
        if "offset_approximation" in e.data:
            for key in ("distance", "tolerance"):
                e.data["offset_approximation"][key] *= factor

    def mirror(self, ids, a, b, copy_entities=False):
        axis = angle(sub(b, a))
        if distance(a, b) <= EPS:
            raise ValueError("Mirror axis needs two different points.")
        with self.transaction("Mirror"):
            result = self.transform(ids, copy_entities=copy_entities)
            mirrored = set()
            for id in result:
                owner = self.feature_for(id)
                if owner and owner["kind"] == "block":
                    if owner["id"] not in mirrored:
                        params = owner["params"]
                        local = rotate(sub((params["x"], params["y"]), a), -axis)
                        params["x"], params["y"] = add(
                            a, rotate((local[0], -local[1]), axis)
                        )
                        params["angle"] = 2 * axis - params["angle"]
                        params["mirror"] = not params["mirror"]
                        mirrored.add(owner["id"])
                    continue
                e = self.entities[id]
                p = rotate(sub((e.x, e.y), a), -axis)
                e.x, e.y = add(a, rotate((p[0], -p[1]), axis))
                e.angle = 2 * axis - e.angle
                if "points" in e.data:
                    e.data["points"] = [(x, -y) for x, y in e.data["points"]]
                if e.kind == "region":
                    e.data["rings"] = [
                        [(x, -y) for x, y in ring] for ring in e.data["rings"]
                    ]
                    e.data["hatch_angle"] *= -1
                    for line in e.data.get("hatch_definition", []):
                        line[0] *= -1
                        line[1], line[2] = (
                            (line[1][0], -line[1][1]),
                            (line[2][0], -line[2][1]),
                        )
                if e.kind == "rectangle":
                    # Keep an oriented rectangle rather than baking its corners.
                    e.x, e.y = e.world((0, -e.data["height"]))
                if "start" in e.data:
                    e.data["start"] *= -1
                    e.data["sweep"] *= -1
                e.data.pop("ref", None)
            if not copy_entities:
                for f in self.features.values():
                    if f["kind"] != "block" and set(f["sources"]).issubset(set(result)):
                        if f["params"].get("pick") is not None:
                            p = rotate(sub(f["params"]["pick"], a), -axis)
                            f["params"]["pick"] = add(a, rotate((p[0], -p[1]), axis))
                        source = self.entities[f["sources"][0]]
                        if (
                            f["kind"] == "offset"
                            and source.kind in ("line", "bezier", "polyline")
                            or f["kind"] == "clean_offset"
                            and (
                                source.kind == "line"
                                or source.kind == "bezier"
                                or source.kind == "polyline"
                                and not source.data.get("closed")
                            )
                        ):
                            f["params"]["amount"] *= -1
            return result

    def offset(self, id, amount, *, tolerance=0.01, linked=True):
        if linked:
            return self._create_feature(
                "offset",
                [id],
                {"amount": finite(amount), "tolerance": positive(tolerance)},
            )[0]
        amount = finite(amount)
        tolerance = positive(tolerance)
        with self.transaction("Offset"):
            e = copy.deepcopy(self.editable([id], allow_derived=True)[0])
            e.id = self.unique_id(e.id + "_offset")
            if e.kind in ("circle", "arc"):
                e.data["radius"] = positive(e.data["radius"] + amount)
            elif e.kind == "line":
                a, b = e.vertices()
                v = mul(rotate(unit(sub(b, a)), 90), amount)
                e.x, e.y = add((e.x, e.y), v)
            elif e.kind == "rectangle":
                e.x, e.y = e.world((-amount, -amount))
                e.data["width"] = positive(e.data["width"] + 2 * amount)
                e.data["height"] = positive(e.data["height"] + 2 * amount)
            elif e.kind == "polyline":
                try:
                    from .cad_operations import offset_polyline
                except ImportError:
                    from cad_operations import offset_polyline
                offset_polyline(e, amount)
                e.data.pop("offset_approximation", None)
            elif e.kind in ("ellipse", "bezier"):
                try:
                    from .cad_curves import offset_curve
                except ImportError:
                    from cad_curves import offset_curve
                offset_curve(e, amount, tolerance)
            else:
                raise ValueError(
                    "Offset supports lines, circles/arcs, rectangles, polylines, ellipses and Beziers."
                )
            self.entities[e.id] = e
            return e.id

    def trim_extend(self, id, boundary, pick, extend=False, *, tolerance=0.01, limit=4):
        with self.transaction("Extend" if extend else "Trim"):
            e = self.editable([id])[0]
            cut = self.entities[boundary]
            if id == boundary:
                raise ValueError("Choose two different entities for trim/extend.")
            try:
                from .cad_operations import trim_curve
                from .cad_trimming import extend_path, trim_path
            except ImportError:
                from cad_operations import trim_curve
                from cad_trimming import extend_path, trim_path
            # Existing primitive semantics retain backwards-compatible endpoint picks.
            if e.kind in ("line", "circle", "arc") and cut.kind in (
                "line",
                "circle",
                "arc",
            ):
                trim_curve(e, cut, pick, extend)
                output = [copy.deepcopy(e)]
            else:
                output = (
                    extend_path(e, cut, pick, limit)
                    if extend
                    else trim_path(e, cut, pick, positive(tolerance))
                )
            topology_changed = (
                len(output) != 1
                or output[0].kind != e.kind
                or len(output[0].vertices()) != len(e.vertices())
            )
            referenced = any(
                r.rsplit("@", 1)[0] == id
                for c in self.constraints.values()
                for r in c["refs"]
            )
            vertex_driven = any(
                b["target"] == "entity"
                and b["id"] == id
                and b["property"].startswith("v")
                for b in self.bindings
            )
            if topology_changed and (referenced or vertex_driven):
                raise ValueError(
                    "Remove affected constraints or vertex bindings before changing path topology."
                )
            if not output:
                self.delete([id])
                return []
            ids = []
            for index, result in enumerate(output):
                result.id = id if index == 0 else self.unique_id(id + "_trim")
                result.layer, result.construction = e.layer, e.construction
                self.entities[result.id] = result.validate()
                ids.append(result.id)
            self.refresh_dimensions()
            if self.constraints or self.bindings:
                expected = [copy.deepcopy(self.entities[i]) for i in ids]
                self.apply_parameters()
                self.solve_constraints()
                if any(
                    self.entities[i].kind != expected[j].kind
                    or len(self.entities[i].paths()[0]) != len(expected[j].paths()[0])
                    or any(
                        distance(a, b) > 1e-7
                        for a, b in zip(
                            self.entities[i].paths()[0], expected[j].paths()[0]
                        )
                    )
                    for j, i in enumerate(ids)
                ):
                    raise ValueError(
                        "Trim conflicts with driving geometry; edit drivers or remove affected rules."
                    )
            return ids

    def corner(self, first, second, amount, fillet=True, *, pick=None, linked=True):
        """Trim/extend straight legs; pick chooses retained sides of crossing lines."""
        try:
            from .cad_operations import corner_leg
        except ImportError:
            from cad_operations import corner_leg
        amount = finite(amount)
        if amount < 0:
            raise ValueError("Corner radius/distance cannot be negative.")
        if pick is not None:
            if len(pick) != 2:
                raise ValueError("Corner pick must contain X and Y.")
            pick = tuple(finite(v) for v in pick)
        if linked:
            outputs = self._create_feature(
                "fillet" if fillet else "chamfer",
                [first, second],
                {"amount": amount, "pick": pick},
            )
            return outputs[-1] if len(outputs) == 3 else None
        with self.transaction("Fillet" if fillet else "Chamfer"):
            a, b = self.editable([first, second])
            if first == second:
                raise ValueError("Select two different curves.")
            if a.kind != "line" or b.kind != "line":
                if not fillet or amount == 0:
                    raise ValueError("Curved corners require a positive fillet radius.")
                try:
                    from .cad_features import curve_fillet
                except ImportError:
                    from cad_features import curve_fillet
                aa, bb, connector = curve_fillet(a, b, amount, pick)
                self.entities[first], self.entities[second] = aa, bb
                connector.id = self.unique_id("arc")
                self.entities[connector.id] = connector
                if self.constraints:
                    raise ValueError(
                        "Use a linked fillet to preserve constrained curved sources."
                    )
                return connector.id
            av, bv = a.vertices(), b.vertices()
            try:
                p, _, _ = line_intersection(*av, *bv)
            except ValueError:
                if not fillet or amount <= 0:
                    raise
                try:
                    from .cad_features import parallel_round
                except ImportError:
                    from cad_features import parallel_round
                connector = parallel_round(a, b, amount, pick)
                connector.id = self.unique_id("arc")
                self.entities[connector.id] = connector
                if self.constraints:
                    raise ValueError(
                        "Use a linked round to preserve constrained sources."
                    )
                return connector.id
            ai, u, a_length = corner_leg(a, p, pick)
            bi, v, b_length = corner_leg(b, p, pick)
            theta = math.acos(max(-1, min(1, u[0] * v[0] + u[1] * v[1])))
            if theta < 1e-6 or math.pi - theta < 1e-6:
                raise ValueError("Corner is degenerate.")
            tangent = amount / math.tan(theta / 2) if fillet else amount
            if tangent >= min(a_length, b_length) - EPS:
                raise ValueError("Radius/distance exceeds the available line lengths.")
            t1, t2 = add(p, mul(u, tangent)), add(p, mul(v, tangent))
            a.data["points"][ai], b.data["points"][bi] = a.local(t1), b.local(t2)
            if amount == 0:
                connector = None
            elif fillet:
                center = add(p, mul(unit(add(u, v)), amount / math.sin(theta / 2)))
                start = angle(sub(t1, center))
                sweep = (angle(sub(t2, center)) - start + 180) % 360 - 180
                connector = self.arc(*center, amount, start, sweep, layer=a.layer)
            else:
                connector = self.line(*t1, *t2, layer=a.layer)
            if self.constraints:
                # A solver projection must not silently disconnect the new corner.
                self.solve_constraints()
                for id, index, tangent_point, ray in (
                    (first, ai, t1, u),
                    (second, bi, t2, v),
                ):
                    ends = self.entities[id].vertices()
                    direction = unit(sub(ends[1 - index], ends[index]))
                    if (
                        distance(ends[index], tangent_point) > 1e-7
                        or distance(direction, ray) > 1e-7
                    ):
                        raise ValueError(
                            "Driving constraints conflict with this corner; remove or adjust them first."
                        )
            return connector

    def array(self, ids, count, dx=0, dy=0, rotation=0, pivot=(0, 0)):
        if isinstance(count, bool) or int(count) != count or not 1 <= count <= 500:
            raise ValueError(
                "Array count must be an integer from 1 to 500 (including original)."
            )
        with self.transaction("Array"):
            result = []
            for i in range(1, int(count)):
                result += self.transform(
                    ids,
                    dx=i * dx,
                    dy=i * dy,
                    rotation=i * rotation,
                    pivot=pivot,
                    copy_entities=True,
                )
            return result

    def bounds(self, visible_only=True):
        bounds = [
            e.bounds()
            for e in self.entities.values()
            if not visible_only or self.layers[e.layer].visible
        ]
        if not bounds:
            return -10, -10, 110, 90
        return (
            min(b[0] for b in bounds),
            min(b[1] for b in bounds),
            max(b[2] for b in bounds),
            max(b[3] for b in bounds),
        )

    def save(self, path):
        self.validate()
        path = Path(path)
        text = json.dumps(self.snapshot(), indent=2, allow_nan=False)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path):
        if Path(path).stat().st_size > 20_000_000:
            raise ValueError("Drawing file exceeds 20 MB.")
        state = json.loads(Path(path).read_text())
        if state.get("format") != "geometric-drawer" or state.get("version") not in (
            1,
            2,
        ):
            raise ValueError("Unsupported drawing format/version.")
        if len({e["id"] for e in state["entities"]}) != len(state["entities"]) or len(
            {l["name"] for l in state["layers"]}
        ) != len(state["layers"]):
            raise ValueError("Duplicate entity IDs or layer names in document.")
        if state.get("probes"):
            raise ValueError(
                "Electrical probe drawings are unsupported; open a geometric drawing."
            )
        for entity in state["entities"]:
            data = entity.get("data", {})
            if data.get("circuit_wire"):
                raise ValueError(
                    "Circuit wiring is unsupported; open a geometric drawing."
                )
            # Older geometric drawings saved an unused false wire flag on lines.
            data.pop("circuit_wire", None)
        constraints = state.get("constraints", [])
        if len({c["id"] for c in constraints}) != len(constraints):
            raise ValueError("Duplicate constraint IDs in document.")
        features = state.get("features", [])
        if len({f["id"] for f in features}) != len(features):
            raise ValueError("Duplicate linked feature IDs.")
        doc = cls()
        doc._restore(state)
        doc.validate()
        return doc
