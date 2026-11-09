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
const PITCH_LIMIT = Math.PI - 0.02
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

// Part body colours, by material family. These are the real ones: black epoxy
// for ICs, dark grey-brown resistor bodies, tan MLCCs, silver aluminium cans,
// cream connector shells. Anything unknown stays a neutral dark grey.
const PART_COLORS = {
  passive: '#33302c',
  ceramic: '#8a6b4f',
  ic: '#1d1f21',
  module: '#16342c',
  connector: '#ddd8c8',
  electrolytic: '#b9bcc0',
  metal: '#b9bcc0',
  led: '#8a3a3a',
  relay: '#2c3a44',
  crystal: '#c8ccd0',
  header: '#1b1d1f',
  hole: '#000000',
  default: '#26282b'
}

// Plated metal: solder fillets, part terminations, connector pins.
const METAL = '#cfd3d8'

// The shadowed mouth of a connector shell (USB-C, RJ45, card slot).
const SLOT_INK = '#0a0c0b'

// --------------------------------------------------------------------------- //
// Package geometry: what a part actually looks like
// --------------------------------------------------------------------------- //
// A real 3D viewer loads a STEP/VRML model per footprint. Without a mesh
// renderer the honest win is procedural geometry driven by the package family
// and the footprint's own numbers: the right height (this is what reads as
// "wrong" when it is guessed), the right silhouette, the right material colour,
// and leads at the real pad positions. Every rule below is ordered specific to
// generic, because "CM5IO:SOT-23-6" must not match the module rule and
// "C_0402_1005Metric" must not match the 0402 resistor rule by accident.

// Nominal heights in mm above the board, from the package drawings (IPC-7351B
// nominal for the chip sizes; datasheet body heights elsewhere).
const CHIP_H = {
  '01005': 0.2, '0201': 0.23, '0402': 0.5, '0603': 0.55, '0805': 0.6,
  '1206': 0.65, '1210': 0.7, '1812': 0.8, '2010': 0.8, '2512': 0.9,
  '1005': 0.5, '1608': 0.55, '2012': 0.6, '3216': 0.65, '3225': 0.7,
  '4532': 0.8, '5025': 0.8, '6332': 0.9
}

// family, height (mm), material, silhouette, lead style
const PACKAGE_RULES = [
  // board features with no body of their own
  { re: /stitching[-_ ]?via|^via[_-]|stitch\d/i, family: 'via', z: 0, shape: 'none' },
  { re: /solder[-_ ]?jumper|solder[-_ ]?bridge|nettie|net[-_ ]?tie/i, family: 'flat', z: 0, shape: 'none' },
  { re: /mounting[-_ ]?hole|mountinghole/i, family: 'hole', z: 0, shape: 'none' },
  { re: /fiducial|fid\b/i, family: 'fiducial', z: 0, shape: 'none' },
  { re: /testpoint_tht|test[-_ ]?point[-_ ]?tht/i, family: 'testpost', z: 1.2, color: 'metal', shape: 'cylinder', lead: 'tht' },
  { re: /testpoint|test[-_ ]?point|pad_d\d/i, family: 'testpoint', z: 0, shape: 'none' },

  // connectors, most specific first
  { re: /usb[_-]?c|typec|type[_-]?c|usb4\d{3}/i, family: 'usb-c', z: 3.3, color: 'metal', shape: 'chamfer', slot: 0.42 },
  { re: /usb[_-]?a\b|usba\b/i, family: 'usb-a', z: 13.5, color: 'metal', shape: 'rect', slot: 0.4 },
  { re: /micro[_-]?usb|mini[_-]?usb/i, family: 'usb-mini', z: 2.5, color: 'metal', shape: 'chamfer', slot: 0.35 },
  { re: /rj45|magjack|ethernet|8p8c/i, family: 'rj45', z: 13.6, color: 'connector', shape: 'rect', slot: 0.3 },
  { re: /hdmi|displayport|micro[_-]?hdmi/i, family: 'hdmi', z: 6.0, color: 'metal', shape: 'rect', slot: 0.3 },
  { re: /sd[-_ ]?card|microsd|tf[-_ ]?card|sim[-_ ]?card/i, family: 'card', z: 2.8, color: 'metal', shape: 'rect', slot: 0.28 },
  { re: /m\.2|m2[-_ ]?(key|socket)/i, family: 'm2', z: 4.2, color: 'metal', shape: 'rect', slot: 0.22 },
  { re: /hirose|fpc|ffc|zif|jst|ph\d|sh[_-]|sur\b|bm\d|sm\d|molex|picoblade/i, family: 'fpc', z: 2.4, color: 'connector', shape: 'rect' },
  { re: /barrel|dc[-_ ]?jack|power[-_ ]?jack/i, family: 'barrel', z: 11, color: 'header', shape: 'cylinder' },
  { re: /screw[-_ ]?terminal|terminal[-_ ]?block|edac|phoenix|dg\d{2}/i, family: 'terminal', z: 10, color: 'header', shape: 'rect' },
  { re: /sma\b|bnc\b|u\.fl|ipex|mhf/i, family: 'rf', z: 10, color: 'metal', shape: 'cylinder', lead: 'tht' },
  { re: /audio|trrs|headphone|jack\b/i, family: 'audio', z: 5, color: 'header', shape: 'rect', slot: 0.3 },

  // headers: plastic body, posts standing out of it
  { re: /pin[-_ ]?header|pin[-_ ]?socket|header|idc|box[-_ ]?header/i, family: 'header', z: 2.5, color: 'header', shape: 'rect', lead: 'post', postZ: 8.5 },

  // electromechanical
  { re: /relay|srd|g5v|omron|tq2/i, family: 'relay', z: 15, color: 'relay', shape: 'rect', lead: 'tht' },
  { re: /buzzer|speaker/i, family: 'buzzer', z: 9.5, color: 'header', shape: 'cylinder', lead: 'tht' },
  { re: /tact|push[-_ ]?button|pushbutton|switch|sw[-_ ]?\d/i, family: 'switch', z: 1.5, color: 'header', shape: 'rect' },
  { re: /trimmer|potentiometer|\bpot\b/i, family: 'pot', z: 2.2, color: 'header', shape: 'rect' },
  { re: /battery|coin[-_ ]?cell|cr20\d\d|holder/i, family: 'battery', z: 5.0, color: 'metal', shape: 'cylinder' },
  { re: /shield|rf[-_ ]?can/i, family: 'shield', z: 2.5, color: 'metal', shape: 'chamfer' },

  // discrete semiconductors
  { re: /sot[_-]?223|dpak|d2pak|to[_-]?252/i, family: 'sot223', z: 1.8, color: 'ic', shape: 'chamfer', lead: 'gullwing' },
  { re: /sot[_-]?89/i, family: 'sot89', z: 1.5, color: 'ic', shape: 'chamfer', lead: 'gullwing' },
  { re: /sot[_-]?416|sc[_-]?70|sot[_-]?323|sot[_-]?363|sot[_-]?563/i, family: 'sot323', z: 0.9, color: 'ic', shape: 'chamfer', lead: 'gullwing' },
  { re: /sot[_-]?23|sot[_-]?143/i, family: 'sot23', z: 1.1, color: 'ic', shape: 'chamfer', lead: 'gullwing' },
  { re: /to[_-]?220|to[_-]?247|to[_-]?263/i, family: 'to220', z: 9.0, color: 'ic', shape: 'rect', lead: 'tab' },
  { re: /to[_-]?92|to[_-]?126/i, family: 'to92', z: 4.5, color: 'ic', shape: 'cylinder', lead: 'tht' },
  { re: /sod[_-]?323|sod[_-]?523|sod[_-]?123|smf/i, family: 'sod', z: 0.9, color: 'ic', shape: 'rect' },
  { re: /sma\b|smb\b|smc\b|do[_-]?214/i, family: 'smx', z: 2.3, color: 'ic', shape: 'chamfer' },
  { re: /melf/i, family: 'melf', z: 1.4, color: 'passive', shape: 'cylinder', lead: 'axial' },

  // ICs: qfn before qfp, tssop before soic
  { re: /wlcsp|\bcsp\b|bga/i, family: 'bga', z: 1.2, color: 'ic', shape: 'rect', lead: 'nolead' },
  { re: /uson|son\b|xdfn/i, family: 'uson', z: 0.55, color: 'ic', shape: 'chamfer', lead: 'nolead' },
  { re: /qfn|dfn/i, family: 'qfn', z: 0.9, color: 'ic', shape: 'chamfer', lead: 'nolead' },
  { re: /tqfp|lqfp|qfp|pqfp/i, family: 'qfp', z: 1.4, color: 'ic', shape: 'chamfer', lead: 'gullwing' },
  { re: /tssop|msop|vssop|qsop|ssop/i, family: 'tssop', z: 1.1, color: 'ic', shape: 'rect', lead: 'gullwing' },
  { re: /soic|so[_-]?\d|sop\b|sop[_-]?\d/i, family: 'soic', z: 1.6, color: 'ic', shape: 'rect', lead: 'gullwing' },
  { re: /dip|pdip|sdip/i, family: 'dip', z: 4.0, color: 'ic', shape: 'rect', lead: 'tht' },

  // passives: tantalum before electrolytic (CP_EIA-3528 is a tantalum)
  { re: /tantal|t49\d|eia[_-]?3528|eia[_-]?3216|eia[_-]?7343|eia[_-]?6032/i, family: 'tantalum', z: 2.0, color: 'ceramic', shape: 'chamfer' },
  { re: /\bcp[_-]|electrolyt|alu[-_ ]?can|radial|_can\b/i, family: 'electrolytic', z: 6.0, color: 'electrolytic', shape: 'cylinder', lead: 'tht' },
  { re: /crystal|xtal|resonator|hc[_-]?49/i, family: 'crystal', z: 1.0, color: 'crystal', shape: 'chamfer' },
  { re: /inductor|coil|ferrite|\bl[_-]\d|srn\d|xal\d/i, family: 'inductor', z: 1.2, color: 'passive', shape: 'chamfer' },
  { re: /led|ws2812|neopixel/i, family: 'led', z: 0.8, color: 'led', shape: 'dome' },

  // modules: whole boards sitting on the board
  { re: /compute[-_ ]?module|cm[45]\b|pico|nano|module|arduino|feather|esp32|wroom|rp2040/i, family: 'module', z: 6.0, color: 'module', shape: 'rect', lead: 'castellated' },

  // generic passives by family word, height from the size code
  { re: /cap|capacitor|\bc[_-]\d/i, family: 'chip', z: null, color: 'ceramic', shape: 'rect' },
  { re: /res|resistor|\br[_-]\d/i, family: 'chip', z: null, color: 'passive', shape: 'rect' }
]

