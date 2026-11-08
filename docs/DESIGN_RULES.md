# Design rules and the part library

## Board rules (defaults, per project)

| Rule | Default | Where it lives |
|---|---|---|
| Layers | 2 | `board.layers` |
| Thickness | 1.6 mm | `board.thickness` |
| Surface finish | HASL | `board.finish` |
| Signal trace width | 0.20 mm | `rules.trace_width` |
| Power/ground trace width | 0.30 mm | net class `power`/`ground` |
| Copper clearance | 0.15 mm | `rules.clearance` |
| Minimum trace | 0.15 mm | `rules.min_trace` |
| Minimum drill | 0.25 mm | `rules.min_drill` |
| Annular ring | 0.15 mm | enforced in DRC |
| Board-edge clearance | 0.30 mm | `rules.edge_clearance` |
| Via | 0.6 mm pad / 0.3 mm drill | `rules.via_diameter`, `via_drill` |
| Routing grid | 0.10 mm | `rules.grid` (advanced setting) |

These are deliberately conservative "cheap 2-layer fab" numbers (6/6 mil). A
project can change them: `circuit_create` takes the rules from the plugin's
settings, and the store keeps them per board so a re-run is reproducible.

**Net classes** are inferred from the net name:

- ground — `GND`, `AGND`, `PGND`, `DGND`, `VSS`, `0V`, `EARTH`
- power — `+3V3`, `3V3`, `5V`, `12V`, `VCC`, `VDD`, `VIN`, `VBUS`, `VBAT`, `VSYS`
- everything else is a signal

## Footprint library

`circuit_core/lib/footprints.py` builds land patterns procedurally, so the whole
library is a few hundred lines that can be reviewed, not a binary blob.

| Group | Footprints |
|---|---|
| Chip passives | 0402, 0603, 0805, 1206 |
| Discrete | SOT-23, SOT-23-5, SOT-23-6, SOD-123, SMA, SOT-223, TO-220, SIP-3 |
| ICs | SOIC-8/14/16, SOIC-28W, TSSOP-16/20, DIP-4, DIP-8, QFN-24 |
| Modules | Raspberry Pi Pico (40-pin), Arduino Nano (30-pin) |
| Connectors | 1×2…1×10 headers, 2×4, 2×5, JST-PH 2, USB-C 16-pin, screw terminal 2, barrel jack |
| Electromechanical | 6 mm tact switch, SRD relay, 12 mm buzzer, 3225 crystal, SMD electrolytic 6.3 mm |
| Mechanical | M3 mounting hole (NPTH) |

Each footprint carries pads (shape, size, drill, rotation), a body box for the 3D
view, a courtyard and pin names. `tests/test_library.py` asserts three
invariants that matter more than a datasheet-perfect land pattern:

1. no two pads of a footprint overlap;
2. the courtyard contains every pad (so the placer cannot create a collision);
3. every part's pin map covers exactly the footprint's pads.

### Adding a part

```python
# circuit_core/lib/footprints.py
_dual_row("SOIC-10", 10, 1.27, 5.4, 0.62, 1.55, (3.9, 6.2), 1.75)

# circuit_core/lib/parts.py
_part("opamp-dual", "Dual op-amp", "SOIC-8", "ic", "General purpose",
      pins={"1": "OUT1", "2": "IN1-", "3": "IN1+", "4": "GND",
            "5": "IN2+", "6": "IN2-", "7": "OUT2", "8": "VCC"},
      tags=["analog"], datasheet="https://…")
```

`verified=True` (the default) means the pin map follows the datasheet. Leave a
part out of the catalog rather than guessing its pinout: a wrong pin map is
worse than a missing part.

## How a board becomes files

```
netlist  ->  placement  ->  routing  ->  DRC  ->  export
            (greedy +      (A* grid   (geometry,  (Gerber,
             relax)         maze)      connectivity) Excellon,
                                                 KiCad, STEP, SVG)
```

A board is only "done" when `drc.ok` is true: no clearance, width, drill,
annular-ring or edge violations, and every net is a single copper island.

## Interpreting DRC output

```
net GND is unrouted (8 pads)                       → routing failed for GND; reroute
net SCL is only partly routed (12 items, 2 islands) → a trace stops short
clearance 0.08 mm < 0.15 mm between R2.1 (+3V3) and trace GND @12.3,8.4
                                                    → coordinates are mm from 0,0
U1 is placed outside the board outline               → placement vs board size
courtyard overlap: U2 and C4                         → parts collide
```

Fixes, in the order that usually works: give the board more area
(`circuit_place(fit=true)`), let the placer run again, then reroute. Hand-moving
a part into the middle of a channel makes routing worse, not better.
