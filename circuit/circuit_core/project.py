"""Board project model: components, nets, rules, ERC.

The project is the single source of truth the tools read and write. It is a
plain JSON-serialisable dict, so a board can be inspected, diffed and repaired
by hand — and the router/exporters take it as input without hidden state.
"""

from __future__ import annotations

import math
import re
import os
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import geom
from .lib import footprints, parts

SCHEMA = 1

DEFAULT_RULES = {
    "trace_width": 0.20,
    "clearance": 0.15,
    "via_diameter": 0.60,
    "via_drill": 0.30,
    "min_trace": 0.15,
    "min_clearance": 0.15,
    "min_drill": 0.25,
    "edge_clearance": 0.30,
    "grid": 0.10,
    "chamfer": 0.35,
    # Soldermask covers vias unless a board asks otherwise: exposed vias wick
    # solder and short under a stencil.
    "tent_vias": True,
}

NET_CLASS_WIDTH = {"signal": 0.20, "power": 0.30, "ground": 0.30, "diff": 0.20}

_POWER_RE = re.compile(
    r"^(\+?\d+(\.\d+)?V\d*|VCC|VDD|VIN|VBUS|VBAT|VSYS|V\+|5V|3V3|12V|24V)$", re.I)
_GROUND_RE = re.compile(r"^(GND|AGND|PGND|DGND|VSS|0V|EARTH)$", re.I)

_REF_PREFIX = {
    "passive": None,  # by tag
    "opto": "D",
    "diode": "D",
    "transistor": "Q",
    "power": "U",
    "ic": "U",
    "sensor": "U",
    "module": "U",
    "connector": "J",
    "switch": "SW",
    "relay": "K",
    "audio": "LS",
    "timing": "Y",
    "mechanical": "H",
}


def canonical_net(name: str) -> str:
    n = re.sub(r"\s+", "_", (name or "").strip())
    return n.upper()


def net_class(name: str) -> str:
    if _GROUND_RE.match(name):
        return "ground"
    if _POWER_RE.match(name):
        return "power"
    return "signal"


def _ref_prefix(part: dict) -> str:
    tags = part.get("tags") or []
    cat = part.get("category", "ic")
    if cat == "passive":
        if "resistor" in tags:
            return "R"
        if "capacitor" in tags:
            return "C"
        if "inductor" in tags:
            return "L"
        if "ferrite" in tags:
            return "FB"
        if "protection" in tags:
            return "F"
        return "E"
    return _REF_PREFIX.get(cat, "U")


class BoardError(ValueError):
    """A user-facing problem with the board definition."""


