"""Project model: nets, references, ERC, persistence."""

import json

import pytest

from circuit_core import store
from circuit_core.project import Board, BoardError, canonical_net, net_class


def test_net_classes():
    assert net_class("GND") == "ground"
    assert net_class("+3V3") == "power"
    assert net_class("5V") == "power"
    assert net_class("SDA") == "signal"
    assert canonical_net("  led a ") == "LED_A"


def test_add_component_assigns_refs_and_nets(board):
    c = board.add_component("r-0603", nets={"1": "+3v3", "2": "gnd"})
    assert c["ref"] == "R3"  # R1/R2 exist in the template
    assert c["nets"] == {"1": "+3V3", "2": "GND"}
    assert board.data["nets"]["+3V3"]["class"] == "power"


def test_unknown_part_and_pin_are_rejected(board):
    with pytest.raises(KeyError):
        board.add_component("does-not-exist")
    with pytest.raises(BoardError):
        board.add_component("r-0603", nets={"9": "X"})
    with pytest.raises(BoardError):
        board.add_component("r-0603", ref="R1")  # already used


def test_connect_merges_onto_existing_net(board):
    board.add_component("r-0603", ref="R9", nets={"1": "LED", "2": "NODE_A"})
    board.connect([["R9", "2", "C1", "1"]])
    assert board.component("C1")["nets"]["1"] == "NODE_A"


def test_remove_prunes_dangling_nets(board):
    board.remove_component("SW1")
    board._prune_nets()
    assert "BTN" not in board.data["nets"] or board.data["nets"]["BTN"]


def test_erc_detects_overlap_and_dangling(board):
    from circuit_core import placement

    placement.auto_place(board)
    # put a second part exactly on top of the button
    sw = board.component("SW1")
    board.add_component("tact-6mm", ref="SW9", nets={"1": "GND", "2": "GND"},
                        x=sw["x"], y=sw["y"])
    board.add_component("r-0603", ref="R99", nets={"1": "ONLY_ONE"})
    report = board.erc()
    assert any("courtyard overlap" in e for e in report["errors"])
    assert any("ONLY_ONE" in w for w in report["warnings"])
    assert report["ok"] is False


def test_boards_roundtrip_through_store(board):
    slug = store.save(board)
    assert slug
    again = store.load(slug)
    assert again.data["title"] == board.data["title"]
    assert len(again.data["components"]) == len(board.data["components"])
    assert json.loads(json.dumps(again.to_dict())) == again.to_dict()


def test_store_rejects_bad_slugs():
    with pytest.raises(BoardError):
        store.load("../etc/passwd")
    with pytest.raises(BoardError):
        store.load("does-not-exist")


def test_duplicate_titles_get_unique_slugs(board):
    a = store.save(board)
    b = store.save(Board.create(board.data["title"]))
    assert a != b
    assert len(store.list_boards()) == 2


def test_pins_can_be_addressed_by_name_or_number(board):
    """A datasheet gives names, the geometry gives numbers — accept both."""
    ref = board.add_component("bme280-brk", nets={"1": "+3V3"})["ref"]
    # by name, unambiguous
    board.set_net(ref, "SDA", "I2C_SDA")
    assert board.component(ref)["nets"]["4"] == "I2C_SDA"
    # by pad number, same result
    board.set_net(ref, "4", "I2C_SDA")
    assert board.component(ref)["nets"]["4"] == "I2C_SDA"
    # case-insensitive
    board.set_net(ref, "scl", "I2C_SCL")
    assert board.component(ref)["nets"]["3"] == "I2C_SCL"


def test_ambiguous_pin_name_says_which_pads_to_use(board):
    ref = board.add_component("pico")["ref"]
    with pytest.raises(BoardError) as exc:
        board.set_net(ref, "GND", "GND")
    message = str(exc.value)
    assert "pins named GND" in message
    assert "use the pad number" in message
    # the numbers it suggests actually work
    assert "3" in message
    board.set_net(ref, "3", "GND")
    assert board.component(ref)["nets"]["3"] == "GND"


def test_unknown_pin_lists_what_the_part_has(board):
    ref = board.add_component("ne555")["ref"]
    with pytest.raises(BoardError) as exc:
        board.set_net(ref, "NOPE", "X")
    message = str(exc.value)
    assert "no pin NOPE" in message and "known pins" in message
