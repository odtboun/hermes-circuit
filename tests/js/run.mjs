// Node harness for desktop/plugin.js: loads the real file with SDK/react stubs,
// then exercises registration, the 3D facet builder and both canvas renderers.
import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import assert from 'node:assert'

const here = dirname(fileURLToPath(import.meta.url))
const repo = join(here, '..', '..')
const work = mkdtempSync(join(tmpdir(), 'circuit-plugin-'))

const write = (rel, body) => {
  const p = join(work, rel)
  mkdirSync(dirname(p), { recursive: true })
  writeFileSync(p, body)
}

write('node_modules/@hermes/plugin-sdk/package.json',
  JSON.stringify({ name: '@hermes/plugin-sdk', type: 'module', main: 'index.mjs' }))
write('node_modules/@hermes/plugin-sdk/index.mjs', `
export const host = { navigate() {}, onEvent() { return () => {} }, state: {} }
export const useQuery = () => ({ isLoading: false, error: globalThis.__QUERY_ERROR || null, data: globalThis.__QUERY_DATA })
export const useQueryClient = () => ({ invalidateQueries() {} })
const comp = (name) => function Stub() { return { type: 'div', props: { 'data-stub': name } } }
export const Button = comp('button')
export const Badge = comp('badge')
export const EmptyState = comp('empty')
export const GlyphSpinner = comp('spinner')
export const PALETTE_AREA = 'palette'
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const TRANSCRIPT_DIRECTIVE_AREA = 'transcript.directives'
`)

write('node_modules/react/package.json', JSON.stringify({ name: 'react', type: 'module', main: 'index.mjs' }))
write('node_modules/react/index.mjs', `
export function useState(initial) { return [typeof initial === 'function' ? initial() : initial, () => {}] }
export function useRef(value) { return { current: value } }
export function useMemo(fn) { return fn() }
export function useCallback(fn) { return fn }
export function useEffect() {}
export function useLayoutEffect() {}
`)
write('node_modules/react/jsx-runtime.js', `
// Mirror the real runtime signature: jsx(type, props, key). A third positional
// argument is the KEY, so children passed there are silently dropped by React —
// the exact bug that left the Board tab blank. Fail loudly instead.
function build(fn) {
  return function (type, props, key) {
    if (arguments.length > 3) throw new Error(fn + ': too many arguments (type, props, key) — children belong in props.children')
    if (Array.isArray(key)) throw new Error(fn + ': children passed as the 3rd argument; that slot is \`key\`')
    return { type, props: props || {}, key }
  }
}
export const jsx = build('jsx')
export const jsxs = build('jsxs')
`)
write('node_modules/react/jsx-runtime.mjs', `
function build(fn) {
  return function (type, props, key) {
    if (arguments.length > 3) throw new Error(fn + ': too many arguments (type, props, key) — children belong in props.children')
    if (Array.isArray(key)) throw new Error(fn + ': children passed as the 3rd argument; that slot is \`key\`')
    return { type, props: props || {}, key }
  }
}
export const jsx = build('jsx')
export const jsxs = build('jsxs')
`)
write('node_modules/react/package.json', JSON.stringify({
  name: 'react', type: 'module', main: 'index.mjs',
  exports: { '.': './index.mjs', './jsx-runtime': './jsx-runtime.mjs' }
}))

copyFileSync(join(repo, 'circuit', 'desktop', 'plugin.js'), join(work, 'plugin.mjs'))
const view = JSON.parse(readFileSync(join(here, 'fixtures', 'view.json'), 'utf8'))
const plugin = (await import(pathToFileURL(join(work, 'plugin.mjs')).href)).default
const { __test__ } = await import(pathToFileURL(join(work, 'plugin.mjs')).href)

// ---- registration -------------------------------------------------------- //
assert.equal(plugin.id, 'circuit')
const contributions = []
const ctx = {
  register: (c) => contributions.push(c),
  rest: async () => ({}),
  // Hooks are stubbed, so the "pick a board" effect never runs: seed the
  // selected slug the same way the app does after `Open board`.
  storage: { get: (k, d) => (k === 'selected' ? 'pico-sensor-hub' : d), set() {}, remove() {} },
  onDispose: () => {},
  setTimeout: (f) => setTimeout(f, 0),
  setInterval: (f) => setInterval(f, 1000)
}
plugin.register(ctx)
const areas = contributions.map((c) => c.area).sort()
assert.deepEqual(areas, ['palette', 'routes', 'sidebar.nav', 'transcript.directives'])
const directive = contributions.find((c) => c.area === 'transcript.directives')
assert.equal(directive.data.name, 'circuit')
assert.equal(typeof directive.data.render, 'function')
assert.equal(contributions.find((c) => c.area === 'routes').data.path, '/circuit')

