"""Backend routes for the Circuit plugin — ``/api/plugins/circuit/``.

Read-only views over the board store plus a rebuild endpoint. Mounted by the
gateway/dashboard loader; the desktop half reaches it through ``ctx.rest``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from circuit_core import compile as builder  # noqa: E402
from circuit_core import drc as drc_mod  # noqa: E402
from circuit_core import placement, store, view  # noqa: E402
from circuit_core import router as autorouter  # noqa: E402
from circuit_core.project import BoardError  # noqa: E402

router = APIRouter()

_SAFE_SUFFIXES = {".gbr", ".drl", ".kicad_pcb", ".kicad_pro", ".step", ".csv",
                  ".json", ".svg", ".html", ".png", ".zip"}


@router.get("/health")
def health():
    return {"ok": True, "plugin": "circuit", "boards": len(store.list_boards())}


@router.get("/boards")
def boards():
    return {"boards": store.list_boards(), "count": len(store.list_boards())}


@router.get("/boards/{slug}")
def board(slug: str):
    try:
        store.resolve(slug)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        doc = store.load_view(slug)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(doc)


@router.get("/boards/{slug}/files")
def files(slug: str):
    try:
        root = store.project_dir(slug) / "exports"
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    out = []
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out.append({"path": p.relative_to(root).as_posix(),
                            "bytes": p.stat().st_size})
    return {"board": slug, "files": out, "export_dir": str(root)}


@router.get("/boards/{slug}/file/{path:path}")
def file(slug: str, path: str):
    try:
        root = (store.project_dir(slug) / "exports").resolve()
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    if target.suffix.lower() not in _SAFE_SUFFIXES:
        raise HTTPException(status_code=415, detail="unsupported file type")
    if target.suffix.lower() in {".html", ".svg"}:
        return FileResponse(target, media_type="text/html" if target.suffix == ".html" else "image/svg+xml")
    return FileResponse(target, filename=target.name)


@router.post("/boards/{slug}/rebuild")
def rebuild(slug: str):
    """Re-run place -> route -> DRC -> export for a board (UI 'Rebuild' button)."""
    try:
        board = store.load(slug)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if board.data.get("imported"):
        # An imported board has no engine part ids and no route table: the router
        # would raise KeyError('unknown part …') and the UI would show a 500.
        raise HTTPException(
            status_code=409,
            detail="this board was imported from KiCad and is read-only — there is nothing to rebuild",
        )
    if any(c.get("x") is None for c in board.data["components"]):
        placement.auto_place(board)
    result = autorouter.route_board(board)
    board.data["drc"] = drc_mod.check(board)
    summary = builder.build(board, do_route=False, export=True)
    doc = store.load_view(slug)
    return {"ok": summary["ok"], "routing": result["stats"],
            "failed": result["failed"], "drc": board.data["drc"],
            "files": summary["files"], "view": doc}


@router.get("/boards/{slug}/view")
def board_view(slug: str):
    """Fresh view model (bypasses the cached view.json)."""
    try:
        board = store.load(slug)
        if board.data.get("imported"):
            # view_model() walks the engine part library, which an imported board
            # has no ids for; its stored view document is the view model.
            return JSONResponse(store.load_view(slug))
        return JSONResponse(view.view_model(board))
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
