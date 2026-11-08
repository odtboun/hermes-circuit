// Circuit — PCB designer for the Hermes desktop app.
//
// One file, SDK-only (no bundler, no external imports). It renders two views of
// the same board document served by `dashboard/plugin_api.py`:
//   * a 2D layer stackup drawn on canvas (copper / mask / silk / drills)
//   * a 3D extruded board with component bodies, orbit + zoom
// and exposes them as an inline transcript directive, a workspace page and a
// sidebar entry.

import {
  host,
  useQuery,
  useQueryClient,
  Button,
  Badge,
  EmptyState,
  GlyphSpinner,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  TRANSCRIPT_DIRECTIVE_AREA
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'circuit'
const ROUTE = '/circuit'

// Physical board colours (a PCB is green/copper regardless of the app theme).
// Tuned against real reference renders: a saturated green mask (not near-black),
// yellow-gold exposed copper, warm white silk. Traces are NOT bare copper — under
// mask they read as a lighter green than the substrate, which is what makes a
// render look like a fabricated board instead of an orange drawing.
const C = {
  substrate: '#14663a',
  substrateEdge: '#e0be6a',
  trace: '#4a9e70',
  traceBottom: '#2b6b4a',
  pad: '#f0d24a',
  padBottom: '#b8983c',
  silk: '#f6f2e6',
  drill: '#08110d',
  mask: '#0a3123',
  gold: '#f0d24a',
  body: '#1b2320',
  bodyEdge: '#39443d'
}

const PART_COLORS = {
  passive: '#2a2f2c',
  ic: '#14181a',
  module: '#16342c',
  connector: '#d7d2c4',
  electrolytic: '#243036',
  metal: '#8f8f8f',
  led: '#7a2f2f',
  relay: '#2c3a44',
  hole: '#000000',
  default: '#20262a'
}

const UI = {
  text: 'var(--ui-text, #e8e4d8)',
  dim: 'var(--ui-text-secondary, #9aa39c)',
  faint: 'var(--ui-text-quaternary, #6d776f)',
  stroke: 'var(--ui-stroke-secondary, rgba(255,255,255,0.12))',
  accent: 'var(--ui-accent, #7fc7a1)',
  panel: 'var(--ui-bg-secondary, rgba(255,255,255,0.03))'
}

// --------------------------------------------------------------------------- //
// data
// --------------------------------------------------------------------------- //
const rest = (ctx, path, opts) => ctx.rest(`/${path}`, opts)

function useBoards(ctx) {
  return useQuery({
    queryKey: [ID, 'boards'],
    queryFn: () => rest(ctx, 'boards'),
    refetchInterval: 6000,
    retry: 1
  })
}

function useBoard(ctx, slug) {
  return useQuery({
    queryKey: [ID, 'board', slug],
    queryFn: () => rest(ctx, `boards/${slug}`),
    enabled: Boolean(slug),
    retry: 1,
    staleTime: 2000
  })
}

// --------------------------------------------------------------------------- //
// small building blocks
// --------------------------------------------------------------------------- //
const dot = (color, size = 7) =>
  jsx('span', {
    style: {
      display: 'inline-block',
      width: size,
      height: size,
      borderRadius: 99,
      background: color,
      flex: '0 0 auto'
    }
  })

const chip = (label, active, onClick, swatch, key) =>
  jsx(
    'button',
    {
      type: 'button',
      onClick,
      'aria-pressed': active ? 'true' : 'false',
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        fontSize: 12,
        lineHeight: 1.3,
        borderRadius: 99,
        cursor: 'pointer',
        border: `1px solid ${active ? UI.accent : UI.stroke}`,
        background: active ? 'rgba(127,199,161,0.12)' : 'transparent',
        color: active ? UI.text : UI.dim
      },
      children: [
        swatch
          ? jsx(
              'span',
              { style: { width: 7, height: 7, borderRadius: 2, background: swatch, display: 'inline-block' } },
              'swatch'
            )
          : null,
        label
      ]
    },
    key
  )

const stat = (label, value) =>
  jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 64 },
    children: [
      jsx('div', { style: { fontSize: 11, color: UI.faint, letterSpacing: '0.04em', textTransform: 'uppercase' }, children: label }),
      jsx('div', { style: { fontSize: 15, fontWeight: 600, color: UI.text }, children: value })
    ]
  })

const panel = {
  border: `1px solid ${UI.stroke}`,
  borderRadius: 12,
  background: UI.panel
}

// --------------------------------------------------------------------------- //
// 2D renderer
// --------------------------------------------------------------------------- //
function drawPath(g, pts, close) {
  if (!pts || pts.length < 2) return
  g.beginPath()
  g.moveTo(pts[0][0], pts[0][1])
  for (let i = 1; i < pts.length; i += 1) g.lineTo(pts[i][0], pts[i][1])
  if (close) g.closePath()
}

function padPath(g, f) {
  const x = f.x
  const y = f.y
  g.beginPath()
  if (f.shape === 'round') {
    g.arc(x, y, f.w / 2, 0, Math.PI * 2)
    return
  }
  const rot = ((f.rot || 0) * Math.PI) / 180
  if (f.shape === 'oval') {
    g.save()
    g.translate(x, y)
    g.rotate(rot)
    g.ellipse(0, 0, f.w / 2, f.h / 2, 0, 0, Math.PI * 2)
    g.restore()
    return
  }
  if (!rot) {
    g.rect(x - f.w / 2, y - f.h / 2, f.w, f.h)
    return
  }
  g.save()
  g.translate(x, y)
  g.rotate(rot)
  g.rect(-f.w / 2, -f.h / 2, f.w, f.h)
  g.restore()
}

