"""Standalone pages generated from a board: shopping list, wiring card, poster.

All three are single self-contained HTML files — inline CSS, inline SVG, no
scripts, no external assets — so they open in the Hermes preview pane, print on
paper, and travel inside an export zip without any of it breaking.

The plugin owns the *shape* of the information: which parts to buy, which pin goes
where, what the board looks like. Facts that need the internet (manufacturer part
numbers) are the agent's job and land in ``bom.csv`` before these pages render.
"""

from __future__ import annotations

import html
from typing import Dict, List, Sequence, Tuple
from urllib.parse import quote_plus

from .. import layers
from ..lib import parts
from ..project import Board, net_class
from . import svg as svg_mod

# kind -> (filename, title); this order is the order the UI and the tool present.
DOCS: Tuple[Tuple[str, str, str], ...] = (
    ("shopping", "bom.html", "Shopping list"),
    ("wiring", "wiring.html", "Wiring card"),
    ("poster", "poster.html", "Board poster"),
)
KINDS = tuple(k for k, _f, _t in DOCS)

_CONNECTOR_HINTS = ("header", "jst", "screw", "barrel", "usb", "terminal", "rj45",
                    "fpc", "ffc", "jack", "conn")


def filename(kind: str) -> str:
    for k, f, _t in DOCS:
        if k == kind:
            return f
    raise KeyError(kind)


def title(kind: str) -> str:
    for k, _f, t in DOCS:
        if k == kind:
            return t
    raise KeyError(kind)


def render(board: Board, kind: str) -> str:
    """Render one document by kind."""
    if kind == "shopping":
        return shopping_html(board)
    if kind == "wiring":
        return wiring_html(board)
    if kind == "poster":
        return poster_html(board)
    raise KeyError(kind)


# --------------------------------------------------------------------------- #
# shared shell
# --------------------------------------------------------------------------- #

_CSS = """
:root{
  color-scheme: dark;
  --bg:#0a0d0b; --panel:#111614; --panel2:#151b18; --line:#243029;
  --text:#e8e4d8; --dim:#9aa49d; --faint:#7f8a81; --accent:#7fc7a1;
  --power:#e0a458; --gnd:#8d978f; --signal:#7fc7a1; --warn:#d9a45f;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:radial-gradient(1200px 600px at 20% -10%,#132019 0%,var(--bg) 55%) fixed;
  color:var(--text);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:28px 32px 44px;
}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto}
header.top{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:20px}
h1{font-size:23px;line-height:1.2;margin:0 0 6px;letter-spacing:-0.01em}
.sub{color:var(--dim);font-size:13px}
.kicker{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:7px}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:14px;padding:18px 20px;box-shadow:0 1px 0 rgba(255,255,255,.03) inset}
.card + .card{margin-top:16px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse}
thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--faint);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)}
tbody td{padding:11px 10px;border-bottom:1px solid rgba(255,255,255,.045);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:rgba(127,199,161,.045)}
.qty{font-family:var(--mono);color:var(--dim);width:46px}
.val{font-weight:600}
.refs{color:var(--faint);font-family:var(--mono);font-size:11.5px;margin-top:2px}
.desc{color:var(--dim);font-size:12.5px}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid var(--line);
  font-size:11px;color:var(--dim);background:rgba(255,255,255,.02);margin:0 4px 4px 0;white-space:nowrap}
.pill:hover{color:var(--text);border-color:var(--accent);text-decoration:none}
.pill.buy{color:var(--accent);border-color:rgba(127,199,161,.35)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;vertical-align:middle}
.power{background:var(--power)} .ground{background:var(--gnd)} .signal{background:var(--signal)}
.note{color:var(--faint);font-size:12px;margin-top:14px}
.badge{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:999px;
  font-size:12px;border:1px solid rgba(127,199,161,.35);color:var(--accent);
  background:rgba(127,199,161,.08);white-space:nowrap}
.badge.bad{border-color:rgba(217,164,95,.4);color:var(--warn);background:rgba(217,164,95,.08)}
.conn-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:12px}
.conn-ref{font-size:16px;font-weight:650}
.conn-part{color:var(--faint);font-size:12px;font-family:var(--mono)}
.pin{font-family:var(--mono);color:var(--dim);width:52px}
.net{font-family:var(--mono)}
.dest{color:var(--dim);font-family:var(--mono);font-size:12.5px}
.muted{color:var(--faint)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px}
.stat{background:rgba(255,255,255,.02);border:1px solid var(--line);border-radius:11px;padding:12px 14px}
.stat .k{color:var(--faint);font-size:10.5px;text-transform:uppercase;letter-spacing:.1em}
.stat .v{font-size:20px;font-weight:600;margin-top:3px;font-variant-numeric:tabular-nums}
.hero{display:flex;justify-content:center;padding:8px 0 4px}
.hero svg{width:100%;height:auto;max-height:620px;filter:drop-shadow(0 18px 30px rgba(0,0,0,.45))}
/* The Docs tab in the desktop app is about 700 px wide, and the preview pane can
   be narrower still. Drop the least critical columns rather than let the table
   squeeze into four lines per row. */
@media (max-width: 860px){
  .desc{display:none}
  .pill.buy{font-size:10.5px;padding:2px 7px}
  body{padding:20px 20px 32px}
}
@media (max-width: 620px){
  .footprint{display:none}
  .pill.buy{display:block;margin:0 0 4px}
  .stats{grid-template-columns:repeat(2,1fr)}
}
@media print{
  :root{color-scheme:light}
  body{background:#fff;color:#111;padding:0}
  .card{background:#fff;border-color:#ddd;box-shadow:none}
  thead th{color:#666} .desc,.sub,.refs,.note,.dest{color:#555}
  a{color:#0b6b46} .pill{border-color:#ddd;color:#333}
  .stat{background:#fafafa}
  /* On paper the render lands at roughly the board's real size (88 mm board ->
     250 px at 96 dpi ~ 66 mm tall), which keeps the poster on one page and makes
     the printout a usable reference. */
  .hero svg{max-height:250px}
  .card{break-inside:avoid;padding:12px 14px}
  .card + .card{margin-top:10px}
  tbody td{padding:7px 10px}
  .stats{gap:8px;grid-template-columns:repeat(3,1fr)}
  .stat{padding:6px 9px}
  .stat .v{font-size:17px}
}
"""


