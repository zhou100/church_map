import { test } from 'node:test'
import assert from 'node:assert/strict'
import { keepFitted, overlayPadding } from './mapFit.js'

// Just enough of a Leaflet map: events by space-separated name.
function fakeMap() {
  const handlers = new Map()
  return {
    invalidated: 0,
    on(names, fn) { for (const name of names.split(' ')) handlers.set(name, fn) },
    off(names) { for (const name of names.split(' ')) handlers.delete(name) },
    fire(name) { handlers.get(name)?.() },
    invalidateSize() { this.invalidated += 1 },
    listening: () => handlers.size,
  }
}

function fakeObserver() {
  const instances = []
  class Observer {
    constructor(callback) { this.callback = callback; this.observed = []; instances.push(this) }
    observe(element) { this.observed.push(element) }
    disconnect() { this.disconnected = true }
  }
  return { Observer, resize: () => instances.forEach(o => o.callback()), instances }
}

// A fit moves the map without animation, so Leaflet fires inside the call.
function setup() {
  const map = fakeMap()
  const observer = fakeObserver()
  let fits = 0
  const fit = () => { fits += 1; map.fire('movestart'); map.fire('zoomstart') }
  const stop = keepFitted(map, fit, ['map', null, 'card'], observer.Observer)
  return { map, observer, stop, fits: () => fits }
}

test('overlayPadding: beside a narrow card, below a full-width one', () => {
  const mapRect = { left: 0, top: 0, width: 1366 }
  assert.deepEqual(overlayPadding(mapRect, { right: 560, bottom: 700, width: 440 }), [608, 48])
  assert.deepEqual(overlayPadding({ left: 0, top: 0, width: 375 }, { right: 363, bottom: 663, width: 351 }), [32, 695])
  assert.deepEqual(overlayPadding(mapRect, undefined), [48, 48])
})

test('keepFitted: fits now and again when the card or map resizes', () => {
  const { map, observer, fits } = setup()
  assert.equal(fits(), 1)
  assert.deepEqual(observer.instances[0].observed, ['map', 'card'])
  observer.resize()
  assert.equal(map.invalidated, 1)
  assert.equal(fits(), 2, 'its own moves are not taken for the visitor’s')
})

test('keepFitted: after the visitor pans or zooms, a resize only resizes', () => {
  for (const event of ['movestart', 'zoomstart']) {
    const { map, observer, fits } = setup()
    map.fire(event)
    observer.resize()
    assert.equal(map.invalidated, 1)
    assert.equal(fits(), 1)
  }
})

test('keepFitted: stopping disconnects and unsubscribes', () => {
  const { map, observer, stop } = setup()
  stop()
  assert.equal(observer.instances[0].disconnected, true)
  assert.equal(map.listening(), 0)
})

test('keepFitted: without ResizeObserver it still fits once', () => {
  const map = fakeMap()
  let fits = 0
  keepFitted(map, () => { fits += 1 }, ['map'], null)
  assert.equal(fits, 1)
})