function drawBoard2D(g, view, opts) {
  const { width, height } = view.board
  const t = opts.transform
  const dpr = opts.dpr
  const canvas = opts.canvas
  g.setTransform(1, 0, 0, 1, 0, 0)
  g.clearRect(0, 0, canvas.width, canvas.height)
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.save()
  g.translate(t.ox, t.oy)
  g.scale(t.k, -t.k)

  const px = 1 / t.k // one screen pixel in world units
  const hotNet = opts.hotNet || null

  // substrate
  drawPath(g, view.outline, true)
  g.fillStyle = C.substrate
  // soft halo so the board lifts off the background instead of sitting flat —
  // the same trick reference renders get from layered drop-shadows
  g.save()
  g.shadowColor = 'rgba(126, 226, 176, 0.30)'
  g.shadowBlur = 26
  g.fill()
  g.restore()
  g.fill()
  // soft key-light falloff across the mask so a sparse board still reads as a
  // surface rather than a flat green fill (lighting only — no fake copper)
  const grad = g.createRadialGradient(
    width * 0.5,
    height * 0.42,
    0,
    width * 0.5,
    height * 0.42,
    Math.max(width, height) * 0.75
  )
  grad.addColorStop(0, 'rgba(255,255,255,0.075)')
  grad.addColorStop(1, 'rgba(0,0,0,0.22)')
  g.fillStyle = grad
  g.fill()
  g.lineWidth = Math.max(0.12, px * 1.2)
  g.strokeStyle = C.substrateEdge
  g.stroke()

  const layers = opts.layers
  const drawCopper = (layerId, traceColor, padColor, alpha) => {
    const layer = view.copper[layerId]
    if (!layer) return
    g.globalAlpha = alpha
    g.strokeStyle = traceColor
    g.fillStyle = padColor
    g.lineCap = 'round'
    g.lineJoin = 'round'
    for (const d of layer.draws) {
      const hot = hotNet && d.net === hotNet
      g.globalAlpha = hot ? 1 : alpha
      g.strokeStyle = hot ? UI.accent : traceColor
      g.lineWidth = d.width
      drawPath(g, d.points, false)
      g.stroke()
    }
    for (const f of layer.flashes) {
      const hot = hotNet && f.net === hotNet
      g.globalAlpha = hot ? 1 : alpha
      g.fillStyle = hot ? UI.accent : padColor
      padPath(g, f)
      g.fill()
      // Metal vs dielectric: plated copper gets a specular streak, the mask
      // stays glossy-but-diffuse. Only above ~5 px/mm, below that it is noise.
      if (!hot && t.k > 5) {
        g.save()
        g.globalAlpha = 0.32
        g.fillStyle = '#fffdf2'
        g.beginPath()
        g.arc(f.x - f.w * 0.12, f.y + f.h * 0.12, Math.max(0.08, Math.min(f.w, f.h) * 0.22), 0, Math.PI * 2)
        g.fill()
        g.restore()
      }
    }
    g.globalAlpha = 1
  }

  // mask tint sits on the substrate, under the copper artwork
  if (layers.mask) {
    drawPath(g, view.outline, true)
    g.globalAlpha = 0.5
    g.fillStyle = C.mask
    g.fill()
    g.globalAlpha = 1
  }

  if (layers.bottom) drawCopper('B.Cu', C.traceBottom, C.padBottom, 0.75)
  if (layers.top) drawCopper('F.Cu', C.trace, C.pad, 1)

  if (layers.silk) {
    for (const key of ['F.SilkS', 'B.SilkS']) {
      const layer = view.silk[key]
      if (!layer) continue
      g.strokeStyle = key === 'B.SilkS' ? '#9aa39c' : C.silk
      g.lineWidth = Math.max(0.1, px * 0.9)
      g.globalAlpha = key === 'B.SilkS' ? 0.55 : 0.95
      for (const ln of layer.lines) {
        drawPath(g, ln.points, false)
        g.stroke()
      }
      for (const tx of layer.text) {
        drawPath(g, tx.points, false)
        g.stroke()
      }
      g.globalAlpha = 1
    }
  }

  if (layers.drills) {
    g.fillStyle = C.drill
    for (const d of view.drills) {
      g.beginPath()
      g.arc(d.x, d.y, d.d / 2, 0, Math.PI * 2)
      g.fill()
    }
  }

  if (layers.parts) {
    g.globalAlpha = 0.9
    for (const c of view.components) {
      const b = c.body || { w: 0, h: 0 }
      if (!b.w || !b.h) continue
      g.save()
      g.translate(c.x, c.y)
      g.rotate((c.rot * Math.PI) / 180)
      g.strokeStyle = 'rgba(255,255,255,0.28)'
      g.lineWidth = Math.max(0.08, px * 0.8)
      g.setLineDash([0.5, 0.4])
      g.strokeRect(-b.w / 2, -b.h / 2, b.w, b.h)
      g.setLineDash([])
      g.restore()
      if (t.k > 9) {
        g.save()
        g.translate(c.x, c.y - (b.h / 2 + 1.4))
        g.fillStyle = 'rgba(255,255,255,0.55)'
        g.font = '10px ui-sans-serif, system-ui, sans-serif'
        g.textAlign = 'center'
        g.scale(1 / t.k, -1 / t.k)
        g.fillText(c.ref, 0, 0)
        g.restore()
      }
    }
    g.globalAlpha = 1
  }

  g.restore()
}

// --------------------------------------------------------------------------- //
// 3D renderer
// --------------------------------------------------------------------------- //
function rotMatrix(yaw, pitch) {
  const cy = Math.cos(yaw)
  const sy = Math.sin(yaw)
  const cp = Math.cos(pitch)
  const sp = Math.sin(pitch)
  // yaw around Z, then pitch around X
  const m = [
    [cy, -sy, 0],
    [sy * cp, cy * cp, -sp],
    [sy * sp, cy * sp, cp]
  ]
  return (p) => [
    m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2],
    m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2],
    m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2]
  ]
}