/** Last-resort family from the reference designator, for footprints whose name
 *  is a vendor part number (…:434121025816 with ref SW1). */
function refFallback(comp) {
  const ref = String(comp.ref || '')
  const pins = (comp.pins || []).length
  const table = [
    [/^SW\d/i, { family: 'switch', z: pins > 4 ? 3.0 : 1.5, color: 'header', shape: 'rect' }],
    [/^K\d/i, { family: 'relay', z: 15, color: 'relay', shape: 'rect', lead: 'tht' }],
    [/^Y\d|^X\d/i, { family: 'crystal', z: 1.0, color: 'crystal', shape: 'chamfer' }],
    [/^F\d/i, { family: 'fuse', z: 1.2, color: 'ic', shape: 'rect' }],
    [/^D\d/i, { family: 'diode', z: 0.9, color: 'ic', shape: 'rect' }],
    [/^Q\d/i, { family: 'sot23', z: 1.1, color: 'ic', shape: 'chamfer', lead: 'gullwing' }],
    [/^J\d|^P\d|^CN\d|^CON\d/i, { family: 'connector', z: pins >= 8 ? 3.0 : 4.5, color: 'connector', shape: 'rect' }],
    [/^LS\d|^SP\d/i, { family: 'buzzer', z: 9.5, color: 'header', shape: 'cylinder', lead: 'tht' }],
    [/^BT\d|^BAT\d/i, { family: 'battery', z: 5.0, color: 'metal', shape: 'cylinder' }],
    [/^U\d/i, { family: 'ic', z: 1.2, color: 'ic', shape: 'rect', lead: pins > 8 ? 'gullwing' : 'none' }]
  ]
  for (const [re, shape] of table) {
    if (re.test(ref)) {
      return { ...shape, lead: shape.lead || 'none', pitch: null, postZ: 0, slot: 0, pins }
    }
  }
  return null
}

function chipHeight(name) {
  const m = /(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512|1005|1608|2012|3216|3225|4532|5025|6332)/.exec(name)
  return m ? CHIP_H[m[1]] || 0.55 : 0.55
}

/** Everything the renderers need to know about how a part is built.
 *  Memoised per component object: the 3D pass runs on every pointermove. */
const PKG_CACHE = typeof WeakMap === 'function' ? new WeakMap() : null
function parsePackage(comp) {
  if (PKG_CACHE && PKG_CACHE.has(comp)) return PKG_CACHE.get(comp)
  const prof = parsePackageUncached(comp)
  if (PKG_CACHE) PKG_CACHE.set(comp, prof)
  return prof
}

