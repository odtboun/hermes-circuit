"""Sample boards — real open-source KiCad designs, imported on demand.

Nothing here is redistributed: each entry is a URL into the upstream KiCad
demo repository, fetched when the user asks for it and then parsed by
``import_kicad``. That keeps the plugin free of third-party board files (and of
their licences) while still giving the viewer genuinely complex boards to
render, which the bundled 13-part templates cannot.
"""

from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List

from .import_kicad import import_board
from .project import BoardError

_BASE = "https://gitlab.com/kicad/code/kicad/-/raw/master/demos"
# A KiCad board of this size is already pathological; refuse anything bigger
# rather than buffering an arbitrary download in memory.
MAX_BYTES = 40 * 1024 * 1024
_TIMEOUT_S = 90
_LICENSE = "GPL-3.0-or-later (KiCad demo project)"

SAMPLES: Dict[str, dict] = {
    "tiny-tapeout": {
        "title": "Tiny Tapeout demo",
        "file": "tiny_tapeout/tinytapeout-demo.kicad_pcb",
        "parts": 309, "size_mm": [104.0, 81.0], "layers": 4,
        "note": "The densest sample: 309 footprints, 1481 top traces. 4 layers flattened to 2.",
    },
    "openair-max": {
        "title": "OpenAir MAX",
        "file": "openair-max/One-Air-Max.kicad_pcb",
        "parts": 210, "size_mm": [99.0, 72.0], "layers": 2,
        "note": "Mixed SMD/THT control board, 410 vias. A few footprints have no reference designator.",
    },
    "video": {
        "title": "KiCad demo — video",
        "file": "video/video.kicad_pcb",
        "parts": 189, "size_mm": [312.0, 106.7], "layers": 4,
        "note": "Long PCI-era board: 312 mm wide, 588 nets, 1728 tracks. 4 layers flattened to 2.",
    },
    "cm5-minima": {
        "title": "CM5 MINIMA",
        "file": "cm5_minima/CM5_MINIMA_3.kicad_pcb",
        "parts": 112, "size_mm": [61.0, 64.0], "layers": 6,
        "note": "Compact 6-layer carrier, flattened to 2 on import.",
    },
    "stickhub": {
        "title": "StickHub",
        "file": "stickhub/StickHub.kicad_pcb",
        "parts": 94, "size_mm": [16.0, 40.0], "layers": 2,
        "note": "A 16 x 40 mm USB stick — the best test of the viewer at small board sizes.",
    },
    "royalblue54l-feather": {
        "title": "RoyalBlue54L Feather",
        "file": "royalblue54L_feather/RoyalBlue54L-Feather.kicad_pcb",
        "parts": 71, "size_mm": [58.0, 23.0], "layers": 8,
        "note": "Feather-form-factor module, 8 layers flattened to 2.",
    },
    "pic-programmer": {
        "title": "PIC programmer",
        "file": "pic_programmer/pic_programmer.kicad_pcb",
        "parts": 63, "size_mm": [160.0, 99.0], "layers": 2,
        "note": "Classic through-hole KiCad demo, 2 layers, nothing flattened.",
    },
}


def _url(entry: dict) -> str:
    return f"{_BASE}/{entry['file']}"


def names() -> List[dict]:
    """The sample catalogue, without downloading anything."""
    return [
        {
            "id": sid,
            "title": e["title"],
            "parts": e["parts"],
            "size_mm": e["size_mm"],
            "layers": e["layers"],
            "license": _LICENSE,
            "note": e["note"],
            "url": _url(e),
        }
        for sid, e in SAMPLES.items()
    ]


def fetch(sample_id: str, dest: Path) -> Path:
    """Download one sample board to ``dest`` and return the path."""
    entry = SAMPLES.get(sample_id)
    if entry is None:
        raise BoardError(
            f"unknown sample {sample_id!r} (one of: {', '.join(SAMPLES)})"
        )
    request = urllib.request.Request(_url(entry), headers={"User-Agent": "hermes-circuit"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            payload = response.read(MAX_BYTES + 1)
    except Exception as exc:  # network, DNS, TLS, HTTP status
        raise BoardError(f"could not download {sample_id!r}: {exc}") from exc
    if len(payload) > MAX_BYTES:
        raise BoardError(f"{sample_id!r} is larger than {MAX_BYTES // (1024 * 1024)} MB — refusing")
    if not payload.lstrip().startswith(b"("):
        # A GitLab error page or an HTML login wall would otherwise be parsed as
        # a board and produce a confusing empty result.
        raise BoardError(f"{sample_id!r} did not return a KiCad board (got an HTML/error page)")
    dest.write_bytes(payload)
    return dest


def load(sample_id: str) -> dict:
    """Fetch and import one sample, returning the importer summary."""
    entry = SAMPLES.get(sample_id)
    if entry is None:
        raise BoardError(
            f"unknown sample {sample_id!r} (one of: {', '.join(SAMPLES)})"
        )
    with tempfile.TemporaryDirectory(prefix="circuit-sample-") as tmp:
        path = fetch(sample_id, Path(tmp) / f"{sample_id}.kicad_pcb")
        # Stable slug + stable source identity: the download lives at a fresh temp
        # path each time, which would otherwise create <id>-2, <id>-3, ...
        summary = import_board(str(path), key=sample_id, source=_url(entry))
    summary["sample"] = sample_id
    summary["license"] = _LICENSE
    summary["source"] = _url(entry)
    return summary