def _shell(title_text: str, kicker: str, subtitle: str, right: str, body: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title_text)} — Circuit</title>"
        f"<style>{_CSS}</style></head><body><div class=\"wrap\">"
        "<header class=\"top\"><div>"
        f"<div class=\"kicker\">{html.escape(kicker)}</div>"
        f"<h1>{html.escape(title_text)}</h1>"
        f"<div class=\"sub\">{html.escape(subtitle)}</div></div>"
        f"<div>{right}</div></header>{body}</div></body></html>"
    )


def _size_line(board: Board) -> str:
    b = board.board
    return (f'{b["width"]:.1f} × {b["height"]:.1f} mm · {b.get("layers", 2)} layers · '
            f'{b.get("thickness", 1.6):.2f} mm · {b.get("finish", "HASL")}')


def _drc_badge(board: Board) -> str:
    drc = board.data.get("drc") or {}
    errors = len(drc.get("errors") or [])
    if drc.get("ok"):
        return '<span class="badge">DRC clean</span>'
    return f'<span class="badge bad">{errors} DRC issue(s)</span>'


# --------------------------------------------------------------------------- #
# shopping list
# --------------------------------------------------------------------------- #

_DISTRIBUTORS: Sequence[Tuple[str, str]] = (
    ("Digi-Key", "https://www.digikey.com/en/products/result?keywords={q}"),
    ("Mouser", "https://www.mouser.com/c/?q={q}"),
    ("LCSC", "https://www.lcsc.com/search?q={q}"),
    ("Octopart", "https://octopart.com/search?q={q}"),
)


def search_links(mpn: str, value: str, footprint: str) -> List[Tuple[str, str]]:
    """Distributor search URLs for one BOM line.

    Built locally from the part number: no network call, no API key, no scrape.
    Without an MPN the search falls back to value + footprint, which usually still
    lands on the right family.
    """
    query = (mpn or f"{value} {footprint}").strip()
    q = quote_plus(query)
    return [(name, pattern.format(q=q)) for name, pattern in _DISTRIBUTORS]