function parsePackageUncached(comp) {
  const key = `${comp.footprint || ''} ${comp.part || ''} ${comp.value || ''}`
  const b = comp.body || {}
  const pins = comp.pins || []
  let rule = null
  for (const r of PACKAGE_RULES) {
    if (r.re.test(key)) { rule = r; break }
  }
  if (!rule) {
    // No package name matched. A reference designator prefix is still a strong
    // hint (SW1 is a switch, TP3 a test point), so use it before giving up.
    const byRef = refFallback(comp)
    if (byRef) return byRef
    // Otherwise fall back to the engine's own body box, which is still better
    // than a fixed slab.
    return {
      family: 'other',
      z: Math.max(0.3, b.z || 1),
      color: b.color || 'default',
      shape: 'rect',
      lead: pins.length > 2 ? 'gullwing' : 'none',
      pitch: null,
      pins: pins.length
    }
  }
  const prof = {
    family: rule.family,
    z: rule.z == null ? chipHeight(key) : rule.z,
    color: rule.color || (rule.family === 'chip' ? 'passive' : 'default'),
    shape: rule.shape || 'rect',
    lead: rule.lead || 'none',
    pitch: parsePitch(key),
    postZ: rule.postZ || 0,
    slot: rule.slot || 0,
    pins: pins.length
  }
  // Small overrides that need a number from the footprint name.
  // These run against upper-case footprint names, so every pattern is /i.
  if (prof.family === 'crystal' && /3225|3215/i.test(key)) prof.z = 0.8
  if (prof.family === 'crystal' && /5032|4532/i.test(key)) prof.z = 1.0
  if (prof.family === 'crystal' && /hc-?49/i.test(key)) prof.z = 3.5
  if (prof.family === 'led' && /0402|1005|l1\.0|l1\.1/i.test(key)) prof.z = 0.45
  if (prof.family === 'led' && /0603|1608|l1\.6|l1\.7/i.test(key)) prof.z = 0.6
  if (prof.family === 'led' && /1206|3216|l2\.0|l3\.2/i.test(key)) prof.z = 0.9
  if (prof.family === 'fpc' && /sh_|sh-/i.test(key)) prof.z = 2.9
  if (prof.family === 'fpc' && /sur_|sur-/i.test(key)) prof.z = 1.3
  if (prof.family === 'tantalum' && /3216/i.test(key)) prof.z = 1.6
  if (prof.family === 'tantalum' && /3528/i.test(key)) prof.z = 1.9
  if (prof.family === 'tantalum' && /7343/i.test(key)) prof.z = 3.0
  if (prof.family === 'qfn' && /dfn2\d{3}|dfn_?2|uson2/i.test(key)) prof.z = 0.6
  if (prof.family === 'inductor' && /xal\d{4}/i.test(key)) prof.z = 3.0
  if (prof.family === 'inductor' && /srn\d{4}|srp\d{4}/i.test(key)) prof.z = 3.0
  if (prof.family === 'sot23' && /sot-?416|sc-?70|sot-?323/i.test(key)) prof.z = 0.9
  if (prof.family === 'header') {
    // A pin SOCKET has no pins standing up — the tall plastic body is the part,
    // with a hole per pin. A male pin HEADER is a 2.5 mm plastic block with 8.5 mm
    // pins through it. An SMD header is just the block: its pins are flat pads.
    // Treating all three as "male header" put 8.5 mm grey posts on every socket,
    // which is what the "grey sticks" were on tiny-tapeout's PMOD connectors.
    const socket = /socket|receptacle|female/i.test(key)
    const smd = pins.length > 0 && pins.every((pin) => (pin.kind || 'tht') !== 'tht')
    if (socket) {
      prof.z = 8.5
      prof.lead = 'holes'
      prof.holeR = Math.min(0.6, Math.max(0.35, (prof.pitch || 2.54) * 0.2))
    } else if (smd) {
      prof.z = 2.5
      prof.lead = 'none'
    } else {
      prof.z = 2.5
      prof.lead = 'post'
      prof.postZ = 8.5
    }
  }
  return prof
}

/** Pad pitch in mm, from a footprint name like …_P0.50mm_Vertical. */
function parsePitch(name) {
  const m = /[_-]p(\d+(?:\.\d+)?)\s?mm/i.exec(name)
  return m ? parseFloat(m[1]) : null
}

/** Resolved body colour: the inferred family wins, then the engine's own hint. */
function bodyColor(comp, prof) {
  return PART_COLORS[prof.color] || PART_COLORS[(comp.body || {}).color] || PART_COLORS.default
}

/** Ink that reads on top of a body colour (etched marking / designator). */
function inkFor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return '#101312'
  const n = parseInt(m[1], 16)
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)
  return lum > 128 ? '#101312' : '#e9ecea'
}

/** Body outline in world mm. Rectangle, chamfered rectangle, rounded rectangle
 *  or a true circle, by package family — a SOT is not a cube and an electrolytic
 *  is not a box. */
function packageSilhouette(comp, prof) {
  const b = comp.body || {}
  const rot = ((comp.rot || 0) * Math.PI) / 180
  const cos = Math.cos(rot)
  const sin = Math.sin(rot)
  const hw = b.w / 2
  const hh = b.h / 2
  const put = (lx, ly) => [comp.x + lx * cos - ly * sin, comp.y + lx * sin + ly * cos]
  const out = []
  const shape = prof.shape || 'rect'

  if (shape === 'cylinder') {
    // Inscribed 16-gon: at PCB scale a circle reads as a circle.
    for (let i = 0; i < 16; i += 1) {
      const a = (i / 16) * Math.PI * 2 + Math.PI / 16
      out.push(put(Math.cos(a) * hw, Math.sin(a) * hh))
    }
    return out
  }

  if (shape === 'chamfer') {
    const c = Math.min(Math.min(b.w, b.h) * 0.16, 0.55)
    const pts = [
      [-hw + c, -hh], [hw - c, -hh], [hw, -hh + c], [hw, hh - c],
      [hw - c, hh], [-hw + c, hh], [-hw, hh - c], [-hw, -hh + c]
    ]
    for (const [lx, ly] of pts) out.push(put(lx, ly))
    return out
  }

  if (shape === 'dome') {
    // LED: a rounded body, the lens is added as a second solid by facetsFor.
    const r = Math.min(hw, hh) * 0.55
    const n = 12
    for (let i = 0; i < n; i += 1) {
      const a = (i / n) * Math.PI * 2 + Math.PI / n
      out.push(put(Math.cos(a) * (hw - r) + Math.cos(a) * r, Math.sin(a) * (hh - r) + Math.sin(a) * r))
    }
    return out
  }

  for (const [lx, ly] of [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]]) out.push(put(lx, ly))
  return out
}

/** A lighter hex shade of a hex colour (for LED lenses, plastic highlights). */
function lightenHex(hex, factor) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * factor))
  const gg = Math.min(255, Math.round(((n >> 8) & 255) * factor))
  const b = Math.min(255, Math.round((n & 255) * factor))
  return `#${((1 << 24) | (r << 16) | (gg << 8) | b).toString(16).slice(1)}`
}

/** Outward direction of a pin, snapped to the component's own axes. */
function pinOutward(comp, pin) {
  const rot = ((comp.rot || 0) * Math.PI) / 180
  const dx = pin.x - comp.x
  const dy = pin.y - comp.y
  const lx = dx * Math.cos(rot) + dy * Math.sin(rot)
  const ly = -dx * Math.sin(rot) + dy * Math.cos(rot)
  if (Math.abs(lx) >= Math.abs(ly)) return [Math.sign(lx) || 1, 0]
  return [0, Math.sign(ly) || 1]
}

/** Metal for a part, in board mm: the visible terminations.

 *  Returns boxes — { quad, z0, z1, color } — so the 3D pass turns each into a
 *  prism and the 2D pass fills the same quad. A gull-wing lead is a low strip
 *  from under the body out to the pad end; a no-lead part gets a side pad
 *  notch; a through-hole part gets a post; a header gets square pins standing
 *  out of its plastic body.
 */
