import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import ChurchCard from '../components/ChurchCard'
import ChurchDetailPanel from '../components/ChurchDetailPanel'

const API = import.meta.env.VITE_API_URL || ''
const PAGE = 50

// Fix Leaflet default marker icons (broken by bundlers)
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

function MapBounds({ churches }) {
  const map = useMap()
  useEffect(() => {
    const pts = churches.filter(c => c.latitude && c.longitude)
    if (pts.length === 0) return
    const bounds = L.latLngBounds(pts.map(c => [c.latitude, c.longitude]))
    map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 })
  }, [churches, map])
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

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [city, setCity] = useState(searchParams.get('city') || '')
  const [state, setState] = useState(searchParams.get('state') || '')
  const [churches, setChurches] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState(null)
  const [selectedTags, setSelectedTags] = useState([])
  const [selectedLang, setSelectedLang] = useState(null)
  const [sortBy, setSortBy] = useState('distance')
  const [detectedLocation, setDetectedLocation] = useState(null)
  const [userCoords, setUserCoords] = useState(null)
  const [hoveredId, setHoveredId] = useState(null)
  const [selectedChurchId, setSelectedChurchId] = useState(null)
  const offsetRef = useRef(0)
  const cardRefs = useRef({})

  async function fetchPage(cityVal, stateVal, offset, append = false) {
    const url = `${API}/api/churches?city=${encodeURIComponent(cityVal)}&state=${encodeURIComponent(stateVal)}&limit=${PAGE}&offset=${offset}`
    const res = await fetch(url)
    if (!res.ok) throw new Error('Failed to fetch')
    const data = await res.json()
    if (append) {
      setChurches(prev => [...(prev || []), ...data])
    } else {
      setChurches(data)
    }
    setHasMore(data.length === PAGE)
    offsetRef.current = offset + data.length
    return data
  }

  async function handleSearch(e) {
    if (e) e.preventDefault()
    if (!city.trim() || !state.trim()) return
    setSearchParams({ city: city.trim(), state: state.trim() })
    setSelectedTags([])
    setSelectedLang(null)
    setDetectedLocation(null)
    setSelectedChurchId(null)
    setLoading(true)
    setError(null)
    offsetRef.current = 0
    try {
      await fetchPage(city.trim(), state.trim(), 0)
    } catch (err) {
      setError(`${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleLoadMore() {
    setLoadingMore(true)
    try {
      await fetchPage(city.trim(), state.trim(), offsetRef.current, true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    const c = searchParams.get('city')
    const s = searchParams.get('state')
    if (c && s) {
      setCity(c)
      setState(s)
      setLoading(true)
      setError(null)
      offsetRef.current = 0
      fetchPage(c, s, 0)
        .then(() => setSelectedTags([]))
        .catch(err => setError(err.message))
        .finally(() => setLoading(false))
    } else {
      setLoading(true)
      fetch('https://ipapi.co/json/')
        .then(r => r.json())
        .then(data => {
          const detCity = data.city
          const detState = data.region_code
          if (detCity && detState && data.country_code === 'US') {
            setCity(detCity)
            setState(detState)
            setDetectedLocation({ city: detCity, state: detState })
            if (data.latitude && data.longitude) {
              setUserCoords({ lat: data.latitude, lon: data.longitude })
            }
            setSearchParams({ city: detCity, state: detState })
            offsetRef.current = 0
            return fetchPage(detCity, detState, 0)
              .then(() => setSelectedTags([]))
          }
        })
        .catch(() => {})
        .finally(() => setLoading(false))
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function haversine(lat1, lon1, lat2, lon2) {
    const R = 3958.8, dLat = (lat2 - lat1) * Math.PI / 180, dLon = (lon2 - lon1) * Math.PI / 180
    const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a))
  }

  const availableTags = churches ? [...new Set(churches.flatMap(c => c.tags ?? []))] : []
  const availableLangs = churches
    ? [...new Set(churches.flatMap(c => [c.language, c.cultural_background]).filter(Boolean))]
    : []

  const filtered = churches
    ?.filter(c => selectedTags.length === 0 || selectedTags.every(t => c.tags?.includes(t)))
    ?.filter(c => !selectedLang || c.language === selectedLang || c.cultural_background === selectedLang)

  const visibleChurches = filtered ? [...filtered].sort((a, b) => {
    if (sortBy === 'distance' && userCoords?.lat) {
      const da = (a.latitude && a.longitude) ? haversine(userCoords.lat, userCoords.lon, a.latitude, a.longitude) : 9999
      const db_ = (b.latitude && b.longitude) ? haversine(userCoords.lat, userCoords.lon, b.latitude, b.longitude) : 9999
      return da - db_
    }
    if (sortBy === 'rating') return (b.avg_rating ?? 0) - (a.avg_rating ?? 0)
    if (sortBy === 'reviews') return (b.review_count ?? 0) - (a.review_count ?? 0)
    return 0
  }) : null

  const mappable = (visibleChurches || []).filter(c => c.latitude && c.longitude)
  const selectedChurch = selectedChurchId
    ? (visibleChurches || []).find(c => c.id === selectedChurchId) ?? null
    : null

  function toggleTag(tag) {
    setSelectedTags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag])
  }

  function tryDemo() {
    setCity('Brooklyn')
    setState('NY')
    setTimeout(() => { document.querySelector('form')?.requestSubmit() }, 0)
  }

  function markerIcon(id) {
    const active = id === hoveredId || id === selectedChurchId
    return L.divIcon({
      className: '',
      html: `<div class="map-pin${active ? ' map-pin-active' : ''}"></div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 28],
      popupAnchor: [0, -28],
    })
  }

  function scrollToCard(id) {
    cardRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    setHoveredId(id)
  }

  function handleSelectChurch(id) {
    setSelectedChurchId(id)
    setHoveredId(id)
  }

  const hasResults = !loading && churches !== null

  return (
    <div className="search-page">
      <div className="search-top">
        <header>
          <h1>ChurchMap</h1>
          <p>Find your church — rated on what actually matters.</p>
        </header>

        <form onSubmit={handleSearch}>
          <div className="search-form">
            <input
              value={city} onChange={e => setCity(e.target.value)}
              placeholder="City" aria-label="City"
            />
            <input
              value={state} onChange={e => setState(e.target.value)}
              placeholder="State (e.g. NY)" aria-label="State" style={{ maxWidth: 120 }}
            />
            <button type="submit" className="search-btn" disabled={loading}>
              {loading ? 'Searching…' : 'Search'}
            </button>
          </div>
          <div className="demo-hint">
            Try:{' '}
            <button type="button" onClick={tryDemo}>Brooklyn, NY →</button>
          </div>
        </form>

        {detectedLocation && !loading && (
          <p className="location-detected">
            📍 Showing churches near <strong>{detectedLocation.city}, {detectedLocation.state}</strong>
          </p>
        )}
        {error && <p className="error-msg">{error}</p>}
        {loading && <p className="loading">Finding churches…</p>}

        {hasResults && !selectedChurchId && (
          <>
            <div className="sort-bar">
              <span className="sort-label">Sort:</span>
              {[
                { key: 'distance', label: '📍 Nearest', disabled: !userCoords?.lat },
                { key: 'rating',   label: '★ Rating' },
                { key: 'reviews',  label: '💬 Reviews' },
              ].map(({ key, label, disabled }) => (
                <button
                  key={key} type="button" disabled={disabled}
                  className={`sort-pill${sortBy === key ? ' sort-active' : ''}`}
                  onClick={() => setSortBy(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            {(availableTags.length > 0 || availableLangs.length > 0) && (
              <div className="tag-filter-bar">
                {availableLangs.map(lang => (
                  <button
                    key={lang} type="button"
                    onClick={() => setSelectedLang(prev => prev === lang ? null : lang)}
                    className={`tag-filter-pill tag-filter-lang${selectedLang === lang ? ' tag-active' : ''}`}
                  >
                    {lang}
                  </button>
                ))}
                {availableTags.map(tag => (
                  <button
                    key={tag} type="button"
                    onClick={() => toggleTag(tag)}
                    className={`tag-filter-pill${selectedTags.includes(tag) ? ' tag-active' : ''}`}
                  >
                    {tag}
                  </button>
                ))}
                {(selectedTags.length > 0 || selectedLang) && (
                  <button type="button" className="tag-clear" onClick={() => { setSelectedTags([]); setSelectedLang(null) }}>
                    Clear
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {hasResults && (
        <div className="results-pane">
          {/* ── List / Detail panel ── */}
          <div className="list-panel">
            {selectedChurchId ? (
              <ChurchDetailPanel
                churchId={selectedChurchId}
                onBack={() => { setSelectedChurchId(null); setHoveredId(null) }}
                onSelect={handleSelectChurch}
              />
            ) : visibleChurches?.length === 0 ? (
              <div className="empty-state">
                {churches.length === 0
                  ? <><p>No churches found in {city}, {state}.</p><p style={{ fontSize: '0.85rem' }}>Try a different city!</p></>
                  : <p>No churches match the selected filters.</p>
                }
              </div>
            ) : (
              <>
                <div className="church-list">
                  {visibleChurches?.map(c => (
                    <div
                      key={c.id}
                      ref={el => { cardRefs.current[c.id] = el }}
                      className={`card-wrapper${hoveredId === c.id ? ' card-wrapper-active' : ''}`}
                      onMouseEnter={() => setHoveredId(c.id)}
                      onMouseLeave={() => setHoveredId(null)}
                    >
                      <ChurchCard
                        church={c}
                        userLat={userCoords?.lat}
                        userLon={userCoords?.lon}
                        onSelect={handleSelectChurch}
                      />
                    </div>
                  ))}
                </div>
                {hasMore && selectedTags.length === 0 && (
                  <div className="load-more-row">
                    <button
                      type="button"
                      className="load-more-btn"
                      onClick={handleLoadMore}
                      disabled={loadingMore}
                    >
                      {loadingMore ? 'Loading…' : 'Load more churches'}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* ── Map panel ── */}
          <div className="map-panel">
            <MapContainer
              center={[39.5, -98.35]}
              zoom={4}
              style={{ height: '100%', width: '100%' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {!selectedChurch && <MapBounds churches={mappable} />}
              {selectedChurch && <MapFlyTo church={selectedChurch} />}
              {mappable.map(c => (
                <Marker
                  key={c.id}
                  position={[c.latitude, c.longitude]}
                  icon={markerIcon(c.id)}
                  eventHandlers={{
                    click: () => handleSelectChurch(c.id),
                    mouseover: () => setHoveredId(c.id),
                    mouseout:  () => setHoveredId(null),
                  }}
                >
                  <Popup>
                    <div className="map-popup">
                      <strong>{c.name}</strong>
                      {c.denomination && <span className="popup-denom">{c.denomination}</span>}
                      {c.avg_rating != null && (
                        <span className="popup-rating">★ {c.avg_rating.toFixed(1)}</span>
                      )}
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </div>
        </div>
      )}
    </div>
  )
}
