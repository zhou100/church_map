import { hasPreferences } from './preferences.js'
import { SEARCH_PAGE, listChurches, prefetchSearch } from './api/client.js'

// What Search is showing and how it pages. One query is a scope (a city, a
// circle the visitor chose, or a name), a sort and, for "For you", the
// preferences. Pages only ever append inside that query; widening to nearby
// cities is a different query the visitor starts on purpose.
//
// `sort` stays null until the visitor picks one. While it is null, a city or
// circle ranks "For you" whenever preferences are saved and nearest-first
// otherwise, and a name search keeps its best-match order. A pick is kept in
// the URL, so it survives a reload and Back.

export const PAGE_SIZE = SEARCH_PAGE
// URL and API names: `nearest` is the API's distance order.
const SORT_PARAM = { forYou: 'for_you', distance: 'nearest', relevance: 'relevance' }
const SORT_FROM_PARAM = { for_you: 'forYou', nearest: 'distance', relevance: 'relevance' }
export const NEARBY_MILES = [5, 10, 25, 50]
const SNAPSHOT_KEY = 'churchmap_search_snapshot'
const SNAPSHOT_TTL_MS = 30 * 60 * 1000

function coord(params, latKey, lonKey) {
  const lat = Number(params.get(latKey)), lon = Number(params.get(lonKey))
  return params.get(latKey) !== null && params.get(lonKey) !== null
    && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
    ? { lat, lon } : null
}

// URL → query. `you` is the visitor's approximate (IP-based) location when
// they asked for it, offered as a center for nearby cities. A city itself is
// always measured from its approximate center, so every visitor's request for
// a city is the same URL (the list cache and the landing prefetch rely on it).
export function queryFromParams(params) {
  const sort = SORT_FROM_PARAM[params.get('sort')] ?? null
  const name = params.get('name')?.trim()
  if (name) return { scope: { kind: 'name', name }, sort: sort === 'distance' ? null : sort, you: null }
  const city = params.get('city')?.trim(), state = params.get('state')?.trim()
  if (!city || !state) return null
  const you = coord(params, 'lat', 'lon')
  const center = coord(params, 'clat', 'clon')
  const miles = Number(params.get('miles'))
  if (params.get('near') === '1' && center) {
    return {
      scope: {
        kind: 'nearby', city, state, center,
        centerSource: params.get('center') === 'you' ? 'you' : 'city',
        miles: NEARBY_MILES.includes(miles) ? miles : 10,
      },
      sort: sort === 'relevance' ? null : sort, you,
    }
  }
  return { scope: { kind: 'city', city, state }, sort: sort === 'relevance' ? null : sort, you }
}

export function paramsFromQuery({ scope, sort, you }) {
  const params = new URLSearchParams()
  if (scope.kind === 'name') {
    params.set('name', scope.name)
  } else {
    params.set('city', scope.city)
    params.set('state', scope.state)
    if (you) {
      params.set('lat', String(you.lat))
      params.set('lon', String(you.lon))
    }
    if (scope.kind === 'nearby') {
      params.set('near', '1')
      params.set('clat', String(scope.center.lat))
      params.set('clon', String(scope.center.lon))
      params.set('center', scope.centerSource)
      params.set('miles', String(scope.miles))
    }
  }
  if (sort) params.set('sort', SORT_PARAM[sort])
  return params
}

export function resolveSort(query, prefs) {
  if (query.sort) return query.sort
  if (query.scope.kind === 'name') return 'relevance'
  return hasPreferences(prefs) ? 'forYou' : 'distance'
}

