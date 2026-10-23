import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  EMPTY_PREFERENCES,
  PREFERENCES_KEY,
  hasPreferences,
  loadPreferences,
  normalizePreferences,
  preferencePhrase,
  preferenceSummary,
  savePreferences,
} from './preferences.js'

function memoryStorage(initial = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: key => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value) },
    removeItem: key => { delete data[key] },
  }
}

const throwingStorage = {
  getItem() { throw new Error('SecurityError') },
  setItem() { throw new Error('QuotaExceededError') },
  removeItem() { throw new Error('SecurityError') },
}

test('nothing stored means no preferences', () => {
  assert.deepEqual(loadPreferences(memoryStorage()), EMPTY_PREFERENCES)
})

test('corrupted JSON from an older build falls back to no preferences', () => {
  assert.deepEqual(loadPreferences(memoryStorage({ [PREFERENCES_KEY]: '{not json' })), EMPTY_PREFERENCES)
})

test('blocked storage never throws, on read or on write', () => {
  assert.deepEqual(loadPreferences(throwingStorage), EMPTY_PREFERENCES)
  assert.doesNotThrow(() => savePreferences({ languages: ['Spanish'], worship: [], kids: true }, throwingStorage))
  assert.doesNotThrow(() => savePreferences(EMPTY_PREFERENCES, throwingStorage))
})

test('save then load round-trips, and clearing removes the key', () => {
  const storage = memoryStorage()
  const prefs = { languages: ['Spanish'], worship: ['contemporary'], kids: true }
  savePreferences(prefs, storage)
  assert.deepEqual(loadPreferences(storage), prefs)
  assert.ok(JSON.parse(storage.data[PREFERENCES_KEY]).updated_at)

  savePreferences(EMPTY_PREFERENCES, storage)
  assert.equal(PREFERENCES_KEY in storage.data, false)
})

test('normalize drops unknown keys, unknown worship values and bad languages', () => {
  assert.deepEqual(normalizePreferences({
    languages: ['Spanish', ' spanish ', '', 42, 'x'.repeat(41), 'Korean'],
    worship: ['contemporary', 'rave', 'contemporary'],
    kids: 'yes',
    stance: 'progressive',
  }), { languages: ['Spanish', 'Korean'], worship: ['contemporary'], kids: false })
  assert.deepEqual(normalizePreferences(null), EMPTY_PREFERENCES)
  assert.deepEqual(normalizePreferences('Spanish'), EMPTY_PREFERENCES)
})

test('normalize caps the language list', () => {
  const languages = Array.from({ length: 15 }, (_, i) => `Language ${i}`)
  assert.equal(normalizePreferences({ languages }).languages.length, 10)
})

test('hasPreferences is false only when every group is empty', () => {
  assert.equal(hasPreferences(EMPTY_PREFERENCES), false)
  assert.equal(hasPreferences({ languages: [], worship: [], kids: true }), true)
  assert.equal(hasPreferences({ languages: ['Tagalog'], worship: [], kids: false }), true)
  assert.equal(hasPreferences(null), false)
})

test('summary and phrases read like a person wrote them', () => {
  const prefs = { languages: ['Korean', 'Mandarin'], worship: ['traditional-hymns'], kids: true }
  assert.equal(preferenceSummary(prefs), 'Korean · Mandarin · Hymns · Kids')
  assert.equal(preferencePhrase(prefs, 'or'), 'Korean or Mandarin services, hymn-led worship or a kids program')
  assert.equal(preferencePhrase({ languages: ['Spanish'], worship: [], kids: true }, 'and'), 'Spanish services and a kids program')
  assert.equal(preferencePhrase({ languages: [], worship: [], kids: true }), 'a kids program')
})
