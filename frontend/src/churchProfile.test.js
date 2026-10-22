import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { isChurch, rankStartingPoints, startingPointScore } from './churchProfile.js'

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

test('scores reviews and service times above a website summary alone', () => {
  const reviewed = church({ name: 'Reviewed', review_count: 2, service_times: '10am' })
  const readOnly = church({ name: 'Read', ...READ })
  assert.ok(startingPointScore(reviewed) > startingPointScore(readOnly))
})

test('leaves out non-church houses of worship and empty profiles', () => {
  const picks = rankStartingPoints([
    church({ name: 'Society for Ethical Culture', denomination: 'Ethical', ...READ }),
    church({ name: 'Kolot', denomination: 'Jewish', ...READ }),
    church({ name: 'Unread Chapel' }),
    church({ name: 'Grace Church', denomination: 'Presbyterian', ...READ }),
  ], 3)
  assert.deepEqual(picks.map(c => c.name), ['Grace Church'])
})

test('breaks ties toward the middle of the city', () => {
  const picks = rankStartingPoints([
    church({ name: 'Far west', ...READ, latitude: 40.60, longitude: -74.05 }),
    church({ name: 'Near middle', ...READ, latitude: 40.62, longitude: -74.03 }),
    church({ name: 'Middle', ...READ, latitude: 40.68, longitude: -73.97 }),
    church({ name: 'East', ...READ, latitude: 40.75, longitude: -73.90 }),
    church({ name: 'Far east', ...READ, latitude: 40.76, longitude: -73.89 }),
  ], 2)
  assert.deepEqual(picks.map(c => c.name), ['Middle', 'Near middle'])
})

test('a church without coordinates can still be picked, after located ties', () => {
  const picks = rankStartingPoints([
    church({ name: 'Unmapped', ...READ, latitude: null, longitude: null }),
    church({ name: 'Mapped', ...READ }),
  ], 2)
  assert.deepEqual(picks.map(c => c.name), ['Mapped', 'Unmapped'])
})

test('a visitor location wins the tiebreak over the middle of the city', () => {
  const picks = rankStartingPoints([
    church({ name: 'Middle', ...READ, latitude: 40.68, longitude: -73.97 }),
    church({ name: 'By the visitor', ...READ, latitude: 40.60, longitude: -74.05 }),
    church({ name: 'Elsewhere', ...READ, latitude: 40.75, longitude: -73.90 }),
  ], 1, { lat: 40.61, lon: -74.04 })
  assert.deepEqual(picks.map(c => c.name), ['By the visitor'])
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

test('skips houses of worship the seed does not list yet', () => {
  for (const denomination of ['Ethical', 'Krishna', 'Rastafarian', 'Scientologist']) {
    assert.equal(isChurch({ denomination }), false, denomination)
  }
  for (const denomination of ['Christian Science', 'Roman Catholic', 'Non-denominational']) {
    assert.equal(isChurch({ denomination }), true, denomination)
  }
})