def _bom_row(row: dict) -> str:
    refs = " ".join(row.get("refs") or [])
    mpn = (row.get("mpn") or "").strip()
    mfr = (row.get("mfr") or "").strip()
    links = "".join(
        f'<a class="pill buy" href="{html.escape(url)}" target="_blank" rel="noopener">'
        f'{html.escape(name)}</a>'
        for name, url in search_links(mpn, str(row.get("value") or ""),
                                      str(row.get("footprint") or ""))
    )
    if mpn:
        mpn_cell = f'<span class="mono">{html.escape(mpn)}</span>'
        if mfr:
            mpn_cell += f'<div class="refs">{html.escape(mfr)}</div>'
    else:
        mpn_cell = '<span class="muted">—</span>'
    return (
        f'<tr><td class="qty">{int(row.get("qty") or 1)}</td>'
        f'<td><div class="val">{html.escape(str(row.get("value") or ""))}</div>'
        f'<div class="refs">{html.escape(refs)}</div></td>'
        f'<td class="mono footprint">{html.escape(str(row.get("footprint") or ""))}</td>'
        f'<td class="desc">{html.escape(str(row.get("description") or ""))}</td>'
        f'<td>{mpn_cell}</td>'
        f'<td>{links}</td></tr>'
    )


def shopping_html(board: Board) -> str:
    rows = layers.bom(board)
    total = sum(int(r.get("qty") or 1) for r in rows)
    with_mpn = sum(1 for r in rows if (r.get("mpn") or "").strip())
    body = (
        '<div class="card"><table><thead><tr>'
        '<th class="qty">Qty</th><th>Value</th><th class="footprint">Footprint</th>'
        '<th class="desc">Description</th><th>MPN</th><th>Buy</th></tr></thead><tbody>'
        + "".join(_bom_row(r) for r in rows)
        + '</tbody></table></div>'
        f'<div class="note">{len(rows)} line(s) · {total} part(s) · {with_mpn} with a '
        'manufacturer part number. Buy links open a distributor search for the MPN, '
        'or for the value and footprint when the MPN is not known yet.</div>'
    )
    subtitle = f'{len(rows)} lines · {total} parts · {_size_line(board)}'
    return _shell(board.data.get("title") or "Board", "Bill of materials",
                  subtitle, _drc_badge(board), body)


# --------------------------------------------------------------------------- #
# wiring card
# --------------------------------------------------------------------------- #

def _is_connector(comp: dict) -> bool:
    try:
        part = parts.get(comp["part"])
    except KeyError:
        return False
    if part.get("category") == "connector":
        return True
    blob = f"{comp['part']} {part.get('footprint', '')}".lower()
    return any(h in blob for h in _CONNECTOR_HINTS)


def _pin_sort_key(num: str):
    text = str(num)
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def _pin_data(board: Board, ref: str, by_net: Dict[str, List[dict]],
              part_pins: Dict[str, str]) -> List[dict]:
    """One row per pad: number, semantic name, net, and what else is on that net."""
    rows = []
    pads = sorted(board.world_pads(ref=ref), key=lambda p: _pin_sort_key(p["num"]))
    for pad in pads:
        if pad.get("kind") == "npth":
            continue
        net = pad.get("net") or ""
        name = str(part_pins.get(pad["num"], "") or "").strip()
        if name == str(pad["num"]):
            name = ""
        dest = ""
        if net:
            others = [p for p in by_net.get(net, [])
                      if not (p["ref"] == ref and p["num"] == pad["num"])]
            dest = ", ".join(f'{p["ref"]}.{p["num"]}' for p in others[:4])
            if len(others) > 4:
                dest += f' +{len(others) - 4}'
        rows.append({"num": str(pad["num"]), "name": name, "net": net,
                     "cls": net_class(net) if net else "", "dest": dest})
    return rows


