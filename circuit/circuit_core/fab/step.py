"""STEP (ISO 10303-21 / AP214) export.

The board is a real B-rep solid: the substrate is the board outline extruded
through the stackup thickness, and every component body is its own extruded
prism sitting on top. No faceted mesh, no external CAD kernel — the file is
written entity by entity and validated by a parser in the test suite.
"""

from __future__ import annotations

import math
import time
from typing import List, Sequence, Tuple

from .. import geom
from ..lib import footprints, parts
from ..project import Board

Point3 = Tuple[float, float, float]


class _Step:
    def __init__(self) -> None:
        self.entities: List[str] = []
        self.n = 0

    def add(self, body: str) -> int:
        self.n += 1
        self.entities.append(f"#{self.n}={body};")
        return self.n

    # primitives ----------------------------------------------------- #
    def point(self, p: Point3) -> int:
        return self.add(f"CARTESIAN_POINT('',({_f(p[0])},{_f(p[1])},{_f(p[2])}))")

    def direction(self, d: Point3) -> int:
        n = math.sqrt(sum(c * c for c in d)) or 1.0
        return self.add(f"DIRECTION('',({_f(d[0] / n)},{_f(d[1] / n)},{_f(d[2] / n)}))")

    def vertex(self, p: Point3) -> int:
        return self.add(f"VERTEX_POINT('',#{self.point(p)})")

    def line(self, a: Point3, b: Point3) -> int:
        d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        length = math.sqrt(sum(c * c for c in d)) or 1.0
        vector = s_add = self.add(
            "VECTOR('',#%d,%s)" % (self.direction(d), _f(length)))
        return self.add("LINE('',#%d,#%d)" % (self.point(a), vector))

    def edge(self, a: Point3, b: Point3) -> int:
        v1, v2 = self.vertex(a), self.vertex(b)
        return self.add(f"EDGE_CURVE('',#{v1},#{v2},#{self.line(a, b)},.T.)")

    def face(self, loop: Sequence[Point3], normal: Point3) -> int:
        """Planar face bounded by ``loop`` (already ordered CCW about normal)."""
        oriented = []
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            e = self.edge(a, b)
            oriented.append(self.add(f"ORIENTED_EDGE('',*,*,#{e},.T.)"))
        edge_loop = self.add(f"EDGE_LOOP('',({','.join(f'#{o}' for o in oriented)}))")
        bound = self.add(f"FACE_OUTER_BOUND('',#{edge_loop},.T.)")
        origin = loop[0]
        xdir = _sub(loop[1], loop[0])
        if abs(xdir[0]) + abs(xdir[1]) + abs(xdir[2]) < 1e-9:
            xdir = (1.0, 0.0, 0.0)
        axis = self.add(
            f"AXIS2_PLACEMENT_3D('',#{self.point(origin)},#{self.direction(normal)},"
            f"#{self.direction(xdir)})")
        plane = self.add(f"PLANE('',#{axis})")
        return self.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)")


def _f(v: float) -> str:
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0." if s in ("", "-0", "-") else s


def _sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _prism(s: _Step, poly: Sequence[geom.Point], z0: float, z1: float, name: str) -> int:
    pts = list(poly)
    if geom.polygon_area(pts) < 0:
        pts = list(reversed(pts))
    if geom.polygon_area(pts) == 0:
        return 0
    faces: List[int] = []
    top = [(x, y, z1) for x, y in pts]
    bottom = [(x, y, z0) for x, y in reversed(pts)]
    faces.append(s.face(top, (0, 0, 1)))
    faces.append(s.face(bottom, (0, 0, -1)))
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b[0] - a[0], b[1] - a[1])
        normal = (d[1], -d[0], 0.0)
        loop = [
            (a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1),
        ]
        faces.append(s.face(loop, normal))
    shell = s.add(f"CLOSED_SHELL('',({','.join(f'#{f}' for f in faces)}))")
    return s.add(f"MANIFOLD_SOLID_BREP('{name}',#{shell})")


def write_step(board: Board) -> str:
    s = _Step()
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    ctx = s.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    s.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{ctx})")
    pctx = s.add(f"PRODUCT_CONTEXT('',#{ctx},'mechanical')")
    product = s.add(f"PRODUCT('board','{_esc(board.data['title'])}','',(#{pctx}))")
    formation = s.add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{product},.NOT_KNOWN.)")
    dctx = s.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{ctx},'design')")
    definition = s.add(f"PRODUCT_DEFINITION('design','',#{formation},#{dctx})")
    shape = s.add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
    length = s.add("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    angle = s.add("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    solid_angle = s.add("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    uncertainty = s.add(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.001),#{length},'distance_accuracy_value','')")
    context = s.add(
        "(GEOMETRIC_REPRESENTATION_CONTEXT(3) "
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid_angle})) "
        "REPRESENTATION_CONTEXT('',''))")
    origin = s.add(f"AXIS2_PLACEMENT_3D('',#{s.point((0, 0, 0))},#{s.direction((0, 0, 1))},"
                   f"#{s.direction((1, 0, 0))})")

    solids: List[int] = []
    thickness = float(board.board["thickness"])
    board_solid = _prism(s, board.outline(10), 0.0, thickness, "substrate")
    if board_solid:
        solids.append(board_solid)

    for c in board.data["components"]:
        if c.get("x") is None:
            continue
        part = parts.get(c["part"])
        fp = footprints.get(part["footprint"])
        body = fp["body"]
        if body["w"] <= 0 or body["h"] <= 0 or body["z"] <= 0:
            continue
        hw, hh = body["w"] / 2.0, body["h"] / 2.0
        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        poly = [geom.place(p, c["x"], c["y"], c.get("rot", 0.0)) for p in local]
        z0 = thickness + 0.05
        solid = _prism(s, poly, z0, z0 + body["z"], c["ref"])
        if solid:
            solids.append(solid)

    rep = s.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('board',"
                f"({','.join(['#' + str(origin)] + ['#' + str(x) for x in solids])}),#{context})")
    s.add(f"SHAPE_DEFINITION_REPRESENTATION(#{shape},#{rep})")

    header = "\n".join([
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('Circuit PCB mechanical model'),'2;1');",
        f"FILE_NAME('{board.data.get('slug') or 'board'}.step','{now}',('Circuit'),(''),"
        "'circuit','circuit','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
        "ENDSEC;",
        "DATA;",
    ])
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    return header + "\n" + "\n".join(s.entities) + "\n" + footer


def _esc(text: str) -> str:
    return (text or "").replace("'", "''").replace("\n", " ")