function facetsFor(view, opts) {
  const faces = []
  const th = view.board.thickness || 1.6
  const outline = view.outline || []
  const lift = opts.explode ? 6 : 0

  const pushPoly = (pts3, color, normalHint, liftAmount = 0, order = 0) => {
    if (!pts3 || pts3.length < 3) return
    faces.push({
      pts: pts3.map((p) => [p[0], p[1], p[2] + liftAmount]),
      color,
      n: normalHint,
      order
    })
  }

  // `order` is the paint pass, not a depth. A 2-layer board is a stack of
  // near-coplanar sheets (bottom, sides, top, traces, pads, bodies); sorting the
  // whole set by average depth cannot order those — a far pad ends up "behind"
  // the single big top face and gets buried. The orbit never goes under the
  // board (pitch is clamped, camera stays on +z), so a fixed stack is correct
  // for every reachable angle and only the bodies need a real depth sort.

  // substrate: bottom, sides, top
  pushPoly(outline.map((p) => [p[0], p[1], 0]), C.substrateEdge, [0, 0, -1], 0, 0)
  for (let i = 0; i < outline.length; i += 1) {
    const a = outline[i]
    const b = outline[(i + 1) % outline.length]
    const n = [b[1] - a[1], -(b[0] - a[0]), 0]
    pushPoly(
      [
        [a[0], a[1], 0],
        [b[0], b[1], 0],
        [b[0], b[1], th],
        [a[0], a[1], th]
      ],
      C.substrate,
      n,
      0,
      2
    )
  }
  pushPoly(outline.map((p) => [p[0], p[1], th]), C.substrate, [0, 0, 1], 0, 3)

  // copper traces as thin plates on each copper side
  for (const layerId of ['F.Cu', 'B.Cu']) {
    const layer = view.copper[layerId]
    if (!layer) continue
    const top = layerId === 'F.Cu'
    const z = top ? th + 0.01 : -0.01
    const color = top ? C.trace : C.traceBottom
    for (const d of layer.draws) {
      const pts = d.points || []
      const hw = Math.max(d.width || 0.2, 0.05) / 2
      for (let i = 0; i < pts.length - 1; i += 1) {
        const [x1, y1] = pts[i]
        const [x2, y2] = pts[i + 1]
        const len = Math.hypot(x2 - x1, y2 - y1) || 1e-6
        const nx = (-(y2 - y1) / len) * hw
        const ny = ((x2 - x1) / len) * hw
        pushPoly(
          [
            [x1 + nx, y1 + ny, z],
            [x2 + nx, y2 + ny, z],
            [x2 - nx, y2 - ny, z],
            [x1 - nx, y1 - ny, z]
          ],
          color,
          [0, 0, top ? 1 : -1],
          0,
          top ? 4 : 1
        )
      }
    }
  }

  // pads as thin plates on both copper sides
  for (const layerId of ['F.Cu', 'B.Cu']) {
    const layer = view.copper[layerId]
    if (!layer) continue
    const z = layerId === 'F.Cu' ? th + 0.02 : -0.02
    const color = layerId === 'F.Cu' ? C.pad : C.padBottom
    for (const f of layer.flashes) {
      const segs = f.shape === 'round' ? 12 : 4
      const pts = []
      const rot = ((f.rot || 0) * Math.PI) / 180
      for (let i = 0; i < segs; i += 1) {
        const a = (i / segs) * Math.PI * 2
        let lx = Math.cos(a) * (f.w / 2)
        let ly = Math.sin(a) * (f.h / 2)
        if (f.shape === 'round') {
          lx = Math.cos(a) * (f.w / 2)
          ly = Math.sin(a) * (f.w / 2)
        }
        const rx = lx * Math.cos(rot) - ly * Math.sin(rot)
        const ry = lx * Math.sin(rot) + ly * Math.cos(rot)
        pts.push([f.x + rx, f.y + ry, z])
      }
      pushPoly(pts, color, layerId === 'F.Cu' ? [0, 0, 1] : [0, 0, -1], 0, layerId === 'F.Cu' ? 5 : 1)
    }
  }

  // component bodies
  for (const comp of view.components) {
    const b = comp.body || {}
    if (!b.w || !b.h || !b.z) continue
    const rot = (comp.rot * Math.PI) / 180
    const hw = b.w / 2
    const hh = b.h / 2
    const corners = [
      [-hw, -hh],
      [hw, -hh],
      [hw, hh],
      [-hw, hh]
    ].map((p) => [
      comp.x + p[0] * Math.cos(rot) - p[1] * Math.sin(rot),
      comp.y + p[0] * Math.sin(rot) + p[1] * Math.cos(rot)
    ])
    const z0 = th + 0.06
    const z1 = z0 + b.z
    const color = PART_COLORS[b.color] || PART_COLORS.default
    pushPoly(corners.map((p) => [p[0], p[1], z1]), color, [0, 0, 1], lift, 6)
    for (let i = 0; i < 4; i += 1) {
      const p = corners[i]
      const q = corners[(i + 1) % 4]
      const n = [q[1] - p[1], -(q[0] - p[0]), 0]
      pushPoly(
        [
          [p[0], p[1], z0],
          [q[0], q[1], z0],
          [q[0], q[1], z1],
          [p[0], p[1], z1]
        ],
        color,
        n,
        lift,
        6
      )
    }
  }
  return faces
}

