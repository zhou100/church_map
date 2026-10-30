import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { fitScore } from './churchProfile.js'
import { takeSearchPrefetch } from './api/client.js'
import {
  EMPTY_RESULTS, apiRequest, failPage, loadSnapshot, mergePage, originLabel, paramsFromQuery,
  prefetchFirstPage, queryFromParams, queryKey, resolveSort, saveSnapshot,
} from './searchScope.js'

const prefs = { languages: ['Korean'], worship: [], kids: false }
const page = (from, n, total) => Array.from({ length: n }, (_, i) => ({ id: from + i, total_count: total }))

test('a city opens as the city, measured from its approximate center', () => {
  const query = queryFromParams(new URLSearchParams('city=Oakland&state=CA'))
  assert.equal(query.scope.kind, 'city')
  assert.equal(resolveSort(query, { languages: [], worship: [], kids: false }), 'distance')
  assert.equal(originLabel(query), 'the approximate center of Oakland')
  // A known visitor location doesn't change how a city is measured (one
  // cacheable URL per city); it is offered as a center for nearby cities.
  const withYou = queryFromParams(new URLSearchParams('city=Oakland&state=CA&lat=37.8&lon=-122.2'))
  assert.equal(withYou.scope.kind, 'city')
  assert.equal(originLabel(withYou), 'the approximate center of Oakland')
  assert.equal(apiRequest(withYou, prefs).options.origin, undefined)
  const circle = queryFromParams(new URLSearchParams('city=Oakland&state=CA&near=1&clat=37.8&clon=-122.2&center=you&miles=10'))
  assert.equal(originLabel(circle), 'your approximate location')
})

test('For you turns on by itself with saved preferences; a chosen sort sticks', () => {
  const none = { languages: [], worship: [], kids: false }
  const auto = queryFromParams(new URLSearchParams('city=Oakland&state=CA'))
  assert.equal(resolveSort(auto, prefs), 'forYou')
  assert.equal(apiRequest(auto, prefs).options.sort, 'for_you')
  assert.equal(resolveSort(auto, none), 'distance')
  // The visitor picked Nearest: saved preferences no longer override it.
  const chosen = queryFromParams(new URLSearchParams('city=Oakland&state=CA&sort=nearest'))
  assert.equal(resolveSort(chosen, prefs), 'distance')
  assert.equal(apiRequest(chosen, prefs).options.prefs, null)
  // A name search keeps best match unless For you is picked.
  assert.equal(resolveSort(queryFromParams(new URLSearchParams('name=Grace')), prefs), 'relevance')
  // Auto and an explicit pick of the same order are the same list.
  assert.equal(queryKey(auto, prefs), queryKey({ ...auto, sort: 'forYou' }, prefs))
})

test('the prefetched first page is the exact request Search makes', async t => {
  const urls = []
  t.mock.method(globalThis, 'fetch', async url => { urls.push(url); return { ok: true, json: async () => [] } })
  globalThis.window = {}
  t.after(() => { delete globalThis.window })
  const params = new URLSearchParams('city=Oakland&state=CA')
  prefetchFirstPage(params, prefs)
  const query = queryFromParams(params)
  assert.ok(takeSearchPrefetch(queryKey(query, prefs)))
  assert.equal(new URL(urls[0], 'https://x').searchParams.get('sort'), 'for_you')
  assert.equal(new URL(urls[0], 'https://x').searchParams.get('prefer_language'), 'Korean')
  // Different preferences are a different list; that prefetch is not reused.
  prefetchFirstPage(params, prefs)
  assert.equal(takeSearchPrefetch(queryKey(query, { ...prefs, kids: true })), null)
})

