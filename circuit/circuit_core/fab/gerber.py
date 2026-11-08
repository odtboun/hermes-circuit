"""RS-274X Gerber and Excellon writers, plus a small reader for verification.

Only the subset this engine emits is written (clear flashes, linear draws,
regions) — and that is exactly the subset the reader understands, so an
independent round-trip test can prove the files describe the board.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .. import geom

_SCALE = 1_000_000  # FSLAX46: 4 integer, 6 decimal digits


def _coord(v: float) -> str:
    return str(int(round(v * _SCALE)))


class GerberWriter:
    def __init__(self, file_function: str, polarity: str = "Dark"):
        self.file_function = file_function
        self.lines: List[str] = []
        self.apertures: Dict[Tuple, int] = {}
        self.next_dcode = 10
        self.current = None
        self._header_done = False
        self._header()

    # ------------------------------------------------------------------ #
    def _header(self) -> None:
        self.lines += [
            "G04 Circuit PCB exporter -- https://github.com/odtboun/hermes-circuit*",
            f"%TF.GenerationSoftware,Circuit,circuit,1.0*%",
            f"%TF.FileFunction,{self.file_function}*%",
            "%FSLAX46Y46*%",
            "%MOMM*%",
            "%LPD*%",
            "G01*",
        ]
        self._header_done = True

    def _aperture(self, kind: str, *params: float) -> int:
        key = (kind,) + tuple(round(p, 4) for p in params)
        if key in self.apertures:
            return self.apertures[key]
        d = self.next_dcode
        self.next_dcode += 1
        self.apertures[key] = d
        body = "X".join(f"{p:.6f}" for p in params)
        self.lines.append(f"%ADD{d}{kind},{body}*%")
        return d

    def _select(self, dcode: int) -> None:
        if self.current != dcode:
            self.lines.append(f"D{dcode}*")
            self.current = dcode

    # ------------------------------------------------------------------ #
    def flash(self, shape: str, x: float, y: float, w: float, h: float,
              rot: float = 0.0) -> None:
        r = rot % 360.0
        if shape == "round":
            d = self._aperture("C", w)
            self._select(d)
            self.lines.append(f"X{_coord(x)}Y{_coord(y)}D03*")
            return
        if shape in ("oval", "rect") and abs(r % 90.0) < 1e-6:
            ww, hh = (h, w) if int(round(r / 90.0)) % 2 else (w, h)
            if shape == "oval":
                d = self._aperture("O", ww, hh)
            else:
                d = self._aperture("R", ww, hh)
            self._select(d)
            self.lines.append(f"X{_coord(x)}Y{_coord(y)}D03*")
            return
        # arbitrary rotation: draw the pad as a region
        poly = geom.pad_outline(shape, x, y, w, h, r, 0.0)
        self.region(poly)

    def polyline(self, pts: Sequence[Sequence[float]], width: float) -> None:
        if len(pts) < 2:
            return
        d = self._aperture("C", width)
        self._select(d)
        self.lines.append(f"X{_coord(pts[0][0])}Y{_coord(pts[0][1])}D02*")
        for p in pts[1:]:
            self.lines.append(f"X{_coord(p[0])}Y{_coord(p[1])}D01*")

    def region(self, poly: Sequence[Sequence[float]]) -> None:
        if len(poly) < 3:
            return
        self.lines.append("G36*")
        self.lines.append(f"X{_coord(poly[0][0])}Y{_coord(poly[0][1])}D02*")
        for p in list(poly)[1:]:
            self.lines.append(f"X{_coord(p[0])}Y{_coord(p[1])}D01*")
        self.lines.append(f"X{_coord(poly[0][0])}Y{_coord(poly[0][1])}D01*")
        self.lines.append("G37*")

    def render(self) -> str:
        return "\n".join(self.lines + ["M02*"]) + "\n"


# --------------------------------------------------------------------------- #
# board -> gerber files
# --------------------------------------------------------------------------- #
def copper_gerber(layer: dict, file_function: str) -> str:
    g = GerberWriter(file_function)
    for d in layer.get("draws", []):
        g.polyline(d["points"], d["width"])
    for f in layer.get("flashes", []):
        g.flash(f["shape"], f["x"], f["y"], f["w"], f["h"], f.get("rot", 0.0))
    return g.render()


def mask_gerber(layer: dict, file_function: str) -> str:
    g = GerberWriter(file_function)
    for f in layer.get("flashes", []):
        g.flash(f["shape"], f["x"], f["y"], f["w"], f["h"], f.get("rot", 0.0))
    return g.render()


def silk_gerber(layer: dict, file_function: str) -> str:
    g = GerberWriter(file_function)
    for ln in layer.get("lines", []):
        g.polyline(ln["points"], ln["width"])
    for tx in layer.get("text", []):
        g.polyline(tx["points"], tx["width"])
    return g.render()


def edge_gerber(outlines: List[List[List[float]]]) -> str:
    g = GerberWriter("Profile,NP")
    for poly in outlines:
        g.polyline(poly, 0.10)
    return g.render()


# --------------------------------------------------------------------------- #
# Excellon
# --------------------------------------------------------------------------- #
def excellon(drills: List[dict], plated: bool = True) -> str:
    tools: Dict[float, int] = {}
    lines = [
        "M48",
        "; Circuit drill file -- units mm",
        "FMAT,2",
        "METRIC,TZ",
    ]
    for d in drills:
        if d["plated"] != plated:
            continue
        dia = round(d["diameter"], 3)
        if dia not in tools:
            tools[dia] = len(tools) + 1
    for dia in sorted(tools):
        lines.append(f"T{tools[dia]}C{dia:.3f}")
    lines.append("%")
    lines.append("G90")
    lines.append("G05")
    by_tool: Dict[int, List[dict]] = {}
    for d in drills:
        if d["plated"] != plated:
            continue
        by_tool.setdefault(tools[round(d["diameter"], 3)], []).append(d)
    for t in sorted(by_tool):
        lines.append(f"T{t}")
        for d in by_tool[t]:
            lines.append(f"X{d['x']:.3f}Y{d['y']:.3f}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# reader (verification + a fallback renderer path)
# --------------------------------------------------------------------------- #
_ADD_RE = re.compile(r"%ADD(\d+)([A-Z]+),([^*%]*)\*%")
_FLASH_RE = re.compile(r"X(-?\d+)Y(-?\d+)D03\*")
_MOVE_RE = re.compile(r"X(-?\d+)Y(-?\d+)D02\*")
_DRAW_RE = re.compile(r"X(-?\d+)Y(-?\d+)D01\*")
_SEL_RE = re.compile(r"^D(\d+)\*$")


def parse_gerber(text: str) -> dict:
    apertures: Dict[int, dict] = {}
    flashes: List[dict] = []
    draws: List[dict] = []
    regions: List[List[Tuple[float, float]]] = []
    cur = None
    in_region = False
    region_pts: List[Tuple[float, float]] = []
    last: Optional[Tuple[float, float]] = None
    scale = 1e6
    for raw in text.splitlines():
        line = raw.strip()
        m = _ADD_RE.match(line)
        if m:
            apertures[int(m.group(1))] = {
                "kind": m.group(2),
                "params": [float(x) for x in m.group(3).split("X") if x],
            }
            continue
        if line.startswith("%FSLAX"):
            mm = re.match(r"%FSLAX(\d)(\d)Y", line)
            if mm:
                scale = 10 ** int(mm.group(2))
            continue
        if line == "%MOIN*%":
            raise ValueError("inch Gerber is not supported")
        if line == "G36*":
            in_region = True
            region_pts = []
            continue
        if line == "G37*":
            if len(region_pts) >= 3:
                regions.append(region_pts)
            in_region = False
            region_pts = []
            continue
        sel = _SEL_RE.match(line)
        if sel:
            cur = int(sel.group(1))
            continue
        m = _MOVE_RE.match(line)
        if m:
            p = (int(m.group(1)) / scale, int(m.group(2)) / scale)
            last = p
            if in_region:
                region_pts.append(p)
            continue
        m = _DRAW_RE.match(line)
        if m:
            p = (int(m.group(1)) / scale, int(m.group(2)) / scale)
            if in_region:
                region_pts.append(p)
            elif last is not None and cur in apertures:
                ap = apertures[cur]
                width = ap["params"][0] if ap["params"] else 0.2
                draws.append({"points": [list(last), list(p)], "width": width})
            last = p
            continue
        m = _FLASH_RE.match(line)
        if m:
            p = (int(m.group(1)) / scale, int(m.group(2)) / scale)
            ap = apertures.get(cur, {"kind": "C", "params": [0.2]})
            flashes.append({"x": p[0], "y": p[1], "kind": ap["kind"], "params": ap["params"]})
            last = p
    return {"apertures": apertures, "flashes": flashes, "draws": draws, "regions": regions}
