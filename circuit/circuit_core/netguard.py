"""Where a board may be downloaded from.

Both ``circuit_import url=…`` and the sample catalogue take a URL and end in a
socket, and that URL is chosen by a model. A model-picked URL is untrusted input:
``http://127.0.0.1:8080/…`` reaches whatever the host is running, and
``http://169.254.169.254/latest/meta-data/`` reaches the cloud metadata service.
A redirect chain does the same thing while looking innocent at the first hop.

So every hop is resolved here, and the socket is opened to the address that was
checked — not to a hostname that a second resolver call could answer differently
(DNS rebinding). Nothing in this module talks to a distributor, a CDN or anything
else; it is only the front door for board downloads.

Refused: loopback, private (RFC 1918 and IPv6 unique-local), link-local
(169.254.0.0/16 and fe80::/10, which covers the metadata address), CGNAT
(100.64.0.0/10), multicast, reserved, unspecified, and IPv4-mapped IPv6 forms of
any of those.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from typing import Any, List, Tuple
from urllib.parse import urljoin, urlsplit

from .project import BoardError

MAX_REDIRECTS = 5
_REDIRECT_CODES = (301, 302, 303, 307, 308)

_BLOCKED_V4 = tuple(
    ipaddress.ip_network(net) for net in (
        "0.0.0.0/8",        # "this network"
        "10.0.0.0/8",       # RFC 1918
        "100.64.0.0/10",    # CGNAT
        "127.0.0.0/8",      # loopback
        "169.254.0.0/16",   # link-local, incl. 169.254.169.254
        "172.16.0.0/12",    # RFC 1918
        "192.0.0.0/24",     # IETF protocol assignments
        "192.0.2.0/24",     # TEST-NET-1
        "192.168.0.0/16",   # RFC 1918
        "198.18.0.0/15",    # benchmarking
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",   # TEST-NET-3
        "224.0.0.0/4",      # multicast
        "240.0.0.0/4",      # reserved, incl. 255.255.255.255
    )
)


def is_blocked(address: ipaddress._BaseAddress) -> bool:
    """True when this address must never be dialled from a model-chosen URL."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_blocked(address.ipv4_mapped)
        return bool(
            address.is_private          # fc00::/7 unique-local, ::1
            or address.is_loopback
            or address.is_link_local    # fe80::/10
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    return any(address in net for net in _BLOCKED_V4)


_AddrInfo = Tuple[int, int, int, str, Any]


def _resolve(host: str, port: int) -> List[_AddrInfo]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BoardError(f"could not resolve {host}: {exc}") from exc
    if not infos:
        raise BoardError(f"could not resolve {host}")
    return infos


def check_url(url: str) -> str:
    """Validate a URL before a request is made. Returns it unchanged when it passes."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BoardError(f"{url!r} is not an http(s) URL")
    host = parts.hostname
    if not host:
        raise BoardError(f"{url!r} has no host")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise BoardError(f"{url!r} has an invalid port") from exc
    for _family, _type, _proto, _canon, sockaddr in _resolve(host, port):  # type: ignore[misc]
        address = ipaddress.ip_address(sockaddr[0])
        if is_blocked(address):
            raise BoardError(
                f"refusing to fetch {url}: {host} resolves to {address}, which is not a public address"
            )
    return url


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """Open a socket to an address that was checked first — the anti-rebinding part."""
    last: Exception | None = None
    for family, socktype, proto, _canon, sockaddr in _resolve(host, port):
        address = ipaddress.ip_address(sockaddr[0])
        if is_blocked(address):
            raise BoardError(
                f"refusing to fetch from {host}: it resolves to {address}, which is not a public address"
            )
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            sock.close()
            last = exc
    raise BoardError(f"could not connect to {host}: {last}")


def fetch(url: str, *, max_bytes: int, timeout: float = 90.0, label: str = "board") -> bytes:
    """Download ``url`` with every hop checked, and never more than ``max_bytes``.

    Redirects are followed by hand rather than by ``urllib``, so each ``Location``
    goes through the same address check as the first request.
    """
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        check_url(current)
        parts = urlsplit(current)
        host = parts.hostname or ""
        secure = parts.scheme == "https"
        port = parts.port or (443 if secure else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        sock = _connect(host, port, timeout)
        try:
            if secure:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            conn = http.client.HTTPSConnection(host, port, timeout=timeout) if secure \
                else http.client.HTTPConnection(host, port, timeout=timeout)
            conn.sock = sock          # the socket we already validated and opened
            try:
                conn.request("GET", path, headers={
                    "User-Agent": "hermes-circuit",
                    "Accept": "application/octet-stream,text/plain;q=0.9,*/*;q=0.5",
                })
                response = conn.getresponse()
                status = response.status
                if status in _REDIRECT_CODES:
                    location = response.getheader("Location")
                    if not location:
                        raise BoardError(f"{label}: HTTP {status} without a Location")
                    current = urljoin(current, location)
                    continue
                if status != 200:
                    raise BoardError(f"{label}: HTTP {status} from {host}")
                chunks: List[bytes] = []
                total = 0
                while True:
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise BoardError(
                            f"{label} is larger than {max_bytes // (1024 * 1024)} MB — refusing"
                        )
                    chunks.append(block)
                return b"".join(chunks)
            finally:
                conn.close()
        except ssl.SSLError as exc:
            raise BoardError(f"TLS failed for {host}: {exc}") from exc
        finally:
            try:
                sock.close()
            except OSError:
                pass
    raise BoardError(f"{label}: more than {MAX_REDIRECTS} redirects")
