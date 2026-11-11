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
    "pico-relay-4": {
        "title": "Pico relay 4",
        "desc": "Four-channel relay controller: Pico, ULN2003 driver, protected 5 V input, screw terminals, status LEDs, test points and fiducials.",
        "board": {"width": 90, "height": 116, "corner_radius": 3},
        "components": [
            ("pico", "U1", "Pico", {"39": "+5V", "36": "+3V3", "3": "GND", "8": "GND", "13": "GND", "18": "GND", "23": "GND", "28": "GND", "33": "GND", "38": "GND", "4": "N1", "5": "N2", "6": "N3", "7": "N4"}),
            ("barrel-jack", "J1", "5-12V IN", {"1": "VIN", "2": "GND", "3": "GND"}),
            ("fuse-1206", "F1", "1.1A", {"1": "VIN", "2": "VFUSED"}),
            ("d-schottky", "D1", "SS34", {"2": "VFUSED", "1": "+5V"}),
            ("cp-6.3", "C1", "100uF", {"1": "+5V", "2": "GND"}),
            ("c-0805", "C2", "10uF", {"1": "+5V", "2": "GND"}),
            ("c-0805", "C3", "100nF", {"1": "+5V", "2": "GND"}),
            ("uln2003", "U2", "ULN2003A", {"1": "IN1", "2": "IN2", "3": "IN3", "4": "IN4", "8": "GND", "9": "+5V", "16": "OUT1", "15": "OUT2", "14": "OUT3", "13": "OUT4"}),
            ("c-0805", "C4", "100nF", {"1": "+5V", "2": "GND"}),
            ("r-0805", "R1", "1k", {"1": "N1", "2": "IN1"}),
            ("r-0805", "R9", "470R", {"1": "N1", "2": "LEDA1"}),
            ("led-0603", "D2", "Green", {"2": "LEDA1", "1": "GND"}),
            ("relay-srd", "K1", "SRD-05VDC", {"1": "+5V", "2": "OUT1", "3": "COM1", "4": "NO1"}),
            ("screw-term-2", "J2", "OUT1", {"1": "COM1", "2": "NO1"}),
            ("r-0805", "R2", "1k", {"1": "N2", "2": "IN2"}),
            ("r-0805", "R10", "470R", {"1": "N2", "2": "LEDA2"}),
            ("led-0603", "D3", "Green", {"2": "LEDA2", "1": "GND"}),
            ("relay-srd", "K2", "SRD-05VDC", {"1": "+5V", "2": "OUT2", "3": "COM2", "4": "NO2"}),
            ("screw-term-2", "J3", "OUT2", {"1": "COM2", "2": "NO2"}),
            ("r-0805", "R3", "1k", {"1": "N3", "2": "IN3"}),
            ("r-0805", "R11", "470R", {"1": "N3", "2": "LEDA3"}),
            ("led-0603", "D4", "Green", {"2": "LEDA3", "1": "GND"}),
            ("relay-srd", "K3", "SRD-05VDC", {"1": "+5V", "2": "OUT3", "3": "COM3", "4": "NO3"}),
            ("screw-term-2", "J4", "OUT3", {"1": "COM3", "2": "NO3"}),
            ("r-0805", "R4", "1k", {"1": "N4", "2": "IN4"}),
            ("r-0805", "R12", "470R", {"1": "N4", "2": "LEDA4"}),
            ("led-0603", "D5", "Green", {"2": "LEDA4", "1": "GND"}),
            ("relay-srd", "K4", "SRD-05VDC", {"1": "+5V", "2": "OUT4", "3": "COM4", "4": "NO4"}),
            ("screw-term-2", "J5", "OUT4", {"1": "COM4", "2": "NO4"}),
            ("mounting-hole-m3", "H1", "M3", {}),
            ("mounting-hole-m3", "H2", "M3", {}),
            ("mounting-hole-m3", "H3", "M3", {}),
            ("mounting-hole-m3", "H4", "M3", {}),
            ("fiducial-1mm", "FID1", "FID", {}),
            ("fiducial-1mm", "FID2", "FID", {}),
            ("fiducial-1mm", "FID3", "FID", {}),
            ("testpoint-1.5mm", "TP1", "+5V", {"1": "+5V"}),
            ("testpoint-1.5mm", "TP2", "GND", {"1": "GND"}),
            ("testpoint-1.5mm", "TP3", "+3V3", {"1": "+3V3"}),
        ],
        "placement": {
            "U1": (45, 13, 90),
            "U2": (38, 40, 0),
            "C4": (38, 51, 0),
            "J1": (44, 86, 0),
            "F1": (52, 86, 0),
            "D1": (58, 86, 90),
            "C1": (66, 86, 0),
            "C2": (72, 86, 0),
            "C3": (78, 86, 0),
            "H1": (6, 6, 0),
            "H2": (84, 6, 0),
            "H3": (6, 110, 0),
            "H4": (84, 110, 0),
            "FID1": (76, 6, 0),
            "FID2": (80, 6, 0),
            "FID3": (76, 12, 0),
            "TP1": (64, 94, 0),
            "TP2": (70, 94, 0),
            "TP3": (76, 94, 0),
            "K1": (20, 36, 0),
            "J2": (6.5, 36, 90),
            "R1": (44, 36, 0),
            "R9": (50, 36, 0),
            "D2": (56, 36, 0),
            "K2": (20, 57, 0),
            "J3": (6.5, 57, 90),
            "R2": (44, 57, 0),
            "R10": (50, 57, 0),
            "D3": (56, 57, 0),
            "K3": (20, 78, 0),
            "J4": (6.5, 78, 90),
            "R3": (44, 78, 0),
            "R11": (50, 78, 0),
            "D4": (56, 78, 0),
            "K4": (20, 99, 0),
            "J5": (6.5, 99, 90),
            "R4": (44, 99, 0),
            "R12": (50, 99, 0),
            "D5": (56, 99, 0),
        },
        "notes": "Relays switch COM to NO; the ULN2003 clamps the coil flyback to +5V, so no external diodes. J1 takes 5-12 V through a 1.1 A PTC fuse and a Schottky for reverse-polarity protection. Channels are GP2-GP5, relay 1-4. TP1/TP2/TP3 are +5 V, GND and +3V3.",
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
    # A template may ship a designed layout: the placement is part of the design,
    # not something to rediscover. Auto-placement still runs on request.
    for ref, (x, y, rot) in (t.get("placement") or {}).items():
        comp = board.component(ref)
        comp["x"], comp["y"], comp["rot"] = float(x), float(y), float(rot)
    if t.get("placement"):
        board.touch()
    board.data["meta"]["template"] = tid
    board.data["meta"]["notes"] = t["notes"]
    return board
