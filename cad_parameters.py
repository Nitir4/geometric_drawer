"""Persisted expression graphs and numeric design drivers, with declaration units."""

import ast
import copy
import keyword
import math
import operator

try:
    from .cad_geometry import EPS, angle, distance, finite, mul, sub
except ImportError:
    from cad_geometry import EPS, angle, distance, finite, mul, sub

UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
FUNCTIONS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "abs": abs,
    "radians": math.radians,
    "degrees": math.degrees,
}
CONSTANTS = {"pi": math.pi, "tau": math.tau}
OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def expression_tree(expression):
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or len(expression) > 2048
    ):
        raise ValueError("Expression must contain 1–2048 characters.")
    try:
        tree = ast.parse(expression, mode="eval").body
    except SyntaxError as exc:
        raise ValueError("Invalid numeric expression.") from exc
    if sum(1 for _ in ast.walk(tree)) > 80:
        raise ValueError("Numeric expression is too complex.")
    return tree


def evaluate(expression, names):
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return finite(n.value)
        if isinstance(n, ast.Name) and n.id in names:
            return finite(names[n.id])
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return finite(visit(n.operand) * (1 if isinstance(n.op, ast.UAdd) else -1))
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 12:
                raise ValueError("Exponent magnitude is limited to 12.")
            return finite(OPS[type(n.op)](a, b))
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in FUNCTIONS
            and len(n.args) == 1
            and not n.keywords
        ):
            return finite(FUNCTIONS[n.func.id](visit(n.args[0])))
        raise ValueError(
            "Use numbers, named parameters, arithmetic or supported math functions."
        )

    try:
        return finite(visit(expression_tree(str(expression))))
    except (OverflowError, ZeroDivisionError, TypeError) as exc:
        raise ValueError("Expression is undefined or exceeds numeric limits.") from exc


def dependencies(expression):
    tree = expression_tree(expression)
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and id(n) not in called and n.id not in CONSTANTS
    }


def property_kind(e, key):
    if key.startswith("v") and key.endswith((".x", ".y")):
        index = key[1:-2]
        if (
            not index.isdigit()
            or e.kind not in ("line", "polyline", "bezier", "region")
            or int(index) >= len(e.vertices())
        ):
            raise ValueError("Invalid driven vertex property.")
        return "length"
    pose = {
        "point",
        "line",
        "rectangle",
        "circle",
        "arc",
        "ellipse",
        "region",
        "text",
        "dimension",
        "radial_dimension",
        "angular_dimension",
    }
    if key in ("x", "y", "angle") and e.kind in pose:
        return "angle" if key == "angle" else "length"
    allowed = {
        "line": {"length"},
        "rectangle": {"width", "height"},
        "circle": {"radius"},
        "arc": {"radius", "start", "sweep"},
        "ellipse": {"rx", "ry", "start", "sweep"},
        "region": {"spacing", "hatch_angle"},
        "text": {"height"},
        "dimension": {"offset", "text_height"},
        "radial_dimension": {"offset", "text_height"},
    }
    if key not in allowed.get(e.kind, set()):
        raise ValueError(f"Unsupported driven property {e.kind}.{key}.")
    return "angle" if key in ("start", "sweep", "hatch_angle") else "length"


def property_value(e, key):
    property_kind(e, key)
    if key.startswith("v") and key.endswith((".x", ".y")):
        return e.vertices()[int(key[1:-2])][0 if key[-1] == "x" else 1]
    if e.kind == "line":
        a, b = e.vertices()
        if key in ("x", "y"):
            return a[0 if key == "x" else 1]
        if key == "length":
            return distance(a, b)
        if key == "angle":
            return angle(sub(b, a))
    return (
        getattr(e, key)
        if key in ("x", "y", "angle")
        else e.data.get(key, 360 if key == "sweep" else 0)
    )


def set_property(e, key, value):
    property_kind(e, key)
    if key.startswith("v") and key.endswith((".x", ".y")):
        index, axis = int(key[1:-2]), 0 if key[-1] == "x" else 1
        p = list(e.vertices()[index])
        p[axis] = value
        if e.kind == "region":
            for ring in e.data["rings"]:
                if index < len(ring):
                    ring[index] = e.local(p)
                    break
                index -= len(ring)
        else:
            e.data["points"][index] = e.local(p)
    elif e.kind == "line" and key in ("x", "y"):
        setattr(e, key, getattr(e, key) + value - property_value(e, key))
    elif e.kind == "line" and key in ("length", "angle"):
        a, b = e.vertices()
        if key == "length":
            if value <= EPS:
                raise ValueError("Driven line length must be positive.")
            e.data["points"][1] = tuple(
                e.data["points"][0][i]
                + mul(
                    sub(e.data["points"][1], e.data["points"][0]),
                    value / distance(a, b),
                )[i]
                for i in (0, 1)
            )
        else:
            e.angle += value - property_value(e, key)
    elif key in ("x", "y", "angle"):
        setattr(e, key, value)
    else:
        e.data[key] = value


