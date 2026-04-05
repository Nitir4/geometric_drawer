Enable Object snap, choose Line, and place its first point. Move near the desired
foot/contact point and click: perpendicular supports finite straight edges and
circle/arc/ellipse/Bezier normals; tangent supports circles/arcs/ellipses and
finite cubic Beziers. A circle/ellipse tangent needs an external start.
Candidates outside a finite edge/arc or requiring a zero-length segment are
excluded. The snap readout shows the winning mode. These modes default off and
all enabled object snaps compete by cursor distance. Exact object snaps override
Ortho; grid/Ortho apply when no object snap is captured. Hidden/preview entities
are excluded. Locked reference geometry can supply snaps without being edited.

Snapping places coordinates; it does not add persistent driving constraints.
Enable **Nearest** to capture the closest actual point on a supported finite
curve without a preceding point. Bezier object snaps use actual endpoints and
the parameter midpoint; control grips remain editable but are not curve points.
**Tangents** constructs common circle/arc tangent segments. **Extension** enables
nearby infinite-line or full-arc support snaps and their intersections. These
virtual supports affect snapping only; source geometry is unchanged.
Use `examples/curves.cad` or `examples/drafting-snaps.cad` as a scene.
Contacts use bounded polynomial equations, including repeated tangent roots,
rather than display tessellation. Overlapping/coincident curves have no isolated
intersection snap. Floating-point elimination is not an exact-arithmetic completeness
guarantee for very close roots/extreme scales; generated-polyline topology checks
do not certify exact topology below the chosen offset tolerance.
Python can use `cad_snap.reference_points(entity, start, tangent=True)` or
`perpendicular=True`; results are `(point, mode)` pairs. Create ordinary document
lines from the desired point, then use native save/code/export as usual.

## Programming

```text
UNITS mm
LAYER parts color=#007f84 width=0.25
LET pitch=30
RECT plate x=100 y=50 width=40 height=20 angle=90 layer=parts
CIRCLE hole x=15 y=35 radius=5 layer=parts
ARRAY hole count=4 dx=pitch
LINE edge x=0 y=0 length=100 angle=30
DIM length entity=edge offset=8
MOVE plate dx=10 dy=5
ROTATE plate angle=45 px=100 py=50
```

Other commands: POINT, ARC (`radius`, `start`, signed `sweep`), ELLIPSE (`rx`,
`ry`, optional `start`/`sweep`), POLY (`points="0,0;20,0;20,20"`, `closed=true`), BEZIER (four control
points), TEXT (`text="Part A"`, `height=3`), RDIM, ADIM, COPY, SCALE, MIRROR,
OFFSET, TRIM, EXTEND, FILLET, CHAMFER, DELETE, USE and LAYER.
`FILLET a b radius=5 x=-10 y=10` and `CHAMFER a b distance=5 x=-10 y=10`
select a crossing corner; provide both x/y or omit both. Python uses
`doc.corner("a", "b", 5, pick=(-10, 10))` (set `fillet=False` for chamfer).
See `examples/corners.cad` for separated and crossing legs.
The in-app Guide describes their parameters. Examples are in `examples/`.

Numeric expressions support variables, arithmetic, pi/tau, sqrt, abs,
sin/cos/tan and radians/degrees. Trigonometric functions use radians. Quote
expressions containing spaces. This command language does not execute arbitrary
Python. The separate Python API supports normal Python loops and functions:

```python
from cad_document import Document
from cad_exchange import export_dxf

drawing = Document()
with drawing.transaction("Mounting plate"):
    plate = drawing.rectangle(100, 50, 40, 20, angle=90, id="plate")
    for x in (15, 45, 75, 105):
        drawing.circle(x, 35, 5)
    edge = drawing.line(0, 0, length=120)
    drawing.dimension(edge, offset=-8)
drawing.save("plate.gdraw")
export_dxf(drawing, "plate.dxf")
```