function packageLeads(comp, prof) {
  const b = comp.body || {}
  const pins = comp.pins || []
  const style = prof.lead || 'none'
  const out = []
  if (style === 'none' || !b.w || !b.h || !pins.length) return out
  const rot = ((comp.rot || 0) * Math.PI) / 180
  const cos = Math.cos(rot)
  const sin = Math.sin(rot)
  const z0 = 0.02
  for (const pin of pins) {
    const [ux, uy] = pinOutward(comp, pin)
    const wx = ux * cos - uy * sin
    const wy = ux * sin + uy * cos
    const vx = -wy
    const vy = wx
    // half extents of the pad along the outward axis and across it
    const pu = (Math.abs(wx) * (pin.w || 0.5) + Math.abs(wy) * (pin.h || 0.5)) / 2
    const pv = (Math.abs(vx) * (pin.w || 0.5) + Math.abs(vy) * (pin.h || 0.5)) / 2
    const bu = (Math.abs(wx) * b.w + Math.abs(wy) * b.h) / 2
    const at = (u, v) => [pin.x + wx * u + vx * v, pin.y + wy * u + vy * v]
    // Distance from the pin centre to the body edge, along the outward axis.
    // Measured from the PIN, not from the component centre: a pin on a SOIC sits
    // 0.75 mm outside the body edge, not 2 mm, and a lead that starts at the
    // centre-relative half-extent floats in the middle of nowhere.
    const offU = (pin.x - comp.x) * wx + (pin.y - comp.y) * wy
    const edge = -Math.max(0.05, offU - bu)

    if (style === 'gullwing') {
      const inner = edge
      const outer = pu
      if (outer - inner < 0.08) continue
      const wv = Math.max(0.12, pv * 0.8)
      out.push({
        quad: [at(inner, -wv), at(inner, wv), at(outer, wv), at(outer, -wv)],
        z0,
        z1: z0 + Math.min(0.32, Math.max(0.12, (prof.z || 1) * 0.22)),
        color: 'metal'
      })
    } else if (style === 'nolead' || style === 'castellated') {
      const wv = Math.max(0.1, Math.min(pv * 0.9, (prof.pitch || 0.5) * 0.5))
      const inner = -Math.max(0.02, offU - bu) - 0.04
      const outer = -Math.max(0.02, offU - bu) + (style === 'castellated' ? 0.18 : 0.1)
      out.push({
        quad: [at(inner, -wv), at(inner, wv), at(outer, wv), at(outer, -wv)],
        z0: style === 'castellated' ? z0 : z0 + 0.06,
        z1: style === 'castellated' ? Math.min(prof.z, 0.9) : Math.max(0.2, prof.z - 0.12),
        color: 'metal'
      })
    } else if (style === 'tht') {
      // A through-hole pin goes *under* the board: from above you see the solder
      // fillet and nothing else. Drawing it as a post up to 90% of the body
      // height put a grey cylinder standing next to every relay and can — one of
      // the "grey sticks" on THT-heavy boards.
      const r = Math.max(0.25, Math.min(0.6, ((pin.drill || 0.8) / 2) * 1.6))
      const n = 8
      const quad = []
      for (let i = 0; i < n; i += 1) {
        const a = (i / n) * Math.PI * 2 + Math.PI / n
        quad.push([pin.x + Math.cos(a) * r, pin.y + Math.sin(a) * r])
      }
      out.push({ quad, z0, z1: z0 + 0.35, color: 'metal' })
    } else if (style === 'post') {
      const half = 0.32
      out.push({
        quad: [
          [pin.x - half, pin.y - half], [pin.x + half, pin.y - half],
          [pin.x + half, pin.y + half], [pin.x - half, pin.y + half]
        ],
        z0,
        z1: prof.postZ || 8.5,
        color: 'metal'
      })
    } else if (style === 'axial') {
      const inner = edge
      const wv = Math.max(0.1, pv * 0.7)
      out.push({
        quad: [at(inner, -wv), at(inner, wv), at(pu, wv), at(pu, -wv)],
        z0: z0 + (prof.z || 1) * 0.25,
        z1: z0 + (prof.z || 1) * 0.55,
        color: 'metal'
      })
    } else if (style === 'tab') {
      const wv = Math.max(0.4, pv * 1.4)
      out.push({
        quad: [at(edge, -wv), at(edge, wv), at(pu, wv), at(pu, -wv)],
        z0: z0 + 0.1,
        z1: z0 + 0.4,
        color: 'metal'
      })
    }
  }
  return out
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

  // Opaque, like the top. The bottom side used to be drawn at 75% alpha so both
  // sides were visible at once, but a see-through trace reads as a rendering
  // bug; the darker bottom colours already separate the two sides, and the
  // layer chips hide either side outright.
  if (layers.bottom) drawCopper('B.Cu', C.traceBottom, C.padBottom, 1)
  if (layers.top) drawCopper('F.Cu', C.trace, C.pad, 1)

  if (layers.silk) {
    for (const key of ['F.SilkS', 'B.SilkS']) {
      const layer = view.silk[key]
      if (!layer) continue
      g.strokeStyle = key === 'B.SilkS' ? '#9aa39c' : C.silk
      g.lineWidth = Math.max(0.1, px * 0.9)
      // 0.55 alpha on bottom silk was the other see-through element: silk is
      // printed ink, it is opaque from either side.
      g.globalAlpha = 1
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
    const polyFill = (poly, color) => {
      g.beginPath()
      g.moveTo(poly[0][0], poly[0][1])
      for (let i = 1; i < poly.length; i += 1) g.lineTo(poly[i][0], poly[i][1])
      g.closePath()
      g.fillStyle = color
      g.fill()
    }
    for (const c of view.components) {
      const b = c.body || { w: 0, h: 0 }
      if (!b.w || !b.h) continue
      const prof = parsePackage(c)
      const color = bodyColor(c, prof)
      if (prof.shape !== 'none') {
        const poly = packageSilhouette(c, prof)
        // Opaque: a translucent body let the copper and silk show through it,
        // which reads as a mistake, not as depth.
        polyFill(poly, color)
        g.strokeStyle = 'rgba(0,0,0,0.38)'
        g.lineWidth = Math.max(0.06, px * 0.7)
        g.stroke()
        // connector mouth: a dark slot at the front face, in plan view
        if (prof.slot) {
          const quad = localQuad(c, -b.w / 2 + Math.min(b.w * 0.16, 1.2), -b.h / 2,
            b.w / 2 - Math.min(b.w * 0.16, 1.2), -b.h / 2 + b.h * prof.slot)
          polyFill(quad, SLOT_INK)
        }
      }
      const plan = metalPlan(c)
      for (const cap of plan.caps) polyFill(cap.quad, METAL)
      for (const lead of packageLeads(c, prof)) polyFill(lead.quad, METAL)
      if (t.k > 9) {
        g.save()
        g.translate(c.x, c.y - (b.h / 2 + 1.4))
        g.fillStyle = inkFor(color)
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
  // The same layer chips drive 2D and 3D, so a toggle means the same thing in
  // both views. Anything not explicitly off is on.
  const L = opts.layers || {}
  const showTop = L.top !== false
  const showBottom = L.bottom !== false
  const showSilk = L.silk !== false
  const showDrills = L.drills !== false
  const showParts = L.parts !== false

  // Faces carry (side, rank), not a fixed paint index. A 2-layer board is a
  // stack of near-coplanar sheets (bottom sheet, edges, top sheet, traces, pads,
  // bodies) and sorting the whole set by average depth cannot order those — a
  // far pad ends up "behind" the single big top face and gets buried. `rank`
  // orders the sheets on one side; drawBoard3D turns the pair into a paint order
  // for whichever side currently faces the camera, so the board can be turned all
  // the way over and its underside renders correctly too.
  // `obj` groups the faces of one physical object (a part, the board, the copper
  // sheet, ...). drawBoard3D paints whole objects in depth order, so two parts
  // that overlap can never interleave face-by-face.
  let currentObject = 'board'
  const setObject = (name) => {
    currentObject = name
  }
  const pushPoly = (pts3, color, normalHint, liftAmount, side, rank, extra) => {
    if (!pts3 || pts3.length < 3) return
    faces.push({
      pts: pts3.map((p) => [p[0], p[1], p[2] + liftAmount]),
      color,
      n: normalHint,
      side,
      rank,
      obj: currentObject,
      ...(extra || {})
    })
  }

  // A solid: top face plus one quad per side. Used for bodies and for every
  // piece of metal (leads, posts, tabs), so a lead cannot drift from its pad.
  const pushPrism = (poly, zBottom, zTop, color, rank, extra) => {
    if (!poly || poly.length < 3) return
    pushPoly(poly.map((p) => [p[0], p[1], zTop]), color, [0, 0, 1], 0, 'top', rank, extra)
    for (let i = 0; i < poly.length; i += 1) {
      const p = poly[i]
      const q = poly[(i + 1) % poly.length]
      pushPoly(
        [
          [p[0], p[1], zBottom],
          [q[0], q[1], zBottom],
          [q[0], q[1], zTop],
          [p[0], p[1], zTop]
        ],
        color,
        [q[1] - p[1], -(q[0] - p[0]), 0],
        0,
        'top',
        rank
      )
    }
  }

  // substrate: both faces are soldermask green, the exposed edge is plated
  // Silk is painted into the substrate face as a texture when the host can
  // rasterise one (see silkTexture); the quad path below is the fallback.
  const texTop = showSilk && canTexture()
  const texBottom = showSilk && canTexture()
  pushPoly(outline.map((p) => [p[0], p[1], 0]), C.substrate, [0, 0, -1], 0, 'bottom', 0, texBottom ? { tex: 'bottom' } : null)
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
      C.substrateEdge,
      n,
      0,
      'edge',
      0
    )
  }
  pushPoly(outline.map((p) => [p[0], p[1], th]), C.substrate, [0, 0, 1], 0, 'top', 0, texTop ? { tex: 'top' } : null)

  // copper traces as thin plates on each copper side
  setObject('copper')
  for (const layerId of ['F.Cu', 'B.Cu']) {
    const layer = view.copper[layerId]
    if (!layer) continue
    const top = layerId === 'F.Cu'
    if (top ? !showTop : !showBottom) continue
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
          top ? 'top' : 'bottom',
          1
        )
      }
    }
  }

  // pads as thin plates on both copper sides
  setObject('pads')
  for (const layerId of ['F.Cu', 'B.Cu']) {
    const layer = view.copper[layerId]
    if (!layer) continue
    if (layerId === 'F.Cu' ? !showTop : !showBottom) continue
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
      pushPoly(pts, color, layerId === 'F.Cu' ? [0, 0, 1] : [0, 0, -1], 0,
               layerId === 'F.Cu' ? 'top' : 'bottom', 2)
    }
  }

  // silkscreen, as thin plates of ink on the mask. Glyph polylines are skipped:
  // at board scale they are sub-pixel, and the designators are etched on the
  // parts anyway.
  // Textured silk replaces these quads wherever the host can rasterise; the
  // geometry path stays as the fallback (and as what the test harness exercises).
  if (showSilk && !canTexture()) {
    setObject('silk')
    for (const [key, z, side, color] of [['F.SilkS', th + 0.03, 'top', C.silk], ['B.SilkS', -0.03, 'bottom', '#9aa39c']]) {
      const layer = view.silk[key]
      if (!layer) continue
      for (const ln of layer.lines || []) {
        const pts = ln.points || []
        const hw = Math.max(ln.width || 0.15, 0.1) / 2
        for (let i = 0; i < pts.length - 1; i += 1) {
          const [x1, y1] = pts[i]
          const [x2, y2] = pts[i + 1]
          const len = Math.hypot(x2 - x1, y2 - y1)
          if (len < 0.08) continue
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
            [0, 0, side === 'top' ? 1 : -1],
            0,
            side,
            1.5
          )
        }
      }
    }
  }

  // drilled holes: a dark disc in each pad, so through-hole pads read as pads
  // with a hole instead of solid gold blobs
  if (showDrills) {
    setObject('drills')
    for (const d of view.drills || []) {
      const r = Math.max((d.d || 0.8) / 2, 0.15)
      const pts = []
      for (let i = 0; i < 12; i += 1) {
        const a = (i / 12) * Math.PI * 2
        pts.push([d.x + Math.cos(a) * r, d.y + Math.sin(a) * r, th + 0.03])
      }
      pushPoly(pts, C.drill, [0, 0, 1], 0, 'top', 2.6)
    }
  }

  // Component bodies, as prisms: rectangle / chamfered / cylindrical by family.
  // Each part also gets a contact shadow, its designator etched on the top face,
  // a pin-1 dot, and metal on it: terminations for two-terminal parts, visible
  // leads for everything else. Without the metal a part reads as a bare box,
  // because its pads sit underneath it.
  for (const comp of showParts ? view.components : []) {
    setObject(`part:${comp.ref}`)
    const b = comp.body || {}
    if (!b.w || !b.h) continue
    const prof = parsePackage(comp)
    const color = bodyColor(comp, prof)
    const z0 = th + 0.06
    const z1 = z0 + Math.max(0.3, prof.z || b.z || 1)
    const pins = comp.pins || []

    if (prof.shape !== 'none') {
      const corners = packageSilhouette(comp, prof)

      // shadow: same footprint at the body's base, offset in screen space at draw
      pushPoly(corners.map((p) => [p[0], p[1], z0]), color, [0, 0, 1], 0, 'top', 2.5, { shadow: true })

      pushPoly(corners.map((p) => [p[0], p[1], z1]), color, [0, 0, 1], lift, 'top', 3, {
        label: { text: comp.ref, w: b.w, h: b.h, ink: inkFor(color) },
        pin1: pins.length ? [pins[0].x, pins[0].y, z1 + 0.01] : null
      })
      for (let i = 0; i < corners.length; i += 1) {
        const p = corners[i]
        const q = corners[(i + 1) % corners.length]
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
          'top',
          3
        )
      }

      // LED lens: a smaller, lighter cylinder sitting on the body
      if (prof.shape === 'dome') {
        const r = Math.min(b.w, b.h) * 0.33
        const lens = []
        for (let i = 0; i < 12; i += 1) {
          const a = (i / 12) * Math.PI * 2
          lens.push([comp.x + Math.cos(a) * r, comp.y + Math.sin(a) * r])
        }
        pushPrism(lens, z1, z1 + Math.max(0.15, prof.z * 0.4), lightenHex(color, 1.45), 3.2)
      }

      // socket holes: one dark recess per pin, which is what you actually see
      // looking down into a PMOD or header socket
      if (prof.lead === 'holes') {
        const r = prof.holeR || 0.5
        for (const pin of pins) {
          const hole = []
          for (let i = 0; i < 8; i += 1) {
            const a = (i / 8) * Math.PI * 2 + Math.PI / 8
            hole.push([pin.x + Math.cos(a) * r, pin.y + Math.sin(a) * r])
          }
          pushPoly(hole.map((q) => [q[0], q[1], z1 + 0.005]), SLOT_INK, [0, 0, 1], lift, 'top', 3.05)
        }
      }

      // connector mouth: a dark slot in the front face
      if (prof.slot) {
        const quad = localQuad(comp, -b.w / 2 + Math.min(b.w * 0.16, 1.2), -b.h / 2,
          b.w / 2 - Math.min(b.w * 0.16, 1.2), -b.h / 2 + b.h * prof.slot)
        pushPoly(quad.map((p) => [p[0], p[1], z1 + 0.01]), SLOT_INK, [0, 0, 1], lift, 'top', 3.1)
      }
    }

    // ---- metal -----------------------------------------------------------
    const plan = metalPlan(comp)
    for (const cap of plan.caps) {
      pushPoly(cap.quad.map((p) => [p[0], p[1], z1 + 0.004]), METAL, [0, 0, 1], lift, 'top', 3.5)
      pushPoly(
        [
          [cap.outer[0][0], cap.outer[0][1], z0 + 0.02],
          [cap.outer[1][0], cap.outer[1][1], z0 + 0.02],
          [cap.outer[1][0], cap.outer[1][1], z1],
          [cap.outer[0][0], cap.outer[0][1], z1]
        ],
        METAL,
        cap.normal,
        lift,
        'top',
        3.5
      )
    }
    for (const lead of packageLeads(comp, prof)) {
      pushPrism(lead.quad, th + lead.z0, th + lead.z1, METAL, 3.5)
    }
  }
  return faces
}

