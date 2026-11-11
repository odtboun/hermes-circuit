"""Generated documents: shopping list, wiring card, board poster.

Each is a standalone HTML page rendered from the same netlist as the Gerbers, so
these tests check both the facts on the page and that the page needs nothing from
the outside world to display.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from circuit_core import drc, layers, placement, router, templates
from circuit_core.fab import docs


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    import os

    os.environ.setdefault("CIRCUIT_DATA_DIR", str(tmp_path_factory.mktemp("docs-data")))
    b = templates.instantiate("pico-sensor-hub")
    placement.auto_place(b)
    router.route_board(b)
    b.data["drc"] = drc.check(b)
    return b


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def test_tables_cannot_widen_the_page(board):
    """Fixed layout plus per-column widths. An imported board carries footprints like
    `kit-dev-coldfire:DSUB-9_Female_Horizontal_P2.77x2.84mm_EdgePinOffset9.40mm`, and
    with auto layout one such cell pushed the table 600 px past the viewport."""
    for kind in docs.KINDS:
        html = docs.render(board, kind)
        if "<table" not in html:
            continue
        assert "table-layout:fixed" in html, kind
        assert html.count("<colgroup>") == html.count("<table"), kind
        assert "overflow-wrap:anywhere" in html, kind


def test_a_long_reference_list_is_counted_not_printed():
    """A 40-capacitor line lists 100-odd references, which wraps into a 400 px row at
    the width of the Docs tab. The cell shows the first few and counts the rest, and
    keeps the whole list in the tooltip."""
    cell = docs._refs_cell({"refs": [f"C{i}" for i in range(1, 41)]})
    shown = re.search(r'>([^<]*)</div>', cell).group(1)
    assert shown.startswith("C1 C2 C3 C4 C5 C6 C7 C8 ")
    assert shown.endswith(" +32")
    assert "C9 " not in shown
    assert 'title="C1 C2' in cell and "C40" in cell

    short = docs._refs_cell({"refs": ["R1", "R2"]})
    assert "+" not in re.search(r'>([^<]*)</div>', short).group(1)
    assert docs._refs_cell({"refs": []}) == ""


def test_shopping_list_has_a_row_per_bom_line(board):
    html = docs.shopping_html(board)
    rows = layers.bom(board)
    assert html.count("<tr>") == len(rows) + 1          # + the header row
    for row in rows:
        assert str(row.get("value") or "") in html
        assert " ".join(row["refs"]) in html


def test_every_row_links_to_four_distributors(board):
    html = docs.shopping_html(board)
    rows = layers.bom(board)
    assert html.count('class="pill buy"') == len(rows) * 4
    for name in ("Digi-Key", "Mouser", "LCSC", "Octopart"):
        assert f">{name}</a>" in html


def test_search_links_use_the_mpn_and_fall_back_to_value_and_footprint():
    with_mpn = docs.search_links("BME280", "BME280", "header-1x4")
    assert "keywords=BME280" in with_mpn[0][1]
    assert quote_plus("BME280") in with_mpn[0][1]

    without = docs.search_links("", "10k", "0805")
    q = quote_plus("10k 0805")
    for _name, url in without:
        assert q in url


def test_shopping_list_counts_mpn_coverage(board):
    html = docs.shopping_html(board)
    known = sum(1 for r in layers.bom(board) if (r.get("mpn") or "").strip())
    assert f"{known} with a manufacturer part number" in _strip_tags(html)


def test_shopping_list_shows_an_mpn_when_the_component_has_one(board):
    board.data["components"][0]["mpn"] = "TEST-MPN-123"
    try:
        html = docs.shopping_html(board)
        assert "TEST-MPN-123" in html
        assert "keywords=TEST-MPN-123" in html
    finally:
        board.data["components"][0].pop("mpn", None)


# --------------------------------------------------------------------------- #
# wiring card
# --------------------------------------------------------------------------- #

def test_wiring_card_lists_every_connector_pin(board):
    html = docs.wiring_html(board)
    connectors = [c for c in board.data["components"] if docs._is_connector(c)]
    assert connectors, "the fixture board should have connectors"
    for comp in connectors:
        assert f'class="conn-ref">{comp["ref"]}<' in html
        for pad in board.world_pads(ref=comp["ref"]):
            if pad.get("kind") == "npth":
                continue
            assert f'class="pin">{pad["num"]}</td>' in html


def test_wiring_card_says_where_each_net_goes(board):
    html = docs.wiring_html(board)
    by_net = board.net_pins()
    for comp in board.data["components"]:
        if not docs._is_connector(comp):
            continue
        for pad in board.world_pads(ref=comp["ref"]):
            net = pad.get("net")
            if not net:
                continue
            others = [p for p in by_net[net]
                      if not (p["ref"] == comp["ref"] and p["num"] == pad["num"])]
            if others:
                assert f'{others[0]["ref"]}.{others[0]["num"]}' in html


def test_wiring_card_hides_an_empty_name_column(board):
    """A generic header's pin names are its numbers — a blank column looks broken."""
    html = docs.wiring_html(board)
    assert "<th>Name</th>" not in html


