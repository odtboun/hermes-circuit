"""The door a model-chosen board URL has to get through.

Nothing here touches the network: the address checks are pure, hostname resolution
is stubbed to a public address (IP literals resolve to themselves, so the refusals
stay honest), and the fetch loop talks to a local HTTP server through a stubbed
``_connect`` — which is how a redirect to 169.254.169.254 gets exercised for real
without dialling it.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from circuit_core import netguard
from circuit_core.project import BoardError

PUBLIC = "93.184.216.34"


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.9.9.9", "0.0.0.0", "10.1.2.3", "172.16.5.4", "172.31.255.254",
    "192.168.0.10", "169.254.169.254", "169.254.1.1", "100.64.0.1", "100.127.255.254",
    "224.0.0.1", "240.0.0.1", "255.255.255.255", "::1", "fe80::1", "fc00::1", "fd12::34",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254",
])
def test_these_addresses_are_never_dialled(address):
    assert netguard.is_blocked(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "140.82.121.4", "2606:4700:4700::1111"])
def test_public_addresses_pass(address):
    assert not netguard.is_blocked(ipaddress.ip_address(address))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/board.kicad_pcb",
    "http://localhost/board.kicad_pcb",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://[::1]/board.kicad_pcb",
    "http://192.168.1.20:9000/board.kicad_pcb",
    "http://100.64.0.9/board.kicad_pcb",
    "file:///etc/passwd",
    "ftp://example.com/board.kicad_pcb",
])
def test_check_url_refuses(url):
    with pytest.raises(BoardError):
        netguard.check_url(url)


def test_check_url_allows_a_public_address():
    assert netguard.check_url(f"https://{PUBLIC}/x/board.kicad_pcb")


# --------------------------------------------------------------------------- #
# the fetch loop, against a local server standing in for a public host
# --------------------------------------------------------------------------- #

class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802 — http.server's spelling
        status, headers, body = self.routes.get(self.path, (404, {}, b"nope"))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture()
def wire(monkeypatch):
    """A local HTTP server, offline DNS, and a socket that reaches the server."""
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def fake_resolve(host, _port):
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            ip = ipaddress.ip_address(PUBLIC)     # a hostname we never actually dial
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (str(ip), _port))]

    monkeypatch.setattr(netguard, "_resolve", fake_resolve)
    monkeypatch.setattr(
        netguard, "_connect",
        lambda host, p, timeout: socket.create_connection(("127.0.0.1", port), timeout),
    )
    yield _Handler
    httpd.shutdown()
    httpd.server_close()


def test_fetch_downloads(wire):
    wire.routes = {"/board.kicad_pcb": (200, {}, b"(kicad_pcb (version 20231120))")}
    body = netguard.fetch("http://example.com/board.kicad_pcb", max_bytes=1000)
    assert body.startswith(b"(kicad_pcb")


def test_fetch_follows_a_public_redirect(wire):
    wire.routes = {
        "/old.kicad_pcb": (302, {"Location": "/new.kicad_pcb"}, b""),
        "/new.kicad_pcb": (200, {}, b"(kicad_pcb)"),
    }
    assert netguard.fetch("http://example.com/old.kicad_pcb", max_bytes=1000) == b"(kicad_pcb)"


@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8080/admin",
    "http://[::1]/",
])
def test_fetch_refuses_a_redirect_into_the_private_network(wire, target):
    wire.routes = {"/old.kicad_pcb": (302, {"Location": target}, b"")}
    with pytest.raises(BoardError) as excinfo:
        netguard.fetch("http://example.com/old.kicad_pcb", max_bytes=1000)
    assert "not a public address" in str(excinfo.value)


def test_fetch_refuses_a_redirect_loop(wire):
    wire.routes = {"/a": (302, {"Location": "/a"}, b"")}
    with pytest.raises(BoardError) as excinfo:
        netguard.fetch("http://example.com/a", max_bytes=1000)
    assert "redirects" in str(excinfo.value)


def test_fetch_refuses_an_oversize_body(wire):
    wire.routes = {"/big.kicad_pcb": (200, {}, b"x" * 5000)}
    with pytest.raises(BoardError) as excinfo:
        netguard.fetch("http://example.com/big.kicad_pcb", max_bytes=1000)
    assert "larger than" in str(excinfo.value)


def test_fetch_reports_a_bad_status(wire):
    wire.routes = {"/missing.kicad_pcb": (404, {}, b"nope")}
    with pytest.raises(BoardError) as excinfo:
        netguard.fetch("http://example.com/missing.kicad_pcb", max_bytes=1000)
    assert "HTTP 404" in str(excinfo.value)
