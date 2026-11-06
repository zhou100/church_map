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

// The age bands a family can ask about, as church_programs stores them
// (migration 0007; backend/db/repository.py KID_BANDS). Young adults are a
// band there too, but never an answer to "we're bringing kids".
export const KID_BANDS = [
  { value: 'preschool', label: 'Under 5', phrase: 'children under 5', heading: 'Babies & preschool (0–5)' },
  { value: 'children', label: 'K–5th grade', phrase: 'kids in K–5th grade', heading: 'Children (K–5th grade)' },
  { value: 'youth', label: '6th–12th grade', phrase: 'students in 6th–12th grade', heading: 'Youth (6th–12th grade)' },
]
const BAND_VALUES = KID_BANDS.map(band => band.value)

export const NO_KIDS = Object.freeze({ bands: Object.freeze([]), weekday_care: false })
export const EMPTY_PREFERENCES = Object.freeze({ languages: [], worship: [], kids: NO_KIDS })

// { bands, weekday_care } from any kids value. A build before age bands
// saved `kids: true`; that meant any age, and still does.
export function kidsNeed(kids) {
  if (kids === true) return { bands: [...BAND_VALUES], weekday_care: false }
  if (!kids || typeof kids !== 'object') return { bands: [], weekday_care: false }
  const bands = Array.isArray(kids.bands) ? BAND_VALUES.filter(band => kids.bands.includes(band)) : []
  return { bands, weekday_care: kids.weekday_care === true }
}

function asksAboutKids(kids) {
  const need = kidsNeed(kids)
  return need.bands.length > 0 || need.weekday_care
}

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
  return { languages, worship, kids: kidsNeed(raw.kids) }
}

export function hasPreferences(prefs) {
  return Boolean(prefs && (prefs.languages.length || prefs.worship.length || asksAboutKids(prefs.kids)))
}

// Storage can throw (private windows, blocked site data), and so can reading
// `localStorage` itself, which is why it is looked up inside the try and not
// as a default parameter. Then preferences last for this page view only, and
// nothing is said about it.
export function loadPreferences(storage) {
  try {
    const store = storage ?? globalThis.localStorage
    return normalizePreferences(JSON.parse(store.getItem(PREFERENCES_KEY)))
  } catch {
    return { ...EMPTY_PREFERENCES }
  }
}

export function savePreferences(prefs, storage) {
  try {
    const store = storage ?? globalThis.localStorage
    if (hasPreferences(prefs)) {
      store.setItem(PREFERENCES_KEY, JSON.stringify({ ...prefs, updated_at: new Date().toISOString() }))
    } else {
      store.removeItem(PREFERENCES_KEY)
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

function bandLabel(value) {
  return KID_BANDS.find(band => band.value === value)?.label ?? value
}

// "Spanish · Contemporary · Under 5 · Weekday childcare" for the summary row.
export function preferenceSummary(prefs) {
  const need = kidsNeed(prefs.kids)
  const anyAge = need.bands.length === BAND_VALUES.length
  return [
    ...prefs.languages,
    ...prefs.worship.map(worshipLabel),
    ...(anyAge ? ['Kids'] : need.bands.map(bandLabel)),
    ...(need.weekday_care ? ['Weekday childcare'] : []),
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
  const need = kidsNeed(prefs.kids)
  if (need.bands.length === BAND_VALUES.length) parts.push('a kids program')
  else if (need.bands.length) {
    const phrases = need.bands.map(value => KID_BANDS.find(band => band.value === value).phrase)
    parts.push(`programs for ${joinWith(phrases, joiner)}`)
  }
  if (need.weekday_care) parts.push('weekday childcare')
  return joinWith(parts, joiner)
}
