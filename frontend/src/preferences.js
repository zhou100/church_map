// What a visitor told us matters to them ("Make these fit you"). Kept in this
// browser only; nothing is sent anywhere. Plan:
// docs/plans/landing_fit_preferences_plan.md.
//
// Stored under one key for every city: language and kids don't change when
// someone looks at a different town.

export const PREFERENCES_KEY = 'churchmap_preferences'

// The `worship_style` buckets the extractor emits
// (backend/scrapers_v2/prompts/website_v3.py), with the chip label and the
// word used in a sentence ("hymn-led worship").
export const WORSHIP_STYLES = [
  { value: 'liturgical', label: 'Liturgical', phrase: 'liturgical' },
  { value: 'traditional-hymns', label: 'Hymns', phrase: 'hymn-led' },
  { value: 'blended', label: 'Blended', phrase: 'blended' },
  { value: 'contemporary', label: 'Contemporary', phrase: 'contemporary' },
  { value: 'charismatic', label: 'Charismatic', phrase: 'charismatic' },
]
const WORSHIP_VALUES = new Set(WORSHIP_STYLES.map(style => style.value))
const MAX_LANGUAGES = 10

export const EMPTY_PREFERENCES = Object.freeze({ languages: [], worship: [], kids: false })

function uniqueBy(values, key) {
  const seen = new Set()
  return values.filter(value => {
    const k = key(value)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

// Anything read back from storage passes through here, so an older build's
// shape or a hand-edited value can't reach the ranking.
export function normalizePreferences(raw) {
  if (!raw || typeof raw !== 'object') return { ...EMPTY_PREFERENCES }
  const languages = Array.isArray(raw.languages)
    ? uniqueBy(
      raw.languages
        .filter(language => typeof language === 'string')
        .map(language => language.trim())
        .filter(language => language && language.length <= 40),
      language => language.toLowerCase(),
    ).slice(0, MAX_LANGUAGES)
    : []
  const worship = Array.isArray(raw.worship)
    ? [...new Set(raw.worship.filter(style => WORSHIP_VALUES.has(style)))]
    : []
  return { languages, worship, kids: raw.kids === true }
}

export function hasPreferences(prefs) {
  return Boolean(prefs && (prefs.languages.length || prefs.worship.length || prefs.kids))
}

// Storage can throw (private windows, blocked site data). Then preferences
// last for this page view only, and nothing is said about it.
export function loadPreferences(storage = globalThis.localStorage) {
  try {
    return normalizePreferences(JSON.parse(storage.getItem(PREFERENCES_KEY)))
  } catch {
    return { ...EMPTY_PREFERENCES }
  }
}

export function savePreferences(prefs, storage = globalThis.localStorage) {
  try {
    if (hasPreferences(prefs)) {
      storage.setItem(PREFERENCES_KEY, JSON.stringify({ ...prefs, updated_at: new Date().toISOString() }))
    } else {
      storage.removeItem(PREFERENCES_KEY)
    }
  } catch {
    // Kept in memory for this page view.
  }
}

export function worshipLabel(value) {
  return WORSHIP_STYLES.find(style => style.value === value)?.label ?? value
}

function worshipPhrase(value) {
  return WORSHIP_STYLES.find(style => style.value === value)?.phrase ?? value
}

// "Spanish · Contemporary · Kids" for the summary row.
export function preferenceSummary(prefs) {
  return [
    ...prefs.languages,
    ...prefs.worship.map(worshipLabel),
    ...(prefs.kids ? ['Kids'] : []),
  ].join(' · ')
}

function joinWith(items, joiner) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} ${joiner} ${items[items.length - 1]}`
}

// "Korean services or a kids program" / "Spanish services and contemporary
// worship", for sentences about what matched or didn't.
export function preferencePhrase(prefs, joiner = 'or') {
  const parts = []
  if (prefs.languages.length) parts.push(`${joinWith(prefs.languages, joiner)} services`)
  if (prefs.worship.length) {
    parts.push(`${joinWith(prefs.worship.map(worshipPhrase), joiner)} worship`)
  }
  if (prefs.kids) parts.push('a kids program')
  return joinWith(parts, joiner)
}