function drawBoard3D(g, view, opts) {
  const canvas = opts.canvas
  const dpr = opts.dpr
  g.setTransform(1, 0, 0, 1, 0, 0)
  g.clearRect(0, 0, canvas.width, canvas.height)
  g.setTransform(dpr, 0, 0, dpr, 0, 0)

  const w = canvas.width / dpr
  const h = canvas.height / dpr
  const cx = view.board.width / 2
  const cy = view.board.height / 2
  const rotate = rotMatrix(opts.yaw, opts.pitch)
  const dist = opts.dist
  const fov = Math.min(w, h) * 0.95

  const project = (p) => {
    const r = rotate([p[0] - cx, p[1] - cy, p[2] - (view.board.thickness || 1.6) / 2])
    // Camera on the +z side, looking down -z. With `dist + r[2]` the camera sat
    // BELOW the board, so the bottom face (z=0) was always nearer than the top
    // face (z=th) and painter-sorted over it — the whole top surface, its pads
    // and every component body were painted and then buried. The board rendered
    // as a bare gold slab with parts missing.
    const z = dist - r[2]
    if (z <= 0.2) return null
    const s = fov / z
    return [w / 2 + r[0] * s, h / 2 - r[1] * s, z]
  }

  const light = [0.32, 0.42, 0.85]
  const faces = facetsFor(view, opts)

  // Contact shadow: the board reads as a physical object on a surface rather
  // than a floating diagram. Drawn first so every face paints over it.
  const shadowPts = (view.outline || []).map((p) => project([p[0], p[1], 0]))
  if (shadowPts.length > 2 && !shadowPts.some((p) => p === null)) {
    g.save()
    g.beginPath()
    g.moveTo(shadowPts[0][0] + 10, shadowPts[0][1] + 16)
    for (let i = 1; i < shadowPts.length; i += 1) g.lineTo(shadowPts[i][0] + 10, shadowPts[i][1] + 16)
    g.closePath()
    g.filter = 'blur(14px)'
    g.fillStyle = 'rgba(0,0,0,0.45)'
    g.fill()
    g.filter = 'none'
    g.restore()
  }

  const prepared = []
  for (const f of faces) {
    const pts = f.pts.map(project)
    if (pts.some((p) => p === null)) continue
    const depth = pts.reduce((acc, p) => acc + p[2], 0) / pts.length
    prepared.push({ f, pts, depth })
  }

  // Fixed paint passes, far-to-near inside each (see facetsFor for why a single
  // global depth sort cannot order a stack of coplanar sheets).
  const passes = new Map()
  for (const item of prepared) {
    const key = item.f.order || 0
    if (!passes.has(key)) passes.set(key, [])
    passes.get(key).push(item)
  }
  const ordered = []
  for (const key of [...passes.keys()].sort((a, b) => a - b)) {
    ordered.push(...passes.get(key).sort((a, b) => b.depth - a.depth))
  }

  for (const item of ordered) {
    const { f, pts } = item
    const n = f.n || [0, 0, 1]
    const rn = rotate(n)
    // Normals arrive in board units, not normalized (a side face carries
    // [dy, -dx, 0], magnitude ~20 mm), so the raw dot product reached 5-7 and
    // every side face saturated to pure white over the pads and part bodies.
    const len = Math.hypot(rn[0], rn[1], rn[2]) || 1
    const lambert = Math.max(0, (rn[0] * light[0] + rn[1] * light[1] + rn[2] * light[2]) / len)
    // Lift the ambient term: at 0.5 the green mask and dark part bodies collapsed
    // into near-black, which read as "empty" next to reference renders.
    const shade = 0.68 + 0.32 * lambert
    g.beginPath()
    g.moveTo(pts[0][0], pts[0][1])
    for (let i = 1; i < pts.length; i += 1) g.lineTo(pts[i][0], pts[i][1])
    g.closePath()
    g.fillStyle = shadeColor(f.color, shade, opts.alpha || 1)
    g.fill()
    g.strokeStyle = 'rgba(0,0,0,0.18)'
    g.lineWidth = 0.6
    g.stroke()
  }
}

function shadeColor(hex, factor, alpha) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * factor))
  const gg = Math.min(255, Math.round(((n >> 8) & 255) * factor))
  const b = Math.min(255, Math.round((n & 255) * factor))
  return `rgba(${r},${gg},${b},${alpha})`
}

