"""The agent-facing tools, end to end, exactly as the model calls them."""

import json

from circuit.tools import HANDLERS


def call(name, **args):
    payload = json.loads(HANDLERS[name](args))
    return payload


def test_catalog_lists_parts_and_templates():
    out = call("circuit_catalog", query="resistor")
    assert out["ok"] is True
    assert any(p["id"] == "r-0805" for p in out["parts"])
    assert any(t["id"] == "pico-blinky" for t in out["templates"])
    assert "module" in out["categories"]


def test_create_from_template_routes_and_checks():
    out = call("circuit_create", title="Blinky", template="pico-blinky")
    assert out["ok"] is True
    assert out["drc_ok"] is True
    assert out["routed"]["routed_nets"] == out["routed"]["nets"]
    assert out["summary"]["component_count"] >= 8


def test_full_custom_board_flow():
    created = call("circuit_create", title="Divider", width=40, height=30)
    slug = created["board"]
    a = call("circuit_add_part", board=slug, part="header-1x2", ref="J1",
             value="IN", nets={"1": "VIN", "2": "GND"})
    assert a["ok"] is True
    b = call("circuit_add_part", board=slug, part="r-0805", ref="R1", value="10k",
             nets={"1": "VIN", "2": "MID"})
    c = call("circuit_add_part", board=slug, part="r-0805", ref="R2", value="10k",
             nets={"1": "MID", "2": "GND"})
    assert b["ok"] and c["ok"]
    conn = call("circuit_connect", board=slug,
                connections=[["J1", "1", "R1", "1"], ["R1", "2", "R2", "1"], ["R2", "2", "J1", "2"]])
    assert conn["ok"] is True
    placed = call("circuit_place", board=slug)
    assert placed["ok"] and placed["mode"] == "auto"
    routed = call("circuit_route", board=slug)
    assert routed["ok"] is True
    assert routed["drc_ok"] is True, routed["drc"]["errors"]
    exported = call("circuit_export", board=slug)
    assert exported["ok"] is True
    assert any(f["path"].endswith("-F_Cu.gbr") for f in exported["files"])
    view = call("circuit_view", board=slug)
    assert view["directive"] == f'::circuit{{board="{slug}"}}'
    assert view["preview_file"].endswith("preview.html")


def test_unknown_part_and_board_return_errors():
    out = call("circuit_add_part", part="nope", nets={})
    assert out["ok"] is False and "no boards" in out["error"].lower()
    created = call("circuit_create", title="Err board")
    slug = created["board"]
    bad = call("circuit_add_part", board=slug, part="nope")
    assert bad["ok"] is False and "unknown part" in bad["error"]
    missing = call("circuit_board", board="does-not-exist")
    assert missing["ok"] is False


def test_boards_list_and_check():
    call("circuit_create", title="Listed", template="power-5v")
    listing = call("circuit_boards")
    assert listing["count"] >= 1
    slug = listing["boards"][0]["slug"]
    checked = call("circuit_check", board=slug)
    assert checked["ok"] is True
    assert checked["verdict"] in ("pass", "needs work")


def test_remove_part_updates_state():
    created = call("circuit_create", title="Removable", template="pico-blinky")
    slug = created["board"]
    out = call("circuit_remove_part", board=slug, ref="SW1")
    assert out["ok"] is True
    state = call("circuit_board", board=slug)
    assert all(c["ref"] != "SW1" for c in state["components"])
