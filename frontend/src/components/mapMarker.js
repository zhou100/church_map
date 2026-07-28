import L from 'leaflet'

export function churchMarkerIcon(active = false) {
  return L.divIcon({
    className: 'church-marker',
    html: `
      <svg class="map-pin${active ? ' map-pin-active' : ''}" viewBox="0 0 32 40" aria-hidden="true">
        <path d="M16 1C7.7 1 1 7.7 1 16c0 10.4 15 23 15 23s15-12.6 15-23C31 7.7 24.3 1 16 1Z" />
        <circle cx="16" cy="16" r="5" />
      </svg>
    `,
    iconSize: [32, 40],
    iconAnchor: [16, 39],
    popupAnchor: [0, -38],
  })
}
