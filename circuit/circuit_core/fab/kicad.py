"""KiCad project export.

Writes a ``.kicad_pcb`` (KiCad 8 file format) plus a ``.kicad_pro`` shell so the
board opens directly in KiCad's PCB editor with real footprints, nets, tracks,
vias and an Edge.Cuts outline. The Y axis is flipped on the way out: KiCad's
board frame grows downwards, this engine's grows upwards.
"""

from __future__ import annotations

import json
import uuid
from typing import Dict, List, Sequence

from .. import geom
from ..lib import footprints, parts
from ..project import Board

_NS = uuid.UUID("6f6b1d2a-5f3e-4f4a-9a0e-1b0c8d7e6f50")


def _uid(*key) -> str:
    return str(uuid.uuid5(_NS, ":".join(str(k) for k in key)))


def _n(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _xy(board: Board, x: float, y: float) -> str:
    return f"{_n(x)} {_n(board.board['height'] - y)}"


def _pad_shape(pad: dict) -> str:
    return {"rect": "rect", "round": "circle", "oval": "oval"}.get(pad["shape"], "rect")


def kicad_pcb(board: Board) -> str:
    H = board.board["height"]
    nets = sorted(board.data["nets"])
    net_no = {name: i + 1 for i, name in enumerate(nets)}
    out: List[str] = []
    out.append('(kicad_pcb (version 20240108) (generator "circuit")')
    out.append("  (general (thickness %s) (legacy_teardrops no))" % _n(board.board["thickness"]))
    out.append('  (paper "A4")')
    out.append("  (layers")
    out.append('    (0 "F.Cu" signal)')
    out.append('    (31 "B.Cu" signal)')
    out.append('    (34 "B.Paste" user)')
    out.append('    (35 "F.Paste" user)')
    out.append('    (36 "B.SilkS" user "B.Silkscreen")')
    out.append('    (37 "F.SilkS" user "F.Silkscreen")')
    out.append('    (38 "B.Mask" user)')
    out.append('    (39 "F.Mask" user)')
    out.append('    (44 "Edge.Cuts" user)')
    out.append("  )")
    out.append("  (setup (pad_to_mask_clearance 0) (grid_origin 0 0))")
    out.append('  (net 0 "")')
    for name in nets:
        out.append(f'  (net {net_no[name]} "{name}")')

    for c in board.data["components"]:
        part = parts.get(c["part"])
        fp = footprints.get(part["footprint"])
        front = c.get("layer", "top") == "top"
        layer = "F.Cu" if front else "B.Cu"
        silk_layer = "F.SilkS" if front else "B.SilkS"
        out.append(f'  (footprint "circuit:{fp["name"]}" (layer "{layer}")')
        out.append(f'    (uuid "{_uid("fp", c["ref"])}")')
        out.append(f'    (at {_xy(board, c["x"], c["y"])} {_n(-c.get("rot", 0.0))})')
        out.append(
            f'    (property "Reference" "{c["ref"]}" (at 0 {_n(-(fp["body"]["h"] / 2 + 1.1))} 0)'
            f' (layer "{silk_layer}") (uuid "{_uid("ref", c["ref"])}")'
            f' (effects (font (size 0.85 0.85) (thickness 0.12))))')
        out.append(
            f'    (property "Value" "{c["value"]}" (at 0 {_n(fp["body"]["h"] / 2 + 2.1)} 0)'
            f' (layer "{silk_layer}") (uuid "{_uid("val", c["ref"])}")'
            f' (effects (font (size 0.85 0.85) (thickness 0.12)) hide))')
        out.append(f'    (attr {"smd" if all(p["kind"] != "tht" for p in fp["pads"]) else "through_hole"})')
        # body outline on silkscreen
        bw, bh = fp["body"]["w"], fp["body"]["h"]
        if bw > 0 and bh > 0:
            pts = [(-bw / 2 - 0.12, -bh / 2 - 0.12), (bw / 2 + 0.12, -bh / 2 - 0.12),
                   (bw / 2 + 0.12, bh / 2 + 0.12), (-bw / 2 - 0.12, bh / 2 + 0.12)]
            for i in range(4):
                a, b = pts[i], pts[(i + 1) % 4]
                out.append(
                    f'    (fp_line (start {_n(a[0])} {_n(a[1])}) (end {_n(b[0])} {_n(b[1])})'
                    f' (stroke (width 0.12) (type solid)) (layer "{silk_layer}"))')
        for pad in fp["pads"]:
            num = pad["num"]
            net = (c.get("nets") or {}).get(num)
            nref = f' (net {net_no[net]} "{net}")' if net else ""
            at = f'{_n(pad["x"])} {_n(-pad["y"])} {_n(-pad.get("rot", 0.0))}'
            size = f'{_n(pad["w"])} {_n(pad["h"])}'
            if pad["kind"] == "npth":
                out.append(
                    f'    (pad "{num}" np_thru_hole circle (at {at}) (size {_n(pad["w"])} {_n(pad["w"])})'
                    f' (drill {_n(pad["drill"])}) (layers "*.Cu" "*.Mask"))')
                continue
            if pad["kind"] == "tht":
                kind = "thru_hole"
                layers = '"*.Cu" "*.Mask"'
                drill = f' (drill {_n(pad["drill"])})'
            else:
                kind = "smd"
                layers = '"F.Cu" "F.Paste" "F.Mask"' if front else '"B.Cu" "B.Paste" "B.Mask"'
                drill = ""
            out.append(
                f'    (pad "{num}" {kind} {_pad_shape(pad)} (at {at}) (size {size}){drill}'
                f' (layers {layers}){nref} (uuid "{_uid("pad", c["ref"], num)}"))')
        out.append("  )")

    for net, runs in board.data.get("routes", {}).items():
        for run in runs:
            pts = run["points"]
            for a, b in zip(pts, pts[1:]):
                out.append(
                    f'  (segment (start {_xy(board, a[0], a[1])}) (end {_xy(board, b[0], b[1])})'
                    f' (width {_n(run.get("width", board.rules["trace_width"]))})'
                    f' (layer "{run["layer"]}") (net {net_no[net]}) (uuid "{_uid("seg", net, a, b)}"))')
    for v in board.data.get("vias", []):
        out.append(
            f'  (via (at {_xy(board, v["x"], v["y"])}) (size {_n(v["diameter"])})'
            f' (drill {_n(v["drill"])}) (layers "F.Cu" "B.Cu")'
            f' (net {net_no[v["net"]]}) (uuid "{_uid("via", v["net"], v["x"], v["y"])}"))')

    outline = board.outline(10)
    pts = outline + [outline[0]]
    for a, b in zip(pts, pts[1:]):
        out.append(
            f'  (gr_line (start {_xy(board, a[0], a[1])}) (end {_xy(board, b[0], b[1])})'
            f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts")'
            f' (uuid "{_uid("edge", a, b)}"))')
    out.append(")")
    return "\n".join(out) + "\n"


def kicad_pro(board: Board, filename: str) -> str:
    doc = {
        "board": {
            "design_settings": {
                "defaults": {"board_outline_line_width": 0.1, "silk_line_width": 0.12},
                "rules": {
                    "min_clearance": board.rules.get("min_clearance", 0.15),
                    "min_track_width": board.rules.get("min_trace", 0.15),
                    "min_via_diameter": board.rules.get("via_diameter", 0.6),
                },
            },
            "layer_presets": [],
        },
        "meta": {"filename": filename, "version": 1},
        "net_settings": {"classes": [{"name": "Default", "clearance": board.rules["clearance"],
                                      "track_width": board.rules["trace_width"],
                                      "via_diameter": board.rules["via_diameter"],
                                      "via_drill": board.rules["via_drill"]}]},
        "sheets": [["00000000-0000-0000-0000-000000000000", "Root"]],
    }
    return json.dumps(doc, indent=2)