class Board:
    def __init__(self, data: dict):
        self.data = data
        self._reindex()

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @classmethod
    def create(cls, title: str, width: float = 40.0, height: float = 30.0,
               layers: int = 2, thickness: float = 1.6, corner_radius: float = 2.0,
               rules: Optional[dict] = None) -> "Board":
        width, height = float(width), float(height)
        if not (10.0 <= width <= 400.0 and 10.0 <= height <= 400.0):
            raise BoardError("board dimensions must be between 10 and 400 mm")
        if layers not in (2,):
            raise BoardError("this engine routes 2-layer boards; layers must be 2")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data = {
            "schema": SCHEMA,
            "slug": "",
            "title": title.strip()[:120] or "Untitled board",
            "created": now,
            "updated": now,
            "board": {
                "width": round(width, 3),
                "height": round(height, 3),
                "layers": layers,
                "thickness": float(thickness),
                "corner_radius": min(float(corner_radius), min(width, height) / 2.0 - 0.5),
                "finish": "HASL",
                "soldermask": "green",
            },
            "rules": dict(DEFAULT_RULES, **(rules or {})),
            "components": [],
            "nets": {},
            "routes": {},
            "vias": [],
            "meta": {"generator": "circuit", "version": 1},
        }
        return cls(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Board":
        if not isinstance(data, dict) or "board" not in data:
            raise BoardError("not a circuit board document")
        data.setdefault("rules", dict(DEFAULT_RULES))
        for k, v in DEFAULT_RULES.items():
            data["rules"].setdefault(k, v)
        data.setdefault("components", [])
        data.setdefault("nets", {})
        data.setdefault("routes", {})
        data.setdefault("vias", [])
        data.setdefault("meta", {})
        return cls(data)

    def _reindex(self) -> None:
        self.by_ref: Dict[str, dict] = {c["ref"]: c for c in self.data["components"]}
        self._pad_cache: Optional[List[dict]] = None

    def touch(self) -> None:
        # Anything that moves or edits a component calls this, so the cached pad
        # positions are stale from here on. Without the invalidation the router
        # routed to where the parts used to be: traces crossed real pads and nets
        # came back unrouted on a board that looked fine.
        self._pad_cache = None
        # SOURCE_DATE_EPOCH pins the stamp as well: board.json is part of the
        # export package, and a moving timestamp there makes every hash in the
        # manifest change on each build.
        epoch = os.environ.get("SOURCE_DATE_EPOCH")
        if epoch and epoch.isdigit():
            self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch)))
        else:
            self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._reindex()

    # ------------------------------------------------------------------ #
    # geometry helpers
    # ------------------------------------------------------------------ #
    @property
    def board(self) -> dict:
        return self.data["board"]

    @property
    def rules(self) -> dict:
        return self.data["rules"]

    def outline(self, samples_per_corner: int = 6) -> List[geom.Point]:
        b = self.board
        w, h, r = b["width"], b["height"], b.get("corner_radius", 0.0)
        if r <= 0.01:
            return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
        pts: List[geom.Point] = []
        corners = [
            (w - r, r, -90.0), (w - r, h - r, 0.0), (r, h - r, 90.0), (r, r, 180.0),
        ]
        for cx, cy, start in corners:
            for i in range(samples_per_corner + 1):
                a = math.radians(start + 90.0 * i / samples_per_corner)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def world_pads(self, ref: Optional[str] = None) -> List[dict]:
        if ref is None and self._pad_cache is not None:
            return self._pad_cache
        out: List[dict] = []
        for c in self.data["components"]:
            if ref and c["ref"] != ref:
                continue
            fp = footprints.get(parts.get(c["part"])["footprint"])
            cx, cy = c.get("x") or 0.0, c.get("y") or 0.0
            for pad in fp["pads"]:
                x, y = geom.place((pad["x"], pad["y"]), cx, cy, c.get("rot", 0.0))
                out.append({
                    "ref": c["ref"], "num": pad["num"], "name": pad["name"],
                    "kind": pad["kind"], "shape": pad["shape"],
                    "x": x, "y": y, "w": pad["w"], "h": pad["h"],
                    "rot": (pad.get("rot", 0.0) + c.get("rot", 0.0)) % 360.0,
                    "drill": pad.get("drill", 0.0), "r": pad.get("r", 0.0),
                    "layer": pad["layer"] if pad["kind"] != "tht" else "both",
                    "net": (c.get("nets") or {}).get(pad["num"]),
                })
        if ref is None:
            self._pad_cache = out
        return out

    def pad(self, ref: str, pin: str) -> dict:
        for p in self.world_pads(ref):
            if p["num"] == str(pin):
                return p
        raise BoardError(f"{ref} has no pin {pin}")

    def component(self, ref: str) -> dict:
        if ref not in self.by_ref:
            raise BoardError(f"no component {ref!r} on this board")
        return self.by_ref[ref]

    def courtyard(self, ref: str) -> List[geom.Point]:
        c = self.component(ref)
        fp = footprints.get(parts.get(c["part"])["footprint"])
        cw, ch = fp["courtyard"]["w"], fp["courtyard"]["h"]
        if cw <= 0 or ch <= 0:
            return []
        local = [(-cw / 2, -ch / 2), (cw / 2, -ch / 2), (cw / 2, ch / 2), (-cw / 2, ch / 2)]
        return [geom.place(p, c.get("x") or 0.0, c.get("y") or 0.0, c.get("rot", 0.0))
                for p in local]

    def body(self, ref: str) -> dict:
        c = self.component(ref)
        fp = footprints.get(parts.get(c["part"])["footprint"])
        return dict(fp["body"], x=c.get("x") or 0.0, y=c.get("y") or 0.0,
                    rot=c.get("rot", 0.0), ref=ref,
                    pad_nets=c.get("nets") or {})

    # ------------------------------------------------------------------ #
    # editing
    # ------------------------------------------------------------------ #
    def add_component(self, part_id: str, nets: Optional[Dict[str, str]] = None,
                      ref: Optional[str] = None, value: str = "",
                      x: Optional[float] = None, y: Optional[float] = None,
                      rot: float = 0.0, group: str = "") -> dict:
        part = parts.get(part_id)
        fp = footprints.get(part["footprint"])
        nets = {str(k): canonical_net(v) for k, v in (nets or {}).items() if v}
        unknown = [k for k in nets if k not in {p["num"] for p in fp["pads"]}]
        if unknown:
            raise BoardError(
                f"{part_id} has no pin(s) {', '.join(unknown)} "
                f"(pins: {', '.join(p['num'] for p in fp['pads'])})")
        ref = (ref or self._next_ref(part)).upper()
        if ref in self.by_ref:
            raise BoardError(f"reference {ref} already used")
        c = {
            "ref": ref,
            "part": part_id,
            "value": value or part["name"],
            "x": float(x) if x is not None else None,
            "y": float(y) if y is not None else None,
            "rot": float(rot) % 360.0,
            "layer": "top",
            "nets": nets,
            "group": group,
            "locked": False,
        }
        self.data["components"].append(c)
        for n in nets.values():
            self._ensure_net(n)
        self.touch()
        return c

    def _ensure_net(self, name: str) -> dict:
        name = canonical_net(name)
        net = self.data["nets"].get(name)
        if net is None:
            cls = net_class(name)
            net = {"class": cls, "width": NET_CLASS_WIDTH.get(cls, self.rules["trace_width"])}
            self.data["nets"][name] = net
        return net

    def _next_ref(self, part: dict) -> str:
        prefix = _ref_prefix(part)
        used = set()
        for c in self.data["components"]:
            m = re.match(r"^([A-Z]+)(\d+)$", c["ref"])
            if m and m.group(1) == prefix:
                used.add(int(m.group(2)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}{n}"

    def remove_component(self, ref: str) -> None:
        self.component(ref)
        self.data["components"] = [c for c in self.data["components"] if c["ref"] != ref]
        self.touch()

    def set_net(self, ref: str, pin: str, net: str) -> None:
        c = self.component(ref)
        part = parts.get(c["part"])
        fp = footprints.get(part["footprint"])
        nums = {p["num"] for p in fp["pads"]}
        pin = str(pin)
        if pin not in nums:
            # A datasheet gives you names, not pad numbers: accept either, as long
            # as the name is unambiguous ("SDA" for pad 4 of a BME280 breakout).
            names = part.get("pins") or {}
            match = [num for num, name in names.items()
                     if str(name).lower() == pin.lower() and num in nums]
            if len(match) == 1:
                pin = match[0]
            elif len(match) > 1:
                raise BoardError(
                    f"{ref} has {len(match)} pins named {pin} (pads {', '.join(match)}) — "
                    f"use the pad number")
            else:
                known = ", ".join(f"{num}={name}" for num, name in list(names.items())[:8])
                raise BoardError(f"{ref} has no pin {pin} (known pins: {known}…)")
        if net:
            c["nets"][pin] = canonical_net(net)
            self._ensure_net(c["nets"][str(pin)])
        else:
            c["nets"].pop(pin, None)
        self.touch()

    def rename_net(self, old: str, new: str) -> None:
        old, new = canonical_net(old), canonical_net(new)
        if old not in self.data["nets"]:
            raise BoardError(f"no net {old}")
        for c in self.data["components"]:
            for pin, net in list((c.get("nets") or {}).items()):
                if net == old:
                    c["nets"][pin] = new
        self.data["nets"][new] = self.data["nets"].pop(old)
        if old in self.data["routes"]:
            self.data["routes"][new] = self.data["routes"].pop(old)
        for v in self.data["vias"]:
            if v.get("net") == old:
                v["net"] = new
        self.touch()

    def set_position(self, ref: str, x: float, y: float, rot: Optional[float] = None) -> None:
        c = self.component(ref)
        c["x"], c["y"] = float(x), float(y)
        if rot is not None:
            c["rot"] = float(rot) % 360.0
        self.touch()

    def connect(self, pairs: Iterable[Sequence[str]]) -> List[str]:
        """``[["U1","GP0","R1","1"], ...]`` — every pin in a tuple joins one net.

        Existing nets on those pins win (first non-empty name found), otherwise
        a name is generated from the component refs.
        """
        touched: List[str] = []
        for pair in pairs:
            if len(pair) < 2 or len(pair) % 2 != 0:
                raise BoardError("connections must be [ref, pin, ref, pin, ...]")
            pins = [(str(pair[i]).upper(), str(pair[i + 1])) for i in range(0, len(pair), 2)]
            for ref, pin in pins:
                self.component(ref)
            existing = None
            for ref, pin in pins:
                c = self.component(ref)
                n = (c.get("nets") or {}).get(pin)
                if n:
                    existing = existing or n
            name = existing or self._auto_net_name(pins)
            for ref, pin in pins:
                self.set_net(ref, pin, name)
            touched.append(name)
        self._prune_nets()
        self.touch()
        return touched

    def _auto_net_name(self, pins: Sequence[Tuple[str, str]]) -> str:
        base = "N_" + "_".join(f"{r}{p}" for r, p in pins[:3])
        name, i = base, 2
        while name in self.data["nets"]:
            name = f"{base}_{i}"
            i += 1
        return name

    def _prune_nets(self) -> None:
        used = {n for c in self.data["components"] for n in (c.get("nets") or {}).values()}
        for name in list(self.data["nets"]):
            if name not in used:
                self.data["nets"].pop(name, None)
                self.data["routes"].pop(name, None)
                self.data["vias"] = [v for v in self.data["vias"] if v.get("net") != name]

    def clear_routes(self, net: Optional[str] = None) -> None:
        if net:
            self.data["routes"].pop(canonical_net(net), None)
            self.data["vias"] = [v for v in self.data["vias"] if v.get("net") != canonical_net(net)]
        else:
            self.data["routes"] = {}
            self.data["vias"] = []
        self.touch()

    # ------------------------------------------------------------------ #
    # net helpers
    # ------------------------------------------------------------------ #
    def net_pins(self) -> Dict[str, List[dict]]:
        out: Dict[str, List[dict]] = {}
        for p in self.world_pads():
            if p["net"] and p["kind"] != "npth":
                out.setdefault(p["net"], []).append(p)
        return out

    def netlist(self) -> Dict[str, List[str]]:
        return {n: [f"{p['ref']}.{p['name']}" for p in pins]
                for n, pins in sorted(self.net_pins().items())}

    def stats(self) -> dict:
        nets = self.net_pins()
        routed = sum(1 for n, rs in self.data["routes"].items() if rs)
        return {
            "components": len(self.data["components"]),
            "nets": len(self.data["nets"]),
            "routed_nets": routed,
            "pads": len(self.world_pads()),
            "vias": len(self.data["vias"]),
            "board_mm": f"{self.board['width']} x {self.board['height']}",
            "area_mm2": round(self.board["width"] * self.board["height"], 1),
        }

    # ------------------------------------------------------------------ #
    # electrical rule check
    # ------------------------------------------------------------------ #
    def erc(self) -> dict:
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        if not self.data["components"]:
            errors.append("board has no components")

        nets = self.net_pins()
        for name, net in self.data["nets"].items():
            pins = nets.get(name, [])
            if len(pins) < 2:
                warnings.append(
                    f"net {name} has only {len(pins)} pin(s) — dangling" if pins
                    else f"net {name} has no pins")
        if not any(net_class(n) == "ground" for n in self.data["nets"]):
            warnings.append("no ground net (no net named GND/VSS/AGND)")
        if self.data["components"] and not any(net_class(n) == "power" for n in self.data["nets"]):
            warnings.append("no power net (no net named +3V3/5V/VCC/VIN/…)")

        # every module/IC should have at least one net on it
        for c in self.data["components"]:
            part = parts.get(c["part"])
            if part["category"] in ("ic", "module") and not (c.get("nets") or {}):
                warnings.append(f"{c['ref']} ({part['name']}) has no pins connected")

        # overlapping courtyards
        comps = [c for c in self.data["components"] if c.get("x") is not None]
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                a, b = comps[i], comps[j]
                ca, cb = self.courtyard(a["ref"]), self.courtyard(b["ref"])
                if not ca or not cb:
                    continue
                if geom.bbox_gap(geom.bbox(ca), geom.bbox(cb)) <= 0.0:
                    errors.append(f"courtyard overlap: {a['ref']} and {b['ref']}")

        # components outside the board
        out_pts = self.outline(8)
        for c in comps:
            x, y = c["x"], c["y"]
            if not (0 <= x <= self.board["width"] and 0 <= y <= self.board["height"]):
                errors.append(f"{c['ref']} is placed outside the board outline")
            elif not geom.point_in_polygon((x, y), out_pts):
                warnings.append(f"{c['ref']} centre is outside the board outline")

        if comps and len(comps) == len(self.data["components"]):
            info.append("all components placed")
        return {"errors": errors, "warnings": warnings, "info": info,
                "ok": not errors}

    # ------------------------------------------------------------------ #
    # serialisation
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return self.data

    def summary(self) -> dict:
        return {
            "slug": self.data.get("slug", ""),
            "title": self.data["title"],
            "board": self.board,
            "stats": self.stats(),
            "erc": self.erc(),
            "components": [
                {"ref": c["ref"], "part": c["part"], "value": c["value"],
                 "x": c.get("x"), "y": c.get("y"), "rot": c.get("rot", 0.0),
                 "nets": c.get("nets") or {}}
                for c in self.data["components"]
            ],
            "nets": {n: {"class": v["class"], "pins": len(self.net_pins().get(n, [])),
                         "routed": bool(self.data["routes"].get(n))}
                     for n, v in self.data["nets"].items()},
            "updated": self.data.get("updated"),
        }
