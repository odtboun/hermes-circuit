"""Sample-board catalogue: offline behaviour only.

The samples themselves are downloaded from upstream at load time, so these tests
never touch the network — they pin the catalogue shape and the guards that stop a
bad download from being parsed as a board.
"""

from __future__ import annotations

import io
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
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(
        samples.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse(b"<!DOCTYPE html><html>login</html>"),
    )
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert "did not return a KiCad board" in str(exc.value)
    assert not (tmp_path / "video.kicad_pcb").exists()


def test_oversized_download_is_refused(monkeypatch, tmp_path):
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(samples, "MAX_BYTES", 16)
    monkeypatch.setattr(
        samples.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse(b"(kicad_pcb (version 20241229) " + b" " * 64),
    )
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert "larger than" in str(exc.value)


def test_network_failure_is_reported_not_raised_raw(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(samples.urllib.request, "urlopen", boom)
    with pytest.raises(BoardError) as exc:
        samples.fetch("video", tmp_path / "video.kicad_pcb")
    assert "could not download" in str(exc.value)


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
