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
