import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from '../router'
import AboutSection from '../components/AboutSection'
import AccountButton from '../components/AccountButton'
import DimensionBars from '../components/DimensionBars'
import FitPreferences from '../components/FitPreferences'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { detectLocation, getStats, listChurches } from '../api/client'
import {
  cityLanguageChips,
  fitReason,
  hasWebsiteProfile,
  isStartingPoint,
  pickStartingPoints,
  rankForYou,
  zeroMatchSentence,
} from '../churchProfile'
import { EMPTY_PREFERENCES, hasPreferences, loadPreferences, savePreferences } from '../preferences'
import { prefetchFirstPage } from '../searchScope'

const PREVIEW_LIMIT = 100
const NO_CHURCHES = []
const TOP_PICKS = 3
const AUDITED_COVERAGE = { withSummary: 4332, total: 133939 }
const DEMO_DIMENSIONS = {
  worship_energy: 4.6,
  community_warmth: 4.8,
  sermon_depth: 4.2,
  childrens_programs: 4.0,
  theological_openness: 3.4,
  facilities: 3.8,
}

function parseLocation(value) {
  const match = value.trim().match(/^(.+?),\s*([A-Za-z]{2})$/)
  if (!match) return null
  return { city: match[1].trim(), state: match[2].toUpperCase() }
}

function searchParams({ city, state }) {
  return new URLSearchParams({ city, state })
}

function searchUrl(place) {
  return `/search?${searchParams(place)}`
}

