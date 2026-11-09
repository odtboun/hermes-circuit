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
    """SMD stencil apertures — top side only in this engine.

    Fiducials are excluded: they are bare copper dots for the pick-and-place
    camera, and a paste aperture over one would cover it in solder.
    """
    out = {"F.Paste": {"flashes": []}}
    fiducials = _refs_with_tag(board, "fiducial")
    for pad in board.world_pads():
        if pad["kind"] != "smd" or pad.get("layer") != "top":
            continue
        if pad["ref"] in fiducials:
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
    # Mask openings per silk side: silk must not print on exposed copper, and the
    # designator has to be placed where it actually fits.
    side_pads: Dict[str, List[tuple]] = {"F.SilkS": [], "B.SilkS": []}
    for pad in board.world_pads():
        if pad["kind"] == "npth":
            continue
        rect = (pad["x"] - pad["w"] / 2.0, pad["y"] - pad["h"] / 2.0,
                pad["x"] + pad["w"] / 2.0, pad["y"] + pad["h"] / 2.0)
        if pad["kind"] == "tht" or pad.get("layer", "top") == "top":
            side_pads["F.SilkS"].append(rect)
        if pad["kind"] == "tht" or pad.get("layer") == "bottom":
            side_pads["B.SilkS"].append(rect)

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
        # pin-1 marker: a small square inside the body at the corner nearest pin 1.
        # It used to be drawn centred on the pad, which printed silk on exposed
        # copper — fabs clip that away, so the marker silently vanished.
        pads = [p for p in fp["pads"] if p["kind"] != "npth"]
        if pads and body["w"] > 0 and body["h"] > 0:
            p1 = next((p for p in pads if p["num"] == "1"), pads[0])
            mx, my = geom.place((p1["x"], p1["y"]), c["x"], c["y"], c.get("rot", 0.0))
            # pull the point toward the body centre until it is inside the outline
            hw = body["w"] / 2.0 - 0.45
            hh = body["h"] / 2.0 - 0.45
            if hw > 0.2 and hh > 0.2:
                dx = max(-hw, min(hw, mx - c["x"]))
                dy = max(-hh, min(hh, my - c["y"]))
                rot = c.get("rot", 0.0)
                cx, cy = geom.place((dx, dy), c["x"], c["y"], rot)
                out[layer]["lines"].append({
                    "points": [[cx - 0.22, cy - 0.22], [cx + 0.22, cy - 0.22],
                               [cx + 0.22, cy + 0.22], [cx - 0.22, cy + 0.22], [cx - 0.22, cy - 0.22]],
                    "width": 0.1, "kind": "pin1", "ref": ref,
                })
        # designator above the body
        if body["h"] > 0:
            # A designator printed on a pad is clipped away by the fab, so pick an
            # anchor that is actually clear; if none is, leave it off rather than
            # ship silk that will disappear.
            strokes = None
            for ty in (c["y"] + body["h"] / 2.0 + 1.1, c["y"] - body["h"] / 2.0 - 1.1):
                candidate = stroke_text(ref, c["x"], ty, size=0.85, rot=c.get("rot", 0.0))
                if not _strokes_hit(candidate, side_pads[layer]):
                    strokes = candidate
                    break
            for pts in strokes or []:
                out[layer]["text"].append({"points": [list(p) for p in pts], "width": 0.12,
                                           "text": ref, "ref": ref})

    # Silkscreen must not print on exposed copper: clip every line against the
    # mask openings on its own side.
    for layer, rects in side_pads.items():
        clipped = []
        for line in out[layer]["lines"]:
            for a, b in _clip_line_to_pads(line["points"], line.get("width", 0.12) / 2, rects):
                clipped.append({**line, "points": [a, b]})
        out[layer]["lines"] = clipped
    return out


def _seg_rect_span(a, b, rect):
    """Parameter span of segment a→b inside an axis-aligned rect (Liang-Barsky)."""
    x0, y0, x1, y1 = rect
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    return (t0, t1) if t0 < t1 else None


def _clip_line_to_pads(points, half_width, pad_rects, mask_expansion=0.06):
    """Split a polyline into the pieces that fall outside every mask opening.

    Real fabrication clips silkscreen where it would print on exposed copper;
    doing it here means the gerbers match what the fab would ship, and the DRC
    check for silk-over-pad can stay at zero for generated boards.
    """
    if not pad_rects:
        return points
    grow = mask_expansion + half_width
    out = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        spans = []
        for rect in pad_rects:
            span = _seg_rect_span(a, b, (rect[0] - grow, rect[1] - grow,
                                         rect[2] + grow, rect[3] + grow))
            if span:
                spans.append(span)
        if not spans:
            out.append((a, b))
            continue
        spans.sort()
        cursor = 0.0
        for s0, s1 in spans:
            if s0 > cursor:
                out.append((_lerp(a, b, cursor), _lerp(a, b, s0)))
            cursor = max(cursor, s1)
        if cursor < 1.0:
            out.append((_lerp(a, b, cursor), _lerp(a, b, 1.0)))
    return out


def _strokes_hit(strokes, rects, margin: float = 0.13) -> bool:
    """Does any stroke of this text land on a mask opening?

    The margin covers the mask expansion plus half the stroke width, so a stroke
    that merely grazes an opening is treated as a hit — otherwise the designator
    passes this test and the DRC check (which does expand) still flags it.
    """
    for stroke in strokes or []:
        for i in range(len(stroke) - 1):
            for rect in rects:
                if _seg_rect_span(stroke[i], stroke[i + 1],
                                  (rect[0] - margin, rect[1] - margin,
                                   rect[2] + margin, rect[3] + margin)):
                    return True
    return False


def _lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


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


def _refs_with_tag(board: Board, tag: str) -> set:
    """Refs whose library part carries a tag (fiducials are copper, not parts)."""
    out = set()
    for c in board.data["components"]:
        try:
            if tag in (parts.get(c["part"]).get("tags") or []):
                out.add(c["ref"])
        except KeyError:
            continue
    return out


def bom(board: Board) -> List[dict]:
    groups: Dict[str, dict] = {}
    skip = _refs_with_tag(board, "fiducial")
    for c in board.data["components"]:
        if c["ref"] in skip:
            continue
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
    skip = _refs_with_tag(board, "fiducial")   # nothing to place: it is bare copper
    for c in board.data["components"]:
        if c["ref"] in skip:
            continue
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
    skip = _refs_with_tag(board, "fiducial")
    for c in board.data["components"]:
        if c["ref"] in skip:
            continue
        part = parts.get(c["part"])
        rows.append({
            "ref": c["ref"], "part": c["part"], "footprint": part["footprint"],
            "x": round(c.get("x") or 0.0, 3), "y": round(c.get("y") or 0.0, 3),
            "rot": round(c.get("rot", 0.0), 1), "side": "top",
        })
    rows.sort(key=lambda r: (r["side"], r["ref"]))
    return rows
