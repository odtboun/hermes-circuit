"""Automatic component placement.

A deterministic greedy placer: biggest parts first, each one dropped at the
candidate spot that minimises estimated wirelength to the parts it shares nets
with, subject to courtyard clearance and board-edge keepout. Connectors are
biased to the board edge. Followed by a short relaxation pass that pulls
connected parts together without creating overlaps.

Deterministic on purpose: the same board always produces the same layout, so a
tool call is reproducible and a diff means a real change.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom
from .lib import footprints, parts
from .project import Board

MARGIN = 1.6          # board-edge keepout for ordinary parts (mm)
CONNECTOR_MARGIN = 0.8
GAP = 0.6             # extra courtyard-to-courtyard gap (mm)
GRID = 0.5            # candidate search grid (mm)


def _footprint(component: dict) -> dict:
    return footprints.get(parts.get(component["part"])["footprint"])


def _size(component: dict, rot: float = 0.0) -> Tuple[float, float]:
    fp = _footprint(component)
    w, h = fp["courtyard"]["w"], fp["courtyard"]["h"]
    if round(rot) % 180 == 90:
        w, h = h, w
    return w, h


def _is_connector(component: dict) -> bool:
    return parts.get(component["part"])["category"] in ("connector", "mechanical")


def _connectivity(board: Board) -> Dict[str, Dict[str, float]]:
    """ref -> {other_ref: weight} derived from shared nets."""
    weights: Dict[str, Dict[str, float]] = {c["ref"]: {} for c in board.data["components"]}
    for net, pins in board.net_pins().items():
        refs = sorted({p["ref"] for p in pins})
        if len(refs) < 2:
            continue
        w = 1.0 / (len(refs) - 1)
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                weights[a][b] = weights[a].get(b, 0.0) + w
                weights[b][a] = weights[b].get(a, 0.0) + w
    return weights


def _bbox_at(component: dict, x: float, y: float, rot: float) -> Tuple[float, float, float, float]:
    w, h = _size(component, rot)
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _inside_board(board: Board, box: Tuple[float, float, float, float], margin: float) -> bool:
    return (box[0] >= margin and box[1] >= margin
            and box[2] <= board.board["width"] - margin
            and box[3] <= board.board["height"] - margin)


def _overlaps(box, placed: Sequence[Tuple[float, float, float, float]], gap: float) -> bool:
    for other in placed:
        if geom.bbox_gap(box, other) < gap:
            return True
    return False


def _edge_affinity(board: Board, box) -> float:
    w, h = board.board["width"], board.board["height"]
    d = min(box[0], box[1], w - box[2], h - box[3])
    return max(0.0, 1.0 - d / 12.0)


def auto_place(board: Board, gap: float = GAP, refinement_passes: int = 2) -> List[dict]:
    comps = board.data["components"]
    if not comps:
        return []
    conn = _connectivity(board)

    # placement order: most-connected + biggest first, connectors first so they
    # claim the edges before small parts fill them.
    def rank(c: dict):
        fp = _footprint(c)
        area = fp["courtyard"]["w"] * fp["courtyard"]["h"]
        return (-(area + len(fp["pads"]) * 0.8),)

    ordered = sorted(comps, key=rank)
    w, h = board.board["width"], board.board["height"]
    placed_boxes: List[Tuple[float, float, float, float]] = []
    placed_net_pins: Dict[str, List[Tuple[float, float]]] = {}
    moves: List[dict] = []

    for comp in ordered:
        fp = _footprint(comp)
        margin = CONNECTOR_MARGIN if _is_connector(comp) else MARGIN
        best = None
        best_score = float("inf")
        # candidate rotations: connectors/passives can turn; ICs stay upright
        rots = [0.0, 90.0]
        for rot in rots:
            cw, ch = _size(comp, rot)
            if cw + 2 * margin > w or ch + 2 * margin > h:
                continue
            xs = _axis_candidates(cw / 2 + margin, w - cw / 2 - margin, board.board["width"], cw)
            ys = _axis_candidates(ch / 2 + margin, h - ch / 2 - margin, board.board["height"], ch)
            for cx in xs:
                for cy in ys:
                    box = _bbox_at(comp, cx, cy, rot)
                    if not _inside_board(board, box, margin):
                        continue
                    if _overlaps(box, placed_boxes, gap):
                        continue
                    score = _score(comp, cx, cy, rot, conn, placed_net_pins, board)
                    if score < best_score - 1e-9:
                        best_score, best = score, (cx, cy, rot, box)
        if best is None:
            # nothing fits: park it outside the outline and let ERC complain
            best = (w + 5.0, h + 5.0, 0.0, _bbox_at(comp, w + 5.0, h + 5.0, 0.0))
        cx, cy, rot, box = best
        comp["x"], comp["y"], comp["rot"] = round(cx, 2), round(cy, 2), rot
        placed_boxes.append(box)
        for pad in board.world_pads(comp["ref"]):
            if pad["net"]:
                placed_net_pins.setdefault(pad["net"], []).append((pad["x"], pad["y"]))
        moves.append({"ref": comp["ref"], "x": comp["x"], "y": comp["y"], "rot": rot})

    if refinement_passes:
        _relax(board, placed_boxes, gap, refinement_passes)
    board.touch()
    return moves


def _axis_candidates(lo: float, hi: float, span: float, size: float) -> List[float]:
    if hi < lo:
        return []
    cands = {round(lo + i * GRID, 2) for i in range(int((hi - lo) / GRID) + 1)}
    cands.add(round(hi, 2))
    # a coarse lattice keeps the search cheap on big boards
    if len(cands) > 90:
        step = max(1, len(cands) // 90)
        cands = {c for i, c in enumerate(sorted(cands)) if i % step == 0}
    return sorted(cands)


def _score(comp: dict, x: float, y: float, rot: float,
           conn: Dict[str, Dict[str, float]],
           placed_net_pins: Dict[str, List[Tuple[float, float]]],
           board: Board) -> float:
    # distance from this part's pads to the average position of same-net pins
    est = 0.0
    fp = _footprint(comp)
    for pad in fp["pads"]:
        px, py = geom.place((pad["x"], pad["y"]), x, y, rot)
        net = (comp.get("nets") or {}).get(pad["num"])
        if not net:
            continue
        others = placed_net_pins.get(net)
        if not others:
            continue
        ox = sum(p[0] for p in others) / len(others)
        oy = sum(p[1] for p in others) / len(others)
        est += geom.dist((px, py), (ox, oy)) / max(3.0, math.sqrt(len(others)))
    if fp["pads"]:
        est /= len(fp["pads"])

    edge = _edge_affinity(board, _bbox_at(comp, x, y, rot))
    bias = 0.0
    if _is_connector(comp):
        bias -= 3.0 * edge
    else:
        bias += 1.2 * edge  # keep the middle free for ICs
    # mild preference for staying near the board centre of mass
    cx, cy = board.board["width"] / 2, board.board["height"] / 2
    bias += 0.01 * geom.dist((x, y), (cx, cy))
    return est + bias


def _relax(board: Board, boxes: List[Tuple[float, float, float, float]], gap: float,
           passes: int) -> None:
    comps = board.data["components"]
    conn = _connectivity(board)
    w, h = board.board["width"], board.board["height"]
    by_ref = {c["ref"]: c for c in comps}
    for _ in range(passes):
        for i, c in enumerate(comps):
            if _is_connector(c) or c.get("locked"):
                continue
            nbrs = [by_ref[r] for r in conn.get(c["ref"], {}) if by_ref.get(r)]
            if not nbrs:
                continue
            tx = sum(n["x"] for n in nbrs) / len(nbrs)
            ty = sum(n["y"] for n in nbrs) / len(nbrs)
            dx, dy = (tx - c["x"]) * 0.18, (ty - c["y"]) * 0.18
            cw, ch = _size(c, c["rot"])
            nx = min(max(c["x"] + dx, MARGIN + cw / 2), w - MARGIN - cw / 2)
            ny = min(max(c["y"] + dy, MARGIN + ch / 2), h - MARGIN - ch / 2)
            box = _bbox_at(c, nx, ny, c["rot"])
            others = [b for j, b in enumerate(boxes) if j != i]
            if _overlaps(box, others, gap * 0.8):
                continue
            boxes[i] = box
            c["x"], c["y"] = round(nx, 2), round(ny, 2)


def suggest_size(board: Board, fill: float = 0.55) -> Tuple[float, float]:
    area = 0.0
    for c in board.data["components"]:
        fp = _footprint(c)
        area += fp["courtyard"]["w"] * fp["courtyard"]["h"]
    side = math.sqrt(max(area, 100.0) / fill)
    return max(20.0, round(side + 4.0, 0)), max(20.0, round(side * 0.75 + 4.0, 0))


def fit_board_to_components(board: Board, margin: float = 3.0) -> Optional[dict]:
    """Grow the board so every placed part fits with ``margin``.

    Returns the new dimensions, or None when nothing had to change.
    """
    boxes = []
    for c in board.data["components"]:
        if c.get("x") is None:
            continue
        boxes.append(_bbox_at(c, c["x"], c["y"], c.get("rot", 0.0)))
    if not boxes:
        return None
    minx = min(b[0] for b in boxes)
    miny = min(b[1] for b in boxes)
    maxx = max(b[2] for b in boxes)
    maxy = max(b[3] for b in boxes)
    dx = margin - minx
    dy = margin - miny
    new_w = max(board.board["width"], maxx - minx + 2 * margin)
    new_h = max(board.board["height"], maxy - miny + 2 * margin)
    if abs(dx) < 0.01 and abs(dy) < 0.01 and new_w <= board.board["width"] and new_h <= board.board["height"]:
        return None
    for c in board.data["components"]:
        if c.get("x") is not None:
            c["x"] = round(c["x"] + dx, 2)
            c["y"] = round(c["y"] + dy, 2)
    board.board["width"] = round(new_w, 2)
    board.board["height"] = round(new_h, 2)
    board.board["corner_radius"] = min(board.board.get("corner_radius", 2.0),
                                       min(new_w, new_h) / 2 - 0.5)
    board.touch()
    return {"width": board.board["width"], "height": board.board["height"]}
