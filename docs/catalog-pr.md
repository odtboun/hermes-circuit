# Catalog submission — Circuit

Everything below is what the entry PR needs, in the order the guide asks for it.

- Entry file to add to `NousResearch/hermes-agent`: [`docs/catalog-entry.yaml`](catalog-entry.yaml)
  → save it as `plugin-catalog/circuit.yaml`.
- Pinned commit: `bd6168e5fec5b2cd63009a499a75b680f9ca0dbc` (the entry file in this
  repo is one commit later; the pin is the commit that contains the plugin, the
  README and the images).
- Validation, run against this tree:

```
$ hermes plugins validate ./circuit --install-deps
✓ manifest · ✓ manifest fields · ✓ requires_hermes · ✓ config schema
✓ requires_env · ✓ loadable · ✓ python dependencies · ✓ capability probe
✓ declared tools · ✓ declared hooks · ✓ declared middleware
✓ built-in tool collisions · ✓ security scan · ✓ no core override
✓ desktop surface
Validation passed.
```

## PR title

```
plugin-catalog: circuit — design real PCBs by talking to your agent
```

## PR description

**What it does.** Circuit turns a conversation into a fabrication-ready two-layer
PCB. The agent describes hardware in chat; the plugin holds the part library, adds
and connects parts, places them deterministically, autoroutes both layers, runs an
independent DRC, and exports a package a board house can build: RS-274X Gerbers
with X2 attributes, Excellon drills, a Ucamco job file, a KiCad 8 project, a STEP
AP214 model, a BOM with MPN columns, pick-and-place in two dialects, and three
generated documents (shopping list with distributor search links, wiring card,
board poster). The desktop half renders the board in 2D and 3D and shows those
documents in a Docs tab.

**Hermes surfaces used.**

- 15 tools via `ctx.register_tool` (listed in the entry's `capabilities`).
- A bundled skill (`circuit-design`) via `ctx.register_skill`, teaching the agent
  the workflow.
- Desktop plugin through the plugin SDK only: a sidebar route/page, and a
  `::circuit{board="…"}` transcript directive that renders the board inline in
  chat. No app markup is read or patched, no core functions are rebound, no
  `eval`/`import()` outside `@hermes/plugin-sdk` and `react`.
- A dashboard backend API (`dashboard/plugin_api.py`) served through the plugin
  host.

**Disclosure (rule 13).**

- **Network.** The plugin makes no network calls of its own. Two tools fetch a file
  when the user explicitly asks for it: `circuit_samples` downloads an open-source
  `.kicad_pcb` from its upstream URL, and `circuit_import url=…` downloads a board
  from a URL the user supplies. Nothing else leaves the machine: the engine, the
  router, the DRC and the viewer are local, and the shopping list's buy links are
  built as URL strings from part numbers — the plugin never contacts a distributor.
- **Filesystem.** Writes only under its own plugin data directory
  (`plugin-data/circuit/projects/<slug>/`): `board.json`, `view.json`, `exports/`.
  Reads only the plugin's own data, plus a KiCad file the user points it at.
- **Credentials.** None requested, none stored, no `requires_env`, no `oauth`.
- **Shell / processes.** None. No subprocesses, no background jobs, no daemons.
- **Telemetry.** None.
- **Third-party code.** None at runtime — the Python package has zero third-party
  dependencies, and the desktop bundle imports only `@hermes/plugin-sdk` and
  `react`.

**Screenshots.** In the entry (`image` + `screenshots`), pinned to the SHA: 3D view,
2D layer stackup, exploded view, and the three generated documents.

**Notes for the reviewer.**

- `subdir: circuit` — the plugin lives in a monorepo next to its own tests and CI.
- The engine is two-layer by design, and the README's FAQ states the routing cost
  plainly (a 39-part board takes about two and a half minutes at normal effort) so
  nobody installs it expecting a 300-part board to fall out of a prompt.
- Everything in the package is source: no binaries, no bytecode, no archives.