// --------------------------------------------------------------------------- //
// canvas component that owns pan / zoom / orbit
// --------------------------------------------------------------------------- //
function BoardCanvas({ view, mode, layers, hotNet, onHover, onPick, height, autoSpin }) {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const state = useRef({
    k: 1,
    ox: 0,
    oy: 0,
    yaw: -0.55,
    // Negative pitch looks DOWN on the board: the top face (soldermask, parts)
    // lands above the bottom face on screen, so the lamp in drawBoard3D lights
    // it instead of the underside. Positive pitch rendered the board from below.
    pitch: -0.95,
    dist: 120,
    drag: null,
    spin: true
  })
  const [ready, setReady] = useState(false)

  const fit2D = useCallback(() => {
    const wrap = wrapRef.current
    if (!wrap || !view) return
    const rect = wrap.getBoundingClientRect()
    const pad = 26
    const k = Math.min(
      (rect.width - pad) / (view.board.width + 6),
      (rect.height - pad) / (view.board.height + 6)
    )
    state.current.k = Math.max(0.6, k)
    state.current.ox = rect.width / 2 - (view.board.width / 2) * state.current.k
    state.current.oy = rect.height / 2 + (view.board.height / 2) * state.current.k
  }, [view])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap || !view) return
    const dpr = window.devicePixelRatio || 1
    const rect = wrap.getBoundingClientRect()
    const width = Math.max(80, Math.floor(rect.width))
    const hgt = Math.max(80, Math.floor(rect.height))
    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(hgt * dpr)) {
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(hgt * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${hgt}px`
      if (mode === '2d') fit2D()
    }
    const g = canvas.getContext('2d')
    if (mode === '2d') {
      drawBoard2D(g, view, {
        canvas,
        dpr,
        layers,
        hotNet,
        transform: { k: state.current.k, ox: state.current.ox, oy: state.current.oy }
      })
    } else {
      drawBoard3D(g, view, {
        canvas,
        dpr,
        explode: layers.explode,
        alpha: 1,
        yaw: state.current.yaw,
        pitch: state.current.pitch,
        dist: state.current.dist
      })
    }
  }, [view, mode, layers, hotNet, fit2D])

  useEffect(() => {
    fit2D()
    draw()
    setReady(true)
  }, [fit2D, draw])

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const ro = new ResizeObserver(() => draw())
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [draw])

  useEffect(() => {
    if (!autoSpin) return
    let raf = 0
    let last = performance.now()
    const tick = (now) => {
      const s = state.current
      if (mode === '3d' && s.spin && !s.drag) {
        s.yaw += (now - last) * 0.00012
        draw()
      }
      last = now
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [mode, draw, autoSpin])

  const toWorld = (clientX, clientY) => {
    const rect = wrapRef.current.getBoundingClientRect()
    const s = state.current
    return [
      (clientX - rect.left - s.ox) / s.k,
      -(clientY - rect.top - s.oy) / s.k
    ]
  }

  const onPointerDown = (e) => {
    const s = state.current
    s.drag = { x: e.clientX, y: e.clientY, ox: s.ox, oy: s.oy, yaw: s.yaw, pitch: s.pitch }
    s.spin = false
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e) => {
    const s = state.current
    if (!s.drag) {
      if (mode === '2d' && onHover) {
        const [wx, wy] = toWorld(e.clientX, e.clientY)
        onHover(wx, wy)
      }
      return
    }
    const dx = e.clientX - s.drag.x
    const dy = e.clientY - s.drag.y
    if (mode === '2d') {
      s.ox = s.drag.ox + dx
      s.oy = s.drag.oy + dy
    } else {
      // Both angles are anchored at the drag ORIGIN. Accumulating the running
      // delta into s.yaw/s.pitch on every pointermove multiplied the rotation by
      // the number of move events, so the same 100 px drag spun the board 5x or
      // 40x depending on the pointer's event rate.
      s.yaw = s.drag.yaw + dx * 0.01
      // Drag down raises pitch: the board follows the pointer. The sign was
      // inverted, so vertical drags fought the hand.
      s.pitch = Math.max(-1.35, Math.min(1.35, s.drag.pitch + dy * 0.008))
    }
    draw()
  }

  const onPointerUp = (e) => {
    state.current.drag = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch (err) {
      /* pointer already released */
    }
  }

  const onWheel = (e) => {
    e.preventDefault()
    const s = state.current
    if (mode === '2d') {
      const rect = wrapRef.current.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const factor = Math.exp(-e.deltaY * 0.0016)
      const k = Math.max(0.4, Math.min(40, s.k * factor))
      s.ox = mx - ((mx - s.ox) * k) / s.k
      s.oy = my - ((my - s.oy) * k) / s.k
      s.k = k
    } else {
      s.dist = Math.max(35, Math.min(420, s.dist * Math.exp(e.deltaY * 0.0012)))
    }
    draw()
  }

  const onClick = () => {
    if (mode === '2d' && onPick) onPick(null)
  }

  // React attaches `wheel` at the root as a PASSIVE listener, so the
  // preventDefault() inside a JSX onWheel handler is ignored: the page scrolls
  // instead of the board zooming and the console fills with warnings. Bind our
  // own non-passive listener on the canvas instead.
  const onWheelRef = useRef(onWheel)
  useEffect(() => {
    onWheelRef.current = onWheel
  })
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return undefined
    const handler = (e) => {
      e.preventDefault()
      onWheelRef.current(e)
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  return jsx('div', {
    ref: wrapRef,
    style: { position: 'relative', width: '100%', height: height || '100%', minHeight: 180, overflow: 'hidden' },
    children: jsx('canvas', {
      ref: canvasRef,
      style: { display: 'block', width: '100%', height: '100%', touchAction: 'none', cursor: state.current.drag ? 'grabbing' : 'grab' },
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onClick,
      role: 'img',
      'aria-label': view ? `${view.title} board preview` : 'board preview'
    })
  })
}

// --------------------------------------------------------------------------- //
// shared chrome
// --------------------------------------------------------------------------- //
function DrcBadge({ drc }) {
  if (!drc || drc.ok === undefined) {
    return jsx(Badge, { variant: 'muted', children: 'not checked' })
  }
  const errors = (drc.errors || []).length
  return jsx(Badge, {
    variant: errors ? 'destructive' : 'success',
    children: errors ? `${errors} DRC issue${errors === 1 ? '' : 's'}` : 'DRC clean'
  })
}

const LAYER_KEYS = [
  ['top', 'Top copper', C.trace],
  ['bottom', 'Bottom copper', C.traceBottom],
  ['silk', 'Silkscreen', C.silk],
  ['drills', 'Drills', '#000'],
  ['parts', 'Parts', '#888']
]

function LayerChips({ layers, setLayers, compact }) {
  return jsx('div', {
    style: { display: 'flex', gap: 6, flexWrap: 'wrap' },
    children: LAYER_KEYS.filter((k) => !(compact && k[0] === 'parts')).map(([key, label, color]) =>
      chip(label, layers[key], () => setLayers({ ...layers, [key]: !layers[key] }), color, key)
    )
  })
}

// --------------------------------------------------------------------------- //
// inline directive card
// --------------------------------------------------------------------------- //
function InlineBoard({ ctx, attrs }) {
  const slug = (attrs && attrs.board ? String(attrs.board) : '').trim()
  const boards = useBoards(ctx)
  const fallback = !slug && boards.data && boards.data.boards && boards.data.boards[0]
  const boardId = slug || (fallback ? fallback.slug : '')
  const query = useBoard(ctx, boardId)
  const [layers, setLayers] = useState({ top: true, bottom: true, silk: true, drills: true, parts: true })
  const [hot, setHot] = useState(null)
  const [hover, setHover] = useState(null)

  if (!boardId) {
    return jsx('div', { style: { ...panel, padding: 12, fontSize: 12, color: UI.dim }, children: 'No Circuit board yet — ask the agent to design one.' })
  }
  if (query.isLoading) {
    return jsxs('div', { style: { ...panel, padding: 14, display: 'flex', gap: 10, alignItems: 'center' }, children: [jsx(GlyphSpinner, {}), jsx('span', { style: { fontSize: 12, color: UI.dim }, children: 'Loading board…' })] })
  }
  if (query.error) {
    return jsxs('div', {
      style: { ...panel, padding: 12, fontSize: 12, color: UI.dim, display: 'flex', flexDirection: 'column', gap: 6 },
      children: [
        jsx('div', { style: { color: UI.text, fontWeight: 600 }, children: 'Circuit backend not reachable' }),
        jsx('div', { children: 'Enable the plugin (Settings → Plugins) so its API mounts, then reload the desktop plugins.' })
      ]
    })
  }
  const view = query.data
  const stats = view.stats || {}
  const nets = view.nets || []
  const routed = nets.filter((n) => n.routed).length

  const onHover = (wx, wy) => {
    let best = null
    let bestD = 1.6
    for (const comp of view.components) {
      for (const pin of comp.pins) {
        const d = Math.hypot(pin.x - wx, pin.y - wy)
        if (d < bestD) {
          bestD = d
          best = { ref: comp.ref, pin: pin.name, net: pin.net }
        }
      }
    }
    setHover(best)
  }

  return jsxs('div', {
    style: { ...panel, overflow: 'hidden', maxWidth: 720 },
    children: [
      jsxs('div', {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 12px 8px',
          borderBottom: `1px solid ${UI.stroke}`,
          flexWrap: 'wrap'
        },
        children: [
          jsx('div', { style: { fontSize: 13, fontWeight: 650, color: UI.text, letterSpacing: '-0.01em' }, children: view.title }),
          jsx('span', { style: { fontSize: 11.5, color: UI.faint }, children: `${view.board.width} × ${view.board.height} mm · ${view.board.layers}L` }),
          jsx(DrcBadge, { drc: view.drc }),
          jsx('div', { style: { flex: 1 } }),
          jsx(Button, {
            variant: 'secondary',
            size: 'sm',
            onClick: () => {
              ctx.storage.set('selected', boardId)
              host.navigate(ROUTE)
            },
            children: 'Open board'
          })
        ]
      }),
      jsx('div', {
        style: { position: 'relative', background: 'radial-gradient(120% 120% at 50% 0%, #0d1712 0%, #070a08 70%)' },
        children: jsx(BoardCanvas, {
          view,
          mode: '2d',
          layers,
          hotNet: hot,
          onHover,
          height: 300
        })
      }),
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderTop: `1px solid ${UI.stroke}`, flexWrap: 'wrap' },
        children: [
          jsx(LayerChips, { layers, setLayers, compact: true }),
          jsx('div', { style: { flex: 1 } }),
          jsx('span', { style: { fontSize: 11.5, color: UI.faint }, children: `${stats.components} parts · ${routed}/${nets.length} nets routed · ${stats.vias || 0} vias` }),
          hover && hover.net
            ? jsx('span', { style: { fontSize: 11.5, color: UI.accent }, children: `${hover.ref}.${hover.pin} → ${hover.net}` })
            : null
        ]
      })
    ]
  })
}

// --------------------------------------------------------------------------- //
// workspace page
// --------------------------------------------------------------------------- //
function NetRow({ net, active, onClick, onHover }) {
  const color = net.class === 'ground' ? '#8fb0a2' : net.class === 'power' ? '#d9a45f' : '#7fa8c9'
  return jsxs('button', {
    type: 'button',
    onClick,
    onMouseEnter: () => onHover(net.name),
    onMouseLeave: () => onHover(null),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      width: '100%',
      textAlign: 'left',
      padding: '5px 9px',
      borderRadius: 8,
      border: `1px solid ${active ? UI.accent : 'transparent'}`,
      background: active ? 'rgba(127,199,161,0.10)' : 'transparent',
      color: active ? UI.text : UI.dim,
      cursor: 'pointer',
      fontSize: 12
    },
    children: [
      dot(color, 6),
      jsx('span', { style: { flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: net.name }),
      jsx('span', { style: { fontSize: 10.5, color: UI.faint }, children: net.pins.length }),
      jsx('span', {
        style: { width: 6, height: 6, borderRadius: 99, background: net.routed ? '#6fbf8f' : '#c96a5a' }
      })
    ]
  })
}

function Table({ columns, rows }) {
  return jsxs('div', {
    style: { overflow: 'auto', ...panel },
    children: [
      jsxs('div', {
        style: {
          display: 'grid',
          gridTemplateColumns: columns.map((c) => c.width || '1fr').join(' '),
          gap: 8,
          padding: '8px 12px',
          borderBottom: `1px solid ${UI.stroke}`,
          fontSize: 10.5,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: UI.faint,
          position: 'sticky',
          top: 0,
          background: 'var(--ui-bg, #0f1311)'
        },
        children: columns.map((c) => jsx('div', { children: c.label }))
      }),
      ...rows.map((r, i) =>
        jsxs(
          'div',
          {
            style: {
              display: 'grid',
              gridTemplateColumns: columns.map((c) => c.width || '1fr').join(' '),
              gap: 8,
              padding: '6px 12px',
              fontSize: 12,
              color: i % 2 ? UI.dim : UI.text,
              borderBottom: `1px solid ${UI.stroke}`
            },
            children: columns.map((c) => jsx('div', { style: { overflow: 'hidden', textOverflow: 'ellipsis' }, children: r[c.key] }))
          },
          String(i)
        )
      )
    ]
  })
}

function emptyState(title, body) {
  return jsxs('div', {
    style: { ...panel, padding: 28, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, color: UI.dim },
    children: [
      jsx('div', { style: { fontSize: 14, fontWeight: 600, color: UI.text }, children: title }),
      jsx('div', { style: { fontSize: 12.5, maxWidth: 460, textAlign: 'center', lineHeight: 1.5 }, children: body })
    ]
  })
}

function BoardPage({ ctx }) {
  const list = useBoards(ctx)
  const [slug, setSlug] = useState(() => ctx.storage.get('selected', ''))
  const [tab, setTab] = useState('board')
  const [mode, setMode] = useState('2d')
  const [hot, setHot] = useState(null)
  const [layers, setLayers] = useState({ top: true, bottom: true, silk: true, drills: true, parts: true, explode: false })
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const query = useBoard(ctx, slug)
  const qc = useQueryClient()

  useEffect(() => {
    if (!slug && list.data && list.data.boards && list.data.boards.length) {
      const stored = ctx.storage.get('selected', '')
      const found = list.data.boards.find((b) => b.slug === stored)
      setSlug(found ? found.slug : list.data.boards[0].slug)
    }
  }, [list.data, slug, ctx])

  useEffect(() => {
    if (!ctx.onDispose) return undefined
    const off = host.onEvent('plugin.circuit.board.updated', () => {
      qc.invalidateQueries({ queryKey: [ID, 'boards'] })
      if (slug) qc.invalidateQueries({ queryKey: [ID, 'board', slug] })
    })
    return off
  }, [qc, slug])

  const pick = (next) => {
    setSlug(next)
    ctx.storage.set('selected', next)
    setNote('')
  }

  const rebuild = async () => {
    if (!slug) return
    setBusy(true)
    setNote('')
    try {
      const res = await rest(ctx, `boards/${slug}/rebuild`, { method: 'POST', timeoutMs: 120000 })
      setNote(res && res.ok ? 'Rebuilt — DRC clean' : 'Rebuilt — DRC still reports issues')
      qc.invalidateQueries({ queryKey: [ID, 'board', slug] })
      qc.invalidateQueries({ queryKey: [ID, 'boards'] })
    } catch (err) {
      setNote(`Rebuild failed: ${err && err.message ? err.message : err}`)
    } finally {
      setBusy(false)
    }
  }

  const view = query.data
  const boards = (list.data && list.data.boards) || []

  const sidebar = jsxs('div', {
    style: { width: 228, flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 6, borderRight: `1px solid ${UI.stroke}`, padding: 10, overflow: 'auto' },
    children: [
      jsxs('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '2px 2px 8px' }, children: [
        jsx('div', { style: { fontSize: 12, fontWeight: 650, letterSpacing: '0.02em', color: UI.text }, children: 'Boards' }),
        jsx('div', { style: { flex: 1 } }),
        jsx('span', { style: { fontSize: 11, color: UI.faint }, children: String(boards.length) })
      ] }),
      ...boards.map((b) =>
        jsxs(
          'button',
          {
            type: 'button',
            onClick: () => pick(b.slug),
            style: {
              textAlign: 'left',
              padding: '8px 10px',
              borderRadius: 10,
              border: `1px solid ${b.slug === slug ? UI.accent : UI.stroke}`,
              background: b.slug === slug ? 'rgba(127,199,161,0.10)' : 'transparent',
              color: UI.text,
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              gap: 3
            },
            children: [
              jsx('div', { style: { fontSize: 12.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: b.title }, 'title'),
              jsxs('div', { style: { fontSize: 11, color: UI.faint, display: 'flex', gap: 6, alignItems: 'center' }, children: [
                jsx('span', { children: `${b.board.width}×${b.board.height}` }),
                jsx('span', { children: '·' }),
                jsx('span', { children: `${b.components} parts` }),
                dot(b.drc_ok === true ? '#6fbf8f' : b.drc_ok === false ? '#c96a5a' : '#6d776f', 6)
              ] }, 'meta')
            ]
          },
          b.slug
        )
      ),
      boards.length === 0 && !list.isLoading
        ? jsx('div', { style: { fontSize: 12, color: UI.faint, padding: '8px 2px' }, children: 'No boards yet. Ask the agent to design one.' })
        : null
    ]
  })

  const header = jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${UI.stroke}`, flexWrap: 'wrap' },
    children: [
      jsx('div', { style: { fontSize: 14, fontWeight: 650, color: UI.text }, children: view ? view.title : 'Circuit' }),
      view ? jsx('span', { style: { fontSize: 11.5, color: UI.faint }, children: `${view.board.width} × ${view.board.height} mm · ${view.board.layers} layer · ${view.board.thickness} mm` }) : null,
      view ? jsx(DrcBadge, { drc: view.drc }) : null,
      jsx('div', { style: { flex: 1 } }),
      note ? jsx('span', { style: { fontSize: 11.5, color: UI.dim }, children: note }) : null,
      jsxs('div', { style: { display: 'flex', gap: 4, ...panel, padding: 3 }, children: [
        chip('2D', mode === '2d', () => setMode('2d')),
        chip('3D', mode === '3d', () => setMode('3d'))
      ] }),
      jsx(Button, { variant: 'secondary', size: 'sm', disabled: busy || !slug, onClick: rebuild, children: busy ? 'Rebuilding…' : 'Rebuild' })
    ]
  })

  const tabs = [
    ['board', 'Board'],
    ['nets', 'Nets'],
    ['bom', 'BOM'],
    ['drc', 'DRC'],
    ['files', 'Files']
  ]

  const tabBar = jsx('div', {
    style: { display: 'flex', gap: 4, padding: '8px 14px 0' },
    children: tabs.map(([key, label]) => chip(label, tab === key, () => setTab(key), undefined, key))
  })

  const statsRow = view
    ? jsx('div', { style: { display: 'flex', gap: 20, padding: '10px 14px', flexWrap: 'wrap' }, children: [
        stat('Parts', view.stats.components),
        stat('Nets', view.stats.nets),
        stat('Routed', `${(view.nets || []).filter((n) => n.routed).length}/${view.stats.nets}`),
        stat('Vias', view.stats.vias),
        stat('Pads', view.stats.pads),
        stat('Area', `${view.stats.area_mm2} mm²`)
      ] })
    : null

  let body = null
  if (query.isLoading) {
    body = jsxs('div', { style: { display: 'flex', gap: 10, alignItems: 'center', padding: 24, color: UI.dim }, children: [jsx(GlyphSpinner, {}), jsx('span', { children: 'Loading board…' })] })
  } else if (!slug) {
    body = emptyState('No board selected', 'Design one with the agent — “build me a Pico sensor hub” — then it appears here.')
  } else if (query.error) {
    body = emptyState('Circuit backend not reachable', 'Enable the Circuit plugin in Settings → Plugins so its API mounts, then reload desktop plugins.')
  } else if (view) {
    if (tab === 'board') {
      body = jsxs('div', { style: { display: 'flex', flex: 1, minHeight: 0 }, children: [
        jsxs('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }, children: [
          jsx('div', {
            style: { flex: 1, minHeight: 260, borderRadius: 12, overflow: 'hidden', border: `1px solid ${UI.stroke}`, background: 'radial-gradient(120% 120% at 50% 0%, #0d1712 0%, #070a08 70%)' },
            children: jsx(BoardCanvas, {
              view,
              mode,
              layers,
              hotNet: hot,
              onHover: (wx, wy) => {
                let best = null
                let bestD = 1.4
                for (const comp of view.components) {
                  for (const pin of comp.pins) {
                    const d = Math.hypot(pin.x - wx, pin.y - wy)
                    if (d < bestD) {
                      bestD = d
                      best = pin.net
                    }
                  }
                }
                setHot(best || null)
              },
              autoSpin: true
            })
          }),
          jsxs('div', { style: { display: 'flex', gap: 8, alignItems: 'center', paddingTop: 10, flexWrap: 'wrap' }, children: [
            jsx(LayerChips, { layers, setLayers }),
            chip('Explode', layers.explode, () => setLayers({ ...layers, explode: !layers.explode })),
            jsx('div', { style: { flex: 1 } }),
            jsx('span', { style: { fontSize: 11.5, color: hot ? UI.accent : UI.faint }, children: hot ? `net ${hot}` : mode === '2d' ? 'hover a pad · drag to pan · scroll to zoom' : 'drag to orbit · scroll to zoom' })
          ] })
        ] }),
        jsxs('div', { style: { width: 250, flex: '0 0 auto', marginLeft: 12, display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }, children: [
          jsxs('div', { style: { ...panel, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 2 }, children: [
            jsx('div', { style: { fontSize: 11, color: UI.faint, textTransform: 'uppercase', letterSpacing: '0.06em' }, children: 'Design' }),
            jsx('div', { style: { fontSize: 12, color: UI.dim }, children: view.rules ? `${view.rules.trace_width} mm trace · ${view.rules.clearance} mm clearance` : '' }),
            jsx('div', { style: { fontSize: 12, color: UI.dim }, children: `${view.board.finish} · ${view.board.soldermask} mask` })
          ] }),
          jsx('div', { style: { fontSize: 11, color: UI.faint, textTransform: 'uppercase', letterSpacing: '0.06em', padding: '4px 2px' }, children: 'Nets' }),
          jsx('div', { style: { overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2, minHeight: 0 }, children: (view.nets || []).map((n) =>
            jsx(NetRow, { net: n, active: hot === n.name, onClick: () => setHot(hot === n.name ? null : n.name), onHover: setHot }, n.name)
          ) })
        ] })
      ] })
    } else if (tab === 'nets') {
      body = jsx(Table, {
        columns: [
          { key: 'name', label: 'Net', width: '1.4fr' },
          { key: 'cls', label: 'Class', width: '0.8fr' },
          { key: 'width', label: 'Width', width: '0.7fr' },
          { key: 'count', label: 'Pads', width: '0.6fr' },
          { key: 'pins', label: 'Connections', width: '2.6fr' }
        ],
        rows: (view.nets || []).map((n) => ({
          name: n.name,
          cls: n.class,
          width: `${n.width} mm`,
          count: String(n.pins.length),
          pins: n.pins.join(', ')
        }))
      })
    } else if (tab === 'bom') {
      body = jsx(Table, {
        columns: [
          { key: 'refs', label: 'Refs', width: '1.1fr' },
          { key: 'qty', label: 'Qty', width: '0.4fr' },
          { key: 'value', label: 'Value', width: '0.8fr' },
          { key: 'part', label: 'Part', width: '1.4fr' },
          { key: 'footprint', label: 'Footprint', width: '1fr' }
        ],
        rows: (view.bom || []).map((r) => ({
          refs: r.refs.join(' '),
          qty: String(r.qty),
          value: r.value,
          part: r.part,
          footprint: r.footprint
        }))
      })
    } else if (tab === 'drc') {
      const d = view.drc || {}
      const rows = [
        ...(d.errors || []).map((e) => ({ level: 'error', text: e })),
        ...(d.warnings || []).map((w) => ({ level: 'warning', text: w }))
      ]
      body = rows.length
        ? jsx('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, overflow: 'auto' }, children: rows.map((r, i) =>
            jsxs('div', {
              style: { ...panel, padding: '8px 12px', display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: 12 },
              children: [
                dot(r.level === 'error' ? '#c96a5a' : '#d9a45f', 7),
                jsx('div', { style: { color: UI.text, lineHeight: 1.45 }, children: r.text })
              ]
            }, String(i))
          ) })
        : emptyState('No DRC issues', 'The board passes clearance, minimum width/drill, annular ring, edge clearance and full net connectivity.')
    } else {
      const files = Object.keys(view.files || {}).sort()
      body = files.length
        ? jsx(Table, {
            columns: [
              { key: 'path', label: 'File', width: '3fr' },
              { key: 'size', label: 'Size', width: '0.8fr' }
            ],
            rows: files.map((f) => ({ path: f, size: `${Math.max(1, Math.round((view.files[f].size || 0) / 102.4) / 10)} KB` }))
          })
        : emptyState('No fabrication files yet', 'Ask the agent to run circuit_export, or press Rebuild.')
    }
  }

  return jsxs('div', { style: { display: 'flex', height: '100%', minHeight: 0, color: UI.text }, children: [
    sidebar,
    jsxs('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }, children: [
      header,
      tabBar,
      statsRow,
      jsx('div', { style: { flex: 1, minHeight: 0, padding: '4px 14px 14px', display: 'flex', flexDirection: 'column' }, children: body })
    ] })
  ] })
}

