"""Project storage.

Boards live in the plugin's own data directory (never inside the install tree,
which ``hermes plugins update`` replaces):

    <plugin data>/projects/<slug>/
        board.json        the model
        view.json         the rendered view model
        manifest.json     export manifest + hashes
        exports/          fab files

The directory is profile-scoped in Hermes and overridable with
``CIRCUIT_DATA_DIR`` for tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from .project import Board, BoardError

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def data_root() -> Path:
    env = os.environ.get("CIRCUIT_DATA_DIR")
    if env:
        return Path(env).expanduser()
    try:
        from plugins.plugin_storage import plugin_data_dir  # type: ignore

        return Path(plugin_data_dir("circuit"))
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
        return home / "plugin-data" / "circuit"


def projects_dir() -> Path:
    p = data_root() / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:48].strip("-")
    return s or "board"


def resolve(slug: str) -> Path:
    slug = (slug or "").strip()
    if not _SLUG_RE.match(slug):
        raise BoardError(f"invalid board id {slug!r}")
    p = projects_dir() / slug
    if not (p / "board.json").exists():
        raise BoardError(f"no board named {slug!r} (use circuit_boards to list)")
    return p


def unique_slug(title: str) -> str:
    base = slugify(title)
    slug, i = base, 2
    while (projects_dir() / slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def save(board: Board, make_slug: bool = True) -> str:
    if make_slug and not board.data.get("slug"):
        board.data["slug"] = unique_slug(board.data["title"])
    slug = board.data["slug"]
    if not _SLUG_RE.match(slug):
        raise BoardError(f"invalid board id {slug!r}")
    root = projects_dir() / slug
    (root / "exports").mkdir(parents=True, exist_ok=True)
    board.touch()
    _write_json(root / "board.json", board.to_dict())
    return slug


def load(slug: str) -> Board:
    root = resolve(slug)
    try:
        data = json.loads((root / "board.json").read_text())
    except json.JSONDecodeError as exc:
        raise BoardError(f"board {slug!r} is corrupt: {exc}") from exc
    board = Board.from_dict(data)
    board.data["slug"] = slug
    return board


def exists(slug: str) -> bool:
    try:
        resolve(slug)
        return True
    except BoardError:
        return False


def project_dir(slug: str) -> Path:
    return resolve(slug)


def delete(slug: str) -> None:
    root = resolve(slug)
    shutil.rmtree(root)


def list_boards() -> List[dict]:
    out: List[dict] = []
    for d in sorted(projects_dir().iterdir()):
        if not d.is_dir() or not (d / "board.json").exists():
            continue
        try:
            data = json.loads((d / "board.json").read_text())
        except Exception:
            continue
        comps = data.get("components") or []
        out.append({
            "slug": d.name,
            "title": data.get("title", d.name),
            "updated": data.get("updated") or "",
            "components": len(comps),
            "nets": len(data.get("nets") or {}),
            "routed": data.get("routed_nets", len(data.get("routes") or {})),
            "board": data.get("board", {}),
            "drc_ok": (data.get("drc") or {}).get("ok"),
            "thumb": (d / "exports" / "preview.svg").exists(),
            "path": str(d),
        })
    out.sort(key=lambda b: b["updated"], reverse=True)
    return out


def latest() -> Optional[str]:
    boards = list_boards()
    return boards[0]["slug"] if boards else None


def write_view(slug: str, view: dict) -> Path:
    root = project_dir(slug)
    path = root / "view.json"
    _write_json(path, view)
    return path


def load_view(slug: str) -> dict:
    root = project_dir(slug)
    path = root / "view.json"
    if path.exists():
        try:
            doc = json.loads(path.read_text())
            # Boards exported before the generated documents existed still have a
            # view.json without them. Add the list on the way out so the page
            # offers the Docs tab without needing a rebuild first. Imported boards
            # have no library parts, so they legitimately have none.
            if "docs" not in doc:
                from .fab import docs as docs_mod

                doc["docs"] = [{"kind": k, "title": t, "file": f}
                               for k, f, t in docs_mod.DOCS]
            return doc
        except json.JSONDecodeError:
            pass
    # view missing or stale: regenerate from the model
    from . import view as view_mod

    board = load(slug)
    doc = view_mod.view_model(board)
    _write_json(path, doc)
    return doc


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)


def touch_build(slug: str, summary: dict) -> None:
    root = project_dir(slug)
    _write_json(root / "build.json", dict(summary, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
