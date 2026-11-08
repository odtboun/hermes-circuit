"""Library invariants: pads must not overlap, parts must agree with footprints."""

from circuit_core import drc, geom
from circuit_core.lib import footprints, parts


def test_footprints_have_unique_pad_numbers():
    for name, fp in footprints.FOOTPRINTS.items():
        nums = [p["num"] for p in fp["pads"]]
        assert len(nums) == len(set(nums)), f"{name}: duplicate pad numbers"


def test_no_footprint_has_overlapping_pads():
    bad = []
    for name, fp in footprints.FOOTPRINTS.items():
        pads = fp["pads"]
        for i in range(len(pads)):
            for j in range(i + 1, len(pads)):
                a, b = pads[i], pads[j]
                pa = geom.pad_outline(a["shape"], a["x"], a["y"], a["w"], a["h"], a["rot"], a["r"])
                pb = geom.pad_outline(b["shape"], b["x"], b["y"], b["w"], b["h"], b["rot"], b["r"])
                d = drc._poly_dist(pa, pb)
                if d <= 0.001:
                    bad.append((name, a["num"], b["num"], round(d, 3)))
    assert not bad, f"overlapping pads: {bad[:8]}"


def test_courtyard_covers_pads():
    bad = []
    for name, fp in footprints.FOOTPRINTS.items():
        cw, ch = fp["courtyard"]["w"], fp["courtyard"]["h"]
        if cw <= 0:
            continue
        for pad in fp["pads"]:
            if abs(pad["x"]) + pad["w"] / 2 > cw / 2 + 0.01:
                bad.append((name, pad["num"], "x"))
            if abs(pad["y"]) + pad["h"] / 2 > ch / 2 + 0.01:
                bad.append((name, pad["num"], "y"))
    assert not bad, f"pads outside courtyard: {bad[:8]}"


def test_every_part_matches_its_footprint():
    for pid, part in parts.CATALOG.items():
        fp = footprints.get(part["footprint"])
        pads = {p["num"] for p in fp["pads"]}
        assert set(part["pins"]) == pads, f"{pid}: pin map does not cover {fp['name']}"
        assert part["verified"] is True


def test_catalog_search():
    assert any(p["id"] == "r-0805" for p in parts.search("resistor"))
    assert all(p["category"] == "connector" for p in parts.search(category="connector"))
    assert parts.search("nope-nothing") == []


def test_oval_geometry_is_a_stadium():
    # 1.9 x 2.2 oval centred at origin: long axis 2.2, half-width 0.95
    assert geom.pad_contains("oval", 0, 1.09, 0, 0, 1.9, 2.2)
    assert not geom.pad_contains("oval", 0, 1.12, 0, 0, 1.9, 2.2)
    assert geom.pad_contains("oval", 0.9, 0, 0, 0, 1.9, 2.2)
    assert not geom.pad_contains("oval", 1.0, 0, 0, 0, 1.9, 2.2)
    # near the tip the stadium is rounded, not square
    assert not geom.pad_contains("oval", 0.9, 1.05, 0, 0, 1.9, 2.2)


def test_chamfer_shortens_an_L():
    pts = [(0, 0), (10, 0), (10, 10)]
    out = geom.chamfer_path(pts, 0.5)
    assert out[0] == (0, 0) and out[-1] == (10, 10)
    assert (9.5, 0) in [(round(x, 6), round(y, 6)) for x, y in out]
    assert (10, 0.5) in [(round(x, 6), round(y, 6)) for x, y in out]


def test_pad_distance_zero_inside():
    pad = {"shape": "rect", "x": 0, "y": 0, "w": 2, "h": 1, "rot": 0, "r": 0}
    assert geom.pad_distance_to_point(pad, 0, 0) == 0
    assert abs(geom.pad_distance_to_point(pad, 2.5, 0) - 1.5) < 1e-6
