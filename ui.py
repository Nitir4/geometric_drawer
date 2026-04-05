from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from .builder import TrackBuilder
    from .exporting import Exporter
    from .rendering import OverflowInfo, Renderer, Settings
except ImportError:
    from builder import TrackBuilder
    from exporting import Exporter
    from rendering import OverflowInfo, Renderer, Settings


class App:
    EXAMPLE = """POINT A 0 0
LINE FROM=A LEN=40 ANGLE=90 TO=B
LINE FROM=B LEN=60 ANGLE=0 TO=C
LINE FROM=B LEN=30 ANGLE=180 TO=D
CIRCLE CENTER=C R=10
LINE FROM=C LEN=20 ANGLE=90 TO=E
LINE FROM=C LEN=20 ANGLE=-90 TO=F
"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LFR Track Generator (Graph-Based)")
        self.root.minsize(1000, 650)

        self.builder = TrackBuilder()

        self.var_width = tk.StringVar(value="244")
        self.var_height = tk.StringVar(value="244")
        self.var_line_width = tk.StringVar(value="3")
        self.var_margin = tk.StringVar(value="5")
        self.var_markers = tk.BooleanVar(value=False)

        self._build_ui()
        self.editor.insert("1.0", self.EXAMPLE)
        self.root.after(50, self.render)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        for label, var in (
            ("Track Width (mm)", self.var_width),
            ("Track Height (mm)", self.var_height),
            ("Line Width (mm)", self.var_line_width),
            ("Margin (mm)", self.var_margin),
        ):
            self._labeled_entry(top, label, var)

        tk.Button(top, text="Render", command=self.render).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Export SVG", command=self.export_svg).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Export PDF", command=self.export_pdf).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Clear", command=self.clear_editor).pack(side=tk.LEFT, padx=4)
        tk.Checkbutton(
            top,
            text="Start/End Markers",
            variable=self.var_markers,
            command=self.render,
        ).pack(side=tk.LEFT, padx=8)

        body = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = tk.Frame(body)
        tk.Label(left, text="Commands").pack(anchor="w")
        self.editor = tk.Text(left, wrap=tk.NONE, undo=True, font=("Courier", 11))
        self.editor.pack(fill=tk.BOTH, expand=True)
        body.add(left, minsize=380)

        right = tk.Frame(body)
        tk.Label(right, text="Preview").pack(anchor="w")
        self.canvas = tk.Canvas(right, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.render(silent=True))
        body.add(right)

        self.status = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status, anchor="w").pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 6))

    @staticmethod
    def _labeled_entry(parent: tk.Widget, label: str, var: tk.StringVar) -> None:
        frame = tk.Frame(parent)
        frame.pack(side=tk.LEFT, padx=4)
        tk.Label(frame, text=label).pack(anchor="w")
        tk.Entry(frame, textvariable=var, width=10).pack(anchor="w")

    def _read_settings(self) -> Settings:
        width = float(self.var_width.get())
        height = float(self.var_height.get())
        line_width = float(self.var_line_width.get())
        margin = float(self.var_margin.get())

        if width <= 0 or height <= 0:
            raise ValueError("Track width/height must be positive")
        if line_width <= 0:
            raise ValueError("Line width must be positive")
        if margin < 0:
            raise ValueError("Margin cannot be negative")
        if margin * 2 >= width or margin * 2 >= height:
            raise ValueError("Margin is too large for track size")

        return Settings(
            track_width=width,
            track_height=height,
            line_width=line_width,
            margin=margin,
        )

    def _parse_or_raise(self) -> None:
        script = self.editor.get("1.0", tk.END)
        if not self.builder.parse(script):
            message = "\n".join(f"Line {line}: {err}" for line, err in self.builder.errors)
            raise ValueError(message)

    @staticmethod
    def _overflow_message(info: OverflowInfo) -> str:
        return (
            "Geometry exceeds margin-safe 1:1 size.\n"
            f"Overflow: Left {info.overflow_left:.2f} mm, Right {info.overflow_right:.2f} mm, "
            f"Top {info.overflow_top:.2f} mm, Bottom {info.overflow_bottom:.2f} mm.\n"
            f"Auto-scale required: {info.scale_stroke * 100.0:.1f}%."
        )

    def render(self, silent: bool = False) -> None:
        try:
            self._parse_or_raise()
            settings = self._read_settings()
            renderer = Renderer(settings)
            overflow = renderer.overflow_info(self.builder)
            renderer.render(self.canvas, self.builder, show_markers=self.var_markers.get())

            if overflow.scale_stroke < 1.0:
                self.status.set(
                    "Rendered with auto-scale "
                    f"{overflow.scale_centerline * 100.0:.1f}% | "
                    f"Overflow L/R {overflow.overflow_left:.1f}mm, "
                    f"T/B {overflow.overflow_top:.1f}mm"
                )
            else:
                self.status.set("Rendered successfully (no overflow at 1:1)")
        except Exception as exc:
            self.canvas.delete("all")
            self.status.set("Render error")
            if not silent:
                messagebox.showerror("Render Error", str(exc))

    def export_svg(self) -> None:
        self._export("svg")

    def export_pdf(self) -> None:
        self._export("pdf")

    def _export(self, kind: str) -> None:
        try:
            self._parse_or_raise()
            settings = self._read_settings()
            renderer = Renderer(settings)
            overflow = renderer.overflow_info(self.builder)

            if overflow.scale_stroke < 1.0:
                ok = messagebox.askyesno(
                    "Overflow Warning",
                    self._overflow_message(overflow) + "\n\nExport anyway?",
                )
                if not ok:
                    return

            if kind == "svg":
                path = filedialog.asksaveasfilename(
                    title="Export SVG",
                    defaultextension=".svg",
                    filetypes=[("SVG files", "*.svg")],
                )
            else:
                path = filedialog.asksaveasfilename(
                    title="Export PDF",
                    defaultextension=".pdf",
                    filetypes=[("PDF files", "*.pdf")],
                )

            if not path:
                return

            exporter = Exporter(renderer)
            if kind == "svg":
                exporter.export_svg(self.builder, path)
            else:
                exporter.export_pdf(self.builder, path)

            self.status.set(f"{kind.upper()} exported: {path}")
        except Exception as exc:
            messagebox.showerror(f"Export {kind.upper()} Error", str(exc))

    def clear_editor(self) -> None:
        self.editor.delete("1.0", tk.END)
        self.canvas.delete("all")
        self.status.set("Cleared")
