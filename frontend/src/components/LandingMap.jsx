import { useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Popup, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import { churchMarkerIcon } from './mapMarker'
import 'leaflet/dist/leaflet.css'

// Loaded with a dynamic import from Landing: Leaflet touches `window` at
// import time, and the landing page is server-rendered by scripts/prerender.mjs.

// The search card floats over the map, so fit the pins into whatever is left
// beside it (desktop) or below it (mobile) instead of the full map.
function FitChurches({ churches, overlayRef }) {
  const map = useMap()
  useEffect(() => {
    if (churches.length === 0) return
    const bounds = L.latLngBounds(churches.map(c => [c.latitude, c.longitude]))
    const mapRect = map.getContainer().getBoundingClientRect()
    const overlayRect = overlayRef?.current?.getBoundingClientRect()
    let paddingTopLeft = [48, 48]
    if (overlayRect) {
      paddingTopLeft = overlayRect.width < mapRect.width * 0.6
        ? [overlayRect.right - mapRect.left + 48, 48]
        : [32, overlayRect.bottom - mapRect.top + 32]
    }
    map.fitBounds(bounds, { paddingTopLeft, paddingBottomRight: [48, 48], maxZoom: 14 })
  }, [churches, map, overlayRef])
  return null
}

export default function LandingMap({ churches, hoveredId, onHover, overlayRef }) {
  // Stable across hover and typing, so FitChurches only refits when the
  // churches change and never undoes a visitor's own pan or zoom.
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
