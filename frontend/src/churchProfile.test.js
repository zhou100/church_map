import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { isChurch, pickStartingPoints } from './churchProfile.js'

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
