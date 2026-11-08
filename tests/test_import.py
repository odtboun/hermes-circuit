"""The KiCad importer: the fixture board, the tool, and view-model parity."""

import json
from pathlib import Path

from circuit.tools import HANDLERS
from circuit_core import import_kicad, placement, router, store, templates, view

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"


def call(name, **args):
    return json.loads(HANDLERS[name](args))


def test_parses_outline_components_pads_tracks_and_nets():
    board, doc, warnings = import_kicad.parse_board(FIXTURE)
    assert warnings == []
    assert doc["title"] == "Import fixture"
    assert doc["board"]["width"] == 40.0
    assert doc["board"]["height"] == 30.0
    assert len(doc["outline"]) == 4                       # rectangle, no duplicated corner
    assert [c["ref"] for c in doc["components"]] == ["R1", "U1"]
    assert doc["stats"]["components"] == 2
    assert doc["stats"]["pads"] == 6
    assert doc["stats"]["vias"] == 1

    f_cu, b_cu = doc["copper"]["F.Cu"], doc["copper"]["B.Cu"]
    assert len(f_cu["flashes"]) == 7                      # 2 SMD + 4 THT + 1 via
    assert len(b_cu["flashes"]) == 5                      # 4 THT + 1 via
    assert len(f_cu["draws"]) == 2
    assert len(b_cu["draws"]) == 1
    assert len(doc["drills"]) == 5

    nets = {n["name"]: n for n in doc["nets"]}
    assert set(nets) == {"GND", "+3V3", "SIG"}
    assert nets["GND"]["class"] == "ground"
    assert nets["+3V3"]["class"] == "power"
    assert nets["SIG"]["class"] == "signal"
    assert nets["SIG"]["routed"] is True and nets["GND"]["routed"] is True
    assert sorted(nets["SIG"]["pins"]) == ["R1.1", "U1.2", "U1.4"]

    assert board.data["imported"] is True
    assert board.data["meta"]["format"] == "kicad"


def test_rotated_footprint_lands_where_kicad_puts_it():
    _board, doc, _warnings = import_kicad.parse_board(FIXTURE)
    u1 = next(c for c in doc["components"] if c["ref"] == "U1")
    pin1 = next(p for p in u1["pins"] if p["num"] == "1")
    # KiCad: footprint (125 120 90), pad local (-3.81 -2.54) -> (122.46 123.81);
    # engine frame is translated to the outline and mirrored in Y.
    assert (round(pin1["x"], 2), round(pin1["y"], 2)) == (22.46, 6.19)
    assert u1["rot"] == 270.0
    r1 = next(c for c in doc["components"] if c["ref"] == "R1")
    assert round(r1["body"]["w"], 3) == 2.85


def test_import_tool_creates_and_replaces_the_project():
    out = call("circuit_import", path=str(FIXTURE))
    assert out["ok"] is True
    assert out["board"] == "simple"
    assert out["components"] == 2
    assert out["nets"] == 3
    assert out["size_mm"] == [40.0, 30.0]
    assert out["read_only"] is True

    root = store.project_dir("simple")
    assert (root / "view.json").exists()
    stored = json.loads((root / "board.json").read_text())
    assert stored["imported"] is True
    assert stored["meta"]["source"] == str(FIXTURE)

    again = call("circuit_import", path=str(FIXTURE))
    assert again["board"] == "simple"                     # same file replaces, no "-2" copy
    slugs = [b["slug"] for b in call("circuit_boards")["boards"]]
    assert slugs.count("simple") == 1


def test_imported_board_is_viewable_and_read_only():
    slug = call("circuit_import", path=str(FIXTURE))["board"]
    rendered = call("circuit_view", board=slug)
    assert rendered["ok"] is True
    assert rendered["directive"] == f'::circuit{{board="{slug}"}}'
    assert rendered["stats"]["components"] == 2
    assert rendered["stats"]["pads"] == 6

    summary = call("circuit_board", board=slug)
    assert summary["ok"] is True and summary["imported"] is True
    assert summary["component_count"] == 2

    edit = call("circuit_add_part", board=slug, part="r-0805")
    assert edit["ok"] is False and "read-only" in edit["error"]


def test_bad_paths_return_errors():
    assert call("circuit_import", path="")["ok"] is False
    missing = call("circuit_import", path=str(FIXTURE.with_name("nope.kicad_pcb")))
    assert missing["ok"] is False
    wrong = call("circuit_import", path=str(FIXTURE.with_suffix(".txt")))
    assert wrong["ok"] is False and ".kicad_pcb" in wrong["error"]


def test_arc_flattening_and_loop_chaining():
    arc = import_kicad.arc_points((0.0, 0.0), (5.0, 5.0), (10.0, 0.0))
    assert len(arc) > 10                                   # flattened, not a chord
    assert arc[0] == (0.0, 0.0) and arc[-1] == (10.0, 0.0)
    assert max(p[1] for p in arc) > 4.9                    # passes through the mid point

    loop = import_kicad.chain_loops([
        [(10.0, 0.0), (10.0, 5.0)],
        [(0.0, 0.0), (10.0, 0.0)],
        [(0.0, 5.0), (0.0, 0.0)],
        [(10.0, 5.0), (0.0, 5.0)],
    ])
    assert len(loop) == 1
    assert len(loop[0]) == 4 and loop[0][0] != loop[0][-1]


