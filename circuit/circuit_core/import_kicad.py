"""Import an existing KiCad board as a read-only Circuit project.

The importer reads the ``.kicad_pcb`` s-expression format (KiCad 6/7/8, plus the
newer files that name nets inline) and builds the view document directly: pads
become copper flashes, tracks become draws, footprint silk becomes silk, and the
``Edge.Cuts`` outline becomes the board outline. Nothing is re-placed, re-routed
or design-rule checked — an imported board is a picture of somebody else's
design, not a project this engine owns.

Coordinate systems: KiCad's board frame is Y-down with an arbitrary origin, the
engine's is Y-up with the origin at the board's bottom-left corner. Everything
is translated to the outline's bounding box and mirrored in Y on the way in, and
rotations are negated to match that mirror.
"""

from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import store
from .layers import stroke_text
from .project import DEFAULT_RULES, NET_CLASS_WIDTH, Board, BoardError, net_class

Point = Tuple[float, float]

EDGE_LAYER = "Edge.Cuts"
SILK_LAYERS = ("F.SilkS", "B.SilkS")

#: KiCad pad shape -> engine pad shape.
PAD_SHAPES = {
    "circle": "round", "oval": "oval", "rect": "rect", "roundrect": "roundrect",
    "trapezoid": "rect", "chamfered_rect": "rect", "custom": "rect", "connect": "round",
}

#: KiCad pad type -> engine pad kind.
THT_TYPES = {"thru_hole", "connect"}

_ARC_STEP = 0.2      # mm between flattened arc vertices
_CHAIN_TOL = 0.05    # mm tolerance when stitching outline segments


# --------------------------------------------------------------------------- #
# s-expression reader
# --------------------------------------------------------------------------- #
class _Str(str):
    """A quoted string atom, kept distinct from a bare symbol."""


