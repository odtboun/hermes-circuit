"""Board view model — the JSON the desktop viewer renders.

Deliberately renderer-agnostic: layers, primitives and component bodies, no
pixels. Keeping it separate from the viewer means the same document feeds the
inline chat card, the workspace page and the test suite.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from . import drc, layers
from .lib import footprints, parts
from .project import Board


def view_model(board: Board, files: Optional[Dict[str, dict]] = None) -> dict:
    copper = layers.copper(board)
    silk = layers.silk(board)
    comps = []
    for c in board.data["components"]:
        part = parts.get(c["part"])
        fp = footprints.get(part["footprint"])
        pins = []
        for pad in board.world_pads(c["ref"]):
            pins.append({
                "num": pad["num"], "name": pad["name"], "net": pad["net"],
                "x": round(pad["x"], 3), "y": round(pad["y"], 3),
                "w": pad["w"], "h": pad["h"], "shape": pad["shape"],
                "rot": round(pad.get("rot", 0.0), 2), "drill": pad.get("drill", 0.0),
                "kind": pad["kind"],
            })
        comps.append({
            "ref": c["ref"], "part": c["part"], "value": c["value"],
            "category": part["category"], "footprint": part["footprint"],
            "x": round(c.get("x") or 0.0, 3), "y": round(c.get("y") or 0.0, 3),
            "rot": round(c.get("rot", 0.0), 2), "side": c.get("layer", "top"),
            "body": fp["body"], "pins": pins,
        })

    nets = []
    pins_by_net = board.net_pins()
    for name, meta in sorted(board.data["nets"].items()):
        pins = pins_by_net.get(name, [])
        nets.append({
            "name": name, "class": meta["class"], "width": meta.get("width", 0.25),
            "routed": bool(board.data["routes"].get(name)),
            "pins": [f"{p['ref']}.{p['name']}" for p in pins],
        })

    drills = layers.drills(board)
    return {
        "slug": board.data.get("slug", ""),
        "title": board.data["title"],
        "schema": 1,
        "board": {
            "width": board.board["width"], "height": board.board["height"],
            "thickness": board.board["thickness"], "layers": board.board["layers"],
            "corner_radius": board.board.get("corner_radius", 0.0),
            "finish": board.board.get("finish", "HASL"),
            "soldermask": board.board.get("soldermask", "green"),
        },
        "rules": board.rules,
        "outline": [[round(x, 3), round(y, 3)] for x, y in board.outline(10)],
        "copper": copper,
        "silk": silk,
        "drills": [{"x": round(d["x"], 3), "y": round(d["y"], 3),
                    "d": d["diameter"], "plated": d["plated"]} for d in drills],
        "components": comps,
        "nets": nets,
        "bom": layers.bom(board),
        "stats": board.stats(),
        "erc": board.erc(),
        "drc": board.data.get("drc") or {},
        "files": files or {},
        "updated": board.data.get("updated"),
    }


def compact(board: Board, max_nets: int = 0) -> dict:
    """A small summary for tool output and inline cards."""
    return {
        "slug": board.data.get("slug", ""),
        "title": board.data["title"],
        "board": {"width": board.board["width"], "height": board.board["height"],
                  "layers": board.board["layers"]},
        "stats": board.stats(),
        "erc": board.erc(),
        "drc": board.data.get("drc") or {},
        "components": [{"ref": c["ref"], "part": c["part"], "value": c["value"]}
                       for c in board.data["components"]],
        "nets": sorted(board.data["nets"])[:max_nets or None],
    }


def file_hashes(paths: Dict[str, "object"]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for name, p in paths.items():
        try:
            data = p.read_bytes()
        except OSError:
            continue
        out[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16]}
    return out
