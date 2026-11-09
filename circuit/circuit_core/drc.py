"""Design-rule check and connectivity verification.

Everything here works on the final geometry (pads, routed segments, vias), not
on the router's internal grid, so it independently catches anything the router
mis-modelled. A board only reports ``ok`` when there are no errors: clearance,
minimum width/drill, annular ring, board-edge clearance and full net
connectivity.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import geom, layers as layer_mod
from .project import Board


def _pad_poly(pad: dict) -> List[geom.Point]:
    return geom.pad_outline(pad["shape"], pad["x"], pad["y"], pad["w"], pad["h"],
                            pad.get("rot", 0.0), pad.get("r", 0.0))


def _poly_dist(a: Sequence[geom.Point], b: Sequence[geom.Point]) -> float:
    for p in a:
        if geom.point_in_polygon(p, b):
            return 0.0
    for p in b:
        if geom.point_in_polygon(p, a):
            return 0.0
    best = float("inf")
    for i in range(len(a)):
        a1, a2 = a[i], a[(i + 1) % len(a)]
        for j in range(len(b)):
            b1, b2 = b[j], b[(j + 1) % len(b)]
            d = geom.seg_seg_distance(a1, a2, b1, b2)
            if d < best:
                best = d
                if best == 0.0:
                    return 0.0
    return best


def _point_poly_dist(p: geom.Point, poly: Sequence[geom.Point]) -> float:
    if geom.point_in_polygon(p, poly):
        return 0.0
    return min(geom.point_seg_distance(p, a, b) for a, b in zip(poly, poly[1:] + poly[:1]))


def _seg_poly_dist(a: geom.Point, b: geom.Point, poly: Sequence[geom.Point]) -> float:
    if geom.point_in_polygon(a, poly) or geom.point_in_polygon(b, poly):
        return 0.0
    best = min(_point_poly_dist(a, poly), _point_poly_dist(b, poly))
    for c, d in zip(poly, poly[1:] + poly[:1]):
        if geom.segments_intersect(a, b, c, d):
            return 0.0
        best = min(best, geom.seg_seg_distance(a, b, c, d))
    return best


def _trace_segments(board: Board) -> Iterable[dict]:
    for net, runs in board.data.get("routes", {}).items():
        for i, run in enumerate(runs):
            pts = run["points"]
            for j, (a, b) in enumerate(zip(pts, pts[1:])):
                yield {
                    "kind": "trace", "net": net, "layer": run["layer"],
                    "width": run.get("width", board.rules["trace_width"]),
                    "a": tuple(a), "b": tuple(b), "id": f"{net}/{i}/{j}",
                    "kind_item": "trace", "layers": {run["layer"]},
                    "bbox": (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])),
                }


def _pads(board: Board) -> List[dict]:
    out = []
    for pad in board.world_pads():
        if pad["kind"] == "npth":
            continue
        item = dict(pad)
        item["kind_item"] = "pad"
        item["poly"] = _pad_poly(pad)
        item["bbox"] = geom.bbox(item["poly"])
        item["layers"] = {"F.Cu", "B.Cu"} if pad["kind"] == "tht" else {"F.Cu"}
        if pad.get("layer") == "bottom":
            item["layers"] = {"B.Cu"}
        out.append(item)
    return out


def _vias(board: Board) -> List[dict]:
    out = []
    for v in board.data.get("vias", []):
        r = v.get("diameter", board.rules["via_diameter"]) / 2.0
        out.append({
            "kind": "via", "kind_item": "via", "net": v["net"], "x": v["x"], "y": v["y"], "r": r,
            "layers": {"F.Cu", "B.Cu"},
            "bbox": (v["x"] - r, v["y"] - r, v["x"] + r, v["y"] + r),
            "id": f"via/{v['x']:.2f}/{v['y']:.2f}",
        })
    return out


def _gap(a: dict, b: dict) -> float:
    """Edge-to-edge distance between two copper items (0 when touching)."""
    if a["kind_item"] == "pad" and b["kind_item"] == "pad":
        return _poly_dist(a["poly"], b["poly"])
    if a["kind"] == "trace" and b["kind"] == "trace":
        return max(0.0, geom.seg_seg_distance(a["a"], a["b"], b["a"], b["b"])
                   - a["width"] / 2.0 - b["width"] / 2.0)
    if a["kind_item"] == "pad" and b["kind"] == "trace":
        return max(0.0, _seg_poly_dist(b["a"], b["b"], a["poly"]) - b["width"] / 2.0)
    if a["kind"] == "trace" and b["kind_item"] == "pad":
        return max(0.0, _seg_poly_dist(a["a"], a["b"], b["poly"]) - a["width"] / 2.0)
    if a["kind"] == "via" and b["kind_item"] == "pad":
        return max(0.0, _point_poly_dist((a["x"], a["y"]), b["poly"]) - a["r"])
    if a["kind_item"] == "pad" and b["kind"] == "via":
        return max(0.0, _point_poly_dist((b["x"], b["y"]), a["poly"]) - b["r"])
    if a["kind"] == "via" and b["kind"] == "trace":
        return max(0.0, geom.point_seg_distance((a["x"], a["y"]), b["a"], b["b"])
                   - a["r"] - b["width"] / 2.0)
    if a["kind"] == "trace" and b["kind"] == "via":
        return max(0.0, geom.point_seg_distance((b["x"], b["y"]), a["a"], a["b"])
                   - b["r"] - a["width"] / 2.0)
    if a["kind"] == "via" and b["kind"] == "via":
        return max(0.0, geom.dist((a["x"], a["y"]), (b["x"], b["y"])) - a["r"] - b["r"])
    return float("inf")


def _layers_overlap(a: dict, b: dict) -> bool:
    return bool(a["layers"] & b["layers"])


class _DSU:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def check(board: Board, clearance: Optional[float] = None) -> dict:
    rules = board.rules
    clearance = float(clearance if clearance is not None else rules["clearance"])
    errors: List[str] = []
    warnings: List[str] = []
    counts = {"clearance": 0, "width": 0, "drill": 0, "edge": 0, "connectivity": 0,
              "silk": 0}

    pads = _pads(board)
    traces = list(_trace_segments(board))
    vias = _vias(board)
    items = pads + traces + vias

    for t in traces:
        if t["width"] < rules["min_trace"] - 1e-9:
            counts["width"] += 1
            errors.append(
                f"trace on {t['net']} is {t['width']:.2f} mm, below minimum {rules['min_trace']:.2f} mm")
    for pad in pads:
        if pad["kind"] == "tht" and pad["drill"] < rules["min_drill"] - 1e-9:
            counts["drill"] += 1
            errors.append(f"{pad['ref']}.{pad['num']} drill {pad['drill']:.2f} mm below minimum")
        if pad["kind"] == "tht":
            ring = (min(pad["w"], pad["h"]) - pad["drill"]) / 2.0
            if ring < 0.15 - 1e-9:
                counts["drill"] += 1
                errors.append(f"{pad['ref']}.{pad['num']} annular ring {ring:.2f} mm < 0.15 mm")
    for v in vias:
        if v["r"] * 2 < rules["via_diameter"] - 1e-9:
            counts["drill"] += 1
            errors.append("via diameter below rule")

    # clearance between foreign copper
    n = len(items)
    for i in range(n):
        a = items[i]
        for j in range(i + 1, n):
            b = items[j]
            if a["net"] and a["net"] == b["net"]:
                continue
            if not _layers_overlap(a, b):
                continue
            if geom.bbox_gap(a["bbox"], b["bbox"]) > clearance + 0.01:
                continue
            gap = _gap(a, b)
            if gap < clearance - 0.012:
                counts["clearance"] += 1
                if counts["clearance"] <= 25:
                    errors.append(
                        f"clearance {gap:.2f} mm < {clearance:.2f} mm between "
                        f"{_label(a)} and {_label(b)}")

    # board-edge clearance
    outline = board.outline(10)
    segs = list(geom.polyline_segments(outline + [outline[0]]))
    edge_rule = rules.get("edge_clearance", 0.3)
    for item in items:
        pts: List[geom.Point] = []
        if item["kind_item"] == "pad":
            pts = item["poly"]
        elif item["kind"] == "via":
            pts = [(item["x"], item["y"])]
        else:
            pts = [item["a"], item["b"]]
        d = min(min(geom.point_seg_distance(p, a, b) for a, b in segs) for p in pts)
        half = item.get("width", 0.0) / 2.0 if item["kind"] == "trace" else (
            item["r"] if item["kind"] == "via" else 0.0)
        if d - half < edge_rule - 0.01:
            counts["edge"] += 1
            if counts["edge"] <= 10:
                errors.append(f"{_label(item)} is {max(0.0, d - half):.2f} mm from the board edge")

    # connectivity: every net must be one copper island
    dsu = _DSU()
    for item in items:
        dsu.find(_node(item))
    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            if not a["net"] or a["net"] != b["net"]:
                continue
            if not _layers_overlap(a, b):
                continue
            if geom.bbox_gap(a["bbox"], b["bbox"]) > 0.02:
                continue
            if _gap(a, b) <= 0.015:
                dsu.union(_node(a), _node(b))

    by_net: Dict[str, List[dict]] = {}
    for item in items:
        if item["net"]:
            by_net.setdefault(item["net"], []).append(item)
    unrouted: List[str] = []
    partial: List[str] = []
    for net, net_items in by_net.items():
        roots = {dsu.find(_node(it)) for it in net_items}
        if len(roots) > 1:
            counts["connectivity"] += 1
            pads_only = [it for it in net_items if it["kind_item"] == "pad"]
            if len(pads_only) == len(net_items):
                unrouted.append(net)
            else:
                partial.append(net)

    for net in sorted(unrouted):
        errors.append(f"net {net} is unrouted ({len(by_net[net])} pads)")
    for net in sorted(partial):
        errors.append(f"net {net} is only partly routed ({len(by_net[net])} items in "
                      f"{len({dsu.find(_node(it)) for it in by_net[net]})} islands)")

    # Silkscreen over exposed copper: a fab clips it away, so the legend loses
    # detail but the board still works — warning, not error.
    silk_hits = _silk_over_pads(board, pads)
    counts["silk"] = len(silk_hits)
    warnings.extend(silk_hits[:12])
    if len(silk_hits) > 12:
        warnings.append(f"… {len(silk_hits) - 12} more silk-over-pad overlaps")

    if counts["clearance"] > 25:
        errors.append(f"… {counts['clearance'] - 25} more clearance violations")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "checked": {"pads": len(pads), "traces": len(traces), "vias": len(vias),
                    "nets": len(by_net), "clearance_mm": clearance},
        "unrouted_nets": sorted(unrouted),
    }


def _silk_over_pads(board: Board, pads: List[dict]) -> List[str]:
    """Silk segments that print on a mask opening, one message per pad."""
    silk = layer_mod.silk(board)
    by_side: Dict[str, List[Tuple[Tuple[float, float, float, float], dict]]] = {}
    for pad in pads:
        rect = (pad["x"] - pad["w"] / 2.0, pad["y"] - pad["h"] / 2.0,
                pad["x"] + pad["w"] / 2.0, pad["y"] + pad["h"] / 2.0)
        for copper_layer in pad["layers"]:
            side = "F.SilkS" if copper_layer == "F.Cu" else "B.SilkS"
            by_side.setdefault(side, []).append((rect, pad))
    hits: List[str] = []
    seen = set()
    for side, entries in by_side.items():
        drawn = silk.get(side, {})
        for line in list(drawn.get("lines") or []) + list(drawn.get("text") or []):
            hw = (line.get("width") or 0.12) / 2.0
            pts = line.get("points") or []
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                for rect, pad in entries:
                    span = layer_mod._seg_rect_span(
                        a, b, (rect[0] - hw, rect[1] - hw, rect[2] + hw, rect[3] + hw))
                    if not span:
                        continue
                    key = (side, pad["ref"], pad["num"])
                    if key in seen:
                        break
                    seen.add(key)
                    hits.append(
                        f"silk on {side[0]} overlaps the mask opening of "
                        f"{pad['ref']}.{pad['num']} — the fab will clip it")
                    break
    return hits


def _node(item: dict) -> str:
    return item.get("id") or f"{item.get('ref')}.{item.get('num')}"


def _label(item: dict) -> str:
    if item["kind_item"] == "pad":
        return f"{item['ref']}.{item['num']} ({item['net'] or 'no net'})"
    if item["kind"] == "via":
        return f"via @{item['x']:.1f},{item['y']:.1f} ({item['net']})"
    return f"trace {item['net']} @{item['a'][0]:.1f},{item['a'][1]:.1f}"
