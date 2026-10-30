import assert from 'node:assert/strict'
import { test } from 'node:test'
import { previewKey, previewStatus, previewStep } from './landingPreview.js'

const NONE = { languages: [], worship: [], kids: false }
const SPANISH = { languages: ['Spanish'], worship: [], kids: false }
const KIDS = { languages: [], worship: [], kids: true }
const PLACE = { city: 'Brooklyn', state: 'NY' }

// The page as previewStep sees it, driven the way Landing drives it: after
// every event, act on the step until it settles. A request that is replaced
// or cancelled is aborted and never answers.
function page(savedPrefs) {
  const s = { place: null, prefs: savedPrefs, loaded: undefined, pending: undefined, failed: undefined, rows: [], log: [] }
  const want = () => (s.place ? previewKey(s.place, s.prefs) : null)
  function settle() {
    for (let i = 0; i < 5; i++) {
      const step = previewStep({ want: want(), loaded: s.loaded, pending: s.pending, failed: s.failed })
      if (step.type === 'idle') return
      if (step.type === 'cancel') s.pending = undefined
      if (step.type === 'request') { s.pending = step.key; s.log.push(step.key) }
    }
    throw new Error('previewStep did not settle')
  }
  const events = {
    place() { s.place = PLACE },
    prefs(next) { s.prefs = next; s.failed = undefined },
    answer() {
      if (s.pending === undefined) return
      const key = s.pending
      s.pending = undefined
      if (key === want()) { s.loaded = key; s.rows = [key] }
    },
    fail() {
      if (s.pending === undefined) return
      s.failed = s.pending
      s.pending = undefined
    },
  }
  return {
    state: s, want,
    run(name, arg) { events[name](arg); settle() },
    // Let every request in flight answer, as the network eventually does.
    drain() { for (let i = 0; i < 10 && s.pending !== undefined; i++) this.run('answer') },
    status() { return previewStatus({ want: want(), loaded: s.loaded, failed: s.failed, rows: s.rows }) },
  }
}

test('the review case: saved Spanish, first answer held, Clear, then the answer arrives', () => {
  const p = page(SPANISH)
  p.run('place')
  assert.equal(p.state.pending, previewKey(PLACE, SPANISH))
  p.run('prefs', NONE)
  // The Spanish request is replaced at once by the one the page now wants.
  assert.equal(p.state.pending, previewKey(PLACE, NONE))
  p.drain()
  assert.equal(p.state.loaded, previewKey(PLACE, NONE))
  assert.equal(p.status(), 'ready')
})

test('preferences picked before the city is known are what the first request asks for', () => {
  const p = page(NONE)
  p.run('prefs', SPANISH)
  assert.equal(p.state.pending, undefined)
  p.run('place')
  assert.deepEqual(p.state.log, [previewKey(PLACE, SPANISH)])
})

test('every interleaving of first load, Select, Clear, answers and failures settles on what is shown', () => {
  // Up to six events after the city arrives, from saved Spanish or none.
  const moves = [['prefs', NONE], ['prefs', SPANISH], ['prefs', KIDS], ['answer'], ['fail']]
  let sequences = 0
  function walk(saved, before, path) {
    if (path.length > 6) return
    const p = page(saved)
    for (const [name, arg] of before) p.run(name, arg)
    p.run('place')
    for (const [name, arg] of path) p.run(name, arg)
    p.drain()
    sequences++
    const want = p.want()
    const label = JSON.stringify({ saved, before, path })
    // Settled: the rows are ranked for the preferences on screen, or the
    // last request for them failed and the page says so. Never stuck loading.
    if (p.state.failed === want) {
      assert.equal(p.state.pending, undefined, label)
      assert.notEqual(p.status(), 'loading', label)
    } else {
      assert.equal(p.state.loaded, want, label)
      assert.notEqual(p.status(), 'loading', label)
    }
    for (const move of moves) walk(saved, before, [...path, move])
  }
  for (const saved of [NONE, SPANISH]) {
    walk(saved, [], [])
    walk(saved, [['prefs', saved === NONE ? SPANISH : NONE]], [])
  }
  assert.ok(sequences > 10000, `${sequences} sequences`)
})

test('a failed re-rank keeps the picks already shown', () => {
  const p = page(NONE)
  p.run('place')
  p.run('answer')
  p.run('prefs', SPANISH)
  p.run('fail')
  assert.equal(p.status(), 'ready')
  assert.equal(p.state.pending, undefined)
  // A failed first load says so instead of loading forever.
  const q = page(NONE)
  q.run('place')
  q.run('fail')
  assert.equal(q.status(), 'error')
})

test('no-preference keys never collide with "nothing loaded yet"', () => {
  assert.notEqual(previewKey(PLACE, NONE), undefined)
  assert.equal(previewStep({ want: previewKey(PLACE, NONE), loaded: undefined, pending: undefined }).type, 'request')
})
