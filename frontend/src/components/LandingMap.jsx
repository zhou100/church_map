import { useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Popup, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import { churchMarkerIcon } from './mapMarker'
import { keepFitted, overlayPadding } from './mapFit'
import 'leaflet/dist/leaflet.css'

// Loaded with a dynamic import from Landing: Leaflet touches `window` at
// import time, and the landing page is server-rendered by scripts/prerender.mjs.

// Keeps the pins in the part of the map the search card leaves uncovered,
// including after the card reflows, until the visitor moves the map.
function FitChurches({ churches, overlayRef }) {
  const map = useMap()
  useEffect(() => {
    const bounds = churches.length
      ? L.latLngBounds(churches.map(c => [c.latitude, c.longitude]))
      : null
    const container = map.getContainer()
    return keepFitted(map, () => {
      if (!bounds) return
      const paddingTopLeft = overlayPadding(
        container.getBoundingClientRect(),
        overlayRef?.current?.getBoundingClientRect(),
      )
      map.fitBounds(bounds, { paddingTopLeft, paddingBottomRight: [48, 48], maxZoom: 14, animate: false })
    }, [container, overlayRef?.current])
  }, [churches, map, overlayRef])
  return null
}

export default function LandingMap({ churches, hoveredId, onHover, overlayRef }) {
  // Stable across hover and typing, so FitChurches only starts over when the
  // churches change; a resize refits only until the visitor pans or zooms.
  const mappable = useMemo(
    () => churches.filter(c => c.latitude && c.longitude),
    [churches],
  )
  return (
    <MapContainer
      center={[39.5, -98.35]}
      zoom={4}
      scrollWheelZoom={false}
      zoomControl={false}
      style={{ height: '100%', width: '100%' }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ZoomControl position="bottomright" />
      <FitChurches churches={mappable} overlayRef={overlayRef} />
      {mappable.map(c => (
        <Marker
          key={c.id}
          position={[c.latitude, c.longitude]}
          icon={churchMarkerIcon(c.id === hoveredId)}
          eventHandlers={{
            mouseover: () => onHover(c.id),
            mouseout: () => onHover(null),
          }}
        >
          <Popup>
            <div className="map-popup">
              <strong>{c.name}</strong>
              {c.denomination && <span className="popup-denom">{c.denomination}</span>}
              {c.avg_rating != null && (
                <span className="popup-rating">★ {c.avg_rating.toFixed(1)}</span>
              )}
              <a className="popup-link" href={`/church/${c.id}`}>View church</a>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}
