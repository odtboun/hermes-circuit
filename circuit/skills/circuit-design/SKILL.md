---
name: circuit-design
description: Design a PCB with the Circuit plugin — netlist, place, route, check, export Gerbers/KiCad/STEP, and show it in chat.
version: 1.0.0
author: Circuit
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pcb, hardware, circuit, gerber, kicad, step, electronics]
---

# Designing a PCB with Circuit

You have a full PCB toolchain in the `circuit_*` tools. The user describes
hardware in chat; you produce a routed 2-layer board and real fabrication files:
RS-274X Gerbers, Excellon drills, a KiCad 8 project, a STEP AP214 model, BOM and
pick-and-place.

## The loop (do not skip steps)

1. **`circuit_catalog`** — read the part library and templates before inventing
   anything. Only ids returned here exist. Each part lists its **pin numbers**.
2. **`circuit_create`** — `template="pico-sensor-hub"` (etc.) gives a complete
   working design in one call: created, placed, routed, checked. For something
   custom, create an empty board with `width`/`height`.
3. **`circuit_add_part`** — `part` id + `nets` as `{pin_number: net_name}`, e.g.
   `{"1": "+3V3", "2": "GND"}`. Pin **numbers**, not pin names, are the keys
   (`circuit_board` shows the mapping after the fact).
4. **`circuit_connect`** — join pins across parts: `[["U1","GP15","R1","1"],
   ["R1","2","D1","2"]]`. The first pin that already has a net donates its name.
5. **`circuit_place`** — no arguments = deterministic auto-placement. Manual
   `positions` are also accepted. Use `fit: true` if parts do not fit the outline.
6. **`circuit_route`** — autoroute + DRC. Read `failed` and `drc` carefully.
7. **`circuit_check`** — ERC (dangling nets, missing power/ground, courtyard
   overlaps) plus DRC. Fix errors before exporting.
8. **`circuit_export`** — writes everything and returns the file list.
9. **`circuit_view`** — returns a transcript directive; put the `directive` value
   **alone on its own line** in your reply so the board renders inline:

   ```
   ::circuit{board="pico-blinky"}
   ```

## Design rules the engine enforces

- **2 layers only**, 1.6 mm FR4 by default, HASL, green mask.
- **Trace/clearance defaults**: 0.2 mm signal, 0.3 mm power/ground, 0.15 mm
  clearance, 0.6/0.3 mm vias. Net names matching `GND|VSS|AGND` and
  `+3V3|5V|VCC|VDD|VIN|VBUS` get the wider power class automatically.
- **Routing grid 0.1 mm**, so 2.54 mm headers with 1.7 mm pads route reliably.
- **Curated footprints**: 0402–1206 passives, SOT-23/223, SOIC, TSSOP, QFN-24,
  DIP, 2.54 mm headers, USB-C, JST, screw terminals, relays, crystals,
  mounting holes, plus Raspberry Pi Pico and Arduino Nano module carriers.
- **No BGA / no fine-pitch fanout**, no schematic capture, no copper pour, no
  differential-pair impedance control. If the user needs those, say so plainly
  and suggest a module-based approach (e.g. carry a Pico instead of an RP2040).

## Choosing parts

- Prefer **modules on 2.54 mm headers** (`pico`, `nano`) and **breakout headers**
  (`bme280-brk`, `mpu6050-brk`, `hcsr04-brk`) over bare fine-pitch ICs: they
  route, they are reflow-free, and the pin maps in the catalog are verified.
- Passives: `r-0603`/`r-0805`, `c-0805`, `cp-6.3` for bulk, `led-0805`
  (pin 1 = cathode), `d-sod123` (pin 1 = cathode).
- Power: `ams1117-33` (pin 1 GND, 2 VOUT, 3 VIN, 4 = tab VOUT), `lm7805`
  (1 IN, 2 GND, 3 OUT), `buck-in-1x4` for module bucks.
- Logic level matters: Pico IO is 3.3 V, Nano is 5 V. Do not drive a 3.3 V
  part from a Nano without a level shifter.
- Decoupling is not optional: 100 nF per IC/module supply pin, 10 µF bulk per
  rail. Add them without being asked — reviewers expect it.

## Reading results

- `route.failed` lists nets with no path. Usual causes: the board is too small,
  parts are piled on one side, or a connector sits in the middle. Fix with
  `circuit_place` (auto again after moving the outline) or a bigger board — do
  not hand-wave a partial route.
- `drc.errors` names the exact culprit, e.g.
  `net GND is unrouted (8 pads)` or
  `clearance 0.08 mm < 0.15 mm between R2.1 (+3V3) and trace GND @12.3,8.4`.
  Coordinates are millimetres from the board's bottom-left corner.
- `erc.warnings` about dangling nets usually mean a pin you forgot to connect.
- A board is only "done" when `drc.ok` is true and every net routes.

## Presenting the result

Reply with: what the board is, the key parts and nets, the size, the DRC verdict,
then the directive. After that list the important files:

- `gerbers/*.gbr` + `*-gerbers.zip` — upload this zip to JLCPCB/PCBWay/OSHPark
- `gerbers/*.drl` — plated and non-plated drill files
- `kicad/<board>.kicad_pcb` — open in KiCad 8 to inspect or edit
- `<board>.step` — mechanical envelope for enclosure design
- `bom.csv`, `pos.csv` — sourcing and assembly

Always state the limits honestly: footprints come from the bundled library and
should be checked against the supplier's datasheet before ordering; there is no
schematic, so the netlist in `netlist.json` is the source of truth.

## Cost and turnaround (say it only if asked)

The plugin itself is free and local. Board cost is whatever the fab charges for
a 2-layer board of that size — quote the user the board dimensions and layer
count so they can price it; do not invent numbers.

## Failure handling

- `no boards yet` → call `circuit_create` first.
- `unknown part` → `circuit_catalog` with a search term; ids are lowercase and
  hyphenated (`r-0805`, not `R0805`).
- `reference R4 already used` → omit `ref` and let the engine assign one.
- `board is corrupt` → the project JSON is unreadable; create a new board rather
  than editing the file by hand.
- Desktop half missing → the inline directive renders as plain text. Use the
  `preview_directive` (an HTML file) or tell the user to enable **Circuit** in
  Settings → Plugins.
