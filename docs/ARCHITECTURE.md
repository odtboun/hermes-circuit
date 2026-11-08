# Architecture and decisions

This document records why Circuit is built the way it is, including the parts of
the original brief that were dropped or reshaped, so they can be revisited.

## 1. The brief, and what changed

| Brief | Built | Why |
|---|---|---|
| Integrate the HeyPCB MCP server as the design engine | A self-contained engine in `circuit_core/` | The referenced `heypcb/mcp` repository does not exist, and a catalog plugin cannot depend on an untrusted remote service for the core function. A local engine is also what makes the plugin offline, auditable at a pinned commit, and deterministic. |
| tracespace for 2D | Hand-written canvas renderer in `desktop/plugin.js` | A desktop plugin may statically import only `@hermes/plugin-sdk` and `react` (catalog rule 8, enforced by `hermes plugins validate`). `tracespace`/`three` cannot be imported, and pulling them from a CDN at runtime is a self-updating remote-code path the catalog forbids. |
| Three.js for 3D | Same canvas, small perspective renderer | Same constraint. The board is a flat extrusion plus component boxes — painter-sorted polygons with one directional light — so a dependency-free renderer is appropriate rather than a compromise. |
| "Monitor the workspace for generated files" | The export step writes a stable, versioned tree and returns its manifest | Polling a workspace for files is racy and ambiguous when several boards exist. Tools return the artefact list; the UI reads the same store through a scoped REST namespace. |

Everything else from the brief survives: natural-language design, background
generation, production files, and an interactive view inside Hermes.

## 2. Engine layout

```
circuit_core/
  geom.py        points, pads (rect/round/oval/roundrect), distances, chamfering
  lib/           footprints.py (procedural land patterns) + parts.py (pin maps)
  project.py     board model, net classes, references, ERC, serialisation
  placement.py   deterministic greedy placer + relaxation
  router.py      two-tier grid maze router (A*, 2 layers, vias)
  drc.py         independent geometric checks + connectivity (union-find)
  layers.py      one description of copper/mask/silk/drill per layer
  fab/           gerber.py, kicad.py, step.py, svg.py
  compile.py     place → route → check → export → manifest
  store.py       per-profile project storage, slug validation
  templates.py   four starter netlists
```

The engine imports nothing outside the standard library. `hermes plugins
validate` imports the plugin with a bare interpreter, and the catalog forbids
catalog-style plugins from depending on Hermes internals; keeping the engine
pure is also what makes it testable in isolation.

## 3. Datum and units

- Millimetres everywhere, Y up, origin at the board's bottom-left corner.
- Gerber Y-up matches directly. KiCad is Y-down, so `fab/kicad.py` flips on the
  way out (including pad rotation signs).
- Angles are degrees, counter-clockwise, in the board frame.

One datum and one unit system removes the class of bug where the exporter, the
viewer and the DRC disagree about which way is up.

## 4. Routing: two-tier occupancy

A pure "blocked/free" grid cannot route a 2.54 mm header: two 1.7 mm pads leave
an 0.84 mm channel, and a 0.2 mm trace with 0.15 mm clearance needs 0.5 mm of it
— a single grid column with no slack. A pure "clearance-only" grid routes it but
lets traces graze foreign copper.

So each cell carries two thresholds:

- **hard** — pad or trace copper plus most of the clearance ring; A* may never
  enter another net's hard cells;
- **soft** — a ring just outside, traversable at a per-cell penalty.

Paths take the centre of a channel by default and squeeze only when there is no
alternative, and the independent DRC is the gate that certifies the result. When
DRC disagrees with the router, DRC wins and the board fails.

Routing is sequential, ordered by net span, with multi-source A* per net: the
net's growing tree is the source set and each remaining pad is a goal, so a
6-pin net becomes one tree rather than five unrelated segments. Vias are legal
only where both layers have room for the drill, the annular ring and the
clearance ring.

**Determinism:** no randomness, stable iteration order, integer cell indices. The
same board always produces the same routes, so a diff is a real change and a
test can assert the outcome.

## 5. DRC is the source of truth

`drc.check()` works on the final geometry, not the router's grid:

- pairwise copper clearance (pads, traces, vias, same layer, different nets);
- minimum trace width, drill, annular ring;
- board-edge clearance against the real outline;
- **connectivity**: every net must be one copper island, computed with
  union-find over touching items. This is what catches a "routed" board with a
  trace that stops 0.3 mm short of its pad.

The router optimises; the DRC certifies. That separation is why the test suite
asserts `drc.ok` on every starter design instead of trusting the router's own
report.

## 6. Exporters

- **Gerber** — RS-274X with a 4.6 metric format. Apertures are emitted before
  first use, pad rotation is handled as an aperture swap for 90° steps and as a
  region otherwise. `fab/gerber.py` also contains a reader; the tests round-trip
  every layer through it and check the Edge.Cuts bounding box equals the board.
- **Excellon** — metric, `TZ`, explicit tool table, plated and non-plated in
  separate files, hits deduplicated by position and diameter.
- **KiCad** — `.kicad_pcb` at file version `20240108` (KiCad 8) with real
  footprints, per-pad nets, tracks, vias and an Edge.Cuts outline, plus a
  minimal `.kicad_pro`. No schematic is synthesised: a fake schematic would be
  worse than none, so `netlist.json` is the machine-readable netlist.
- **STEP** — AP214 `MANIFOLD_SOLID_BREP`: the substrate is the board outline
  extruded through the stackup, each component body is its own prism. Faces are
  built from `PLANE` + `EDGE_LOOP` + `LINE` entities, so no CAD kernel is
  needed. The tests parse the file and assert no dangling entity references.

## 7. Desktop surface

`desktop/plugin.js` is a single ESM file:

- `TRANSCRIPT_DIRECTIVE_AREA` → `::circuit{board="…"}` renders a live 2D card
  (layer toggles, hover-a-pad-to-see-its-net, "Open board");
- `ROUTES_AREA` → the `/circuit` workspace page: board list, 2D/3D canvas,
  nets, BOM, DRC, files;
- `SIDEBAR_NAV_AREA` + `PALETTE_AREA` for discovery.

The page fetches `ctx.rest('/boards/…')` from `dashboard/plugin_api.py`, which is
mounted at `/api/plugins/circuit/` only when the plugin is enabled — so a
disabled plugin degrades to a clear "backend not reachable" panel rather than a
crash. Canvas panes observe their container with a `ResizeObserver` and resize
the backing store to `devicePixelRatio`.

## 8. Security posture

- No network calls, no shell commands, no telemetry, no self-updating code.
- Writes are confined to `<HERMES_HOME>/plugin-data/circuit/` and the export
  tree; slugs are validated against `[a-z0-9-]` and every path is resolved and
  containment-checked before a file is served.
- No core overrides, no monkey-patching, no `document` scraping: the plugin
  only uses `ctx.register*`, the SDK and documented Hermes imports.

## 9. Known limitations

- Two layers, no plane/pour, no impedance control, no BGA fanout.
- No schematic; the netlist is derived from the part pin maps.
- The router is sequential: on very dense boards a later net can fail where a
  rip-up-and-reroute engine would succeed. Failures are reported per net rather
  than hidden.
- Step resolution is 0.1 mm, so geometry is grid-aligned; the chamfer pass makes
  the result look like hand-routed 45° copper.
- Footprint geometry is datasheet-derived but not vendor-certified.
