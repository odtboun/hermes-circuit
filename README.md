# Circuit — AI PCB designer for Hermes

Describe a circuit board in chat. Hermes designs it, routes it, checks it, and
hands you fabrication files — then draws the board inline in the conversation.

![A routed 2-layer board: 3D model on the left, 2D layer stackup on the right](docs/assets/hero.png)

```
You:  build me a Pico sensor hub with a BME280 and an OLED header, powered from 5 V

Hermes: → circuit_create(template="pico-sensor-hub")
        → circuit_export()
        → ::circuit{board="pico-sensor-hub"}

        72 × 50 mm, 2 layers, 13 parts, 8 nets — DRC clean.
        Gerbers, drills, KiCad 8 project and STEP model in exports/.
```

Everything runs locally: a deterministic 2-layer PCB compiler written in plain
Python (no KiCad install, no EDA license, no cloud service), plus a desktop
viewer that renders the same files the fab will receive.

---

## What you get

| | |
|---|---|
| **Gerbers** | RS-274X: F/B copper, F/B soldermask, F/B silkscreen, Edge.Cuts |
| **Drills** | Excellon, plated and non-plated, metric with tool table |
| **KiCad 8** | `.kicad_pcb` + `.kicad_pro` with real footprints, nets, tracks, vias |
| **STEP** | AP214 B-rep: substrate plus every component body, for enclosure work |
| **Assembly** | `bom.csv`, `pos.csv` (pick-and-place), `netlist.json` |
| **Preview** | `preview.svg`, interactive `preview.html`, and the in-chat 2D/3D view |
| **Trust** | `manifest.json` with a SHA-256 for every artefact, plus the DRC report |

## How it is put together

```
┌──────────────────────────── Hermes agent ────────────────────────────┐
│  12 circuit_* tools          bundled skill "circuit-design"           │
└───────────────┬──────────────────────────────────────────────────────┘
                │
┌───────────────▼─────────────┐        ┌──────────────────────────────┐
│ Design engine (Python)      │        │ Desktop half (SDK-only JS)   │
│  parts + footprints         │        │  ::circuit{board="…"} card   │
│  netlist / ERC              │◀──────▶│  /circuit workspace page     │
│  autoplace + autorouter     │  REST  │  2D layer stackup (canvas)   │
│  DRC + connectivity         │        │  3D orbit view (canvas)      │
│  Gerber / Excellon / KiCad  │        │  nets, BOM, DRC, files       │
│  STEP / SVG / manifest      │        └──────────────────────────────┘
└─────────────────────────────┘
```

- **Engine** — `circuit/circuit_core/`: geometry, curated parts, deterministic
  placement, a two-tier grid maze router, an independent DRC that certifies the
  final copper, and the exporters. No third-party runtime dependencies.
- **Agent surface** — `circuit/tools.py` + `schemas.py`: twelve tools that map
  the design loop (catalog → create → add/connect → place → route → check →
  export → view), and a bundled skill that teaches the model the workflow.
- **Desktop half** — `circuit/desktop/plugin.js`: one SDK-only ESM file that
  registers the transcript directive, the workspace page and a sidebar entry.
  Its renderer is hand-written canvas code because the plugin sandbox allows
  only `@hermes/plugin-sdk` and `react` imports — which also keeps it offline.
- **Backend** — `circuit/dashboard/plugin_api.py`: read-only board/file routes
  under `/api/plugins/circuit/` plus a rebuild endpoint.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the trade-offs and the
things this deliberately does not do.

## Install (local development)

```bash
git clone https://github.com/odtboun/hermes-circuit
ln -s "$PWD/hermes-circuit/circuit" "$HERMES_HOME/plugins/circuit"
hermes plugins enable circuit
```

Restart the desktop app (or the gateway) once so the Python backend mounts, then
open **Settings → Plugins → Circuit** and flip the desktop half on. The viewer
appears as **Circuit** in the sidebar, as a ⌘K command, and inline whenever the
agent emits `::circuit{board="…"}`.

## Use

Ask for hardware, or drive the tools directly:

```
circuit_catalog(query="i2c sensor")      # what exists, and its pin numbers
circuit_create(title="…", template="pico-sensor-hub")
circuit_add_part(part="ne555", nets={"1": "GND", "8": "+5V"})
circuit_connect(connections=[["U1","GP15","R1","1"]])
circuit_place()                          # or explicit positions
circuit_route()                          # autoroute + DRC
circuit_check()                          # ERC + DRC verdict
circuit_export()                         # everything above, written to disk
circuit_view()                           # returns the chat directive
```

Boards live under Hermes's plugin data directory:
`<HERMES_HOME>/plugin-data/circuit/projects/<slug>/exports/`.

### Starter designs

`pico-blinky`, `pico-sensor-hub`, `nano-relay`, `power-5v` — each one a real
netlist that is placed, routed and DRC-checked in a single call.

## Scope, honestly

**Supported:** 2-layer boards, 0.1 mm routing grid, 0.15 mm minimum clearance,
0.2 mm signal / 0.3 mm power traces, SMD and through-hole, module carriers
(Raspberry Pi Pico, Arduino Nano), 0402–1206 passives, SOIC/TSSOP/SOT/QFN-24,
2.54 mm headers, common connectors.

**Not supported:** BGA or fine-pitch fanout, controlled impedance, more than two
layers, copper pours/planes, schematic capture, panelisation. Projects that need
those should be finished in KiCad — the exported `.kicad_pcb` opens there.

**Verify before you order:** footprint geometry comes from the bundled library
and is checked for self-consistency (pads never overlap, courtyards enclose
pads, drill and annular-ring rules pass), but every part should be confirmed
against its supplier's datasheet. This is a design assistant, not a certified
layout service.

## Development

```bash
pytest                      # 51 Python tests: engine, exports, tools, API
node tests/js/run.mjs       # desktop plugin: registration, 3D facets, canvas draws
hermes plugins validate ./circuit
hermes plugins doctor ./circuit --ci
```

Layout:

```
circuit/               the installable plugin (plugin.yaml + __init__.py)
  circuit_core/        engine: geom, lib/, project, placement, router, drc, fab/
  dashboard/           FastAPI routes mounted at /api/plugins/circuit/
  desktop/plugin.js    the desktop half (single file, SDK-only)
  skills/              bundled skill the agent loads
tests/                 pytest suite + the Node harness
docs/                  architecture, design rules, catalog entry
```

## License

MIT
