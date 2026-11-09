"""Footprint library.

Each footprint is a plain dict so it can be serialised, diffed and extended
without touching engine code:

    {
      "name": "0603",
      "desc": "0603 chip (1.6 x 0.8 mm)",
      "pads": [{"num","name","kind","shape","x","y","w","h","rot","drill","layer","r"}],
      "pin_names": {"1": "1", "2": "2"},
      "body": {"w","h","z","color"},
      "courtyard": {"w","h"},          # centred rectangle
      "tags": ["passive"],
    }

Pad coordinates are local to the footprint origin (the part's centre), Y up.
``kind`` is ``smd`` (one copper layer), ``tht`` (drilled, both layers) or
``npth`` (non-plated hole, no net).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

FOOTPRINTS: Dict[str, dict] = {}


def geom_pad_bbox(pad: dict) -> Tuple[float, float, float, float]:
    """Axis-aligned bbox of a pad in footprint-local coordinates."""
    w, h, rot = pad["w"], pad["h"], pad.get("rot", 0.0)
    if pad["shape"] == "round":
        half = w / 2.0
        return (pad["x"] - half, pad["y"] - half, pad["x"] + half, pad["y"] + half)
    r = math.radians(rot)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    hw = (w * c + h * s) / 2.0
    hh = (w * s + h * c) / 2.0
    return (pad["x"] - hw, pad["y"] - hh, pad["x"] + hw, pad["y"] + hh)


def _pad(num: str, x: float, y: float, w: float, h: float, shape: str = "rect",
         drill: float = 0.0, layer: str = "top", name: str = "", rot: float = 0.0,
         r: float = 0.0) -> dict:
    kind = "smd"
    if drill and shape == "npth":
        kind, shape = "npth", "round"
    elif drill:
        kind = "tht"
    return {
        "num": str(num), "name": name or str(num), "kind": kind, "shape": shape,
        "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4),
        "rot": rot, "drill": drill, "layer": layer if kind != "tht" else "both",
        "r": r,
    }


def _register(name: str, desc: str, pads: List[dict], body: dict, courtyard: dict,
              pin_names: Optional[Dict[str, str]] = None, tags: Optional[List[str]] = None,
              silk: Optional[List[dict]] = None) -> dict:
    # A courtyard must contain every pad plus a placement margin, whatever the
    # hand-written size said — otherwise the placer can overlap two parts.
    half_w = half_h = 0.0
    for pad in pads:
        poly = geom_pad_bbox(pad)
        half_w = max(half_w, abs(poly[0]), abs(poly[2]))
        half_h = max(half_h, abs(poly[1]), abs(poly[3]))
    courtyard = {
        "w": round(max(courtyard["w"], 2 * half_w + 0.4), 3),
        "h": round(max(courtyard["h"], 2 * half_h + 0.4), 3),
    }
    fp = {
        "name": name,
        "desc": desc,
        "pads": pads,
        "pin_names": pin_names or {p["num"]: p["name"] for p in pads},
        "body": body,
        "courtyard": courtyard,
        "tags": tags or [],
        "silk": silk or [],
    }
    FOOTPRINTS[name] = fp
    return fp


def _chip(name: str, body_w: float, body_h: float, pad_w: float, pad_h: float,
          gap: float, height: float, tags: List[str]) -> dict:
    x = gap / 2.0 + pad_w / 2.0
    pads = [_pad("1", -x, 0, pad_w, pad_h), _pad("2", x, 0, pad_w, pad_h)]
    return _register(
        name, f"{name} chip ({body_w} x {body_h} mm)", pads,
        {"w": body_w, "h": body_h, "z": height, "color": "passive"},
        {"w": body_w + 0.9, "h": max(pad_h, body_h) + 0.6},
        tags=tags,
    )


# --------------------------------------------------------------------------- #
# passives
# --------------------------------------------------------------------------- #
_chip("0402", 1.0, 0.5, 0.55, 0.60, 0.40, 0.45, ["passive", "smd"])
_chip("0603", 1.6, 0.8, 0.90, 0.95, 0.70, 0.55, ["passive", "smd"])
_chip("0805", 2.0, 1.25, 1.00, 1.20, 0.90, 0.65, ["passive", "smd"])
_chip("1206", 3.2, 1.6, 1.20, 1.45, 1.50, 0.75, ["passive", "smd"])

# --------------------------------------------------------------------------- #
# discrete semiconductors
# --------------------------------------------------------------------------- #
def _sot23(pin_count: int = 3, row: float = 2.2, pitch: float = 0.95, pad_w: float = 0.6,
           pad_h: float = 1.1, name: str = "SOT-23", body=(2.9, 1.6, 1.1)) -> dict:
    pads: List[dict] = []
    if pin_count == 3:
        pads.append(_pad("1", -pitch / 2, -row / 2, pad_w, pad_h))
        pads.append(_pad("2", pitch / 2, -row / 2, pad_w, pad_h))
        pads.append(_pad("3", 0.0, row / 2, pad_w, pad_h))
    else:
        per_side = (pin_count + 1) // 2
        y0 = -(per_side - 1) * pitch / 2.0
        for i in range(per_side):
            pads.append(_pad(str(i + 1), -row / 2, y0 + i * pitch, pad_h, pad_w))
        for i in range(pin_count - per_side):
            pads.append(_pad(str(per_side + i + 1), row / 2, y0 + i * pitch, pad_h, pad_w))
    return _register(name, f"{name} {pin_count}-pin", pads,
                     {"w": body[0], "h": body[1], "z": body[2], "color": "ic"},
                     {"w": body[0] + 1.2, "h": body[1] + 1.6}, tags=["smd", "ic"])


_sot23(3, 2.2, 0.95, name="SOT-23")
_sot23(5, 2.4, 0.95, name="SOT-23-5", body=(3.0, 1.7, 1.1))
_sot23(6, 2.4, 0.95, name="SOT-23-6", body=(3.0, 1.7, 1.1))

_register(
    "SOD-123", "SOD-123 diode", [
        _pad("1", -1.1, 0, 0.9, 1.0), _pad("2", 1.1, 0, 0.9, 1.0),
    ],
    {"w": 2.7, "h": 1.6, "z": 1.1, "color": "ic"},
    {"w": 3.6, "h": 2.0}, tags=["smd", "diode"],
)

_register(
    "SOT-223", "SOT-223 (1.5 A regulator)", [
        _pad("1", -2.3, -3.05, 1.2, 2.0),
        _pad("2", 0.0, -3.05, 1.2, 2.0),
        _pad("3", 2.3, -3.05, 1.2, 2.0),
        _pad("4", 0.0, 2.6, 3.6, 2.2),
    ],
    {"w": 6.5, "h": 7.0, "z": 1.8, "color": "ic"},
    {"w": 8.0, "h": 8.2}, tags=["smd", "power"],
)

# --------------------------------------------------------------------------- #
# IC packages
# --------------------------------------------------------------------------- #
def _dual_row(name: str, pins: int, pitch: float, row: float, pad_w: float, pad_h: float,
              body: tuple, height: float, pad_shape: str = "rect") -> dict:
    per_side = pins // 2
    span = (per_side - 1) * pitch
    pads: List[dict] = []
    # pad_h is the land length (outward), pad_w the width along the pin row
    for i in range(per_side):
        pads.append(_pad(str(i + 1), -row / 2, span / 2 - i * pitch, pad_h, pad_w,
                         shape=pad_shape))
    for i in range(per_side):
        pads.append(_pad(str(per_side + i + 1), row / 2, -span / 2 + i * pitch, pad_h, pad_w,
                         shape=pad_shape))
    return _register(
        name, f"{name} ({pins} pins, {pitch} mm pitch)", pads,
        {"w": body[0], "h": body[1], "z": height, "color": "ic"},
        {"w": row + pad_w + 0.9, "h": span + pitch + pad_h + 0.5}, tags=["smd", "ic"],
    )


_dual_row("SOIC-8", 8, 1.27, 5.4, 0.62, 1.55, (3.9, 4.9), 1.75)
_dual_row("SOIC-14", 14, 1.27, 5.4, 0.62, 1.55, (3.9, 8.55), 1.75)
_dual_row("SOIC-16", 16, 1.27, 5.4, 0.62, 1.55, (3.9, 9.9), 1.75)
_dual_row("SOIC-28W", 28, 1.27, 8.9, 0.62, 1.55, (7.5, 17.9), 2.0)
_dual_row("TSSOP-16", 16, 0.65, 5.0, 0.45, 1.5, (4.4, 5.0), 1.1)
_dual_row("TSSOP-20", 20, 0.65, 5.0, 0.45, 1.5, (4.4, 6.5), 1.1)
_dual_row("DIP-4", 4, 2.54, 7.62, 1.6, 1.6, (5.0, 6.4), 4.0, pad_shape="round")
_dual_row("DIP-8", 8, 2.54, 7.62, 1.7, 1.7, (6.4, 9.8), 4.0, pad_shape="round")

# QFN-24 0.5 mm pitch — usable, but fanout is tight; the engine warns.
_register(
    "QFN-24", "QFN-24 (0.5 mm pitch, exposed pad)", [
        *[_pad(str(i + 1), -2.25, -2.75 + i * 0.5, 0.8, 0.28)
          for i in range(6)],
        *[_pad(str(7 + i), -2.75 + i * 0.5, 2.25, 0.28, 0.8)
          for i in range(6)],
        *[_pad(str(13 + i), 2.25, 2.75 - i * 0.5, 0.8, 0.28)
          for i in range(6)],
        *[_pad(str(19 + i), 2.75 - i * 0.5, -2.25, 0.28, 0.8)
          for i in range(6)],
        _pad("25", 0.0, 0.0, 3.4, 3.4),
    ],
    {"w": 4.0, "h": 4.0, "z": 0.95, "color": "ic"},
    {"w": 5.4, "h": 5.4}, tags=["smd", "ic", "fine-pitch"],
)

# --------------------------------------------------------------------------- #
# modules (2.54 mm headers — the engine's sweet spot)
# --------------------------------------------------------------------------- #
def _module(name: str, desc: str, pins_per_side: int, row_mm: float, pin_names: List[str],
            body: tuple, height: float) -> dict:
    """Dual-row module, standard DIP-style numbering.

    Pin 1 sits top-left and runs DOWN the left column; the right column
    continues bottom-right back UP, so pin N and pin N+1 are adjacent at the
    top edge (the convention every dev board silk uses).
    """
    span = (pins_per_side - 1) * 2.54
    pads: List[dict] = []
    names: Dict[str, str] = {}
    for i in range(pins_per_side):
        num = str(i + 1)
        pads.append(_pad(num, -row_mm / 2, span / 2 - i * 2.54,
                         1.7, 1.7, shape="round", drill=1.0))
        names[num] = pin_names[i]
    for i in range(pins_per_side):
        num = str(pins_per_side + i + 1)
        pads.append(_pad(num, row_mm / 2, -span / 2 + i * 2.54,
                         1.7, 1.7, shape="round", drill=1.0))
        names[num] = pin_names[pins_per_side + i]
    return _register(
        name, desc, pads,
        {"w": body[0], "h": body[1], "z": height, "color": "module"},
        {"w": row_mm + 4.0, "h": span + 6.5}, pin_names=names, tags=["module", "tht"],
    )


PICO_PINS = [
    "GP0", "GP1", "GND", "GP2", "GP3", "GP4", "GP5", "GND", "GP6", "GP7",
    "GP8", "GP9", "GND", "GP10", "GP11", "GP12", "GP13", "GND", "GP14", "GP15",
    "GP16", "GP17", "GND", "GP18", "GP19", "GP20", "GP21", "GND", "GP22", "RUN",
    "GP26", "GP27", "GND", "GP28", "ADC_VREF", "3V3", "3V3_EN", "GND", "VSYS", "VBUS",
]
_module("module-pico", "Raspberry Pi Pico / Pico W (40-pin, 2.54 mm)", 20, 17.78,
        PICO_PINS, (21.0, 51.0), 4.0)

NANO_PINS = [
    "D1/TX", "D0/RX", "RESET", "GND", "D2", "D3", "D4", "D5", "D6", "D7",
    "D8", "D9", "D10", "D11", "D12",
    "D13", "3V3", "AREF", "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
    "5V", "RESET2", "GND2", "VIN",
]
_module("module-nano", "Arduino Nano (30-pin, 2.54 mm)", 15, 15.24,
        NANO_PINS, (18.0, 45.0), 4.0)

# --------------------------------------------------------------------------- #
# connectors & electromechanical
# --------------------------------------------------------------------------- #
def _header(name: str, count: int, rows: int = 1) -> dict:
    pitch = 2.54
    if rows == 1:
        pads = [_pad(str(i + 1), 0.0, -((count - 1) * pitch) / 2 + i * pitch,
                     1.7, 1.7, shape="round", drill=1.0) for i in range(count)]
        span_y = (count - 1) * pitch
        body = (2.54, span_y + 2.54, 2.5)
        cy = (1.7, span_y + 2.0)
    else:
        per = count // 2
        pads = []
        for i in range(per):
            pads.append(_pad(str(2 * i + 1), -pitch / 2, -((per - 1) * pitch) / 2 + i * pitch,
                             1.7, 1.7, shape="round", drill=1.0))
            pads.append(_pad(str(2 * i + 2), pitch / 2, -((per - 1) * pitch) / 2 + i * pitch,
                             1.7, 1.7, shape="round", drill=1.0))
        span_y = (per - 1) * pitch
        body = (2 * pitch, span_y + 2.54, 2.5)
        cy = (2 * pitch + 1.6, span_y + 2.0)
    return _register(
        name, f"{count}-pin {rows}x header, 2.54 mm", pads,
        {"w": body[0], "h": body[1], "z": body[2], "color": "connector"},
        {"w": cy[0] + 0.8, "h": cy[1]}, tags=["connector", "tht"],
    )


for n in (2, 3, 4, 5, 6, 8, 10):
    _header(f"header-1x{n}", n, 1)
for name, n in (("header-2x4", 8), ("header-2x5", 10)):
    _header(name, n, 2)

_register(
    "JST-PH-2", "JST-PH 2-pin side entry, 2.0 mm", [
        _pad("1", -1.0, 0, 1.2, 1.8), _pad("2", 1.0, 0, 1.2, 1.8),
    ],
    {"w": 7.4, "h": 4.5, "z": 1.6, "color": "connector"},
    {"w": 8.6, "h": 5.6}, tags=["connector", "smd"],
)

_register(
    "USB-C-16", "USB-C receptacle, 16-pin SMD (0.5 mm pitch)", [
        _pad(str(i + 1), -2.75 + i * 0.5, -4.0, 0.3, 1.2) for i in range(8)
    ] + [
        _pad(str(i + 9), -2.75 + i * 0.5, 4.0, 0.3, 1.2) for i in range(8)
    ] + [
        _pad("A1", -4.3, 1.0, 0.9, 2.0), _pad("B1", 4.3, 1.0, 0.9, 2.0),
    ],
    {"w": 9.0, "h": 7.5, "z": 3.2, "color": "connector"},
    {"w": 10.2, "h": 10.5}, tags=["connector", "smd", "fine-pitch"],
)

_register(
    "screw-terminal-2", "2-pin 5.0 mm screw terminal", [
        _pad("1", -2.5, 0, 2.6, 2.6, shape="round", drill=1.3),
        _pad("2", 2.5, 0, 2.6, 2.6, shape="round", drill=1.3),
    ],
    {"w": 10.0, "h": 7.5, "z": 8.0, "color": "connector"},
    {"w": 11.2, "h": 8.6}, tags=["connector", "tht"],
)

_register(
    "barrel-jack", "DC barrel jack 5.5/2.1 mm", [
        _pad("1", 0.0, -3.6, 2.4, 2.4, shape="round", drill=1.3),
        _pad("2", -4.0, -2.9, 2.4, 2.4, shape="round", drill=1.3),
        _pad("3", 4.0, -2.9, 2.4, 2.4, shape="round", drill=1.3),
    ],
    {"w": 9.5, "h": 11.0, "z": 9.0, "color": "connector"},
    {"w": 11.0, "h": 12.0}, tags=["connector", "tht"],
)

_register(
    "tact-6mm", "6x6 mm tactile push button", [
        _pad("1", -3.25, -2.25, 2.0, 2.0, shape="round", drill=1.1),
        _pad("2", 3.25, -2.25, 2.0, 2.0, shape="round", drill=1.1),
        _pad("3", -3.25, 2.25, 2.0, 2.0, shape="round", drill=1.1),
        _pad("4", 3.25, 2.25, 2.0, 2.0, shape="round", drill=1.1),
    ],
    {"w": 6.0, "h": 6.0, "z": 5.0, "color": "connector"},
    {"w": 9.4, "h": 7.4}, tags=["switch", "tht"],
)

_register(
    "relay-SRD", "SRD-05VDC-SL-C relay", [
        _pad("1", -5.0, 3.2, 2.0, 2.0, shape="round", drill=1.3),
        _pad("2", -5.0, -7.7, 2.0, 2.0, shape="round", drill=1.3),
        _pad("3", 5.0, 3.2, 2.0, 2.0, shape="round", drill=1.3),
        _pad("4", 5.0, -7.7, 2.4, 2.4, shape="round", drill=1.3),
        _pad("5", 5.0, 5.8, 2.0, 2.0, shape="round", drill=1.3),
    ],
    {"w": 15.0, "h": 19.0, "z": 15.0, "color": "connector"},
    {"w": 17.0, "h": 21.0}, tags=["relay", "tht"],
)

_register(
    "buzzer-12mm", "12 mm active buzzer", [
        _pad("1", -3.8, 0, 2.4, 2.4, shape="round", drill=1.3),
        _pad("2", 3.8, 0, 2.4, 2.4, shape="round", drill=1.3),
    ],
    {"w": 12.0, "h": 12.0, "z": 9.0, "color": "connector"},
    {"w": 13.0, "h": 13.0}, tags=["audio", "tht"],
)

_register(
    "crystal-3225", "3.2 x 2.5 mm 4-pad crystal", [
        _pad("1", -1.1, -0.85, 0.9, 1.0), _pad("2", 1.1, -0.85, 0.9, 1.0),
        _pad("3", 1.1, 0.85, 0.9, 1.0), _pad("4", -1.1, 0.85, 0.9, 1.0),
    ],
    {"w": 3.2, "h": 2.5, "z": 0.9, "color": "metal"},
    {"w": 4.4, "h": 3.6}, tags=["smd", "crystal"],
)

_register(
    "fiducial-1mm", "1 mm fiducial (mask-opened copper dot)", [
        _pad("1", 0.0, 0.0, 1.0, 1.0, shape="round", name="FID"),
    ],
    {"w": 0.0, "h": 0.0, "z": 0.0, "color": "hole"},
    {"w": 2.0, "h": 2.0}, tags=["mechanical", "fiducial"],
)

_register(
    "testpoint-1.5mm", "1.5 mm test point pad", [
        _pad("1", 0.0, 0.0, 1.5, 1.5, shape="round", name="TP"),
    ],
    {"w": 0.0, "h": 0.0, "z": 0.0, "color": "metal"},
    {"w": 2.4, "h": 2.4}, tags=["mechanical", "testpoint"],
)

_register(
    "mounting-hole-m3", "M3 mounting hole (NPTH)", [
        _pad("1", 0.0, 0.0, 3.2, 3.2, shape="npth", drill=3.2, name="MH"),
    ],
    {"w": 0.0, "h": 0.0, "z": 0.0, "color": "hole"},
    {"w": 6.0, "h": 6.0}, tags=["mechanical", "npth"],
)


def get(name: str) -> dict:
    if name not in FOOTPRINTS:
        raise KeyError(f"unknown footprint {name!r}")
    return FOOTPRINTS[name]


def names() -> List[str]:
    return sorted(FOOTPRINTS)


# --------------------------------------------------------------------------- #
# power / discrete extras
# --------------------------------------------------------------------------- #
_register(
    "SMA", "SMA diode (5.2 x 2.6 mm)", [
        _pad("1", -2.0, 0, 1.6, 1.8), _pad("2", 2.0, 0, 1.6, 1.8),
    ],
    {"w": 4.3, "h": 2.6, "z": 2.2, "color": "ic"},
    {"w": 5.4, "h": 3.4}, tags=["smd", "diode"],
)

_register(
    "CP-6.3", "SMD electrolytic capacitor 6.3 x 5.4 mm", [
        _pad("1", -2.3, 0, 2.2, 2.6), _pad("2", 2.3, 0, 2.2, 2.6),
    ],
    {"w": 6.6, "h": 6.6, "z": 5.4, "color": "electrolytic"},
    {"w": 7.8, "h": 7.2}, tags=["smd", "capacitor"],
)

_register(
    "TO-220", "TO-220 upright (1.27 mm class regulators)", [
        _pad("1", -2.54, 0, 1.9, 2.2, shape="oval", drill=1.1),
        _pad("2", 0.0, 0, 1.9, 2.2, shape="oval", drill=1.1),
        _pad("3", 2.54, 0, 1.9, 2.2, shape="oval", drill=1.1),
    ],
    {"w": 10.0, "h": 4.5, "z": 15.0, "color": "ic"},
    {"w": 11.5, "h": 6.0}, tags=["tht", "power"],
)

_register(
    "SIP-3", "3-pin SIP (0.1 in)", [
        _pad("1", -2.54, 0, 1.8, 1.8, shape="round", drill=1.0),
        _pad("2", 0.0, 0, 1.8, 1.8, shape="round", drill=1.0),
        _pad("3", 2.54, 0, 1.8, 1.8, shape="round", drill=1.0),
    ],
    {"w": 7.6, "h": 2.5, "z": 5.0, "color": "module"},
    {"w": 8.6, "h": 4.0}, tags=["tht"],
)