def test_wiring_card_shows_names_when_the_part_has_them(tmp_path):
    """A breakout with semantic pins (VIN/GND/SCL/SDA) gets the Name column."""
    b = templates.instantiate("pico-blinky")
    b.add_component("bme280-brk", nets={"1": "+3V3", "2": "GND"})
    placement.auto_place(b)
    html = docs.wiring_html(b)
    assert "<th>Name</th>" in html
    assert "VIN" in html and "SDA" in html


def test_wiring_card_handles_a_board_with_no_connectors():
    b = templates.instantiate("power-5v")
    html = docs.wiring_html(b)
    assert "no connectors" in html or 'class="conn-ref"' in html


# --------------------------------------------------------------------------- #
# poster
# --------------------------------------------------------------------------- #

def test_poster_carries_the_board_render_and_the_numbers(board):
    html = docs.poster_html(board)
    stats = board.stats()
    assert "<svg" in html and "</svg>" in html
    assert str(stats["components"]) in html
    assert str(stats["nets"]) in html
    assert f'{board.board["width"]:.1f} × {board.board["height"]:.1f} mm' in html
    assert "Board poster" in html


def test_poster_shows_the_drc_verdict(board):
    ok_html = docs.poster_html(board)
    assert "DRC clean" in ok_html

    board.data["drc"] = {"ok": False, "errors": ["x", "y"], "warnings": []}
    try:
        bad_html = docs.poster_html(board)
        assert "2 DRC issue(s)" in bad_html
    finally:
        board.data["drc"] = drc.check(board)


# --------------------------------------------------------------------------- #
# all three
# --------------------------------------------------------------------------- #

def test_documents_are_self_contained(board):
    """No scripts, no external assets — they must render offline and in a sandbox."""
    distributors = ("digikey", "mouser", "lcsc", "octopart")
    for kind in docs.KINDS:
        html = docs.render(board, kind)
        assert html.startswith("<!doctype html>")
        assert "<style>" in html
        # nothing that loads: no <link>, no @import, no src= — and the one script
        # is the buy-link forwarder, which needs no network and no DOM access
        assert html.count("<script") == 1, "only the link forwarder"
        assert "circuit-doc-open" in html
        assert "<link" not in html.lower()
        assert "@import" not in html
        assert 'src="' not in html
        # the only URLs allowed are the distributor searches and the SVG namespace
        body = html.replace("http://www.w3.org/2000/svg", "")
        for url in re.findall(r'https?://[^"\s]+', body):
            assert any(d in url for d in distributors), f"{kind}: unexpected URL {url}"


def test_document_metadata_is_complete():
    assert docs.KINDS == ("shopping", "wiring", "poster")
    for kind in docs.KINDS:
        assert docs.filename(kind).endswith(".html")
        assert docs.title(kind)
    with pytest.raises(KeyError):
        docs.render(None, "nope")


