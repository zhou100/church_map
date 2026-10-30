// Group overlapping screen-space markers, including churches at identical
// coordinates. Membership is independent of API order and changes with zoom.
export function clusterMapPoints(points, gap = 52) {
  const parents = points.map((_, i) => i)
  function root(i) {
    while (parents[i] !== i) { parents[i] = parents[parents[i]]; i = parents[i] }
    return i
  }
  const cells = new Map()
  points.forEach((point, i) => {
    const x = Math.floor(point.x / gap), y = Math.floor(point.y / gap)
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const j of cells.get(`${x + dx},${y + dy}`) || []) {
        if (Math.abs(point.x - points[j].x) < gap && Math.abs(point.y - points[j].y) < gap) parents[root(i)] = root(j)
      }
    }
    const key = `${x},${y}`
    if (!cells.has(key)) cells.set(key, [])
    cells.get(key).push(i)
  })
  const groups = new Map()
  points.forEach((point, i) => {
    const key = root(i)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(point.church)
  })
  return [...groups.values()]
}

// Every listing in the group sits on the same coordinates, so zooming in
// can never separate them.
export function samePoint(group) {
  return group.every(c => Math.abs(c.latitude - group[0].latitude) < 1e-7
    && Math.abs(c.longitude - group[0].longitude) < 1e-7)
}

// One page of a stack, in a fixed order (name, then id) so Next and
// Previous never skip or repeat a listing.
export function stackPage(group, page, size = 6) {
  const sorted = [...group].sort((a, b) => (a.name || '').localeCompare(b.name || '') || a.id - b.id)
  const pages = Math.max(1, Math.ceil(sorted.length / size))
  const current = Math.min(Math.max(page, 0), pages - 1)
  const items = sorted.slice(current * size, current * size + size)
  return { items, pages, from: current * size + 1, to: current * size + items.length }
}
