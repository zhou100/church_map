import { KID_BANDS, hasPreferences, kidsNeed, preferencePhrase, worshipLabel } from './preferences.js'

export function hasWebsiteProfile(church) {
  const extracted = church.extracted_tags || {}
  return Boolean(
    church.website_summary ||
    Object.values(extracted).some(value => Array.isArray(value) ? value.length : value)
  )
}

// Churches we've actually read first, then the ones people have reviewed.
export function byProfileUsefulness(a, b) {
  const profileDifference = Number(hasWebsiteProfile(b)) - Number(hasWebsiteProfile(a))
  if (profileDifference) return profileDifference
  return (b.review_count ?? 0) - (a.review_count ?? 0)
}

// The directory's source lists (IRS, OSM) include every house of worship.
// They stay on the map, but they are not where we point someone looking for
// a church. Each entry matches the start of a word in `denomination`, so this
// covers every `out_of_scope` label in analytics/dbt/seeds/denomination_scope.csv
// (churchProfile.test.js checks that) plus labels the seed doesn't list yet.
// Entries must not hit an in-scope label: 'scientolog', never 'scientist',
// which would catch Christian Science.
const NOT_A_CHURCH = [
  'jewish', 'judaism', 'synagogue', 'kabbalah', 'islam', 'muslim', 'mosque',
  'ahmadi', 'hindu', 'krishna', 'vaishnav', 'buddhist', 'zen', 'sikh', 'jain',
  'baha', 'bahá', 'taoist', 'confucian', 'shinto', 'tenrikyo', 'zoroastrian',
  'pagan', 'wicca', 'shaman', 'voodoo', 'vodou', 'eckankar', 'falun gong',
  'scientolog', 'spiritualist', 'spiritist', 'spiritual science',
  'religious science', 'unitarian universalist', 'ethical', 'rastafari',
]
const NOT_A_CHURCH_PATTERN = new RegExp(`(^|[^a-z])(${NOT_A_CHURCH.join('|')})`)

// D-1 keeps Messianic Jewish congregations in scope; 'jewish' alone would not.
const MESSIANIC = /messianic|jews for jesus|hebrew christian/

export function isChurch(church) {
  const denomination = (church.denomination || '').toLowerCase()
  return MESSIANIC.test(denomination) || !NOT_A_CHURCH_PATTERN.test(denomination)
}

function hasValue(value) {
  return Array.isArray(value)
    ? value.length > 0
    : typeof value === 'string' ? value.trim() !== '' : Boolean(value)
}

// Anything a newcomer could read before a first visit: what people say, when
// to go, what the church says about itself, or a fact we verified. The
// non-verified fields are the ones that score above zero in
// STARTING_POINT_SCORE (backend/db/repository.py).
function hasSomethingToShow(church) {
  const extracted = church.extracted_tags || {}
  return (church.review_count ?? 0) > 0
    || hasValue(church.service_times)
    || hasValue(church.website_summary)
    || hasValue(church.kids_program)
    || hasValue(church.service_languages)
    || ['service_languages', 'worship_style', 'programs', 'theological_stance', 'statement_of_faith']
      .some(field => hasValue(extracted[field]))
}

// Whether the landing page may recommend this church. Picks and the landing
// zero-match check both use it, so a match is never counted that the picks
// then drop.
export function isStartingPoint(church) {
  return isChurch(church) && hasSomethingToShow(church)
}

// Picks for the landing page. `churches` must come from
// `sort=starting_point`, which ranks the whole city (best documented first,
// ties toward the middle of the city) before its row limit; this keeps that
// order and only drops what we shouldn't recommend.
export function pickStartingPoints(churches, count) {
  return churches.filter(isStartingPoint).slice(0, count)
}

