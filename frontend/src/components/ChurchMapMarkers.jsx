import { useEffect, useState } from 'react'
import { Marker, Popup, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { churchMarkerIcon } from './mapMarker'
import { clusterMapPoints, samePoint, stackPage } from './mapClusters'

// Listings that share one map point (or still overlap at full zoom), a few
// at a time: a stack can hold dozens of directory rows.
function StackPopup({ group, exact, onSelect }) {
  const [page, setPage] = useState(0)
  const { items, from, to, pages } = stackPage(group, page)
  return (
    <div className="cluster-popup">
      <strong>{group.length} listings {exact ? 'at this map point' : 'in this small area'}</strong>
      <p className="cluster-note">A count of listings, not confirmed separate churches or locations.</p>
      <ul aria-label={`Listings ${from}–${to} of ${group.length}`}>
        {items.map(c => <li key={c.id}>
          {onSelect ? <button type="button" onClick={() => onSelect(c.id)}>{c.name}</button>
            : <a href={`/church/${c.id}`}>{c.name}</a>}
          <span>{[c.address, c.city, c.state].filter(Boolean).join(', ')}</span>
        </li>)}
      </ul>
      {pages > 1 && <div className="cluster-pager">
        <button type="button" onClick={() => setPage(page - 1)} disabled={page === 0}>Previous</button>
        <span aria-live="polite">{from}–{to} of {group.length}</span>
        <button type="button" onClick={() => setPage(page + 1)} disabled={page >= pages - 1}>Next</button>
      </div>}
    </div>
  )
}

export default function ChurchMapMarkers({ churches, hoveredId, selectedId, onHover, onSelect, searchCenter }) {
  const [, redraw] = useState(0)
  const map = useMapEvents({ zoomend: () => redraw(n => n + 1), resize: () => redraw(n => n + 1) })
  useEffect(() => { redraw(n => n + 1) }, [])
  const groups = clusterMapPoints(churches.map(church => {
    const point = map.project([church.latitude, church.longitude], map.getZoom())
    return { church, x: point.x, y: point.y }
  }))
  const maxZoom = map.getMaxZoom()
  return groups.map(group => {
    const first = group[0]
    const clustered = group.length > 1
    const exact = clustered && samePoint(group)
    // Zoom first; only a stack that zooming cannot split opens a list.
    const stack = clustered && (exact || map.getZoom() >= maxZoom)
    const active = group.some(c => c.id === hoveredId || c.id === selectedId)
    const position = L.latLng(
      group.reduce((sum, c) => sum + c.latitude, 0) / group.length,
      group.reduce((sum, c) => sum + c.longitude, 0) / group.length,
    )
    // A count represents an area, so offset its badge when needed to keep
    // the search center visible. Individual pins stay exact.
    let badgeOffset = 0
    if (clustered && searchCenter) {
      const point = map.project(position, map.getZoom())
      const center = map.project([searchCenter.lat, searchCenter.lon], map.getZoom())
      if (point.distanceTo(center) < 56) badgeOffset = 56
    }
    const label = !clustered ? first.name
      : stack ? `${group.length} listings at one point — choose one` : `${group.length} listings — zoom in`
    return <Marker key={group.map(c => c.id).sort((a, b) => a - b).join(',')}
      position={position} title={label} alt={label}
      icon={clustered ? L.divIcon({
        className: `church-cluster${active ? ' church-cluster-active' : ''}${stack ? ' church-cluster-stack' : ''}`,
        html: `<span>${group.length}</span>`, iconSize: [44, 44], iconAnchor: [22 - badgeOffset, 22], popupAnchor: [badgeOffset, -22],
      }) : churchMarkerIcon(active)}
      eventHandlers={{
        mouseover: () => { if (!clustered) onHover?.(first.id) },
        mouseout: () => onHover?.(null),
        click: () => {
          if (!clustered) onSelect?.(first.id)
          else if (!stack) {
            // A chain of overlaps can be wider than the view; always go closer.
            const bounds = L.latLngBounds(group.map(c => [c.latitude, c.longitude]))
            if (map.getBoundsZoom(bounds, false, L.point(96, 96)) > map.getZoom()) {
              map.fitBounds(bounds, { padding: [48, 48], maxZoom: Math.min(maxZoom, map.getZoom() + 3) })
            } else {
              map.setView(position, Math.min(maxZoom, map.getZoom() + 2))
            }
          }
        },
      }}>
      {(!clustered || stack) && <Popup maxWidth={300}>
        {stack ? <StackPopup group={group} exact={exact} onSelect={onSelect} /> : <div className="map-popup">
          <strong>{first.name}</strong>
          <span>{[first.city, first.state].filter(Boolean).join(', ')}</span>
          {first.denomination && <span className="popup-denom">{first.denomination}</span>}
          <a className="popup-link" href={`/church/${first.id}`}>View church</a>
        </div>}
      </Popup>}
    </Marker>
  })
}
