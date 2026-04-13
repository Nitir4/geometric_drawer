            in (
                "coincident",
                "distance",
                "parallel",
                "perpendicular",
                "equal_length",
                "concentric",
                "tangent",
                "curve_tangent",
                "free_tangent",
                "angle_between",
                "equal_radius",
            )
            else 1
        )
    )
    if (
        not isinstance(refs, list)
        or len(refs) != count
        or not all(isinstance(r, str) for r in refs)
    ):
        raise ValueError(f"{kind} requires {count} reference(s).")
    entities = []
    for ref in refs:
        id = entity_id(ref)
        if id not in doc.entities or doc.entities[id].kind not in SUPPORTED:
            raise ValueError(
                f"Constraint reference must name supported sketch geometry: {ref}"
            )
        entities.append(doc.entities[id])
    if kind == "symmetry":
        point(doc, refs[0])
        point(doc, refs[1])
        if entities[2].kind != "line" or "@" in refs[2]:
            raise ValueError(
                "Symmetry needs two point references and a whole axis line."
            )
    elif kind in ("coincident", "distance"):
        for ref in refs:
            point(doc, ref)
    elif any("@" in r for r in refs):
        raise ValueError(f"{kind} takes whole entity IDs, not vertex references.")
    if kind in (
        "horizontal",
        "vertical",
        "length",
        "angle",
        "parallel",
        "perpendicular",
        "equal_length",
        "angle_between",
    ) and any(e.kind != "line" for e in entities):
        raise ValueError(f"{kind} requires straight lines.")
    if kind in ("radius", "concentric", "equal_radius") and any(
        e.kind not in ("circle", "arc") for e in entities
    ):
        raise ValueError(f"{kind} requires circles or arcs.")
    if kind in ("arc_start", "arc_sweep") and entities[0].kind != "arc":
        raise ValueError("Arc angle rules require an arc.")
    if kind in ("rx", "ry") and entities[0].kind != "ellipse":
        raise ValueError("Ellipse axis rules require an ellipse.")
    if kind in ("width", "height") and entities[0].kind != "rectangle":
        raise ValueError(f"{kind} requires a rectangle.")
    if kind == "tangent" and sorted(e.kind for e in entities) not in (
        ["circle", "line"],
        ["circle", "circle"],
    ):
        raise ValueError(
            "Tangent supports line/circle or two externally tangent circles."
        )
    if kind in ("length", "radius", "width", "height", "rx", "ry"):
        positive(c.get("value"))
    elif kind == "distance":
        if finite(c.get("value")) < 0:
            raise ValueError("Distance cannot be negative.")
    elif kind == "arc_sweep":
        if not EPS < abs(finite(c.get("value"))) <= 360:
            raise ValueError("Arc sweep must be nonzero and within +/-360 degrees.")
    elif kind in ("angle", "angle_between", "arc_start"):
        finite(c.get("value"))
    elif "value" in c:
        raise ValueError(f"{kind} does not take a numeric value.")
    if kind in ("curve_tangent", "free_tangent"):
        parameters = c.get("parameters")
        if (
            not isinstance(parameters, list)
            or len(parameters) != 2
            or any(not 0 <= finite(t) <= 1 for t in parameters)
        ):
            raise ValueError(
                "Curve tangent needs two normalized contact parameters in [0,1]."
            )
        if refs[0] == refs[1]:
            raise ValueError("Curve tangent requires two different curves.")
        try:
            from .cad_features import parameter_curve
        except ImportError:
            from cad_features import parameter_curve
        for e, t in zip(entities, parameters):
            _, v = parameter_curve(e)(t)
            if kind == "curve_tangent" and math.hypot(*v) <= EPS:
                raise ValueError(
                    "Curve tangent contact must have a regular derivative."
                )
    elif "parameters" in c:
        raise ValueError("Only curve tangent accepts contact parameters.")
    if kind == "fixed":
        state = c.get("state")
        if not isinstance(state, list) or len(state) != len(coordinates(entities[0])):
            raise ValueError("Fixed constraint has invalid saved coordinates.")
        for v in state:
            finite(v)
    elif "state" in c:
        raise ValueError("Only fixed constraints have saved coordinates.")


