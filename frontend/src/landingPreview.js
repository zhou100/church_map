import { hasPreferences } from './preferences.js'

// Landing's "Start here" rows: one page for one city, ranked for one set of
// preferences. Every request is identified by a key for (city, preferences),
// so "nothing loaded yet" (undefined) can never be mistaken for "loaded with
// no preferences" (a key like "Brooklyn|NY|").
//
// The page holds four facts and asks previewStep what to do whenever any of
// them changes, including when a request ends:
//   want     the key for the city and preferences on screen (null: no city)
//   loaded   the key the shown rows were ranked for (undefined: none yet)
//   pending  the key of the request in flight (undefined: none)
//   failed   the key whose last request failed (so it isn't retried in a loop)
// Only a response whose key is still `want` may replace the rows.

export function previewKey(place, prefs) {
  return `${place.city}|${place.state}|${hasPreferences(prefs) ? JSON.stringify(prefs) : ''}`
}

// { type: 'idle' } | { type: 'cancel' } | { type: 'request', key, delay }
// A request replaces (aborts) whatever is in flight. The first load for a
// city goes at once; a re-rank waits for the visitor to pause on the chips.
export function previewStep({ want, loaded, pending, failed }) {
  if (want == null) return { type: 'idle' }
  if (loaded === want) return pending !== undefined ? { type: 'cancel' } : { type: 'idle' }
  if (pending === want || failed === want) return { type: 'idle' }
  return { type: 'request', key: want, delay: loaded === undefined ? 0 : 300 }
}

export function previewStatus({ want, loaded, failed, rows }) {
  if (want == null) return 'idle'
  if (loaded !== undefined) return rows.length ? 'ready' : 'empty'
  return failed === want ? 'error' : 'loading'
}
