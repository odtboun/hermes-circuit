"""Build pipeline: place -> route -> check -> export.

``build()`` is the one call the tools use; it is idempotent and always leaves
the project directory in a consistent state (model, view, manifest, exports).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from . import drc as drc_mod
from . import layers, placement, router, store, view
from .fab import gerber, kicad, step as step_mod, svg
from .project import Board

TOOL = {"name": "circuit", "version": "1.0.0", "format": "gerber-rs274x/excellon/kicad8/step-ap214"}


def build(board: Board, do_route: bool = True, effort: str = "normal",
          export: bool = True, grid: Optional[float] = None) -> dict:
    placed = [c for c in board.data["components"] if c.get("x") is None]
    if placed:
        placement.auto_place(board)
    route_result = None
    if do_route:
        route_result = router.route_board(board, grid=grid, effort=effort)
    result = drc_mod.check(board)
    board.data["drc"] = result
    board.touch()
    slug = store.save(board)
    files: Dict[str, str] = {}
    if export:
        files = export_all(board, slug)
    doc = view.view_model(board, files={k: {"size": Path(v).stat().st_size,
                                            "sha256": _sha(Path(v))[:16]}
                                        for k, v in files.items()})
    store.write_view(slug, doc)
    summary = {
        "slug": slug,
        "ok": result["ok"],
        "drc": result,
        "route": (route_result or {}).get("stats"),
        "failed_nets": [f["net"] for f in (route_result or {}).get("failed", [])],
        "files": sorted(files),
        "export_dir": str(store.project_dir(slug) / "exports"),
        "stats": board.stats(),
    }
    store.touch_build(slug, summary)
    return summary


def export_all(board: Board, slug: str) -> Dict[str, str]:
    root = store.project_dir(slug)
    ex = root / "exports"
    gdir = ex / "gerbers"
    kdir = ex / "kicad"
    for d in (ex, gdir, kdir):
        d.mkdir(parents=True, exist_ok=True)
    copper = layers.copper(board)
    mask = layers.mask(board)
    silk = layers.silk(board)
    drills = layers.drills(board)
    written: Dict[str, str] = {}

    def put(rel: str, text: str) -> Path:
        p = ex / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written[rel] = str(p)
        return p

    put(f"gerbers/{slug}-F_Cu.gbr", gerber.copper_gerber(copper["F.Cu"], "Copper,L1,Top"))
    put(f"gerbers/{slug}-B_Cu.gbr", gerber.copper_gerber(copper["B.Cu"], "Copper,L2,Bot"))
    put(f"gerbers/{slug}-F_Mask.gbr", gerber.mask_gerber(mask["F.Mask"], "Soldermask,Top"))
    put(f"gerbers/{slug}-B_Mask.gbr", gerber.mask_gerber(mask["B.Mask"], "Soldermask,Bot"))
    put(f"gerbers/{slug}-F_Silkscreen.gbr", gerber.silk_gerber(silk["F.SilkS"], "Legend,Top"))
    put(f"gerbers/{slug}-B_Silkscreen.gbr", gerber.silk_gerber(silk["B.SilkS"], "Legend,Bot"))
    put(f"gerbers/{slug}-Edge_Cuts.gbr", gerber.edge_gerber(layers.outline(board)))
    put(f"gerbers/{slug}-PTH.drl", gerber.excellon(drills, plated=True))
    put(f"gerbers/{slug}-NPTH.drl", gerber.excellon(drills, plated=False))

    # fab zip
    zpath = ex / f"{slug}-gerbers.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(written):
            if name.startswith("gerbers/"):
                zf.write(written[name], arcname=Path(name).name)
    written[f"{slug}-gerbers.zip"] = str(zpath)

    put(f"kicad/{slug}.kicad_pcb", kicad.kicad_pcb(board))
    put(f"kicad/{slug}.kicad_pro", kicad.kicad_pro(board, f"{slug}.kicad_pro"))
    put(f"{slug}.step", step_mod.write_step(board))
    put("bom.csv", _csv(layers.bom(board),
                        ["Refs", "Qty", "Value", "Part", "Footprint", "Description"]))
    put("pos.csv", _csv(layers.placement(board),
                        ["Ref", "Part", "Footprint", "PosX", "PosY", "Rot", "Side"]))
    put("netlist.json", json.dumps(board.netlist(), indent=1))
    put("preview.svg", svg.render_svg(board))
    put("preview.html", svg.render_html(board))
    put("board.json", json.dumps(board.to_dict(), indent=1))
    put("manifest.json", json.dumps(_manifest(board, written, ex), indent=1))
    written["manifest.json"] = str(ex / "manifest.json")
    return written


def _csv(rows: List[dict], columns: List[str]) -> str:
    keys = {
        "Refs": lambda r: " ".join(r.get("refs", [r.get("ref", "")])),
        "Qty": lambda r: r.get("qty", 1),
        "Value": lambda r: r.get("value", ""),
        "Part": lambda r: r.get("part", ""),
        "Footprint": lambda r: r.get("footprint", ""),
        "Description": lambda r: r.get("description", ""),
        "Ref": lambda r: r.get("ref", ""),
        "PosX": lambda r: f"{r.get('x', 0):.3f}",
        "PosY": lambda r: f"{r.get('y', 0):.3f}",
        "Rot": lambda r: f"{r.get('rot', 0):.1f}",
        "Side": lambda r: r.get("side", "top"),
    }
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for row in rows:
        w.writerow([keys[c](row) if c in keys else row.get(c, "") for c in columns])
    return buf.getvalue()


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _manifest(board: Board, written: Dict[str, str], root: Path) -> dict:
    files = []
    for rel, abs_path in sorted(written.items()):
        p = Path(abs_path)
        if not p.exists():
            continue
        files.append({"path": rel, "size": p.stat().st_size, "sha256": _sha(p)})
    return {
        "board": {
            "slug": board.data.get("slug"), "title": board.data["title"],
            "width": board.board["width"], "height": board.board["height"],
            "layers": board.board["layers"], "thickness": board.board["thickness"],
            "finish": board.board.get("finish"),
        },
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": TOOL,
        "rules": board.rules,
        "stats": board.stats(),
        "drc": board.data.get("drc", {}),
        "files": files,
        "notes": [
            "Gerbers are RS-274X with a 4.6 metric format; drills are Excellon with a metric header.",
            "KiCad 8 project opens in the PCB editor; the schematic is intentionally not synthesised.",
            "STEP is an AP214 B-rep of the substrate and component bodies.",
            "Footprint geometry comes from the bundled library — verify against your supplier's datasheet before ordering.",
        ],
    }
