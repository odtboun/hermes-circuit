"""Build pipeline: place -> route -> check -> export.

``build()`` is the one call the tools use; it is idempotent and always leaves
the project directory in a consistent state (model, view, manifest, exports).
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import json
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from . import drc as drc_mod
from . import layers, placement, router, store, view
from .fab import docs as docs_mod
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


def _build_epoch() -> int:
    """Timestamp used in every generated file.

    Honours SOURCE_DATE_EPOCH (the reproducible-builds convention) so two exports
    of the same board produce byte-identical files; otherwise it is "now". The
    manifest's hashes are only a fingerprint if the inputs pin this.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(time.time())


def _zip_add(zf: zipfile.ZipFile, path: str, arcname: str, epoch: int) -> None:
    """Add a file with a pinned timestamp, so the zip is reproducible too."""
    stamp = time.gmtime(max(epoch, 315532800))  # zip cannot go below 1980
    info = zipfile.ZipInfo(arcname, date_time=stamp[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, Path(path).read_bytes())


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
    # Stencil apertures. layers.paste() existed but was never written, so the
    # package had no way to order a stencil for the SMT side.
    put(f"gerbers/{slug}-F_Paste.gbr", gerber.mask_gerber(layers.paste(board)["F.Paste"], "Paste,Top"))

    # A fab needs the stackup in the zip, not in a manifest it never opens.
    epoch = _build_epoch()
    put("readme.txt", _readme(board, slug, epoch))
    put(f"{slug}.gbrjob", json.dumps(_gbrjob(board, slug, epoch), indent=2))

    # fab zip: gerbers, drills, stencil, readme and the job file
    zpath = ex / f"{slug}-gerbers.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(written):
            if name.startswith("gerbers/") or name in ("readme.txt", f"{slug}.gbrjob"):
                _zip_add(zf, written[name], Path(name).name, epoch)
    written[f"{slug}-gerbers.zip"] = str(zpath)

    put(f"kicad/{slug}.kicad_pcb", kicad.kicad_pcb(board))
    put(f"kicad/{slug}.kicad_pro", kicad.kicad_pro(board, f"{slug}.kicad_pro"))
    put(f"{slug}.step", step_mod.write_step(board, epoch))
    put("bom.csv", _csv(layers.bom(board),
                        ["Refs", "Qty", "Value", "Part", "Footprint", "Description", "MPN", "Mfr"]))
    put("pos.csv", _csv(layers.placement(board),
                        ["Ref", "Part", "Footprint", "PosX", "PosY", "Rot", "Side"]))
    # Assembly houses take a dialect, not a generic file: millimetres, "Mid X/Y"
    # with Y measured from the bottom-left, and the layer named Top/Bottom.
    put("pos-jlcpcb.csv", _csv(layers.placement_assembly(board),
                               ["Designator", "Val", "Package", "Mid X", "Mid Y", "Layer", "Rotation"]))
    put("netlist.json", json.dumps(board.netlist(), indent=1))
    put("preview.svg", svg.render_svg(board))
    put("preview.html", svg.render_html(board))
    # Documents generated from the same netlist: what to buy, what to wire where,
    # and a one-page poster. Standalone HTML, so they open anywhere.
    put("bom.html", docs_mod.shopping_html(board))
    put("wiring.html", docs_mod.wiring_html(board))
    put("poster.html", docs_mod.poster_html(board))
    # assembly zip: what a contract manufacturer quotes from
    apath = ex / f"{slug}-assembly.zip"
    with zipfile.ZipFile(apath, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("bom.csv", "bom.html", "wiring.html", "pos.csv",
                     "pos-jlcpcb.csv", "readme.txt", f"gerbers/{slug}-F_Paste.gbr"):
            if name in written:
                _zip_add(zf, written[name], Path(name).name, epoch)
    written[f"{slug}-assembly.zip"] = str(apath)

    put("board.json", json.dumps(board.to_dict(), indent=1))
    put("manifest.json", json.dumps(_manifest(board, written, ex, epoch), indent=1))
    written["manifest.json"] = str(ex / "manifest.json")
    return written


def _readme(board: Board, slug: str, epoch: Optional[int] = None) -> str:
    """The stackup and rules a fabricator reads. Lives inside the zip because the
    manifest does not travel with the gerbers."""
    b = board.board
    drc = board.data.get("drc") or {}
    issues = len(drc.get("errors") or []) + len(drc.get("warnings") or [])
    tented = board.rules.get("tent_vias", True)
    lines = [
        f"{board.data.get('title') or slug}  ({slug})",
        f"Generated by {TOOL['name']} {TOOL['version']} on "
        f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(epoch))}",
        "",
        "BOARD",
        f"  size            {b['width']:.2f} x {b['height']:.2f} mm",
        f"  copper          {b.get('layers', 2)} layers, {b.get('thickness', 1.6):.2f} mm FR4",
        f"  surface finish  {b.get('finish', 'HASL')}",
        f"  soldermask      {b.get('soldermask', 'green')}",
        "  silkscreen      white",
        "",
        "FILES",
        "  *.gbr            RS-274X, 4.6 metric, X2 file-function attributes",
        "  *-PTH.drl        Excellon, metric, plated through holes",
        "  *-NPTH.drl       Excellon, metric, non-plated holes",
        "  *-F_Paste.gbr    stencil apertures, top side",
        f"  {slug}.gbrjob   Ucamco job file (layer roles and stackup)",
        "",
        "DESIGN RULES",
        f"  trace / space    {board.rules['trace_width']:.2f} / {board.rules['clearance']:.2f} mm",
        f"  via              {board.rules['via_diameter']:.2f} / {board.rules['via_drill']:.2f} mm",
        f"  minimum drill    {board.rules['min_drill']:.2f} mm",
        f"  edge clearance   {board.rules['edge_clearance']:.2f} mm",
        "",
        "NOTES",
        "  Vias are tented (covered by soldermask)." if tented
        else "  Vias are exposed through the soldermask.",
        "  Footprint geometry comes from the bundled library: verify against the",
        "  supplier datasheet before ordering.",
        f"  DRC at generation: {'clean' if drc.get('ok') else f'{issues} issue(s)'}.",
        "",
    ]
    return "\n".join(lines)


