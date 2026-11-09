"""Fabrication outputs: Gerber, Excellon, KiCad, STEP, SVG — checked by parsers."""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from circuit_core import compile as builder
from circuit_core import layers, store, templates
from circuit_core.fab import gerber, kicad, step, svg


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import os

    data = tmp_path_factory.mktemp("fab-data")
    os.environ["CIRCUIT_DATA_DIR"] = str(data)
    board = templates.instantiate("pico-sensor-hub")
    summary = builder.build(board, effort="normal")
    return board, summary


def test_export_wrote_the_expected_files(built):
    _board, summary = built
    names = set(summary["files"])
    for required in (
        "gerbers/pico-sensor-hub-F_Cu.gbr",
        "gerbers/pico-sensor-hub-B_Cu.gbr",
        "gerbers/pico-sensor-hub-F_Mask.gbr",
        "gerbers/pico-sensor-hub-B_Mask.gbr",
        "gerbers/pico-sensor-hub-F_Silkscreen.gbr",
        "gerbers/pico-sensor-hub-Edge_Cuts.gbr",
        "gerbers/pico-sensor-hub-PTH.drl",
        "gerbers/pico-sensor-hub-NPTH.drl",
        "kicad/pico-sensor-hub.kicad_pcb",
        "kicad/pico-sensor-hub.kicad_pro",
        "pico-sensor-hub.step",
        "pico-sensor-hub-gerbers.zip",
        "bom.csv",
        "pos.csv",
        "netlist.json",
        "preview.svg",
        "preview.html",
        "manifest.json",
    ):
        assert required in names, f"missing {required}"


def test_gerber_roundtrip_bounds_match_the_board(built):
    _board, summary = built
    ex = Path(summary["export_dir"])
    for name in ("F_Cu", "B_Cu", "F_Mask", "B_Mask", "F_Silkscreen"):
        text = (ex / f"gerbers/pico-sensor-hub-{name}.gbr").read_text()
        parsed = gerber.parse_gerber(text)
        assert parsed["flashes"] or parsed["draws"], name
    edge = gerber.parse_gerber((ex / "gerbers/pico-sensor-hub-Edge_Cuts.gbr").read_text())
    xs = [p[0] for d in edge["draws"] for p in d["points"]]
    ys = [p[1] for d in edge["draws"] for p in d["points"]]
    assert min(xs) == pytest.approx(0, abs=1e-6)
    assert min(ys) == pytest.approx(0, abs=1e-6)
    assert max(xs) == pytest.approx(72, abs=1e-6)
    assert max(ys) == pytest.approx(50, abs=1e-6)


def test_every_aperture_is_declared_before_use(built):
    _board, summary = built
    ex = Path(summary["export_dir"])
    for path in (ex / "gerbers").glob("*.gbr"):
        declared = set()
        used = set()
        for line in path.read_text().splitlines():
            m = re.match(r"%ADD(\d+)", line)
            if m:
                declared.add(m.group(1))
            m = re.match(r"^D(\d+)\*$", line)
            if m:
                used.add(m.group(1))
        assert used <= declared, f"{path.name}: uses undeclared apertures {used - declared}"


def test_gerber_flashes_stay_inside_the_board(built):
    board, summary = built
    ex = Path(summary["export_dir"])
    parsed = gerber.parse_gerber((ex / "gerbers/pico-sensor-hub-F_Cu.gbr").read_text())
    assert len(parsed["flashes"]) > 40
    for f in parsed["flashes"]:
        assert -1.0 <= f["x"] <= board.board["width"] + 1.0
        assert -1.0 <= f["y"] <= board.board["height"] + 1.0


def test_excellon_matches_drill_list(built):
    board, summary = built
    ex = Path(summary["export_dir"])
    text = (ex / "gerbers/pico-sensor-hub-PTH.drl").read_text()
    assert text.startswith("M48")
    assert "METRIC,TZ" in text
    assert text.rstrip().endswith("M30")
    hits = len(re.findall(r"^X-?\d+\.\d+Y-?\d+\.\d+$", text, re.M))
    plated = [d for d in layers.drills(board) if d["plated"]]
    assert hits == len(plated)
    npth = (ex / "gerbers/pico-sensor-hub-NPTH.drl").read_text()
    assert "T1C3.200" in npth


