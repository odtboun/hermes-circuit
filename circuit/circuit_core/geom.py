"""Geometry primitives for the Circuit PCB engine.

All coordinates are millimetres in a Y-up board frame whose origin is the
board's bottom-left corner. Angles are degrees, counter-clockwise.

Nothing here depends on Hermes: the engine is importable and testable on its
own, which is also what ``hermes plugins validate`` needs (it imports the
plugin with a bare interpreter).
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]


# --------------------------------------------------------------------------- #
# basic vector math
# --------------------------------------------------------------------------- #
def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def mul(a: Point, k: float) -> Point:
    return (a[0] * k, a[1] * k)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(v: Point) -> float:
    return math.hypot(v[0], v[1])


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def norm(v: Point) -> Point:
    n = length(v)
    return (v[0] / n, v[1] / n) if n else (0.0, 0.0)


def rotate(p: Point, deg: float) -> Point:
    if not deg:
        return p
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def place(local: Point, x: float, y: float, rot: float) -> Point:
    """Local footprint coordinate -> board coordinate."""
    rx, ry = rotate(local, rot)
    return (x + rx, y + ry)


# --------------------------------------------------------------------------- #
# distances
# --------------------------------------------------------------------------- #
def point_seg_distance(p: Point, a: Point, b: Point) -> float:
    ab = sub(b, a)
    ll = dot(ab, ab)
    if ll <= 1e-12:
        return dist(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / ll))
    return dist(p, (a[0] + ab[0] * t, a[1] + ab[1] * t))


def _orient(a: Point, b: Point, c: Point) -> float:
    return cross(sub(b, a), sub(c, a))


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    return False


def seg_seg_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(
        point_seg_distance(a, c, d),
        point_seg_distance(b, c, d),
        point_seg_distance(c, a, b),
        point_seg_distance(d, a, b),
    )


# --------------------------------------------------------------------------- #
# polygons
# --------------------------------------------------------------------------- #
def polygon_area(poly: Sequence[Point]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
            if x < xin:
                inside = not inside
    return inside


def polyline_segments(pts: Sequence[Point]) -> Iterable[Tuple[Point, Point]]:
    for a, b in zip(pts, pts[1:]):
        yield a, b


def bbox(points: Iterable[Point]) -> Tuple[float, float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for x, y in points:
        xs.append(x)
        ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_gap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    """Euclidean gap between two axis-aligned boxes (0 when they overlap)."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


# --------------------------------------------------------------------------- #
# pad shapes
# --------------------------------------------------------------------------- #
def pad_outline(shape: str, x: float, y: float, w: float, h: float,
                rot: float = 0.0, r: float = 0.0, segments: int = 16) -> List[Point]:
    """Closed outline for a pad, in board coordinates.

    ``shape`` is one of ``rect``, ``round``, ``oval``, ``roundrect``, ``poly``.
    Rounded shapes are approximated with ``segments`` points per full circle.
    """
    if shape == "round":
        pts = [
            (x + w / 2.0 * math.cos(2 * math.pi * i / segments),
             y + w / 2.0 * math.sin(2 * math.pi * i / segments))
            for i in range(segments)
        ]
        return pts

    if shape == "oval":
        # stadium: a straight spine with a semicircle at each end
        rad = min(w, h) / 2.0
        hl = max(w, h) / 2.0 - rad
        pts = []
        steps = max(4, segments // 2)
        if h >= w:  # vertical spine
            for i in range(steps + 1):
                a = math.pi * i / steps
                pts.append((rad * math.cos(a), hl + rad * math.sin(a)))
            for i in range(steps + 1):
                a = math.pi + math.pi * i / steps
                pts.append((rad * math.cos(a), -hl + rad * math.sin(a)))
        else:  # horizontal spine
            for i in range(steps + 1):
                a = -math.pi / 2 + math.pi * i / steps
                pts.append((-hl + rad * math.cos(a), rad * math.sin(a)))
            for i in range(steps + 1):
                a = math.pi / 2 + math.pi * i / steps
                pts.append((hl + rad * math.cos(a), rad * math.sin(a)))
        return [place(p, x, y, rot) for p in pts]

    if shape == "roundrect":
        rr = min(r or min(w, h) * 0.25, min(w, h) / 2.0)
        hw, hh = w / 2.0 - rr, h / 2.0 - rr
        pts = []
        corners = [(hw, hh, 0.0), (-hw, hh, 90.0), (-hw, -hh, 180.0), (hw, -hh, 270.0)]
        per = max(2, segments // 4)
        for cx, cy, start in corners:
            for i in range(per + 1):
                a = math.radians(start + 90.0 * i / per)
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        return [place(p, x, y, rot) for p in pts]

    # rectangle (default)
    local = [(-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0), (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0)]
    return [place(p, x, y, rot) for p in local]


def pad_contains(shape: str, px: float, py: float, x: float, y: float,
                 w: float, h: float, rot: float = 0.0) -> bool:
    """Point-in-pad test in the pad's own frame."""
    lx, ly = rotate((px - x, py - y), -rot)
    if shape == "round":
        return math.hypot(lx, ly) <= w / 2.0 + 1e-9
    if shape == "oval":
        rad = min(w, h) / 2.0
        if h >= w:
            hl = max(0.0, h / 2.0 - rad)
            dy = ly - max(-hl, min(hl, ly))
            return math.hypot(lx, dy) <= rad + 1e-9
        hl = max(0.0, w / 2.0 - rad)
        dx = lx - max(-hl, min(hl, lx))
        return math.hypot(dx, ly) <= rad + 1e-9
    return abs(lx) <= w / 2.0 + 1e-9 and abs(ly) <= h / 2.0 + 1e-9


def pad_distance_to_point(pad: dict, x: float, y: float) -> float:
    """Signed-ish distance from a point to a pad (0 inside, positive outside)."""
    px, py = pad["x"], pad["y"]
    shape = pad.get("shape", "rect")
    if pad_contains(shape, x, y, px, py, pad["w"], pad["h"], pad.get("rot", 0.0)):
        return 0.0
    poly = pad_outline(shape, px, py, pad["w"], pad["h"], pad.get("rot", 0.0), pad.get("r", 0.0))
    return min(point_seg_distance((x, y), a, b) for a, b in zip(poly, poly[1:] + poly[:1]))


def pad_bbox(pad: dict) -> Tuple[float, float, float, float]:
    poly = pad_outline(pad.get("shape", "rect"), pad["x"], pad["y"], pad["w"], pad["h"],
                       pad.get("rot", 0.0), pad.get("r", 0.0))
    return bbox(poly)


def chamfer_path(pts: Sequence[Point], amount: float = 0.0) -> List[Point]:
    """Replace each right-angle corner with a 45-degree chamfer.

    Chamfering only removes copper, so a chamfered path can never violate a
    clearance the axis-aligned path already respected.
    """
    if len(pts) < 3:
        return list(pts)
    out: List[Point] = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        v1, v2 = norm(sub(b, a)), norm(sub(c, b))
        if abs(cross(v1, v2)) < 1e-6:  # collinear, nothing to cut
            continue
        cut = min(amount or min(dist(a, b), dist(b, c)) * 0.5,
                  dist(a, b) * 0.45, dist(b, c) * 0.45)
        if cut < 0.05:
            out.append(b)
            continue
        out.append(add(b, mul(v1, -cut)))
        out.append(add(b, mul(v2, cut)))
    out.append(pts[-1])
    # drop duplicates
    dedup: List[Point] = []
    for p in out:
        if not dedup or dist(p, dedup[-1]) > 1e-6:
            dedup.append(p)
    return dedup