/** A rectangle in the component's own frame, rotated into board mm. */
function localQuad(comp, x0, y0, x1, y1) {
  const rot = ((comp.rot || 0) * Math.PI) / 180
  const cos = Math.cos(rot)
  const sin = Math.sin(rot)
  const put = (lx, ly) => [comp.x + lx * cos - ly * sin, comp.y + lx * sin + ly * cos]
  return [put(x0, y0), put(x1, y0), put(x1, y1), put(x0, y1)]
}

/** Etch a designator onto a projected top face.

 * The face is a parallelogram, so an affine transform built from three of its
 * corners puts the text on the board at the right size and angle — it zooms and
 * turns with the part instead of floating above it.
 */
function drawFaceLabel(g, pts, label) {
  if (!label || !label.text || pts.length < 4) return
  const p0 = pts[0]
  const p1 = pts[1]
  const p3 = pts[3]
  const ex = [p1[0] - p0[0], p1[1] - p0[1]]
  // local +y runs from the last corner back to the first, which is screen-down,
  // so the glyphs stay upright when the board is seen from above
  const ey = [p0[0] - p3[0], p0[1] - p3[1]]
  const lenX = Math.hypot(ex[0], ex[1])
  const lenY = Math.hypot(ey[0], ey[1])
  if (lenX < 15 || lenY < 8) return          // too small to read: leave it clean
  if (ex[0] * ey[1] - ex[1] * ey[0] <= 0) return   // mirrored / facing away
  const W = Math.max(0.01, label.w)
  const H = Math.max(0.01, label.h)
  const size = Math.min(H * 0.52, W * 0.3, 2.6)
  if (size <= 0.05) return
  g.save()
  g.transform(ex[0] / W, ex[1] / W, ey[0] / H, ey[1] / H, p0[0], p0[1])
  g.font = `${size}px ui-sans-serif, system-ui, sans-serif`
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.fillStyle = label.ink
  g.fillText(label.text, W / 2, H / 2)
  g.restore()
}

