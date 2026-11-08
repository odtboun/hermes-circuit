"""Placement, routing and DRC on every starter design."""

import time

import pytest

from circuit_core import drc, placement, router, templates


TEMPLATES = [t["id"] for t in templates.names()]


@pytest.mark.parametrize("tid", TEMPLATES)
def test_template_places_cleanly(tid):
    board = templates.instantiate(tid)
    moves = placement.auto_place(board)
    assert len(moves) == len(board.data["components"])
    # no courtyard overlaps, everything on the board
    report = board.erc()
    assert not [e for e in report["errors"] if "overlap" in e], report["errors"]
    assert not [e for e in report["errors"] if "outside" in e], report["errors"]
    for c in board.data["components"]:
        assert 0 <= c["x"] <= board.board["width"]
        assert 0 <= c["y"] <= board.board["height"]


@pytest.mark.parametrize("tid", TEMPLATES)
def test_template_routes_with_no_drc_errors(tid):
    board = templates.instantiate(tid)
    placement.auto_place(board)
    started = time.time()
    result = router.route_board(board)
    elapsed = time.time() - started
    assert result["failed"] == [], result["failed"]
    assert result["stats"]["routed_nets"] == result["stats"]["nets"]
    report = drc.check(board)
    assert report["ok"], report["errors"][:6]
    assert report["counts"]["connectivity"] == 0
    assert elapsed < 120, f"{tid} routing took {elapsed:.1f}s"


def test_routing_is_deterministic():
    board = templates.instantiate("pico-blinky")
    placement.auto_place(board)
    first = router.route_board(board)
    second = router.route_board(board)
    assert first["stats"]["routed_nets"] == second["stats"]["routed_nets"]
    assert first["failed"] == second["failed"]


def test_drc_catches_a_short(board):
    placement.auto_place(board)
    board.data["routes"] = {
        "LED": [{"layer": "F.Cu", "width": 0.2, "points": [[5, 5], [20, 5]]}],
        "GND": [{"layer": "F.Cu", "width": 0.2, "points": [[10, 2], [10, 9]]}],
    }
    board.data["vias"] = []
    report = drc.check(board)
    assert not report["ok"]
    assert any("clearance" in e for e in report["errors"])
    assert any("unrouted" in e or "partly" in e for e in report["errors"])


def test_drc_reports_unrouted_net(board):
    placement.auto_place(board)
    board.data["routes"] = {}
    report = drc.check(board)
    assert "LED" in report["unrouted_nets"] or "GND" in report["unrouted_nets"]
    assert not report["ok"]


def test_router_never_crosses_an_unassigned_pad(board):
    """A pad the netlist left unassigned must still be an obstacle."""
    placement.auto_place(board)
    router.route_board(board)
    report = drc.check(board)
    # any trace crossing a no-net pad shows up as a clearance violation
    crossings = [e for e in report["errors"] if "(no net)" in e]
    assert crossings == []


def test_board_sized_too_small_reports_failure_not_crash():
    board = templates.instantiate("pico-sensor-hub")
    board.board["width"] = 30
    board.board["height"] = 20
    placement.auto_place(board)
    result = router.route_board(board)
    assert result["stats"]["nets"] >= 1  # routed what it could
    assert isinstance(result["failed"], list)
