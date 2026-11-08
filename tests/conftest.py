"""Shared fixtures."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "circuit"))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets an isolated board store."""
    monkeypatch.setenv("CIRCUIT_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data"


@pytest.fixture
def board():
    from circuit_core import templates

    b = templates.instantiate("pico-blinky")
    return b