/** End terminations for two-terminal parts (chip caps, resistors, tantalums), in
 *  board mm. Everything else — leads, posts, tabs — comes from packageLeads(),
 *  which knows the package's lead style and thickness; these caps are the metal
 *  ends you see on a chip part from above. */
function metalPlan(comp) {
  const b = comp.body || {}
  const pins = comp.pins || []
  const rot = ((comp.rot || 0) * Math.PI) / 180
  const ax = [Math.cos(rot), Math.sin(rot)]      // along the body's length
  const px = [-Math.sin(rot), Math.cos(rot)]     // across it
  const hx = (Math.abs(ax[0]) * b.w + Math.abs(ax[1]) * b.h) / 2
  const hp = (Math.abs(px[0]) * b.w + Math.abs(px[1]) * b.h) / 2
  const at = (a, c) => [comp.x + ax[0] * a + px[0] * c, comp.y + ax[1] * a + px[1] * c]
  const caps = []
  if (pins.length === 2) {
    const capLen = Math.min(Math.max(hx * 0.44, 0.22), 1.0)
    for (const side of [-1, 1]) {
      const a0 = side * (hx - capLen)
      const a1 = side * hx
      caps.push({
        quad: [at(a0, -hp), at(a1, -hp), at(a1, hp), at(a0, hp)],
        outer: [at(a1, -hp), at(a1, hp)],
        normal: [side * ax[0], side * ax[1], 0]
      })
    }
  }
  return { caps }
}

/** Rasterise a silk layer into a board-space texture.

 *  Silk text arrives as polyline glyphs (tiny-tapeout has 681 lines, median
 *  length 0.44 mm). Drawn as one quad per segment they read as scattered white
 *  sticks — no joins, no caps, and the whole glyph is smaller than a pixel at
 *  most zooms. A real board prints them as continuous ink, so the layer is
 *  rasterised once at board resolution and sampled per pixel in the depth pass:
 *  legible text, round caps, and a few thousand quads gone.
 */
const SILK_TEX = typeof WeakMap === 'function' ? new WeakMap() : null

function silkTexture(view, key, color, wantPxPerMm) {
  if (typeof document === 'undefined' || !document.createElement) return null
  let cache = SILK_TEX ? SILK_TEX.get(view) : null
  if (!cache) {
    cache = {}
    if (SILK_TEX) SILK_TEX.set(view, cache)
  }
  // Rasterise at roughly the resolution it will be displayed at. A fixed 24
  // px/mm texture sampled at 5 px/mm aliases a 0.12 mm stroke into dashes —
  // which is the "white sticks" again, just at a different stage.
  // Coarse buckets (×1.5 steps): a wheel zoom would otherwise rebuild the
  // texture on every frame. 3 → 40 px/mm is eight buckets in total.
  const want = Math.max(2, Math.min(40, wantPxPerMm || 20))
  const bucket = Math.max(3, Math.min(40, Math.round(Math.pow(1.5, Math.round(Math.log(want) / Math.log(1.5))))))
  const cacheKey = `${key}@${bucket}`
  if (cache[cacheKey] !== undefined) return cache[cacheKey]
  if (Object.keys(cache).length > 6) for (const k of Object.keys(cache)) delete cache[k]
  const lines = ((view.silk || {})[key] || {}).lines || []
  if (!lines.length) {
    cache[cacheKey] = null
    return null
  }
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const ln of lines) {
    for (const [x, y] of ln.points || []) {
      if (x < x0) x0 = x
      if (y < y0) y0 = y
      if (x > x1) x1 = x
      if (y > y1) y1 = y
    }
  }
  const margin = 0.5
  x0 -= margin
  y0 -= margin
  x1 += margin
  y1 += margin
  const bw = Math.max(0.1, x1 - x0)
  const bh = Math.max(0.1, y1 - y0)
  // 2048 on the long edge keeps text sharp on a 100 mm board (20 px/mm) and
  // still renders a 300 mm board at ~7 px/mm.
  const pxPerMm = Math.min(bucket, 2048 / Math.max(bw, bh))
  const tw = Math.max(1, Math.round(bw * pxPerMm))
  const th = Math.max(1, Math.round(bh * pxPerMm))
  const c = document.createElement('canvas')
  c.width = tw
  c.height = th
  const cx = c.getContext('2d')
  cx.setTransform(pxPerMm, 0, 0, -pxPerMm, -x0 * pxPerMm, y1 * pxPerMm)
  cx.strokeStyle = color
  cx.lineCap = 'round'
  cx.lineJoin = 'round'
  for (const ln of lines) {
    const pts = ln.points || []
    if (pts.length < 2) continue
    // Keep a hairline at least ~1.2 displayed pixels wide. A 0.12 mm stroke at
    // 5 px/mm is 0.6 px: it renders as a dotted ghost rather than printed ink.
    cx.lineWidth = Math.max(ln.width || 0.15, 0.12, 1.2 / pxPerMm)
    cx.beginPath()
    cx.moveTo(pts[0][0], pts[0][1])
    for (let i = 1; i < pts.length; i += 1) cx.lineTo(pts[i][0], pts[i][1])
    cx.stroke()
  }
  const img = cx.getImageData(0, 0, tw, th)
  const tex = { data: new Uint32Array(img.data.buffer), w: tw, h: th, x0, y1, pxPerMm }
  cache[cacheKey] = tex
  return tex
}

/** Can this host rasterise a texture at all? Node (the test harness) cannot. */
function canTexture() {
  return typeof document !== 'undefined' && !!document.createElement
}

