"""Sample-board catalogue: offline behaviour only.

The samples themselves are downloaded from upstream at load time, so these tests
never touch the network — they pin the catalogue shape and the guards that stop a
bad download from being parsed as a board.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit.circuit_core import samples
from circuit.circuit_core.project import BoardError


def test_catalogue_entries_are_complete():
    rows = samples.names()
    assert len(rows) >= 5
    for row in rows:
        assert row["id"] in samples.SAMPLES
        assert row["title"]
        assert row["url"].startswith("https://")
        assert row["url"].endswith(".kicad_pcb")
        assert row["parts"] > 0
        assert len(row["size_mm"]) == 2 and all(v > 0 for v in row["size_mm"])
        assert "GPL" in row["license"]
        assert row["note"]


def test_unknown_sample_is_rejected():
    with pytest.raises(BoardError) as exc:
        samples.fetch("no-such-board", Path("/tmp/never-written.kicad_pcb"))
    assert "unknown sample" in str(exc.value)


def test_html_error_page_is_not_parsed_as_a_board(monkeypatch, tmp_path):
    """A GitLab/GitHub error page must not parse as an empty board."""
    monkeypatch.setattr(samples.netguard, "fetch",
                        lambda *a, **k: b"<!DOCTYPE html><html>login</html>")
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert "did not return a KiCad board" in str(exc.value)
    assert not (tmp_path / "video.kicad_pcb").exists()


def test_download_passes_the_size_cap_to_the_guard(monkeypatch, tmp_path):
    """The cap lives in netguard now, so this pins that it is handed the catalogue's."""
    seen = {}

    def fake_fetch(url, *, max_bytes, timeout, label):
        seen["max_bytes"] = max_bytes
        seen["url"] = url
        raise BoardError(f"{label} is larger than {max_bytes // (1024 * 1024)} MB — refusing")

    monkeypatch.setattr(samples.netguard, "fetch", fake_fetch)
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert seen["max_bytes"] == samples.MAX_BYTES
    assert seen["url"].startswith("https://")
    assert "larger than" in str(exc.value)


def test_network_failure_is_reported_not_raised_raw(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(samples.netguard, "fetch", boom)
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert "could not download" in str(exc.value)


def test_a_private_address_is_refused_before_any_socket(monkeypatch, tmp_path):
    """The catalogue goes through the same door as `circuit_import url=`."""
    from circuit_core import netguard

    real = netguard.check_url
    seen = []

    def spy(url):
        seen.append(url)
        return real(url)

    monkeypatch.setattr(samples.netguard, "check_url", spy)
    with pytest.raises(BoardError):
        samples.download_board("http://127.0.0.1:8080/board.kicad_pcb", tmp_path / "x.kicad_pcb")
    assert seen == ["http://127.0.0.1:8080/board.kicad_pcb"]


def test_reloading_a_sample_replaces_the_same_project(monkeypatch):
    """A sample downloads to a fresh temp path each time; the slug must not drift."""
    from circuit_core import store

    fixture = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"

    def fake_fetch(sample_id, dest):
        dest.write_bytes(fixture.read_bytes())
        return dest

    monkeypatch.setattr(samples, "fetch", fake_fetch)

    first = samples.load("pic-programmer")
    second = samples.load("pic-programmer")

    assert first["board"] == "pic-programmer"
    assert second["board"] == first["board"], "re-load created a -2 copy"
    assert [b["slug"] for b in store.list_boards()] == ["pic-programmer"]
    # imported boards must not claim to be routable/editable
    from circuit_core import store as s2

    assert s2.load("pic-programmer").data["imported"] is True


def test_catalogue_covers_the_whole_kicad_demo_set():
    """Fifteen boards, not seven: the catalogue should be a browse, not a taste."""
    ids = set(samples.SAMPLES)
    for required in ("tiny-tapeout", "coldfire", "complex-hierarchy", "ecc83",
                     "interf-u", "multichannel", "multichannel-unrouted",
                     "nfc-antenna", "sonde-xilinx"):
        assert required in ids, f"missing sample {required}"
    assert len(ids) >= 15
    # a spread of sizes, not fifteen variations of the same board
    parts = sorted(samples.SAMPLES[s]["parts"] for s in ids)
    assert parts[0] <= 2, "the catalogue should include a one-part board"
    assert parts[-1] >= 250, "the catalogue should include a very dense board"
    sizes = [max(samples.SAMPLES[s]["size_mm"]) for s in ids]
    assert min(sizes) < 45 and max(sizes) > 300, "small and very large boards"


def test_sample_paths_with_spaces_are_url_quoted():
    """'sonde xilinx/sonde xilinx.kicad_pcb' would 404 as a raw URL."""
    entry = samples.SAMPLES["sonde-xilinx"]
    assert " " in entry["file"], "this test is pointless if the path has no space"
    url = samples._url(entry)
    assert " " not in url
    assert "%20" in url
    assert url.startswith("https://") and url.endswith(".kicad_pcb")


def test_every_sample_has_its_own_licence_string():
    """A future non-KiCad board can declare its own licence; the default is KiCad's."""
    for row in samples.names():
        assert row["license"], row["id"]
        assert "GPL" in row["license"] or "MIT" in row["license"] or "Apache" in row["license"]
