"""Starter designs.

A template is a netlist plus a board outline; placement and routing are still
done by the engine, so the result is a real, editable design rather than a
static picture. They exist so the first prompt in a fresh install produces
something worth looking at.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .project import Board, BoardError

TEMPLATES: Dict[str, dict] = {
    "pico-blinky": {
        "title": "Pico blinky",
        "desc": "Raspberry Pi Pico, one user LED, one button, 5 V input header.",
        "board": {"width": 68, "height": 44, "corner_radius": 3},
        "components": [
            ("pico", "U1", "Pico", {
                "39": "VSYS", "36": "+3V3",
                "3": "GND", "8": "GND", "13": "GND", "18": "GND",
                "23": "GND", "28": "GND", "33": "GND", "38": "GND",
                "20": "LED", "19": "BTN",
            }),
            ("r-0805", "R1", "330R", {"1": "LED", "2": "LED_A"}),
            ("led-0805", "D1", "Green", {"2": "LED_A", "1": "GND"}),
            ("r-0805", "R2", "10k", {"1": "+3V3", "2": "BTN"}),
            ("tact-6mm", "SW1", "BOOT", {"1": "BTN", "2": "GND", "3": "BTN", "4": "GND"}),
            ("c-0805", "C1", "1uF", {"1": "+3V3", "2": "GND"}),
            ("header-1x2", "J1", "5V IN", {"1": "VSYS", "2": "GND"}),
            ("mounting-hole-m3", "H1", "M3", {}),
            ("mounting-hole-m3", "H2", "M3", {}),
        ],
        "notes": "Feed 1.8-5.5 V into J1 (VSYS). LED on GP15, button on GP14.",
    },
    "pico-sensor-hub": {
        "title": "Pico sensor hub",
        "desc": "I2C sensor hub: BME280 + OLED headers, pull-ups, decoupling, user button.",
        "board": {"width": 72, "height": 50, "corner_radius": 3},
        "components": [
            ("pico", "U1", "Pico", {
                "39": "VSYS", "36": "+3V3",
                "3": "GND", "8": "GND", "13": "GND", "18": "GND",
                "23": "GND", "28": "GND", "33": "GND", "38": "GND",
                "6": "SDA", "7": "SCL", "20": "LED", "19": "BTN",
            }),
            ("header-1x4", "J1", "BME280", {"1": "+3V3", "2": "GND", "3": "SCL", "4": "SDA"}),
            ("header-1x4", "J2", "OLED", {"1": "+3V3", "2": "GND", "3": "SCL", "4": "SDA"}),
            ("r-0603", "R1", "4k7", {"1": "+3V3", "2": "SDA"}),
            ("r-0603", "R2", "4k7", {"1": "+3V3", "2": "SCL"}),
            ("c-0805", "C1", "100nF", {"1": "+3V3", "2": "GND"}),
            ("cp-6.3", "C2", "10uF", {"1": "VSYS", "2": "GND"}),
            ("r-0805", "R3", "330R", {"1": "LED", "2": "LED_A"}),
            ("led-0603", "D1", "Green", {"2": "LED_A", "1": "GND"}),
            ("tact-6mm", "SW1", "MODE", {"1": "BTN", "2": "GND", "3": "BTN", "4": "GND"}),
            ("header-1x2", "J3", "PWR", {"1": "VSYS", "2": "GND"}),
            ("mounting-hole-m3", "H1", "M3", {}),
            ("mounting-hole-m3", "H2", "M3", {}),
        ],
        "notes": "I2C0 on GP4/GP5. J1 = BME280, J2 = SSD1306 OLED, both on the same bus.",
    },
    "nano-relay": {
        "title": "Nano relay board",
        "desc": "Two 5 V relays driven through a ULN2003, screw terminals, flyback diodes.",
        "board": {"width": 88, "height": 62, "corner_radius": 3},
        "components": [
            ("nano", "U1", "Nano", {
                "27": "5V", "4": "GND", "29": "GND",
                "7": "D4", "8": "D5",
            }),
            ("uln2003", "U2", "ULN2003", {
                "1": "IN1", "2": "IN2", "8": "GND", "9": "5V",
                "16": "OUT1", "15": "OUT2",
            }),
            ("r-0805", "R1", "1k", {"1": "D4", "2": "IN1"}),
            ("r-0805", "R2", "1k", {"1": "D5", "2": "IN2"}),
            ("relay-srd", "K1", "SRD-05VDC", {"1": "5V", "2": "OUT1", "3": "COM1",
                                               "4": "NO1"}),
            ("relay-srd", "K2", "SRD-05VDC", {"1": "5V", "2": "OUT2", "3": "COM2",
                                               "4": "NO2"}),
            ("d-sod123", "D1", "1N4148W", {"1": "5V", "2": "OUT1"}),
            ("d-sod123", "D2", "1N4148W", {"1": "5V", "2": "OUT2"}),
            ("screw-term-2", "J1", "OUT1", {"1": "NO1", "2": "COM1"}),
            ("screw-term-2", "J2", "OUT2", {"1": "NO2", "2": "COM2"}),
            ("header-1x2", "J3", "5V IN", {"1": "5V", "2": "GND"}),
            ("mounting-hole-m3", "H1", "M3", {}),
            ("mounting-hole-m3", "H2", "M3", {}),
        ],
        "notes": "Relay coils are open-collector driven; D1/D2 clamp the coil flyback.",
    },
    "power-5v": {
        "title": "5 V power supply",
        "desc": "Barrel jack, 7805 regulator, bulk + decoupling capacitors, LED, terminal block.",
        "board": {"width": 50, "height": 38, "corner_radius": 3},
        "components": [
            ("barrel-jack", "J1", "9-12V", {"1": "VIN", "2": "GND", "3": "GND"}),
            ("lm7805", "U1", "L7805", {"1": "VIN", "2": "GND", "3": "VOUT"}),
            ("cp-6.3", "C1", "100uF", {"1": "VIN", "2": "GND"}),
            ("c-0805", "C2", "100nF", {"1": "VOUT", "2": "GND"}),
            ("c-0805", "C3", "100nF", {"1": "VIN", "2": "GND"}),
            ("r-0805", "R1", "1k", {"1": "VOUT", "2": "LED_A"}),
            ("led-0805", "D1", "Red", {"2": "LED_A", "1": "GND"}),
            ("screw-term-2", "J2", "5V OUT", {"1": "VOUT", "2": "GND"}),
        ],
        "notes": "Keep C1 close to the regulator input, C2/C3 at the connector.",
    },
}


def names() -> List[dict]:
    return [{"id": k, "title": v["title"], "desc": v["desc"],
             "components": len(v["components"]), "board": v["board"]} for k, v in TEMPLATES.items()]


def instantiate(tid: str, title: Optional[str] = None) -> Board:
    if tid not in TEMPLATES:
        raise BoardError(f"unknown template {tid!r} (one of: {', '.join(TEMPLATES)})")
    t = TEMPLATES[tid]
    b = t["board"]
    board = Board.create(title or t["title"], width=b["width"], height=b["height"],
                         corner_radius=b.get("corner_radius", 2.0))
    for part_id, ref, value, nets in t["components"]:
        board.add_component(part_id, nets=nets, ref=ref, value=value)
    board.data["meta"]["template"] = tid
    board.data["meta"]["notes"] = t["notes"]
    return board
