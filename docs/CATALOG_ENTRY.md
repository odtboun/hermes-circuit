# Catalog submission (not opened yet)

The plugin is built and validated locally; the PR to `NousResearch/hermes-agent`
is intentionally **not** opened. This file holds everything that PR needs, so it
is a copy-paste job when the go-ahead comes.

## Pre-flight

```bash
hermes plugins validate ./circuit --install-deps   # what catalog CI runs
hermes plugins doctor ./circuit --ci
pytest
node tests/js/run.mjs
```

Requirements that are *not* met by a private repo: rule 1 needs a public
`https://` repository anyone can clone, and the entry pins a full 40-character
commit. Make the repo public and pin the commit you validated **before** opening
the PR.

## Entry file — `plugin-catalog/circuit.yaml`

```yaml
name: circuit
repo: https://github.com/odtboun/hermes-circuit
sha: <40-character commit sha you validated>
subdir: circuit
description: >-
  End-to-end PCB design in chat: a local 2-layer design engine (parts, nets,
  auto-placement, autorouting, DRC) exports RS-274X Gerbers, Excellon drills, a
  KiCad 8 project and a STEP AP214 model, and renders the board inline in the
  desktop UI in 2D and 3D.
maintainer: odtboun
tier: community
category: tools
requires_hermes: ">=0.21.5"
version: "1.0.0"
docs_url: https://github.com/odtboun/hermes-circuit
title: Circuit — PCB designer
platforms: [linux, macos, windows]
capabilities:
  provides_tools:
    - circuit_catalog
    - circuit_create
    - circuit_boards
    - circuit_board
    - circuit_add_part
    - circuit_connect
    - circuit_remove_part
    - circuit_place
    - circuit_route
    - circuit_check
    - circuit_export
    - circuit_view
  provides_hooks: []
  provides_middleware: []
  requires_env: []
screenshots:
  - https://raw.githubusercontent.com/odtboun/hermes-circuit/<sha>/docs/assets/hero.png
```

`image:` can point at the same file if a 2:1 banner is preferred.

## PR description — what it does

Circuit turns a natural-language description into a manufacturable 2-layer
board without leaving Hermes:

- **12 tools** map the design loop: browse the part library, create a board,
  add parts and nets, place, autoroute, run DRC, export, render.
- **A bundled skill** (`circuit:circuit-design`) teaches the model the workflow,
  the design rules, and how to read DRC output.
- **A local engine** does the actual work — no KiCad install, no EDA licence, no
  network call. Output is Gerber RS-274X, Excellon, a KiCad 8 `.kicad_pcb`, a
  STEP AP214 B-rep, BOM/pick-and-place, and a hashed manifest.
- **A desktop half** adds `::circuit{board="…"}` (inline 2D card), a `/circuit`
  workspace page (2D layer stackup + orbitable 3D board, nets, BOM, DRC, files)
  and a sidebar entry.

Surfaces used: `register_tool`, `register_skill`, `register_command`, the
Desktop plugin SDK (`TRANSCRIPT_DIRECTIVE_AREA`, `ROUTES_AREA`,
`SIDEBAR_NAV_AREA`, `PALETTE_AREA`, `ctx.rest`), and a dashboard-style
`plugin_api.py` mounted at `/api/plugins/circuit/`.

## Rule 13 disclosures (risky behaviour)

- **No network access at all.** No telemetry, no analytics, no remote fetches.
- **No shell commands and no subprocesses.** The engine is pure Python.
- **Writes** are confined to `<HERMES_HOME>/plugin-data/circuit/` (boards,
  view documents, exports) and nothing else on disk.
- **Backend routes** are read-only apart from `POST /boards/<slug>/rebuild`,
  which re-runs placement/routing/export for a board already in that directory.
  Every path is resolved and containment-checked; slugs are `[a-z0-9-]` only.
- **No stored credentials**, no `requires_env`, no OAuth, no vendor accounts.
- **Desktop half** uses only `@hermes/plugin-sdk` and `react`; no dynamic
  imports, no `eval`, no prototype patching, no DOM scraping, no script tags.
  It is opt-in (`defaultEnabled: false`) like every unified-package desktop half.
- **Unattended runs**: tools are synchronous and bounded (worst case ~1 min on a
  dense board); nothing waits on a human, so cron/gateway runs fail cleanly
  rather than hanging. The desktop page degrades to a "backend not reachable"
  panel when the plugin is disabled.
- **Known limitation disclosed to users**: footprint geometry is
  datasheet-derived and self-checked, not vendor-certified; the README and the
  bundled skill both tell the user to verify footprints before ordering.

## Dependency policy

No Python dependencies, no `pyproject.toml` requirements, nothing to quarantine.
The test-only extras (`pytest`, `httpx`) are not part of the plugin manifest.
