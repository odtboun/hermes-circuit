"""Tool handlers — the agent-facing surface of the engine."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from . import settings
from .circuit_core import compile as builder
from .circuit_core import drc as drc_mod
from .circuit_core import import_kicad, placement, router, samples, store, templates, view
from .circuit_core.lib import parts
from .circuit_core.project import Board, BoardError

MAX_COMPONENTS_IN_OUTPUT = 60


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def ok(**payload) -> str:
    return json.dumps({"ok": True, **payload}, separators=(",", ":"))


def err(message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": str(message), **extra}, separators=(",", ":"))


def _board(args: dict) -> Board:
    slug = (args.get("board") or "").strip()
    if not slug:
        slug = store.latest() or ""
    if not slug:
        raise BoardError("no boards yet — call circuit_create first")
    return store.load(slug)


def _writable(board: Board) -> Board:
    """Imported KiCad boards are a picture, not a project: refuse edits."""
    if board.data.get("imported"):
        raise BoardError(
            f"board {board.data.get('slug')!r} is an imported KiCad design (read-only) — "
            "call circuit_create to start an editable board")
    return board


def _imported_summary(board: Board) -> dict:
    doc = store.load_view(board.data.get("slug") or "")
    return {
        "board": board.data.get("slug"),
        "title": doc.get("title"),
        "imported": True,
        "size_mm": [doc["board"]["width"], doc["board"]["height"]],
        "layers": doc["board"]["layers"],
        "components": [
            {"ref": c["ref"], "part": c["part"], "value": c["value"],
             "pins": len(c["pins"]), "placed": True}
            for c in doc["components"][:MAX_COMPONENTS_IN_OUTPUT]
        ],
        "component_count": len(doc["components"]),
        "nets": [{"name": n["name"], "class": n["class"], "pads": len(n["pins"]),
                  "routed": n["routed"]} for n in doc["nets"]],
        "stats": doc["stats"],
        "erc": doc.get("erc"),
        "note": "imported from KiCad — read-only, not routed or checked by this engine",
        "next": ["circuit_view — open the imported board in the viewer"],
    }


def _persist(board: Board) -> dict:
    # keep the stored board drawable: an unplaced part has no coordinates yet
    if any(c.get("x") is None for c in board.data["components"]):
        placement.auto_place(board)
    slug = store.save(board)
    stage = store.load(slug)
    doc = view.view_model(stage, files=_file_index(slug))
    store.write_view(slug, doc)
    return doc


def _file_index(slug: str) -> dict:
    ex = store.project_dir(slug) / "exports"
    out: Dict[str, dict] = {}
    if not ex.exists():
        return out
    for p in sorted(ex.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            out[p.relative_to(ex).as_posix()] = {"size": p.stat().st_size}
    return out


def _next_steps(board: Board, routed: bool = False) -> list:
    steps = []
    if any(c.get("x") is None for c in board.data["components"]):
        steps.append("circuit_place — auto-place the parts")
    if not routed:
        steps.append("circuit_route — autoroute and run DRC")
    steps.append("circuit_export — write Gerbers, drills, KiCad and STEP")
    steps.append("circuit_view — render the board in the chat")
    return steps


def _summary(board: Board, routed: bool = False) -> dict:
    comps = board.data["components"]
    nets = board.net_pins()
    return {
        "board": board.data.get("slug"),
        "title": board.data["title"],
        "size_mm": [board.board["width"], board.board["height"]],
        "layers": board.board["layers"],
        "components": [
            {"ref": c["ref"], "part": c["part"], "value": c["value"],
             "pins": len(c.get("nets") or {}), "placed": c.get("x") is not None}
            for c in comps[:MAX_COMPONENTS_IN_OUTPUT]
        ],
        "component_count": len(comps),
        "nets": [
            {"name": n, "class": m["class"], "pads": len(nets.get(n, [])),
             "routed": bool(board.data["routes"].get(n))}
            for n, m in sorted(board.data["nets"].items())
        ],
        "stats": board.stats(),
        "erc": board.erc(),
        "next": _next_steps(board, routed),
    }


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
def circuit_catalog(args: dict, **kwargs) -> str:
    try:
        rows = parts.search(args.get("query") or "", args.get("category") or "")
        return ok(parts=rows, count=len(rows), categories=parts.categories(),
                  templates=templates.names(),
                  hint="nets maps pin NUMBER -> net name; pins are listed per part.")
    except Exception as exc:  # never raise into the agent loop
        return err(exc)


def circuit_create(args: dict, **kwargs) -> str:
    title = (args.get("title") or "").strip() or "Untitled board"
    try:
        template = (args.get("template") or "").strip()
        if template:
            board = templates.instantiate(template, title=title)
            placement.auto_place(board)
            routed = router.route_board(board)
            drc = drc_mod.check(board)
            board.data["drc"] = drc
            slug = store.save(board)
            _persist(board)
            return ok(board=slug, from_template=template, routed=routed["stats"],
                      failed_nets=[f["net"] for f in routed["failed"]],
                      drc_ok=drc["ok"], drc_errors=drc["errors"][:6],
                      summary=_summary(store.load(slug), routed=True),
                      next=["circuit_view — see it in the chat",
                            "circuit_export — write the fabrication files"])
        board = Board.create(title,
                             width=float(args.get("width") or settings.get("default_board_width")),
                             height=float(args.get("height") or settings.get("default_board_height")),
                             layers=int(args.get("layers") or 2),
                             rules=settings.rules())
        slug = store.save(board)
        _persist(board)
        return ok(board=slug, summary=_summary(store.load(slug)),
                  hint="Empty board created. Browse circuit_catalog, then circuit_add_part and circuit_connect.")
    except Exception as exc:
        return err(exc)


def circuit_boards(args: dict, **kwargs) -> str:
    try:
        rows = store.list_boards()
        return ok(boards=rows, count=len(rows),
                  hint="Pass the slug as 'board' to any other circuit_* tool.")
    except Exception as exc:
        return err(exc)


def circuit_board(args: dict, **kwargs) -> str:
    try:
        board = _board(args)
        if board.data.get("imported"):
            return ok(**_imported_summary(board))
        return ok(**_summary(board, routed=bool(board.data["routes"])))
    except Exception as exc:
        return err(exc)


def circuit_import(args: dict, **kwargs) -> str:
    try:
        path = (args.get("path") or "").strip()
        url = (args.get("url") or "").strip()
        if not path and not url:
            return err("path or url is required — an absolute path to a .kicad_pcb file, "
                       "or an http(s) URL to a raw .kicad_pcb")
        if url:
            if not url.lower().startswith(("http://", "https://")):
                return err("url must start with http:// or https://")
            name = (url.rsplit("/", 1)[-1] or "board").split("?")[0]
            if not name.lower().endswith(".kicad_pcb"):
                name = f"{name or 'board'}.kicad_pcb"
            with tempfile.TemporaryDirectory(prefix="circuit-import-") as tmp:
                local = samples.download_board(url, Path(tmp) / name, label=url)
                # The temp path changes every call; key the project on the URL so a
                # re-import replaces it instead of piling up -2 copies.
                result = import_kicad.import_board(str(local), source=url)
        else:
            result = import_kicad.import_board(path)
        return ok(**result,
                  next=["circuit_view — open the imported board in the viewer",
                        "circuit_boards — list every project"])
    except Exception as exc:
        return err(exc)


def circuit_samples(args: dict, **kwargs) -> str:
    try:
        action = (args.get("action") or "list").strip().lower()
        if action in ("", "list"):
            rows = samples.names()
            return ok(samples=rows, count=len(rows),
                      hint="circuit_samples action=load id=<sample> downloads and imports it "
                           "read-only (needs network); then circuit_view to render it.")
        if action == "load":
            sample_id = (args.get("id") or "").strip()
            if not sample_id:
                return err("id is required for action=load — see circuit_samples action=list")
            result = samples.load(sample_id)
            return ok(**result,
                      next=["circuit_view — open the imported board in the viewer",
                            "circuit_boards — list every project"])
        return err(f"unknown action {action!r} (use 'list' or 'load')")
    except Exception as exc:
        return err(exc)


def circuit_add_part(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        part_id = (args.get("part") or "").strip()
        comp = board.add_component(part_id, nets=args.get("nets") or {},
                                   ref=(args.get("ref") or None),
                                   value=(args.get("value") or ""))
        doc = _persist(board)
        pins = {p["num"]: p["name"] for p in board.world_pads(comp["ref"])}
        unconnected = [f"{n}:{pins.get(n, '')}" for n in pins if n not in (comp.get("nets") or {})]
        return ok(board=board.data["slug"], added={"ref": comp["ref"], "part": part_id,
                                                   "value": comp["value"],
                                                   "nets": comp.get("nets") or {}},
                  pins=pins, unconnected=unconnected[:40],
                  needs_reroute=bool(board.data["routes"]),
                  next=["circuit_place or circuit_route when the design is complete"])
    except Exception as exc:
        return err(exc)


def circuit_connect(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        groups = args.get("connections") or []
        if not isinstance(groups, list) or not groups:
            return err("connections must be a non-empty list of pin groups")
        forced = (args.get("net") or "").strip()
        touched = []
        for group in groups:
            if not isinstance(group, list) or len(group) < 4 or len(group) % 2:
                return err(f"bad connection group {group!r}: expected [ref, pin, ref, pin, ...]")
            if forced:
                ref, pin = str(group[0]).upper(), str(group[1])
                board.component(ref)
                board.set_net(ref, pin, forced)
                touched.append(forced)
            touched.extend(board.connect([list(group)]))
        doc = _persist(board)
        return ok(board=board.data["slug"], nets=sorted(set(touched)),
                  netlist={n: v for n, v in board.netlist().items() if n in set(touched)},
                  needs_reroute=bool(board.data["routes"]))
    except Exception as exc:
        return err(exc)


def circuit_remove_part(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        ref = (args.get("ref") or "").strip().upper()
        board.remove_component(ref)
        _persist(board)
        return ok(board=board.data["slug"], removed=ref, stats=board.stats())
    except Exception as exc:
        return err(exc)


def circuit_place(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        positions = args.get("positions") or []
        if positions:
            for pos in positions:
                ref = str(pos.get("ref", "")).upper()
                board.set_position(ref, float(pos["x"]), float(pos["y"]),
                                   pos.get("rot") if pos.get("rot") is not None else None)
        else:
            moves = placement.auto_place(board)
            if args.get("fit"):
                placement.fit_board_to_components(board)
            _persist(board)
            return ok(board=board.data["slug"], placed=len(moves), mode="auto",
                      size_mm=[board.board["width"], board.board["height"]],
                      positions=moves[:MAX_COMPONENTS_IN_OUTPUT],
                      next=["circuit_route — autoroute the board"])
        if args.get("fit"):
            placement.fit_board_to_components(board)
        _persist(board)
        return ok(board=board.data["slug"], placed=len(positions), mode="manual",
                  size_mm=[board.board["width"], board.board["height"]],
                  next=["circuit_route — autoroute the board"])
    except Exception as exc:
        return err(exc)


def circuit_route(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        if any(c.get("x") is None for c in board.data["components"]):
            placement.auto_place(board)
        result = router.route_board(board, effort=args.get("effort") or settings.get("effort"))
        drc = drc_mod.check(board)
        board.data["drc"] = drc
        _persist(board)
        return ok(board=board.data["slug"], routing=result["stats"],
                  failed=result["failed"],
                  drc_ok=drc["ok"], drc=drc,
                  stats=board.stats(),
                  next=["circuit_export — write Gerbers/KiCad/STEP",
                        "circuit_view — render the result"])
    except Exception as exc:
        return err(exc)


def circuit_check(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        erc = board.erc()
        result = drc_mod.check(board)
        board.data["drc"] = result
        _persist(board)
        return ok(board=board.data["slug"], erc=erc, drc=result,
                  stats=board.stats(),
                  verdict="pass" if (erc["ok"] and result["ok"]) else "needs work")
    except Exception as exc:
        return err(exc)


def circuit_export(args: dict, **kwargs) -> str:
    try:
        board = _writable(_board(args))
        route = args.get("route")
        do_route = True if route is None else bool(route)
        do_route = do_route and (not board.data["routes"]
                                 or any(c.get("x") is None for c in board.data["components"]))
        summary = builder.build(board, do_route=do_route, export=True,
                                effort=settings.get("effort"))
        files = []
        ex = Path(summary["export_dir"])
        for name in summary["files"]:
            p = ex / name
            files.append({"path": name, "bytes": p.stat().st_size if p.exists() else 0})
        return ok(board=summary["slug"], ok=summary["ok"], drc=summary["drc"],
                  stats=summary["stats"], files=files, export_dir=summary["export_dir"],
                  preview=str(ex / "preview.html"),
                  next=["circuit_view — show the board in the chat",
                        "open the export folder and upload the gerbers zip to your fab"])
    except Exception as exc:
        return err(exc)


def circuit_view(args: dict, **kwargs) -> str:
    try:
        board = _board(args)
        slug = board.data.get("slug") or ""
        doc = store.load_view(slug) if board.data.get("imported") else _persist(board)
        ex = store.project_dir(slug) / "exports"
        preview = ex / "preview.html"
        payload = {
            "board": slug,
            "title": doc["title"],
            "directive": f'::circuit{{board="{slug}"}}',
            "preview_file": str(preview) if preview.exists() else "",
            "preview_directive": (f'::preview{{file="{preview}"}}' if preview.exists() else ""),
            "stats": doc["stats"],
            "drc_ok": (doc.get("drc") or {}).get("ok"),
            "hint": ("Emit the directive line exactly as given, alone on its own line, to render the "
                     "board inline in the Hermes desktop chat. In a terminal or on a remote gateway "
                     "use preview_directive instead."),
        }
        if not args.get("inline", True):
            payload.pop("directive", None)
        return ok(**payload)
    except Exception as exc:
        return err(exc)


HANDLERS = {
    "circuit_catalog": circuit_catalog,
    "circuit_create": circuit_create,
    "circuit_boards": circuit_boards,
    "circuit_import": circuit_import,
    "circuit_samples": circuit_samples,
    "circuit_board": circuit_board,
    "circuit_add_part": circuit_add_part,
    "circuit_connect": circuit_connect,
    "circuit_remove_part": circuit_remove_part,
    "circuit_place": circuit_place,
    "circuit_route": circuit_route,
    "circuit_check": circuit_check,
    "circuit_export": circuit_export,
    "circuit_view": circuit_view,
}
