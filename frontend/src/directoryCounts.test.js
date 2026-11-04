import assert from 'node:assert/strict'
import { test } from 'node:test'
import { directoryCounts } from './directoryCounts.js'

const WHOLE_TABLE = { total: 134377, with_website: 9032, with_website_pct: 6.7, with_summary: 6008 }

test('visitor-facing counts come from the visible rows', () => {
  const visible = { total: 133100, with_website: 9000, with_website_pct: 6.8, with_summary: 5990 }
  assert.deepEqual(directoryCounts({ ...WHOLE_TABLE, visible }), {
    total: 133100, withWebsite: 9000, withWebsitePct: 6.8, withSummary: 5990,
  })
})

test('an API without visible counts falls back to the whole table', () => {
  assert.deepEqual(directoryCounts(WHOLE_TABLE), {
    total: 134377, withWebsite: 9032, withWebsitePct: 6.7, withSummary: 6008,
  })
})