def residual(doc, c):
    k, refs = c["kind"], c["refs"]
    e = [doc.entities[entity_id(r)] for r in refs]
    value = c.get("value", 0)
    if k == "property_driver":
        try:
            from .cad_parameters import property_value
        except ImportError:
            from cad_parameters import property_value
        current = property_value(e[0], c["property"])
        if c["property"] in ("angle", "start", "hatch_angle"):
            delta = math.radians(current - value)
            return [math.sin(delta), math.cos(delta) - 1]
        return [current - value]
    if k == "symmetry":
        p, q = point(doc, refs[0]), point(doc, refs[1])
        a, b = e[2].vertices()
        v = sub(b, a)
        length = distance(a, b)
        u = tuple(x / length for x in v)
        delta = sub(p, a)
        projection = sum(x * y for x, y in zip(delta, u))
        reflected = tuple(a[i] + 2 * projection * u[i] - delta[i] for i in (0, 1))
        return list(sub(reflected, q))
    if k == "equal_radius":
        return [e[0].data["radius"] - e[1].data["radius"]]
    if k in ("arc_start", "arc_sweep"):
        current = e[0].data["start" if k == "arc_start" else "sweep"]
        if k == "arc_sweep":
            return [current - value]
        delta = math.radians(current - value)
        return [math.sin(delta), math.cos(delta) - 1]
    if k == "fixed":
        return [a - b for a, b in zip(coordinates(e[0]), c["state"])]
    if k in ("coincident", "distance"):
        a, b = (point(doc, r) for r in refs)
        return list(sub(a, b)) if k == "coincident" else [distance(a, b) - value]
    if k == "concentric":
        return [e[0].x - e[1].x, e[0].y - e[1].y]
    if k in ("radius", "width", "height", "rx", "ry"):
        return [e[0].data[k] - value]
    if k in ("curve_tangent", "free_tangent"):
        try:
            from .cad_features import parameter_curve
        except ImportError:
            from cad_features import parameter_curve
        (a, u), (b, v) = [
            parameter_curve(entity)(t) for entity, t in zip(e, c["parameters"])
        ]
        speed = math.hypot(*u) * math.hypot(*v)
        if speed <= EPS * EPS and k == "free_tangent":
            return [*sub(a, b), 1.0]
        if speed <= EPS * EPS:
            raise ValueError("Curve tangent contact became singular.")
        return [*sub(a, b), (u[0] * v[1] - u[1] * v[0]) / speed]
    if k == "tangent":
        if all(v.kind == "circle" for v in e):
            return [
                distance((e[0].x, e[0].y), (e[1].x, e[1].y))
                - sum(v.data["radius"] for v in e)
            ]
        line, circle = sorted(e, key=lambda v: v.kind == "circle")
        a, b = line.vertices()
        u, v = sub(b, a), sub((circle.x, circle.y), a)
        return [
            abs(u[0] * v[1] - u[1] * v[0]) / max(distance(a, b), EPS)
            - circle.data["radius"]
        ]
    a, b = e[0].vertices()
    u = sub(b, a)
    length = max(distance(a, b), EPS)
    if k == "horizontal":
        return [u[1]]
    if k == "vertical":
        return [u[0]]
    if k == "length":
        return [length - value]
    if k == "angle":
        # Directed angle: two residuals prevent accepting the opposite direction.
        t = math.radians(value)
        return [u[0] / length - math.cos(t), u[1] / length - math.sin(t)]
    a2, b2 = e[1].vertices()
    v = sub(b2, a2)
    length2 = max(distance(a2, b2), EPS)
    if k == "angle_between":
        theta = math.radians(value)
        return [
            (u[0] * v[1] - u[1] * v[0]) / (length * length2) - math.sin(theta),
            (u[0] * v[0] + u[1] * v[1]) / (length * length2) - math.cos(theta),
        ]
    if k == "equal_length":
        return [length - length2]
    if k == "parallel":
        return [(u[0] * v[1] - u[1] * v[0]) / (length * length2)]
    return [(u[0] * v[0] + u[1] * v[1]) / (length * length2)]


