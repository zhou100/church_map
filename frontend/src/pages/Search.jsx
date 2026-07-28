import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import ChurchCard from '../components/ChurchCard'
import ChurchDetailPanel from '../components/ChurchDetailPanel'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { churchMarkerIcon } from '../components/mapMarker'
import { detectLocation, listChurches } from '../api/client'

const PAGE = 50

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

function MapResize({ active }) {
  const map = useMap()
  useEffect(() => {
    if (!active) return
    const frame = requestAnimationFrame(() => map.invalidateSize())
    return () => cancelAnimationFrame(frame)
  }, [active, map])
  return null
}

function hasWebsiteProfile(church) {
  const extracted = church.extracted_tags || {}
  return Boolean(
    church.website_summary ||
    Object.values(extracted).some(value => Array.isArray(value) ? value.length : value)
  )
}

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [city, setCity] = useState(searchParams.get('city') || '')
  const [state, setState] = useState(searchParams.get('state') || '')
  const [churchName, setChurchName] = useState(searchParams.get('name') || '')
  const [searchMode, setSearchMode] = useState(searchParams.get('name') ? 'name' : 'location')
  const [activeSearch, setActiveSearch] = useState(null)
  const [churches, setChurches] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState(null)
  const [selectedTags, setSelectedTags] = useState([])
  const [selectedLang, setSelectedLang] = useState(null)
  const [sortBy, setSortBy] = useState('usefulness')
  const [detectedLocation, setDetectedLocation] = useState(null)
  const [userCoords, setUserCoords] = useState(null)
  const [locating, setLocating] = useState(false)
  const [mobileView, setMobileView] = useState('list')
  const [hoveredId, setHoveredId] = useState(null)
  const [selectedChurchId, setSelectedChurchId] = useState(null)
  const offsetRef = useRef(0)

  async function fetchPage(search, offset, append = false) {
    const data = await listChurches(search, { limit: PAGE, offset })
    if (append) {
      setChurches(prev => [...(prev || []), ...data])
    } else {
      setChurches(data)
    }
    setHasMore(data.length === PAGE)
    offsetRef.current = offset + data.length
    return data
  }

  async function runSearch(search, location = null) {
    setSearchParams(search.type === 'name'
      ? { name: search.name }
      : { city: search.city, state: search.state })
    if (search.type === 'location') {
      localStorage.setItem('churchmap_last_search', JSON.stringify({
        city: search.city,
        state: search.state,
      }))
    }
    setActiveSearch(search)
    setSelectedTags([])
    setSelectedLang(null)
    setDetectedLocation(location ? { city: location.city, state: location.state } : null)
    setUserCoords(location ? { lat: location.lat, lon: location.lon } : null)
    setSelectedChurchId(null)
    setMobileView('list')
    setSortBy(search.type === 'name' ? 'relevance' : 'usefulness')
    setLoading(true)
    setError(null)
    offsetRef.current = 0
    try {
      await fetchPage(search, 0)
    } catch (err) {
      setError(`${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  function handleLocationSearch(e) {
    e.preventDefault()
    if (!city.trim() || !state.trim()) return
    runSearch({ type: 'location', city: city.trim(), state: state.trim() })
  }

  function handleNameSearch(e) {
    e.preventDefault()
    if (churchName.trim().length < 2) return
    runSearch({ type: 'name', name: churchName.trim() })
  }

  async function handleLoadMore() {
    if (!activeSearch) return
    setLoadingMore(true)
    try {
      await fetchPage(activeSearch, offsetRef.current, true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingMore(false)
    }
  }

  async function handleNearMe() {
    setLocating(true)
    setError(null)
    try {
      const location = await detectLocation()
      setCity(location.city)
      setState(location.state)
      setSearchMode('location')
      await runSearch({
        type: 'location',
        city: location.city,
        state: location.state,
      }, location)
    } catch (err) {
      setError(err.message)
    } finally {
      setLocating(false)
    }
  }

  useEffect(() => {
    const n = searchParams.get('name')
    const c = searchParams.get('city')
    const s = searchParams.get('state')
    if (n) {
      const search = { type: 'name', name: n }
      setChurchName(n)
      setSearchMode('name')
      setActiveSearch(search)
      setSortBy('relevance')
      setLoading(true)
      setError(null)
      offsetRef.current = 0
      fetchPage(search, 0)
        .then(() => setSelectedTags([]))
        .catch(err => setError(err.message))
        .finally(() => setLoading(false))
    } else if (c && s) {
      const search = { type: 'location', city: c, state: s }
      localStorage.setItem('churchmap_last_search', JSON.stringify({ city: c, state: s }))
      setCity(c)
      setState(s)
      setSearchMode('location')
      setActiveSearch(search)
      setSortBy('usefulness')
      setLoading(true)
      setError(null)
      offsetRef.current = 0
      fetchPage(search, 0)
        .then(() => setSelectedTags([]))
        .catch(err => setError(err.message))
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
    if (sortBy === 'usefulness') {
      const profileDifference = Number(hasWebsiteProfile(b)) - Number(hasWebsiteProfile(a))
      if (profileDifference) return profileDifference
      return (b.review_count ?? 0) - (a.review_count ?? 0)
    }
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
    setSearchMode('location')
    runSearch({ type: 'location', city: 'Brooklyn', state: 'NY' })
  }

  function markerIcon(id) {
    const active = id === hoveredId || id === selectedChurchId
    return churchMarkerIcon(active)
  }

  function handleSelectChurch(id) {
    setSelectedChurchId(id)
    setHoveredId(id)
    setMobileView('list')
  }

  const hasResults = !loading && churches !== null

  return (
    <div className="search-page">
      <Seo
        title={activeSearch?.type === 'name'
          ? `${activeSearch.name} church search`
          : activeSearch
            ? `Churches in ${activeSearch.city}, ${activeSearch.state}`
            : 'Search churches'}
        description="Find churches by city or name, then see what their own websites say and community ratings where available."
        canonicalPath={`/search${searchParams.toString() ? `?${searchParams}` : ''}`}
      />
      <div className="search-top">
        <header>
          <a href="/" className="wordmark" aria-label="ChurchMap home">
            ChurchMap
          </a>
          <p>Know what a Sunday is actually like before you walk in.</p>
        </header>

        <div className="search-mode-tabs" role="tablist" aria-label="Search by">
          <button
            type="button"
            role="tab"
            aria-selected={searchMode === 'location'}
            className={searchMode === 'location' ? 'search-mode-active' : ''}
            onClick={() => setSearchMode('location')}
          >
            By location
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={searchMode === 'name'}
            className={searchMode === 'name' ? 'search-mode-active' : ''}
            onClick={() => setSearchMode('name')}
          >
            By church name
          </button>
        </div>

        {searchMode === 'location' ? (
          <form onSubmit={handleLocationSearch} className="search-controls">
            <div className="search-form">
              <input
                value={city} onChange={e => setCity(e.target.value)}
                placeholder="City" aria-label="City"
              />
              <input
                value={state} onChange={e => setState(e.target.value)}
                placeholder="State (e.g. NY)" aria-label="State" className="state-input"
              />
              <button type="submit" className="search-btn" disabled={loading || !city.trim() || !state.trim()}>
                {loading ? 'Searching…' : 'Search area'}
              </button>
            </div>
            <div className="demo-hint">
              <button type="button" className="near-me-btn" onClick={handleNearMe} disabled={locating || loading}>
                <Icon name="pin" size={14} /> {locating ? 'Finding your city…' : 'Near me'}
              </button>
              <span>or try </span>
              <button type="button" onClick={tryDemo}>Brooklyn, NY <Icon name="arrow" size={13} /></button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleNameSearch} className="search-controls">
            <div className="search-form church-name-form">
              <input
                value={churchName}
                onChange={e => setChurchName(e.target.value)}
                placeholder="Church name (e.g. Grace Community)"
                aria-label="Church name"
                minLength={2}
                autoFocus
              />
              <button type="submit" className="search-btn" disabled={loading || churchName.trim().length < 2}>
                {loading ? 'Searching…' : 'Find church'}
              </button>
            </div>
            <p className="search-help">Searches church names across all cities.</p>
          </form>
        )}

        {detectedLocation && searchMode === 'location' && !loading && (
          <p className="location-detected">
            <Icon name="pin" size={14} /> Showing churches near <strong>{detectedLocation.city}, {detectedLocation.state}</strong>
          </p>
        )}
        {error && <p className="error-msg">{error}</p>}
        {loading && <p className="loading">Finding churches…</p>}

        {hasResults && !selectedChurchId && (
          <>
            <div className="sort-bar">
              <span className="sort-label">Sort:</span>
              {[
                ...(activeSearch?.type === 'name'
                  ? [{ key: 'relevance', label: 'Best match' }]
                  : [{ key: 'usefulness', label: 'Best profiles' }]),
                { key: 'distance', label: 'Nearest', icon: 'pin', disabled: !userCoords?.lat },
                { key: 'rating',   label: 'Rating' },
                { key: 'reviews',  label: 'Reviews', icon: 'reviews' },
              ].map(({ key, label, icon, disabled }) => (
                <button
                  key={key} type="button" disabled={disabled}
                  className={`sort-pill${sortBy === key ? ' sort-active' : ''}`}
                  onClick={() => setSortBy(key)}
                >
                  {icon && <Icon name={icon} size={13} />} {label}
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

        {hasResults && (
          <div className="mobile-view-toggle" role="group" aria-label="Results view">
            <button
              type="button"
              className={mobileView === 'list' ? 'mobile-view-active' : ''}
              aria-pressed={mobileView === 'list'}
              onClick={() => setMobileView('list')}
            >
              <Icon name="reviews" size={15} /> List
            </button>
            <button
              type="button"
              className={mobileView === 'map' ? 'mobile-view-active' : ''}
              aria-pressed={mobileView === 'map'}
              onClick={() => setMobileView('map')}
            >
              <Icon name="pin" size={15} /> Map
            </button>
          </div>
        )}
      </div>

      {hasResults && (
        <div className={`results-pane mobile-view-${mobileView}`}>
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
                  ? activeSearch?.type === 'name'
                    ? <><p>No churches found matching “{activeSearch.name}”.</p><p>Try a shorter or different name.</p></>
                    : <><p>No churches found in {city}, {state}.</p><p>Our directory is still growing. Try a nearby city or check the spelling.</p></>
                  : <p>No churches match the selected filters.</p>
                }
              </div>
            ) : (
              <>
                <div className="church-list">
                  {visibleChurches?.map(c => (
                    <div
                      key={c.id}
                      className={`card-wrapper${hoveredId === c.id ? ' card-wrapper-active' : ''}`}
                      onMouseEnter={() => setHoveredId(c.id)}
                      onMouseLeave={() => setHoveredId(null)}
                    >
                      <ChurchCard
                        church={c}
                        userLat={userCoords?.lat}
                        userLon={userCoords?.lon}
                        showLocation={activeSearch?.type === 'name'}
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
              <MapResize active={mobileView === 'map'} />
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
              ))}
            </MapContainer>
          </div>
        </div>
      )}
    </div>
  )
}
