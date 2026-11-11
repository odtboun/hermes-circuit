"""SVG / standalone-HTML rendering.

A dependency-free 2D render used for ``preview.svg``, the offline
``preview.html`` (layer toggles, pan/zoom) and OpenGraph-style snapshots. The
desktop viewer does its own canvas drawing, but both read the same geometry.
"""

from __future__ import annotations

import html
from typing import Dict, List, Tuple

from .. import geom, layers
from ..project import Board

# Layer view: every copper side in its own colour, the way an EDA tool draws it.
PALETTE = {
    "board": "#0b2b1e",
    "board_edge": "#d9b26a",
    "F.Cu": "#c96a3a",
    "B.Cu": "#3f6f9e",
    "F.SilkS": "#e8e4d8",
    "B.SilkS": "#9aa39c",
    "drill": "#06120c",
    "pad": "#d8b25c",
}

# Product view: what the board looks like finished — green mask over the copper,
# gold pads, white silk. Used for the poster, where the render is the hero.
PRODUCT_PALETTE = {
    "board": "#14663a",
    "board_edge": "#e0be6a",
    "F.Cu": "#4a9e70",
    "B.Cu": "#2b6b4a",
    "F.SilkS": "#f6f2e6",
    "B.SilkS": "#2b6b4a",
    "drill": "#08110d",
    "pad": "#f0d24a",
    "pad_bottom": "#b8983c",
}


def _pt(p) -> str:
    return f"{round(float(p[0]), 3)},{round(float(p[1]), 3)}"


def _strokes(items: List[dict]) -> List[Tuple[float, str]]:
    """Group polylines into (stroke width, SVG path data) pairs.

    One <path> per width instead of one <polyline> per segment: same geometry,
    a fraction of the bytes, and the browser draws it in one pass.
    """
    groups: Dict[float, List[str]] = {}
    for item in items:
        points = item.get("points") or []
        if len(points) < 2:
            continue
        d = "M" + "L".join(f"{float(p[0]):.2f} {float(p[1]):.2f}" for p in points)
        groups.setdefault(round(float(item.get("width") or 0.15), 3), []).append(d)
    return [(width, "".join(segs)) for width, segs in sorted(groups.items())]


def _pad_svg(f: dict, color: str) -> str:
    x, y, w, h = f["x"], f["y"], f["w"], f["h"]
    rot = f.get("rot", 0.0) % 360.0
    tf = f' transform="rotate({-rot:.2f} {x:.3f} {y:.3f})"' if rot else ""
    shape = f["shape"]
    if shape == "round":
        return f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{w / 2:.3f}" fill="{color}"/>'
    if shape == "oval":
        return (f'<ellipse cx="{x:.3f}" cy="{y:.3f}" rx="{w / 2:.3f}" ry="{h / 2:.3f}"'
                f' fill="{color}"{tf}/>')
    return (f'<rect x="{x - w / 2:.3f}" y="{y - h / 2:.3f}" width="{w:.3f}" height="{h:.3f}"'
            f' rx="{min(w, h) * 0.12:.3f}" fill="{color}"{tf}/>')


def render_svg(board: Board, standalone: bool = True, background: bool = True,
               style: str = "layer") -> str:
    """Render the board as SVG.

    ``style="layer"`` draws each copper side in its own colour — the design view,
    good for reviewing what is on which layer. ``style="product"`` draws the
    finished board: mask green over the copper, gold pads, white silk.
    """
    return render_pieces(
        width=board.board["width"], height=board.board["height"],
        copper=layers.copper(board), silk=layers.silk(board),
        drills=layers.drills(board), outline=board.outline(10),
        title=board.data.get("title", "Board"), background=background, style=style,
    )


def render_svg_view(view: dict, background: bool = True, style: str = "layer") -> str:
    """Render an imported board from its stored view document.

    An imported KiCad board has no library parts, so nothing that walks the part
    catalog works on it — but the view document already carries the copper, silk,
    drills and outline, which is everything the renderer needs.
    """
    return render_pieces(
        width=view["board"]["width"], height=view["board"]["height"],
        copper=view["copper"], silk=view["silk"], drills=view.get("drills") or [],
        outline=[tuple(p) for p in view["outline"]],
        title=view.get("title") or "Board", background=background, style=style,
    )


