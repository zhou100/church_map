import { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import AccountButton from '../components/AccountButton'
import ChurchCard from '../components/ChurchCard'
import FitPreferences from '../components/FitPreferences'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import {
  SEARCH_CITY_SORT,
  SEARCH_PAGE as PAGE,
  detectLocation,
  listChurches,
  takeCitySearchPrefetch,
} from '../api/client'
import { cityLanguageChips, fitReason, rankForYou, zeroMatchSentence } from '../churchProfile'
import { EMPTY_PREFERENCES, hasPreferences, loadPreferences, savePreferences } from '../preferences'

const SearchMap = lazy(() => import('../components/SearchMap'))
const ChurchDetailPanel = lazy(() => import('../components/ChurchDetailPanel'))

const DESKTOP_MAP = '(min-width: 840px)'
const CAN_HOVER = typeof window !== 'undefined' && window.matchMedia('(hover: hover)').matches

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
  const [prefs, setPrefs] = useState(EMPTY_PREFERENCES)
  const [detectedLocation, setDetectedLocation] = useState(null)
  const [userCoords, setUserCoords] = useState(null)
  const [locating, setLocating] = useState(false)
  const [mobileView, setMobileView] = useState('list')
  const [hoveredId, setHoveredId] = useState(null)
  const [selectedChurchId, setSelectedChurchId] = useState(null)
  const [wideLayout, setWideLayout] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_MAP).matches,
  )
  const [mapActivated, setMapActivated] = useState(wideLayout)
  const offsetRef = useRef(0)

  function updatePrefs(next) {
    setPrefs(next)
    savePreferences(next)
  }

  async function fetchPage(search, offset, append = false) {
    let data = null
    if (!append && offset === 0 && search.type === 'location') {
      const prefetched = takeCitySearchPrefetch(search.city, search.state)
      if (prefetched) {
        try {
          data = await prefetched
        } catch {
          data = null
        }
      }
    }
    if (data == null) {
      data = await listChurches(search, {
        limit: PAGE,
        offset,
        sort: search.type === 'location' ? SEARCH_CITY_SORT : undefined,
      })
    }
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
    setDetectedLocation(location ? { city: location.city, state: location.state } : null)
    setUserCoords(location ? { lat: location.lat, lon: location.lon } : null)
    setSelectedChurchId(null)
    setMobileView('list')
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
    const mq = window.matchMedia(DESKTOP_MAP)
    const onChange = () => setWideLayout(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (mobileView === 'map' || wideLayout) setMapActivated(true)
  }, [mobileView, wideLayout])

  useEffect(() => {
    const storedPrefs = loadPreferences()
    setPrefs(storedPrefs)
    const n = searchParams.get('name')
    const c = searchParams.get('city')
    const s = searchParams.get('state')
    if (n) {
      const search = { type: 'name', name: n }
      setChurchName(n)
      setSearchMode('name')
      setActiveSearch(search)
      setLoading(true)
      setError(null)
      offsetRef.current = 0
      fetchPage(search, 0)
        .catch(err => setError(err.message))
        .finally(() => setLoading(false))
    } else if (c && s) {
      const search = { type: 'location', city: c, state: s }
      localStorage.setItem('churchmap_last_search', JSON.stringify({ city: c, state: s }))
      setCity(c)
      setState(s)
      setSearchMode('location')
      setActiveSearch(search)
      setLoading(true)
      setError(null)
      offsetRef.current = 0
      fetchPage(search, 0)
        .catch(err => setError(err.message))
        .finally(() => setLoading(false))
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectChurch = useCallback((id) => {
    setSelectedChurchId(id)
    setHoveredId(id)
    setMobileView('list')
  }, [])

  // No sort control: a city search is nearest-first (the API's order), and
  // once the visitor has said what matters, most evidence for that first,
  // nearer churches winning ties. A name search keeps its best-match order.
  const forYou = activeSearch?.type === 'location' && hasPreferences(prefs)
  const visibleChurches = useMemo(() => {
    if (!churches) return null
    return forYou ? rankForYou(churches, prefs) : churches
  }, [churches, forYou, prefs])

  // Exact only once every page of the city is loaded (no "Load more" left).
  const forYouZeroMatch = churches && forYou
    ? zeroMatchSentence(churches, prefs, {
      city: activeSearch.city,
      limit: hasMore ? churches.length : churches.length + 1,
    })
    : null

  const mappable = useMemo(
    () => (visibleChurches || []).filter(c => c.latitude && c.longitude),
    [visibleChurches],
  )
  const selectedChurch = selectedChurchId
    ? (visibleChurches || []).find(c => c.id === selectedChurchId) ?? null
    : null

  function tryDemo() {
    setCity('Brooklyn')
    setState('NY')
    setSearchMode('location')
    runSearch({ type: 'location', city: 'Brooklyn', state: 'NY' })
  }

  const hasChurches = churches !== null

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
          <div>
            <a href="/" className="wordmark" aria-label="ChurchMap home">
              ChurchMap
            </a>
            <p>Know what a Sunday is actually like before you walk in.</p>
          </div>
          <AccountButton />
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
        {loading && !hasChurches && <p className="loading">Finding churches…</p>}

        {hasChurches && (
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

      {hasChurches && (
        <div className={`results-pane mobile-view-${mobileView}`}>
          {loading && <div className="results-loading" role="status">Finding churches…</div>}
          {/* ── List / Detail panel ── */}
          <div className="list-panel">
            {selectedChurchId ? (
              <Suspense fallback={<div className="loading" style={{ padding: '2rem 0' }}>Loading…</div>}>
                <ChurchDetailPanel
                  churchId={selectedChurchId}
                  onBack={() => { setSelectedChurchId(null); setHoveredId(null) }}
                  onSelect={handleSelectChurch}
                />
              </Suspense>
            ) : (
              <>
                {/* In the list column, so opening the panel on desktop grows
                    the list, not the header above both panes. */}
                <FitPreferences
                  className="search-fit"
                  prefs={prefs}
                  onChange={updatePrefs}
                  languageChips={cityLanguageChips(churches, prefs.languages)}
                  phoneMediaQuery="(max-width: 839px)"
                />
                {forYouZeroMatch && <p className="search-fit-nomatch">{forYouZeroMatch}</p>}
                {visibleChurches?.length === 0 ? (
                  <div className="empty-state">
                    {activeSearch?.type === 'name'
                      ? <><p>No churches found matching “{activeSearch.name}”.</p><p>Try a shorter or different name.</p></>
                      : <><p>No churches found in {city}, {state}.</p><p>Our directory is still growing. Try a nearby city or check the spelling.</p></>}
                  </div>
                ) : (
                  <>
                    <div className="church-list">
                      {visibleChurches?.map(c => (
                        <div
                          key={c.id}
                          className={`card-wrapper${hoveredId === c.id ? ' card-wrapper-active' : ''}`}
                          {...(CAN_HOVER ? {
                            onMouseEnter: () => setHoveredId(c.id),
                            onMouseLeave: () => setHoveredId(null),
                          } : {})}
                        >
                          <ChurchCard
                            church={c}
                            userLat={userCoords?.lat}
                            userLon={userCoords?.lon}
                            showLocation={activeSearch?.type === 'name'}
                            fitReason={fitReason(c, prefs)}
                            onSelect={handleSelectChurch}
                          />
                        </div>
                      ))}
                    </div>
                    {hasMore && (
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
              </>
            )}
          </div>

          {/* ── Map panel. On a phone the list is the default, so Leaflet stays
              unloaded until the visitor asks for the map (or the viewport is
              wide enough that the map is already on screen). ── */}
          {mapActivated && (
            <div className="map-panel">
              <Suspense fallback={null}>
                <SearchMap
                  mappable={mappable}
                  selectedChurch={selectedChurch}
                  hoveredId={hoveredId}
                  selectedChurchId={selectedChurchId}
                  activeSearch={activeSearch}
                  onSelect={handleSelectChurch}
                  onHover={setHoveredId}
                  hoverEnabled={CAN_HOVER}
                  mobileView={mobileView}
                />
              </Suspense>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
