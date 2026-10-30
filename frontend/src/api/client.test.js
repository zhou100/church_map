import assert from 'node:assert/strict'
import { test } from 'node:test'
import { listChurches } from './client.js'
import { zeroMatchSentence } from '../churchProfile.js'
import { apiRequest, queryFromParams } from '../searchScope.js'

const prefs = { languages: ['Vietnamese'], worship: [], kids: true }

function capture(t, page = []) {
  const urls = []
  t.mock.method(globalThis, 'fetch', async url => {
    urls.push(new URL(url, 'https://test.local').searchParams)
    return { ok: true, json: async () => page }
  })
  return urls
}

test('a city search asks for one page of the city, never every page', async t => {
  const urls = capture(t, Array.from({ length: 20 }, (_, id) => ({ id })))
  const query = queryFromParams(new URLSearchParams('city=San Francisco&state=CA'))
  const { search, options } = apiRequest(query, { languages: [], worship: [], kids: false })
  const rows = await listChurches(search, { ...options, limit: 20 })
  assert.equal(rows.length, 20)
  assert.equal(urls.length, 1)
  assert.equal(urls[0].get('city'), 'San Francisco')
  assert.equal(urls[0].get('sort'), 'nearest')
  // The city is the scope; no circle that would pull in nearby cities.
  for (const key of ['radius_miles', 'lat', 'lon', 'prefer_language']) assert.equal(urls[0].has(key), false)
})

test('For you sends preferences so the server ranks the whole city before page one', async t => {
  const urls = capture(t)
  const query = { ...queryFromParams(new URLSearchParams('city=San Francisco&state=CA&lat=37.7&lon=-122.4')), sort: 'forYou' }
  const { search, options } = apiRequest(query, prefs)
  await listChurches(search, { ...options, limit: 20, offset: 40 })
  assert.equal(urls[0].get('sort'), 'for_you')
  assert.deepEqual(urls[0].getAll('prefer_language'), ['Vietnamese'])
  assert.equal(urls[0].get('prefer_kids'), 'true')
  assert.equal(urls[0].get('offset'), '40')
  // A known visitor location stays out of a city request: the city is the
  // scope and its center the origin, so every visitor shares one cached URL.
  assert.equal(urls[0].has('lat'), false)
  assert.equal(urls[0].has('radius_miles'), false)
})

test('a nearby search keeps its chosen center and distance on every page', async t => {
  const urls = capture(t)
  const query = queryFromParams(new URLSearchParams('city=San Mateo&state=CA&near=1&clat=37.56&clon=-122.32&center=city&miles=25&sort=nearest'))
  for (const offset of [0, 20]) {
    const { search, options } = apiRequest(query, prefs)
    await listChurches(search, { ...options, limit: 20, offset })
  }
  for (const params of urls) {
    assert.equal(params.get('lat'), '37.56')
    assert.equal(params.get('lon'), '-122.32')
    assert.equal(params.get('radius_miles'), '25')
    assert.equal(params.has('city'), false)
    assert.equal(params.has('prefer_language'), false)
  }
})

test('a request can be abandoned when the visitor changes scope or sort', async t => {
  let seen
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    seen = options.signal
    return { ok: true, json: async () => [] }
  })
  const ctrl = new AbortController()
  await listChurches({ type: 'location', city: 'A', state: 'ZZ' }, { signal: ctrl.signal })
  assert.equal(seen, ctrl.signal)
})

test('no match on page one of a server-ranked list is not "more may match"', () => {
  const rows = Array.from({ length: 20 }, (_, id) => ({ id, website_summary: 'A church.' }))
  const ranked = zeroMatchSentence(rows, prefs, { city: 'San Francisco', limit: 20, ranked: true })
  assert.doesNotMatch(ranked, /may match|loaded/)
  assert.doesNotMatch(ranked, /\d+ churches/)
  assert.match(zeroMatchSentence(rows, prefs, { city: 'San Francisco', limit: 20 }), /loaded/)
})

test('name-derived language cannot satisfy a service-language preference', () => {
  const rows = [{ id: 1, language: 'Vietnamese', cultural_background: 'Vietnamese', website_summary: 'x' }]
  assert.match(zeroMatchSentence(rows, prefs, { city: 'X', limit: 2 }), /None|doesn't mention/)
})
