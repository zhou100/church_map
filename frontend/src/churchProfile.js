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
// to go, or what the church says about itself. The same fields score above
// zero in STARTING_POINT_SCORE (backend/db/repository.py).
function hasSomethingToShow(church) {
  const extracted = church.extracted_tags || {}
  return (church.review_count ?? 0) > 0
    || hasValue(church.service_times)
    || hasValue(church.website_summary)
    || ['service_languages', 'worship_style', 'programs', 'theological_stance', 'statement_of_faith']
      .some(field => hasValue(extracted[field]))
}

// Picks for the landing page. `churches` must come from
// `sort=starting_point`, which ranks the whole city (best documented first,
// ties toward the middle of the city) before its row limit; this keeps that
// order and only drops what we shouldn't recommend.
export function pickStartingPoints(churches, count) {
  return churches
    .filter(church => isChurch(church) && hasSomethingToShow(church))
    .slice(0, count)
}