def _gbrjob(board: Board, slug: str, epoch: Optional[int] = None) -> dict:
    """Ucamco Gerber job file: tells the fab which file is which layer and the
    stackup, so it does not have to guess from file names."""
    b = board.board
    layers = [
        (f"{slug}-F_Cu.gbr", "Copper,L1,Top"),
        (f"{slug}-B_Cu.gbr", "Copper,L2,Bot"),
        (f"{slug}-F_Mask.gbr", "Soldermask,Top"),
        (f"{slug}-B_Mask.gbr", "Soldermask,Bot"),
        (f"{slug}-F_Silkscreen.gbr", "Legend,Top"),
        (f"{slug}-B_Silkscreen.gbr", "Legend,Bot"),
        (f"{slug}-F_Paste.gbr", "Paste,Top"),
        (f"{slug}-Edge_Cuts.gbr", "Profile,NP"),
        (f"{slug}-PTH.drl", "Plated,1,2,PTH"),
        (f"{slug}-NPTH.drl", "NonPlated,1,2,NPTH"),
    ]
    return {
        "Header": {
            "GenerationSoftware": {"Vendor": "Circuit", "Application": TOOL["name"],
                                   "Version": TOOL["version"]},
            "CreationDate": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(epoch)),
            "ProjectId": {"Name": slug},
        },
        "GeneralSpecs": {
            "ProjectId": {"Name": slug},
            "Size": {"X": b["width"], "Y": b["height"]},
            "LayerNumber": b.get("layers", 2),
            "BoardThickness": b.get("thickness", 1.6),
            "Finish": b.get("finish", "HASL"),
        },
        "FilesAttributes": [
            {"Path": name, "FileFunction": fn, "FilePolarity": "Positive"}
            for name, fn in layers
        ],
    }


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
        "MPN": lambda r: r.get("mpn", ""),
        "Mfr": lambda r: r.get("mfr", ""),
        "Designator": lambda r: r.get("ref", ""),
        "Val": lambda r: r.get("value", ""),
        "Package": lambda r: r.get("footprint", ""),
        "Mid X": lambda r: f"{r.get('mx', 0):.3f}",
        "Mid Y": lambda r: f"{r.get('my', 0):.3f}",
        "Layer": lambda r: "Top" if r.get("side", "top") == "top" else "Bottom",
        "Rotation": lambda r: f"{r.get('rot', 0.0):.1f}",
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


def _manifest(board: Board, written: Dict[str, str], root: Path,
              epoch: Optional[int] = None) -> dict:
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
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)),
        "tool": TOOL,
        "rules": board.rules,
        "stats": board.stats(),
        "drc": board.data.get("drc", {}),
        "files": files,
        "notes": [
            "Gerbers are RS-274X with a 4.6 metric format; drills are Excellon with a metric header.",
            "KiCad 8 project opens in the PCB editor; the schematic is intentionally not synthesised.",
            "STEP is an AP214 B-rep of the substrate and component bodies.",
            "bom.html, wiring.html and poster.html are generated documents: the "
            "shopping list links to distributor searches built from each MPN.",
            "Footprint geometry comes from the bundled library — verify against your supplier's datasheet before ordering.",
        ],
    }