test('scope, center, distance and sort survive the URL', () => {
  for (const qs of [
    'city=Oakland&state=CA',
    'city=Oakland&state=CA&sort=nearest',
    'city=Oakland&state=CA&lat=37.8&lon=-122.2&sort=for_you',
    'city=Oakland&state=CA&near=1&clat=37.8&clon=-122.27&center=city&miles=25',
    'name=Grace&sort=for_you',
  ]) {
    assert.equal(paramsFromQuery(queryFromParams(new URLSearchParams(qs))).toString(), new URLSearchParams(qs).toString())
  }
  // A malformed circle falls back to the city, never to a default radius.
  assert.equal(queryFromParams(new URLSearchParams('city=A&state=ZZ&near=1&clat=nan')).scope.kind, 'city')
  assert.equal(queryFromParams(new URLSearchParams('city=A&state=ZZ&near=1&clat=1&clon=2&miles=7')).scope.miles, 10)
})

test('preferences only change the list while For you ranks it', () => {
  const query = queryFromParams(new URLSearchParams('city=A&state=ZZ&sort=nearest'))
  assert.equal(queryKey(query, prefs), queryKey(query, { ...prefs, kids: true }))
  const forYou = { ...query, sort: 'forYou' }
  assert.notEqual(queryKey(forYou, prefs), queryKey(forYou, { ...prefs, kids: true }))
  assert.equal(queryKey(forYou, prefs), queryKey(forYou, { ...prefs, languages: ['korean'] }))
})

test('pages append in order without repeats and stop at the total', () => {
  let state = mergePage({ ...EMPTY_RESULTS, status: 'loading' }, page(1, 20, 45), { offset: 0 })
  assert.deepEqual([state.rows.length, state.total, state.hasMore, state.nextOffset], [20, 45, true, 20])
  // A row that shifted onto page two is not shown twice.
  state = mergePage(state, [{ id: 20, total_count: 45 }, ...page(21, 19, 45)], { offset: 20 })
  assert.deepEqual([state.rows.length, state.nextOffset, state.hasMore], [39, 40, true])
  state = mergePage(state, page(40, 5, 45), { offset: 40 })
  assert.deepEqual([state.rows.length, state.hasMore], [44, false])
  assert.equal(new Set(state.rows.map(row => row.id)).size, state.rows.length)
})

test('a failed next page keeps the loaded rows; a failed first page shows none', () => {
  const loaded = mergePage(EMPTY_RESULTS, page(1, 20, 60), { offset: 0 })
  const failed = failPage({ ...loaded, status: 'more' }, 'Service unavailable', { offset: 20 })
  assert.equal(failed.rows.length, 20)
  assert.equal(failed.status, 'moreError')
  assert.equal(failed.hasMore, true)
  assert.equal(failPage(loaded, 'x', { offset: 0 }).rows, null)
})

test('an empty or short first page has an exact total', () => {
  assert.deepEqual(mergePage(EMPTY_RESULTS, [], { offset: 0 }).total, 0)
  assert.equal(mergePage(EMPTY_RESULTS, [{ id: 1 }], { offset: 0 }).hasMore, false)
})

test('returning restores only the same query, and not a stale one', () => {
  const store = new Map()
  const storage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
  saveSnapshot({ key: 'a', rows: [{ id: 1 }], scrollTop: 640 }, storage)
  assert.equal(loadSnapshot('a', storage).scrollTop, 640)
  assert.equal(loadSnapshot('b', storage), null)
  assert.equal(loadSnapshot('a', storage, Date.now() + 31 * 60 * 1000), null)
  assert.equal(loadSnapshot('a', { getItem: () => { throw new Error('blocked') } }), null)
})

test('fitScore counts the same evidence as the server For you ranking', () => {
  const { prefs: parityPrefs, cases } = JSON.parse(readFileSync(new URL('./fitParityCases.json', import.meta.url)))
  for (const c of cases) {
    // As the list API returns it: verified languages split, review tags derived.
    const reviews = c.reviews || []
    const row = {
      ...c,
      service_languages: (c.service_languages || '').split(';').map(s => s.trim()).filter(Boolean),
      tags: reviews.length >= 3 && reviews.reduce((a, b) => a + b, 0) / reviews.length > 4 ? ['Kids programs'] : [],
    }
    assert.equal(fitScore(row, parityPrefs), c.score, c.name)
  }
})
