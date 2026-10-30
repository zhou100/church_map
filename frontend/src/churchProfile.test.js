import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  churchLanguages,
  cityLanguageChips,
  fitReason,
  fitScore,
  fitSignals,
  isChurch,
  isStartingPoint,
  languageSignals,
  pickStartingPoints,
  rankForYou,
  speaksLanguage,
  zeroMatchSentence,
} from './churchProfile.js'
import { EMPTY_PREFERENCES } from './preferences.js'

function church(overrides) {
  return {
    id: overrides.name,
    denomination: 'Non-denominational',
    review_count: 0,
    service_times: null,
    website_summary: null,
    extracted_tags: null,
    latitude: 40.68,
    longitude: -73.97,
    ...overrides,
  }
}

const READ = { website_summary: 'A neighborhood church.', extracted_tags: { programs: ['kids'] } }

test('keeps the order the API ranked the city in', () => {
  const picks = pickStartingPoints([
    church({ name: 'Zion', ...READ }),
    church({ name: 'Abbey Road', review_count: 1 }),
    church({ name: 'Middle', service_times: 'Sun 10am' }),
    church({ name: 'Fourth', ...READ }),
  ], 3)
  assert.deepEqual(picks.map(c => c.name), ['Zion', 'Abbey Road', 'Middle'])
})

test('leaves out non-church houses of worship and churches with nothing to show', () => {
  const picks = pickStartingPoints([
    church({ name: 'Society for Ethical Culture', denomination: 'Ethical', ...READ }),
    church({ name: 'Kolot', denomination: 'Jewish', ...READ }),
    church({ name: 'Unread Chapel' }),
    church({ name: 'Blank Times', service_times: '  ', extracted_tags: { programs: [] } }),
    church({ name: 'Grace Church', denomination: 'Presbyterian', ...READ }),
  ], 3)
  assert.deepEqual(picks.map(c => c.name), ['Grace Church'])
})

test('skips every out-of-scope label in the dbt denomination scope seed', () => {
  const seed = readFileSync(
    new URL('../../analytics/dbt/seeds/denomination_scope.csv', import.meta.url),
    'utf8',
  )
  const rows = seed.trim().split('\n').slice(1).map(line => line.split(','))
  const labels = status => rows.filter(row => row[1] === status).map(row => row[0])

  assert.ok(labels('out_of_scope').length > 0)
  for (const denomination of labels('out_of_scope')) {
    assert.equal(isChurch({ denomination }), false, `${denomination} should be skipped`)
  }
  for (const denomination of labels('in_scope_labeled')) {
    assert.equal(isChurch({ denomination }), true, `${denomination} should stay`)
  }
})

test('skips labels from the snapshot, including ones the seed may not list yet', () => {
  for (const denomination of [
    'Ethical', 'Krishna', 'Hare Krishna', 'Vaishnavism', 'Rastafarian', 'Scientologist',
    'Zen', 'Spiritist', 'Eckankar', 'Shamanic', 'Voodoo', 'Tenrikyo', 'Confucian',
    'Kabbalah', 'Ahmadiyya', "Bahá'í",
  ]) {
    assert.equal(isChurch({ denomination }), false, denomination)
  }
})

test('keeps Christian labels that share words with excluded ones', () => {
  for (const denomination of [
    'Christian Science', 'Roman Catholic', 'Non-denominational', 'Nazarene',
    'Messianic Jewish', 'Messianic Judaism', 'Jews for Jesus',
    'Universal Church of the Kingdom of God', 'Metropolitan Community',
  ]) {
    assert.equal(isChurch({ denomination }), true, denomination)
  }
})

// ── Fit preferences ─────────────────────────────────────────────────────────

const prefs = overrides => ({ ...EMPTY_PREFERENCES, ...overrides })

test('service languages use verified facts and the website, excluding directory guesses', () => {
  assert.deepEqual(languageSignals(church({
    name: 'All three',
    service_languages: ['Spanish'],
    extracted_tags: { service_languages: ['spanish', 'English'] },
    language: ' Korean ',
  })), [
    { language: 'Spanish', source: 'verified' },
    { language: 'English', source: 'website' },
  ])
  assert.deepEqual(churchLanguages(church({ name: 'Website only', extracted_tags: { service_languages: ['Tagalog'] } })), ['Tagalog'])
  assert.deepEqual(churchLanguages(church({ name: 'Directory only', language: 'Haitian Creole' })), [])
  assert.deepEqual(churchLanguages(church({ name: 'Nothing', language: '', service_languages: [] })), [])
  assert.deepEqual(churchLanguages(church({ name: 'Junk', extracted_tags: { service_languages: 'Spanish' } })), [])
})

test('cultural background is not a language', () => {
  assert.equal(speaksLanguage(church({ name: 'Iglesia', cultural_background: 'Hispanic/Latino' }), 'Spanish'), false)
  assert.equal(speaksLanguage(church({ name: 'Iglesia', language: 'spanish' }), 'Spanish'), false)
})

