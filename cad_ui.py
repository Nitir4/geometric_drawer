            if name in self.doc.layers:
                raise ValueError("Layer already exists.")
            self.doc.set_layer(name)
            self.doc.active_layer = name
            self.layer_var.set(name)
            self.changed("Layer created")

    def color_layer(self):
        l = self.doc.layers[self.layer_var.get()]
        color = colorchooser.askcolor(l.color, parent=self.root)[1]
        if color:
            self.doc.set_layer(l.name, color=color)
            self.changed()

    def toggle_layer(self, prop):
        l = self.doc.layers[self.layer_var.get()]
        self.doc.set_layer(l.name, **{prop: not getattr(l, prop)})
        self.changed()

    def change_units(self):
        self.doc.set_units(self.unit_var.get())
        self.changed("Drawing units converted")
        self.fit()

    def run_script(self):
        ScriptEngine(self.doc).execute(
            self.editor.get("1.0", "end-1c"), replace=self.replace_script.get()
        )
        self.cancel()
        self.changed("Script applied as one undoable edit")
        if self.replace_script.get():
            self.fit()

    def drawing_to_code(self):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", document_script(self.doc))
        self.replace_script.set(True)
        self.status.set("Current drawing captured as editable code")

    def open_script(self):
        path = filedialog.askopenfilename(
            filetypes=[("CAD script", "*.cad"), ("Text", "*.txt"), ("All files", "*")]
        )
        if path:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", Path(path).read_text())

    def save_script(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".cad", filetypes=[("CAD script", "*.cad")]
        )
        if path:
            Path(path).write_text(self.editor.get("1.0", "end-1c"))

    def confirm_discard(self):
        if self.doc.snapshot() == self.saved_state:
            return True
        result = messagebox.askyesnocancel(
            "Unsaved drawing", "Save the drawing before continuing?", parent=self.root
        )
        if result is None:
            return False
        return bool(self.save_file()) if result else True

    def new_file(self):
        if self.confirm_discard():
            self.set_document(Document(), None, saved=True)

    def set_document(self, doc, filename=None, saved=False):
        self.cancel()
        self.doc = doc
        self.block_edit_ids = []
        self.block_edit_name = None
        self.block_edit_existing = set()
        self.filename = filename
        self.selection = []
        self.saved_state = doc.snapshot() if saved else Document().snapshot()
        self.layer_var.set(doc.active_layer)
        self.changed("Drawing loaded")
        self.fit()

    def open_file(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            filetypes=[("Geometric Drawer", "*.gdraw"), ("JSON", "*.json")]
        )
        if path:
            self.safe(lambda: self.set_document(Document.load(path), path, saved=True))

    def save_file(self, save_as=False):
        path = self.filename
        if save_as or not path:
            path = filedialog.asksaveasfilename(
                defaultextension=".gdraw", filetypes=[("Geometric Drawer", "*.gdraw")]
            )
        if not path:
            return False
        try:
            self.doc.save(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return False
        self.filename = path
        self.saved_state = self.doc.snapshot()
        self.changed("Drawing saved")
        return True

    def open_dxf(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            filetypes=[
                ("CAD drawing", "*.dxf *.dwg"),
                ("DXF", "*.dxf"),
                ("DWG", "*.dwg"),
            ]
        )
        if path:

            def perform():
                doc = (
                    import_dwg(path)
                    if Path(path).suffix.lower() == ".dwg"
                    else import_dxf(path)
                )
                self.set_document(doc)
                if getattr(doc, "import_warnings", []):
                    messagebox.showinfo(
                        "Import details",
                        "\n".join(doc.import_warnings),
                        parent=self.root,
                    )

            self.safe(perform)

    def open_legacy(self):
        path = filedialog.askopenfilename(
            filetypes=[("Track script", "*.txt"), ("All files", "*")]
        )
        if path:

            def perform_import():
                import_legacy(self.doc, Path(path).read_text())
                self.changed("Legacy track imported")
                self.fit()

            self.safe(perform_import)

    def export(self, kind):
        path = filedialog.asksaveasfilename(
            defaultextension="." + kind, filetypes=[(kind.upper(), "*." + kind)]
        )
        if path:

            def perform_export():
                {
                    "dxf": export_dxf,
                    "dwg": export_dwg,
                    "svg": export_svg,
                    "pdf": export_pdf,
                }[kind](self.doc, path)
                self.status.set("Exported: " + path)

            self.safe(perform_export)

    def close(self):
        if self.confirm_discard():
            self.root.destroy()

    def fit(self):
        self.view.fit(
            self.doc.bounds(), self.canvas.winfo_width(), self.canvas.winfo_height()
        )
        self.redraw()

    def wheel(self, event):
        up = getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0
        self.view.zoom(1.2 if up else 1 / 1.2, event.x, event.y)
        self.redraw()

    def pan_start(self, e):
        self.pan = (e.x, e.y, self.view.ox, self.view.oy)

    def pan_motion(self, e):
        if self.pan:
            x, y, ox, oy = self.pan
            self.view.ox, self.view.oy = ox + e.x - x, oy + e.y - y
            self.redraw()

    def snap_settings_changed(self):
        self.snap_info.set("Snap: —")
        self.redraw()

    def snap(self, p, reference=None):
        tolerance = 9 / self.view.scale
        nearest, best = p, tolerance
        kind = None
        if self.object_snap.get():
            perpendicular, tangent, nearest_enabled = (
                self.perpendicular_snap.get(),
                self.tangent_snap.get(),
                self.nearest_snap.get(),
            )
            curves = []
            for e in self.doc.entities.values():
                if not self.doc.layers[e.layer].visible or e.id in self.preview:
                    continue
                if not self.extension_snap.get() and e.kind in (
                    "point",
                    "line",
                    "polyline",
                    "rectangle",
                    "circle",
                    "arc",
                    "ellipse",
                    "bezier",
                ):
                    x0, y0, x1, y1 = e.bounds()
                    # Arc centres are valid object snaps outside the finite arc box.
                    if e.kind == "arc":
                        x0, y0, x1, y1 = (
                            min(x0, e.x),
                            min(y0, e.y),
                            max(x1, e.x),
                            max(y1, e.y),
                        )
                    if not (
                        x0 - tolerance <= p[0] <= x1 + tolerance
                        and y0 - tolerance <= p[1] <= y1 + tolerance
                    ):
                        continue
                for q in e.snap_points():
                    d = distance(p, q)
                    if d < best:
                        nearest, best = q, d
                        kind = "Object"
                for original_part in curve_parts(e):
                    extension = (
                        extension_part(original_part, p, tolerance)
                        if self.extension_snap.get()
                        else None
                    )
                    part = extension or original_part
                    x0, y0, x1, y1 = part.bounds()
                    if not (
                        x0 - tolerance <= p[0] <= x1 + tolerance
                        and y0 - tolerance <= p[1] <= y1 + tolerance
                    ):
                        continue
                    if on_curve(part, p, tolerance):
                        curves.append((part, extension is not None))
                        if nearest_enabled or extension is not None:
                            q = nearest_point(part, p)
                            d = distance(p, q)
                            if d < best:
                                nearest, best, kind = (
                                    q,
                                    d,
                                    "Extension" if extension is not None else "Nearest",
                                )
                        if reference is not None and (perpendicular or tangent):
                            for q, mode in reference_points(
                                part,
                                reference,
                                perpendicular=perpendicular,
                                tangent=tangent,
                            ):
                                d = distance(p, q)
                                if d < best:
                                    nearest, best, kind = q, d, mode
            for i, (a, extended_a) in enumerate(curves):
                for b, extended_b in curves[i + 1 :]:
                    for q in finite_intersections(a, b):
                        d = distance(p, q)
                        if d < best or kind == "Extension" and d < tolerance:
                            nearest, best = q, d
                            kind = (
                                "Extension intersection"
                                if extended_a or extended_b
                                else "Intersection"
                            )
        if best == tolerance and self.grid_snap.get():
            try:
                spacing = positive(self.spacing.get())
                nearest = tuple(round(v / spacing) * spacing for v in p)
            except ValueError:
                pass
        if reference is not None and self.ortho.get() and kind is None:
            dx, dy = sub(nearest, reference)
            nearest = (
                (nearest[0], reference[1])
                if abs(dx) >= abs(dy)
                else (reference[0], nearest[1])
            )
        self.snap_info.set("Snap: " + (kind or "—"))
        return nearest

    def hit(self, p):
        tol = 7 / self.view.scale
        candidates = []
        for e in self.doc.entities.values():
            if not self.doc.layers[e.layer].visible or self.doc.layers[e.layer].locked:
                continue
            x0, y0, x1, y1 = e.bounds()
            if x0 - tol <= p[0] <= x1 + tol and y0 - tol <= p[1] <= y1 + tol:
                d = e.hit_distance(p)
                if d <= tol:
                    candidates.append((d, e.id))
        return min(candidates)[1] if candidates else None

    def press(self, event):
        self.canvas.focus_set()
        self.safe(lambda: self._press(event))

    def _press(self, event):
        self.canvas.focus_set()
        raw = self.view.world(event.x, event.y)
        p = self.snap(raw, self.pending[-1] if self.pending else None)
        if self.tool.get() != "Select":
            if not self.doc.layers[self.doc.active_layer].visible:
                raise ValueError("Choose a visible active layer to draw.")
            self.pending.append(p)
            self.hover = p
            needed = {
                "Point": 1,
                "Text": 1,
                "Line": 2,
                "Rectangle": 2,
                "Circle": 2,
                "Ellipse": 2,
                "Arc": 3,
                "Dimension": 3,
                "Radial dimension": 2,
                "Angular dimension": 3,
                "Bezier": 4,
            }.get(self.tool.get())
            if needed and len(self.pending) == needed:
                try:
                    self.create_from_points()
                except Exception:
                    self.pending.pop()
                    raise
            self.redraw()
            return
        block = self.selected_block()
        if (
            block
            and distance(raw, self.block_rotation_handle(block)) < 8 / self.view.scale
        ):
            self.drag = {
                "mode": "block_rotate",
                "start": p,
                "pivot": (block["params"]["x"], block["params"]["y"]),
                "originals": {
                    i: copy.deepcopy(self.doc.entities[i]) for i in block["outputs"]
                },
            }
            return
        if len(self.selection) == 1 and not block:
            e = self.doc.entities[self.selection[0]]
            if distance(raw, self.rotation_handle(e)) < 8 / self.view.scale:
                self.drag = {
                    "mode": "rotate",
                    "start": p,
                    "originals": {e.id: copy.deepcopy(e)},
                }
                return
            for i, q in enumerate(e.handles()):
                if distance(raw, q) < 8 / self.view.scale:
                    self.drag = {
                        "mode": "handle",
                        "start": p,
                        "handle": i,
                        "originals": {e.id: copy.deepcopy(e)},
                    }
                    return
        id = self.hit(raw)
        if id:
            picked = self.doc.expand_selection([id])
            if event.state & 1:
                if id in self.selection:
                    self.selection = [i for i in self.selection if i not in picked]
                else:
                    self.selection.extend(picked)
            elif id not in self.selection:
                self.selection = picked
            self.selection = self.doc.expand_selection(self.selection)
            self.drag = {
                "mode": "move",
                "start": p,
                "originals": {
                    i: copy.deepcopy(self.doc.entities[i]) for i in self.selection
                },
            }
            self.changed()
        else:
            if not event.state & 1:
                self.selection = []
            self.drag = {"mode": "window", "start": raw, "end": raw, "originals": {}}
            self.changed()

    def motion(self, event):
        raw = self.view.world(event.x, event.y)
        p = self.snap(raw, self.pending[-1] if self.pending else None)
        self.hover = p
        self.coords.set(f"X {p[0]:.3f}  Y {p[1]:.3f} {self.doc.units}")
        if self.drag:
            if self.drag["mode"] == "window":
                self.drag["end"] = raw
            else:
                delta = sub(p, self.drag["start"])
                preview = copy.deepcopy(self.drag["originals"])
                try:
                    for e in preview.values():
                        if self.drag["mode"] == "move":
                            e.x, e.y = add((e.x, e.y), delta)
                            if e.data.get("ref") not in self.drag["originals"]:
                                e.data.pop("ref", None)
                        elif self.drag["mode"] == "block_rotate":
                            pivot = self.drag["pivot"]
                            turn = angle(sub(p, pivot)) - angle(
                                sub(self.drag["start"], pivot)
                            )
                            e.x, e.y = add(pivot, rotate(sub((e.x, e.y), pivot), turn))
                            e.angle += turn
                        elif self.drag["mode"] == "rotate":
                            pivot = (e.x, e.y)
                            e.angle += angle(sub(p, pivot)) - angle(
                                sub(self.drag["start"], pivot)
                            )
                            e.data.pop("ref", None)
                        else:
                            self.edit_handle(e, self.drag["handle"], p)
                        e.validate()
                    self.preview = preview
                except ValueError as exc:
                    self.preview = {}
                    self.status.set(str(exc))
        self.redraw()

    @staticmethod
    def edit_handle(e, index, p):
        if e.kind == "region":
            for ring in e.data["rings"]:
                if index < len(ring):
                    ring[index] = e.local(p)
                    break
                index -= len(ring)
        elif e.kind in ("line", "polyline", "bezier", "dimension"):
            e.data["points"][index] = e.local(p)
            e.data.pop("ref", None)
        elif e.kind == "rectangle":
            if index == 0:
                e.x, e.y = p
            else:
                q = e.local(p)
                if index in (1, 2):
                    e.data["width"] = positive(q[0])
                if index in (2, 3):
                    e.data["height"] = positive(q[1])
        elif index == 0:
            e.x, e.y = p
            e.data.pop("ref", None)
        elif e.kind in ("circle", "radial_dimension"):
            e.data["radius"] = positive(distance((e.x, e.y), p))
            e.data.pop("ref", None)
        elif e.kind == "ellipse":
            q = e.local(p)
            if index <= 2:
                e.data["rx" if index == 1 else "ry"] = positive(abs(q[index - 1]))
            else:
                a = math.degrees(math.atan2(q[1] / e.data["ry"], q[0] / e.data["rx"]))
                sign = 1 if e.data["sweep"] > 0 else -1
                if index == 3:
                    end = e.data.get("start", 0) + e.data["sweep"]
                    e.data["start"] = a
                    e.data["sweep"] = sign * ((sign * (end - a)) % 360 or 360)
                else:
                    e.data["sweep"] = sign * (
                        (sign * (a - e.data.get("start", 0))) % 360 or 360
                    )
        elif e.kind in ("arc", "angular_dimension"):
            q = e.local(p)
            a = angle(q)
            if index == 1:
                old_end = e.data["start"] + e.data["sweep"]
                e.data["radius"] = positive(math.hypot(*q))
                e.data["start"] = a
                e.data["sweep"] = (
                    ((old_end - a) % 360 or 360)
                    if e.data["sweep"] > 0
                    else -((a - old_end) % 360 or 360)
                )
            else:
                positive_sweep = e.data["sweep"] > 0
                e.data["sweep"] = (
                    ((a - e.data["start"]) % 360 or 360)
                    if positive_sweep
                    else -((e.data["start"] - a) % 360 or 360)
                )

    def release(self, event):
        if not self.drag:
            return
        drag, preview = self.drag, self.preview
        self.drag, self.preview = None, {}
        if drag["mode"] == "window":
            a, b = drag["start"], drag["end"]
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for e in self.doc.entities.values():
                l = self.doc.layers[e.layer]
                bx0, by0, bx1, by1 = e.bounds()
                if (
                    l.visible
                    and not l.locked
                    and x0 <= bx0 <= bx1 <= x1
                    and y0 <= by0 <= by1 <= y1
                    and e.id not in self.selection
                ):
                    self.selection.append(e.id)
        elif preview:

            def commit():
                with self.doc.transaction("Drag " + drag["mode"]):
                    if drag["mode"] == "move":
                        first = next(iter(preview))
                        delta = sub(
                            (preview[first].x, preview[first].y),
                            (drag["originals"][first].x, drag["originals"][first].y),
                        )
                        self.doc.transform(
                            list(drag["originals"]), dx=delta[0], dy=delta[1]
                        )
                    elif drag["mode"] == "block_rotate":
                        first = next(iter(preview))
                        turn = preview[first].angle - drag["originals"][first].angle
                        self.doc.transform(
                            list(drag["originals"]), rotation=turn, pivot=drag["pivot"]
                        )
                    else:
                        for e in preview.values():
                            self.doc.replace(e)

            self.safe(commit)
        self.changed("Selection/edit complete")

    def finish_polyline(self):
        if self.tool.get() == "Polyline" and len(self.pending) >= 2:
            self.create_from_points()

    def create_from_points(self):
        p, tool = self.pending, self.tool.get()
        id = None
        if tool == "Line":
            id = self.doc.line(*p[0], *p[1])
        elif tool == "Rectangle":
            id = self.doc.rectangle(
                min(p[0][0], p[1][0]),
                min(p[0][1], p[1][1]),
                abs(p[1][0] - p[0][0]),
                abs(p[1][1] - p[0][1]),
            )
        elif tool in ("Circle", "Radial dimension"):
            id = self.doc.add(
                "circle" if tool == "Circle" else "radial_dimension",
                x=p[0][0],
                y=p[0][1],
                radius=distance(*p),
            )
        elif tool == "Ellipse":
            id = self.doc.add(
                "ellipse",
                x=(p[0][0] + p[1][0]) / 2,
                y=(p[0][1] + p[1][1]) / 2,
                rx=abs(p[1][0] - p[0][0]) / 2,
                ry=abs(p[1][1] - p[0][1]) / 2,
            )
        elif tool in ("Arc", "Angular dimension"):
            start = angle(sub(p[1], p[0]))
            sweep = (angle(sub(p[2], p[0])) - start) % 360 or 360
            id = self.doc.add(
                "arc" if tool == "Arc" else "angular_dimension",
                x=p[0][0],
                y=p[0][1],
                radius=distance(p[0], p[1]),
                start=start,
                sweep=sweep,
            )
        elif tool == "Dimension":
            v = sub(p[1], p[0])
            length = positive(distance(p[0], p[1]))
            delta = sub(p[2], p[0])
            offset = (v[0] * delta[1] - v[1] * delta[0]) / length
            id = self.doc.add(
                "dimension", x=p[0][0], y=p[0][1], points=[(0, 0), v], offset=offset
            )
        elif tool == "Polyline":
            id = self.doc.polyline(p[:])
        elif tool == "Bezier":
            id = self.doc.add("bezier", points=p[:])
        elif tool == "Point":
            id = self.doc.add("point", x=p[0][0], y=p[0][1])
        elif tool == "Text":
            text = simpledialog.askstring("Text", "Text to place:", parent=self.root)
            if text:
                id = self.doc.add(
                    "text",
                    x=p[0][0],
                    y=p[0][1],
                    text=text,
                    height=3 / UNIT_MM[self.doc.units],
                )
        self.pending = []
        if id:
            self.selection = [id]
        self.changed("Created " + tool)

    def cancel(self, select=False):
        self.pending, self.preview, self.drag = [], {}, None
        if select:
            self.tool.set("Select")
        self.redraw()

    def rotation_handle(self, e):
        if e.kind == "rectangle":
            return e.world(
                (e.data["width"] / 2, e.data["height"] + 25 / self.view.scale)
            )
        if e.kind in ("circle", "ellipse"):
            return e.world(
                (0, e.data.get("radius", e.data.get("ry")) + 25 / self.view.scale)
            )
        box = e.bounds()
        points = [
            e.local(p)
            for p in [
                (box[0], box[1]),
                (box[0], box[3]),
                (box[2], box[1]),
                (box[2], box[3]),
            ]
        ]
        x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
        y = max(p[1] for p in points)
        return e.world(((x0 + x1) / 2, y + 25 / self.view.scale))

    def draw_entity(self, e, selected=False, ghost=False):
        l = self.doc.layers[e.layer]
        color = "#df8d22" if ghost else "#1479cf" if selected else l.color
        width = max(1.1, min(10, l.width * self.view.scale)) + (1 if selected else 0)
        dash = (6, 4) if e.construction or ghost else ()
        if e.kind == "region":
            try:
                from .cad_regions import hatch_segments, triangles
            except ImportError:
                from cad_regions import hatch_segments, triangles
            if e.data["hatch"] == "solid":
                for triangle in triangles(e):
                    self.canvas.create_polygon(
                        *[v for q in triangle for v in self.view.screen(q)],
                        fill=l.color,
                        outline="",
                        stipple="gray25",
                    )
            else:
                try:
                    segments = hatch_segments(e)
                except ValueError as exc:
                    segments = []
                    self.status.set(f"Hatch preview unavailable: {exc}")
                for a, b in segments:
                    self.canvas.create_line(
                        *self.view.screen(a),
                        *self.view.screen(b),
                        fill=color,
                        width=width,
                    )
        for p in e.paths(max(64, min(512, int(self.view.scale * 30)))):
            flat = [v for q in p for v in self.view.screen(q)]
            if len(flat) >= 4:
                if e.data.get("fill") and (
                    e.kind == "rectangle" or e.data.get("closed")
                ):
                    self.canvas.create_polygon(
                        *flat,
                        fill=l.color,
                        stipple="gray25",
                        outline=color
                        if e.data.get("outline", True) or selected
                        else "",
                        width=width,
                    )
                else:
                    self.canvas.create_line(
                        *flat,
                        fill=color,
                        width=width,
                        dash=dash,
                        arrow="both"
                        if e.kind == "dimension" and p == e.paths()[-1]
                        else "last"
                        if e.kind == "radial_dimension"
                        else "none",
                    )
        if e.kind == "point":
            x, y = self.view.screen((e.x, e.y))
            self.canvas.create_line(x - 4, y, x + 4, y, fill=color, width=width)
            self.canvas.create_line(x, y - 4, x, y + 4, fill=color, width=width)
        label = e.label()
        if label:
            p, text, height = label
            self.canvas.create_text(
                *self.view.screen(p),
                text=text,
                anchor="sw",
                fill=color,
                angle=e.angle,
                font=(
                    "TkDefaultFont",
                    -max(7, min(300, round(height * self.view.scale))),
                ),
            )
        if selected:
            for p in e.handles():
                x, y = self.view.screen(p)
                self.canvas.create_rectangle(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    fill="white",
                    outline="#1479cf",
                    width=1.5,
                )
            if len(self.selection) == 1 and not self.selected_block():
                a, b = (
                    self.view.screen((e.x, e.y)),
                    self.view.screen(self.rotation_handle(e)),
                )
                self.canvas.create_line(*a, *b, fill="#df8d22", dash=(3, 4))
                self.canvas.create_oval(
                    b[0] - 5,
                    b[1] - 5,
                    b[0] + 5,
                    b[1] + 5,
                    fill="#fff2d5",
                    outline="#df8d22",
                    width=2,
                )

    def redraw(self):
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if self.grid.get():
            try:
                step = positive(self.spacing.get())
            except ValueError:
                step = 5
            while step * self.view.scale < 14:
                step *= 10
            a, b = self.view.world(0, h), self.view.world(w, 0)
            for axis in (0, 1):
                low, high = a[axis], b[axis]
                for i in range(
                    math.floor(low / step),
                    min(math.ceil(high / step) + 1, math.floor(low / step) + 500),
                ):
                    v = self.view.screen((i * step, 0) if axis == 0 else (0, i * step))[
                        axis
                    ]
                    c.create_line(
                        v, 0, v, h, fill="#e4ebf2"
                    ) if axis == 0 else c.create_line(0, v, w, v, fill="#e4ebf2")
        ox, oy = self.view.screen((0, 0))
        c.create_line(0, oy, w, oy, fill="#bccbd8")
        c.create_line(ox, 0, ox, h, fill="#bccbd8")
        c.create_text(ox + 7, oy + 7, text="0", anchor="nw", fill="#7890a4")
        lower, upper = self.view.world(-30, h + 30), self.view.world(w + 30, -30)
        for e in self.doc.entities.values():
            if self.doc.layers[e.layer].visible:
                displayed = self.preview.get(e.id, e)
                if e.id not in self.selection and displayed.kind in (
                    "point",
                    "line",
                    "polyline",
                    "rectangle",
                    "circle",
                    "arc",
                    "ellipse",
                    "bezier",
                ):
                    x0, y0, x1, y1 = displayed.bounds()
                    margin = self.doc.layers[e.layer].width
                    if (
                        x1 + margin < lower[0]
                        or y1 + margin < lower[1]
                        or x0 - margin > upper[0]
                        or y0 - margin > upper[1]
                    ):
                        continue
                self.draw_entity(displayed, e.id in self.selection)
        self.draw_block_handle()
        if self.pending:
            p = self.pending + ([self.hover] if self.hover else [])
            if len(p) >= 2:
                draft = self.draft_entity(p)
                if draft:
                    self.draw_entity(draft, ghost=True)
                else:
                    c.create_line(
                        *[v for q in p for v in self.view.screen(q)],
                        fill="#e58b21",
                        width=1.5,
                        dash=(4, 3),
                    )
        if self.drag and self.drag["mode"] == "window":
            c.create_rectangle(
                *self.view.screen(self.drag["start"]),
                *self.view.screen(self.drag["end"]),
                outline="#1479cf",
                dash=(4, 3),
            )
        if self.hover:
            x, y = self.view.screen(self.hover)
            c.create_line(x - 6, y, x + 6, y, fill="#da8a17")
            c.create_line(x, y - 6, x, y + 6, fill="#da8a17")
        # A scale bar is tied to drawing coordinates, never to export fitting.
        length = 10 ** math.floor(math.log10(max(1e-9, 100 / self.view.scale)))
        x, y = 20, h - 24
        c.create_line(x, y, x + length * self.view.scale, y, fill="#536d82", width=2)
        c.create_text(
            x, y - 5, text=f"{length:g} {self.doc.units}", anchor="sw", fill="#536d82"
        )

    def draft_entity(self, p):
        """Transient geometry preview; never enters document history."""
        tool = self.tool.get()
        kind, data, x, y = None, {}, 0, 0
        if tool == "Rectangle":
            kind, x, y = "rectangle", min(p[0][0], p[1][0]), min(p[0][1], p[1][1])
            data = {"width": abs(p[1][0] - p[0][0]), "height": abs(p[1][1] - p[0][1])}
        elif tool == "Ellipse":
            kind, x, y = "ellipse", (p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2
            data = {"rx": abs(p[1][0] - p[0][0]) / 2, "ry": abs(p[1][1] - p[0][1]) / 2}
        elif tool in ("Circle", "Arc", "Angular dimension", "Radial dimension"):
            kind, x, y = "circle", *p[0]
            data = {"radius": distance(p[0], p[1])}
            if len(p) >= 3 and tool in ("Arc", "Angular dimension"):
                kind = "arc" if tool == "Arc" else "angular_dimension"
                data["start"] = angle(sub(p[1], p[0]))
                data["sweep"] = (angle(sub(p[2], p[0])) - data["start"]) % 360 or 360
            elif tool == "Radial dimension":
                kind = "radial_dimension"
        elif tool == "Dimension" and len(p) >= 3:
            kind, x, y = "dimension", *p[0]
            v, q = sub(p[1], p[0]), sub(p[2], p[0])
            data = {
                "points": [(0, 0), v],
                "offset": (v[0] * q[1] - v[1] * q[0]) / max(distance(p[0], p[1]), EPS),
            }
        elif tool == "Bezier" and len(p) == 4:
            kind, data = "bezier", {"points": p}
        elif tool in (
            "Line",
            "Polyline",
        ):
            kind, data = "polyline", {"points": p}
        if kind:
            try:
                return Entity(
                    "_preview", kind, x, y, layer=self.doc.active_layer, data=data
                ).validate()
            except ValueError:
                pass
        return None