function drawBoard3D(g, view, opts) {
  const canvas = opts.canvas
  const dpr = opts.dpr
  g.setTransform(1, 0, 0, 1, 0, 0)
  g.clearRect(0, 0, canvas.width, canvas.height)
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.globalAlpha = 1

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

  // Key light sits on the viewer's side of the board; without the flip the
  // underside of a fully turned board renders as a black silhouette.
  const undersideLight = Math.cos(opts.pitch || 0) < 0
  const light = [0.32, 0.42, undersideLight ? -0.85 : 0.85]
  const faces = facetsFor(view, opts)

  // Contact shadow: the board reads as a physical object on a surface rather
  // than a floating diagram. Drawn first so every face paints over it.
  const shadowPts = undersideLight ? [] : (view.outline || []).map((p) => project([p[0], p[1], 0]))
  if (shadowPts.length > 2 && !shadowPts.some((p) => p === null)) {
    // Solid, not blurred: a translucent shadow is still a see-through element.
    // A hard offset silhouette in a darker shade gives the same lift with no
    // alpha anywhere in the scene.
    g.save()
    g.beginPath()
    g.moveTo(shadowPts[0][0] + 9, shadowPts[0][1] + 14)
    for (let i = 1; i < shadowPts.length; i += 1) g.lineTo(shadowPts[i][0] + 9, shadowPts[i][1] + 14)
    g.closePath()
    g.fillStyle = '#07130d'
    g.fill()
    g.restore()
  }

  // ---- software z-buffer ---------------------------------------------------
  // A painter's algorithm cannot order this scene. CM5 MINIMA has a 40x55 mm
  // module 6 mm tall sitting over the whole board; no global sort can put a
  // small part that lies *under* it behind it without also burying the parts
  // that sit on top. Sorting by average depth left 27% of interior pixels
  // disagreeing with a real depth test (measured against a numpy z-buffer), and
  // that disagreement is exactly the "parts go through each other / are
  // see-through" look. So depth is resolved per pixel: flat-shaded faces are
  // rasterised scanline by scanline into a colour buffer and a 1/z buffer, and
  // the result is composited over the shadow in one drawImage. Correct by
  // construction — no ranks, no ordering heuristics, nothing can pop in or out.
  const ss = Math.min(2, Math.max(1, Math.round(dpr || 1)))
  // device pixels per board millimetre at the board centre, used to rasterise
  // the silk layer at display resolution
  const silkScale = Math.max(2, Math.min(40, (fov / dist) * ss * 1.4))
  const rw = Math.max(1, Math.round(w * ss))
  const rh = Math.max(1, Math.round(h * ss))
  const th = view.board.thickness || 1.6

  const items = []
  for (const f of faces) {
    const n = f.n || [0, 0, 1]
    const rn = rotate(n)
    // Normals arrive in board units, not normalized (a side face carries
    // [dy, -dx, 0], magnitude ~20 mm), so the raw dot product reached 5-7 and
    // every side face saturated to pure white over the pads and part bodies.
    const len = Math.hypot(rn[0], rn[1], rn[2]) || 1
    // Cull faces pointing away from the camera (it sits on +z looking down -z),
    // otherwise every box also paints its far walls and you can read the inside
    // of a part through the one in front of it.
    if (rn[2] / len <= 0) continue
    const lambert = Math.max(0, (rn[0] * light[0] + rn[1] * light[1] + rn[2] * light[2]) / len)
    // Lift the ambient term: at 0.5 the green mask and dark part bodies collapsed
    // into near-black, which read as "empty" next to reference renders.
    const shade = f.shadow ? 0.45 : 0.68 + 0.32 * lambert
    let tex = null
    if (f.tex) {
      tex = f.tex === 'top'
        ? silkTexture(view, 'F.SilkS', C.silk, silkScale)
        : silkTexture(view, 'B.SilkS', '#9aa39c', silkScale)
    }
    const pts = []
    const uvz = tex ? [] : null
    let zsum = 0
    let culled = false
    for (const p of f.pts) {
      const q = project(p)
      if (!q) { culled = true; break }
      const dx = f.shadow ? 2.5 : 0
      const dy = f.shadow ? 4 : 0
      pts.push([(q[0] + dx) * ss, (q[1] + dy) * ss, 1 / q[2]])
      if (uvz) {
        // u/z and v/z interpolate linearly in screen space, so the texel lookup
        // is perspective-correct after dividing by the interpolated 1/z.
        uvz.push([((p[0] - tex.x0) * tex.pxPerMm) / q[2], ((tex.y1 - p[1]) * tex.pxPerMm) / q[2]])
      }
      zsum += q[2]
    }
    if (culled || pts.length < 3) continue
    items.push({ f, pts, uvz, tex, rgb: packShaded(f.color, shade), depth: zsum / pts.length })
  }

  const raster = zRaster(items, rw, rh)
  const image = makeImage(raster.px, rw, rh)
  const off = offscreen(canvas, rw, rh)
  if (off) {
    off.getContext('2d').putImageData(image, 0, 0)
    g.drawImage(off, 0, 0, w, h)
  } else {
    g.putImageData(image, 0, 0)
  }

  // Labels and pin-1 dots stay vector so the text is crisp. They are drawn only
  // where the face they belong to is the surface actually visible at that pixel,
  // which keeps a hidden part's designator from floating on top of its neighbour.
  const visible = (it, cx2, cy2) => {
    const x = Math.round(cx2 * ss)
    const y = Math.round(cy2 * ss)
    if (x < 0 || y < 0 || x >= rw || y >= rh) return false
    const owner = raster.owner[y * rw + x]
    return owner >= 0 && items[owner].f.obj === it.f.obj
  }
  const overlays = items.filter((it) => it.f.label || it.f.pin1).sort((a, b) => b.depth - a.depth)
  for (const it of overlays) {
    const f = it.f
    if (f.pin1) {
      const dot = project(f.pin1)
      if (dot && visible(it, dot[0], dot[1])) {
        g.beginPath()
        g.arc(dot[0], dot[1], 2.2, 0, Math.PI * 2)
        g.fillStyle = '#0b0e0d'
        g.fill()
      }
    }
    if (f.label) {
      const css = it.pts.map((p) => [p[0] / ss, p[1] / ss])
      let ax = 0
      let ay = 0
      for (const p of css) { ax += p[0]; ay += p[1] }
      ax /= css.length
      ay /= css.length
      if (visible(it, ax, ay)) drawFaceLabel(g, css, f.label)
    }
  }

  canvas.__stats = { faces: faces.length, drawn: items.length, painted: raster.painted }
}

// Pack a shaded hex colour into the ABGR word an ImageData buffer wants on a
// little-endian machine (bytes in memory: R, G, B, A).
function packShaded(hex, factor) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return 0xff000000
  const n = parseInt(m[1], 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * factor))
  const gg = Math.min(255, Math.round(((n >> 8) & 255) * factor))
  const b = Math.min(255, Math.round((n & 255) * factor))
  return ((255 << 24) | (b << 16) | (gg << 8) | r) >>> 0
}

function makeImage(px, rw, rh) {
  const bytes = new Uint8ClampedArray(px.buffer, 0, rw * rh * 4)
  if (typeof ImageData !== 'undefined') return new ImageData(bytes, rw, rh)
  return { width: rw, height: rh, data: bytes }
}

// One offscreen canvas per board canvas, reused between frames: allocating a
// 1800x1280 backing store on every pointermove is what makes drags stutter.
function offscreen(canvas, rw, rh) {
  if (canvas.__zbCanvas) {
    const c = canvas.__zbCanvas
    if (c.width !== rw) c.width = rw
    if (c.height !== rh) c.height = rh
    return c
  }
  if (typeof document === 'undefined' || !document.createElement) return null
  const c = document.createElement('canvas')
  c.width = rw
  c.height = rh
  canvas.__zbCanvas = c
  return c
}

