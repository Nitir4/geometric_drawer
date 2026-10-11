"""CAD-only scope and safe compatibility with the previous native format."""

import json
import subprocess
import sys

import pytest

from cad_document import Document
from cad_geometry import distance
from cad_script import ScriptEngine, ScriptError, document_script


def test_older_geometric_native_metadata_loads_without_losing_constraints(tmp_path):
    original = Document()
    original.line(0, 0, length=40, id="edge")
    original.constrain("length", ["edge"], 40, id="size")
    old = original.snapshot()
    old["probes"] = []
    old["entities"][0]["data"]["circuit_wire"] = False
    path = tmp_path / "old.gdraw"
    path.write_text(json.dumps(old))
    contents = path.read_bytes()
    loaded = Document.load(path)
    assert loaded.snapshot() == original.snapshot()
    assert path.read_bytes() == contents
    clone = Document()
    ScriptEngine(clone).execute(document_script(loaded))
    assert clone.snapshot() == original.snapshot()
    loaded.set_constraint_value("size", 60)
    assert distance(*loaded.entities["edge"].vertices()) == pytest.approx(60)


@pytest.mark.parametrize("content", ["probe", "wire", "device"])
def test_native_electrical_content_fails_without_rewriting_input(tmp_path, content):
    original = Document()
    original.line(0, 0, length=20, id="edge")
    state = original.snapshot()
    if content == "probe":
        state["probes"] = [{"id": "reading", "target": "edge", "quantity": "voltage"}]
    elif content == "wire":
        state["entities"][0]["data"]["circuit_wire"] = True
    else:
        state["entities"].append(
            {"id": "R", "kind": "resistor", "data": {"length": 20, "value": 1000}}
        )
    path = tmp_path / "electrical.gdraw"
    path.write_text(json.dumps(state))
    contents = path.read_bytes()
    with pytest.raises(ValueError, match="unsupported|Unsupported"):
        Document.load(path)
    assert path.read_bytes() == contents


@pytest.mark.parametrize(
    "command",
    [
        "RESISTOR R value=1000",
        "VSOURCE V value=5",
        "ISOURCE I value=1",
        "GROUND G",
        "WIRE w x2=10 y2=0",
        "PROBE p target=edge quantity=voltage",
        "UNPROBE p",
    ],
)
def test_removed_commands_are_atomic(command):
    drawing = Document()
    drawing.line(0, 0, length=20, id="edge")
    before = drawing.snapshot()
    with pytest.raises(ScriptError, match="Unknown command"):
        ScriptEngine(drawing).execute("MOVE edge dx=10\n" + command)
    assert drawing.snapshot() == before


def test_electrical_metadata_cannot_enter_through_python_api():
    drawing = Document()
    before = drawing.snapshot()
    with pytest.raises(ValueError, match="Circuit metadata"):
        drawing.line(0, 0, 20, 0, circuit_wire=True)
    assert drawing.snapshot() == before


@pytest.mark.parametrize(
    "option", ["--dc", "--data", "--sweep", "--plot", "--results", "--x", "--y"]
)
def test_removed_cli_options_are_rejected(option):
    result = subprocess.run(
        [sys.executable, "main.py", "--headless", option],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
