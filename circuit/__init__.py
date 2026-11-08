"""Circuit — an end-to-end PCB design plugin for Hermes Agent.

The agent designs a board with the circuit_* tools; the same export step writes
Gerbers, Excellon drills, a KiCad project and a STEP model, and the bundled
desktop half renders the board inline in chat.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import schemas, settings, tools

logger = logging.getLogger(__name__)

TOOLSET = "circuit"


def _circuit_command(raw_args: str) -> str:
    """``/circuit`` — quick status readout straight from the CLI/gateway."""
    from .circuit_core import store

    arg = (raw_args or "").strip()
    try:
        if arg:
            board = store.load(arg)
            s = board.stats()
            drc = board.data.get("drc") or {}
            lines = [
                f"{board.data['title']} ({board.data['slug']})",
                f"  {s['board_mm']} mm · {s['components']} parts · {s['nets']} nets · "
                f"{s['routed_nets']} routed",
                f"  DRC: {'pass' if drc.get('ok') else 'not run' if not drc else 'fail'}",
                f"  files: {store.project_dir(board.data['slug']) / 'exports'}",
            ]
            return "\n".join(lines)
        boards = store.list_boards()
        if not boards:
            return "No Circuit boards yet — ask the agent to design one."
        lines = [f"Circuit boards ({len(boards)}):"]
        for b in boards[:20]:
            lines.append(f"  {b['slug']:<28} {b['components']:>3} parts  "
                         f"{b['board'].get('width', '?')}x{b['board'].get('height', '?')} mm  "
                         f"{'routed' if b['routed'] else 'unrouted'}")
        return "\n".join(lines)
    except Exception as exc:  # pragma: no cover - defensive
        return f"circuit: {exc}"


def register(ctx):
    settings.configure(ctx)

    for schema in schemas.ALL:
        handler = tools.HANDLERS[schema["name"]]
        ctx.register_tool(
            name=schema["name"],
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
        )

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)

    ctx.register_command("circuit", _circuit_command,
                         description="Show Circuit boards and their build status")
    logger.debug("circuit: registered %d tools", len(schemas.ALL))
