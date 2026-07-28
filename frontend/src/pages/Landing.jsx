import { useEffect, useRef, useState } from 'react'
import AboutSection from '../components/AboutSection'
import DimensionBars from '../components/DimensionBars'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { detectLocation, getStats } from '../api/client'

const AUDITED_COVERAGE = { withSummary: 4332, total: 133939 }
const EXAMPLE_PROFILE = {
  summary: 'A multi-branch Brooklyn church with a long history, focused on community outreach, practical care, and global evangelism.',
  tags: {
    vibe_tags: ['community-focused', 'mission-driven', 'spirit-filled', 'intergenerational'],
    pull_quote: 'Gospel Tabernacle embrace the Pentecostal born again experience, and is committed to do all we can to help improve the quality of life for our residents and congregants.',
    theology_summary: 'They affirm the Bible as the word of God, the deity of Jesus Christ, regeneration by the Holy Spirit, divine healing, and the baptism of the Holy Spirit.',
    service_languages: [],
    programs: ['Food pantry', 'Family counseling', 'Youth activities', 'Elderly programs'],
  },
}
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

export default function Landing() {
  const [location, setLocation] = useState('')
  const [locationError, setLocationError] = useState('')
  const [lastSearch, setLastSearch] = useState(null)
  const [coverage, setCoverage] = useState(AUDITED_COVERAGE)
  const userEdited = useRef(false)

  useEffect(() => {
    const legacyParams = new URLSearchParams(window.location.search)
    if (legacyParams.has('name') || (legacyParams.has('city') && legacyParams.has('state'))) {
      window.location.replace(`/search?${legacyParams}`)
      return
    }

    try {
      const stored = JSON.parse(localStorage.getItem('churchmap_last_search'))
      if (stored?.city && stored?.state) setLastSearch(stored)
    } catch {
      localStorage.removeItem('churchmap_last_search')
    }

    getStats()
      .then(data => setCoverage({
        withSummary: data.churches.with_summary,
        total: data.churches.total,
      }))
      .catch(() => {})

    detectLocation()
      .then(data => {
        if (!userEdited.current) setLocation(`${data.city}, ${data.state}`)
      })
      .catch(() => {})
  }, [])

  function handleSubmit(event) {
    event.preventDefault()
    const parsed = parseLocation(location)
    if (!parsed) {
      setLocationError('Enter a city and two-letter state, like Brooklyn, NY.')
      return
    }
    window.location.assign(`/search?city=${encodeURIComponent(parsed.city)}&state=${encodeURIComponent(parsed.state)}`)
  }

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
          <a className="nav-search-link" href="/search">Search churches</a>
        </div>
      </nav>

      <main>
        <section className="landing-hero">
          <p className="eyebrow">Church discovery, with the homework done</p>
          <h1>Know what a Sunday is actually like — before you walk in.</h1>
          <p className="hero-copy">
            We read what churches say about themselves, so you don&apos;t have to click
            through twelve websites.
          </p>
          {lastSearch && (
            <a className="continue-link" href={`/search?city=${encodeURIComponent(lastSearch.city)}&state=${encodeURIComponent(lastSearch.state)}`}>
              Continue in {lastSearch.city} <Icon name="arrow" />
            </a>
          )}
          <form className="landing-search" onSubmit={handleSubmit}>
            <label htmlFor="landing-location">Find churches in</label>
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
                placeholder="Brooklyn, NY"
                autoComplete="address-level2"
              />
              <button type="submit">Explore churches <Icon name="arrow" /></button>
            </div>
            {locationError && <p className="landing-form-error">{locationError}</p>}
          </form>
          <a className="browse-city-link" href="/search?city=Brooklyn&state=NY">
            Or browse a city we&apos;ve read thoroughly <Icon name="arrow" />
          </a>
        </section>

        <section className="profile-showcase" aria-labelledby="profile-showcase-title">
          <div className="showcase-intro">
            <p className="eyebrow">A real profile, not a promise</p>
            <h2 id="profile-showcase-title">The Gospel Tabernacle Church</h2>
            <p>Brooklyn, New York · Pentecostal</p>
            <a href="/church/113184">See the full church profile <Icon name="arrow" /></a>
          </div>
          <AboutSection summary={EXAMPLE_PROFILE.summary} tags={EXAMPLE_PROFILE.tags} />
        </section>

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
            <a className="primary-link" href="/search">Find a church to review <Icon name="arrow" /></a>
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
