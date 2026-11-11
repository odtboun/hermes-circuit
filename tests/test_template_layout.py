"""Templates that ship a designed layout.

`pico-relay-4` is a real board, not a netlist: the placement is part of the design,
so instantiating it must give you the parts where the designer put them — and the
layout has to be physically possible before anyone routes it.
"""

from __future__ import annotations

from circuit_core import templates
from circuit_core.lib import footprints, parts


def _box(board, ref):
    comp = board.component(ref)
    fp = footprints.get(parts.get(comp["part"])["footprint"])
    w, h = fp["courtyard"]["w"], fp["courtyard"]["h"]
    if round(comp.get("rot", 0)) % 180 == 90:
        w, h = h, w
    return (comp["x"] - w / 2, comp["y"] - h / 2, comp["x"] + w / 2, comp["y"] + h / 2)


def test_every_part_is_placed():
    board = templates.instantiate("pico-relay-4")
    for comp in board.data["components"]:
        assert comp.get("x") is not None, f"{comp['ref']} has no position"


def test_no_two_parts_share_the_same_floor_space():
    board = templates.instantiate("pico-relay-4")
    refs = [c["ref"] for c in board.data["components"]]
    boxes = {ref: _box(board, ref) for ref in refs}
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            A, B = boxes[a], boxes[b]
            overlap_x = min(A[2], B[2]) - max(A[0], B[0])
            overlap_y = min(A[3], B[3]) - max(A[1], B[1])
            assert not (overlap_x > 0 and overlap_y > 0), f"{a} and {b} overlap"


def test_everything_is_on_the_board():
    board = templates.instantiate("pico-relay-4")
    w, h = board.board["width"], board.board["height"]
    for ref in [c["ref"] for c in board.data["components"]]:
        x0, y0, x1, y1 = _box(board, ref)
        assert x0 >= -0.01 and y0 >= -0.01 and x1 <= w + 0.01 and y1 <= h + 0.01, ref


def test_the_netlist_is_a_working_relay_controller():
    """Every channel: a GPIO through a resistor into the driver, out to the coil,
    and the contact on a terminal. Nothing floating, nothing half-wired."""
    board = templates.instantiate("pico-relay-4")
    pins = board.net_pins()
    for ch in range(1, 5):
        assert len(pins[f"N{ch}"]) == 3, f"N{ch}: GPIO, base resistor and LED resistor"
        assert len(pins[f"IN{ch}"]) == 2, f"IN{ch}: resistor to driver input"
        assert len(pins[f"OUT{ch}"]) == 2, f"OUT{ch}: driver output to coil"
        assert len(pins[f"COM{ch}"]) == 2, f"COM{ch}: contact to terminal"
        assert len(pins[f"NO{ch}"]) == 2, f"NO{ch}: contact to terminal"
    # the coil supply and the driver's clamp diodes share +5V
    assert any(p["ref"] == "U2" and p["num"] == "9" for p in pins["+5V"])
    # the fuse is in series with the input, the diode after it
    assert {p["ref"] for p in pins["VIN"]} == {"J1", "F1"}
    assert {p["ref"] for p in pins["VFUSED"]} == {"F1", "D1"}