def _tokenize(text: str) -> List[str]:
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "()":
            out.append(ch)
            i += 1
        elif ch == '"':
            i += 1
            buf: List[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            out.append(_Str("".join(buf)))
        elif ch.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            out.append(text[i:j])
            i = j
    return out


class _Reader:
    def __init__(self, tokens: Sequence[str]):
        self.tokens = tokens
        self.i = 0

    def node(self) -> list:
        if self.i >= len(self.tokens) or self.tokens[self.i] != "(":
            raise BoardError("malformed KiCad file: expected '('")
        self.i += 1
        out: list = []
        while self.i < len(self.tokens):
            tok = self.tokens[self.i]
            if tok == "(":
                out.append(self.node())
            elif tok == ")":
                self.i += 1
                return out
            else:
                out.append(tok)
                self.i += 1
        raise BoardError("malformed KiCad file: unbalanced parentheses")


def parse_sexpr(text: str) -> list:
    """Parse a KiCad s-expression document into nested lists."""
    reader = _Reader(_tokenize(text))
    while reader.i < len(reader.tokens) and reader.tokens[reader.i] != "(":
        reader.i += 1
    return reader.node()


def _head(node) -> str:
    if isinstance(node, list) and node and isinstance(node[0], str) and not isinstance(node[0], _Str):
        return str(node[0])
    return ""


def _child(node: list, name: str) -> Optional[list]:
    for item in node[1:]:
        if isinstance(item, list) and _head(item) == name:
            return item
    return None


def _children(node: list, name: str) -> List[list]:
    return [c for c in node[1:] if isinstance(c, list) and _head(c) == name]


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point(node: Optional[list], default: Point = (0.0, 0.0)) -> Point:
    if not node or len(node) < 3:
        return default
    return (_num(node[1]), _num(node[2]))


def _xy_list(node: Optional[list]) -> List[Point]:
    """``(pts (xy 1 2) (xy 3 4))`` -> points."""
    if not node:
        return []
    return [_point(c) for c in _children(node, "xy")]


def _stroke_width(node: list, default: float = 0.12) -> float:
    stroke = _child(node, "stroke")
    if stroke is not None:
        width = _child(stroke, "width")
        if width is not None and len(width) > 1:
            return _num(width[1], default)
    width = _child(node, "width")
    if width is not None and len(width) > 1:
        return _num(width[1], default)
    return default


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def arc_points(start: Point, mid: Point, end: Point, step: float = _ARC_STEP) -> List[Point]:
    """Flatten a three-point arc into a polyline, passing through ``mid``."""
    ax, ay = start
    bx, by = mid
    cx, cy = end
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:                      # collinear: a straight segment
        return [start, end]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    if r < 1e-9:
        return [start, end]
    a0 = math.atan2(ay - uy, ax - ux)
    a1 = math.atan2(by - uy, bx - ux)
    a2a = math.atan2(cy - uy, cx - ux)
    sweep = (a2a - a0) % (2.0 * math.pi)
    if (a1 - a0) % (2.0 * math.pi) > sweep:      # mid is on the other side
        sweep -= 2.0 * math.pi
    steps = max(2, int(abs(sweep) * r / max(step, 1e-3)))
    pts = [(ux + r * math.cos(a0 + sweep * i / steps),
            uy + r * math.sin(a0 + sweep * i / steps)) for i in range(steps + 1)]
    pts[0], pts[-1] = start, end          # exact endpoints keep chaining exact
    return pts


def circle_points(center: Point, edge: Point, step: float = _ARC_STEP) -> List[Point]:
    r = _dist(center, edge)
    if r < 1e-9:
        return []
    steps = max(8, int(2.0 * math.pi * r / max(step, 1e-3)))
    return [(center[0] + r * math.cos(2.0 * math.pi * i / steps),
             center[1] + r * math.sin(2.0 * math.pi * i / steps)) for i in range(steps)]


def _rect_points(start: Point, end: Point) -> List[Point]:
    x0, x1 = sorted((start[0], end[0]))
    y0, y1 = sorted((start[1], end[1]))
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _simplify(points: Sequence[Point], eps: float = 1e-4) -> List[Point]:
    """Drop duplicate and collinear vertices from a polyline."""
    pts: List[Point] = []
    for p in points:
        if not pts or _dist(p, pts[-1]) > eps:
            pts.append(p)
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > 1e-6:
            out.append(b)
    out.append(pts[-1])
    return out


def chain_loops(polylines: Sequence[Sequence[Point]], tol: float = _CHAIN_TOL) -> List[List[Point]]:
    """Stitch loose edge segments into closed (or open) polylines."""
    remaining = [list(p) for p in polylines if len(p) >= 2]
    loops: List[List[Point]] = []
    while remaining:
        cur = remaining.pop(0)
        merged = True
        while merged:
            merged = False
            for i, seg in enumerate(remaining):
                if _dist(seg[0], cur[-1]) <= tol:
                    cur.extend(seg[1:])
                elif _dist(seg[-1], cur[-1]) <= tol:
                    cur.extend(reversed(seg[:-1]))
                elif _dist(seg[-1], cur[0]) <= tol:
                    cur = seg[:-1] + cur
                elif _dist(seg[0], cur[0]) <= tol:
                    cur = list(reversed(seg[1:])) + cur
                else:
                    continue
                remaining.pop(i)
                merged = True
                break
        if len(cur) > 2 and _dist(cur[0], cur[-1]) <= tol:
            cur = cur[:-1]
        loops.append(cur)
    return loops


def _loop_area(points: Sequence[Point]) -> float:
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _kicad_place(local: Point, origin: Point, rot: float) -> Point:
    """Footprint-local -> board coordinates, in KiCad's Y-down frame."""
    if not rot:
        return (origin[0] + local[0], origin[1] + local[1])
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    return (origin[0] + local[0] * c + local[1] * s,
            origin[1] - local[0] * s + local[1] * c)


def _kicad_unplace(world: Point, origin: Point, rot: float) -> Point:
    return _kicad_place((world[0] - origin[0], world[1] - origin[1]), (0.0, 0.0), -rot)


# --------------------------------------------------------------------------- #
# board parsing
# --------------------------------------------------------------------------- #
class _Frame:
    """KiCad board frame -> engine board frame (translate, mirror Y)."""

    def __init__(self, min_x: float, max_y: float):
        self.min_x = min_x
        self.max_y = max_y

    def point(self, p: Point) -> Point:
        return (round(p[0] - self.min_x, 3), round(self.max_y - p[1], 3))

    def points(self, pts: Sequence[Point]) -> List[List[float]]:
        return [[self.point(p)[0], self.point(p)[1]] for p in pts]


def _pad_drill(pad: list) -> float:
    drill = _child(pad, "drill")
    if drill is None:
        return 0.0
    vals: List[float] = []
    for v in drill[1:]:
        if isinstance(v, list) or isinstance(v, _Str):
            continue
        if v == "oval":
            continue
        try:
            vals.append(float(v))
        except ValueError:
            continue
    return max(vals) if vals else 0.0


def _net_name(node: list, net_table: Dict[int, str]) -> Optional[str]:
    """Net of a pad/track/via: ``(net 1 "GND")``, ``(net "GND")`` or ``(net 2)``."""
    net = _child(node, "net")
    if net is None:
        return None
    vals = net[1:]
    if len(vals) >= 2:
        name = str(vals[1])
        return name or None
    if not vals:
        return None
    value = vals[0]
    if isinstance(value, _Str):
        return str(value) or None
    try:
        return net_table.get(int(float(value)))
    except (TypeError, ValueError):
        return None


def _pad_shape(pad: list) -> str:
    raw = str(pad[3]) if len(pad) > 3 and isinstance(pad[3], str) else "rect"
    return PAD_SHAPES.get(raw, "rect")


def _footprint_ref(fp: list) -> Tuple[str, str]:
    """(reference, value) — KiCad 6-8 ``fp_text`` or KiCad 9+ ``property``."""
    ref, value = "", ""
    for text in _children(fp, "fp_text"):
        if len(text) < 3:
            continue
        kind = str(text[1])
        if kind == "reference":
            ref = str(text[2])
        elif kind == "value":
            value = str(text[2])
    for prop in _children(fp, "property"):
        if len(prop) < 3:
            continue
        kind = str(prop[1])
        if kind == "Reference" and not ref:
            ref = str(prop[2])
        elif kind == "Value" and not value:
            value = str(prop[2])
    return ref, value


def _silk_polylines(fp: list) -> List[Tuple[str, List[Point], float]]:
    """Footprint-local silk polylines as ``(layer, points, width)``."""
    out: List[Tuple[str, List[Point], float]] = []
    for kind in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for item in _children(fp, kind):
            layer = _child(item, "layer")
            name = str(layer[1]) if layer and len(layer) > 1 else ""
            if name not in SILK_LAYERS:
                continue
            width = _stroke_width(item)
            if kind == "fp_line":
                pts = [_point(_child(item, "start")), _point(_child(item, "end"))]
            elif kind == "fp_rect":
                pts = _rect_points(_point(_child(item, "start")), _point(_child(item, "end")))
                pts.append(pts[0])
            elif kind == "fp_circle":
                pts = circle_points(_point(_child(item, "center")), _point(_child(item, "end")))
                if pts:
                    pts.append(pts[0])
            elif kind == "fp_arc":
                pts = arc_points(_point(_child(item, "start")),
                                 _point(_child(item, "mid")),
                                 _point(_child(item, "end")))
            else:  # fp_poly
                pts = _xy_list(_child(item, "pts"))
                if len(pts) > 2:
                    pts.append(pts[0])
            if len(pts) >= 2:
                out.append((name, pts, width))
    return out


def parse_board(path: Path) -> Tuple[Board, dict, List[str]]:
    """Parse ``path`` into a board document and its view document."""
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        raise BoardError(f"cannot read {path}: {exc}") from exc
    root = parse_sexpr(text)
    if _head(root) not in ("kicad_pcb", "module"):
        raise BoardError(f"{path.name} is not a KiCad board (no kicad_pcb header)")

    warnings: List[str] = []

    # ---- net table -------------------------------------------------------
    net_table: Dict[int, str] = {}
    for node in _children(root, "net"):
        vals = [v for v in node[1:] if not isinstance(v, list)]
        if len(vals) >= 2:
            net_table[int(_num(vals[0], -1))] = str(vals[1])
        elif vals:
            net_table[int(_num(vals[0], -1))] = ""

    # ---- outline ---------------------------------------------------------
    edges: List[List[Point]] = []
    for node in root[1:]:
        if not isinstance(node, list):
            continue
        layer = _child(node, "layer")
        if not layer or len(layer) < 2 or str(layer[1]) != EDGE_LAYER:
            continue
        kind = _head(node)
        if kind == "gr_line":
            edges.append([_point(_child(node, "start")), _point(_child(node, "end"))])
        elif kind == "gr_rect":
            pts = _rect_points(_point(_child(node, "start")), _point(_child(node, "end")))
            edges.append(pts + [pts[0]])
        elif kind == "gr_circle":
            pts = circle_points(_point(_child(node, "center")), _point(_child(node, "end")))
            if pts:
                edges.append(pts + [pts[0]])
        elif kind == "gr_arc":
            start = _point(_child(node, "start"))
            mid = _point(_child(node, "mid"))
            end = _point(_child(node, "end"))
            if _child(node, "mid") is not None:
                edges.append(arc_points(start, mid, end))
            else:  # legacy centre/start/angle arc
                angle = _num((_child(node, "angle") or [0, 0])[1], 0.0)
                radius = _dist(start, end)
                steps = max(2, int(abs(math.radians(angle)) * radius / _ARC_STEP))
                a0 = math.atan2(end[1] - start[1], end[0] - start[0])
                edges.append([(start[0] + radius * math.cos(a0 + math.radians(angle) * i / steps),
                               start[1] + radius * math.sin(a0 + math.radians(angle) * i / steps))
                              for i in range(steps + 1)])
        elif kind == "gr_poly":
            pts = _xy_list(_child(node, "pts"))
            if len(pts) > 2:
                edges.append(pts + [pts[0]])
        elif kind == "gr_curve":
            pts = [_point(_child(node, "start")), _point(_child(node, "end"))]
            if len(pts) == 2:
                edges.append(pts)

    loops = [loop for loop in chain_loops(edges) if len(loop) >= 3]
    if loops:
        loops.sort(key=_loop_area, reverse=True)
        outline = _simplify(loops[0])
        if len(loops) > 1:
            warnings.append(f"{len(loops) - 1} extra Edge.Cuts loop(s) ignored")
    else:
        outline = []
        warnings.append("no Edge.Cuts outline — board size taken from copper extents")

    # ---- footprints ------------------------------------------------------
    comps: List[dict] = []
    silk_out: Dict[str, dict] = {name: {"lines": [], "text": []} for name in SILK_LAYERS}
    pad_rows: List[dict] = []          # pads, in KiCad coordinates
    drill_rows: List[dict] = []
    net_pins: Dict[str, List[str]] = {}
    fp_nodes = _children(root, "footprint") + _children(root, "module")

    for index, fp in enumerate(fp_nodes):
        lib = str(fp[1]) if len(fp) > 1 and isinstance(fp[1], str) else f"footprint-{index + 1}"
        at = _child(fp, "at")
        origin = _point(at)
        rot = _num(at[3], 0.0) if at and len(at) > 3 else 0.0
        layer_node = _child(fp, "layer")
        side = "bottom" if layer_node and len(layer_node) > 1 and str(layer_node[1]) == "B.Cu" else "top"
        ref, value = _footprint_ref(fp)
        if not ref:
            ref = f"FP{index + 1}"
            warnings.append(f"footprint {lib} has no reference designator (named {ref})")

        pins: List[dict] = []
        local_pts: List[Point] = []
        pad_count = 0
        for pad in _children(fp, "pad"):
            pad_count += 1
            num = str(pad[1]) if len(pad) > 1 and isinstance(pad[1], str) else ""
            ptype = str(pad[2]) if len(pad) > 2 and isinstance(pad[2], str) else "smd"
            pad_at = _child(pad, "at")
            local = _point(pad_at)
            angle = _num(pad_at[3], 0.0) if pad_at and len(pad_at) > 3 else 0.0
            size = _child(pad, "size")
            w = _num(size[1], 0.0) if size and len(size) > 1 else 0.0
            h = _num(size[2], w) if size and len(size) > 2 else w
            shape = _pad_shape(pad)
            drill = _pad_drill(pad)
            kind = "npth" if ptype == "npth" else ("tht" if (ptype in THT_TYPES or drill) else "smd")
            layers_node = _child(pad, "layers")
            pad_layers = [str(v) for v in (layers_node[1:] if layers_node else [])
                          if not isinstance(v, list)]
            both = "*.Cu" in pad_layers or "F&B.Cu" in pad_layers
            on_f = both or "F.Cu" in pad_layers
            on_b = both or "B.Cu" in pad_layers
            if not on_f and not on_b:
                on_f, on_b = side == "top", side == "bottom"
            net = _net_name(pad, net_table)
            if kind == "npth":
                net = None
            world = _kicad_place(local, origin, rot)
            pad_rot = (-angle) % 360.0

            pad_rows.append({"x": world[0], "y": world[1], "w": w, "h": h,
                             "shape": shape, "rot": pad_rot, "drill": drill,
                             "kind": kind, "net": net, "layers": (on_f, on_b),
                             "ref": ref, "pin": num})
            if drill > 0:
                drill_rows.append({"x": world[0], "y": world[1], "d": drill,
                                   "plated": kind != "npth", "ref": ref})
            if num:
                pins.append({"num": num, "name": num, "net": net,
                             "x": world[0], "y": world[1], "w": w, "h": h,
                             "shape": shape, "rot": pad_rot, "drill": drill, "kind": kind})
                if net:
                    net_pins.setdefault(net, []).append(f"{ref}.{num}")

            # body extent in the footprint's own frame
            lx, ly = _kicad_unplace(world, origin, rot)
            if shape == "round":
                hw = hh = w / 2.0
            else:
                a = math.radians(angle - rot)
                c, s = abs(math.cos(a)), abs(math.sin(a))
                hw, hh = (w * c + h * s) / 2.0, (w * s + h * c) / 2.0
            local_pts.extend([(lx - hw, ly - hh), (lx + hw, ly + hh)])

        silk_pts: List[Point] = []
        for layer_name, pts, width in _silk_polylines(fp):
            silk_pts.extend(pts)
            local_pts.extend(pts)
            world_pts = [_kicad_place(p, origin, rot) for p in pts]
            silk_out[layer_name]["lines"].append({
                "points": [[round(p[0], 3), round(p[1], 3)] for p in world_pts],
                "width": round(width, 3), "kind": "footprint", "ref": ref,
            })

        # A footprint with no pads is a drawing, not a part: ESD signs, logos,
        # fiducials-as-art. Its silk is already in the silk layer, so emitting a
        # component here would give the board a body box the size of the graphic
        # (one sample carried a 92 x 98 mm "component" on a 28 mm wide board).
        if pad_count == 0:
            continue

        # Body extent. Pads alone would swallow the part's own terminations (a
        # footprint's pad row IS its widest feature), which is why imported boards
        # showed no metal at all. When the silkscreen outline covers most of the
        # pad box it is the real part body, so prefer it and let the pads stick
        # out the way they do on a real board.
        pad_box = _bbox(local_pts) if pad_count else None
        silk_box = _bbox(silk_pts) if silk_pts else None
        box = None
        if pad_box and silk_box:
            pad_area = max(1e-6, (pad_box[2] - pad_box[0]) * (pad_box[3] - pad_box[1]))
            silk_area = (silk_box[2] - silk_box[0]) * (silk_box[3] - silk_box[1])
            box = silk_box if 0.6 * pad_area <= silk_area <= 1.6 * pad_area else _union(pad_box, silk_box)
        elif pad_box or silk_box:
            box = pad_box or silk_box
        if box:
            bw, bh = box[2] - box[0], box[3] - box[1]
            centre = _kicad_place(((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0), origin, rot)
        else:
            bw = bh = 0.0
            centre = origin
        comps.append({
            "ref": ref, "part": f"kicad:{lib}", "value": value or lib.split(":")[-1],
            "category": "imported", "footprint": lib,
            "x": centre[0], "y": centre[1], "rot": (-rot) % 360.0, "side": side,
            "body": {"w": round(bw, 3), "h": round(bh, 3),
                     "z": 1.0 if any(p["kind"] == "tht" for p in pins) else 0.45,
                     "color": "default"},
            "pins": pins,
        })

    # ---- tracks and vias -------------------------------------------------
    tracks: List[dict] = []
    vias: List[dict] = []
    for node in root[1:]:
        if not isinstance(node, list):
            continue
        kind = _head(node)
        if kind == "segment":
            tracks.append({"points": [_point(_child(node, "start")), _point(_child(node, "end"))],
                           "width": _num((_child(node, "width") or [0, 0.25])[1], 0.25),
                           "layer": str((_child(node, "layer") or ["", "F.Cu"])[1]),
                           "net": _net_name(node, net_table)})
        elif kind == "arc":
            layer = _child(node, "layer")
            if not layer or len(layer) < 2 or str(layer[1]) not in ("F.Cu", "B.Cu"):
                continue
            tracks.append({"points": arc_points(_point(_child(node, "start")),
                                                _point(_child(node, "mid")),
                                                _point(_child(node, "end"))),
                           "width": _num((_child(node, "width") or [0, 0.25])[1], 0.25),
                           "layer": str(layer[1]), "net": _net_name(node, net_table)})
        elif kind == "via":
            at = _child(node, "at")
            size = _child(node, "size")
            drill = _child(node, "drill")
            vias.append({"x": _point(at)[0], "y": _point(at)[1],
                         "size": _num(size[1], 0.6) if size and len(size) > 1 else 0.6,
                         "drill": _num(drill[1], 0.3) if drill and len(drill) > 1 else 0.3,
                         "net": _net_name(node, net_table)})

    # ---- frame -----------------------------------------------------------
    if outline:
        min_x = min(p[0] for p in outline)
        max_x = max(p[0] for p in outline)
        min_y = min(p[1] for p in outline)
        max_y = max(p[1] for p in outline)
    else:
        xs = [p["x"] for p in pad_rows] + [t["points"][0][0] for t in tracks] + [v["x"] for v in vias]
        ys = [p["y"] for p in pad_rows] + [t["points"][0][1] for t in tracks] + [v["y"] for v in vias]
        min_x, max_x = (min(xs), max(xs)) if xs else (0.0, 40.0)
        min_y, max_y = (min(ys), max(ys)) if ys else (0.0, 30.0)
        min_x, min_y = min_x - 2.0, min_y - 2.0
        max_x, max_y = max_x + 2.0, max_y + 2.0
        outline = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]

    width = round(max_x - min_x, 3)
    height = round(max_y - min_y, 3)
    if width < 1.0 or height < 1.0:
        raise BoardError(f"{path.name} has a degenerate outline ({width} x {height} mm)")
    frame = _Frame(min_x, max_y)

    # Silkscreen that sits entirely off the board is not part of it — one Olimex
    # board carries an ESD-sign graphic footprint 60 mm past a 28 mm-wide edge,
    # which made the whole board render tiny and off-centre. Real fabs clip
    # silkscreen to the outline; we drop the fully-outside items and keep the rest.
    silk_margin = 1.0
    lo_x, hi_x = min_x - silk_margin, max_x + silk_margin
    lo_y, hi_y = min_y - silk_margin, max_y + silk_margin

    def _inside(pt):
        return lo_x <= pt[0] <= hi_x and lo_y <= pt[1] <= hi_y

    def _clip_runs(pts):
        """Keep the maximal on-board runs of a polyline.

        Whole-item filtering is not enough: one board carries an ESD-sign
        footprint whose silkscreen is a single polyline spanning 60 mm past a
        28 mm-wide edge, so the item straddles the outline and has to be cut.
        """
        runs, run = [], []
        for pt in pts:
            if _inside(pt):
                run.append(pt)
            else:
                if len(run) >= 2:
                    runs.append(run)
                run = []
        if len(run) >= 2:
            runs.append(run)
        return runs

    dropped_silk = 0
    for layer in silk_out.values():
        kept_lines = []
        for line in layer["lines"]:
            runs = _clip_runs(line["points"])
            if not runs:
                dropped_silk += 1
                continue
            if len(runs) == 1 and len(runs[0]) == len(line["points"]):
                kept_lines.append(line)
                continue
            dropped_silk += 1
            for run in runs:
                kept_lines.append({**line, "points": run})
        layer["lines"] = kept_lines
        kept_text = []
        for item in layer["text"]:
            if not any(_inside(pt) for pt in item["points"]):
                dropped_silk += 1
                continue
            kept_text.append(item)
        layer["text"] = kept_text
    if dropped_silk:
        warnings.append(f"{dropped_silk} silkscreen item(s) outside the board outline dropped")

    # ---- copper ----------------------------------------------------------
    copper: Dict[str, dict] = {name: {"flashes": [], "draws": []} for name in ("F.Cu", "B.Cu")}
    for row in pad_rows:
        if row["kind"] == "npth":
            continue
        on_f, on_b = row["layers"]
        for name, active in (("F.Cu", on_f), ("B.Cu", on_b)):
            if not active:
                continue
            x, y = frame.point((row["x"], row["y"]))
            copper[name]["flashes"].append({
                "shape": row["shape"], "x": x, "y": y,
                "w": round(row["w"], 3), "h": round(row["h"], 3),
                "rot": round(row["rot"], 2), "net": row["net"], "ref": row["ref"],
                "pin": row["pin"], "name": row["pin"], "drill": row["drill"],
            })
    for track in tracks:
        if track["layer"] not in copper:
            continue
        pts = [frame.point(p) for p in track["points"]]
        copper[track["layer"]]["draws"].append({
            "points": [[p[0], p[1]] for p in pts],
            "width": round(track["width"], 3), "net": track["net"],
        })
    for via in vias:
        x, y = frame.point((via["x"], via["y"]))
        for name in ("F.Cu", "B.Cu"):
            copper[name]["flashes"].append({
                "shape": "round", "x": x, "y": y,
                "w": round(via["size"], 3), "h": round(via["size"], 3), "rot": 0.0,
                "net": via["net"], "ref": "VIA", "pin": "", "name": "",
                "drill": round(via["drill"], 3),
            })

    # ---- components (board frame) ---------------------------------------
    for comp in comps:
        comp["x"], comp["y"] = frame.point((comp["x"], comp["y"]))
        for pin in comp["pins"]:
            pin["x"], pin["y"] = frame.point((pin["x"], pin["y"]))
        # reference designator on the matching silk side
        layer_name = "B.SilkS" if comp["side"] == "bottom" else "F.SilkS"
        ty = comp["y"] + comp["body"]["h"] / 2.0 + 1.1
        for pts in stroke_text(comp["ref"], comp["x"], ty, size=0.85, rot=comp["rot"]):
            silk_out[layer_name]["text"].append({
                "points": [[round(p[0], 3), round(p[1], 3)] for p in pts],
                "width": 0.12, "text": comp["ref"], "ref": comp["ref"],
            })

    # ---- silk in board frame --------------------------------------------
    silk: Dict[str, dict] = {}
    for name in SILK_LAYERS:
        silk[name] = {
            "lines": [{**line, "points": frame.points([tuple(p) for p in line["points"]])}
                      for line in silk_out[name]["lines"]],
            "text": silk_out[name]["text"],
        }

    # ---- drills, nets, stats --------------------------------------------
    drills: List[dict] = []
    seen = set()
    for row in drill_rows:
        key = (round(row["x"], 2), round(row["y"], 2), round(row["d"], 3))
        if key in seen:
            continue
        seen.add(key)
        x, y = frame.point((row["x"], row["y"]))
        drills.append({"x": x, "y": y, "d": round(row["d"], 3), "plated": row["plated"]})
    for via in vias:
        key = (round(via["x"], 2), round(via["y"], 2), round(via["drill"], 3))
        if key in seen:
            continue
        seen.add(key)
        x, y = frame.point((via["x"], via["y"]))
        drills.append({"x": x, "y": y, "d": round(via["drill"], 3), "plated": True})

    routed = {t["net"] for t in tracks if t["net"]}
    routed |= {v["net"] for v in vias if v["net"]}
    net_names = set(net_pins)
    net_names |= {n for n in routed if n}
    net_names |= {name for name in net_table.values() if name}

    nets: List[dict] = []
    net_doc: Dict[str, dict] = {}
    for name in sorted(net_names):
        cls = net_class(name)
        meta = {"class": cls, "width": NET_CLASS_WIDTH.get(cls, DEFAULT_RULES["trace_width"])}
        net_doc[name] = meta
        nets.append({"name": name, "class": cls, "width": meta["width"],
                     "routed": name in routed, "pins": net_pins.get(name, [])})

    title = path.stem
    title_block = _child(root, "title_block")
    if title_block is not None:
        node = _child(title_block, "title")
        if node and len(node) > 1 and str(node[1]).strip():
            title = str(node[1]).strip()

    thickness = 1.6
    general = _child(root, "general")
    if general is not None:
        node = _child(general, "thickness")
        if node and len(node) > 1:
            thickness = round(_num(node[1], 1.6), 3)

    copper_layer_count = 0
    layers_node = _child(root, "layers")
    if layers_node is not None:
        copper_layer_count = sum(1 for c in layers_node[1:]
                                 if isinstance(c, list) and len(c) > 1 and str(c[1]).endswith(".Cu"))
    if copper_layer_count > 2:
        warnings.append(f"{copper_layer_count}-layer board flattened to 2 copper layers")

    pads_total = len(pad_rows)
    stats = {
        "components": len(comps), "nets": len(nets), "routed_nets": len(routed),
        "pads": pads_total, "vias": len(vias),
        "board_mm": f"{width} x {height}", "area_mm2": round(width * height, 1),
    }

    bom_groups: Dict[Tuple[str, str], dict] = {}
    for comp in comps:
        key = (comp["part"], comp["value"])
        group = bom_groups.setdefault(key, {
            "part": comp["part"], "value": comp["value"], "footprint": comp["footprint"],
            "description": comp["footprint"], "refs": [], "qty": 0,
        })
        group["refs"].append(comp["ref"])
        group["qty"] += 1
    bom = list(bom_groups.values())
    for row in bom:
        row["refs"] = sorted(row["refs"])
    bom.sort(key=lambda r: (r["refs"][0][0], r["refs"][0]))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    board_data = {
        "schema": 1,
        "slug": "",
        "title": title,
        "created": now,
        "updated": now,
        "board": {"width": width, "height": height, "layers": 2,
                  "thickness": thickness, "corner_radius": 0.0,
                  "finish": "HASL", "soldermask": "green"},
        "rules": dict(DEFAULT_RULES),
        "components": [{
            "ref": comp["ref"], "part": comp["part"], "value": comp["value"],
            "x": comp["x"], "y": comp["y"], "rot": round(comp["rot"], 2),
            "layer": comp["side"], "nets": {p["num"]: p["net"] for p in comp["pins"] if p["net"]},
            "group": "", "locked": True,
        } for comp in comps],
        "nets": net_doc,
        "routes": {},
        # The sidebar/`circuit_boards` summary reads `routes` for its "routed"
        # count; imported traces live in the view document, so record the count
        # here instead of reporting 0/N for a fully routed imported board.
        "routed_nets": sum(1 for n in nets if n.get("routed")),
        "vias": [],
        "imported": True,
        "meta": {"generator": "circuit", "version": 1, "format": "kicad",
                 "source": str(path), "note": "imported from KiCad — read-only, not routed or checked here"},
        "drc": {"ok": True, "errors": [], "warnings": [],
                "note": "imported board — no design-rule check was run"},
    }
    board = Board(board_data)

    doc = {
        "slug": "",
        "title": title,
        "schema": 1,
        "board": dict(board_data["board"]),
        "rules": dict(DEFAULT_RULES),
        "outline": frame.points(outline),
        "copper": copper,
        "silk": silk,
        "drills": drills,
        "components": comps,
        "nets": nets,
        "bom": bom,
        "stats": stats,
        "erc": {"ok": True, "errors": [], "warnings": [], "info": ["imported from KiCad"]},
        "drc": dict(board_data["drc"]),
        "files": {},
        "updated": now,
    }
    if not comps:
        warnings.append("no footprints found — the board has no components")
    return board, doc, warnings


# --------------------------------------------------------------------------- #
# store side
# --------------------------------------------------------------------------- #
def _bbox(pts: List[Point]):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def import_board(path: str, key: Optional[str] = None, source: Optional[str] = None) -> dict:
    """Import ``path`` into the project store and return a summary.

    ``key`` overrides the project slug and ``source`` the identity recorded in
    the board metadata; together they let a caller with an unstable local path
    (a sample downloaded to a temp file) re-import over the same project instead
    of piling up ``-2`` copies.
    """
    raw = (path or "").strip()
    if not raw:
        raise BoardError("path is required")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = p.resolve()
    if p.suffix.lower() != ".kicad_pcb":
        raise BoardError(f"{p.name} is not a .kicad_pcb file")
    if not p.is_file():
        raise BoardError(f"no file at {p}")

    board, doc, warnings = parse_board(p)
    identity = source or str(p)
    base = key or p.stem
    slug = store.slugify(base)
    root = store.projects_dir() / slug
    if root.exists():
        try:
            previous = json.loads((root / "board.json").read_text())
        except Exception:
            previous = {}
        same_source = ((previous.get("meta") or {}).get("source") == identity)
        if previous.get("imported") and same_source:
            shutil.rmtree(root)          # re-import replaces the previous copy
        else:
            slug = store.unique_slug(base)

    board.data["slug"] = slug
    board.data["meta"]["source"] = identity
    doc["slug"] = slug
    store.save(board, make_slug=False)
    store.write_view(slug, doc)
    return {
        "board": slug,
        "title": doc["title"],
        "components": len(doc["components"]),
        "nets": len(doc["nets"]),
        "pads": doc["stats"]["pads"],
        "size_mm": [doc["board"]["width"], doc["board"]["height"]],
        "warnings": warnings,
        "read_only": True,
    }