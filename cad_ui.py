
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
