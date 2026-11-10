"""The plugin backend routes, loaded the way Hermes loads them."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from circuit_core import compile as builder
from circuit_core import templates

PLUGIN = Path(__file__).resolve().parent.parent / "circuit"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    data = tmp_path_factory.mktemp("api-data")
    os.environ["CIRCUIT_DATA_DIR"] = str(data)
    board = templates.instantiate("pico-blinky")
    builder.build(board)
    spec = importlib.util.spec_from_file_location(
        "hermes_dashboard_plugin_circuit", PLUGIN / "dashboard" / "plugin_api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/circuit")
    return TestClient(app), data


@pytest.fixture(autouse=True)
def _pin_store(client):
    """The per-test data dir must not shadow the module's built board."""
    import os

    os.environ["CIRCUIT_DATA_DIR"] = str(client[1])


def test_health(client):
    client = client[0]
    r = client.get("/api/plugins/circuit/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["boards"] >= 1


def test_board_list_and_document(client):
    client = client[0]
    r = client.get("/api/plugins/circuit/boards")
    assert r.status_code == 200
    slug = r.json()["boards"][0]["slug"]
    doc = client.get(f"/api/plugins/circuit/boards/{slug}")
    assert doc.status_code == 200
    view = doc.json()
    assert view["board"]["layers"] == 2
    assert view["copper"]["F.Cu"]["flashes"]
    assert view["components"] and view["nets"]


def test_file_endpoint_serves_exports_only(client):
    client = client[0]
    boards = client.get("/api/plugins/circuit/boards").json()["boards"]
    slug = boards[0]["slug"]
    ok = client.get(f"/api/plugins/circuit/boards/{slug}/file/preview.svg")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/svg")
    bad = client.get(f"/api/plugins/circuit/boards/{slug}/file/../../board.json")
    assert bad.status_code in (404, 400)


def test_unknown_board_is_404(client):
    client = client[0]
    assert client.get("/api/plugins/circuit/boards/nope").status_code == 404


def test_rebuild_on_an_imported_board_is_a_409_not_a_500(tmp_path):
    """The router cannot route a board whose parts are not in the library."""
    from fastapi import HTTPException

    from circuit.dashboard import plugin_api
    from circuit_core import import_kicad

    fixture = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"
    slug = import_kicad.import_board(str(fixture))["board"]

    with pytest.raises(HTTPException) as exc:
        plugin_api.rebuild(slug)
    assert exc.value.status_code == 409
    assert "read-only" in exc.value.detail

    # and the fresh-view route must serve the stored document instead of raising
    body = json.loads(plugin_api.board_view(slug).body)
    assert body["imported"] is True
    assert body["stats"]["components"] == 2


def test_docs_routes_list_and_render(tmp_path, monkeypatch):
    """The page fetches these two: the index, then the HTML for one document."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from circuit.dashboard import plugin_api
    from circuit_core import templates

    monkeypatch.setenv("CIRCUIT_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/circuit")
    client = TestClient(app)

    board = templates.instantiate("pico-blinky")
    plugin_api.placement.auto_place(board)
    plugin_api.autorouter.route_board(board)
    slug = plugin_api.store.save(board)

    index = client.get(f"/api/plugins/circuit/boards/{slug}/docs")
    assert index.status_code == 200
    kinds = [d["kind"] for d in index.json()["documents"]]
    assert kinds == ["shopping", "wiring", "poster"]

    for kind in kinds:
        res = client.get(f"/api/plugins/circuit/boards/{slug}/docs/{kind}")
        assert res.status_code == 200
        body = res.json()
        assert body["kind"] == kind
        assert body["html"].startswith("<!doctype html>")
        assert "<script" not in body["html"].lower()
        assert body["bytes"] > 1000

    missing = client.get(f"/api/plugins/circuit/boards/{slug}/docs/nope")
    assert missing.status_code == 404


def test_docs_route_refuses_an_imported_board(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from circuit.dashboard import plugin_api
    from circuit_core import import_kicad

    monkeypatch.setenv("CIRCUIT_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/circuit")
    client = TestClient(app)

    fixture = Path(__file__).resolve().parent / "fixtures" / "simple.kicad_pcb"
    slug = import_kicad.import_board(str(fixture))["board"]

    res = client.get(f"/api/plugins/circuit/boards/{slug}/docs/poster")
    assert res.status_code == 409
    assert "imported" in res.json()["detail"]
