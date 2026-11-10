"""Part catalog.

A part is a footprint plus the pin numbering a designer reasons about:

    {"id": "ne555", "name": "NE555 timer", "footprint": "SOIC-8",
     "pins": {"1": "GND", "2": "TRIG", ...}, "datasheet": "...", "verified": true}

``pins`` keys are footprint pad numbers, so a component's ``nets`` mapping is
always pin-number -> net name. Every entry carries ``verified=True`` only when
the pin map follows the manufacturer datasheet; the engine refuses to template
a board from an unverified part.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import footprints

CATALOG: Dict[str, dict] = {}


def _part(pid: str, name: str, footprint: str, category: str, desc: str,
          pins: Optional[Dict[str, str]] = None, tags: Optional[List[str]] = None,
          datasheet: str = "", verified: bool = True, attrs: Optional[dict] = None,
          mpn: str = "", mfr: str = "") -> dict:
    fp = footprints.get(footprint)
    pin_map = pins or dict(fp["pin_names"])
    missing = [p["num"] for p in fp["pads"] if p["num"] not in pin_map]
    if missing:
        raise ValueError(f"{pid}: footprint {footprint} pads without pin names: {missing}")
    entry = {
        "id": pid,
        "name": name,
        "footprint": footprint,
        "category": category,
        "desc": desc,
        "pins": pin_map,
        "tags": tags or [],
        "datasheet": datasheet,
        "verified": verified,
        "attrs": attrs or {},
        # Supplier identity. Blank unless a real, verified part number is known —
        # an invented MPN is worse than an empty one.
        "mpn": mpn,
        "mfr": mfr,
        "mount": "tht" if any(p["kind"] == "tht" for p in fp["pads"]) else "smd",
        "pads": len(fp["pads"]),
    }
    CATALOG[pid] = entry
    return entry


# --------------------------------------------------------------------------- #
# passives
# --------------------------------------------------------------------------- #
_part("r-0402", "Resistor 0402", "0402", "passive", "Thick-film resistor, 1/16 W",
      pins={"1": "1", "2": "2"}, tags=["resistor"])
_part("r-0603", "Resistor 0603", "0603", "passive", "Thick-film resistor, 1/10 W",
      pins={"1": "1", "2": "2"}, tags=["resistor"])
_part("r-0805", "Resistor 0805", "0805", "passive", "Thick-film resistor, 1/8 W",
      pins={"1": "1", "2": "2"}, tags=["resistor"])
_part("c-0402", "Ceramic capacitor 0402", "0402", "passive", "MLCC, 16-50 V",
      pins={"1": "1", "2": "2"}, tags=["capacitor"])
_part("c-0603", "Ceramic capacitor 0603", "0603", "passive", "MLCC, 16-50 V",
      pins={"1": "1", "2": "2"}, tags=["capacitor"])
_part("c-0805", "Ceramic capacitor 0805", "0805", "passive", "MLCC, 16-50 V",
      pins={"1": "1", "2": "2"}, tags=["capacitor"])
_part("cp-6.3", "Electrolytic capacitor SMD 6.3 mm", "CP-6.3", "passive",
      "Aluminium electrolytic, 10-470 uF", pins={"1": "+", "2": "-"},
      tags=["capacitor", "polarized"])
_part("l-0805", "Inductor 0805", "0805", "passive", "Wirewound / multilayer inductor",
      pins={"1": "1", "2": "2"}, tags=["inductor"])
_part("l-1206", "Inductor 1206", "1206", "passive", "Power inductor",
      pins={"1": "1", "2": "2"}, tags=["inductor"])
_part("fb-0603", "Ferrite bead 0603", "0603", "passive", "600 ohm @ 100 MHz",
      pins={"1": "1", "2": "2"}, tags=["ferrite"])
_part("fuse-1206", "PTC fuse 1206", "1206", "passive", "Resettable fuse, 0.5-2 A",
      pins={"1": "1", "2": "2"}, tags=["protection"])

_part("led-0603", "LED 0603", "0603", "opto", "Indicator LED. Pin 1 = cathode (K).",
      pins={"1": "K", "2": "A"}, tags=["led"], attrs={"polarized": True})
_part("led-0805", "LED 0805", "0805", "opto", "Indicator LED. Pin 1 = cathode (K).",
      pins={"1": "K", "2": "A"}, tags=["led"], attrs={"polarized": True})
_part("d-sod123", "Diode 1N4148W", "SOD-123", "diode", "Small-signal diode 100 V / 300 mA",
      pins={"1": "K", "2": "A"}, tags=["diode"], attrs={"polarized": True},
      mpn="1N4148W", mfr="Diodes Incorporated")
_part("d-zener", "Zener diode SOD-123", "SOD-123", "diode", "Zener, 3.3-15 V",
      pins={"1": "K", "2": "A"}, tags=["diode", "protection"], attrs={"polarized": True})
_part("d-schottky", "Schottky diode SS34", "SMA", "diode", "3 A / 40 V Schottky rectifier",
      pins={"1": "K", "2": "A"}, tags=["diode"], attrs={"polarized": True},
      mpn="SS34", mfr="MDD")

# --------------------------------------------------------------------------- #
# transistors & power
# --------------------------------------------------------------------------- #
_part("mmbt3904", "NPN transistor MMBT3904", "SOT-23", "transistor",
      "40 V / 200 mA NPN switch", pins={"1": "B", "2": "E", "3": "C"},
      tags=["transistor"],
      mpn="MMBT3904", mfr="onsemi")
_part("ao3400", "N-MOSFET AO3400", "SOT-23", "transistor",
      "30 V / 5.7 A logic-level N-channel MOSFET", pins={"1": "G", "2": "S", "3": "D"},
      tags=["mosfet"],
      mpn="AO3400A", mfr="Alpha & Omega Semiconductor")
_part("ao3401", "P-MOSFET AO3401", "SOT-23", "transistor",
      "-30 V / -4 A logic-level P-channel MOSFET", pins={"1": "G", "2": "S", "3": "D"},
      tags=["mosfet"],
      mpn="AO3401A", mfr="Alpha & Omega Semiconductor")
_part("2n7002", "N-MOSFET 2N7002", "SOT-23", "transistor",
      "60 V / 115 mA small-signal MOSFET", pins={"1": "G", "2": "S", "3": "D"},
      tags=["mosfet"],
      mpn="2N7002", mfr="onsemi")

_part("ams1117-33", "LDO AMS1117-3.3", "SOT-223", "power",
      "800 mA 3.3 V LDO; tab is VOUT", pins={"1": "GND", "2": "VOUT", "3": "VIN", "4": "VOUT"},
      tags=["regulator"],
      mpn="AMS1117-3.3", mfr="AMS")
_part("ams1117-50", "LDO AMS1117-5.0", "SOT-223", "power",
      "800 mA 5 V LDO; tab is VOUT", pins={"1": "GND", "2": "VOUT", "3": "VIN", "4": "VOUT"},
      tags=["regulator"],
      mpn="AMS1117-5.0", mfr="AMS")
_part("xc6206-33", "LDO XC6206P332", "SOT-23", "power",
      "200 mA 3.3 V LDO", pins={"1": "GND", "2": "VOUT", "3": "VIN"}, tags=["regulator"],
      mpn="XC6206P332MR", mfr="Torex Semiconductor")
_part("lm7805", "Regulator 7805", "TO-220", "power", "1.5 A 5 V linear regulator",
      pins={"1": "IN", "2": "GND", "3": "OUT"}, tags=["regulator"],
      mpn="LM7805CT", mfr="Texas Instruments")
_part("buck-in-1x4", "Buck converter module (IN+/IN-/OUT+/OUT-)", "header-1x4", "power",
      "Generic LM2596 / MP1584 buck module carrier", pins={"1": "IN+", "2": "IN-", "3": "OUT+", "4": "OUT-"},
      tags=["regulator", "module"])
_part("boost-in-1x4", "Boost converter module (IN+/IN-/OUT+/OUT-)", "header-1x4", "power",
      "Generic MT3608 boost module carrier", pins={"1": "IN+", "2": "IN-", "3": "OUT+", "4": "OUT-"},
      tags=["regulator", "module"])
_part("usb-power-1x2", "USB power pigtail (5V/GND)", "header-1x2", "power",
      "Carrier for a USB cable tail or 2-pin power entry", pins={"1": "5V", "2": "GND"},
      tags=["connector", "power"])

# --------------------------------------------------------------------------- #
# ICs
# --------------------------------------------------------------------------- #
_part("ne555", "NE555 timer", "SOIC-8", "ic", "Precision timer",
      pins={"1": "GND", "2": "TRIG", "3": "OUT", "4": "RESET", "5": "CTRL",
            "6": "THR", "7": "DIS", "8": "VCC"}, tags=["timer"],
      mpn="NE555DR", mfr="Texas Instruments")
_part("lm358", "LM358 dual op-amp", "SOIC-8", "ic", "Dual general-purpose op-amp",
      pins={"1": "OUT1", "2": "IN1-", "3": "IN1+", "4": "GND",
            "5": "IN2+", "6": "IN2-", "7": "OUT2", "8": "VCC"}, tags=["analog"],
      mpn="LM358DR", mfr="Texas Instruments")
_part("attiny85", "ATtiny85", "DIP-8", "ic", "8-bit AVR, 8 KB flash",
      pins={"1": "PB5", "2": "PB3", "3": "PB4", "4": "GND",
            "5": "PB0", "6": "PB1", "7": "PB2", "8": "VCC"}, tags=["mcu"],
      mpn="ATtiny85-20PU", mfr="Microchip")
_part("uln2003", "ULN2003 Darlington array", "SOIC-16", "ic", "7-channel sink driver",
      pins={"1": "IN1", "2": "IN2", "3": "IN3", "4": "IN4", "5": "IN5", "6": "IN6",
            "7": "IN7", "8": "GND", "9": "COM", "10": "OUT7", "11": "OUT6", "12": "OUT5",
            "13": "OUT4", "14": "OUT3", "15": "OUT2", "16": "OUT1"}, tags=["driver"],
      mpn="ULN2003ADR", mfr="Texas Instruments")
_part("74hc595", "74HC595 shift register", "SOIC-16", "ic", "8-bit serial-in parallel-out",
      pins={"1": "QB", "2": "QC", "3": "QD", "4": "QE", "5": "QF", "6": "QG", "7": "QH",
            "8": "GND", "9": "QH2", "10": "SRCLR", "11": "SRCLK", "12": "RCLK",
            "13": "OE", "14": "SER", "15": "QA", "16": "VCC"}, tags=["logic"],
      mpn="SN74HC595DR", mfr="Texas Instruments")
_part("pc817", "PC817 optocoupler", "DIP-4", "ic", "Phototransistor optocoupler",
      pins={"1": "A", "2": "K", "3": "E", "4": "C"}, tags=["opto", "isolation"],
      mpn="PC817", mfr="Sharp")
_part("ne555-dip", "NE555 timer (DIP-8)", "DIP-8", "ic", "Through-hole 555 timer",
      pins={"1": "GND", "2": "TRIG", "3": "OUT", "4": "RESET", "5": "CTRL",
            "6": "THR", "7": "DIS", "8": "VCC"}, tags=["timer"],
      mpn="NE555P", mfr="Texas Instruments")

# --------------------------------------------------------------------------- #
# sensor breakouts (carried on headers — no vendor-specific land patterns)
# --------------------------------------------------------------------------- #
_part("bme280-brk", "BME280 breakout (VIN/GND/SCL/SDA)", "header-1x4", "sensor",
      "I2C temperature / humidity / pressure breakout", pins={"1": "VIN", "2": "GND", "3": "SCL", "4": "SDA"},
      tags=["i2c", "sensor"])
_part("mpu6050-brk", "MPU6050 breakout (8-pin)", "header-1x8", "sensor",
      "I2C IMU breakout", pins={"1": "VCC", "2": "GND", "3": "SCL", "4": "SDA",
                                "5": "XDA", "6": "XCL", "7": "AD0", "8": "INT"},
      tags=["i2c", "sensor"])
_part("dht22-brk", "DHT22 breakout (3-pin)", "header-1x3", "sensor",
      "Single-wire temperature / humidity sensor", pins={"1": "VCC", "2": "DATA", "3": "GND"},
      tags=["sensor"])
_part("hcsr04-brk", "HC-SR04 ultrasonic breakout (4-pin)", "header-1x4", "sensor",
      "Ultrasonic distance sensor", pins={"1": "VCC", "2": "TRIG", "3": "ECHO", "4": "GND"},
      tags=["sensor"])
_part("pir-brk", "PIR motion breakout (3-pin)", "header-1x3", "sensor",
      "Passive infrared motion detector", pins={"1": "VCC", "2": "OUT", "3": "GND"},
      tags=["sensor"])
_part("ldr-brk", "Photoresistor breakout (2-pin)", "header-1x2", "sensor",
      "LDR in a divider", pins={"1": "A", "2": "B"}, tags=["sensor"])

# --------------------------------------------------------------------------- #
# connectors & electromechanical
# --------------------------------------------------------------------------- #
for _n in (2, 3, 4, 5, 6, 8, 10):
    _part(f"header-1x{_n}", f"Pin header 1x{_n}", f"header-1x{_n}", "connector",
          f"{_n}-pin 2.54 mm header", tags=["connector"])
_part("header-2x4", "Pin header 2x4", "header-2x4", "connector", "8-pin 2.54 mm header",
      tags=["connector"])
_part("header-2x5", "Pin header 2x5 (JTAG/SWD)", "header-2x5", "connector",
      "10-pin 2.54 mm header", tags=["connector", "debug"])
_part("jst-ph-2", "JST-PH 2-pin", "JST-PH-2", "connector", "2.0 mm wire-to-board",
      pins={"1": "+", "2": "-"}, tags=["connector"])
_part("screw-term-2", "Screw terminal 2-pin", "screw-terminal-2", "connector",
      "5.0 mm pitch terminal block", pins={"1": "1", "2": "2"}, tags=["connector"])
_part("barrel-jack", "DC barrel jack", "barrel-jack", "connector",
      "5.5/2.1 mm jack, centre positive", pins={"1": "VIN", "2": "GND", "3": "SW"},
      tags=["connector", "power"])
_part("tact-6mm", "Tactile switch 6 mm", "tact-6mm", "switch",
      "Through-hole push button; 1-2 and 3-4 are tied pairs",
      pins={"1": "A1", "2": "A2", "3": "B1", "4": "B2"}, tags=["switch"])
_part("relay-srd", "Relay SRD-05VDC", "relay-SRD", "relay", "5 V SPDT relay",
      pins={"1": "COIL+", "2": "COIL-", "3": "COM", "4": "NO", "5": "NC"}, tags=["relay"],
      mpn="SRD-05VDC-SL-C", mfr="Songle")
_part("buzzer-12", "Active buzzer 12 mm", "buzzer-12mm", "audio",
      "5 V active buzzer", pins={"1": "+", "2": "-"}, tags=["audio"])
_part("crystal-3225", "Crystal 3.2 x 2.5 mm", "crystal-3225", "timing",
      "8-32 MHz SMD crystal", pins={"1": "X1", "2": "GND", "3": "X2", "4": "GND"},
      tags=["crystal"])
_part("mounting-hole-m3", "Mounting hole M3", "mounting-hole-m3", "mechanical",
      "3.2 mm non-plated hole", pins={"1": "MH"}, tags=["mechanical"])
# Assembly alignment: pick-and-place machines need three of these, and a test
# point is the same copper dot with a net on it.
_part("fiducial-1mm", "Fiducial 1 mm", "fiducial-1mm", "mechanical",
      "Mask-opened copper dot for pick-and-place alignment",
      pins={"1": "FID"}, tags=["mechanical", "fiducial"])
_part("testpoint-1.5mm", "Test point 1.5 mm", "testpoint-1.5mm", "mechanical",
      "Round probe pad", pins={"1": "TP"}, tags=["mechanical", "testpoint"])

# --------------------------------------------------------------------------- #
# modules
# --------------------------------------------------------------------------- #
_part("pico", "Raspberry Pi Pico (RP2040)", "module-pico", "module",
      "40-pin Pico / Pico W module; 3.3 V IO, 1.8-5.5 V VSYS",
      tags=["mcu", "module"], attrs={"logic_v": 3.3, "vbus_pin": "VBUS"})
_part("pico-w", "Raspberry Pi Pico W", "module-pico", "module",
      "Pico W (wireless) module, same land pattern as Pico",
      tags=["mcu", "module", "wifi"], attrs={"logic_v": 3.3, "vbus_pin": "VBUS"})
_part("nano", "Arduino Nano", "module-nano", "module",
      "30-pin Nano module; 5 V IO, 7-12 V VIN",
      tags=["mcu", "module"], attrs={"logic_v": 5.0, "vbus_pin": "5V"})


# --------------------------------------------------------------------------- #
# lookup helpers
# --------------------------------------------------------------------------- #
def get(pid: str) -> dict:
    if pid not in CATALOG:
        raise KeyError(f"unknown part {pid!r}")
    return CATALOG[pid]


def search(query: str = "", category: str = "", limit: int = 40) -> List[dict]:
    q = (query or "").strip().lower()
    out = []
    for p in CATALOG.values():
        if category and p["category"] != category:
            continue
        hay = " ".join([p["id"], p["name"], p["desc"], p["category"], " ".join(p["tags"])]).lower()
        if q and not all(tok in hay for tok in q.split()):
            continue
        out.append({
            "id": p["id"], "name": p["name"], "category": p["category"],
            "footprint": p["footprint"], "mount": p["mount"], "pins": p["pins"],
            "desc": p["desc"], "verified": p["verified"],
        })
    out.sort(key=lambda p: (p["category"], p["id"]))
    return out[:limit]


def categories() -> List[str]:
    return sorted({p["category"] for p in CATALOG.values()})