// ---- 3D geometry --------------------------------------------------------- //
const faces = __test__.facetsFor(view, { explode: false })
assert.ok(faces.length > 50, `expected many facets, got ${faces.length}`)
for (const f of faces) {
  assert.ok(f.pts.length >= 3)
  for (const p of f.pts) assert.ok(Number.isFinite(p[0]) && Number.isFinite(p[1]) && Number.isFinite(p[2]))
}
const exploded = __test__.facetsFor(view, { explode: true })
assert.ok(exploded.length === faces.length, 'explode must not change the facet count')
assert.ok(exploded.every((f, i) => f.pts[0][2] >= faces[i].pts[0][2] - 1e-9))
assert.match(__test__.shadeColor('#804020', 0.5, 1), /^rgba\(/)

// ---- geometry budget ----------------------------------------------------- //
// The 3D pass repaints every face on each pointermove, so the face count is the
// thing that decides whether dragging stays smooth: ~7k faces measured 18 ms
// warm in Chrome, 450 faces 2 ms. A synthetic dense board guards both the count
// and any accidental super-linear work in facetsFor.
const dense = {
  ...view,
  components: Array.from({ length: 240 }, (_, i) => {
    const src = view.components[i % view.components.length]
    return { ...src, ref: `D${i}`, x: 10 + (i % 20) * 2.2, y: 10 + Math.floor(i / 20) * 3.1 }
  })
}
const tGeom = Date.now()
const denseFaces = __test__.facetsFor(dense, { explode: false })
const geomMs = Date.now() - tGeom
assert.ok(denseFaces.length < 12000, `3D face budget exceeded: ${denseFaces.length} faces`)
assert.ok(geomMs < 400, `facetsFor took ${geomMs} ms for 240 parts — check for super-linear work`)
for (const f of denseFaces) {
  assert.ok(['top', 'bottom', 'edge'].includes(f.side), `face missing a side: ${f.side}`)
  assert.ok(Number.isFinite(f.rank), 'face missing a paint rank')
}

// ---- canvas renderers ---------------------------------------------------- //
function recordingContext() {
  const calls = {}
  const handler = {
    get(target, prop) {
      if (prop in target) return target[prop]
      // create* factory methods (gradients, patterns) hand back an object with
      // its own API — return a stub instead of an undefined function result.
      if (typeof prop === 'string' && prop.startsWith('create')) {
        return (...args) => {
          calls[prop] = (calls[prop] || 0) + 1
          return { addColorStop() {}, setTransform() {} }
        }
      }
      return (...args) => { calls[prop] = (calls[prop] || 0) + 1 }
    },
    set(target, prop, value) { target[prop] = value; return true }
  }
  return { ctx: new Proxy({}, handler), calls }
}

const canvas = { width: 1200, height: 700, style: {} }
const r2 = recordingContext()
__test__.drawBoard2D(r2.ctx, view, {
  canvas, dpr: 2,
  layers: { top: true, bottom: true, silk: true, drills: true, parts: true, mask: true },
  transform: { k: 12, ox: 60, oy: 600 },
  hotNet: 'GND'
})
assert.ok(r2.calls.arc > 50, 'pads/drills should be drawn as arcs')
assert.ok(r2.calls.lineTo > 100, 'traces should emit line segments')
assert.ok(r2.calls.stroke > 20)
const bodies = view.components.filter((c) => c.body && c.body.w > 0 && c.body.h > 0).length
assert.ok(r2.calls.fillText >= bodies, `every part with a body gets a designator (${r2.calls.fillText}/${bodies})`)

// ---- package geometry ----------------------------------------------------- //
// The family table is the whole point of the procedural 3D: a SOT-23 is 1.1 mm
// tall and a 0402 is 0.5 mm, and getting those wrong is what made every part
// look like the same slab. Each case below is a real footprint from a real board.
const mkComp = (footprint, pins, extra = {}) => ({
  ref: 'U1',
  footprint,
  part: `kicad:${footprint}`,
  value: '',
  body: { w: 4, h: 3, z: 0.45, color: 'default' },
  x: 10,
  y: 10,
  rot: 0,
  pins: pins || [],
  ...extra
})
const pkg = (fp, pins, extra) => __test__.parsePackage(mkComp(fp, pins, extra))

const cases = [
  ['CM5IO:SOT-23-6', 'sot23', 1.1],
  ['CM5IO:SOT-416', 'sot323', 0.9],
  ['Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'soic', 1.6],
  ['Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm', 'qfn', 0.9],
  ['Package_TO_SOT_SMD:SOT-223-3_TabPin2', 'sot223', 1.8],
  ['Capacitor_SMD:C_0402_1005Metric', 'chip', 0.5],
  ['Capacitor_SMD:C_0603_1608Metric', 'chip', 0.55],
  ['Capacitor_SMD:C_0805_2012Metric', 'chip', 0.6],
  ['Resistor_SMD:R_1206_3216Metric', 'chip', 0.65],
  ['Capacitor_Tantalum_SMD:CP_EIA-3528-21_Kemet-B', 'tantalum', 1.9],
  ['Capacitor_THT:CP_Radial_D8.0mm_P3.50mm', 'electrolytic', 6],
  ['Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm', 'crystal', 0.8],
  ['Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12', 'usb-c', 3.3],
  ['Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', 'header', 2.5],
  ['Package_DIP:DIP-8_W7.62mm', 'dip', 4],
  ['LED_SMD:LED_0603_1608Metric', 'led', 0.6],
  ['Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C', 'relay', 15],
  ['MountingHole:MountingHole_3.2mm_M3_Pad', 'hole', 0],
  ['flyingcarsfootprints:StitchingVia-0.3mm', 'via', 0],
  ['TinyTapeout:SolderJumper-2_Bridged_Throughole1', 'flat', 0]
]
for (const [fp, family, z] of cases) {
  const prof = pkg(fp)
  assert.equal(prof.family, family, `${fp} -> family ${family} (got ${prof.family})`)
  assert.equal(prof.z, z, `${fp} -> height ${z} mm (got ${prof.z})`)
}

// height has to follow the chip size, or the whole point is lost
const heights = ['C_0201_0603Metric', 'C_0402_1005Metric', 'C_0603_1608Metric', 'C_0805_2012Metric', 'C_1206_3216Metric'].map((f) => pkg(`Capacitor_SMD:${f}`).z)
for (let i = 1; i < heights.length; i += 1) {
  assert.ok(heights[i] >= heights[i - 1], `chip heights must not shrink with size: ${heights.join(', ')}`)
}

// vendor part-number footprints fall back to the reference designator
assert.equal(pkg('TinyTapeout:434121025816', [], { ref: 'SW1' }).family, 'switch')
assert.equal(pkg('CM5IO:GLPLXSMT188S7QQYG', [], { ref: 'J1' }).family, 'connector')
assert.equal(pkg('TinyTapeout:WL_S7DS-157112V12700', [], { ref: 'U1' }).family, 'ic')

// pitch comes out of the footprint name
assert.equal(pkg('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm').pitch, 1.27)
assert.equal(pkg('Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical').pitch, 2.54)
assert.equal(pkg('Capacitor_SMD:C_0402_1005Metric').pitch, null)

// silhouettes: a cylinder is round, a chamfer has eight corners, a SOT is not a cube
const silPts = (fp) => __test__.packageSilhouette(mkComp(fp), pkg(fp)).length
assert.equal(silPts('Capacitor_THT:CP_Radial_D8.0mm_P3.50mm'), 16, 'electrolytics are cylinders')
assert.equal(silPts('Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm'), 8, 'QFN bodies are chamfered')
assert.equal(silPts('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'), 4, 'SOIC bodies are plain rectangles')

// leads: real geometry at the real pads, on the board, below the body top
const smdPins = [
  { num: '1', x: 10, y: 8, w: 1.5, h: 0.6, rot: 0, kind: 'smd', drill: 0 },
  { num: '2', x: 10, y: 12, w: 1.5, h: 0.6, rot: 0, kind: 'smd', drill: 0 }
]
const gull = __test__.packageLeads(mkComp('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', smdPins), pkg('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', smdPins))
assert.equal(gull.length, 2, 'one lead per pin')
// body 4x3 at (10,10) => edges at y=8.5 and y=11.5; pins at y=8 and y=12 with
// 0.6 mm pads => pad ends at 7.7 and 12.3. Each lead must span its whole gap.
const bands = [[7.7, 8.5], [11.5, 12.3]]
gull.forEach((l, i) => {
  assert.ok(l.z1 > l.z0, 'a lead must have thickness')
  assert.ok(l.z1 < 1.6, `a gull-wing lead must sit under the body top (${l.z1})`)
  const ys = l.quad.map((p) => p[1])
  assert.ok(Math.abs(Math.min(...ys) - bands[i][0]) < 0.02, `lead ${i} must reach its pad end (min y ${Math.min(...ys)}, want ${bands[i][0]})`)
  assert.ok(Math.abs(Math.max(...ys) - bands[i][1]) < 0.02, `lead ${i} must reach the body edge (max y ${Math.max(...ys)}, want ${bands[i][1]})`)
})
// Male pin header: 2.5 mm plastic block with 8.5 mm pins through it.
const thtPins = smdPins.map((p) => ({ ...p, kind: 'tht', drill: 1.0 }))
const hdrFp = 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical'
const hdrProf = pkg(hdrFp, thtPins)
assert.equal(hdrProf.z, 2.5, 'male header plastic is 2.5 mm')
const posts = __test__.packageLeads(mkComp(hdrFp, thtPins), hdrProf)
assert.ok(posts.length === 2 && posts.every((p) => Math.abs(p.z1 - 8.5) < 1e-6), 'header pins stand 8.5 mm out of the plastic')

// A pin SOCKET is the opposite: the tall plastic body is the part and the pins
// are holes. Rendering it as a male header put 8.5 mm grey posts on every PMOD
// connector (tiny-tapeout has six of them, 72 pins).
const sockFp = 'Connector_PinSocket_2.54mm:PinSocket_2x06_P2.54mm_PMODHost1A'
const sockProf = pkg(sockFp, thtPins)
assert.equal(sockProf.z, 8.5, 'a 2.54 mm socket body is 8.5 mm tall')
assert.equal(sockProf.lead, 'holes', 'a socket has holes, not posts')
assert.equal(__test__.packageLeads(mkComp(sockFp, thtPins), sockProf).length, 0, 'a socket emits no metal pins')

// An SMD header is just the plastic block; its pins are flat pads.
const smdHdrFp = 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical_SMD_Pin1Right'
const smdHdrProf = pkg(smdHdrFp, smdPins)
assert.equal(smdHdrProf.z, 2.5)
assert.equal(smdHdrProf.lead, 'none', 'an SMD header has no standing pins')
assert.equal(__test__.packageLeads(mkComp(smdHdrFp, smdPins), smdHdrProf).length, 0)

// Through-hole pins are solder fillets under the body, never posts: a 15 mm
// relay had a grey cylinder standing beside it up to 13.5 mm.
const relayFp = 'Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C'
const relayProf = pkg(relayFp, thtPins)
for (const l of __test__.packageLeads(mkComp(relayFp, thtPins), relayProf)) {
  assert.ok(l.z1 - l.z0 <= 0.4, `a THT pin must stay at the board (${l.z1 - l.z0} mm)`)
}
assert.equal(__test__.packageLeads(mkComp('MountingHole:MountingHole_3.2mm_M3_Pad', smdPins), pkg('MountingHole:MountingHole_3.2mm_M3_Pad', smdPins)).length, 0, 'a mounting hole has no body and no leads')

// ---- the 3D view resolves depth per pixel, not by sorting ---------------- //
// Two overlapping quads: the nearer one must win at the overlap, and the result
// must not depend on the order they are handed to the rasteriser. A painter's
// algorithm fails this test; that failure is the "parts go through each other"
// bug on boards with a tall part over the whole layout (CM5 MINIMA).
const quad = (x0, y0, x1, y1, w) => [[x0, y0, w], [x1, y0, w], [x1, y1, w], [x0, y1, w]]
const far = { pts: quad(2, 2, 18, 18, 1 / 50), rgb: 0xff0000ff, depth: 50 }
const near = { pts: quad(8, 8, 12, 12, 1 / 10), rgb: 0xff00ff00, depth: 10 }
const a1 = __test__.zRaster([far, near], 20, 20)
const a2 = __test__.zRaster([near, far], 20, 20)
const mid = 10 * 20 + 10
assert.equal(a1.px[mid] >>> 0, 0xff00ff00, 'the nearer quad must own the overlap')
assert.equal(a2.px[mid] >>> 0, a1.px[mid] >>> 0, 'depth order must not depend on paint order')
assert.equal(a1.px[3 * 20 + 3] >>> 0, 0xff0000ff, 'the far quad still shows outside the overlap')

// Zooming in must not delete the board. The substrate is a single polygon over
// the whole outline, so a corner passing behind the camera used to discard the
// entire face (the green vanished, the small parts stayed). Faces are clipped to
// the near plane now: at a distance smaller than the board, the substrate still
// covers the frame.
const zoomView = {
  board: { width: 100, height: 80, thickness: 1.6 },
  outline: [[0, 0], [100, 0], [100, 80], [0, 80]],
  copper: { 'F.Cu': { draws: [], flashes: [] }, 'B.Cu': { draws: [], flashes: [] } },
  silk: {}, drills: [], components: []
}
const zoomCtx = recordingContext()
__test__.drawBoard3D(zoomCtx.ctx, zoomView, { canvas, dpr: 1, explode: false, alpha: 1, yaw: -0.55, pitch: -0.95, dist: 30 })
assert.ok(canvas.__stats.painted > 20000, `the board must still be drawn at close zoom (painted ${canvas.__stats.painted})`)

// A concave outline must not be filled as its convex hull. This is a slot cut
// into a board edge: scanlines through it cross the outline FOUR times, and a
// min..max fill painted the slot in — the "green spills into the L corner" bug.
const slotPoly = [[0, 0], [40, 0], [40, 30], [28, 30], [28, 12], [12, 12], [12, 30], [0, 30]]
  .map(([x, y]) => [x, y, 1 / 50])
const slotFill = __test__.zRaster([{ pts: slotPoly, rgb: 0xff00ff00, depth: 50 }], 60, 40)
const at = (x, y) => slotFill.px[y * 60 + x] >>> 0
assert.equal(at(20, 25), 0, 'the slot must stay empty (even-odd fill)')
assert.notEqual(at(20, 6), 0, 'the board above the slot must be filled')
assert.notEqual(at(6, 25), 0, 'the left arm must be filled')
assert.notEqual(at(34, 25), 0, 'the right arm must be filled')

const r3 = recordingContext()
__test__.drawBoard3D(r3.ctx, view, { canvas, dpr: 2, explode: false, alpha: 1, yaw: -0.6, pitch: 0.9, dist: 120 })
const st = canvas.__stats
assert.ok(st && st.faces > 100, 'drawBoard3D reports its facet count')
assert.ok(st.drawn > 100, `too few faces survived culling (${st.drawn}/${st.faces}) — culling inverted?`)
assert.ok(st.drawn < st.faces, `every face drawn (${st.drawn}/${st.faces}) — culling is off`)
assert.ok(st.painted > 5000, `rasteriser wrote too few pixels (${st.painted})`)
assert.equal(r3.calls.putImageData, 1, 'the rasterised frame is composited once')

// ---- generated documents tab --------------------------------------------- //
// The Docs tab lists the three documents and shows the selected one in an iframe
// via srcDoc. The engine writes them; the page only has to display them.
const docView = {
  ...view,
  docs: [
    { kind: 'shopping', title: 'Shopping list', file: 'bom.html' },
    { kind: 'wiring', title: 'Wiring card', file: 'wiring.html' },
    { kind: 'poster', title: 'Board poster', file: 'poster.html' }
  ]
}
globalThis.__QUERY_DATA = { kind: 'shopping', html: '<!doctype html><p>hi</p>', bytes: 12400 }
const docsText = texts(__test__.DocsTab({ ctx, view: docView, slug: 'pico-sensor-hub' })).join(' ')
for (const label of ['Shopping list', 'Wiring card', 'Board poster']) {
  assert.ok(docsText.includes(label), `docs tab lists ${label}`)
}
assert.ok(docsText.includes('bom.html'), 'docs tab names the selected file')

// the iframe must receive the rendered document, not an empty frame
const docsNode = __test__.DocsTab({ ctx, view: docView, slug: 'pico-sensor-hub' })
const findIframe = (node, depth = 0) => {
  if (!node || typeof node !== 'object' || depth > 8) return null
  if (node.type === 'iframe') return node
  for (const child of [].concat((node.props && node.props.children) || [])) {
    const hit = findIframe(child, depth + 1)
    if (hit) return hit
  }
  return null
}
const frame = findIframe(docsNode)
assert.ok(frame, 'the document renders in an iframe')
assert.ok(frame.props.srcDoc.includes('<!doctype html>'), 'the iframe gets the document html')
// allow-scripts without allow-same-origin: the injected click handler can reach
// this page and nothing else
assert.equal(frame.props.sandbox, 'allow-scripts', 'the frame is sandboxed to an opaque origin')

// The frame fills the tab before the document reports its height, then becomes as
// tall as the document and the tab scrolls — a 10 000 px shopping list must not be
// a 320 px window with its own scrollbar.
assert.equal(frame.props.style.height, '100%', 'the frame fills the tab until it is measured')
const frameParent = (() => {
  const walk = (node, depth = 0) => {
    if (!node || typeof node !== 'object' || depth > 8) return null
    const kids = [].concat((node.props && node.props.children) || [])
    if (kids.some((c) => c && c.type === 'iframe')) return node
    for (const c of kids) {
      const hit = walk(c, depth + 1)
      if (hit) return hit
    }
    return null
  }
  return walk(docsNode)
})()
assert.ok(frameParent, 'the frame is wrapped')
assert.equal(frameParent.props.style.overflowY, 'auto', 'the tab scrolls, not the frame')

// The page must not inject markup into the document (the catalog validator refuses
// it): the document carries its own buy-link forwarder, and the page only listens.
assert.equal(frame.props.srcDoc, globalThis.__QUERY_DATA.html,
  'the document is framed exactly as the engine wrote it')

// an imported board has no library parts, so no documents — say so instead of
// rendering an empty frame
globalThis.__QUERY_DATA = view
const emptyDocs = texts(__test__.DocsTab({ ctx, view: { ...view, docs: [] }, slug: 'x' })).join(' ')
assert.ok(emptyDocs.includes('No documents'), 'empty docs state renders')

// A backend older than the page has no /docs route: say so, instead of claiming
// the board has no documents.
const stale = { ...view }
delete stale.docs
globalThis.__QUERY_ERROR = { message: 'Not Found' }
const staleText = texts(__test__.DocsTab({ ctx, view: stale, slug: 'x' })).join(' ')
assert.ok(staleText.includes('newer backend'), 'stale backend is called out')
assert.ok(!staleText.includes('No documents for this board'), 'stale backend is not blamed on the board')
globalThis.__QUERY_ERROR = null

// ...and when the board document lacks the list but the index route answers,
// the tab still lists the documents
globalThis.__QUERY_DATA = { documents: [
  { kind: 'shopping', title: 'Shopping list', file: 'bom.html' },
  { kind: 'wiring', title: 'Wiring card', file: 'wiring.html' },
  { kind: 'poster', title: 'Board poster', file: 'poster.html' }
] }
const fromIndex = texts(__test__.DocsTab({ ctx, view: stale, slug: 'x' })).join(' ')
assert.ok(fromIndex.includes('Wiring card'), 'the index route fills the list')
globalThis.__QUERY_DATA = view


// ---- components render without a browser --------------------------------- //
// Minimal renderer: executes function components (hooks are stubbed) and
// collects every string a real React pass would put on screen.
function texts(node, out = [], depth = 0) {
  if (node == null || depth > 12) return out
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return out }
  if (Array.isArray(node)) { node.forEach((n) => texts(n, out, depth + 1)); return out }
  if (typeof node !== 'object') return out
  if (node.props && node.props.children !== undefined) texts(node.props.children, out, depth + 1)
  if (typeof node.type === 'function') texts(node.type(node.props || {}), out, depth + 1)
  return out
}

globalThis.__QUERY_DATA = view
const inline = texts(__test__.InlineBoard({ ctx, attrs: { board: 'pico-sensor-hub' } })).join(' ')
assert.ok(inline.includes('Pico sensor hub'), 'inline card shows the board title')
assert.ok(inline.includes('mm'), 'inline card shows the size')

globalThis.__QUERY_DATA = {
  ...view,
  boards: [{ slug: 'pico-sensor-hub', title: 'Pico sensor hub', board: { width: 72, height: 50 }, components: 13, drc_ok: true }]
}
const pageText = texts(__test__.BoardPage({ ctx })).join(' ')
assert.ok(pageText.includes('Boards'), 'sidebar renders')
assert.ok(pageText.includes('DRC clean'), 'DRC badge renders')
assert.ok(pageText.includes('Pico sensor hub'), 'page title renders')
assert.ok(pageText.includes('13 parts'), 'sidebar board row keeps its size/parts meta line')
// Tab labels come from `chip()`; dropping them left five blank pills.
for (const label of ['Board', 'Nets', 'BOM', 'DRC', 'Files']) {
  assert.ok(pageText.includes(label), `tab bar shows the "${label}" label`)
}
// The default Board tab is a canvas + hint row; an empty body here means the
// canvas never mounted (regression: children passed as jsxs's key argument).
assert.ok(pageText.includes('hover a pad'), 'board tab body renders its canvas hint')
assert.ok(pageText.includes('Design'), 'board tab body renders the net sidebar')

console.log(JSON.stringify({
  ok: true,
  contributions: areas,
  facets: faces.length,
  denseFaces: denseFaces.length,
  denseGeomMs: geomMs,
  draw2d: r2.calls,
  draw3d: { fill: r3.calls.fill, lineTo: r3.calls.lineTo },
  components: view.components.length
}, null, 2))

// ---- explode ------------------------------------------------------------- //
// The exploded view has to move a part as one rigid body: if only the lid rises,
// the part just looks slightly taller and the button appears dead.
{
  const zRange = (faces) => {
    const zs = faces.flatMap((f) => f.pts.map((p) => p[2]))
    return [Math.min(...zs), Math.max(...zs)]
  }
  const flat = __test__.facetsFor(view, { explode: false, layers: {} })
  const blown = __test__.facetsFor(view, { explode: true, layers: {} })

  const boardZ = (faces) => zRange(faces.filter((f) => f.obj === 'board'))
  assert.deepEqual(boardZ(blown), boardZ(flat), 'the board does not move')

  // pick the tallest part and compare every one of its faces
  const byObject = new Map()
  for (const f of flat) {
    if (!f.obj || !f.obj.startsWith('part:')) continue
    const list = byObject.get(f.obj) || []
    list.push(f)
    byObject.set(f.obj, list)
  }
  let moved = 0
  for (const [obj, faces] of byObject) {
    const after = blown.filter((f) => f.obj === obj)
    assert.equal(after.length, faces.length, `${obj}: same faces after exploding`)
    const [z0a, z1a] = zRange(faces)
    const [z0b, z1b] = zRange(after)
    const riseBase = z0b - z0a
    const riseTop = z1b - z1a
    assert.ok(riseBase > 4, `${obj}: base rises clear of the board (${riseBase.toFixed(2)} mm)`)
    assert.ok(Math.abs(riseBase - riseTop) < 0.01,
      `${obj}: rigid body — base and top rise together (${riseBase.toFixed(2)} vs ${riseTop.toFixed(2)})`)
    moved += 1
  }
  assert.ok(moved > 5, 'several parts are lifted')

  // taller parts rise further, so the stack separates instead of moving as a slab
  const heights = [...byObject.entries()].map(([obj, faces]) => {
    const [, z1] = zRange(faces)
    const after = blown.filter((f) => f.obj === obj)
    return [z1 - zRange(faces)[0], zRange(after)[1] - z1]
  })
  const tallest = heights.reduce((a, b) => (b[0] > a[0] ? b : a))
  const shortest = heights.reduce((a, b) => (b[0] < a[0] ? b : a))
  assert.ok(tallest[1] > shortest[1], 'a taller part lifts further than a short one')

  // and the chip is a 3D control: a flat view has no depth to separate
  const flatChips = texts(__test__.BoardPage({ ctx })).join(' ')
  assert.ok(!flatChips.includes('Explode'), 'no explode chip in the 2D view')
}