Use public document methods, or a transaction plus validation for low-level
entity changes. An entity stores its local geometry and X/Y/orientation pose.
The canvas only projects those values into pixels.

## Command line and files

```bash
python main.py --headless --script examples/plate.cad --save plate.gdraw --export plate.dxf --export plate.svg --export plate.pdf
python main.py --open plate.gdraw
python main.py --headless --open plate.gdraw --script edits.cad --save edited.gdraw
```

- **Native `.gdraw`:** versioned JSON preserving editable entities, poses,
  layers, constraints and associative measurements. Writes version 2 and loads
  versions 1 and 2. Native save replaces the file atomically.
- **DXF:** planar model-space geometry with explicit mm/cm/m/in units. Supports
  points, lines, polylines (including bulges), rectangles, circles/arcs, full
  ellipses, multi-span cubic splines and text. Nested blocks and block arrays
  expand into editable geometry. MTEXT becomes editable plain text with a
  fidelity note. Aligned/mirrored TEXT becomes font outlines. Dimensions/leaders
  become standalone geometry. Filled polygons export as solid HATCH; imported
  solid and line-pattern hatches preserve compound boundaries, holes and islands. Rational/non-cubic
  splines become polylines with an explicit approximation
  note (`import_dxf(path, curve_tolerance=0.01)`, in drawing units). Normal, outer
  and ignore island styles are respected. Gradient/double pattern hatches, infinite
  entities and unsupported/3-D content fail atomically.
  Layer styles are retained; per-entity style overrides are not represented.
  Constraints and native dimension associations are retained in `.gdraw`/code,
  rather than reconstructed from DXF annotations.
