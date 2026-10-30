// The landing search card floats over the map, so the pins are fitted into
// whatever it leaves uncovered: beside it (desktop) or below it (mobile).
export function overlayPadding(mapRect, overlayRect) {
  if (!overlayRect) return [48, 48]
  return overlayRect.width < mapRect.width * 0.6
    ? [overlayRect.right - mapRect.left + 48, 48]
    : [32, overlayRect.bottom - mapRect.top + 32]
}

// Runs `fit` now and again whenever an element in `watch` changes size (the
// map, or the card as it reflows), until the visitor pans or zooms the map
// themselves. `fit` must move the map without animation: Leaflet then fires
// movestart/zoomstart inside the call, so those aren't mistaken for the
// visitor's. Returns a function that stops watching.
export function keepFitted(map, fit, watch, Observer = globalThis.ResizeObserver) {
  let fitting = false
  let userMoved = false
  const refit = () => {
    fitting = true
    try { fit() } finally { fitting = false }
  }
  const onMoveStart = () => { if (!fitting) userMoved = true }
  map.on('movestart zoomstart', onMoveStart)
  refit()

  // Leaflet itself only tracks window resizes.
  const observer = typeof Observer === 'function'
    ? new Observer(() => {
      map.invalidateSize()
      if (!userMoved) refit()
    })
    : null
  for (const element of watch) if (element) observer?.observe(element)

  return () => {
    map.off('movestart zoomstart', onMoveStart)
    observer?.disconnect()
  }
}