def solve(doc, *, apply=True):
    """Solve only the constrained geometry; locks are immutable parameters.

    Residual acceptance is absolute 1e-7 drawing units (angular residuals are
    dimensionless). Rank/DOF are local numerical diagnostics, not a uniqueness
    proof. A weak displacement preference selects nearby solutions; acceptance
    always checks the unregularized constraints, including contradictory ones.
    """
    import numpy as np
    from scipy.optimize import least_squares

    constraints = list(doc.constraints.values())
    for c in constraints:
        validate_constraint(doc, c)
    drivers = doc.driver_constraints()
    if not constraints and not drivers:
        return {
            "constraints": 0,
            "variables": 0,
            "rank": 0,
            "dof": 0,
            "max_residual": 0.0,
        }
    work = copy.copy(doc)
    work.constraints = copy.deepcopy(doc.constraints)
    work.constraints.update({c["id"]: c for c in drivers})
    constraints = list(work.constraints.values())
    work.entities = copy.deepcopy(doc.entities)
    ids = sorted({entity_id(r) for c in constraints for r in c["refs"]})
    fixed = {c["refs"][0]: c["state"] for c in constraints if c["kind"] == "fixed"}
    for id, state in fixed.items():
        if not doc.layers[work.entities[id].layer].locked:
            assign(work.entities[id], state)
    initial, lower, upper, slices = [], [], [], {}
    for id in ids:
        e = work.entities[id]
        if doc.layers[e.layer].locked or id in fixed:
            continue
        values = coordinates(e)
        slices[id] = slice(len(initial), len(initial) + len(values))
        initial.extend(values)
        lo, hi = [-1e12] * len(values), [1e12] * len(values)
        positive_indices = {
            "circle": [2],
            "arc": [2],
            "rectangle": [3, 4],
            "ellipse": [3, 4],
        }.get(e.kind, [])
        for i in positive_indices:
            lo[i] = EPS * 10
        if e.kind == "arc":
            sweep_rule = next(
                (
                    c["value"]
                    for c in constraints
                    if c["kind"] == "arc_sweep" and c["refs"] == [id]
                ),
                e.data["sweep"],
            )
            e.data["sweep"] = sweep_rule
            initial[slices[id].start + 5] = sweep_rule
            if sweep_rule > 0:
                lo[5], hi[5] = EPS * 10, 360.0
            else:
                lo[5], hi[5] = -360.0, -EPS * 10
        if e.kind == "ellipse" and len(values) == 7:
            if e.data.get("sweep", 360) > 0:
                lo[6], hi[6] = EPS * 10, 360.0
            else:
                lo[6], hi[6] = -360.0, -EPS * 10
        lower.extend(lo)
        upper.extend(hi)
    contact_slices = {}
    for c in constraints:
        if c["kind"] == "free_tangent":
            contact_slices[c["id"]] = slice(len(initial), len(initial) + 2)
            initial.extend(c["parameters"])
            lower.extend([0.0, 0.0])
            upper.extend([1.0, 1.0])
    if len(initial) > 2000:
        raise ValueError(
            "Constrained sketch exceeds 2000 solver coordinates; split it into smaller sketches."
        )

    def fun(values):
        for id, section in slices.items():
            assign(work.entities[id], values[section])
        for id, section in contact_slices.items():
            work.constraints[id]["parameters"] = list(values[section])
        return np.array([v for c in constraints for v in residual(work, c)])

    initial = np.array(initial, dtype=float)
    before = np.array([v for c in constraints for v in residual(doc, c)])
    fun(initial)
    initially_satisfied = (np.max(np.abs(before)) if len(before) else 0) <= 1e-7
    if len(initial):
        options = {
            "bounds": (lower, upper),
            "method": "trf",
            "x_scale": "jac",
            "ftol": 1e-12,
            "xtol": 1e-12,
            "gtol": 1e-12,
            "max_nfev": 500,
        }
        # A small movement preference avoids arbitrary large jumps in sketches
        # that intentionally retain free coordinates. It never relaxes acceptance.
        scale = max(1.0, float(np.ptp(initial)))

        line_lengths = {
            id: distance(values[:2], values[2:])
            for id, section in slices.items()
            if work.entities[id].kind == "line"
            for values in [initial[section]]
        }

        def preferred(values):
            equations = fun(values)
            stays = [
                1e-4
                * (distance(values[slices[id]][:2], values[slices[id]][2:]) - length)
                / scale
                for id, length in line_lengths.items()
            ]
            return np.concatenate((equations, 1e-4 * (values - initial) / scale, stays))

        seed = initial.copy()
        for c in constraints:
            if c["kind"] == "perpendicular":
                target = next((r for r in reversed(c["refs"]) if r in slices), None)
                if target:
                    other = next(r for r in c["refs"] if r != target)
                    a, b = work.entities[other].vertices()
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    norm = max(math.hypot(dx, dy), EPS)
                    values = seed[slices[target]].copy()
                    cx, cy = (values[0] + values[2]) / 2, (values[1] + values[3]) / 2
                    length = distance(values[:2], values[2:])
                    # Keep the closer of the two perpendicular orientations.
                    sign = (
                        1
                        if -dy * (values[2] - values[0]) + dx * (values[3] - values[1])
                        >= 0
                        else -1
                    )
                    vx, vy = (
                        -dy / norm * length * sign / 2,
                        dx / norm * length * sign / 2,
                    )
                    seed[slices[target]] = [cx - vx, cy - vy, cx + vx, cy + vy]
        from types import SimpleNamespace

        result = (
            SimpleNamespace(x=initial)
            if initially_satisfied
            else least_squares(preferred, seed, **options)
        )
        if np.max(np.abs(fun(result.x))) > 1e-7:
            # Parallel starting lines are a stationary point of the perpendicular
            # residual. A deterministic small seed breaks that symmetry.
            seed = result.x.copy()
            for c in constraints:
                if c["kind"] == "perpendicular":
                    target = next((r for r in reversed(c["refs"]) if r in slices), None)
                    if target:
                        section = slices[target]
                        values = seed[section].copy()
                        dx, dy = values[2] - values[0], values[3] - values[1]
                        values[2] += -0.1 * dy + 0.01 * dx
                        values[3] += 0.1 * dx + 0.01 * dy
                        seed[section] = values
            result = least_squares(preferred, seed, **options)
        if contact_slices and np.max(np.abs(fun(result.x))) > 1e-7:
            import itertools

            best = result
            best_error = float(np.max(np.abs(fun(best.x))))
            for pair in itertools.product((0.1, 0.3, 0.5, 0.7, 0.9), repeat=2):
                candidate = initial.copy()
                for section in contact_slices.values():
                    candidate[section] = pair
                attempt = least_squares(preferred, candidate, **options)
                error = float(np.max(np.abs(fun(attempt.x))))
                if error < best_error:
                    best, best_error = attempt, error
                if error <= 1e-9:
                    break
            result = best
        # Refine true equations without the movement preference when necessary.
        if not initially_satisfied and np.max(np.abs(fun(result.x))) > 1e-9:
            result = least_squares(fun, result.x, **options)
        errors = fun(result.x)
        # Compute rank of constraint equations, excluding displacement preference.
        columns = []
        for i in range(len(result.x)):
            h = 1e-5 * max(1.0, abs(result.x[i]))
            a, b = result.x.copy(), result.x.copy()
            a[i] += h
            b[i] -= h
            columns.append((fun(a) - fun(b)) / (2 * h))
        jacobian = np.array(columns).T
        fun(result.x)
        rank = int(np.linalg.matrix_rank(jacobian, tol=1e-7))
    else:
        errors, rank = fun(initial), 0
    worst = float(np.max(np.abs(errors))) if len(errors) else 0.0
    if worst > 1e-7 or not math.isfinite(worst):
        raise ValueError(
            f"Conflicting or unsolved constraints (residual {worst:.3g}); edit rolled back."
        )
    for id in ids:
        work.entities[id].validate()
    if apply and not initially_satisfied:
        for id in ids:
            if not doc.layers[doc.entities[id].layer].locked:
                doc.entities[id] = work.entities[id]
        for id in contact_slices:
            doc.constraints[id]["parameters"] = list(work.constraints[id]["parameters"])
    if initially_satisfied:
        worst = float(np.max(np.abs(before)))
    return {
        "constraints": len(constraints),
        "variables": len(initial),
        "rank": rank,
        "dof": len(initial) - rank,
        "max_residual": worst,
    }
