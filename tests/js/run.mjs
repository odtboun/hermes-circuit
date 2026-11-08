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
export const useQuery = () => ({ isLoading: false, error: null, data: globalThis.__QUERY_DATA })
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

// ---- canvas renderers ---------------------------------------------------- //
function recordingContext() {
  const calls = {}
  const handler = {
    get(target, prop) {
      if (prop in target) return target[prop]
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

const r3 = recordingContext()
__test__.drawBoard3D(r3.ctx, view, { canvas, dpr: 2, explode: false, alpha: 1, yaw: -0.6, pitch: 0.9, dist: 120 })
assert.ok(r3.calls.lineTo > 100, 'facets should be projected and filled')
assert.ok(r3.calls.fill >= faces.length - 5, 'each visible facet is filled')

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
  draw2d: r2.calls,
  draw3d: { fill: r3.calls.fill, lineTo: r3.calls.lineTo },
  components: view.components.length
}, null, 2))
