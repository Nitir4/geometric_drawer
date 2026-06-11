from __future__ import annotations

import argparse
from pathlib import Path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Geometric Drawer — 2-D CAD workspace and command runner"
    )
    parser.add_argument(
        "--open", metavar="DRAWING", help="Open a native .gdraw, DXF or DWG drawing"
    )
    parser.add_argument("--script", metavar="FILE", help="Run a CAD command script")
    parser.add_argument(
        "--legacy", metavar="FILE", help="Import an original track script"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the drawing when running the script",
    )
    parser.add_argument("--save", metavar="FILE", help="Save a native editable drawing")
    parser.add_argument(
        "--export",
        metavar="FILE",
        action="append",
        default=[],
        help="Export .svg, .pdf, .dxf or .dwg; repeatable",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run commands and exports without opening a window",
    )
    args = parser.parse_args(argv)
    try:
        from .cad_document import Document
        from .cad_exchange import (
            export_dwg,
            export_dxf,
            export_pdf,
            export_svg,
            import_dwg,
            import_dxf,
        )
        from .cad_script import ScriptEngine, import_legacy
    except ImportError:
        from cad_document import Document
        from cad_exchange import (
            export_dwg,
            export_dxf,
            export_pdf,
            export_svg,
            import_dwg,
            import_dxf,
        )
        from cad_script import ScriptEngine, import_legacy
    try:
        doc = Document()
        if args.open:
            doc = (
                import_dxf(args.open)
                if Path(args.open).suffix.lower() == ".dxf"
                else import_dwg(args.open)
                if Path(args.open).suffix.lower() == ".dwg"
                else Document.load(args.open)
            )
        for warning in getattr(doc, "import_warnings", []):
            print("Import note: " + warning)
        if args.legacy:
            import_legacy(doc, Path(args.legacy).read_text())
        if args.script:
            ScriptEngine(doc).execute(
                Path(args.script).read_text(), replace=args.replace
            )
        if args.save:
            doc.save(args.save)
        for path in args.export:
            exporter = {
                ".svg": export_svg,
                ".pdf": export_pdf,
                ".dxf": export_dxf,
                ".dwg": export_dwg,
            }.get(Path(path).suffix.lower())
            if not exporter:
                raise ValueError("Export extension must be .svg, .pdf, .dxf or .dwg.")
            exporter(doc, path)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"CAD error: {exc}\n")
    if args.headless:
        print(f"{len(doc.entities)} entities; units {doc.units}")
        return
    import tkinter as tk

    try:
        from .cad_ui import App
    except ImportError:
        from cad_ui import App
    root = tk.Tk()
    prepared = bool(args.open or args.script or args.legacy)
    app = App(root, load_example=not prepared)
    if prepared:
        app.set_document(
            doc,
            args.save
            or (
                args.open
                if args.open
                and not args.script
                and not args.legacy
                and Path(args.open).suffix.lower() not in (".dxf", ".dwg")
                else None
            ),
            saved=bool(
                args.save
                or (
                    args.open
                    and not args.script
                    and not args.legacy
                    and Path(args.open).suffix.lower() not in (".dxf", ".dwg")
                )
            ),
        )
    root.mainloop()


if __name__ == "__main__":
    main()