// --------------------------------------------------------------------------- //
// plugin
// --------------------------------------------------------------------------- //
export default {
  id: ID,
  name: 'Circuit — PCB designer',
  defaultEnabled: false,
  register(ctx) {
    ctx.register({
      id: 'circuit.board',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: {
        name: 'circuit',
        render: ({ attrs }) => jsx(InlineBoard, { ctx, attrs })
      }
    })

    ctx.register({
      id: 'circuit.page',
      area: ROUTES_AREA,
      data: { path: ROUTE },
      render: () => jsx(BoardPage, { ctx })
    })

    ctx.register({
      id: 'circuit.nav',
      area: SIDEBAR_NAV_AREA,
      order: 40,
      data: { path: ROUTE, label: 'Circuit', codicon: 'circuit-board' }
    })

    ctx.register({
      id: 'circuit.palette',
      area: PALETTE_AREA,
      data: {
        id: 'circuit.open',
        label: 'Circuit: open the board viewer',
        run: () => host.navigate(ROUTE)
      }
    })
  }
}

// Exported for the Node test harness only; the loader uses `default`.
export const __test__ = { facetsFor, shadeColor, rotMatrix, drawBoard2D, drawBoard3D, InlineBoard, BoardPage, LAYER_KEYS, PART_COLORS }