// ── Fit to what a visitor asked for ("Make these fit you") ──────────────────
//
//   church row ─► languageSignals ─┐
//                 worship_style ───┤
//                 kids_programs ───┼─► fitSignals(church, prefs) ─► fitScore 0..4
//                 kids sources ────┘           │
//                                              └─► reason line "Spanish service · Kids program"
//   rows ─► rankForYou (stable, by fitScore) ─► pickStartingPoints / Search "For you"
//
// Matching only ever ranks. A church we know nothing about is unknown, not a
// "no", so no function here reports an absence.

const norm = value => value.trim().toLowerCase()

// Languages a church holds services in, from each source the list API returns,
// first source wins: verified facts (migration 0006), the website extraction,
// excluding name-derived directory guesses. Every language question (fit, the
// Search language filter, card tags) asks this one function.
export function languageSignals(church) {
  const candidates = [
    ...(Array.isArray(church.service_languages) ? church.service_languages : [])
      .map(language => ({ language, source: 'verified' })),
    ...(Array.isArray(church.extracted_tags?.service_languages) ? church.extracted_tags.service_languages : [])
      .map(language => ({ language, source: 'website' })),
  ]
  const seen = new Set()
  return candidates.filter(({ language }) => {
    if (typeof language !== 'string' || !language.trim()) return false
    const key = norm(language)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).map(({ language, source }) => ({ language: language.trim(), source }))
}

export function churchLanguages(church) {
  return languageSignals(church).map(signal => signal.language)
}

export function speaksLanguage(church, language) {
  const wanted = norm(language)
  return languageSignals(church).some(signal => norm(signal.language) === wanted)
}

const KIDS_PROGRAM = /\b(kids?|child|children'?s?|youth|nursery|sunday school|vbs|vacation bible school)\b/i

// Programs a church's archived pages state (migration 0007): type, age bands
// and name on list rows, plus the excerpt, page and fetch date on the detail.
export function kidsPrograms(church) {
  return (Array.isArray(church.kids_programs) ? church.kids_programs : [])
    .filter(program => program && typeof program === 'object' && Array.isArray(program.age_bands))
}

const youngAdultsOnly = program => program.age_bands.length > 0
  && program.age_bands.every(band => band === 'young_adult')

// Evidence that a church has something for a child of any age, but no age we
// can match: a program whose page states no ages, or one of the older
// sources. Worth half a point; a stated band that matches is worth one.
function vagueKidsSignal(church) {
  if (kidsPrograms(church).some(program => program.age_bands.length === 0)) {
    return { label: 'Kids program, ages not stated', source: 'website' }
  }
  if (hasValue(church.kids_program)) return { label: 'Kids program', source: 'verified' }
  const programs = church.extracted_tags?.programs
  if (Array.isArray(programs) && programs.some(program => typeof program === 'string' && KIDS_PROGRAM.test(program))) {
    return { label: 'Kids program', source: 'website' }
  }
  // backend/utils.py compute_tags: three or more reviews, kids average above 4.
  if (Array.isArray(church.tags) && church.tags.includes('Kids programs')) {
    return { label: 'Kids program', source: 'community' }
  }
  return null
}

function bandLabel(value) {
  return KID_BANDS.find(band => band.value === value)?.label ?? value
}

function kidsSignals(church, need) {
  const signals = []
  const programs = kidsPrograms(church)
  if (need.bands.length) {
    const match = programs.find(program => program.age_bands.some(band => need.bands.includes(band)))
    if (match) {
      const bands = match.age_bands.filter(band => need.bands.includes(band)).map(bandLabel).join(', ')
      signals.push({ pref: 'kids', label: `${match.name_stated || 'Program'} (${bands})`, source: 'website', weight: 1 })
    } else {
      const vague = vagueKidsSignal(church)
      if (vague) signals.push({ pref: 'kids', ...vague, weight: 0.5 })
    }
  }
  if (need.weekday_care) {
    // Care for the asked-for ages, or for ages the page doesn't state.
    const care = programs.find(program => program.program_type === 'weekday_care' && (
      !need.bands.length || !program.age_bands.length || program.age_bands.some(band => need.bands.includes(band))))
    if (care) {
      signals.push({ pref: 'weekday', label: 'Weekday childcare', source: 'website', weight: 1 })
    }
  }
  return signals
}

// What matched, each with where it came from and how much it counts: one
// entry per matched language, the best entry for each other question.
export function fitSignals(church, prefs) {
  if (!hasPreferences(prefs)) return []
  const signals = []
  for (const language of prefs.languages) {
    const match = languageSignals(church).find(signal => norm(signal.language) === norm(language))
    if (match) signals.push({ pref: 'language', label: `${language} service`, source: match.source, weight: 1 })
  }
  const style = church.extracted_tags?.worship_style
  if (typeof style === 'string' && prefs.worship.includes(style)) {
    signals.push({ pref: 'worship', label: `${worshipLabel(style)} worship`, source: 'website', weight: 1 })
  }
  return [...signals, ...kidsSignals(church, kidsNeed(prefs.kids))]
}

// One point per question this church answers yes to (language, worship, the
// asked-for ages, weekday care); half a point for a kids program of unstated
// ages. fit_sql in backend/db/repository.py counts the same, case for case
// (fitParityCases.json).
export function fitScore(church, prefs) {
  const best = new Map()
  for (const signal of fitSignals(church, prefs)) {
    best.set(signal.pref, Math.max(best.get(signal.pref) ?? 0, signal.weight))
  }
  return [...best.values()].reduce((sum, weight) => sum + weight, 0)
}

export function fitReason(church, prefs) {
  const sources = { verified: 'checked source', website: 'from website', community: 'from reviews' }
  return fitSignals(church, prefs).map(signal => `${signal.label} (${sources[signal.source]})`).join(' · ')
}

const PROGRAM_TYPE_LABELS = {
  during_service: 'During services',
  weekday_care: 'Weekday childcare or school',
  other: 'Activities and groups',
}

export function programTypeLabel(type) {
  return PROGRAM_TYPE_LABELS[type] ?? null
}

const SHORT_BAND = { preschool: 'Under 5', children: 'K–5', youth: '6–12' }

// "Under 5: Nursery · K–5: Kids Church · 6–12: Youth Group" for a result card:
// the first stated program for each family age band, youngest first. Young
// adults stay on the detail page.
export function programHighlights(church, max = 3) {
  const programs = kidsPrograms(church)
  const lines = []
  const named = new Set()
  for (const { value } of KID_BANDS) {
    // AWANA for ages 2-18 is named once, under its youngest band.
    const program = programs.find(p => p.age_bands.includes(value) && !named.has(p))
    if (program) {
      named.add(program)
      const what = program.name_stated || programTypeLabel(program.program_type) || 'Program'
      lines.push(`${SHORT_BAND[value]}: ${what}`)
    }
  }
  if (!lines.length && programs.some(p => p.age_bands.length === 0)) lines.push('Kids program (ages not stated)')
  return lines.slice(0, max)
}

// The detail page's sections, youngest first. A program for several bands is
// listed once, under its youngest, with its other bands on it. Young adults
// are their own section, never folded into youth.
export function programGroups(church) {
  const order = [
    ...KID_BANDS.map(band => ({ key: band.value, heading: band.heading })),
    { key: 'unstated', heading: 'Ages not stated' },
    { key: 'young_adult', heading: 'Young adults' },
  ]
  const groups = new Map(order.map(group => [group.key, { ...group, programs: [] }]))
  for (const program of kidsPrograms(church)) {
    const key = youngAdultsOnly(program)
      ? 'young_adult'
      : KID_BANDS.find(band => program.age_bands.includes(band.value))?.value ?? 'unstated'
    groups.get(key).programs.push(program)
  }
  return [...groups.values()].filter(group => group.programs.length)
}

export function bandLabels(program) {
  return program.age_bands.map(band => band === 'young_adult' ? 'Young adults' : bandLabel(band))
}

// Best fit first; equal fits keep the order they came in, so with no
// preferences the rows are returned untouched.
export function rankForYou(churches, prefs) {
  if (!hasPreferences(prefs)) return churches
  return churches
    .map((church, index) => ({ church, index, score: fitScore(church, prefs) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(entry => entry.church)
}

// When nothing in the loaded rows matches, say what we don't know instead of
// implying the city has no such church (TODOS F4). The count is only exact
// when the whole city fit under the row limit. `ranked` means the rows are
// the top of a server ranking of the whole scope by the same evidence
// (sort=for_you), so a later row can't match either, as long as no row on
// the page matched at all: the server also ranks rows `eligible` drops, and
// a match among those can sit above a real church's on a later page. Search's nearest-first
// pages (`nearestFirst`) can still hold a documented match on a page not
// loaded yet, so until the last page the sentence speaks only of these.
// Otherwise a full page only speaks for the loaded rows. `eligible` is which
// rows the page can show: every church on Search, only `isStartingPoint` on
// Landing.
export function zeroMatchSentence(churches, prefs, { city, limit, eligible = isChurch, ranked = false, nearestFirst = false }) {
  if (!hasPreferences(prefs)) return null
  if (churches.some(church => eligible(church) && fitScore(church, prefs) > 0)) return null
  const phrase = preferencePhrase(prefs, 'or')
  const exact = churches.length < limit
  const known = churches.filter(church => isChurch(church) && hasFitDetails(church)).length
  if (!exact && nearestFirst) {
    const subject = known === 0
      ? `We don't have details on the ${churches.length} churches nearest the middle of ${city}, so we can't tell yet which have`
      : `None of the ${churches.length} churches nearest the middle of ${city} mention`
    return `${subject} ${phrase}. Load more to check churches farther out.`
  }
  const rankedSpeaksForScope = ranked && !churches.some(church => fitScore(church, prefs) > 0)
  if (!exact && !rankedSpeaksForScope) {
    return `No loaded results mention ${phrase} yet. More churches in ${city} may match.`
  }
  if (exact && known === 0) {
    return `We don't have details on any church in ${city} yet, so we can't tell which have ${phrase}. These are still good places to start.`
  }
  const subject = !exact
    ? `None of the churches we have details on in ${city} mention`
    : known === 1
      ? `The one church we have details on in ${city} doesn't mention`
      : `None of the ${known} churches we have details on in ${city} mention`
  return `${subject} ${phrase} yet — most haven't told us. These are still good places to start.`
}

// Anything a fit answer could come from: a read website, or a verified fact.
function hasFitDetails(church) {
  return hasWebsiteProfile(church)
    || languageSignals(church).some(signal => signal.source === 'verified')
    || hasValue(church.kids_program)
    || kidsPrograms(church).length > 0
}

const CHIP_BASE = ['English', 'Spanish']
const MAX_LANGUAGE_CHIPS = 6

// English and Spanish, then this city's most common other languages, and
// always whatever the visitor already picked.
export function cityLanguageChips(churches, selected = []) {
  const counts = new Map()
  for (const church of churches) {
    for (const language of churchLanguages(church)) {
      const key = norm(language)
      const entry = counts.get(key) || { label: language, count: 0 }
      entry.count += 1
      counts.set(key, entry)
    }
  }
  const base = new Set(CHIP_BASE.map(norm))
  const others = [...counts.entries()]
    .filter(([key]) => !base.has(key))
    .sort((a, b) => b[1].count - a[1].count || a[1].label.localeCompare(b[1].label))
    .map(([, entry]) => entry.label)
  const chips = [...CHIP_BASE, ...others].slice(0, MAX_LANGUAGE_CHIPS)
  for (const language of selected) {
    if (!chips.some(chip => norm(chip) === norm(language))) chips.push(language)
  }
  return chips
}