def test_old_view_documents_gain_the_docs_list(tmp_path, monkeypatch):
    """Boards exported before the documents existed must not need a rebuild."""
    import json

    from circuit_core import store

    monkeypatch.setenv("CIRCUIT_DATA_DIR", str(tmp_path / "data"))
    board = templates.instantiate("pico-blinky")
    slug = store.save(board)
    doc = store.load_view(slug)
    doc.pop("docs", None)                      # pretend it predates the feature
    (store.project_dir(slug) / "view.json").write_text(json.dumps(doc))

    back = store.load_view(slug)
    assert [d["kind"] for d in back["docs"]] == ["shopping", "wiring", "poster"]

    # an imported board gets them too: its documents are built from the stored
    # view document rather than the part library
    doc["imported"] = True
    doc.pop("docs", None)
    (store.project_dir(slug) / "view.json").write_text(json.dumps(doc))
    assert [d["kind"] for d in store.load_view(slug)["docs"]] == ["shopping", "wiring", "poster"]


def test_documents_carry_a_print_layout(board):
    """These are meant to be printed: light colours, no card split across pages."""
    for kind in docs.KINDS:
        html = docs.render(board, kind)
        assert "@media print" in html
        assert "color-scheme:light" in html
        assert "break-inside:avoid" in html


def test_the_poster_hero_is_the_finished_board_not_a_layer_diagram(board):
    """The poster is the artefact people look at: green mask, gold pads, white silk."""
    from circuit_core.fab import svg as svg_mod

    layer = svg_mod.render_svg(board)
    product = svg_mod.render_svg(board, style="product")
    # the design view draws each copper side in its own colour
    assert svg_mod.PALETTE["F.Cu"] in layer and svg_mod.PALETTE["B.Cu"] in layer
    # the product view does not: both sides sit under the same green mask
    assert svg_mod.PALETTE["F.Cu"] not in product
    assert svg_mod.PALETTE["B.Cu"] not in product
    assert svg_mod.PRODUCT_PALETTE["pad"] in product
    assert svg_mod.PRODUCT_PALETTE["board"] in product
    # and the poster uses it
    assert svg_mod.PRODUCT_PALETTE["pad"] in docs.poster_html(board)
    assert svg_mod.PALETTE["F.Cu"] not in docs.poster_html(board)


# --------------------------------------------------------------------------- #
# imported boards
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def imported_doc(tmp_path_factory):
    """An imported board's stored view document — no part library involved."""
    import os

    from circuit_core import import_kicad

    os.environ.setdefault("CIRCUIT_DATA_DIR", str(tmp_path_factory.mktemp("imp-data")))
    fixture = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"
    _board, doc, _warnings = import_kicad.parse_board(fixture)
    return doc


def test_imported_board_gets_all_three_documents(imported_doc):
    for kind in docs.KINDS:
        html = docs.render_view(imported_doc, kind)
        assert html.startswith("<!doctype html>")
        assert html.count("<script") == 1        # the buy-link forwarder only
        assert "imported KiCad design" in html


def test_imported_shopping_list_is_built_from_the_stored_bom(imported_doc):
    html = docs.render_view(imported_doc, "shopping")
    rows = imported_doc["bom"]
    assert html.count("<tr>") == len(rows) + 1
    for row in rows[:5]:
        assert " ".join(row["refs"]) in html


def test_imported_wiring_card_uses_the_stored_pins(imported_doc):
    html = docs.render_view(imported_doc, "wiring")
    connectors = [c for c in imported_doc["components"]
                  if docs._is_connector({"footprint": c["footprint"],
                                         "part_name": c["footprint"]})]
    if not connectors:
        assert "no connectors" in html
        return
    ref = connectors[0]["ref"]
    assert f'class="conn-ref">{ref}<' in html
    for pin in connectors[0]["pins"]:
        assert f'class="pin">{pin["num"]}</td>' in html


def test_imported_poster_renders_the_stored_copper(imported_doc):
    html = docs.render_view(imported_doc, "poster")
    assert "<svg" in html and "</svg>" in html
    assert "<path" in html            # traces, grouped by width
    assert "<circle" in html          # drills and round pads
    assert "not DRC-checked" in html  # an import never ran DRC


def test_a_board_without_drc_does_not_claim_it_is_clean():
    b = templates.instantiate("pico-blinky")
    b.data.pop("drc", None)
    html = docs.shopping_html(b)
    assert "not DRC-checked" in html
    assert "DRC clean" not in html