test('each preference matches each of its sources', () => {
  const spanish = prefs({ languages: ['Spanish'] })
  assert.equal(fitScore(church({ name: 'v', service_languages: ['Spanish'] }), spanish), 1)
  assert.equal(fitScore(church({ name: 'w', extracted_tags: { service_languages: ['Spanish'] } }), spanish), 1)
  assert.equal(fitScore(church({ name: 'd', language: 'Spanish' }), spanish), 0)

  const contemporary = prefs({ worship: ['contemporary'] })
  assert.equal(fitScore(church({ name: 'c', extracted_tags: { worship_style: 'contemporary' } }), contemporary), 1)
  assert.equal(fitScore(church({ name: 'l', extracted_tags: { worship_style: 'liturgical' } }), contemporary), 0)

  const kids = prefs({ kids: true })
  assert.equal(fitSignals(church({ name: 'k1', kids_program: 'Sunday school at 9' }), kids)[0].source, 'verified')
  for (const program of ['kids church', "Children's ministry", 'youth group', 'Nursery', 'Sunday School', 'VBS']) {
    assert.equal(fitScore(church({ name: program, extracted_tags: { programs: [program] } }), kids), 1, program)
  }
  assert.equal(fitSignals(church({ name: 'k3', tags: ['Kids programs'] }), kids)[0].source, 'community')
  assert.equal(fitScore(church({ name: 'k4', extracted_tags: { programs: ['food pantry', 'skidmore outreach'] } }), kids), 0)
})

test('the score counts questions answered, not matched values', () => {
  const both = prefs({ languages: ['Spanish', 'English'], worship: ['blended'], kids: true })
  const row = church({
    name: 'Bilingual',
    extracted_tags: { service_languages: ['Spanish', 'English'], worship_style: 'blended', programs: ['kids'] },
  })
  assert.equal(fitScore(row, both), 3)
  assert.equal(fitReason(row, both), 'Spanish service (from website) · English service (from website) · Blended worship (from website) · Kids program (from website)')
})

test('an unread church yields no signal and never a negative one', () => {
  const asked = prefs({ languages: ['Korean'], worship: ['charismatic'], kids: true })
  assert.deepEqual(fitSignals(church({ name: 'Unread' }), asked), [])
  assert.equal(fitReason(church({ name: 'Unread' }), asked), '')
  assert.deepEqual(fitSignals(church({ name: 'Any', language: 'Korean' }), EMPTY_PREFERENCES), [])
})

test('with no preferences the ranking returns the rows untouched', () => {
  const rows = [church({ name: 'B' }), church({ name: 'A', language: 'Spanish' })]
  assert.equal(rankForYou(rows, EMPTY_PREFERENCES), rows)
})

test('better fits rise, equal fits keep their order', () => {
  const asked = prefs({ languages: ['Spanish'], kids: true })
  const rows = [
    church({ name: 'none-1' }),
    church({ name: 'one-a', service_languages: ['Spanish'] }),
    church({ name: 'none-2' }),
    church({ name: 'two', service_languages: ['Spanish'], kids_program: 'Nursery' }),
    church({ name: 'one-b', tags: ['Kids programs'] }),
  ]
  assert.deepEqual(rankForYou(rows, asked).map(c => c.name), ['two', 'one-a', 'one-b', 'none-1', 'none-2'])
})

test('a matching house of worship that is not a church is still never picked', () => {
  const asked = prefs({ languages: ['Hebrew'] })
  const rows = [
    church({ name: 'Grace', ...READ }),
    church({ name: 'Beth El', denomination: 'Jewish', language: 'Hebrew', ...READ }),
  ]
  assert.deepEqual(pickStartingPoints(rankForYou(rows, asked), 3).map(c => c.name), ['Grace'])
})

