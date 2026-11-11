"""Grid maze autorouter for 2-layer boards.

Two-tier occupancy keeps dense packages routable without giving up the design
rules:

* a **hard** block covers copper plus most of the clearance ring — A* may never
  enter it;
* a **soft** ring just outside that costs extra per cell, so paths prefer the
  middle of a channel and only squeeze where they must;
* final geometry is verified by :mod:`circuit_core.drc`, which is what actually
  certifies clearance.

Pads with no net are obstacles too, so a trace can never cross a pin the
netlist left unassigned.

Routing is sequential with multi-source A* per net: the net's growing tree is
the source set and each remaining pad is a goal, so a 6-pin net becomes one
connected tree rather than five independent segments.
"""

from __future__ import annotations

import heapq
import math
import time
from array import array
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom
from .project import Board, net_class

LAYERS = ("F.Cu", "B.Cu")
VIA_COST = 16.0
_FREE, _BLOCKED, _ORPHAN = 0, -1, -2
_SOFT = 9.0


class Router:
    def __init__(self, board: Board, grid: Optional[float] = None,
                 via_cost: float = VIA_COST, effort: str = "normal"):
        self.board = board
        self.r = board.rules
        self.grid = float(grid or self.r.get("grid", 0.15))
        self.via_cost = via_cost
        self.effort = effort
        self.w = board.board["width"]
        self.h = board.board["height"]
        self.nx = int(math.floor(self.w / self.grid)) + 1
        self.ny = int(math.floor(self.h / self.grid)) + 1
        self.size = self.nx * self.ny
        self.owner = [array("h", [_FREE] * self.size) for _ in LAYERS]
        self.vowner = [array("h", [_FREE] * self.size) for _ in LAYERS]
        self.pen = [bytearray(self.size) for _ in LAYERS]
        self.stamp = array("i", [0] * (2 * self.size))
        self.gcost = array("f", [0.0] * (2 * self.size))
        self.parent = array("i", [-1] * (2 * self.size))
        self._search_id = 0
        self.net_ids: Dict[str, int] = {}
        self.id_nets: Dict[int, str] = {}
        self.failed: List[dict] = []
        self.via_radius = (self.r["via_diameter"] / 2.0 + self.r["clearance"] + 0.15)
        self.max_half = max(
            [self.r["trace_width"]] + [m.get("width", 0.0) for m in board.data["nets"].values()]
        ) / 2.0
        self._via_block = [set(), set()]
        self._edge_blocked()
        self._index_smd_pads()

    # ------------------------------------------------------------------ #
    # grid helpers
    # ------------------------------------------------------------------ #
    def idx(self, ix: int, iy: int) -> int:
        return iy * self.nx + ix

    def xy(self, ix: int, iy: int) -> Tuple[float, float]:
        return (round(ix * self.grid, 4), round(iy * self.grid, 4))

    def cell_of(self, x: float, y: float) -> Tuple[int, int]:
        ix = int(round(x / self.grid))
        iy = int(round(y / self.grid))
        return max(0, min(self.nx - 1, ix)), max(0, min(self.ny - 1, iy))

    def inside(self, ix: int, iy: int) -> bool:
        return 0 <= ix < self.nx and 0 <= iy < self.ny

    def _sdf(self, x: float, y: float) -> float:
        bw, bh = self.w, self.h
        r = max(0.0, min(self.board.board.get("corner_radius", 0.0), min(bw, bh) / 2.0))
        qx = abs(x - bw / 2.0) - (bw / 2.0 - r)
        qy = abs(y - bh / 2.0) - (bh / 2.0 - r)
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r

    def _edge_blocked(self) -> None:
        keep = self.r.get("edge_clearance", 0.3) + self.r["trace_width"] / 2.0
        for layer in (0, 1):
            own = self.owner[layer]
            vinc = self.vowner[layer]
            for iy in range(self.ny):
                row = iy * self.nx
                y = iy * self.grid
                for ix in range(self.nx):
                    if self._sdf(ix * self.grid, y) > -keep:
                        own[row + ix] = _BLOCKED
                        vinc[row + ix] = _BLOCKED

    def _index_smd_pads(self) -> None:
        for pad in self.board.world_pads():
            if pad["kind"] != "smd":
                continue
            layer = 0 if pad.get("layer") == "top" else 1
            for cell in self._cells_in_pad(pad, shrink=0.0):
                self._via_block[layer].add(self.idx(*cell))

    def _cells_in_pad(self, pad: dict, shrink: float = 0.18) -> List[Tuple[int, int]]:
        poly = geom.pad_outline(pad["shape"], pad["x"], pad["y"], pad["w"], pad["h"],
                                pad.get("rot", 0.0), pad.get("r", 0.0))
        bx = geom.bbox(poly)
        ix0, iy0 = self.cell_of(bx[0] - shrink, bx[1] - shrink)
        ix1, iy1 = self.cell_of(bx[2] + shrink, bx[3] + shrink)
        out: List[Tuple[int, int]] = []
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                if geom.pad_contains(pad["shape"], ix * self.grid, iy * self.grid,
                                     pad["x"], pad["y"], max(0.01, pad["w"] - shrink),
                                     max(0.01, pad["h"] - shrink), pad.get("rot", 0.0)):
                    out.append((ix, iy))
        return out

    # ------------------------------------------------------------------ #
    # occupancy
    # ------------------------------------------------------------------ #
    def _claim(self, layer: int, x: float, y: float, r_hard: float, r_soft: float,
               net_id: int) -> None:
        r_via = self.via_radius
        reach = max(r_soft, r_via)
        ix0, iy0 = self.cell_of(x - reach, y - reach)
        ix1, iy1 = self.cell_of(x + reach, y + reach)
        own = self.owner[layer]
        vinc = self.vowner[layer]
        pen = self.pen[layer]
        for iy in range(iy0, iy1 + 1):
            row = iy * self.nx
            for ix in range(ix0, ix1 + 1):
                o = own[row + ix]
                if o == _BLOCKED:
                    continue
                d = geom.dist((ix * self.grid, iy * self.grid), (x, y))
                if d <= r_via:
                    vo = vinc[row + ix]
                    if vo == _FREE or vo == net_id:
                        vinc[row + ix] = net_id
                if d <= r_hard:
                    if o == _FREE or o == net_id:
                        own[row + ix] = net_id
                elif d <= r_soft:
                    if o == _FREE and not pen[row + ix]:
                        pen[row + ix] = int(_SOFT)

    def _claim_pad(self, pad: dict, net_id: int, width: float) -> None:
        layers = (0, 1) if pad["kind"] == "tht" else ((0,) if pad.get("layer") == "top" else (1,))
        poly = geom.pad_outline(pad["shape"], pad["x"], pad["y"], pad["w"], pad["h"],
                                pad.get("rot", 0.0), pad.get("r", 0.0))
        bx = geom.bbox(poly)
        r_hard = self.r["clearance"] + self.max_half + 0.02
        r_soft = r_hard + 0.12
        # A via is copper on BOTH layers with an annular ring around the drill, so
        # it has to clear a pad just like a trace does. Without this the router
        # happily drops a via 0.02 mm from an SOIC pin: the pad blocked traces but
        # never vias.
        r_via = self.via_radius
        reach = max(r_soft, r_via)
        for layer in layers:
            own = self.owner[layer]
            pen = self.pen[layer]
            vinc = self.vowner[layer]
            ix0, iy0 = self.cell_of(bx[0] - reach, bx[1] - reach)
            ix1, iy1 = self.cell_of(bx[2] + reach, bx[3] + reach)
            for iy in range(iy0, iy1 + 1):
                row = iy * self.nx
                for ix in range(ix0, ix1 + 1):
                    if own[row + ix] == _BLOCKED:
                        continue
                    d = geom.pad_distance_to_point(pad, ix * self.grid, iy * self.grid)
                    if d <= r_via:
                        vo = vinc[row + ix]
                        if vo == _FREE:
                            vinc[row + ix] = net_id
                        elif vo != net_id and vo != _BLOCKED:
                            # within reach of two pads on different nets: a via here
                            # is too close to one of them whichever net it carries
                            vinc[row + ix] = _BLOCKED
                    if d <= r_hard:
                        if own[row + ix] in (_FREE, net_id):
                            own[row + ix] = net_id
                    elif d <= r_soft and own[row + ix] in (_FREE, net_id) and not pen[row + ix]:
                        pen[row + ix] = int(_SOFT)

    def _claim_pads(self) -> None:
        widths = {n: m.get("width", self.r["trace_width"])
                  for n, m in self.board.data["nets"].items()}
        default_w = self.r["trace_width"]
        for pad in self.board.world_pads():
            if pad["kind"] == "npth":
                continue
            if not pad["net"]:
                self._claim_pad(pad, _ORPHAN, default_w)
                continue
            net_id = self.net_ids.get(pad["net"])
            if net_id is not None:
                self._claim_pad(pad, net_id, widths.get(pad["net"], default_w))

    def _access_cells(self, pad: dict) -> List[Tuple[int, int, int]]:
        layers = (0, 1) if pad["kind"] == "tht" else ((0,) if pad.get("layer") == "top" else (1,))
        cells = [(layer, ix, iy) for ix, iy in self._cells_in_pad(pad, shrink=0.22)
                 for layer in layers]
        if not cells:
            cx, cy = self.cell_of(pad["x"], pad["y"])
            cells = [(layer, cx, cy) for layer in layers]
        return cells

    # ------------------------------------------------------------------ #
    # A*
    # ------------------------------------------------------------------ #
    def _via_ok(self, layer: int, ix: int, iy: int, net_id: int) -> bool:
        """O(1): both layers must be clear for a via at this cell."""
        ci = self.idx(ix, iy)
        for l in (0, 1):
            o = self.vowner[l][ci]
            if o != _FREE and o != net_id:
                return False
        return True

    def _claim_via(self, ix: int, iy: int, net_id: int) -> None:
        r = self.via_radius
        for layer in (0, 1):
            self._claim(layer, ix * self.grid, iy * self.grid, r, r + 0.1, net_id)

    def _free(self, layer: int, ix: int, iy: int, net_id: int) -> bool:
        if not self.inside(ix, iy):
            return False
        o = self.owner[layer][self.idx(ix, iy)]
        return o == _FREE or o == net_id

    def _astar(self, net_id: int, sources: Sequence[int], goals: Sequence[int],
               hx: float, hy: float) -> Optional[List[int]]:
        goal_set = set(goals)
        best: Dict[int, float] = {}
        parent: Dict[int, int] = {}
        heap: List[Tuple[float, float, int]] = []
        for s in sources:
            layer, cell = divmod(s, self.size)
            ix, iy = cell % self.nx, cell // self.nx
            if s not in goal_set and not self._free(layer, ix, iy, net_id):
                continue
            best[s] = 0.0
            parent[s] = -1
            heapq.heappush(heap, (self._heur(ix, iy, hx, hy), 0.0, s))
        cap = 250000
        pops = 0
        while heap:
            f, g, s = heapq.heappop(heap)
            if g > best.get(s, float("inf")) + 1e-9:
                continue
            pops += 1
            if pops > cap:
                break
            if s in goal_set:
                return self._unwind(s, parent)
            layer, cell = divmod(s, self.size)
            ix, iy = cell % self.nx, cell // self.nx
            for dx, dy, cost in _NEIGHBORS:
                nx_, ny_ = ix + dx, iy + dy
                if not self._free(layer, nx_, ny_, net_id):
                    continue
                if dx and dy:
                    if not (self._free(layer, ix + dx, iy, net_id)
                            and self._free(layer, ix, iy + dy, net_id)):
                        continue
                ni = self.idx(nx_, ny_)
                ns = layer * self.size + ni
                ng = g + cost + self.pen[layer][ni] * 0.01
                if ng < best.get(ns, float("inf")) - 1e-9:
                    best[ns] = ng
                    parent[ns] = s
                    heapq.heappush(heap, (ng + self._heur(nx_, ny_, hx, hy) * 1.0001, ng, ns))
            other = 1 - layer
            ci = self.idx(ix, iy)
            if (ci not in self._via_block[other] and self._free(other, ix, iy, net_id)
                    and self._via_ok(layer, ix, iy, net_id)):
                ns = other * self.size + ci
                ng = g + self.via_cost + self.pen[other][ci] * 0.01
                if ng < best.get(ns, float("inf")) - 1e-9:
                    best[ns] = ng
                    parent[ns] = s
                    heapq.heappush(heap, (ng + self._heur(ix, iy, hx, hy) * 1.0001, ng, ns))
        return None

    @staticmethod
    def _unwind(s: int, parent: Dict[int, int]) -> List[int]:
        path = []
        while s != -1:
            path.append(s)
            s = parent[s]
        path.reverse()
        return path

    @staticmethod
    def _heur(ix: int, iy: int, hx: float, hy: float) -> float:
        dx, dy = abs(ix - hx), abs(iy - hy)
        return (dx + dy) + (1.4142 - 2.0) * min(dx, dy)

    # ------------------------------------------------------------------ #
    # main entry
    # ------------------------------------------------------------------ #
    def _class_rank(self, net: str) -> int:
        cls = (self.board.data["nets"].get(net) or {}).get("class") or net_class(net)
        return {"power": 0, "ground": 1}.get(cls, 2)

    def route(self) -> dict:
        started = time.time()
        nets = self.board.net_pins()
        routable = {n: p for n, p in nets.items() if len(p) >= 2}
        # Power and ground first, then signals by span. They are the backbone of a
        # 2-layer board: routed last, they have to weave around everything already
        # placed and end up in islands. Routed first, everything else fills in.
        order = sorted(routable, key=lambda n: (self._class_rank(n),
                                                self._net_span(routable[n])))
        for i, net in enumerate(sorted(nets), start=1):
            self.net_ids[net] = i
            self.id_nets[i] = net
        if not order:
            return {"routes": {}, "vias": [], "failed": [], "stats": {"nets": 0}}

        self._claim_pads()
        routes: Dict[str, List[dict]] = {}
        vias: List[dict] = []
        seen_vias = set()
        widths = {n: m.get("width", self.r["trace_width"])
                  for n, m in self.board.data["nets"].items()}

        for net in order:
            net_id = self.net_ids[net]
            pads = routable[net]
            width = widths.get(net, self.r["trace_width"])
            remaining = list(pads)
            first = remaining.pop(0)
            tree = [layer * self.size + self.idx(ix, iy)
                    for layer, ix, iy in self._access_cells(first)]
            segments: List[dict] = []
            while remaining:
                probe = remaining[:4] if self.effort == "fast" else remaining
                best = None
                for pad in probe:
                    goals = [l * self.size + self.idx(ix, iy)
                             for l, ix, iy in self._access_cells(pad)]
                    hx, hy = self.cell_of(pad["x"], pad["y"])
                    path = self._astar(net_id, tree, goals, hx, hy)
                    if path is None:
                        continue
                    if best is None or len(path) < len(best[1]):
                        best = (pad, path)
                    if self.effort == "fast":
                        break
                if best is None:
                    self.failed.append({"net": net, "pins": len(remaining),
                                        "reason": "no path to " + ", ".join(
                                            f"{p['ref']}.{p['name']}" for p in remaining[:3])})
                    break
                pad, path = best
                remaining.remove(pad)
                drawn = self._path_segments(path, width)
                segments.extend(drawn)
                tree.extend(path)
                for a, b in zip(path, path[1:]):
                    la, ca = divmod(a, self.size)
                    lb, cb = divmod(b, self.size)
                    if la != lb and ca == cb:
                        self._claim_via(ca % self.nx, ca // self.nx, net_id)
                        vx, vy = self.xy(cb % self.nx, cb // self.nx)
                        key = (round(vx, 2), round(vy, 2), net)
                        if key not in seen_vias:
                            seen_vias.add(key)
                            vias.append({"x": vx, "y": vy, "net": net,
                                         "diameter": self.r["via_diameter"],
                                         "drill": self.r["via_drill"]})
                r_hard = width / 2.0 + self.r["clearance"] + self.max_half
                r_soft = r_hard + 0.15
                # Claim the copper that will actually be drawn, not the grid cells
                # it came from: the segments are chamfered at corners, and a 0.35 mm
                # corner cut swings the trace inside the cell it nominally occupies,
                # which is how a trace ended up on top of a via 0.1 mm away.
                for seg in drawn:
                    layer = 0 if seg["layer"] == "F.Cu" else 1
                    pts = seg["points"]
                    for i in range(len(pts) - 1):
                        ax, ay = pts[i]
                        bx, by = pts[i + 1]
                        length = math.hypot(bx - ax, by - ay)
                        steps = max(1, int(length / (self.grid * 0.5)))
                        for k in range(steps + 1):
                            t = k / steps
                            self._claim(layer, ax + (bx - ax) * t, ay + (by - ay) * t,
                                        r_hard, r_soft, net_id)
            if segments:
                routes[net] = _merge_segments(segments)

        elapsed = round(time.time() - started, 2)
        self.board.data["routes"] = routes
        self.board.data["vias"] = vias
        self.board.touch()
        return {
            "routes": routes,
            "vias": vias,
            "failed": self.failed,
            "stats": {
                "nets": len(order), "routed_nets": len(routes),
                "grid_mm": self.grid, "cells": self.size, "elapsed_s": elapsed,
            },
        }

    def _net_span(self, pads: Sequence[dict]) -> float:
        xs = [p["x"] for p in pads]
        ys = [p["y"] for p in pads]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    def _path_segments(self, path: Sequence[int], width: float) -> List[dict]:
        segs: List[dict] = []
        run_layer = path[0] // self.size
        run: List[geom.Point] = []
        for s in path:
            layer, cell = divmod(s, self.size)
            ix, iy = cell % self.nx, cell // self.nx
            p = self.xy(ix, iy)
            if layer != run_layer:
                if len(run) >= 2:
                    segs.append({"layer": LAYERS[run_layer], "width": width,
                                 "points": geom.chamfer_path(run, self.r.get("chamfer", 0.35))})
                run = [p]
                run_layer = layer
            else:
                run.append(p)
        if len(run) >= 2:
            segs.append({"layer": LAYERS[run_layer], "width": width,
                         "points": geom.chamfer_path(run, self.r.get("chamfer", 0.35))})
        return segs


_NEIGHBORS = [
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142),
]


def _merge_segments(segments: List[dict]) -> List[dict]:
    out: List[dict] = []
    for seg in segments:
        if out:
            last = out[-1]
            if (last["layer"] == seg["layer"] and abs(last["width"] - seg["width"]) < 1e-6
                    and geom.dist(last["points"][-1], seg["points"][0]) < 1e-6):
                last["points"] = last["points"] + list(seg["points"][1:])
                continue
        out.append(seg)
    return out


def route_board(board: Board, grid: Optional[float] = None, effort: str = "normal") -> dict:
    return Router(board, grid=grid, effort=effort).route()