def render_pieces(width: float, height: float, copper: dict, silk: dict, drills: list,
                  outline: list, title: str, background: bool = True,
                  style: str = "layer") -> str:
    """The renderer itself: geometry in, SVG out, no board model involved."""
    w, h = width, height
    margin = 2.0
    pal = PRODUCT_PALETTE if style == "product" else PALETTE
    product = style == "product"
    trace = {"B.Cu": pal["B.Cu"], "F.Cu": pal["F.Cu"]}
    if product:
        flash = {"B.Cu": pal["pad_bottom"], "F.Cu": pal["pad"]}
    else:
        flash = {"B.Cu": pal["B.Cu"], "F.Cu": pal["F.Cu"]}
    silk_opacity = 1 if product else 0.9

    parts: List[str] = []
    if background:
        parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="{pal["board"]}"/>')
    # bottom copper first, then top. Traces are grouped into one path per stroke
    # width: a board like `video` has 8k segments, and 8k <polyline> wrappers cost
    # about a megabyte of HTML for the same picture.
    for layer_id in ("B.Cu", "F.Cu"):
        g: List[str] = []
        for width, d in _strokes((copper.get(layer_id) or {}).get("draws") or []):
            g.append(f'<path d="{d}" fill="none" stroke="{trace[layer_id]}"'
                     f' stroke-width="{width:.3f}" stroke-linecap="round"'
                     f' stroke-linejoin="round"/>')
        for f in (copper.get(layer_id) or {}).get("flashes") or []:
            g.append(_pad_svg(f, flash[layer_id]))
        parts.append(f'<g id="layer-{layer_id}" data-layer="{layer_id}">' + "".join(g) + "</g>")
    # silk
    front = (silk or {}).get("F.SilkS") or {}
    g = []
    for width, d in _strokes((front.get("lines") or []) + (front.get("text") or [])):
        g.append(f'<path d="{d}" fill="none" stroke="{pal["F.SilkS"]}"'
                 f' stroke-width="{width:.3f}" opacity="{silk_opacity}"/>')
    parts.append('<g id="layer-F.SilkS" data-layer="F.SilkS">' + "".join(g) + "</g>")
    # drills
    # the engine calls it "diameter", a stored view document calls it "d"
    g = [f'<circle cx="{d["x"]:.3f}" cy="{d["y"]:.3f}"'
         f' r="{(d.get("diameter") or d.get("d") or 0.0) / 2:.3f}"'
         f' fill="{pal["drill"]}"/>' for d in drills or []]
    parts.append('<g id="layer-drill" data-layer="drill">' + "".join(g) + "</g>")
    # outline
    if outline:
        parts.append(f'<polyline points="{" ".join(_pt(p) for p in outline + [outline[0]])}"'
                     f' fill="none" stroke="{pal["board_edge"]}" stroke-width="0.15"/>')

    body = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-margin} {-margin} '
        f'{w + 2 * margin} {h + 2 * margin}" width="{w + 2 * margin}mm" '
        f'height="{h + 2 * margin}mm" role="img" aria-label="{html.escape(title)}">'
        f'<g transform="translate(0 {h}) scale(1 -1)">{body}</g></svg>'
    )


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Circuit</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0a0d0b; color:#e8e4d8;
         font:13px/1.45 ui-sans-serif,system-ui,-apple-system,sans-serif; min-height:100vh; }}
  header {{ display:flex; gap:14px; align-items:baseline; padding:16px 20px 10px; flex-wrap:wrap; }}
  h1 {{ font-size:15px; margin:0; font-weight:600; letter-spacing:-0.01em; }}
  .meta {{ color:#8c9a90; font-size:12px; }}
  .chips {{ display:flex; gap:6px; flex-wrap:wrap; padding:0 20px 12px; }}
  button {{ background:#141a16; border:1px solid #26302a; color:#cfd8d2; border-radius:99px;
            padding:4px 10px; font:inherit; font-size:12px; cursor:pointer; }}
  button[aria-pressed="true"] {{ background:#1d2a22; border-color:#3d5746; color:#eaf5ee; }}
  button .sw {{ display:inline-block; width:7px; height:7px; border-radius:2px; margin-right:6px; }}
  #stage {{ position:relative; margin:0 20px 20px; border:1px solid #1e2621; border-radius:12px;
            overflow:hidden; background:radial-gradient(120% 120% at 50% 0%,#0f1712 0%,#080b09 70%); }}
  #stage svg {{ display:block; width:100%; height:min(76vh,860px); cursor:grab; }}
  #stage svg:active {{ cursor:grabbing; }}
  .hint {{ position:absolute; right:10px; bottom:8px; color:#5e6b63; font-size:11px; }}
  .stats {{ display:flex; gap:18px; padding:0 20px 16px; color:#8c9a90; flex-wrap:wrap; }}
  .stats b {{ color:#e8e4d8; font-weight:600; }}
</style></head>
<body>
<header><h1>{title}</h1><span class="meta">{w} × {h} mm · {layers}-layer · {components} parts · {nets} nets</span></header>
<div class="chips" id="chips"></div>
<div id="stage">{svg}<div class="hint">drag to pan · scroll to zoom</div></div>
<div class="stats"><span><b>{routed}</b> nets routed</span><span><b>{vias}</b> vias</span>
<span><b>{drc}</b> DRC problems</span><span>{finish}</span></div>
<script>
(function () {{
  var stage = document.getElementById('stage'), svg = stage.querySelector('svg');
  var view = {{ x: 0, y: 0, k: 1 }};
  function apply() {{
    var box = svg.viewBox.baseVal;
    svg.setAttribute('viewBox', [box.x, box.y, box.width, box.height].join(' ') );
    svg.style.transform = 'translate(' + view.x + 'px,' + view.y + 'px) scale(' + view.k + ')';
  }}
  var drag = null;
  svg.addEventListener('pointerdown', function (e) {{
    drag = {{ x: e.clientX - view.x, y: e.clientY - view.y }}; svg.setPointerCapture(e.pointerId);
  }});
  svg.addEventListener('pointermove', function (e) {{
    if (!drag) return; view.x = e.clientX - drag.x; view.y = e.clientY - drag.y; apply();
  }});
  svg.addEventListener('pointerup', function () {{ drag = null; }});
  svg.addEventListener('wheel', function (e) {{
    e.preventDefault(); var k = Math.exp(-e.deltaY * 0.0015);
    view.k = Math.min(12, Math.max(0.4, view.k * k)); apply();
  }}, {{ passive: false }});
  var layers = [['F.Cu','Top copper','#c96a3a'],['B.Cu','Bottom copper','#3f6f9e'],
                ['F.SilkS','Silkscreen','#e8e4d8'],['drill','Drills','#0a0d0b']];
  var chips = document.getElementById('chips');
  layers.forEach(function (l) {{
    var b = document.createElement('button');
    b.type = 'button'; b.setAttribute('aria-pressed', 'true');
    b.innerHTML = '<span class="sw" style="background:' + l[2] + '"></span>' + l[1];
    b.onclick = function () {{
      var g = svg.querySelector('[data-layer="' + l[0] + '"]');
      var on = b.getAttribute('aria-pressed') !== 'true';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (g) g.style.display = on ? '' : 'none';
    }};
    chips.appendChild(b);
  }});
}})();
</script>
</body></html>
"""


def render_html(board: Board) -> str:
    svg = render_svg(board)
    stats = board.stats()
    drc_errors = len((board.data.get("drc") or {}).get("errors", []))
    return _HTML.format(
        title=html.escape(board.data["title"]),
        w=board.board["width"], h=board.board["height"],
        layers=board.board["layers"], components=stats["components"], nets=stats["nets"],
        routed=stats["routed_nets"], vias=stats["vias"], drc=drc_errors,
        finish=html.escape(board.board.get("finish", "HASL")),
        svg=svg,
    )
