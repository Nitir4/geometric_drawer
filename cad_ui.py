UNCONSTRAIN width
Supported: fixed, horizontal, vertical, length, angle, radius, width, height,
coincident, distance, parallel, perpendicular, equal_length, concentric, tangent,
curve_tangent and free_tangent.
Tangent supports a line/circle or two externally tangent circles. Curve tangent takes
two explicit normalized contact parameters (0..1). Free tangent solves the contact
locations from your initial guesses and saves the solved values. Driving
rules are distinct from measurement annotations. Solver is local; DOF is a
numerical diagnostic. See README for tolerances, references and format limits.
This application handles planar drafting. Exact analytic general offsets,
CAM and universal curve-topology guarantees are not implemented. Round path supports
polyline/rectangle corners; Tangents constructs common circle/arc tangents.
Clean offset repairs planar regions and retains all components. Cleanup as filled
regions keeps exterior and holes together. Linked components split/merge; vanished
components retire their dependent branches. Undo restores them. Choose a feature
ID to update or detach a feature even if its output is temporarily empty.
REGION material rings='[[[0,0],[40,0],[40,30],[0,30]],[[10,10],[20,10],[20,20],[10,20]]]' hatch=cross spacing=3
Region rings are local JSON coordinates; exterior first, then holes. Create/edit
via properties, code or vertex grips. Patterns follow placement and orientation.
Solid, lines and cross patterns are available; invalid boundaries roll back.
Extension snaps use nearby virtual line/arc supports without editing the source.
"""

DEFAULTS = {
    "point": {},
    "line": {"length": "40"},
    "rectangle": {"width": "40", "height": "25", "fill": "false"},
    "circle": {"radius": "10"},
    "arc": {"radius": "15", "start": "0", "sweep": "90"},
    "ellipse": {"rx": "20", "ry": "10", "start": "0", "sweep": "360"},
    "region": {
        "rings": "[[[0,0],[40,0],[40,30],[0,30]],[[10,10],[20,10],[20,20],[10,20]]]",
        "hatch": "solid",
        "spacing": "2",
        "hatch_angle": "45",
    },
    "polyline": {"points": "0,0;30,0;30,20", "closed": "false", "fill": "false"},
    "bezier": {"points": "0,0;10,20;30,20;40,0"},
    "text": {"text": "Part A", "height": "3"},
    "dimension": {"points": "0,0;40,0", "offset": "8"},
    "radial_dimension": {"radius": "10"},
    "angular_dimension": {"radius": "15", "start": "0", "sweep": "90"},
}
TOOLS = (
    "Select",
    "Line",
    "Rectangle",
    "Circle",
    "Arc",
    "Ellipse",
    "Polyline",
    "Bezier",
    "Point",
    "Text",
    "Dimension",
    "Radial dimension",
    "Angular dimension",
)


class Viewport:
    def __init__(self):
        self.scale, self.ox, self.oy = 5.0, 90.0, 550.0

    def screen(self, p):
        return self.ox + p[0] * self.scale, self.oy - p[1] * self.scale

    def world(self, x, y):
        return (x - self.ox) / self.scale, (self.oy - y) / self.scale

    def zoom(self, factor, x, y):
        p = self.world(x, y)
        self.scale = max(0.0001, min(1e6, self.scale * factor))
        self.ox, self.oy = x - p[0] * self.scale, y + p[1] * self.scale

    def fit(self, box, width, height):
        x0, y0, x1, y1 = box
        self.scale = max(
            0.0001,
            min(
                (max(100, width) - 80) / max(x1 - x0, 1),
                (max(100, height) - 80) / max(y1 - y0, 1),
                1e6,
            ),
        )
        self.ox = width / 2 - (x0 + x1) / 2 * self.scale
        self.oy = height / 2 + (y0 + y1) / 2 * self.scale


class App(DraftingPanels):
    def __init__(self, root, load_example=True):
        self.root = root
        self.doc = Document()
        self.view = Viewport()
        self.selection = []
        self.pending, self.preview = [], {}
        self.drag = self.pan = self.hover = None
        self.filename = None
        self.saved_state = self.doc.snapshot()
        self.root.title("Geometric Drawer · 2-D CAD")
        self.root.geometry("1480x930")
        self.root.minsize(1120, 720)
        self.status = tk.StringVar(value="Ready · drawing units mm")
        self.coords = tk.StringVar(value="X 0.000  Y 0.000 mm")
        self.tool = tk.StringVar(value="Select")
        self.grid = tk.BooleanVar(value=True)
        self.grid_snap = tk.BooleanVar(value=False)
        self.object_snap = tk.BooleanVar(value=True)
        self.perpendicular_snap = tk.BooleanVar(value=False)
        self.tangent_snap = tk.BooleanVar(value=False)
        self.nearest_snap = tk.BooleanVar(value=False)
        self.extension_snap = tk.BooleanVar(value=False)
        self.linked_features = tk.BooleanVar(value=True)
        self.cleanup_join = tk.StringVar(value="round")
        self.cleanup_regions = tk.BooleanVar(value=True)
        self.feature_target = tk.StringVar()
        self.snap_info = tk.StringVar(value="Snap: —")
        self.ortho = tk.BooleanVar(value=False)
        self.spacing = tk.StringVar(value="5")
        self.unit_var = tk.StringVar(value="mm")
        self.kind_var = tk.StringVar(value="rectangle")
        self.replace_script = tk.BooleanVar(value=False)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-s>", lambda e: self.save_file())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-n>", lambda e: self.new_file())
        if load_example:
            self.editor.insert("1.0", EXAMPLE)
            ScriptEngine(self.doc).execute(EXAMPLE)
            self.doc._undo.clear()
        self.changed()
        self.root.after(100, self.fit)

    def _build(self):
        available_families = set(tkfont.families(self.root))
        ui_family = next(
            (
                family
                for family in ("DejaVu Sans", "Noto Sans", "Arial")
                if family in available_families
            ),
            tkfont.nametofont("TkDefaultFont").actual("family"),
        )
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=ui_family, size=10)
        tkfont.nametofont("TkFixedFont").configure(size=10)
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(7, 5))
        style.configure(".", background="#edf2f7", foreground="#243e58")
        style.configure(
            "Treeview", background="white", fieldbackground="white", rowheight=24
        )
        style.configure("Title.TLabel", font=(ui_family, 12, "bold"))
        menu = tk.Menu(self.root)
        file = tk.Menu(menu, tearoff=False)
        for text, fn in [
            ("New", self.new_file),
            ("Open drawing…", self.open_file),
            ("Save", self.save_file),
            ("Save as…", lambda: self.save_file(True)),
            ("Import DXF / DWG…", self.open_dxf),
            ("Import legacy track…", self.open_legacy),
            ("Export DXF…", lambda: self.export("dxf")),
            ("Export DWG (ODA)…", lambda: self.export("dwg")),
            ("Export SVG…", lambda: self.export("svg")),
            ("Export PDF (1:1)…", lambda: self.export("pdf")),
        ]:
            file.add_command(label=text, command=fn)
        file.add_separator()
        file.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file)
        edit = tk.Menu(menu, tearoff=False)
        for text, fn in [
            ("Undo", self.undo),
            ("Redo", self.redo),
            ("Delete selection", self.delete),
            ("Select all unlocked", self.select_all),
            ("Dimension selection", self.dimension_selection),
        ]:
            edit.add_command(label=text, command=lambda f=fn: self.safe(f))
        menu.add_cascade(label="Edit", menu=edit)
        menu.add_command(label="Fit drawing", command=self.fit)
        menu.add_command(label="Help", command=lambda: self.tabs.select(self.help_tab))
        self.root.configure(menu=menu)

        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="GEOMETRIC DRAWER", style="Title.TLabel").pack(
            side="left", padx=(0, 20)
        )
        self.tool_box = ttk.Combobox(
            top, textvariable=self.tool, values=TOOLS, state="readonly", width=20
        )
        self.tool_box.pack(side="left")
        self.tool_box.bind("<<ComboboxSelected>>", lambda e: self.cancel())
        for title, fn in [
            ("Fit", self.fit),
            ("Undo", self.undo),
            ("Redo", self.redo),
            ("Delete", self.delete),
        ]:
            ttk.Button(top, text=title, command=lambda f=fn: self.safe(f)).pack(
                side="left", padx=3
            )
        for text, var in [
            ("Grid", self.grid),
            ("Grid snap", self.grid_snap),
            ("Object snap", self.object_snap),
            ("Ortho", self.ortho),
        ]:
            ttk.Checkbutton(
                top, text=text, variable=var, command=self.snap_settings_changed
            ).pack(side="left", padx=4)
        ttk.Entry(top, textvariable=self.spacing, width=5).pack(side="left")
        ttk.Label(top, text="spacing").pack(side="left", padx=(3, 10))
        unit_box = ttk.Combobox(
            top,
            textvariable=self.unit_var,
            values=list(UNIT_MM),
            state="readonly",
            width=4,
        )
        unit_box.pack(side="right")
        unit_box.bind("<<ComboboxSelected>>", lambda e: self.safe(self.change_units))

        snap_bar = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        snap_bar.pack(fill="x")
        for title, var in (
            ("Nearest", self.nearest_snap),
            ("Perpendicular", self.perpendicular_snap),
            ("Tangent", self.tangent_snap),
            ("Extension", self.extension_snap),
        ):
            ttk.Checkbutton(
                snap_bar, text=title, variable=var, command=self.snap_settings_changed
            ).pack(side="left", padx=(0, 12))
        ttk.Label(
            snap_bar,
            text="Object snap required; reference modes need a preceding point.",
        ).pack(side="left")
        ttk.Label(snap_bar, textvariable=self.snap_info).pack(side="right")

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        left = ttk.Frame(body, width=210, padding=(0, 0, 8, 0))
        body.add(left, weight=0)
        ttk.Label(left, text="DRAWING", style="Title.TLabel").pack(
            anchor="w", pady=(4, 8)
        )
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("kind",),
            show="tree headings",
            selectmode="extended",
            height=13,
        )
        self.tree.heading("#0", text="Entity")
        self.tree.heading("kind", text="Type")
        self.tree.column("#0", width=110, stretch=True)
        self.tree.column("kind", width=80, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.tree_select)
        ttk.Button(
            left,
            text="Dimension selection",
            command=lambda: self.safe(self.dimension_selection),
        ).pack(fill="x", pady=6)
        ttk.Label(left, text="LAYERS", style="Title.TLabel").pack(
            anchor="w", pady=(12, 4)
        )
        self.layer_var = tk.StringVar(value="0")
        self.layer_box = ttk.Combobox(
            left, textvariable=self.layer_var, state="readonly", width=22
        )
        self.layer_box.pack(fill="x")
        self.layer_box.bind(
            "<<ComboboxSelected>>", lambda e: self.safe(self.choose_layer)
        )
        self.layer_info = tk.StringVar()
        ttk.Label(left, textvariable=self.layer_info, wraplength=200).pack(
            anchor="w", pady=6
        )
        for title, fn in [
            ("New layer…", self.new_layer),
            ("Color…", self.color_layer),
            ("Toggle visibility", lambda: self.toggle_layer("visible")),
            ("Toggle lock", lambda: self.toggle_layer("locked")),
        ]:
            ttk.Button(left, text=title, command=lambda f=fn: self.safe(f)).pack(
                fill="x", pady=2
            )

        center = ttk.Frame(body)
        body.add(center, weight=4)
        self.canvas = tk.Canvas(
            center,
            background="#f8fafc",
            highlightthickness=1,
            highlightbackground="#c5d1dc",
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        for event, fn in [
            ("<Configure>", lambda e: self.redraw()),
            ("<ButtonPress-1>", self.press),
            ("<B1-Motion>", self.motion),
            ("<ButtonRelease-1>", self.release),
            ("<Motion>", self.motion),
            ("<MouseWheel>", self.wheel),
            ("<Button-4>", self.wheel),
            ("<Button-5>", self.wheel),
            ("<ButtonPress-2>", self.pan_start),
            ("<B2-Motion>", self.pan_motion),
            ("<Escape>", lambda e: self.cancel(True)),
            ("<Return>", lambda e: self.safe(self.finish_polyline)),
            ("<Delete>", lambda e: self.safe(self.delete)),
            ("<Control-z>", lambda e: self.undo()),
            ("<Control-y>", lambda e: self.redo()),
            ("<Control-a>", lambda e: self.select_all()),
        ]:
            self.canvas.bind(event, fn)
        ttk.Label(
            center,
            text="Wheel: zoom  ·  Middle drag: pan  ·  Shift-click: multi-select  ·  Esc: cancel  ·  Enter: finish polyline",
        ).pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(body, width=340, padding=(8, 0, 0, 0))
        body.add(right, weight=1)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        properties_tab = ttk.Frame(self.tabs)
        self.tabs.add(properties_tab, text="Control panel")
        prop_scroll = tk.Canvas(
            properties_tab, highlightthickness=0, width=340, background="#edf2f7"
        )
        prop_bar = ttk.Scrollbar(
            properties_tab, orient="vertical", command=prop_scroll.yview
        )
        prop_scroll.configure(yscrollcommand=prop_bar.set)
        prop_bar.pack(side="right", fill="y")
        prop_scroll.pack(side="left", fill="both", expand=True)
        properties = ttk.Frame(prop_scroll, padding=8)
        prop_window = prop_scroll.create_window(0, 0, window=properties, anchor="nw")
        properties.bind(
            "<Configure>",
            lambda e: prop_scroll.configure(scrollregion=prop_scroll.bbox("all")),
        )
        prop_scroll.bind(
            "<Configure>",
            lambda e: prop_scroll.itemconfigure(prop_window, width=e.width),
        )
        code = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(code, text="Code")
        self.build_constraint_panel()
        self.build_drafting_panels()
        self.help_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.help_tab, text="Guide")
        kind_box = ttk.Combobox(
            properties, textvariable=self.kind_var, values=KINDS, state="readonly"
        )
        kind_box.pack(fill="x")
        kind_box.bind("<<ComboboxSelected>>", lambda e: self.property_form())
        self.prop_frame = ttk.Frame(properties)
        self.prop_frame.pack(fill="x", pady=8)
        self.props = {}
        self.property_form()
        row = ttk.Frame(properties)
        row.pack(fill="x", pady=5)
        ttk.Button(
            row, text="Create", command=lambda: self.safe(self.create_properties)
        ).pack(side="left", expand=True, fill="x")
        ttk.Button(
            row,
            text="Apply to selection",
            command=lambda: self.safe(self.apply_properties),
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.selection_info = tk.StringVar(value="No selection")
        ttk.Label(properties, textvariable=self.selection_info, wraplength=315).pack(
            anchor="w", pady=5
        )
        ttk.Separator(properties).pack(fill="x", pady=8)
        ttk.Label(properties, text="MODIFY", style="Title.TLabel").pack(anchor="w")
        fields = ttk.Frame(properties)
        fields.pack(fill="x", pady=6)
        self.transform_vars = {}
        for i, (k, val) in enumerate(
            [
                ("dx", "10"),
                ("dy", "0"),
                ("rotation", "90"),
                ("factor", "1"),
                ("pivot x", "0"),
                ("pivot y", "0"),
                ("amount", "5"),
                ("count", "4"),
                ("curve tol", "0.01"),
            ]
        ):
            ttk.Label(fields, text=k).grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=2
            )
            v = tk.StringVar(value=val)
            self.transform_vars[k] = v
            ttk.Entry(fields, textvariable=v, width=9).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="ew", padx=(0, 8), pady=2
            )
        ttk.Checkbutton(
            properties,
            text="Linked (edit sources; detach to edit results)",
            variable=self.linked_features,
        ).pack(anchor="w")
        ttk.Combobox(
            properties,
            textvariable=self.cleanup_join,
            values=("round", "mitre", "bevel"),
            state="readonly",
            width=12,
        ).pack(anchor="w")
        ttk.Checkbutton(
            properties, text="Cleanup as filled regions", variable=self.cleanup_regions
        ).pack(anchor="w")
        ttk.Label(properties, text="Feature ID (for hidden/empty results)").pack(
            anchor="w"
        )
        self.feature_box = ttk.Combobox(
            properties, textvariable=self.feature_target, state="readonly"
        )
        self.feature_box.pack(fill="x")
        buttons = ttk.Frame(properties)
        buttons.pack(fill="x")
        for i, op in enumerate(
            (
                "Move",
                "Copy",
                "Rotate",
                "Scale",
                "Mirror",
                "Offset",
                "Array",
                "Trim",
                "Extend",
                "Fillet",
                "Chamfer",
                "Round path",
                "Tangents",
                "Clean offset",
                "Union",
                "Difference",
                "Intersection",
                "Detach",
                "Update feature",
                "Select sources",
            )
        ):
            ttk.Button(
                buttons,
                text=op,
                command=lambda name=op: self.safe(lambda: self.modify(name)),
            ).grid(row=i // 3, column=i % 3, sticky="ew", padx=1, pady=2)
        for i in range(3):
            buttons.columnconfigure(i, weight=1)
        ttk.Label(
            properties,
            text="Pivot picks the trim end or crossing corner.\nCurve tol bounds ellipse/Bezier offset chord error, in drawing units.",
            wraplength=300,
        ).pack(anchor="w", pady=7)

        bar = ttk.Frame(code)
        bar.pack(fill="x")
        ttk.Button(bar, text="Run", command=lambda: self.safe(self.run_script)).pack(
            side="left"
        )
        ttk.Checkbutton(bar, text="Replace drawing", variable=self.replace_script).pack(
            side="left", padx=4
        )
        self.editor = tk.Text(
            code, width=36, wrap="none", undo=True, font="TkFixedFont"
        )
        self.editor.pack(fill="both", expand=True, pady=5)
        sx = ttk.Scrollbar(code, orient="horizontal", command=self.editor.xview)
        sx.pack(fill="x")
        self.editor.configure(xscrollcommand=sx.set)
        bottom = ttk.Frame(code)
        bottom.pack(fill="x", pady=4)
        for title, fn in [
            ("Drawing → code", self.drawing_to_code),
            ("Open…", self.open_script),
            ("Save…", self.save_script),
        ]:
            ttk.Button(bottom, text=title, command=lambda f=fn: self.safe(f)).pack(
                side="left", padx=1
            )
        guide = tk.Text(
            self.help_tab,
            wrap="word",
            width=40,
            font="TkDefaultFont",
            padx=10,
            pady=10,
        )
        guide.insert("1.0", HELP)
        guide.configure(state="disabled")
        guide.pack(fill="both", expand=True)
        bottom = ttk.Frame(self.root, padding=(10, 3))
        bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        ttk.Label(bottom, textvariable=self.coords).pack(side="right")

    def build_constraint_panel(self):
        try:
            from .cad_constraints import KINDS as CONSTRAINT_KINDS
        except ImportError:
            from cad_constraints import KINDS as CONSTRAINT_KINDS
        self.build_parameter_tab()
        self.constraint_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.constraint_tab, text="Constraints")
        tab = self.constraint_tab
        ttk.Label(tab, text="DRIVING SKETCH CONSTRAINTS", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            tab,
            text="References: IDs or ID@index for vertices. Arc @0 is centre, @1 start, @2 end. Symmetry uses two points then a line. Separate references with commas.",
            wraplength=310,
        ).pack(fill="x", pady=8)
        self.constraint_kind = tk.StringVar(value="length")
        self.constraint_refs = tk.StringVar()
        self.constraint_value = tk.StringVar(value="40")
        self.constraint_parameters = tk.StringVar(value="0.5,0.5")
        ttk.Combobox(
            tab,
            textvariable=self.constraint_kind,
            values=CONSTRAINT_KINDS,
            state="readonly",
        ).pack(fill="x", pady=4)
        ttk.Label(tab, text="References").pack(anchor="w")
        ttk.Entry(tab, textvariable=self.constraint_refs).pack(fill="x")
        ttk.Button(
            tab, text="Use selected entities", command=self.constraint_use_selection
        ).pack(fill="x", pady=4)
        ttk.Label(tab, text="Value (drawing units, or degrees for angle)").pack(
            anchor="w"
        )
        ttk.Entry(tab, textvariable=self.constraint_value).pack(fill="x")
        ttk.Label(tab, text="Curve tangent contact parameters (0..1), t1,t2").pack(
            anchor="w"
        )
        ttk.Entry(tab, textvariable=self.constraint_parameters).pack(fill="x")
        ttk.Button(
            tab, text="Add constraint", command=lambda: self.safe(self.constraint_add)
        ).pack(fill="x", pady=6)
        self.constraint_tree = ttk.Treeview(
            tab,
            columns=("rule", "value"),
            show="tree headings",
            height=10,
            selectmode="browse",
        )
        self.constraint_tree.heading("#0", text="ID")
        self.constraint_tree.column("#0", width=75, stretch=False)
        self.constraint_tree.heading("rule", text="Rule / references")
        self.constraint_tree.column("rule", width=160)
        self.constraint_tree.heading("value", text="Value")
        self.constraint_tree.column("value", width=65, stretch=False)
        self.constraint_tree.pack(fill="both", expand=True)
        self.constraint_tree.bind("<<TreeviewSelect>>", self.constraint_select)
        ttk.Button(
            tab,
            text="Update driving value",
            command=lambda: self.safe(self.constraint_drive),
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab,
            text="Remove constraint",
            command=lambda: self.safe(self.constraint_remove),
        ).pack(fill="x")
        self.constraint_info = tk.StringVar(value="No constraints")
        ttk.Label(tab, textvariable=self.constraint_info, wraplength=310).pack(
            fill="x", pady=8
        )
        ttk.Label(
            tab,
            text="Manual and numeric edits are solved against these rules. To resize a driven sketch, update its driving value. Conflicts roll back the whole edit. Copies start unconstrained.",
            wraplength=310,
        ).pack(fill="x")

    def build_parameter_tab(self):
        self.parameter_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.parameter_tab, text="Parameters")
        scroll = tk.Canvas(self.parameter_tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            self.parameter_tab, orient="vertical", command=scroll.yview
        )
        scrollbar.pack(side="right", fill="y")
        scroll.pack(side="left", fill="both", expand=True)
        scroll.configure(yscrollcommand=scrollbar.set)
        tab = ttk.Frame(scroll, padding=4)
        window = scroll.create_window((0, 0), window=tab, anchor="nw")
        tab.bind(
            "<Configure>",
            lambda event: scroll.configure(scrollregion=scroll.bbox("all")),
        )
        scroll.bind(
            "<Configure>", lambda event: scroll.itemconfigure(window, width=event.width)
        )
        ttk.Label(tab, text="PERSISTENT DESIGN PARAMETERS", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            tab,
            text="Expressions follow named dependencies. Lengths keep their declaration units; angles use degrees. Trig functions take radians.",
            wraplength=310,
        ).pack(fill="x", pady=6)
        self.parameter_name = tk.StringVar()
        self.parameter_expression = tk.StringVar(value="20")
        self.parameter_kind = tk.StringVar(value="length")
        self.parameter_units = tk.StringVar(value=self.doc.units)
        for label, variable in (
            ("Name", self.parameter_name),
            ("Expression", self.parameter_expression),
        ):
            ttk.Label(tab, text=label).pack(anchor="w")
            ttk.Entry(tab, textvariable=variable).pack(fill="x")
        ttk.Combobox(
            tab,
            textvariable=self.parameter_kind,
            values=("length", "angle", "scalar"),
            state="readonly",
        ).pack(fill="x", pady=4)
        ttk.Label(tab, text="Expression length units").pack(anchor="w")
        ttk.Combobox(
            tab,
            textvariable=self.parameter_units,
            values=("mm", "cm", "m", "in"),
            state="readonly",
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab, text="Set parameter", command=lambda: self.safe(self.parameter_set)
        ).pack(fill="x")
        self.parameter_tree = ttk.Treeview(
            tab,
            columns=("expression", "value"),
            show="tree headings",
            height=5,
            selectmode="browse",
        )
        for key, label, width in (
            ("#0", "Name", 85),
            ("expression", "Expression", 135),
            ("value", "Value", 75),
        ):
            self.parameter_tree.heading(key, text=label)
            self.parameter_tree.column(key, width=width)
        self.parameter_tree.pack(fill="x", pady=6)
        self.parameter_tree.bind("<<TreeviewSelect>>", self.parameter_select)
        ttk.Button(
            tab,
            text="Remove parameter",
            command=lambda: self.safe(self.parameter_remove),
        ).pack(fill="x")
        self.binding_target = tk.StringVar(value="entity")
        self.binding_id = tk.StringVar()
        self.binding_property = tk.StringVar(value="radius")
        self.binding_expression = tk.StringVar()
        self.binding_units = tk.StringVar(value=self.doc.units)
        ttk.Label(tab, text="EXPRESSION DRIVERS", style="Title.TLabel").pack(
            anchor="w", pady=(12, 4)
        )
        ttk.Combobox(
            tab,
            textvariable=self.binding_target,
            values=("entity", "constraint", "feature"),
            state="readonly",
        ).pack(fill="x")
        for label, variable in (
            ("Target ID", self.binding_id),
            ("Property (e.g. radius, v0.x, value, amount)", self.binding_property),
            ("Expression", self.binding_expression),
        ):
            ttk.Label(tab, text=label).pack(anchor="w")
            ttk.Entry(tab, textvariable=variable).pack(fill="x")
        ttk.Label(tab, text="Driver expression length units").pack(anchor="w")
        ttk.Combobox(
            tab,
            textvariable=self.binding_units,
            values=("mm", "cm", "m", "in"),
            state="readonly",
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab, text="Use selected target", command=self.binding_use_selection
        ).pack(fill="x", pady=4)
        ttk.Button(
            tab, text="Bind expression", command=lambda: self.safe(self.binding_set)
        ).pack(fill="x")
        self.binding_tree = ttk.Treeview(
            tab,
            columns=("expression",),
            show="tree headings",
            height=5,
            selectmode="browse",
        )
        self.binding_tree.heading("#0", text="Target / property")
        self.binding_tree.heading("expression", text="Expression")
        self.binding_tree.column("#0", width=170)
        self.binding_tree.column("expression", width=125)
        self.binding_tree.pack(fill="both", expand=True, pady=6)
        self.binding_tree.bind("<<TreeviewSelect>>", self.binding_select)
        ttk.Button(
            tab,
            text="Unbind expression",
            command=lambda: self.safe(self.binding_remove),
        ).pack(fill="x")
        ttk.Label(
            tab,
            text="Drivers are enforced during manual and numeric edits. Change the parameter or unbind to edit a driven property. Unit changes preserve the physical design.",
            wraplength=310,
        ).pack(fill="x", pady=8)

    def parameter_select(self, event=None):
        ids = self.parameter_tree.selection()
        if ids and ids[0] in self.doc.parameters:
            name = ids[0]
            spec = self.doc.parameters[name]
            self.parameter_name.set(name)
            self.parameter_expression.set(spec["expression"])
            self.parameter_kind.set(spec["kind"])
            self.parameter_units.set(spec["units"])

    def parameter_set(self):
        name = self.parameter_name.get().strip()
        # The visible unit selector makes the expression convention explicit.
        units = self.parameter_units.get()
        self.doc.set_parameter(
            name,
            self.parameter_expression.get(),
            self.parameter_kind.get(),
            units=units,
        )
        self.changed("Parameter updated; geometry regenerated")

    def parameter_remove(self):
        self.doc.remove_parameter(self.parameter_name.get().strip())
        self.changed("Parameter removed")

    def binding_use_selection(self):
        target = self.binding_target.get()
        if target == "entity" and self.selection:
            self.binding_id.set(self.selection[0])
        elif target == "constraint" and self.constraint_tree.selection():
            self.binding_id.set(self.constraint_tree.selection()[0])
        elif target == "feature":
            self.binding_id.set(self.feature_target.get())

    def binding_set(self):
        self.doc.bind(
            self.binding_id.get().strip(),
            self.binding_property.get().strip(),
            self.binding_expression.get(),
            target=self.binding_target.get(),
            units=self.binding_units.get(),
        )
        self.changed("Expression bound; geometry regenerated")

    def binding_remove(self):
        self.doc.unbind(
            self.binding_id.get().strip(),
            self.binding_property.get().strip(),
            target=self.binding_target.get(),
        )
        self.changed("Expression unbound")

    def binding_select(self, event=None):
        ids = self.binding_tree.selection()
        if ids:
            b = self.doc.bindings[int(ids[0])]
            self.binding_target.set(b["target"])
            self.binding_id.set(b["id"])
            self.binding_property.set(b["property"])
            self.binding_expression.set(b["expression"])
            self.binding_units.set(b["units"])

    def refresh_parameters(self):
        selected = self.parameter_tree.selection()
        self.parameter_tree.delete(*self.parameter_tree.get_children())
        values = self.doc.parameter_values()
        for name, spec in self.doc.parameters.items():
            self.parameter_tree.insert(
                "",
                "end",
                iid=name,
                text=name,
                values=(
                    spec["expression"],
                    f"{values[name]:g} {self.doc.units if spec['kind'] == 'length' else spec['kind']}",
                ),
            )
        self.parameter_tree.selection_set(
            [n for n in selected if n in self.doc.parameters]
        )
        self.binding_tree.delete(*self.binding_tree.get_children())
        for i, b in enumerate(self.doc.bindings):
            self.binding_tree.insert(
                "",
                "end",
                iid=str(i),
                text=f"{b['target']}:{b['id']}.{b['property']}",
                values=(b["expression"],),
            )

    def constraint_use_selection(self):
        self.constraint_refs.set(",".join(self.selection))

    def constraint_select(self, event=None):
        ids = self.constraint_tree.selection()
        if ids and ids[0] in self.doc.constraints:
            c = self.doc.constraints[ids[0]]
            self.constraint_kind.set(c["kind"])
            self.constraint_refs.set(",".join(c["refs"]))
            self.constraint_value.set(str(c.get("value", "")))
            self.constraint_parameters.set(
                ",".join(str(t) for t in c.get("parameters", [0.5, 0.5]))
            )

    def constraint_add(self):
        kind = self.constraint_kind.get()
        dimensional = kind in (
            "length",
            "radius",
            "width",
            "height",
            "distance",
            "angle",
            "angle_between",
            "arc_start",
            "arc_sweep",
            "rx",
            "ry",
        )
        value = (
            ScriptEngine(self.doc).number(self.constraint_value.get())
            if dimensional
            else None
        )
        self.doc.constrain(
            kind,
            [r.strip() for r in self.constraint_refs.get().split(",")],
            value,
            parameters=[
                ScriptEngine(self.doc).number(t.strip())
                for t in self.constraint_parameters.get().split(",")
            ]
            if kind in ("curve_tangent", "free_tangent")
            else None,
        )
        self.changed("Constraint added and sketch solved")

    def constraint_drive(self):
        ids = self.constraint_tree.selection()
        if not ids:
            raise ValueError("Select a driving constraint first.")
        if self.doc.constraints[ids[0]]["kind"] in ("curve_tangent", "free_tangent"):
            self.doc.set_constraint_parameters(
                ids[0],
                [
                    ScriptEngine(self.doc).number(t.strip())
                    for t in self.constraint_parameters.get().split(",")
                ],
            )
        else:
            self.doc.set_constraint_value(
                ids[0], ScriptEngine(self.doc).number(self.constraint_value.get())
            )
        self.changed("Driving value updated; sketch solved")

    def constraint_remove(self):
        ids = self.constraint_tree.selection()
        if not ids:
            raise ValueError("Select a constraint first.")
        self.doc.remove_constraint(ids[0])
        self.changed("Constraint removed")

    def safe(self, fn):
        try:
            return fn()
        except (ValueError, KeyError, OSError, TypeError, ArithmeticError) as exc:
            self.status.set(str(exc))
            messagebox.showerror(
                "Cannot complete operation", str(exc), parent=self.root
            )

    def changed(self, message=None):
        self.doc.refresh_dimensions()
        self.refresh_parameters()
        self.assembly_refresh()
        self.feature_box.configure(values=list(self.doc.features))
        if self.feature_target.get() not in self.doc.features:
            self.feature_target.set("")
        selected_constraints = self.constraint_tree.selection()
        self.constraint_tree.delete(*self.constraint_tree.get_children())
        for c in self.doc.constraints.values():
            self.constraint_tree.insert(
                "",
                "end",
                iid=c["id"],
                text=c["id"],
                values=(c["kind"] + " " + ",".join(c["refs"]), c.get("value", "")),
            )
        self.constraint_tree.selection_set(
            [id for id in selected_constraints if id in self.doc.constraints]
        )
        if self.doc.constraints or self.doc.bindings:
            report = self.doc.constraint_report()
            self.constraint_info.set(
                f"{report['constraints']} constraints · {report['dof']} local degrees of freedom\nResidual {report['max_residual']:.2g}"
            )
        else:
            self.constraint_info.set("No constraints")
        self.selection = [
            i
            for i in self.selection
            if i in self.doc.entities
            and not self.doc.layers[self.doc.entities[i].layer].locked
            and self.doc.layers[self.doc.entities[i].layer].visible
        ]
        self._syncing_tree = True
        self.tree.delete(*self.tree.get_children())
        for e in self.doc.entities.values():
            layer = self.doc.layers[e.layer]
            self.tree.insert(
                "",
                "end",
                iid=e.id,
                text=e.id,
                values=(e.kind,),
                tags=("locked" if layer.locked or not layer.visible else "normal",),
            )
        self.tree.tag_configure("locked", foreground="#999999")
        self.tree.selection_set(self.selection)
        self._syncing_tree = False
        self.unit_var.set(self.doc.units)
        self.layer_box.configure(values=list(self.doc.layers))
        if self.layer_var.get() not in self.doc.layers:
            self.layer_var.set(self.doc.active_layer)
        l = self.doc.layers[self.layer_var.get()]
        self.layer_info.set(
            f"{l.color} · {l.width:g} {self.doc.units}\n"
            + ("Visible" if l.visible else "Hidden")
            + " · "
            + ("Locked" if l.locked else "Unlocked")
        )
        self.update_selection()
        name = Path(self.filename).name if self.filename else "Untitled"
        dirty = self.doc.snapshot() != self.saved_state
        self.root.title(f"{'● ' if dirty else ''}{name} · Geometric Drawer · 2-D CAD")
        if message:
            if self.doc.topology_events:
                created = sum(len(e["created"]) for e in self.doc.topology_events)
                retired = sum(len(e["retired"]) for e in self.doc.topology_events)
                message += f" · topology: {created} new, {retired} retired components"
            self.status.set(message)
        self.redraw()

    def property_form(self, e=None):
        for child in self.prop_frame.winfo_children():
            child.destroy()
        k = self.kind_var.get()
        values = {
            "id": "",
            "x": "0",
            "y": "0",
            "orientation": "0",
            "layer": self.doc.active_layer,
            "construction": "false",
        }
        values.update(DEFAULTS[k])
        if e:
            values.update(
                id=e.id,
                x=f"{e.x:.12g}",
                y=f"{e.y:.12g}",
                orientation=f"{e.angle:.12g}",
                layer=e.layer,
                construction=str(e.construction).lower(),
            )
            for key in DEFAULTS[k]:
                value = e.data.get(key, DEFAULTS[k][key])
                if key == "rings":
                    value = json.dumps(value)
                if key == "points":
                    value = ";".join(",".join(f"{v:.12g}" for v in p) for p in value)
                values[key] = (
                    str(value).lower() if isinstance(value, bool) else str(value)
                )
            if k == "line":
                a, b = e.vertices()
                values.update(
                    x=f"{a[0]:.12g}",
                    y=f"{a[1]:.12g}",
                    orientation=f"{angle(sub(b, a)):.12g}",
                    length=f"{distance(a, b):.12g}",
                )
        self.props = {}
        for i, (key, val) in enumerate(values.items()):
            ttk.Label(self.prop_frame, text=key).grid(
                row=i, column=0, sticky="w", padx=(0, 6), pady=2
            )
            var = tk.StringVar(value=val)
            self.props[key] = var
            if key in ("construction", "closed", "fill"):
                widget = ttk.Combobox(
                    self.prop_frame,
                    textvariable=var,
                    values=("false", "true"),
                    state="readonly",
                    width=22,
                )
            elif key == "layer":
                widget = ttk.Combobox(
                    self.prop_frame,
                    textvariable=var,
                    values=list(self.doc.layers),
                    state="readonly",
                    width=22,
                )
            else:
                widget = ttk.Entry(self.prop_frame, textvariable=var, width=25)
            widget.grid(row=i, column=1, sticky="ew", pady=2)
        self.prop_frame.columnconfigure(1, weight=1)

    def read_properties(self, existing=None):
        v = {k: value.get() for k, value in self.props.items()}
        engine = ScriptEngine(self.doc)
        n = engine.number
        id = v.pop("id") or self.doc.unique_id(self.kind_var.get())
        if existing and id != existing.id:
            raise ValueError(
                "Entity IDs stay fixed; use Copy to create another entity."
            )
        k = self.kind_var.get()
        common = {
            "id": id,
            "kind": k,
            "x": n(v.pop("x")),
            "y": n(v.pop("y")),
            "angle": n(v.pop("orientation")),
            "layer": v.pop("layer"),
            "construction": v.pop("construction") == "true",
        }
        data = copy.deepcopy(existing.data) if existing and k == existing.kind else {}
        if existing and "block_edit_key" in existing.data:
            data["block_edit_key"] = existing.data["block_edit_key"]
        for key, val in v.items():
            if key in ("text", "hatch"):
                data[key] = val
            elif key == "rings":
                data[key] = json.loads(val)
            elif key == "points":
                data[key] = [tuple(n(x) for x in p.split(",")) for p in val.split(";")]
            elif key in ("closed", "fill"):
                data[key] = val == "true"
            elif key == "length" and k == "line":
                data["points"] = [(0, 0), (positive(n(val)), 0)]
            else:
                data[key] = n(val)
        return Entity(**common, data=data).validate()

    def create_properties(self):
        e = self.read_properties()
        if e.id in self.doc.entities:
            e.id = self.doc.unique_id(e.kind)
        id = self.doc.add(
            e.kind,
            id=e.id,
            x=e.x,
            y=e.y,
            angle=e.angle,
            layer=e.layer,
            construction=e.construction,
            **e.data,
        )
        self.selection = [id]
        self.changed("Created " + id)

    def apply_properties(self):
        if len(self.selection) != 1:
            raise ValueError("Select exactly one entity to edit properties.")
        old = self.doc.entities[self.selection[0]]
        e = self.read_properties(old)
        # Independent geometry edits freeze an annotation; offset-only edits stay associative.
        if e.data.get("ref") and (
            e.x,
            e.y,
            e.angle,
            e.data.get("points"),
            e.data.get("radius"),
        ) != (
            old.x,
            old.y,
            old.angle,
            old.data.get("points"),
            old.data.get("radius"),
        ):
            e.data.pop("ref")
        self.doc.replace(e)
        self.changed("Properties applied")

    def update_selection(self):
        self.selection_info.set(
            ", ".join(self.selection) if self.selection else "No selection"
        )
        if len(self.selection) == 1:
            e = self.doc.entities[self.selection[0]]
            f = self.doc.feature_for(e.id)
            if not f:
                self.feature_target.set("")
            if f:
                self.feature_target.set(f["id"])
                self.selection_info.set(
                    f"{e.id} · Linked {f['kind']} ({f['id']})\nSources: {', '.join(f['sources'])}\nEdit via Select sources or Update feature; Detach for independent edits."
                )
            self.kind_var.set(e.kind)
            self.property_form(e)

    def tree_select(self, event=None):
        if getattr(self, "_syncing_tree", False):
            return
        ids = [
            i
            for i in self.tree.selection()
            if self.doc.layers[self.doc.entities[i].layer].visible
            and not self.doc.layers[self.doc.entities[i].layer].locked
        ]
        if ids == self.selection:
            return
        self.selection = self.doc.expand_selection(ids)
        self.update_selection()
        self.redraw()

    def select_all(self):
        self.selection = [
            e.id
            for e in self.doc.entities.values()
            if self.doc.layers[e.layer].visible and not self.doc.layers[e.layer].locked
        ]
        self.changed()

    def modify(self, op):
        feature_op = op in ("Detach", "Select sources", "Update feature")
        if not self.selection and not (feature_op and self.feature_target.get()):
            raise ValueError("Select geometry or a feature ID first.")
        target = (
            self.feature_target.get()
            if feature_op and self.feature_target.get()
            else self.selection[0]
        )
        v = {
            k: ScriptEngine(self.doc).number(x.get())
            for k, x in self.transform_vars.items()
        }
        pivot = v["pivot x"], v["pivot y"]
        if op in ("Move", "Copy", "Rotate", "Scale"):
            self.selection = self.doc.transform(
                self.selection,
                dx=v["dx"] if op in ("Move", "Copy") else 0,
                dy=v["dy"] if op in ("Move", "Copy") else 0,
                rotation=v["rotation"] if op == "Rotate" else 0,
                scale=v["factor"] if op == "Scale" else 1,
                pivot=pivot,
                copy_entities=op == "Copy",
            )
        elif op == "Mirror":
            self.selection = self.doc.mirror(
                self.selection, pivot, add(pivot, polar(1, v["rotation"]))
            )
        elif op == "Array":
            self.selection += self.doc.array(
                self.selection[:], v["count"], v["dx"], v["dy"], v["rotation"], pivot
            )
        elif op == "Detach":
            self.selection = self.doc.detach_feature(target)
        elif op == "Select sources":
            f = self.doc.feature_for(target)
            if f is None:
                raise ValueError("Select a linked output.")
            self.selection = list(f["sources"])
        elif op == "Update feature":
            f = self.doc.feature_for(target)
            if f is None:
                raise ValueError("Select a linked output.")
            params = {}
            for key in ("amount", "radius"):
                if key in f["params"]:
                    params[key] = v["amount"]
            if "tolerance" in f["params"]:
                params["tolerance"] = v["curve tol"]
            if "join" in f["params"]:
                params["join"] = self.cleanup_join.get()
            if "as_regions" in f["params"]:
                params["as_regions"] = self.cleanup_regions.get()
            self.doc.update_feature(f["id"], **params)
            self.selection = list(f["outputs"])
        elif op in ("Round path", "Clean offset"):
            if len(self.selection) != 1:
                raise ValueError("Select one path.")
            if op == "Round path":
                self.selection = [
                    self.doc.round_path(
                        self.selection[0],
                        v["amount"],
                        tolerance=v["curve tol"],
                        linked=self.linked_features.get(),
                    )
                ]
            else:
                self.selection = self.doc.clean_offset(
                    self.selection[0],
                    v["amount"],
                    tolerance=v["curve tol"],
                    join=self.cleanup_join.get(),
                    as_regions=self.cleanup_regions.get(),
                    linked=self.linked_features.get(),
                )
        elif op == "Tangents":
            if len(self.selection) != 2:
                raise ValueError("Select two circles/arcs.")
            self.selection = self.doc.common_tangents(
                *self.selection, linked=self.linked_features.get()
            )
        elif op in ("Union", "Difference", "Intersection"):
            if len(self.selection) < 2:
                raise ValueError(
                    "Select at least two closed shapes; Difference subtracts later selections from the first."
                )
            self.selection = self.doc.boolean(
                self.selection,
                op.lower(),
                tolerance=v["curve tol"],
                linked=self.linked_features.get(),
            )
        elif op == "Offset":
            if len(self.selection) != 1:
                raise ValueError("Select one supported edge or curve.")
            self.selection = [
                self.doc.offset(
                    self.selection[0],
                    v["amount"],
                    tolerance=v["curve tol"],
                    linked=self.linked_features.get(),
                )
            ]
        else:
            if len(self.selection) != 2:
                raise ValueError("Select target and cutter in that order.")
            if op in ("Trim", "Extend"):
                self.selection = self.doc.trim_extend(
                    *self.selection, pivot, op == "Extend", tolerance=v["curve tol"]
                )
            else:
                connector = self.doc.corner(
                    *self.selection,
                    v["amount"],
                    fillet=op == "Fillet",
                    pick=pivot,
                    linked=self.linked_features.get(),
                )
                if connector and self.linked_features.get():
                    self.selection = [connector]
        result = self.doc.entities[self.selection[0]] if self.selection else None
        info = (
            result.data.get("offset_approximation")
            if result is not None and op == "Offset"
            else None
        )
        self.changed(
            f"Offset: {len(result.data['points'])} polyline vertices; tolerance {info['tolerance']:g} {self.doc.units}"
            if info
            else op + " completed"
        )

    def dimension_selection(self):
        if not self.selection:
            raise ValueError("Select a line, circle or arc.")
        with self.doc.transaction("Dimension selection"):
            ids = [self.doc.dimension(i) for i in self.selection]
        self.selection = ids
        self.changed("Associative dimensions created")

    def delete(self):
        self.doc.delete(self.selection)
        self.selection = []
        self.cancel()
        self.changed("Deleted selection")

    def undo(self):
        self.cancel()
        label = self.doc.undo()
        self.changed("Undo " + label if label else "Nothing to undo")

    def redo(self):
        self.cancel()
        label = self.doc.redo()
        self.changed("Redo " + label if label else "Nothing to redo")

    def choose_layer(self):
        name = self.layer_var.get()
        if not self.doc.layers[name].locked:
            self.doc.active_layer = name
        self.changed()

    def new_layer(self):
        name = simpledialog.askstring("New layer", "Layer name:", parent=self.root)
        if name:
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