export default function Landing({ exampleChurch }) {
  const navigate = useNavigate()
  const [location, setLocation] = useState('')
  const [locationError, setLocationError] = useState('')
  const [locating, setLocating] = useState(false)
  const [coverage, setCoverage] = useState(AUDITED_COVERAGE)
  // The map renders client-side only (see LandingMap); the prerendered page
  // and the first hydration pass both show the placeholder.
  const [LandingMap, setLandingMap] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewChurches, setPreviewChurches] = useState(null)
  const [previewStatus, setPreviewStatus] = useState('idle')
  const [hoveredId, setHoveredId] = useState(null)
  // Read after hydration (below), never during render: `/` is prerendered
  // and the first paint must match it.
  const [prefs, setPrefs] = useState(EMPTY_PREFERENCES)
  const userEdited = useRef(false)
  const heroCard = useRef(null)
  const previewRequest = useRef(null)
  // What the current rows were ranked for: the server ranks the whole city
  // (sort=for_you) before its row limit, so picks never depend on page one
  // of some other order.
  const [rankedFor, setRankedFor] = useState(null)

  // Search's first page, with the sort and preferences Search will use.
  function prefetchSearch(place) {
    prefetchFirstPage(searchParams(place), prefs)
  }

  function goToSearch(place) {
    prefetchSearch(place)
    navigate(searchUrl(place))
  }

  // One page only. With preferences, the API ranks every church in the city
  // by the same evidence fitScore counts, then by how much a newcomer can
  // learn; without them, by that second measure alone.
  function showPreview(place, currentPrefs, { refresh = false } = {}) {
    previewRequest.current?.abort()
    const ctrl = new AbortController()
    previewRequest.current = ctrl
    setPreview(place)
    if (!userEdited.current) setLocation(`${place.city}, ${place.state}`)
    if (!refresh) setPreviewStatus('loading')
    const ranked = hasPreferences(currentPrefs)
    listChurches(
      { type: 'location', city: place.city, state: place.state },
      { limit: PREVIEW_LIMIT, sort: ranked ? 'for_you' : 'starting_point', prefs: ranked ? currentPrefs : null, signal: ctrl.signal },
    )
      .then(data => {
        setPreviewChurches(data)
        setRankedFor(ranked ? JSON.stringify(currentPrefs) : null)
        setPreviewStatus(data.length ? 'ready' : 'empty')
      })
      .catch(() => { if (!ctrl.signal.aborted && !refresh) setPreviewStatus('error') })
  }

  // Re-rank on the server once the visitor pauses on the chips; until then
  // the loaded rows re-rank locally, so the picks respond at once.
  useEffect(() => {
    if (!preview || rankedFor === (hasPreferences(prefs) ? JSON.stringify(prefs) : null)) return undefined
    const timer = setTimeout(() => showPreview(preview, prefs, { refresh: true }), 300)
    return () => clearTimeout(timer)
  }, [prefs]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const legacyParams = new URLSearchParams(window.location.search)
    if (legacyParams.has('name')) {
      navigate(`/search?${legacyParams}`, { replace: true })
      return
    }
    if (legacyParams.has('city') && legacyParams.has('state')) {
      prefetchFirstPage(legacyParams, loadPreferences())
      navigate(`/search?${legacyParams}`, { replace: true })
      return
    }

    import('../components/LandingMap')
      .then(module => setLandingMap(() => module.default))
      .catch(() => {})

    getStats()
      .then(data => setCoverage({
        withSummary: data.churches.with_summary,
        total: data.churches.total,
      }))
      .catch(() => {})

    const storedPrefs = loadPreferences()
    setPrefs(storedPrefs)

    // Someone coming back sees the city they were last looking at; a first
    // visit starts wherever the IP lookup places them.
    let stored = null
    try {
      stored = JSON.parse(localStorage.getItem('churchmap_last_search'))
    } catch {
      localStorage.removeItem('churchmap_last_search')
    }
    if (stored?.city && stored?.state) {
      showPreview({ city: stored.city, state: stored.state }, storedPrefs)
    } else {
      detectLocation()
        .then(data => showPreview({ city: data.city, state: data.state }, storedPrefs))
        .catch(() => {})
    }
  }, [navigate])

  function handleSubmit(event) {
    event.preventDefault()
    const parsed = parseLocation(location)
    if (!parsed) {
      setLocationError('Enter a city and two-letter state, like Brooklyn, NY.')
      return
    }
    goToSearch(parsed)
  }

  async function handleUseLocation() {
    setLocating(true)
    setLocationError('')
    try {
      const data = await detectLocation()
      goToSearch(data)
    } catch (err) {
      setLocationError(`${err.message}. Type a city instead.`)
      setLocating(false)
    }
  }

  function updatePrefs(next) {
    setPrefs(next)
    savePreferences(next)
  }

  const rows = previewChurches || NO_CHURCHES
  const topPicks = pickStartingPoints(rankForYou(rows, prefs), TOP_PICKS)
  const zeroMatch = preview && zeroMatchSentence(rows, prefs, {
    city: preview.city,
    limit: PREVIEW_LIMIT,
    eligible: isStartingPoint,
    ranked: hasPreferences(prefs) && rankedFor === JSON.stringify(prefs),
  })
  const forYou = hasPreferences(prefs) && !zeroMatch

  return (
    <div className="landing-page">
      <Seo
        title="ChurchMap — Know Before You Walk In"
        description="Church discovery grounded in what churches say on their own websites, with community ratings where they exist."
      />

      <nav className="landing-nav" aria-label="Main navigation">
        <a className="landing-wordmark" href="/">ChurchMap</a>
        <div>
          <a href="#methodology">How it works</a>
          <Link className="nav-search-link" to="/search">Search churches</Link>
          <AccountButton />
        </div>
      </nav>

      <main>
        <section className="map-hero" aria-labelledby="map-hero-title">
          <div className="map-hero-map">
            {LandingMap
              ? (
                <LandingMap
                  churches={previewChurches || NO_CHURCHES}
                  hoveredId={hoveredId}
                  onHover={setHoveredId}
                  overlayRef={heroCard}
                />
              )
              : <div className="map-hero-placeholder" />}
          </div>

          <div className="map-hero-card" ref={heroCard}>
            <h1 id="map-hero-title">New in town? Find a church that fits.</h1>
            <p className="map-hero-copy">
              Every church near you on one map, and what we&apos;ve learned about each
              before you visit.
            </p>
            <form className="landing-search" onSubmit={handleSubmit}>
              <label htmlFor="landing-location">Where are you looking?</label>
              <div className="landing-search-row">
                <Icon name="pin" size={20} />
                <input
                  id="landing-location"
                  value={location}
                  onChange={event => {
                    userEdited.current = true
                    setLocation(event.target.value)
                    setLocationError('')
                  }}
                  placeholder="City, ST"
                  autoComplete="address-level2"
                />
                <button type="submit">Show churches <Icon name="arrow" /></button>
              </div>
              {locationError && <p className="landing-form-error">{locationError}</p>}
            </form>
            <div className="map-hero-shortcuts">
              <button type="button" onClick={handleUseLocation} disabled={locating}>
                <Icon name="pin" size={14} /> {locating ? 'Finding your city…' : 'Use my location'}
              </button>
              {previewStatus !== 'ready' && previewStatus !== 'loading' && (
                <Link to="/search?city=Brooklyn&state=NY" onClick={() => prefetchSearch({ city: 'Brooklyn', state: 'NY' })}>or try Brooklyn, NY <Icon name="arrow" size={13} /></Link>
              )}
            </div>

            {/* Above the picks and independent of them: a re-rank below can't
                move a chip under the cursor, and nothing here submits. */}
            <FitPreferences
              alwaysOpen
              prefs={prefs}
              onChange={updatePrefs}
              languageChips={cityLanguageChips(rows, prefs.languages)}
            />

            {preview && previewStatus === 'loading' && (
              <p className="map-hero-status">Finding churches near {preview.city}, {preview.state}…</p>
            )}
            {preview && previewStatus === 'empty' && (
              <p className="map-hero-status">
                We don&apos;t have churches in {preview.city}, {preview.state} yet. Try a nearby city.
              </p>
            )}
            {preview && previewStatus === 'ready' && (
              <div className="map-hero-picks map-hero-picks-compact">
                {topPicks.length > 0 && (
                  <p className="eyebrow">Start here in {preview.city}{forYou && ' — for you'}</p>
                )}
                {topPicks.length > 0 && zeroMatch && <p className="map-hero-nomatch">{zeroMatch}</p>}
                <ul>
                  {topPicks.map(church => (
                    <li key={church.id}>
                      <a
                        href={`/church/${church.id}`}
                        className={hoveredId === church.id ? 'pick-active' : ''}
                        onMouseEnter={() => setHoveredId(church.id)}
                        onMouseLeave={() => setHoveredId(null)}
                        onFocus={() => setHoveredId(church.id)}
                        onBlur={() => setHoveredId(null)}
                      >
                        <strong>{church.name}</strong>
                        <span>
                          {church.denomination || 'Church'}
                          {hasWebsiteProfile(church) && <> · <Icon name="check" size={12} /> Website read</>}
                        </span>
                        {fitReason(church, prefs) && (
                          <span className="pick-fit">
                            <Icon name="check" size={12} />
                            {fitReason(church, prefs)}
                          </span>
                        )}
                      </a>
                    </li>
                  ))}
                </ul>
                <Link className="map-hero-all" to={searchUrl(preview)} onClick={() => prefetchSearch(preview)}>
                  See every church in {preview.city} <Icon name="arrow" />
                </Link>
              </div>
            )}
          </div>
        </section>

        {exampleChurch && (
          <section className="profile-showcase" aria-labelledby="profile-showcase-title">
            <div className="showcase-intro">
              <p className="eyebrow">A real profile, not a promise</p>
              <h2 id="profile-showcase-title">{exampleChurch.name}</h2>
              <p>
                {[exampleChurch.city, exampleChurch.state].filter(Boolean).join(', ')}
                {exampleChurch.denomination ? ` · ${exampleChurch.denomination}` : ''}
              </p>
              <a href={`/church/${exampleChurch.id}`}>See the full church profile <Icon name="arrow" /></a>
            </div>
            <AboutSection
              summary={exampleChurch.website_summary}
              tags={exampleChurch.extracted_tags}
            />
          </section>
        )}

        <section className="how-it-works" id="methodology" aria-labelledby="how-title">
          <p className="eyebrow">How ChurchMap works</p>
          <h2 id="how-title">A clearer first visit starts with better context.</h2>
          <div className="steps-grid">
            <article>
              <span>01</span>
              <h3>Search a city</h3>
              <p>Start with the churches near you, whether or not they have reviews.</p>
            </article>
            <article>
              <span>02</span>
              <h3>Read what we found</h3>
              <p>We summarize each church&apos;s own website and validate extracted claims against source snippets.</p>
            </article>
            <article>
              <span>03</span>
              <h3>Add lived experience</h3>
              <p>Where community ratings exist, they sit beside the church&apos;s own account, never disguised as the same source.</p>
            </article>
          </div>
        </section>

        <section className="coverage-band" aria-label="ChurchMap coverage">
          <p>
            We&apos;ve read <strong>{coverage.withSummary.toLocaleString()}</strong> church websites
            so far, out of <strong>{coverage.total.toLocaleString()}</strong> churches we know about.
            We&apos;re adding more every day.
          </p>
          <a href="/status">See coverage and pipeline status <Icon name="arrow" /></a>
        </section>

        <section className="dimensions-invitation" id="about" aria-labelledby="dimensions-title">
          <div>
            <p className="eyebrow">The part only people can tell us</p>
            <h2 id="dimensions-title">A website can describe a church. A community can describe the experience.</h2>
            <p>
              ChurchMap reviews ask about six useful dimensions instead of one generic score.
              Most churches are still waiting for their first review. Your experience can make the next visit less uncertain.
            </p>
            <Link className="primary-link" to="/search">Find a church to review <Icon name="arrow" /></Link>
          </div>
          <div className="dimension-demo" aria-label="Example of the six community rating dimensions">
            <p>Example ratings</p>
            <DimensionBars dimensions={DEMO_DIMENSIONS} />
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div>
          <a className="landing-wordmark" href="/">ChurchMap</a>
          <p>Church data from IRS 990 records, OpenStreetMap, Google Places, and church websites.</p>
        </div>
        <div className="footer-links">
          <a href="/#about">About</a>
          <a href="/#methodology">Methodology</a>
          <a href="/status">Status</a>
          <a href="https://github.com/zhou100/church_map/issues">Contact</a>
          <a href="/privacy">Privacy</a>
        </div>
      </footer>
    </div>
  )
}