- **DWG:** File → Import DXF / DWG and Export DWG, or CLI `--open`/`--export`.
  Uses optional [ODA File Converter](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html)
  or [GNU LibreDWG](https://www.gnu.org/software/libredwg/). ODA is preferred when
  installed; otherwise `dwgread` and `dxf2dwg` are found on PATH, in
  `CAD_LIBREDWG_BIN`, or the adjacent `github-review/tools/libredwg/bin` directory.
  The local GNU tools are built and verified for an R2000 primitive round trip;
  they are separate from this repository and need installing on another machine.
  GNU export uses R2000 (AC1015). Complex/proxy objects may need ODA; conversion
  notes identify the backend and any narrow intermediate repair.
  Configure its executable in ezdxf's `[odafc-addon]` section as `unix_exec_path`
  (Linux/macOS) or `win_exec_path` (Windows). Conversion uses temporary files and
  publishes exports only on success. Missing conversion tools produce an error
  without changing the existing drawing. Converted geometry follows DXF rules.
- **SVG/PDF:** analytic curves and physical dimensions, with 5 mm margins.
  Hidden layers and construction geometry are omitted. Print at Actual size /
  100%; printer fit-to-page changes physical scale. The Python PDF exporter
  optionally accepts an explicit `print_scale`; GUI export is 1:1. Unicode text
  embeds a TrueType font (DejaVu Sans/Arial where installed, or `CAD_FONT_PATH`).
  Missing glyphs cause an actionable error; complex-script shaping is not
  implemented by the CAD text model.
- **Legacy tracks:** File → Import legacy track, or `--legacy track.txt`, accepts
  the original POINT/LINE/CONNECT/CIRCLE/ARC language. Original track modules
  remain available; their old auto-fit exporter is separate from CAD export.

## Driving sketch constraints

Use the **Constraints** tab to choose a rule, references and a numeric value.
Whole-entity references use IDs (`edge`, `hole`); vertex references use zero-based
indices (`edge@0`, `edge@1`, `plate@2`). A circle's bare ID is its centre. Use
**Use selected entities** to fill IDs, then **Add constraint**. Select a saved
constraint to update its driving value or remove it. Constraints are saved,
undoable, and enforced for manual, control-panel, script and Python edits.

Rules: fixed geometry; horizontal/vertical lines; line length/directed angle;
circle/arc radius; rectangle width/height; coincident vertices; point distance;
parallel/perpendicular/equal-length lines; concentric circles/arcs; line-circle
or external circle-circle tangency. Tangency uses complete line/circle supports.
An arc's centre/radius can be constrained; arc endpoint/sweep constraints are
not included. Polygon/Bezier vertices can be coincident or a set distance apart.

```text
POINT origin x=0 y=0
LINE edge length=40
CONSTRAINT anchor kind=fixed refs=origin
CONSTRAINT join kind=coincident refs=edge@0,origin
CONSTRAINT level kind=horizontal refs=edge
CONSTRAINT width kind=length refs=edge value=80
DRIVE width value=120
# UNCONSTRAIN width removes that saved rule.
```

Python equivalents are `doc.constrain("length", ["edge"], 80, id="width")`,
`doc.set_constraint_value("width", 120)`, `doc.remove_constraint("width")` and
`doc.constraint_report()`. Wrap related creations in `doc.transaction()` to
solve them together. Locked layers are constants. A fixed rule captures the
current coordinates; copies/arrays start unconstrained. Deletion removes rules
that reference the deleted geometry. Physical unit conversion scales driving
lengths and fixed targets, while angles stay in degrees.

Free sketches use a small movement/length preference to find a nearby solution.
Every accepted rule must still satisfy its unregularized residual to `1e-7`
drawing units (dimensionless for direction rules). Conflicts or nonconvergence
roll back the entire edit. This is a local nonlinear solve, so a failure can mean
poor initialization as well as an impossible sketch. The displayed DOF is a
local Jacobian-rank diagnostic, not a uniqueness proof. Up to 2000 variable
coordinates are supported per constrained document; split larger sketches.
To resize driven geometry, change the rule's value. Manual changes are projected
back onto the rules. Measurements remain annotations; driving rules are listed
separately in the Constraints tab.

Remaining scope: planar CAD, with the documented constraints and editing tools.
Exact analytic ellipse/Bezier offsets, arbitrary constraints, gradient/double
pattern hatches, 3-D and CAM toolpaths are not implemented. Native Windows/macOS acceptance and installers
have not been exercised. DWG interoperability depends on the external converter.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
CAD_GUI_TESTS=1 python -m pytest tests -q
```

The second command runs core/CLI/exchange checks; native GUI tests are opt-in.
The last command opens real Tk windows and exercises mouse/keyboard interactions.
Linux/X11 (including XWayland) screenshot tests use Pillow and libX11 to capture
only the application window. Native package installers and Windows/macOS GUI
acceptance are separate from Linux verification.

Architecture: `cad_geometry.py` provides analytic entities; `cad_document.py`
owns transactions and operations; `cad_script.py` translates commands;
`cad_exchange.py` handles files; `cad_ui.py` handles user interactions; `main.py`
launches the GUI or runs headless jobs. Project learning resources and observed
test evidence live outside the repository in `../../../docs/geometric_drawer/`.

This project is geometric 2-D CAD only. Circuit simulation, electrical symbols,
experiment data import and plotting are outside its scope. Older native CAD
drawings with empty probe records or false wire flags still load. Drawings with
electrical probes, devices or active circuit wiring are rejected without modifying
the source file; the previous combined implementation is archived externally.

## Linked features and curve contact constraints

```python
from geometric_drawer import Document

doc = Document()
source = doc.circle(0, 0, 10)
result = doc.offset(source, 2)        # linked by default
rule = doc.constrain("radius", [source], 15)  # result radius becomes 17
doc.detach_feature(result)           # explicit independent editing
```

Use `doc.update_feature(result, amount=3)` to change the offset distance and
`doc.detach_feature(result)` to make its result editable independently. Feature
sources can drive dependent offsets. Native files and Drawing to code preserve
this dependency graph, including source frames and component ID counters.
Cycles and invalid geometry roll back atomically; split/merge topology regenerates. Deleting a source removes linked descendants; detached
geometry survives. Copying a result creates ordinary geometry. Edit sources to
move/rotate/scale an assembly, or detach to edit a finished result directly.

`curve_tangent` enforces common position and parallel nonzero tangent vectors at
two **specified normalized contact parameters**. It supports lines, circles/arcs,
ellipses and cubic Beziers. It is a local driving rule; the solver does not search
for unspecified contact locations. **free_tangent** adds two bounded solver
variables for the contact locations, together with the same position and tangent
equations. Its parameter entries are initial guesses; solved values are saved.
In Constraints, choose the rule and enter `t1,t2` in [0,1].
A circle/ellipse parameter traverses one revolution; an arc traverses its sweep;
a Bezier uses its usual cubic parameter; a line traverses start to end.

```text
OFFSET source distance=2 tolerance=0.01 linked=true
DRIVE_FEATURE f1 amount=3
DETACH f1
ROUND outline radius=2 tolerance=0.01 vertex=1
TANGENTS circle_a circle_b kind=external
CLEANOFFSET outline distance=1 join=round tolerance=0.01 regions=true
CONSTRAINT contact kind=curve_tangent refs=ellipse,line parameters=0.25,0.5
CONSTRAINT free_contact kind=free_tangent refs=other_ellipse,other_line parameters=0.1,0.7
```

Feature IDs appear in Drawing to code (`FEATURE ...`); APIs also accept an output
entity ID. `examples/features.cad` demonstrates the new controls.

## Installable package

From a checkout, `python -m pip install .` installs the package and the
`geometric-drawer` command. Then run `geometric-drawer`, or
`python -m geometric_drawer`. Both accept the existing `--headless`, `--script`,
`--save` and repeatable `--export` options. Tkinter remains an operating-system
prerequisite. `python -m pip install build && python -m build` makes a wheel and
source distribution; examples ship in the package. The CI definition runs core
checks/builds on Linux, Windows and macOS, and native Tk checks on Linux/Xvfb.
Windows/macOS GUI acceptance and native installers are still unverified.

## Compound regions and numerical behavior

A region stores one simple exterior ring and nonoverlapping interior hole rings,
all in local coordinates. Nested islands are separate regions. Create regions in
the numeric panel using a JSON `rings` array, through `REGION` in the editor, or
with `doc.region(outer, holes, x=..., y=..., angle=...)`. Vertex grips edit both
exterior and holes; orientation/placement work like other entities. Invalid edits
roll back. Material clicks select the region; hole interiors stay empty.

`hatch=solid` fills material. `lines` and `cross` use `spacing` and `hatch_angle`;
patterns follow object pose, scale, units and reflection. Python/native/code can
also define `custom` families as `[angle, baseXY, offsetXY, dash_lengths]`, with
positive ink, negative gaps and zero dots. Custom definitions are preserved by
DXF HATCH exchange. SVG/PDF use even-odd compound paths, and Tk uses hole-aware
triangulation. Line patterns are clipped to material, with a small ULP-sized
margin to stabilize boundary-collinear lines. Stored rings and solid fills are
unchanged. Preview/export budgets cap hatch lines/dashes at 20000; increase spacing
if exceeded. Preview reports the limit and retains boundaries; export fails clearly.

Near-parallel line determinants fall back to exact rational evaluation of the
represented binary inputs. Circle contacts use ULP-aware classification and a
scaled Heron formula; curved fillets solve in a translated local frame. Bezier
coefficients use successive differences, and close crossing roots avoid an extra
critical-point contact. These improve tested difficult cases; binary floats still
limit geometry far from the origin, polynomial contacts remain numerical, and
local nonlinear solving does not prove existence or completeness. Keep small
features near a sensible origin and choose tolerances in your drawing units.

See `examples/advanced.cad` for compound hatches, splitting cleanup and free tangency.

## Parametric design, material operations and general trimming

The **Parameters** tab persists named expressions and drivers. Choose a name,
expression, kind (`length`, `angle`, `scalar`) and expression units, then **Set
parameter**. Dependencies update automatically. Cycles, unknown names and invalid
geometry reject the whole edit. Angles are in degrees; use `sin(radians(angle))`
for trigonometry. Length definitions and bindings retain their declaration units
when the drawing changes units. The table displays values in current drawing units.
Expressions declare an output kind; there is no automatic dimensional analysis.

Choose a target category and ID, a property and an expression, then **Bind
expression**. Targets include entity dimensions/pose, world vertex coordinates
(`v0.x`, `v1.y`), a constraint's `value`, or numeric feature parameters such as
`amount`, `radius` and `tolerance`. Linked output geometry is driven through its
sources or feature. Numeric and manual edits obey drivers; **Unbind expression**
restores independent editing. Conflicts with fixed constraints or locked geometry
roll back. All definitions survive native files, generated code and Undo/Redo.

```text
PARAM radius expression=5 kind=length units=mm
PARAM diameter expression=2*radius kind=length units=mm
CIRCLE hole radius=5
BIND hole property=radius expression=diameter/2 units=mm
```

```python
from geometric_drawer import Document

doc = Document()
hole = doc.circle(20, 20, 5)
doc.set_parameter("radius", "5", units="mm")
doc.bind(hole, "radius", "radius", units="mm")
doc.set_parameter("radius", "8", units="mm")  # the hole grows to 8 mm
```

Select closed shapes in order and use **Union**, **Difference** or
**Intersection**. Difference keeps the first shape minus all later shapes.
Inputs can be regions, rectangles, closed polylines, circles or full ellipses.
Results preserve every material island and hole as compound regions. Linked
operations retain construction sources and regenerate by default; use **Detach**
or disable Linked for independent results. Empty linked intersections remain
editable by feature ID and can regenerate after source movement. Curved boundaries
are sampled using Curve tol; Boolean results are polygonal approximations.

```text
DIFFERENCE plate hole_a hole_b tolerance=0.01 linked=true
UNION island_a island_b tolerance=0.01
INTERSECTION shape_a shape_b tolerance=0.01
```

`doc.boolean([a, b], "difference", tolerance=.01)` returns all output IDs.
A shared edge or point has zero material area and produces no region.

**Trim** now handles finite ellipses, cubic Beziers, open/closed polylines,
rectangles and region boundaries. Select target then cutter, and set Pivot X/Y to
pick the portion to remove. Curves retain their analytic type; cubic subcurves use
exact reparameterized controls. Removing an interior portion of an open path can
return two entities. Trimming a closed rectangle/polyline opens its boundary;
trimming a region retains closed material, holes and islands. A straight region
cutter uses its infinite support. Other general path cuts use finite crossings.
Existing primitive line/circle/arc operations retain their endpoint-pick semantics.
Topology changes require removing affected vertex bindings and sketch constraints.
Conflicting drivers are rejected rather than silently reversing the trim.

**Extend** handles open polyline ends, finite elliptical arcs and cubic Beziers
as well as lines/circular arcs. Cubic extension is a bounded polynomial
extrapolation: `EXTEND curve boundary=edge x=10 y=5 limit=4` searches normalized
parameters `[-4, 5]`. The default is 4; maximum 32. No crossing within that range
rejects the edit. This is a search bound, not a physical length or proof that no
intersection exists elsewhere. Closed material has no endpoint to extend.

Ellipses accept `start` and signed `sweep` in the control panel, Python and DSL.
Finite ellipses have endpoint grips, clipped snaps, analytic bounds and SVG/PDF/DXF
exchange. DXF stores counterclockwise traversal, so a clockwise ellipse imports
with reversed traversal of the same locus. Native/code files retain direction.

New sketch rules: `angle_between` is the directed angle from the first line to the
second; `symmetry` references two points/vertices then an axis line; `arc_start`
and `arc_sweep` drive the local arc start and signed extent; `equal_radius`, `rx`
and `ry` drive circular equality and ellipse axes. Arc references `@0`, `@1`, `@2`
mean centre, start and end. Region vertices flatten exterior first, then holes.
Region fixed/point rules use the ordinary solver; final invalid rings reject edits.
Local rank/DOF and residual diagnostics do not prove global uniqueness.

Open `examples/parametric.cad` to try a parameter-driven plate with linked holes,
analytic ellipse trimming and the broader driving constraints.

## Reusable blocks, groups and custom hatch editing

The **Assemblies** tab captures selected geometry as a reusable block definition,
relative to a base point. **Insert block** adds a linked instance with its own X/Y,
angle, positive uniform scale, insertion layer and optional local reflection.
Drag any member to move the entire instance; its orange assembly handle rotates
it. Move/Copy/Rotate/Scale/Mirror and arrays retain the definition link. Numeric
instance placement and feature expression drivers use the same model.

**Edit block geometry** creates editable local copies. Modify them using ordinary
numeric/mouse/code controls, then **Save definition geometry** to update every
instance and remove the edit copies as one undoable operation. Added selected
geometry becomes new templates; deleted copies retire templates. Stable template
keys preserve member IDs across reordering. Removed/retyped templates retire linked
descendants and freeze dimensions. **Explode instance** keeps independent geometry;
remove a definition only after every instance is deleted or exploded. Definitions
capture geometry, including patterns, but freeze annotation references and flatten
nested instances; source constraints and expressions are not cloned into templates.
Every instance uses its insertion layer. Native/code saves retain the library and
links; external DXF/DWG/SVG/PDF exports retain expanded visible geometry.

Groups are flat selection sets. **Group selected geometry** creates one;
**Select group**, picking a member and Shift-selection treat the group together.
Transforms/copies/deletion expand all members atomically, including locked members.
**Ungroup geometry** retains entities. A group is not a rigid constraint: saved
constraints/drivers may project individual members differently. Linked block
instances are rigid placements; their members are edited through the definition.
An entity belongs to at most one group. Block instances can belong to a group.

```text
BLOCK bracket refs=plate,pin x=0 y=0
INSERT bracket id=left x=20 y=30 angle=45 scale=2 mirror=false
INSERT bracket id=right x=80 y=30
DRIVE_FEATURE right x=100 angle=30 scale=1.5
GROUP annotations label datum
EXPLODE left
```

GROUP member IDs are separate positional tokens; BLOCK refs uses a comma-separated list.

```python
doc.define_block("bracket", [plate, pin], base=(0, 0))
instance = doc.insert_block("bracket", x=20, y=30, angle=45, scale=2)
doc.transform([instance], dx=10)       # placement changes once for all members
doc.group("assembly", doc.features[instance]["outputs"] + [label])
doc.transform(["assembly"], dy=20, copy_entities=True)
```

The **Patterns** tab edits custom region families without writing JSON. Load the
selected region, then add/update/remove families using angle, base X/Y, offset X/Y
and comma-separated dashes. These values are in the region's local coordinates and
current drawing units. A positive dash draws, a negative dash leaves a gap and zero
places a dot; an empty sequence is continuous. The offset must separate neighboring
parallel lines. Preview clips against the exterior and all holes. **Apply custom
pattern** updates the editable region; linked results must be detached or edited
through their source/definition. Draft preview changes do not modify geometry.
Custom definitions persist through native/code, transformations and supported DXF
HATCH exchange. Dense previews show at most 3,500 segments; the 20,000-segment kernel
budget remains enforced. Up to 32 families and 128 dash entries per family are allowed.

```text
PATTERN plate name=DASHES data="[[0,[0,0],[0,3],[2,-1]]]"
```

Try `examples/assemblies.cad` for shared patterned blocks, reflection, placement
drivers and grouped annotations.