class Parameters:
    def parameter_values(self, units=None):
        units = units or self.units
        if (
            units not in UNIT_MM
            or not isinstance(self.parameters, dict)
            or len(self.parameters) > 128
        ):
            raise ValueError("Invalid parameter table/units; limit is 128 parameters.")
        remaining = dict(self.parameters)
        physical = {}
        kinds = {}
        while remaining:
            ready = []
            for name, spec in remaining.items():
                if (
                    not isinstance(name, str)
                    or not name.isidentifier()
                    or keyword.iskeyword(name)
                    or name in FUNCTIONS
                    or name in CONSTANTS
                    or len(name) > 80
                    or not isinstance(spec, dict)
                    or set(spec) != {"expression", "kind", "units"}
                    or spec["kind"] not in ("length", "angle", "scalar")
                    or spec["units"] not in UNIT_MM
                ):
                    raise ValueError("Invalid parameter definition.")
                deps = dependencies(spec["expression"])
                if deps - self.parameters.keys():
                    raise ValueError("Parameter references an unknown name.")
                if deps <= physical.keys():
                    ready.append(name)
            if not ready:
                raise ValueError("Cyclic parameter expressions.")
            for name in ready:
                spec = remaining.pop(name)
                declaration = UNIT_MM[spec["units"]]
                names = {
                    k: v / declaration if kinds[k] == "length" else v
                    for k, v in physical.items()
                }
                value = evaluate(spec["expression"], dict(CONSTANTS, **names))
                kinds[name] = spec["kind"]
                physical[name] = (
                    value * declaration if spec["kind"] == "length" else value
                )
        return {
            k: finite(v / UNIT_MM[units] if kinds[k] == "length" else v)
            for k, v in physical.items()
        }

    def set_parameter(self, name, expression, kind="length", *, units=None):
        with self.transaction("Edit parameter"):
            self.parameters[name] = {
                "expression": str(expression),
                "kind": kind,
                "units": units or self.units,
            }

    def remove_parameter(self, name):
        with self.transaction("Remove parameter"):
            del self.parameters[name]  # unresolved references reject the whole edit

    def binding_kind(self, b):
        if (
            not isinstance(b, dict)
            or set(b) != {"target", "id", "property", "expression", "units"}
            or b["units"] not in UNIT_MM
        ):
            raise ValueError("Invalid driver definition.")
        target, id, key = b["target"], b["id"], b["property"]
        if target == "entity" and id in self.entities:
            if self.feature_for(id):
                raise ValueError("Drive the linked source, or detach the result first.")
            return property_kind(self.entities[id], key)
        if target == "constraint" and id in self.constraints and key == "value":
            kind = self.constraints[id]["kind"]
            if kind in ("length", "radius", "width", "height", "distance", "rx", "ry"):
                return "length"
            if kind in ("angle", "angle_between", "arc_start", "arc_sweep"):
                return "angle"
        if (
            target == "feature"
            and id in self.features
            and key in self.features[id]["params"]
        ):
            if self.features[id]["kind"] == "block":
                if key in ("x", "y"):
                    return "length"
                if key == "angle":
                    return "angle"
                if key == "scale":
                    return "scalar"
            if key in ("amount", "radius", "tolerance"):
                return "length"
            if key == "vertex":
                return "scalar"
        raise ValueError("Invalid/missing numeric driver target.")

    def binding_value(self, b):
        kind = self.binding_kind(b)
        value = evaluate(
            b["expression"], dict(CONSTANTS, **self.parameter_values(b["units"]))
        )
        return finite(
            value * UNIT_MM[b["units"]] / UNIT_MM[self.units]
            if kind == "length"
            else value
        )

    def bind(self, id, key, expression, *, target="entity", units=None):
        with self.transaction("Bind expression"):
            self.bindings = [
                b
                for b in self.bindings
                if (b["target"], b["id"], b["property"]) != (target, id, key)
            ]
            self.bindings.append(
                {
                    "target": target,
                    "id": id,
                    "property": key,
                    "expression": str(expression),
                    "units": units or self.units,
                }
            )

    def unbind(self, id, key, *, target="entity"):
        with self.transaction("Unbind expression"):
            self.bindings = [
                b
                for b in self.bindings
                if (b["target"], b["id"], b["property"]) != (target, id, key)
            ]

    def prune_bindings(self):
        tables = {
            "entity": self.entities,
            "constraint": self.constraints,
            "feature": self.features,
        }
        self.bindings = [
            b
            for b in self.bindings
            if b["target"] in tables and b["id"] in tables[b["target"]]
        ]

    def apply_parameters(self, *, check=False):
        self.parameter_values()
        if not isinstance(self.bindings, list) or len(self.bindings) > 1000:
            raise ValueError("Driver table exceeds 1000 bindings.")
        seen = set()
        for b in self.bindings:
            kind = self.binding_kind(b)
            value = self.binding_value(b)
            key = b["target"], b["id"], b["property"]
            if key in seen:
                raise ValueError("Duplicate expression driver.")
            seen.add(key)
            if b["target"] == "entity":
                e = self.entities[b["id"]]
                current = property_value(e, b["property"])
                delta = current - value
                if kind == "angle" and b["property"] != "sweep":
                    delta = (delta + 180) % 360 - 180
                if abs(delta) <= 1e-7:
                    continue
                if check:
                    raise ValueError("Stale expression-driven geometry.")
                if self.layers[e.layer].locked:
                    raise ValueError(
                        "Unlock the driven layer before changing parameters."
                    )
                new = copy.deepcopy(e)
                set_property(new, b["property"], value)
                self.entities[e.id] = new
            else:
                table = (
                    self.constraints if b["target"] == "constraint" else self.features
                )
                data = (
                    table[b["id"]]
                    if b["target"] == "constraint"
                    else table[b["id"]]["params"]
                )
                if data.get(b["property"]) != value:
                    if check:
                        raise ValueError("Stale expression-driven value.")
                    data[b["property"]] = value

    def driver_constraints(self):
        return [
            {
                "id": f"@driver{i}"
                + "_" * (1 + max((len(k) for k in self.constraints), default=0)),
                "kind": "property_driver",
                "refs": [b["id"]],
                "property": b["property"],
                "value": self.binding_value(b),
            }
            for i, b in enumerate(self.bindings)
            if b["target"] == "entity"
        ]