test('zero matches: say what we have not read, never that it is absent', () => {
  const korean = prefs({ languages: ['Korean'] })
  const rows = [
    church({ name: 'A', ...READ }),
    church({ name: 'B', service_languages: ['Spanish'] }),
    church({ name: 'C', kids_program: 'Nursery' }),
    church({ name: 'D' }),
  ]

  assert.equal(
    zeroMatchSentence(rows, korean, { city: 'Fresno', limit: 100 }),
    "None of the 3 churches we have details on in Fresno mention Korean services yet — most haven't told us. These are still good places to start.",
  )
  assert.equal(
    zeroMatchSentence(rows, korean, { city: 'Fresno', limit: 4 }),
    "No loaded results mention Korean services yet. More churches in Fresno may match.",
  )
  assert.match(zeroMatchSentence(rows.slice(2), korean, { city: 'Fresno', limit: 100 }), /^The one church we have details on in Fresno doesn't mention/)
  assert.match(
    zeroMatchSentence([church({ name: 'Unread' })], prefs({ languages: ['Korean'], kids: true }), { city: 'Fresno', limit: 100 }),
    /^We don't have details on any church in Fresno yet, so we can't tell which have Korean services or a kids program\./,
  )
})

test('Search, nearest first: until the last page, the sentence speaks only of the loaded churches', () => {
  // Page one: 50 undocumented churches at the middle. The documented Spanish
  // church is 11km out, on page two.
  const pageOne = Array.from({ length: 50 }, (_, i) => church({ name: `Near ${i}`, latitude: 40, longitude: -74 }))
  const pageTwo = church({
    name: 'Iglesia',
    latitude: 40.1,
    longitude: -74,
    website_summary: 'Servicios en español.',
    extracted_tags: { service_languages: ['Spanish'] },
  })
  const spanish = prefs({ languages: ['Spanish'] })
  const more = { city: 'Fresno', limit: pageOne.length, nearestFirst: true }

  const sentence = zeroMatchSentence(pageOne, spanish, more)
  assert.equal(
    sentence,
    "We don't have details on the 50 churches nearest the middle of Fresno, so we can't tell yet which have Spanish services. Load more to check churches farther out.",
  )
  assert.doesNotMatch(sentence, /any church in Fresno/)
  // documented but not matching: still no claim about the city
  const readPage = [church({ name: 'Read', ...READ }), ...pageOne.slice(1)]
  assert.match(zeroMatchSentence(readPage, spanish, more), /^None of the 50 churches nearest the middle of Fresno mention Spanish services\. Load more/)
  // once page two is in, the match is found
  assert.equal(zeroMatchSentence([...pageOne, pageTwo], spanish, { ...more, limit: 52 }), null)
  // every page loaded and nothing documented: the city-wide sentence is true
  assert.match(
    zeroMatchSentence(pageOne, spanish, { ...more, limit: 51 }),
    /^We don't have details on any church in Fresno yet/,
  )
})

test('no zero-match sentence when anything matched or nothing was asked', () => {
  const rows = [church({ name: 'A', ...READ }), church({ name: 'B', service_languages: ['Korean'] })]
  assert.equal(zeroMatchSentence(rows, prefs({ languages: ['Korean'] }), { city: 'X', limit: 100 }), null)
  assert.equal(zeroMatchSentence(rows, EMPTY_PREFERENCES, { city: 'X', limit: 100 }), null)
})

test('a match on a non-church row does not count as a match', () => {
  const rows = [church({ name: 'Grace', ...READ }), church({ name: 'Mosque', denomination: 'Islam', language: 'Arabic' })]
  assert.ok(zeroMatchSentence(rows, prefs({ languages: ['Arabic'] }), { city: 'X', limit: 100 }))
})

test('language chips: English and Spanish first, then the city, six at most, picks always kept', () => {
  const rows = [
    church({ name: '1', service_languages: ['Korean'] }),
    church({ name: '2', extracted_tags: { service_languages: ['Korean', 'Tagalog'] } }),
    church({ name: '3', service_languages: ['Vietnamese', 'Spanish'] }),
    church({ name: '4', service_languages: ['Amharic'] }),
    church({ name: '5', service_languages: ['Russian'] }),
    church({ name: '6', service_languages: ['Tagalog'] }),
  ]
  assert.deepEqual(cityLanguageChips(rows), ['English', 'Spanish', 'Korean', 'Tagalog', 'Amharic', 'Russian'])
  assert.deepEqual(cityLanguageChips(rows, ['Haitian Creole', 'korean']).slice(-1), ['Haitian Creole'])
  assert.deepEqual(cityLanguageChips([]), ['English', 'Spanish'])
})

// What Landing.jsx renders from the rows it loaded: the picks, and whether
// they are labeled "for you" (a match was found) or explained (none was).
function landingView(rows, asked, limit = 100) {
  const picks = pickStartingPoints(rankForYou(rows, asked), 3)
  const zeroMatch = zeroMatchSentence(rows, asked, { city: 'Fresno', limit, eligible: isStartingPoint })
  return { picks: picks.map(c => c.name), zeroMatch }
}

test('landing: a church whose only fact is a verified kids program is picked first', () => {
  const rows = [
    church({ name: 'A', website_summary: 'A neighborhood church.' }),
    church({ name: 'B', website_summary: 'A neighborhood church.' }),
    church({ name: 'C', website_summary: 'A neighborhood church.' }),
    church({ name: 'Kids', kids_program: 'Sunday school at 9' }),
  ]
  const view = landingView(rows, prefs({ kids: true }))
  assert.deepEqual(view.picks, ['Kids', 'A', 'B'])
  assert.equal(view.zeroMatch, null)
})

test('landing: a match the picks would drop does not count, so the picks are explained', () => {
  const rows = [
    church({ name: 'A', website_summary: 'A neighborhood church.' }),
    church({ name: 'B', website_summary: 'A neighborhood church.' }),
    church({ name: 'Directory only', language: 'Korean' }),
  ]
  const view = landingView(rows, prefs({ languages: ['Korean'] }))
  assert.deepEqual(view.picks, ['A', 'B'])
  assert.ok(view.zeroMatch)
  // Search also treats a directory guess as unknown service language.
  assert.ok(zeroMatchSentence(rows, prefs({ languages: ['Korean'] }), { city: 'Fresno', limit: 100 }))
})
