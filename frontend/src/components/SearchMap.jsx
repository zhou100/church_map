import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Circle, useMap } from 'react-leaflet'
import L from 'leaflet'
import ChurchMapMarkers from './ChurchMapMarkers'
import 'leaflet/dist/leaflet.css'

const CENTER_ICON = typeof window === 'undefined' ? null
  : L.divIcon({ className: 'search-center-pin', html: '<span></span>', iconSize: [22, 22], iconAnchor: [11, 11] })

// Fit the map once per search, when it first has rows and a size. Later
// pages add pins without moving the map, so they never undo the visitor's
// own pan, zoom or selection.
function FitOnce({ fitKey, churches, circle, active }) {
  const map = useMap()
  const fitted = useRef(null)
  useEffect(() => {
    if (!fitKey || fitted.current === fitKey) return
    map.invalidateSize({ pan: false })
    const size = map.getSize()
    if (!size.x || !size.y) return
    if (circle) {
      map.fitBounds(L.latLng(circle.center.lat, circle.center.lon).toBounds(circle.miles * 1609.344 * 2), { padding: [24, 24], animate: false })
    } else {
      if (churches.length === 0) return
      map.fitBounds(L.latLngBounds(churches.map(c => [c.latitude, c.longitude])), { padding: [32, 32], maxZoom: 14, animate: false })
    }
    fitted.current = fitKey
  }, [fitKey, churches, circle, active, map])
  return null
}

function MapFlyTo({ church }) {
  const map = useMap()
  useEffect(() => {
    if (church?.latitude && church?.longitude) {
      // A hidden phone map has no size; Leaflet's flight math divides by it.
      const size = map.getSize()
      map.flyTo([church.latitude, church.longitude], 15, { duration: 0.8, animate: size.x > 0 && size.y > 0 })
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

// `mappable` is the loaded rows that have coordinates; `circle` is the
// nearby-cities scope ({ center, miles }) when the visitor chose one.
export default function SearchMap({
  mappable,
  selectedChurch,
  hoveredId,
  selectedChurchId,
  onSelect,
  onHover,
  hoverEnabled,
  mobileView,
  fitKey,
  circle,
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
      <FitOnce fitKey={fitKey} churches={mappable} circle={circle} active={mobileView} />
      {circle && <>
        <Circle center={[circle.center.lat, circle.center.lon]} radius={circle.miles * 1609.344}
          interactive={false} pathOptions={{ color: '#8B5E3C', fillOpacity: 0.06, weight: 2 }} />
        <Marker position={[circle.center.lat, circle.center.lon]} zIndexOffset={1000} interactive={false}
          keyboard={false} alt="Search center" icon={CENTER_ICON} />
      </>}
      {selectedChurch && <MapFlyTo church={selectedChurch} />}
      <ChurchMapMarkers churches={mappable} hoveredId={hoveredId}
        selectedId={selectedChurchId} onHover={hoverEnabled ? onHover : undefined}
        onSelect={onSelect} searchCenter={circle?.center ?? null} />
    </MapContainer>
  )
}