// Arguments for listChurches. The server ranks the whole scope before paging.
export function apiRequest(query, prefs) {
  const { scope } = query
  const sort = resolveSort(query, prefs)
  const apiSort = sort === 'forYou' ? 'for_you' : scope.kind === 'name' ? undefined : 'nearest'
  const search = scope.kind === 'name' ? { type: 'name', name: scope.name }
    : scope.kind === 'nearby'
      ? { type: 'location', city: scope.city, state: scope.state, lat: scope.center.lat, lon: scope.center.lon, radiusMiles: scope.miles }
      : { type: 'location', city: scope.city, state: scope.state }
  return {
    search,
    options: {
      sort: apiSort,
      prefs: sort === 'forYou' ? prefs : null,
    },
  }
}

function prefsKey(prefs) {
  return JSON.stringify([
    [...prefs.languages].map(language => language.toLowerCase()).sort(),
    [...prefs.worship].sort(),
    prefs.kids,
  ])
}

// Identifies one result list: the scope and the sort in effect, plus the
// preferences while "For you" ranks.
export function queryKey(query, prefs) {
  const sort = resolveSort(query, prefs)
  return `${paramsFromQuery({ ...query, sort })}${sort === 'forYou' ? `|${prefsKey(prefs)}` : ''}`
}

// Where distances are measured from, in words.
export function originLabel(query) {
  if (!query || query.scope.kind === 'name') return null
  const fromYou = query.scope.kind === 'nearby' && query.scope.centerSource === 'you'
  return fromYou ? 'your approximate location' : `the approximate center of ${query.scope.city}`
}

export const EMPTY_RESULTS = Object.freeze({
  key: null, rows: null, total: null, nextOffset: 0, hasMore: false, status: 'idle', error: null,
})

// Fold one page into the loaded list. Rows already loaded are not repeated if
// the data shifted between requests; the next offset follows the server.
export function mergePage(prev, page, { offset, pageSize = PAGE_SIZE }) {
  const base = offset === 0 ? [] : prev.rows || []
  const seen = new Set(base.map(row => row.id))
  const rows = [...base, ...page.filter(row => !seen.has(row.id) && seen.add(row.id))]
  const total = page.length && page[0].total_count != null ? page[0].total_count
    : offset === 0 ? (page.length < pageSize ? page.length : null) : prev.total
  const nextOffset = offset + page.length
  return {
    ...prev, rows, total, nextOffset, status: 'idle', error: null,
    hasMore: page.length === pageSize && (total == null || nextOffset < total),
  }
}

// A failed next page keeps every loaded row and offers a retry.
export function failPage(prev, error, { offset }) {
  return offset === 0
    ? { ...prev, rows: null, status: 'error', error }
    : { ...prev, status: 'moreError', error }
}

// Coming back from a church page restores the same list and scroll position
// instead of re-reading page one. Storage may be unavailable; then the
// search simply runs again.
export function saveSnapshot(snapshot, storage) {
  try {
    (storage ?? globalThis.sessionStorage).setItem(SNAPSHOT_KEY, JSON.stringify({ ...snapshot, savedAt: Date.now() }))
  } catch { /* Optional. */ }
}

export function loadSnapshot(key, storage, now = Date.now()) {
  try {
    const snapshot = JSON.parse((storage ?? globalThis.sessionStorage).getItem(SNAPSHOT_KEY))
    if (!snapshot || snapshot.key !== key || !Array.isArray(snapshot.rows)) return null
    if (!(now - snapshot.savedAt < SNAPSHOT_TTL_MS)) return null
    return snapshot
  } catch {
    return null
  }
}

// Start page one of the search a URL describes, before Search itself loads,
// unless Search will restore it from a snapshot instead.
export function prefetchFirstPage(params, prefs) {
  const query = queryFromParams(params)
  if (!query) return
  const key = queryKey(query, prefs)
  if (loadSnapshot(key)) return
  const { search, options } = apiRequest(query, prefs)
  prefetchSearch(key, search, options)
}

// Page one of a query: the prefetched request when it is the same one.
export function firstPage(prefetched, search, options) {
  return (prefetched || Promise.reject(new Error('none')))
    .catch(() => listChurches(search, { ...options, offset: 0 }))
}