// Scanline rasteriser with a 1/z depth buffer. Faces are convex polygons, so a
// scanline crosses each at most twice; interpolating 1/z along the span is
// exact for a perspective projection. Returns the colour buffer plus the index
// of the face that owns each pixel, which the label pass uses for visibility.
// A scanline through a concave outline crosses it more than twice; these hold
// the sorted crossings for one row (reused, so no per-scanline allocation).
const SPAN_MAX = 512
const spanX = new Float64Array(SPAN_MAX)
const spanW = new Float64Array(SPAN_MAX)
const spanU = new Float64Array(SPAN_MAX)
const spanV = new Float64Array(SPAN_MAX)

function zRaster(items, rw, rh) {
  const px = new Uint32Array(rw * rh)
  const zb = new Float32Array(rw * rh)
  const owner = new Int32Array(rw * rh).fill(-1)
  let painted = 0
  for (let fi = 0; fi < items.length; fi += 1) {
    const pts = items[fi].pts
    const col = items[fi].rgb
    const tex = items[fi].tex
    const uvz = items[fi].uvz
    const n = pts.length
    let minX = Infinity
    let maxX = -Infinity
    let minY = Infinity
    let maxY = -Infinity
    for (let i = 0; i < n; i += 1) {
      const p = pts[i]
      if (p[0] < minX) minX = p[0]
      if (p[0] > maxX) maxX = p[0]
      if (p[1] < minY) minY = p[1]
      if (p[1] > maxY) maxY = p[1]
    }
    const y0 = Math.max(0, Math.ceil(minY - 0.5))
    const y1 = Math.min(rh - 1, Math.floor(maxY - 0.5))
    const bx0 = Math.max(0, Math.ceil(minX - 0.5))
    const bx1 = Math.min(rw - 1, Math.floor(maxX - 0.5))
    if (y1 < y0 || bx1 < bx0) continue
    for (let y = y0; y <= y1; y += 1) {
      const sy = y + 0.5
      // Even-odd span fill. A scanline can cross a concave outline four or more
      // times, and filling from the leftmost to the rightmost crossing painted
      // the convex hull — which bridged every notch: an L-shaped board edge came
      // out with the corner filled in, and a cut-out vanished. Collect every
      // crossing, sort them, and fill between successive pairs.
      let nCross = 0
      for (let i = 0; i < n; i += 1) {
        const a = pts[i]
        const b = pts[i + 1 === n ? 0 : i + 1]
        if ((a[1] <= sy && b[1] > sy) || (b[1] <= sy && a[1] > sy)) {
          if (nCross >= SPAN_MAX) break
          const t = (sy - a[1]) / (b[1] - a[1])
          const x = a[0] + (b[0] - a[0]) * t
          const wi = a[2] + (b[2] - a[2]) * t
          const j = i + 1 === n ? 0 : i + 1
          const uo = tex ? uvz[i][0] + (uvz[j][0] - uvz[i][0]) * t : 0
          const vo = tex ? uvz[i][1] + (uvz[j][1] - uvz[i][1]) * t : 0
          let k = nCross - 1
          while (k >= 0 && spanX[k] > x) {
            spanX[k + 1] = spanX[k]
            spanW[k + 1] = spanW[k]
            spanU[k + 1] = spanU[k]
            spanV[k + 1] = spanV[k]
            k -= 1
          }
          spanX[k + 1] = x
          spanW[k + 1] = wi
          spanU[k + 1] = uo
          spanV[k + 1] = vo
          nCross += 1
        }
      }
      for (let c = 0; c + 1 < nCross; c += 2) {
        const xl = spanX[c]
        const xr = spanX[c + 1]
        const wl = spanW[c]
        const wr = spanW[c + 1]
        const sx0 = Math.max(bx0, Math.ceil(xl - 0.5))
        const sx1 = Math.min(bx1, Math.floor(xr - 0.5))
        if (sx1 < sx0) continue
        const span = xr - xl
        const dw = span > 1e-9 ? (wr - wl) / span : 0
        const off = sx0 + 0.5 - xl
        let wi = wl + dw * off
        let idx = y * rw + sx0
        if (tex) {
          // Silk ink is sampled from the board-space texture and blended over the
          // substrate colour: one quad for the whole layer instead of one per
          // glyph stroke.
          const uzl = spanU[c]
          const uzr = spanU[c + 1]
          const vzl = spanV[c]
          const vzr = spanV[c + 1]
          const duz = span > 1e-9 ? (uzr - uzl) / span : 0
          const dvz = span > 1e-9 ? (vzr - vzl) / span : 0
          let uz = uzl + duz * off
          let vz = vzl + dvz * off
          for (let x = sx0; x <= sx1; x += 1, idx += 1, wi += dw, uz += duz, vz += dvz) {
            if (wi > zb[idx]) {
              zb[idx] = wi
              const inv = 1 / wi
              const tx = Math.round(uz * inv)
              const ty = Math.round(vz * inv)
              let out = col
              if (tx >= 0 && ty >= 0 && tx < tex.w && ty < tex.h) {
                const t = tex.data[ty * tex.w + tx]
                const a = t >>> 24
                if (a > 0) {
                  const ia = 255 - a
                  const r = (((t & 255) * a + (col & 255) * ia) / 255) | 0
                  const g2 = ((((t >> 8) & 255) * a + ((col >> 8) & 255) * ia) / 255) | 0
                  const b2 = ((((t >> 16) & 255) * a + ((col >> 16) & 255) * ia) / 255) | 0
                  out = ((255 << 24) | (b2 << 16) | (g2 << 8) | r) >>> 0
                }
              }
              px[idx] = out
              owner[idx] = fi
              painted += 1
            }
          }
        } else {
          for (let x = sx0; x <= sx1; x += 1, idx += 1, wi += dw) {
            if (wi > zb[idx]) {
              zb[idx] = wi
              px[idx] = col
              owner[idx] = fi
              painted += 1
            }
          }
        }
      }
    }
  }
  return { px, zb, owner, painted }
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
        layers,
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
      // A full turn, not a 77-degree tilt: the pass order and the key light flip
      // once the camera passes under the board (see drawBoard3D).
      s.pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, s.drag.pitch + dy * 0.01))
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
      view && view.imported ? jsx(Badge, { variant: 'muted', children: 'imported · read-only' }) : null,
      jsx('div', { style: { flex: 1 } }),
      note ? jsx('span', { style: { fontSize: 11.5, color: UI.dim }, children: note }) : null,
      jsxs('div', { style: { display: 'flex', gap: 4, ...panel, padding: 3 }, children: [
        chip('2D', mode === '2d', () => setMode('2d')),
        chip('3D', mode === '3d', () => setMode('3d'))
      ] }),
      // An imported board has no engine part ids to re-place or re-route, and the
      // endpoint answers 409 — do not offer the button at all.
      jsx(Button, {
        variant: 'secondary',
        size: 'sm',
        disabled: busy || !slug || Boolean(view && view.imported),
        onClick: rebuild,
        children: busy ? 'Rebuilding…' : view && view.imported ? 'Read-only' : 'Rebuild'
      })
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
export const __test__ = {
  facetsFor, shadeColor, rotMatrix, drawBoard2D, drawBoard3D, zRaster, packShaded,
  parsePackage, packageSilhouette, packageLeads, metalPlan, chipHeight, parsePitch, silkTexture, canTexture,
  InlineBoard, BoardPage, LAYER_KEYS, PART_COLORS
}
