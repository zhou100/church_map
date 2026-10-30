import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback, lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import AccountButton from '../components/AccountButton'
import ChurchCard from '../components/ChurchCard'
import FitPreferences from '../components/FitPreferences'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { detectLocation, getSearchCenter, listChurches, takeSearchPrefetch } from '../api/client'
import { cityLanguageChips, fitReason, zeroMatchSentence } from '../churchProfile'
import { EMPTY_PREFERENCES, hasPreferences, loadPreferences, savePreferences } from '../preferences'
import {
  EMPTY_RESULTS,
  NEARBY_MILES,
  PAGE_SIZE,
  apiRequest,
  failPage,
  firstPage,
  loadSnapshot,
  mergePage,
  originLabel,
  paramsFromQuery,
  queryFromParams,
  queryKey,
  resolveSort,
  saveSnapshot,
} from '../searchScope'

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
  const [query, setQuery] = useState(null)
  const [results, setResults] = useState(EMPTY_RESULTS)
  const [attempt, setAttempt] = useState(0)
  const [prefs, setPrefs] = useState(EMPTY_PREFERENCES)
  const [prefsReady, setPrefsReady] = useState(false)
  const [scopeBusy, setScopeBusy] = useState(false)
  const [scopeError, setScopeError] = useState(null)
  const [locating, setLocating] = useState(false)
  const [mobileView, setMobileView] = useState('list')
  const [hoveredId, setHoveredId] = useState(null)
  const [selectedChurchId, setSelectedChurchId] = useState(null)
  const [wideLayout, setWideLayout] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_MAP).matches,
  )
  const [mapActivated, setMapActivated] = useState(wideLayout)
  const listPanel = useRef(null)
  const sentinel = useRef(null)
  const controller = useRef(null)
  const activeKey = useRef(null)
  const loadingMore = useRef(false)
  const scrollAtLoad = useRef(0)
  const listScroll = useRef(0)
  const restoreScroll = useRef(null)
  const restoreAllowed = useRef(true)
  // Bumped by every query the visitor starts. A slow center or location
  // lookup that began before it must not apply its result afterwards.
  const scopeOp = useRef(0)

  const key = query && queryKey(query, prefs)
  const sort = query && resolveSort(query, prefs)

  // One list per query key: a new scope, sort or (For you) preference set
  // abandons the old request and starts again at page one.
  useEffect(() => {
    if (!query || !prefsReady) return
    controller.current?.abort()
    const ctrl = new AbortController()
    controller.current = ctrl
    activeKey.current = key
    loadingMore.current = false
    scrollAtLoad.current = 0
    setSearchParams(paramsFromQuery(query), { replace: true })
    if (query.scope.kind !== 'name') {
      try { localStorage.setItem('churchmap_last_search', JSON.stringify({ city: query.scope.city, state: query.scope.state })) } catch { /* Optional. */ }
    }
    // Only on arrival (e.g. Back from a church page); a search the visitor
    // starts here always asks the server again.
    const snapshot = restoreAllowed.current && loadSnapshot(key)
    restoreAllowed.current = false
    if (snapshot) {
      setResults({ ...EMPTY_RESULTS, key, rows: snapshot.rows, total: snapshot.total, nextOffset: snapshot.nextOffset, hasMore: snapshot.hasMore })
      restoreScroll.current = snapshot.scrollTop || 0
      return () => ctrl.abort()
    }
    // The previous rows stay on screen (dimmed) until page one arrives, so a
    // chip or sort change doesn't tear down the list under the visitor.
    setResults(prev => ({ ...EMPTY_RESULTS, key, rows: prev.rows, status: 'loading' }))
    fetchPage(query, prefs, key, 0, ctrl)
    return () => ctrl.abort()
  }, [key, prefsReady, attempt]) // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchPage(forQuery, forPrefs, forKey, offset, ctrl) {
    const { search, options } = apiRequest(forQuery, forPrefs)
    const pageOptions = { ...options, limit: PAGE_SIZE, offset, signal: ctrl.signal }
    try {
      // Landing (or the entry script) may already have asked for page one.
      const page = offset === 0
        ? await firstPage(takeSearchPrefetch(forKey), search, pageOptions)
        : await listChurches(search, pageOptions)
      if (ctrl.signal.aborted || activeKey.current !== forKey) return
      setResults(prev => mergePage(prev, page, { offset }))
    } catch (err) {
      if (ctrl.signal.aborted || activeKey.current !== forKey) return
      setResults(prev => failPage(prev, err.message, { offset }))
    } finally {
      if (activeKey.current === forKey) {
        loadingMore.current = false
        scrollAtLoad.current = listPanel.current?.scrollTop ?? 0
      }
    }
  }

  function loadMore() {
    if (loadingMore.current || !results.hasMore || !['idle', 'moreError'].includes(results.status)) return
    loadingMore.current = true
    setResults(prev => ({ ...prev, status: 'more', error: null }))
    fetchPage(query, prefs, key, results.nextOffset, controller.current)
  }

  // Scrolling near the end loads one more page, but only once the visitor has
  // moved down the list since the last load: a tall screen, a layout shift
  // or scroll anchoring never walks the pages on its own. A failed page
  // waits for an explicit retry.
  useEffect(() => {
    const target = sentinel.current, root = listPanel.current
    if (!target || !root || typeof IntersectionObserver !== 'function') return undefined
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && results.status === 'idle'
        && root.scrollTop - scrollAtLoad.current > 240) loadMore()
    }, { root, rootMargin: '0px 0px 320px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  })

  // Remember the list, so returning from a church page restores it: on each
  // new page, on pagehide, and when an in-app link leaves Search. Never while
  // a new query is loading, when the rows on screen belong to the old one.
  const persistRef = useRef(null)
  persistRef.current = results.rows && results.key === key && ['idle', 'more', 'moreError'].includes(results.status)
    ? { key, rows: results.rows, total: results.total, nextOffset: results.nextOffset, hasMore: results.hasMore }
    : null
  function persist() {
    if (persistRef.current) saveSnapshot({ ...persistRef.current, scrollTop: listScroll.current })
  }
  useEffect(persist, [results, key])
  useEffect(() => {
    window.addEventListener('pagehide', persist)
    return () => { window.removeEventListener('pagehide', persist); persist() }
  }, [])

  function handleListScroll(event) {
    if (selectedChurchId) return
    listScroll.current = event.currentTarget.scrollTop
  }

  // Back from the in-panel detail, or from a church page: same scroll spot.
  useLayoutEffect(() => {
    if (selectedChurchId || restoreScroll.current == null || !results.rows || !listPanel.current) return
    listPanel.current.scrollTop = restoreScroll.current
    listScroll.current = restoreScroll.current
    scrollAtLoad.current = listPanel.current.scrollTop
    restoreScroll.current = null
  })

  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_MAP)
    const onChange = () => setWideLayout(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // On a phone the list is the default, so Leaflet stays unloaded until the
  // visitor asks for the map (or the viewport already shows it).
  useEffect(() => {
    if (mobileView === 'map' || wideLayout) setMapActivated(true)
  }, [mobileView, wideLayout])

  useEffect(() => {
    setPrefs(loadPreferences())
    setPrefsReady(true)
    const initial = queryFromParams(searchParams)
    if (initial) setQuery(initial)
    return () => controller.current?.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function startQuery(next) {
    scopeOp.current++
    setScopeBusy(false)
    setSelectedChurchId(null)
    setScopeError(null)
    setMobileView('list')
    restoreScroll.current = 0
    setQuery(next)
    setAttempt(n => n + 1)
  }

  // While the visitor hasn't picked a sort, saved preferences turn "For
  // you" on (and clearing them turns it off) through resolveSort.
  function updatePrefs(next) {
    setPrefs(next)
    savePreferences(next)
  }

  function handleLocationSearch(e) {
    e.preventDefault()
    if (!city.trim() || !state.trim()) return
    startQuery({ scope: { kind: 'city', city: city.trim(), state: state.trim() }, sort: null, you: null })
  }

  function handleNameSearch(e) {
    e.preventDefault()
    if (churchName.trim().length < 2) return
    startQuery({ scope: { kind: 'name', name: churchName.trim() }, sort: null, you: null })
  }

  function tryDemo() {
    setCity('Brooklyn')
    setState('NY')
    setSearchMode('location')
    startQuery({ scope: { kind: 'city', city: 'Brooklyn', state: 'NY' }, sort: null, you: null })
  }

  async function handleNearMe() {
    const op = ++scopeOp.current
    setLocating(true)
    setScopeError(null)
    try {
      const location = await detectLocation()
      if (op !== scopeOp.current) return
      setCity(location.city)
      setState(location.state)
      setSearchMode('location')
      const you = Number.isFinite(location.lat) && Number.isFinite(location.lon) ? { lat: location.lat, lon: location.lon } : null
      startQuery({ scope: { kind: 'city', city: location.city, state: location.state }, sort: null, you })
    } catch (err) {
      if (op === scopeOp.current) setScopeError(err.message)
    } finally {
      setLocating(false)
    }
  }

  // Widening is always the visitor's choice: a center and a distance.
  async function includeNearby(centerSource = query.you ? 'you' : 'city', miles = 10) {
    const { city: scopeCity, state: scopeState } = query.scope
    const op = ++scopeOp.current
    setScopeError(null)
    if (centerSource === 'you' && query.you) {
      startQuery({ ...query, scope: { kind: 'nearby', city: scopeCity, state: scopeState, center: query.you, centerSource, miles } })
      return
    }
    setScopeBusy(true)
    try {
      if (centerSource === 'you') {
        const location = await detectLocation()
        if (op !== scopeOp.current) return
        if (!Number.isFinite(location.lat) || !Number.isFinite(location.lon)) throw new Error('Your location has no coordinates')
        const you = { lat: location.lat, lon: location.lon }
        startQuery({ ...query, you, scope: { kind: 'nearby', city: scopeCity, state: scopeState, center: you, centerSource, miles } })
      } else {
        const center = await getSearchCenter(scopeCity, scopeState)
        if (op !== scopeOp.current) return
        startQuery({ ...query, scope: { kind: 'nearby', city: scopeCity, state: scopeState, center: { lat: center.lat, lon: center.lon }, centerSource, miles } })
      }
    } catch (err) {
      if (op === scopeOp.current) setScopeError(`${err.message}. The list still shows ${scopeCity} only.`)
    } finally {
      if (op === scopeOp.current) setScopeBusy(false)
    }
  }

  function onlyCity() {
    startQuery({ ...query, scope: { kind: 'city', city: query.scope.city, state: query.scope.state } })
  }

  function chooseSort(next) {
    if (next !== sort) startQuery({ ...query, sort: next })
  }

  // Stable for the memoized cards; the ref tells it whether the list (not
  // another church's detail) is what Back should return to.
  const selectedRef = useRef(null)
  selectedRef.current = selectedChurchId
  const handleSelectChurch = useCallback((id) => {
    if (!selectedRef.current) restoreScroll.current = listScroll.current
    setSelectedChurchId(id)
    setHoveredId(id)
    setMobileView('list')
  }, [])

  // Rows of the previous query stay visible until the new page one lands;
  // only settled rows count for paging, empty states and fitting the map.
  const rows = results.rows
  const settled = Boolean(rows) && results.key === key && !['loading', 'error'].includes(results.status)
  const scope = query?.scope
  const isLocation = scope && scope.kind !== 'name'
  const forYou = sort === 'forYou'
  const mappable = useMemo(() => (rows || []).filter(c => c.latitude && c.longitude), [rows])
  const selectedChurch = selectedChurchId ? (rows || []).find(c => c.id === selectedChurchId) ?? null : null
  const loading = results.status === 'loading' || (Boolean(query) && results.key !== key)
  const hasResults = Boolean(rows)
  const scopeName = scope?.kind === 'name' ? `names matching “${scope.name}”`
    : scope?.kind === 'nearby' ? `within ${scope.miles} mi of ${originLabel(query)}`
      : scope ? `churches listed in ${scope.city}, ${scope.state}` : ''
  const otherSort = scope?.kind === 'name' ? { key: 'relevance', label: 'Best match' } : { key: 'distance', label: 'Nearest' }
  // "For you": the server ranked the whole scope, so if the first rows hold
  // no match, nothing later does either. Nearest in a city: until the last
  // page, the sentence speaks only of the churches nearest the middle.
  const zeroMatch = settled && isLocation && (forYou || scope.kind === 'city')
    ? zeroMatchSentence(rows, prefs, {
      city: scope.kind === 'nearby' ? `this ${scope.miles}-mile area` : scope.city,
      limit: results.hasMore ? rows.length : rows.length + 1,
      ranked: forYou,
      nearestFirst: !forYou,
    })
    : null

  return (
    <div className="search-page">
      <Seo
        title={scope?.kind === 'name'
          ? `${scope.name} church search`
          : scope ? `Churches in ${scope.city}, ${scope.state}` : 'Search churches'}
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
                {loading ? 'Searching…' : 'Search city'}
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

        {isLocation && (
          <div className="scope-bar" role="group" aria-label="Search area">
            <p className="scope-current">
              <Icon name="pin" size={14} />
              <span>Showing <strong>{scopeName}</strong>
                {scope.kind === 'nearby' && <> · includes nearby cities</>}</span>
            </p>
            {scope.kind === 'city' ? (
              <button type="button" className="scope-btn" onClick={() => includeNearby()} disabled={scopeBusy || loading}>
                {scopeBusy ? 'Finding the center…' : 'Include nearby cities'}
              </button>
            ) : (
              <>
                <button type="button" className="scope-btn" onClick={onlyCity}>
                  Back to {scope.city} only
                </button>
                <div className="scope-options">
                  <fieldset>
                    <legend>Center</legend>
                    <button type="button" aria-pressed={scope.centerSource === 'city'} disabled={scopeBusy}
                      onClick={() => scope.centerSource !== 'city' && includeNearby('city', scope.miles)}>
                      {scope.city} center (approx.)
                    </button>
                    <button type="button" aria-pressed={scope.centerSource === 'you'} disabled={scopeBusy}
                      onClick={() => scope.centerSource !== 'you' && includeNearby('you', scope.miles)}>
                      My approximate location
                    </button>
                  </fieldset>
                  <fieldset>
                    <legend>Distance</legend>
                    {NEARBY_MILES.map(miles => (
                      <button key={miles} type="button" aria-pressed={scope.miles === miles}
                        onClick={() => scope.miles !== miles && startQuery({ ...query, scope: { ...scope, miles } })}>
                        {miles} mi
                      </button>
                    ))}
                  </fieldset>
                </div>
              </>
            )}
          </div>
        )}
        {scopeError && <p className="error-msg">{scopeError}</p>}
        {results.status === 'error' && (
          <p className="error-msg">{results.error} <button type="button" className="retry-btn" onClick={() => setAttempt(n => n + 1)}>Try again</button></p>
        )}
        {loading && !hasResults && <p className="loading">Finding churches…</p>}

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
          <div className={`list-panel${loading ? ' list-updating' : ''}`} ref={listPanel}
            onScroll={handleListScroll} aria-busy={loading}>
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
                <div className="results-summary">
                  <span aria-live="polite">
                    {loading ? 'Updating…' : results.total != null
                      ? `Showing ${rows.length} of ${results.total}`
                      : `Showing ${rows.length}${results.hasMore ? ', more available' : ''}`}
                    {' · '}
                    {forYou ? (hasPreferences(prefs) ? 'Most evidence for your preferences first' : 'Best-documented first')
                      : isLocation ? `Nearest to ${originLabel(query)} first` : 'Best name match first'}
                  </span>
                  {/* "For you" turns itself on when preferences are saved; this
                      keeps the other order one tap away, and the pick sticks. */}
                  {(hasPreferences(prefs) || forYou) && (
                    <div className="sort-switch" role="group" aria-label="Sort">
                      {[{ key: 'forYou', label: 'For you' }, otherSort].map(option => (
                        <button key={option.key} type="button" aria-pressed={sort === option.key}
                          className={`sort-pill${sort === option.key ? ' sort-active' : ''}`}
                          onClick={() => chooseSort(option.key)}>
                          {option.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <FitPreferences
                  className="search-fit"
                  prefs={prefs}
                  onChange={updatePrefs}
                  languageChips={cityLanguageChips(rows, prefs.languages)}
                  phoneMediaQuery="(max-width: 839px)"
                />
                {zeroMatch && <p className="search-fit-nomatch">{zeroMatch}</p>}
                {settled && rows.length === 0 ? (
                  <div className="empty-state">
                    {scope.kind === 'name'
                      ? <><p>No churches found matching “{scope.name}”.</p><p>Try a shorter or different name.</p></>
                      : scope.kind === 'city'
                        ? <><p>No churches are listed in {scope.city}, {scope.state}.</p><p>Check the spelling, or include nearby cities.</p></>
                        : <><p>No mapped churches within {scope.miles} miles.</p><p>Choose a larger distance. Churches without coordinates cannot appear in a distance search.</p></>}
                  </div>
                ) : (
                  <>
                    {/* Stale rows while a new query loads are shown but not paged. */}
                    <div className="church-list">
                      {rows.map(c => (
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
                            showDistance={isLocation}
                            showLocation={scope.kind !== 'city'}
                            fitReason={fitReason(c, prefs)}
                            onSelect={handleSelectChurch}
                          />
                        </div>
                      ))}
                    </div>
                    <div ref={loading ? null : sentinel} className="list-sentinel" aria-hidden="true" />
                    {results.status === 'moreError' && (
                      <p className="error-msg load-more-error" role="alert">
                        Couldn’t load more: {results.error}. The {rows.length} churches above are still here.
                      </p>
                    )}
                    {results.hasMore && !loading && (
                      <div className="load-more-row">
                        {/* aria-disabled, not disabled: a disabled button drops
                            keyboard focus to <body> mid-load. */}
                        <button type="button" className="load-more-btn" onClick={loadMore}
                          aria-disabled={results.status === 'more'}>
                          {results.status === 'more' ? 'Loading…'
                            : results.status === 'moreError' ? 'Try again'
                              : `Load ${results.total != null ? Math.min(PAGE_SIZE, results.total - rows.length) : PAGE_SIZE} more`}
                        </button>
                      </div>
                    )}
                    {!results.hasMore && !loading && scope.kind === 'city' && (
                      <p className="list-end">
                        That’s every church listed in {scope.city}.{' '}
                        <button type="button" className="link-btn" onClick={() => includeNearby()} disabled={scopeBusy}>Include nearby cities</button>
                      </p>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          {mapActivated && (
            <div className="map-panel">
              <p className="map-loaded-note">
                Map: {mappable.length} loaded {mappable.length === 1 ? 'church' : 'churches'}
                {rows.length > mappable.length && ` · ${rows.length - mappable.length} without a location`}
              </p>
              <Suspense fallback={null}>
                <SearchMap
                  mappable={mappable}
                  selectedChurch={selectedChurch}
                  hoveredId={hoveredId}
                  selectedChurchId={selectedChurchId}
                  onSelect={handleSelectChurch}
                  onHover={setHoveredId}
                  hoverEnabled={CAN_HOVER}
                  mobileView={mobileView}
                  fitKey={settled ? key : null}
                  circle={scope.kind === 'nearby' ? scope : null}
                />
              </Suspense>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
