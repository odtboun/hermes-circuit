"""Sample boards — real open-source KiCad designs, imported on demand.

Nothing here is redistributed: each entry is a URL into the upstream KiCad
demo repository, fetched when the user asks for it and then parsed by
``import_kicad``. That keeps the plugin free of third-party board files (and of
their licences) while still giving the viewer genuinely complex boards to
render, which the bundled 13-part templates cannot.
"""

from __future__ import annotations

import tempfile
from urllib.parse import quote
from pathlib import Path
from typing import Dict, List

from . import netguard
from .import_kicad import import_board
from .project import BoardError

_BASE = "https://gitlab.com/kicad/code/kicad/-/raw/master/demos"
# A KiCad board of this size is already pathological; refuse anything bigger
# rather than buffering an arbitrary download in memory.
MAX_BYTES = 40 * 1024 * 1024
_TIMEOUT_S = 90
_LICENSE = "GPL-3.0-or-later (KiCad demo project)"


def download_board(url: str, dest: Path, label: str = "board") -> Path:
    """Fetch a ``.kicad_pcb`` from ``url`` into ``dest``.

    Shared by the sample catalogue and ``circuit_import url=…`` so both get the
    same guards: every hop resolved and refused if it lands on a loopback, private,
    link-local, CGNAT or metadata address (``netguard``), a size cap, and a
    rejection of anything that is not a KiCad s-expression (a GitLab/GitHub error
    page would otherwise parse as an empty board and look like a viewer bug).
    """
    try:
        payload = netguard.fetch(url, max_bytes=MAX_BYTES, timeout=_TIMEOUT_S, label=label)
    except BoardError:
        raise
    except Exception as exc:  # TLS, HTTP status, a socket that died mid-read
        raise BoardError(f"could not download {label}: {exc}") from exc
    if not payload.lstrip().startswith(b"("):
        raise BoardError(f"{label} did not return a KiCad board (got an HTML/error page)")
    dest.write_bytes(payload)
    return dest

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
    "coldfire": {
        "title": "ColdFire / Xilinx dev kit",
        "file": "kit-dev-coldfire-xilinx_5213/kit-dev-coldfire-xilinx_5213.kicad_pcb",
        "parts": 160, "size_mm": [157.5, 91.4], "layers": 4,
        "note": "160 parts, 825 pads, 253 vias and 278 nets: the densest 2-row board here. 4 layers flattened to 2.",
    },
    "complex-hierarchy": {
        "title": "Complex hierarchy",
        "file": "complex_hierarchy/complex_hierarchy.kicad_pcb",
        "parts": 68, "size_mm": [100.7, 80.0], "layers": 2,
        "note": "The hierarchical-schematic demo: 68 footprints, 52 nets, not a single via. The cleanest board for reading silk, outlines and pad shapes.",
    },
    "ecc83": {
        "title": "ECC83 valve preamp",
        "file": "ecc83/ecc83-pp.kicad_pcb",
        "parts": 15, "size_mm": [52.1, 46.4], "layers": 2,
        "note": "A valve preamplifier: 15 through-hole parts with wide pads and big silk lettering. The friendliest board for close-up viewing.",
    },
    "interf-u": {
        "title": "Interf-U ISA card",
        "file": "interf_u/interf_u.kicad_pcb",
        "parts": 24, "size_mm": [115.6, 108.2], "layers": 2,
        "note": "ISA-bus interface card: 379 pads and 84 vias, mostly through-hole, with long parallel buses.",
    },
    "multichannel": {
        "title": "Multichannel mixer",
        "file": "multichannel/multichannel_mixer.kicad_pcb",
        "parts": 114, "size_mm": [110.0, 111.0], "layers": 2,
        "note": "A routed 6-channel mixer on a 110 mm square: 114 parts, 80 nets, 29 vias.",
    },
    "multichannel-unrouted": {
        "title": "Multichannel mixer (unrouted)",
        "file": "multichannel/multichannel_mixer-unrouted.kicad_pcb",
        "parts": 114, "size_mm": [110.0, 111.0], "layers": 2,
        "note": "The same mixer before routing — pads and outlines only. Load it next to multichannel to see exactly what routing adds.",
    },
    "nfc-antenna": {
        "title": "NFC antenna",
        "file": "royalblue54L_feather/nfc_antenna/RoyalBlue54L-NFC-Antenna/RoyalBlue54L-NFC-Antenna.kicad_pcb",
        "parts": 1, "size_mm": [23.0, 58.0], "layers": 2,
        "note": "One part, and the whole board is a spiral of copper. The best test of trace and coil rendering.",
    },
    "sonde-xilinx": {
        "title": "Xilinx probe card",
        "file": "sonde xilinx/sonde xilinx.kicad_pcb",
        "parts": 25, "size_mm": [80.4, 43.2], "layers": 2,
        "note": "Xilinx joint-test probe: 108 pads, 42 nets, through-hole with a dense header row.",
    },
}


def _url(entry: dict) -> str:
    # Some demo paths contain spaces ("sonde xilinx/…"); quote the path but keep
    # the separators, or the request 404s on an HTML page that looks like a board.
    return f"{_BASE}/{quote(entry['file'])}"


def names() -> List[dict]:
    """The sample catalogue, without downloading anything."""
    return [
        {
            "id": sid,
            "title": e["title"],
            "parts": e["parts"],
            "size_mm": e["size_mm"],
            "layers": e["layers"],
            "license": e.get("license", _LICENSE),
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
    return download_board(_url(entry), dest, label=repr(sample_id))


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
    summary["license"] = entry.get("license", _LICENSE)
    summary["source"] = _url(entry)
    return summary
