"""Supplier identity on the library parts.

An empty MPN is honest: the buy link falls back to value + footprint. An invented
one ships the wrong part, so every MPN that *is* filled in has to be the part we
actually modelled — the right family for the footprint, with a manufacturer.
"""

from __future__ import annotations

from circuit_core import layers, templates
from circuit_core.lib import parts

# The parts whose identity *is* the part number. Passives and modules are
# deliberately absent: a 10 k 0805 resistor is a dozen MPNs, and the search link
# built from value + footprint is the correct answer for them.
EXPECTED = {
    "d-sod123": "1N4148W",
    "d-schottky": "SS34",
    "mmbt3904": "MMBT3904",
    "ao3400": "AO3400A",
    "2n7002": "2N7002",
    "ams1117-33": "AMS1117-3.3",
    "xc6206-33": "XC6206P332MR",
    "lm7805": "LM7805CT",
    "ne555": "NE555DR",
    "lm358": "LM358DR",
    "attiny85": "ATtiny85-20PU",
    "uln2003": "ULN2003ADR",
    "74hc595": "SN74HC595DR",
    "relay-srd": "SRD-05VDC-SL-C",
}


def test_every_known_part_number_has_a_manufacturer():
    for pid, mpn in EXPECTED.items():
        part = parts.get(pid)
        assert part["mpn"] == mpn, f"{pid}: expected {mpn}, got {part['mpn']!r}"
        assert part["mfr"], f"{pid}: an MPN without a manufacturer is half a part"


def test_the_part_number_matches_the_footprint_family():
    """A TO-220 regulator is not an SOIC one — the package is the cross-check."""
    families = {
        "d-sod123": "SOD-123",
        "d-schottky": "SMA",
        "mmbt3904": "SOT-23",
        "ams1117-33": "SOT-223",
        "lm7805": "TO-220",
        "ne555": "SOIC-8",
        "ne555-dip": "DIP-8",
        "uln2003": "SOIC-16",
        "74hc595": "SOIC-16",
        "pc817": "DIP-4",
        "attiny85": "DIP-8",
    }
    for pid, footprint in families.items():
        assert parts.get(pid)["footprint"] == footprint, pid


def test_passives_and_modules_stay_blank_on_purpose():
    """No guesswork: a value-dependent part gets a search link, not a fake MPN."""
    for pid in ("r-0805", "c-0603", "led-0603", "header-2x4", "pico", "bme280-brk",
                "crystal-3225", "buzzer-12"):
        assert parts.get(pid)["mpn"] == "", pid


def test_the_bom_carries_the_library_part_number():
    board = templates.instantiate("nano-relay")
    rows = {r["value"]: r for r in layers.bom(board)}
    diode = next(r for v, r in rows.items() if "4148" in v)
    assert diode["mpn"] == "1N4148W"
    assert diode["mfr"] == "Diodes Incorporated"
    relay = next(r for v, r in rows.items() if "SRD" in v)
    assert relay["mpn"] == "SRD-05VDC-SL-C"


def test_a_component_level_part_number_wins_over_the_library_one():
    """The same library part can be fitted with a different real part."""
    board = templates.instantiate("nano-relay")
    comp = next(c for c in board.data["components"] if c["part"] == "relay-srd")
    comp["mpn"] = "SRD-12VDC-SL-C"
    rows = {r["value"]: r for r in layers.bom(board)}
    relay = next(r for v, r in rows.items() if "SRD" in v)
    assert relay["mpn"] == "SRD-12VDC-SL-C"
