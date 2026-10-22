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
  return Array.isArray(value) ? value.length > 0 : Boolean(value)
}

// How much of what a newcomer needs before a first visit we can show:
// what people say about it, when to go, and what the church says about itself.
export function startingPointScore(church) {
  const extracted = church.extracted_tags || {}
  return (
    ((church.review_count ?? 0) > 0 ? 3 : 0) +
    (hasValue(church.service_times) ? 2 : 0) +
    (church.website_summary ? 2 : 0) +
    (hasValue(extracted.service_languages) ? 1 : 0) +
    (hasValue(extracted.worship_style) ? 1 : 0) +
    (hasValue(extracted.programs) ? 1 : 0) +
    (hasValue(extracted.theological_stance) || hasValue(extracted.statement_of_faith) ? 1 : 0)
  )
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

// Picks for the landing page: the most complete church profiles, with ties
// going to the ones nearest the visitor or, when we don't know where they
// are, nearest the middle of the city's churches. `churches` should come
// from `sort=starting_point`, so a large city's best profiles are in it.
export function rankStartingPoints(churches, count, visitor = null) {
  const located = churches.filter(c => c.latitude && c.longitude)
  const center = visitor
    ? [visitor.lat, visitor.lon]
    : located.length
      ? [median(located.map(c => c.latitude)), median(located.map(c => c.longitude))]
      : null
  const distance = church => (center && church.latitude && church.longitude)
    ? Math.hypot(church.latitude - center[0], church.longitude - center[1])
    : Infinity

  return churches
    .filter(church => isChurch(church) && startingPointScore(church) > 0)
    .map(church => ({ church, score: startingPointScore(church), distance: distance(church) }))
    .sort((a, b) => (b.score - a.score)
      || (a.distance - b.distance)
      || a.church.name.localeCompare(b.church.name))
    .slice(0, count)
    .map(({ church }) => church)
}
