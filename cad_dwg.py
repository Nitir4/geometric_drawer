"""Optional ODA/LibreDWG adapters; conversion never runs through a shell."""

import os
import shutil
import subprocess
from pathlib import Path


def libredwg_tools():
    configured = os.environ.get("CAD_LIBREDWG_BIN")
    if configured is not None:
        directory = Path(configured)
        reader, writer = directory / "dwgread", directory / "dxf2dwg"
        return (
            (str(reader), str(writer))
            if all(os.access(p, os.X_OK) and p.is_file() for p in (reader, writer))
            else None
        )
    reader, writer = shutil.which("dwgread"), shutil.which("dxf2dwg")
    if reader and writer:
        return reader, writer
    # Optional tools adjacent to the user's multi-repository checkout.
    directory = Path(__file__).resolve().parents[2] / "tools" / "libredwg" / "bin"
    reader, writer = directory / "dwgread", directory / "dxf2dwg"
    return (
        (str(reader), str(writer))
        if all(os.access(p, os.X_OK) and p.is_file() for p in (reader, writer))
        else None
    )


class LibreDWG:
    def __init__(self, tools):
        self.reader, self.writer = tools
        self.notes = []

    def convert(self, source, dest, **kwargs):
        source, dest = Path(source).resolve(), Path(dest).resolve()
        if dest.suffix.lower() == ".dwg":
            command = [
                self.writer,
                "--as",
                "r2000",
                "-v0",
                "-o",
                str(dest),
                str(source),
            ]
        else:
            command = [self.reader, "-v0", "-O", "DXF", "-o", str(dest), str(source)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("LibreDWG conversion exceeded 60 seconds.") from exc
        if result.returncode or not dest.is_file():
            message = (result.stderr or result.stdout)[-2000:]
            raise ValueError(
                f"LibreDWG conversion failed (exit {result.returncode}): {message}"
            )
        if dest.suffix.lower() == ".dxf":
            # LibreDWG 0.14 can assign handle 0 to an empty ENDBLK record.
            # Removing only that invalid identity lets ezdxf allocate a handle;
            # all geometry and reference tags remain untouched and audited later.
            lines = dest.read_bytes().decode("latin1").splitlines()
            output, record, repaired = [], "", False
            for i in range(0, len(lines), 2):
                if i + 1 >= len(lines):
                    raise ValueError("LibreDWG produced truncated DXF tags.")
                code, value = lines[i].strip(), lines[i + 1].strip()
                if code == "0":
                    record = value
                if code == "5" and value == "0" and record == "ENDBLK":
                    repaired = True
                    continue
                output.extend(lines[i : i + 2])
            if repaired:
                dest.write_bytes(("\r\n".join(output) + "\r\n").encode("latin1"))
                self.notes.append(
                    "Reassigned an invalid empty-block handle emitted by LibreDWG 0.14; geometry was retained and the resulting DXF audited."
                )
        if dest.suffix.lower() == ".dwg" and dest.read_bytes()[:6] != b"AC1015":
            raise ValueError("LibreDWG did not produce an R2000 DWG file.")


def converter():
    from ezdxf.addons import odafc

    if odafc.is_installed():
        return odafc
    tools = libredwg_tools()
    if tools:
        return LibreDWG(tools)
    raise ValueError(
        "DWG requires ODA File Converter or GNU LibreDWG (dwgread and dxf2dwg). Configure ezdxf [odafc-addon] unix_exec_path / win_exec_path, or set CAD_LIBREDWG_BIN to the tools directory. DXF works without a converter."
    )
