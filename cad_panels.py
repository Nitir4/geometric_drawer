        ttk.Checkbutton(
            tab,
            text="Reflect definition in its local X axis",
            variable=self.instance_mirror,
        ).pack(anchor="w", pady=4)
        ttk.Button(
            tab, text="Insert block", command=lambda: self.safe(self.block_insert)
        ).pack(fill="x")
        ttk.Button(
            tab,
            text="Select instance",
            command=lambda: self.safe(self.instance_select_geometry),
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab,
            text="Apply instance placement",
            command=lambda: self.safe(self.instance_apply),
        ).pack(fill="x")
        ttk.Button(
            tab,
            text="Explode instance",
            command=lambda: self.safe(self.instance_explode),
        ).pack(fill="x", pady=4)
        ttk.Label(
            tab,
            text="Drag a member to move the instance. The orange assembly handle rotates it. Move/Copy/Rotate/Scale/Mirror preserve the link.",
            wraplength=310,
        ).pack(fill="x", pady=6)
        ttk.Separator(tab).pack(fill="x", pady=8)
        ttk.Label(tab, text="SELECTION GROUPS", style="Title.TLabel").pack(anchor="w")
        self.group_name = tk.StringVar()
        self.group_box = ttk.Combobox(tab, textvariable=self.group_name)
        self.group_box.pack(fill="x", pady=4)
        ttk.Button(
            tab,
            text="Group selected geometry",
            command=lambda: self.safe(self.group_create),
        ).pack(fill="x")
        ttk.Button(
            tab, text="Select group", command=lambda: self.safe(self.group_select)
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab, text="Ungroup geometry", command=lambda: self.safe(self.group_remove)
        ).pack(fill="x")
        ttk.Label(
            tab,
            text="Groups share selection and transforms; constraints can still move individual members. One group per entity. Ungroup keeps geometry.",
            wraplength=310,
        ).pack(fill="x", pady=6)
        self.build_pattern_panel()

    def assembly_refresh(self):
        self.block_box.configure(values=list(self.doc.blocks))
        self.group_box.configure(values=list(self.doc.groups))
        blocks = [f["id"] for f in self.doc.features.values() if f["kind"] == "block"]
        self.instance_box.configure(values=blocks)
        if self.instance_id.get() not in blocks:
            self.instance_id.set("")
        self.pattern_region_box.configure(
            values=[e.id for e in self.doc.entities.values() if e.kind == "region"]
        )

    def block_define(self):
        n = ScriptEngine(self.doc).number
        self.doc.define_block(
            self.block_name.get().strip(),
            self.selection,
            base=(n(self.block_base_x.get()), n(self.block_base_y.get())),
        )
        self.changed("Reusable block definition saved")

    def block_edit(self):
        if self.block_edit_ids and any(
            i in self.doc.entities for i in self.block_edit_ids
        ):
            raise ValueError(
                "Save or delete the current definition edit geometry first."
            )
        self.block_edit_name = self.block_name.get()
        self.block_edit_existing = set(self.doc.entities)
        self.block_edit_ids = self.doc.block_edit_copies(self.block_edit_name)
        self.selection = list(self.block_edit_ids)
        self.block_base_x.set("0")
        self.block_base_y.set("0")
        self.changed(
            "Edit local copies with normal controls, then Save definition geometry"
        )
        self.fit()

    def block_save(self):
        ids = [i for i in self.block_edit_ids if i in self.doc.entities]
        if not ids or self.block_edit_name != self.block_name.get():
            raise ValueError("Open Edit block geometry for this definition first.")
        # Explicitly added selected geometry becomes a new template; deleted copies retire.
        ids = list(dict.fromkeys(ids + [i for i in self.selection if i not in ids]))
        with self.doc.transaction("Save block geometry"):
            self.doc.define_block(self.block_edit_name, ids)
            cleanup = [i for i in ids if i not in self.block_edit_existing]
            self.doc.delete(cleanup, expand=False)
        self.block_edit_ids = []
        self.block_edit_name = None
        self.selection = []
        self.changed("Definition saved; all linked instances regenerated")

    def block_remove(self):
        self.doc.remove_block(self.block_name.get())
        self.changed("Block definition removed")

    def instance_parameters(self):
        n = ScriptEngine(self.doc).number
        return {
            k: n(v.get()) if k != "layer" else v.get()
            for k, v in self.instance_vars.items()
        } | {"mirror": self.instance_mirror.get()}

    def block_insert(self):
        id = self.doc.insert_block(self.block_name.get(), **self.instance_parameters())
        self.instance_id.set(id)
        self.selection = list(self.doc.features[id]["outputs"])
        self.changed("Linked block inserted")

    def instance_select(self, event=None):
        id = self.instance_id.get()
        if id in self.doc.features and self.doc.features[id]["kind"] == "block":
            params = self.doc.features[id]["params"]
            self.block_name.set(params["name"])
            for k, var in self.instance_vars.items():
                var.set(str(params[k]))
            self.instance_mirror.set(params["mirror"])

    def instance_select_geometry(self):
        f = self.doc.feature_for(self.instance_id.get())
        if f is None or f["kind"] != "block":
            raise ValueError("Choose a block instance.")
        self.selection = list(f["outputs"])
        self.changed("Instance selected")

    def instance_apply(self):
        f = self.doc.feature_for(self.instance_id.get())
        if f is None or f["kind"] != "block":
            raise ValueError("Choose a block instance.")
        self.doc.update_feature(f["id"], **self.instance_parameters())
        self.selection = list(f["outputs"])
        self.changed("Instance placement applied")

    def instance_explode(self):
        f = self.doc.feature_for(self.instance_id.get())
        if f is None or f["kind"] != "block":
            raise ValueError("Choose a block instance.")
        self.selection = self.doc.detach_feature(f["id"])
        self.changed("Instance exploded into independent geometry")

    def group_create(self):
        self.selection = self.doc.group(self.group_name.get(), self.selection)
        self.changed("Geometry grouped")

    def group_select(self):
        name = self.group_name.get()
        if name not in self.doc.groups:
            raise ValueError("Choose a group.")
        self.selection = list(self.doc.groups[name])
        self.changed("Group selected")

    def group_remove(self):
        self.selection = self.doc.ungroup(self.group_name.get())
        self.changed("Geometry ungrouped")

    def selected_block(self):
        selected = set(self.selection)
        return next(
            (
                f
                for f in self.doc.features.values()
                if f["kind"] == "block" and selected == set(f["outputs"])
            ),
            None,
        )

    def block_rotation_handle(self, f):
        p = f["params"]
        # Length comes from bounds, so the handle remains outside scaled geometry.
        origin = (p["x"], p["y"])
        extent = max(
            (
                max(
                    abs(v - origin[i % 2])
                    for i, v in enumerate(self.doc.entities[id].bounds())
                )
                for id in f["outputs"]
            ),
            default=0,
        )
        return add(origin, rotate((0, extent + 25 / self.view.scale), p["angle"]))

    def draw_block_handle(self):
        f = self.selected_block()
        if f:
            a = self.view.screen((f["params"]["x"], f["params"]["y"]))
            b = self.view.screen(self.block_rotation_handle(f))
            self.canvas.create_line(*a, *b, fill="#df8d22", dash=(3, 4))
            self.canvas.create_oval(
                b[0] - 6,
                b[1] - 6,
                b[0] + 6,
                b[1] + 6,
                fill="white",
                outline="#df8d22",
                width=2,
            )

    def build_pattern_panel(self):
        self.pattern_tab, tab = self.scrollable_tab("Patterns")
        ttk.Label(tab, text="CUSTOM REGION PATTERNS", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            tab,
            text="Angles and offsets use region-local coordinates. Positive dash values draw, negative values leave gaps, and zero draws dots. Empty dashes mean continuous lines.",
            wraplength=310,
        ).pack(fill="x", pady=6)
        self.pattern_region = tk.StringVar()
        self.pattern_region_box = ttk.Combobox(
            tab, textvariable=self.pattern_region, state="readonly"
        )
        self.pattern_region_box.pack(fill="x")
        ttk.Button(
            tab,
            text="Load selected region pattern",
            command=lambda: self.safe(self.pattern_load),
        ).pack(fill="x", pady=4)
        self.pattern_name = tk.StringVar(value="CUSTOM")
        ttk.Label(tab, text="Pattern name").pack(anchor="w")
        ttk.Entry(tab, textvariable=self.pattern_name).pack(fill="x")
        self.pattern_families = [[45, (0, 0), (-2, 2), []]]
        self.pattern_vars = {
            k: tk.StringVar(value=v)
            for k, v in (
                ("angle", "45"),
                ("base x", "0"),
                ("base y", "0"),
                ("offset x", "-2"),
                ("offset y", "2"),
                ("dashes", ""),
            )
        }
        self.pattern_tree = ttk.Treeview(
            tab,
            columns=("angle", "offset", "dashes"),
            show="tree headings",
            height=4,
            selectmode="browse",
        )
        for k, title, width in (
            ("#0", "Family", 45),
            ("angle", "Angle", 45),
            ("offset", "Offset", 100),
            ("dashes", "Dashes", 110),
        ):
            self.pattern_tree.heading(k, text=title)
            self.pattern_tree.column(k, width=width)
        self.pattern_tree.pack(fill="x", pady=6)
        self.pattern_tree.bind("<<TreeviewSelect>>", self.pattern_family_select)
        for k, var in self.pattern_vars.items():
            ttk.Label(tab, text=k).pack(anchor="w")
            ttk.Entry(tab, textvariable=var).pack(fill="x")
        ttk.Button(
            tab,
            text="Add pattern family",
            command=lambda: self.safe(self.pattern_family_add),
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab,
            text="Update pattern family",
            command=lambda: self.safe(self.pattern_family_update),
        ).pack(fill="x")
        ttk.Button(
            tab,
            text="Remove pattern family",
            command=lambda: self.safe(self.pattern_family_remove),
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab, text="Preview pattern", command=lambda: self.safe(self.pattern_preview)
        ).pack(fill="x")
        self.pattern_canvas = tk.Canvas(
            tab,
            width=290,
            height=220,
            background="#f5f8fc",
            highlightthickness=1,
            highlightbackground="#bccbd8",
        )
        self.pattern_canvas.pack(fill="x", pady=6)
        self.pattern_canvas.bind(
            "<Configure>", lambda event: self.pattern_preview_safe()
        )
        self.pattern_info = tk.StringVar(
            value="Preview and Apply keep hole boundaries clear."
        )
        ttk.Label(tab, textvariable=self.pattern_info, wraplength=310).pack(fill="x")
        ttk.Button(
            tab,
            text="Apply custom pattern",
            command=lambda: self.safe(self.pattern_apply),
        ).pack(fill="x", pady=6)
        self.pattern_refresh()

    def pattern_refresh(self):
        self.pattern_tree.delete(*self.pattern_tree.get_children())
        for i, (a, base, offset, dashes) in enumerate(self.pattern_families):
            self.pattern_tree.insert(
                "",
                "end",
                iid=str(i),
                text=str(i + 1),
                values=(
                    f"{a:g}",
                    ",".join(f"{v:g}" for v in offset),
                    ",".join(f"{v:g}" for v in dashes),
                ),
            )

    def pattern_load(self):
        selected = next(
            (i for i in self.selection if self.doc.entities[i].kind == "region"), None
        )
        id = selected or self.pattern_region.get()
        if id not in self.doc.entities or self.doc.entities[id].kind != "region":
            raise ValueError("Choose a region to edit its pattern.")
        self.pattern_region.set(id)
        e = self.doc.entities[id]
        self.pattern_families = copy.deepcopy(definition(e)) or [
            [45, (0, 0), (-2, 2), []]
        ]
        self.pattern_name.set(e.data.get("hatch_name", "CUSTOM"))
        self.pattern_refresh()
        self.pattern_preview()

    def pattern_family_select(self, event=None):
        ids = self.pattern_tree.selection()
        if ids:
            a, base, offset, dashes = self.pattern_families[int(ids[0])]
            for k, v in zip(
                ("angle", "base x", "base y", "offset x", "offset y"),
                (a, *base, *offset),
            ):
                self.pattern_vars[k].set(str(v))
            self.pattern_vars["dashes"].set(",".join(str(v) for v in dashes))

    def pattern_read_family(self):
        n = ScriptEngine(self.doc).number
        values = {k: n(v.get()) for k, v in self.pattern_vars.items() if k != "dashes"}
        dashes = [
            n(v.strip())
            for v in self.pattern_vars["dashes"].get().split(",")
            if v.strip()
        ]
        return [
            values["angle"],
            (values["base x"], values["base y"]),
            (values["offset x"], values["offset y"]),
            dashes,
        ]

    def pattern_family_add(self):
        self.pattern_families.append(self.pattern_read_family())
        self.pattern_refresh()

    def pattern_family_update(self):
        ids = self.pattern_tree.selection()
        if not ids:
            raise ValueError("Select a pattern family to update.")
        self.pattern_families[int(ids[0])] = self.pattern_read_family()
        self.pattern_refresh()

    def pattern_family_remove(self):
        ids = self.pattern_tree.selection()
        if not ids:
            raise ValueError("Select a pattern family to remove.")
        self.pattern_families.pop(int(ids[0]))
        self.pattern_refresh()

    def pattern_preview_entity(self):
        id = self.pattern_region.get()
        e = (
            copy.deepcopy(self.doc.entities[id])
            if id in self.doc.entities and self.doc.entities[id].kind == "region"
            else Entity(
                "preview",
                "region",
                data={
                    "rings": [
                        [(0, 0), (40, 0), (40, 30), (0, 30)],
                        [(10, 10), (30, 10), (30, 20), (10, 20)],
                    ]
                },
            )
        )
        e.data.update(
            hatch="custom",
            hatch_name=self.pattern_name.get(),
            hatch_definition=copy.deepcopy(self.pattern_families),
        )
        return e.validate()

    def pattern_preview_safe(self):
        try:
            self.pattern_preview()
        except (ValueError, TypeError, ArithmeticError) as exc:
            self.pattern_info.set(str(exc))

    def pattern_preview(self):
        e = self.pattern_preview_entity()
        segments = hatch_segments(e)
        c = self.pattern_canvas
        c.delete("all")
        x0, y0, x1, y1 = e.bounds()
        w, h = max(c.winfo_width(), 290), 220
        factor = min((w - 24) / (x1 - x0), (h - 24) / (y1 - y0))

        def screen(p):
            return (12 + (p[0] - x0) * factor, h - 12 - (p[1] - y0) * factor)

        for ring in e.paths():
            c.create_line(
                *[v for p in ring for v in screen(p)], fill="#7890a4", width=1.5
            )
        for a, b in segments[:3500]:
            c.create_line(*screen(a), *screen(b), fill="#243e58")
        self.pattern_info.set(
            f"{len(self.pattern_families)} families · {len(segments)} clipped segments"
            + (" (first3500 shown)" if len(segments) > 3500 else "")
        )

    def pattern_apply(self):
        id = self.pattern_region.get()
        self.doc.set_region_pattern(
            id, self.pattern_families, name=self.pattern_name.get()
        )
        self.changed("Custom pattern applied")
        self.pattern_preview()
