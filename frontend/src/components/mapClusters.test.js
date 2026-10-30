import { test } from 'node:test'
import assert from 'node:assert/strict'
import { clusterMapPoints } from './mapClusters.js'
const point = (id, x, y) => ({ church: { id }, x, y })
test('105 overlapping pins become a counted group without losing churches', () => {
  const points = Array.from({ length: 105 }, (_, id) => point(id, 100, id * 2))
  const groups = clusterMapPoints(points)
  assert.equal(groups.length, 1)
  assert.equal(new Set(groups[0].map(c => c.id)).size, 105)
})
test('identical coordinates remain selectable together even at maximum zoom', () => {
  assert.equal(clusterMapPoints([point(1, 0, 0), point(2, 0, 0)])[0].length, 2)
})
test('zoom separates distant pins; grid boundaries do not hide overlaps', () => {
  assert.equal(clusterMapPoints([point(1, 51, 0), point(2, 53, 0)]).length, 1)
  assert.equal(clusterMapPoints([point(1, 0, 0), point(2, 100, 0)]).length, 2)
  assert.deepEqual(clusterMapPoints([]), [])
})
import { samePoint, stackPage } from './mapClusters.js'
test('a stack of 105 listings at one point is chosen six at a time', () => {
  const group = Array.from({ length: 105 }, (_, i) => ({ id: 105 - i, name: 'Same name', latitude: 1, longitude: 2 }))
  assert.equal(samePoint(group), true)
  const seen = []
  for (let page = 0; page < stackPage(group, 0).pages; page++) seen.push(...stackPage(group, page).items.map(c => c.id))
  assert.equal(seen.length, 105)
  assert.equal(new Set(seen).size, 105)
  assert.deepEqual(stackPage(group, 99).items.map(c => c.id), [103, 104, 105])
  assert.equal(samePoint([{ latitude: 1, longitude: 2 }, { latitude: 1.001, longitude: 2 }]), false)
})