def test_view_document_matches_the_view_model_shape():
    """The viewer only knows one document shape — imports must match it exactly."""
    seeded = templates.instantiate("pico-blinky")
    placement.auto_place(seeded)
    router.route_board(seeded)
    reference = view.view_model(seeded)

    _board, doc, _warnings = import_kicad.parse_board(FIXTURE)

    assert set(doc) == set(reference)
    assert set(doc["board"]) == set(reference["board"])
    assert set(doc["rules"]) == set(reference["rules"])
    assert set(doc["stats"]) == set(reference["stats"])
    assert set(doc["erc"]) == set(reference["erc"])
    assert {"ok", "errors", "warnings"} <= set(doc["drc"])
    assert isinstance(doc["outline"], list) and len(doc["outline"][0]) == 2

    for layer in ("F.Cu", "B.Cu"):
        assert set(doc["copper"][layer]) == set(reference["copper"][layer])
        assert set(doc["copper"][layer]["flashes"][0]) == \
            set(reference["copper"][layer]["flashes"][0])
        assert set(doc["copper"][layer]["draws"][0]) == \
            set(reference["copper"][layer]["draws"][0])

    sample_line = reference["silk"]["F.SilkS"]["lines"][0]
    sample_text = reference["silk"]["F.SilkS"]["text"][0]
    for layer in ("F.SilkS", "B.SilkS"):
        assert set(doc["silk"][layer]) == set(reference["silk"][layer])
        for line in doc["silk"][layer]["lines"]:
            assert set(line) == set(sample_line)
        for txt in doc["silk"][layer]["text"]:
            assert set(txt) == set(sample_text)

    assert set(doc["drills"][0]) == set(reference["drills"][0])
    assert set(doc["nets"][0]) == set(reference["nets"][0])
    assert set(doc["bom"][0]) == set(reference["bom"][0])
    assert set(doc["components"][0]) == set(reference["components"][0])
    assert set(doc["components"][0]["body"]) == set(reference["components"][0]["body"])
    assert set(doc["components"][0]["pins"][0]) == set(reference["components"][0]["pins"][0])


# --------------------------------------------------------------------------- #
# url imports
# --------------------------------------------------------------------------- #
def test_import_from_url_downloads_then_parses(monkeypatch):
    # conftest puts both the repo root and circuit/ on sys.path, so the same file
    # is importable as `circuit.circuit_core.samples` and `circuit_core.samples`.
    # tools.py uses the package path — patch that object.
    from circuit.circuit_core import samples

    fixture = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"
    url = "https://example.test/hw/board.kicad_pcb"

    def fake_download(url_arg, dest, label=None):
        assert url_arg == url
        dest.write_bytes(fixture.read_bytes())
        return dest

    monkeypatch.setattr(samples, "download_board", fake_download)
    out = call("circuit_import", url=url)
    assert out["ok"] is True
    assert out["components"] == 2
    assert out["read_only"] is True

    # same url again -> same project, not board-2
    again = call("circuit_import", url=url)
    assert again["board"] == out["board"]
    assert [b["slug"] for b in json.loads(HANDLERS["circuit_boards"]({}))["boards"]] == [out["board"]]


def test_import_rejects_a_non_http_url():
    out = call("circuit_import", url="file:///etc/passwd")
    assert out["ok"] is False
    assert "http" in out["error"]


def test_import_needs_a_path_or_a_url():
    out = call("circuit_import")
    assert out["ok"] is False
    assert "path or url" in out["error"]


def test_offboard_silkscreen_is_clipped_and_graphic_footprints_are_not_parts(tmp_path):
    """A logo/ESD graphic is silkscreen, not a component, and silk is clipped."""
    board = """(kicad_pcb
  (version 20221018)
  (generator pcbnew)
  (general (thickness 1.6))
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.SilkS" user "B.Silkscreen")
    (44 "Edge.Cuts" user)
  )
  (net 0 "")
  (gr_rect (start 0 0) (end 20 10) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))
  (footprint "Demo:Part" (layer "F.Cu") (at 5 5)
    (fp_text reference "U1" (at 0 -2) (layer "F.SilkS"))
    (fp_line (start -1 -1) (end 1 1) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask"))
  )
  (footprint "Demo:Logo" (layer "B.Cu") (at 40 5)
    (fp_text reference "LOGO" (at 0 0) (layer "B.SilkS"))
    (fp_line (start -5 -5) (end 60 5) (stroke (width 0.15) (type solid)) (layer "B.SilkS"))
  )
)
"""
    path = tmp_path / "clip.kicad_pcb"
    path.write_text(board)

    parsed, doc, warnings = import_kicad.parse_board(path)
    refs = [c["ref"] for c in doc["components"]]
    assert refs == ["U1"], "a padless graphic footprint must not become a component"
    assert any("silkscreen" in w for w in warnings)

    for layer in doc["silk"].values():
        for item in layer["lines"] + layer["text"]:
            for x, y in item["points"]:
                assert -1.5 <= x <= 21.5, f"silk point {x},{y} left the board"
                assert -1.5 <= y <= 11.5
