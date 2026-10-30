import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import { churchMarkerIcon } from './mapMarker'
import 'leaflet/dist/leaflet.css'

// Refit only when the set of churches changes (a new search, a filter, more
// results). The list is rebuilt on every render, so keying on it would refit
// on each hover or re-sort and undo the visitor's own pan and zoom.
function MapBounds({ churches }) {
  const map = useMap()
  const latest = useRef(churches)
  latest.current = churches
  const idSet = churches.map(c => c.id).sort((a, b) => a - b).join(',')
  useEffect(() => {
    const pts = latest.current.filter(c => c.latitude && c.longitude)
    if (pts.length === 0) return
    const bounds = L.latLngBounds(pts.map(c => [c.latitude, c.longitude]))
    map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 })
  }, [idSet, map])
  return null
}

function MapFlyTo({ church }) {
  const map = useMap()
  useEffect(() => {
    if (church?.latitude && church?.longitude) {
      map.flyTo([church.latitude, church.longitude], 15, { duration: 0.8 })
    }
  }, [church, map])
  return null
}

function MapResize({ active }) {
  const map = useMap()
  useEffect(() => {
    if (!active) return
    const frame = requestAnimationFrame(() => map.invalidateSize())
    return () => cancelAnimationFrame(frame)
  }, [active, map])
  return null
}

export default function SearchMap({
  mappable,
  selectedChurch,
  hoveredId,
  selectedChurchId,
  activeSearch,
  onSelect,
  onHover,
  hoverEnabled,
  mobileView,
}) {
  return (
    <MapContainer
      center={[39.5, -98.35]}
      zoom={4}
      style={{ height: '100%', width: '100%' }}
    >
      <MapResize active={mobileView === 'map'} />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {!selectedChurch && <MapBounds churches={mappable} />}
      {selectedChurch && <MapFlyTo church={selectedChurch} />}
      {mappable.map(c => {
        const active = c.id === hoveredId || c.id === selectedChurchId
        return (
          <Marker
            key={c.id}
            position={[c.latitude, c.longitude]}
            icon={churchMarkerIcon(active)}
            eventHandlers={{
              click: () => onSelect(c.id),
              ...(hoverEnabled ? {
                mouseover: () => onHover(c.id),
                mouseout: () => onHover(null),
              } : {}),
            }}
          >
            <Popup>
              <div className="map-popup">
                <strong>{c.name}</strong>
                {activeSearch?.type === 'name' && (c.city || c.state) && (
                  <span className="popup-location">{[c.city, c.state].filter(Boolean).join(', ')}</span>
                )}
                {c.denomination && <span className="popup-denom">{c.denomination}</span>}
                {c.avg_rating != null && (
                  <span className="popup-rating">★ {c.avg_rating.toFixed(1)}</span>
                )}
              </div>
            </Popup>
          </Marker>
        )
      })}
    </MapContainer>
  )
}