def test_kicad_project_structure(built):
    board, summary = built
    ex = Path(summary["export_dir"])
    text = (ex / "kicad/pico-sensor-hub.kicad_pcb").read_text()
    assert text.count("(") == text.count(")")
    assert f'(thickness {board.board["thickness"]})' in text
    assert text.count("(footprint ") == len(board.data["components"])
    assert text.count("(net ") >= len(board.data["nets"])
    assert "(layer \"Edge.Cuts\")" in text
    pro = json.loads((ex / "kicad/pico-sensor-hub.kicad_pro").read_text())
    assert pro["meta"]["version"] == 1


def test_step_is_structurally_valid_ap214(built):
    board, summary = built
    text = (Path(summary["export_dir"]) / "pico-sensor-hub.step").read_text()
    assert text.startswith("ISO-10303-21;")
    assert "AUTOMOTIVE_DESIGN" in text
    assert text.rstrip().endswith("END-ISO-10303-21;")
    ids = set(int(m) for m in re.findall(r"^#(\d+)=", text, re.M))
    refs = set(int(m) for m in re.findall(r"#(\d+)", text))
    assert refs - ids == set(), "dangling entity references"
    bodies = len(body_parts(board))
    assert text.count("MANIFOLD_SOLID_BREP") == bodies
    assert text.count("ADVANCED_FACE") > bodies


def body_parts(board):
    out = [1]
    for c in board.data["components"]:
        from circuit_core.lib import footprints, parts

        fp = footprints.get(parts.get(c["part"])["footprint"])
        if fp["body"]["w"] > 0 and fp["body"]["h"] > 0 and fp["body"]["z"] > 0:
            out.append(c["ref"])
    return out


def test_preview_svg_and_html_are_well_formed(built):
    _board, summary = built
    ex = Path(summary["export_dir"])
    ET.parse(ex / "preview.svg")
    html = (ex / "preview.html").read_text()
    assert "<svg" in html and "layer-F.Cu" in html
    assert html.count("<script") == 1


def test_gerber_zip_contains_every_layer(built):
    _board, summary = built
    ex = Path(summary["export_dir"])
    with zipfile.ZipFile(ex / "pico-sensor-hub-gerbers.zip") as zf:
        names = set(zf.namelist())
        assert zf.testzip() is None
    assert "pico-sensor-hub-F_Cu.gbr" in names
    assert "pico-sensor-hub-PTH.drl" in names
    assert len([n for n in names if n.endswith(".gbr")]) == 7


def test_manifest_hashes_match_the_files(built):
    _board, summary = built
    ex = Path(summary["export_dir"])
    manifest = json.loads((ex / "manifest.json").read_text())
    assert manifest["tool"]["name"] == "circuit"
    assert manifest["drc"]["ok"] is True
    import hashlib

    for entry in manifest["files"]:
        p = ex / entry["path"]
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == entry["sha256"]


def test_svg_renderer_is_standalone(built):
    board, _summary = built
    text = svg.render_svg(board)
    assert text.startswith("<svg") and text.endswith("</svg>")
    html = svg.render_html(board)
    assert board.data["title"] in html


def test_soldermask_tents_the_vias(built):
    """An opening over every via wicks solder and shorts under a stencil."""
    board, _summary = built
    copper = layers.copper(board)
    vias = [f for f in copper["F.Cu"]["flashes"] if f.get("ref") == "VIA"]
    assert vias, "the fixture board should have at least one via"
    for layer in ("F.Mask", "B.Mask"):
        refs = {f.get("ref") for f in layers.mask(board)[layer]["flashes"]}
        assert "VIA" not in refs, f"{layer} opens over a via"
    # pads are still exposed
    pads = [f for f in layers.mask(board)["F.Mask"]["flashes"] if f.get("ref") != "VIA"]
    assert pads, "the mask must still open over pads"

    # and the rule can turn tenting off for boards that want open vias
    board.rules["tent_vias"] = False
    try:
        open_refs = {f.get("ref") for f in layers.mask(board)["F.Mask"]["flashes"]}
        assert "VIA" in open_refs, "tent_vias: false must expose vias"
    finally:
        board.rules["tent_vias"] = True
