"""Per-layer geometry, shared by every exporter and the viewer.

One function decides what copper/mask/silk exists on the board; Gerber, KiCad,
STEP, SVG and the desktop view model all read that same description, so the
files you download and the picture in the chat can never disagree.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from . import geom
from .lib import footprints, parts
from .project import Board

# --------------------------------------------------------------------------- #
# stroke font (uppercase + digits) — used for silkscreen designators
# --------------------------------------------------------------------------- #
_G: Dict[str, List[List[Tuple[int, int]]]] = {
    "A": [[(0, 0), (0, 4), (2, 6), (4, 4), (4, 0)], [(0, 2), (4, 2)]],
    "B": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)], [(3, 3), (4, 2), (4, 1), (3, 0), (0, 0)]],
    "C": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1)]],
    "D": [[(0, 0), (0, 6), (2, 6), (4, 4), (4, 2), (2, 0), (0, 0)]],
    "E": [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    "F": [[(0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "G": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (2, 3)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 0), (3, 0)], [(2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "J": [[(3, 6), (3, 1), (2, 0), (1, 0), (0, 1)]],
    "K": [[(0, 0), (0, 6)], [(4, 6), (0, 2)], [(1, 3), (4, 0)]],
    "L": [[(0, 6), (0, 0), (4, 0)]],
    "M": [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    "N": [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    "O": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]],
    "P": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 3), (3, 2), (0, 2)]],
    "Q": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)], [(2, 2), (4, 0)]],
    "R": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 3), (3, 2), (0, 2)], [(2, 2), (4, 0)]],
    "S": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "T": [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    "U": [[(0, 6), (0, 1), (1, 0), (3, 0), (4, 1), (4, 6)]],
    "V": [[(0, 6), (2, 0), (4, 6)]],
    "W": [[(0, 6), (1, 0), (2, 4), (3, 0), (4, 6)]],
    "X": [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    "Y": [[(0, 6), (2, 3), (4, 6)], [(2, 3), (2, 0)]],
    "Z": [[(0, 6), (4, 6), (0, 0), (4, 0)]],
    "0": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)], [(0, 1), (4, 5)]],
    "1": [[(1, 5), (2, 6), (2, 0)]],
    "2": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 0), (4, 0)]],
    "3": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (2, 3)], [(3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "4": [[(3, 0), (3, 6), (0, 2), (4, 2)]],
    "5": [[(4, 6), (0, 6), (0, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "6": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    "7": [[(0, 6), (4, 6), (1, 0)]],
    "8": [[(1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3)]],
    "9": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (4, 3)]],
    "-": [[(1, 3), (3, 3)]],
    "+": [[(1, 3), (3, 3)], [(2, 2), (2, 4)]],
    ".": [[(2, 0), (2, 1)]],
    "/": [[(0, 0), (4, 6)]],
    " ": [],
}


def stroke_text(text: str, x: float, y: float, size: float = 1.0, rot: float = 0.0,
                anchor: str = "center") -> List[List[geom.Point]]:
    """Vector strokes for ``text``; ``size`` is cap height in mm."""
    text = text.upper()
    width = 0.0
    adv = 6.0 * size / 6.0
    total = (len(text) - 1) * adv if text else 0.0
    width = total * 0.9 + 4.0 * size / 6.0
    if anchor == "left":
        cx = 0.0
    elif anchor == "right":
        cx = -width
    else:
        cx = -width / 2.0
    scale = size / 6.0
    out: List[List[geom.Point]] = []
    for ch in text:
        glyph = _G.get(ch, _G[" "])
        for stroke in glyph:
            pts = []
            for gx, gy in stroke:
                lx = cx + gx * scale
                ly = -size / 2.0 + gy * scale
                pts.append(geom.place((lx, ly), x, y, rot))
            if len(pts) >= 2:
                out.append(pts)
        cx += adv * 0.9
    return out


# --------------------------------------------------------------------------- #
# layer builders
# --------------------------------------------------------------------------- #
def copper(board: Board) -> Dict[str, dict]:
    layers: Dict[str, dict] = {l: {"flashes": [], "draws": []} for l in ("F.Cu", "B.Cu")}
    for pad in board.world_pads():
        if pad["kind"] == "npth":
            continue
        targets = ["F.Cu", "B.Cu"] if pad["kind"] == "tht" else (
            ["F.Cu"] if pad.get("layer") == "top" else ["B.Cu"])
        for layer in targets:
            layers[layer]["flashes"].append({
                "shape": pad["shape"], "x": pad["x"], "y": pad["y"],
                "w": pad["w"], "h": pad["h"], "rot": pad.get("rot", 0.0),
                "net": pad["net"], "ref": pad["ref"], "pin": pad["num"],
                "name": pad["name"], "drill": pad.get("drill", 0.0),
            })
    for net, runs in board.data.get("routes", {}).items():
        for run in runs:
            layers[run["layer"]]["draws"].append({
                "points": [list(p) for p in run["points"]],
                "width": run.get("width", board.rules["trace_width"]),
                "net": net,
            })
    for v in board.data.get("vias", []):
        for layer in ("F.Cu", "B.Cu"):
            layers[layer]["flashes"].append({
                "shape": "round", "x": v["x"], "y": v["y"],
                "w": v["diameter"], "h": v["diameter"], "rot": 0.0,
                "net": v["net"], "ref": "VIA", "pin": "", "name": "",
                "drill": v["drill"],
            })
    return layers


def mask(board: Board, expansion: float = 0.06) -> Dict[str, dict]:
    """Soldermask openings: every exposed pad, and — unless the board tents them —
    every via.

    Vias used to get an opening like any other flash, which leaves them exposed to
    the solder wave and to paste slump under a stencil. Tenting (mask over the
    via) is standard practice and is the default; set ``tent_vias: false`` in the
    board rules to keep them open (probe points, thermal vias that must be
    filled).
    """
    out = {"F.Mask": {"flashes": []}, "B.Mask": {"flashes": []}}
    tent = board.rules.get("tent_vias", True)
    for layer in ("F.Cu", "B.Cu"):
        for f in copper(board)[layer]["flashes"]:
            if tent and f.get("ref") == "VIA":
                continue
            out[layer.replace("Cu", "Mask")]["flashes"].append({
                **f, "w": f["w"] + 2 * expansion, "h": f["h"] + 2 * expansion,
            })
    return out


def paste(board: Board, margin: float = 0.0) -> Dict[str, dict]:
    """SMD stencil apertures — top side only in this engine."""
    out = {"F.Paste": {"flashes": []}}
    for pad in board.world_pads():
        if pad["kind"] != "smd" or pad.get("layer") != "top":
            continue
        out["F.Paste"]["flashes"].append({
            "shape": pad["shape"], "x": pad["x"], "y": pad["y"],
            "w": max(0.1, pad["w"] - 2 * margin), "h": max(0.1, pad["h"] - 2 * margin),
            "rot": pad.get("rot", 0.0), "net": pad["net"], "ref": pad["ref"],
            "pin": pad["num"], "name": pad["name"], "drill": 0.0,
        })
    return out


def silk(board: Board) -> Dict[str, dict]:
    out = {"F.SilkS": {"lines": [], "text": []}, "B.SilkS": {"lines": [], "text": []}}
    for c in board.data["components"]:
        if c.get("x") is None:
            continue
        part = parts.get(c["part"])
        fp = footprints.get(part["footprint"])
        body = fp["body"]
        front = c.get("layer", "top") == "top"
        layer = "F.SilkS" if front else "B.SilkS"
        ref = c["ref"]
        if body["w"] > 0 and body["h"] > 0:
            w, h = body["w"] + 0.25, body["h"] + 0.25
            local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2), (-w / 2, -h / 2)]
            pts = [geom.place(p, c["x"], c["y"], c.get("rot", 0.0)) for p in local]
            out[layer]["lines"].append({"points": [list(p) for p in pts], "width": 0.12,
                                        "kind": "body", "ref": ref})
        # pin-1 marker
        pads = [p for p in fp["pads"] if p["kind"] != "npth"]
        if pads:
            p1 = next((p for p in pads if p["num"] == "1"), pads[0])
            mx, my = geom.place((p1["x"], p1["y"]), c["x"], c["y"], c.get("rot", 0.0))
            out[layer]["lines"].append({
                "points": [[mx - 0.25, my - 0.25], [mx + 0.25, my - 0.25],
                           [mx + 0.25, my + 0.25], [mx - 0.25, my + 0.25], [mx - 0.25, my - 0.25]],
                "width": 0.1, "kind": "pin1", "ref": ref,
            })
        # designator above the body
        ty = c["y"] + (body["h"] / 2.0 + 1.1) if body["h"] > 0 else c["y"]
        for idx, pts in enumerate(stroke_text(ref, c["x"], ty, size=0.85,
                                              rot=c.get("rot", 0.0))):
            out[layer]["text"].append({"points": [list(p) for p in pts], "width": 0.12,
                                       "text": ref, "ref": ref})
    return out


def outline(board: Board) -> List[List[List[float]]]:
    pts = board.outline(10)
    return [[[round(p[0], 4), round(p[1], 4)] for p in pts + [pts[0]]]]


def drills(board: Board) -> List[dict]:
    out: List[dict] = []
    seen = set()
    for pad in board.world_pads():
        if not pad.get("drill"):
            continue
        key = (round(pad["x"], 2), round(pad["y"], 2), pad["drill"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"x": pad["x"], "y": pad["y"], "diameter": pad["drill"],
                    "plated": pad["kind"] == "tht", "ref": pad["ref"]})
    for v in board.data.get("vias", []):
        key = (round(v["x"], 2), round(v["y"], 2), v["drill"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"x": v["x"], "y": v["y"], "diameter": v["drill"], "plated": True,
                    "ref": "VIA"})
    return out


def bom(board: Board) -> List[dict]:
    groups: Dict[str, dict] = {}
    for c in board.data["components"]:
        part = parts.get(c["part"])
        key = (c["part"], c["value"])
        g = groups.setdefault(key, {
            "part": c["part"], "value": c["value"], "footprint": part["footprint"],
            "description": part["name"], "refs": [], "qty": 0,
            # A component can carry its own supplier part number; the library value
            # is only a default. Blank means "not known" — never invented.
            "mpn": c.get("mpn") or part.get("mpn", ""),
            "mfr": c.get("mfr") or part.get("mfr", ""),
        })
        g["refs"].append(c["ref"])
        g["qty"] += 1
    rows = list(groups.values())
    for r in rows:
        r["refs"] = sorted(r["refs"])
    rows.sort(key=lambda r: (r["refs"][0][0], r["refs"][0]))
    return rows


def placement_assembly(board: Board) -> List[dict]:
    """Pick-and-place in the dialect assembly houses actually take.

    Millimetres, origin bottom-left, Y measured upwards from the bottom edge
    (this engine's Y already grows upwards, so the value is flipped relative to a
    fab's top-down frame), layer named Top/Bottom. Bottom-side parts are mirrored
    the way JLCPCB documents: X mirrored about the board centre and the rotation
    reflected. A generic pos.csv is still written next to it.
    """
    rows = []
    h = board.board["height"]
    w = board.board["width"]
    for c in board.data["components"]:
        part = parts.get(c["part"])
        side = c.get("side", "top")
        x = c.get("x") or 0.0
        y = c.get("y") or 0.0
        rot = c.get("rot", 0.0)
        if side == "bottom":
            mx = w - x
            rot = (180.0 - rot) % 360.0
        else:
            mx = x
        rows.append({
            "ref": c["ref"], "value": c["value"], "footprint": part["footprint"],
            "mx": round(mx, 3), "my": round(h - y, 3),
            "side": side, "rot": round(rot, 1),
        })
    rows.sort(key=lambda r: (r["side"], r["ref"]))
    return rows


def placement(board: Board) -> List[dict]:
    rows = []
    for c in board.data["components"]:
        part = parts.get(c["part"])
        rows.append({
            "ref": c["ref"], "part": c["part"], "footprint": part["footprint"],
            "x": round(c.get("x") or 0.0, 3), "y": round(c.get("y") or 0.0, 3),
            "rot": round(c.get("rot", 0.0), 1), "side": "top",
        })
    rows.sort(key=lambda r: (r["side"], r["ref"]))
    return rows