def wiring_html(board: Board) -> str:
    by_net = board.net_pins()
    connectors = [c for c in board.data["components"] if _is_connector(c)]
    connectors.sort(key=lambda c: c["ref"])

    cards: List[dict] = []
    for comp in connectors:
        ref = comp["ref"]
        value = (comp.get("value") or "").strip()
        fp = ""
        part_pins: Dict[str, str] = {}
        try:
            part = parts.get(comp["part"])
            fp = part.get("footprint", "")
            part_pins = part.get("pins") or {}
            if not value:
                value = part.get("name", "")
        except KeyError:
            pass
        rows = _pin_data(board, ref, by_net, part_pins)
        if rows:
            cards.append({"ref": ref, "value": value, "footprint": fp, "rows": rows})

    # Only show the Name column when the part actually has semantic pin names:
    # a generic header's names are its numbers, and an empty column reads as a bug.
    show_names = any(row["name"] for card in cards for row in card["rows"])

    blocks: List[str] = []
    for card in cards:
        body_rows = []
        for row in card["rows"]:
            dot = (f'<span class="dot {row["cls"]}"></span>' if row["net"]
                   else '<span class="dot" style="background:#2a352f"></span>')
            net_cell = (f'<span class="net">{dot}{html.escape(row["net"])}</span>'
                        if row["net"] else '<span class="muted">unconnected</span>')
            dest_cell = (f'<span class="dest">{html.escape(row["dest"])}</span>'
                         if row["dest"] else '<span class="muted">—</span>')
            name_cell = (f'<td><span class="muted">{html.escape(row["name"])}</span></td>'
                         if show_names else "")
            body_rows.append(
                f'<tr><td class="pin">{html.escape(row["num"])}</td>'
                f'{name_cell}<td>{net_cell}</td><td>{dest_cell}</td></tr>'
            )
        head = ('<th class="pin">Pin</th>'
                + ('<th>Name</th>' if show_names else "")
                + '<th>Net</th><th>Also on this net</th>')
        blocks.append(
            '<div class="card"><div class="conn-head">'
            f'<div class="conn-ref">{html.escape(card["ref"])}'
            f'<span class="conn-part" style="margin-left:10px">'
            f'{html.escape(card["footprint"])}</span></div>'
            f'<div class="sub">{html.escape(card["value"])}</div></div>'
            f'<table><thead><tr>{head}</tr></thead><tbody>'
            + "".join(body_rows) + '</tbody></table></div>'
        )

    if not blocks:
        body = ('<div class="card"><div class="sub">This board has no connectors, so '
                'there is nothing to wire up — every net is internal to the '
                'components on the board.</div></div>')
    else:
        body = "".join(blocks)
    body += ('<div class="note">Pins are listed in numeric order. The colour dot is the '
             'net class: <span class="dot power"></span>power, '
             '<span class="dot ground"></span>ground, '
             '<span class="dot signal"></span>signal.</div>')
    subtitle = f'{len(cards)} connector(s) · {_size_line(board)}'
    return _shell(board.data.get("title") or "Board", "Wiring card",
                  subtitle, _drc_badge(board), body)


# --------------------------------------------------------------------------- #
# board poster
# --------------------------------------------------------------------------- #

def poster_html(board: Board) -> str:
    stats = board.stats()
    b = board.board
    svg = svg_mod.render_svg(board)
    # Strip the XML prolog if present; keep one inline <svg> for the hero.
    if svg.lstrip().startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()

    rows = layers.bom(board)
    rows.sort(key=lambda r: (-int(r.get("qty") or 1), str(r.get("value") or "")))
    top = rows[:6]
    bom_rows = "".join(
        f'<tr><td class="qty">{int(r.get("qty") or 1)}</td>'
        f'<td><div class="val">{html.escape(str(r.get("value") or ""))}</div>'
        f'<div class="refs">{html.escape(" ".join(r.get("refs") or []))}</div></td>'
        f'<td class="mono">{html.escape(str(r.get("footprint") or ""))}</td></tr>'
        for r in top
    )

    stats_grid = "".join(
        f'<div class="stat"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(str(v))}</div></div>'
        for k, v in (
            ("Parts", stats["components"]),
            ("Nets", stats["nets"]),
            ("Pads", stats["pads"]),
            ("Vias", stats["vias"]),
            ("Area", f'{stats["area_mm2"]:.0f} mm²'),
            ("Layers", b.get("layers", 2)),
        )
    )

    body = (
        f'<div class="card"><div class="hero">{svg}</div></div>'
        f'<div class="card"><div class="stats">{stats_grid}</div></div>'
        '<div class="card"><table><thead><tr><th class="qty">Qty</th><th>Value</th>'
        f'<th>Footprint</th></tr></thead><tbody>{bom_rows}</tbody></table>'
        f'<div class="note">Top {len(top)} of {len(rows)} BOM line(s).</div></div>'
        '<div class="note" style="text-align:center;margin-top:22px">'
        'Designed with Circuit · Hermes Agent</div>'
    )
    right = _drc_badge(board)
    return _shell(board.data.get("title") or "Board", "Board poster",
                  _size_line(board), right, body)
