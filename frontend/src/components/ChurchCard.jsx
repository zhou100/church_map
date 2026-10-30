import { memo } from 'react'
import { Link } from 'react-router-dom'
import Icon from './Icon'
import { languageSignals } from '../churchProfile'

const DENOM_COLORS = {
  baptist:     '#9A3412',
  catholic:    '#1D4ED8',
  episcopal:   '#B45309',
  anglican:    '#B45309',
  methodist:   '#0891B2',
}

function denomAccentColor(denomination) {
  const d = (denomination || '').toLowerCase()
  for (const [key, color] of Object.entries(DENOM_COLORS)) {
    if (d.includes(key)) return color
  }
  return '#8B5E3C' // sienna default
}

function Stars({ rating }) {
  if (rating == null) return <span className="stars">—</span>
  const full = Math.round(rating)
  return <span className="stars">{'★'.repeat(full)}{'☆'.repeat(5 - full)}</span>
}

// Straight-line miles from the search's stated origin, measured by the API
// (`distance_miles`). A listing without coordinates says so instead of
// silently dropping out of a distance-ordered list.
function Distance({ church }) {
  const miles = church.distance_miles
  if (miles == null) return <span className="card-distance card-distance-unknown">Distance unknown</span>
  const label = miles < 0.1 ? 'nearby'
    : miles < 10 ? `${miles.toFixed(1)} mi`
    : `${Math.round(miles)} mi`
  return <span className="card-distance"><Icon name="pin" size={13} /> {label}</span>
}

function CardBody({ church, showDistance, showLocation, fitReason }) {
  const extracted = church.extracted_tags || {}
  const extractedValues = Object.values(extracted)
  const hasWebsiteInsights = Boolean(
    church.website_summary ||
    extractedValues.some(value => Array.isArray(value) ? value.length : value)
  )
  const websiteTags = [...new Set([
    ...(Array.isArray(extracted.service_languages)
      ? extracted.service_languages.filter(language => language !== 'English')
      : []),
    ...(Array.isArray(extracted.vibe_tags) ? extracted.vibe_tags : []),
  ])].slice(0, 2)
  // Website-read languages already sit in the "From their website" block;
  // these are the verified ones. Name-derived language guesses stay out.
  const languageTags = languageSignals(church)
    .filter(signal => signal.source !== 'website' && signal.language.toLowerCase() !== 'english')
    .map(signal => signal.language)

  return (
    <div className="card-body">
      <h3>{church.name}</h3>
      <p className="card-denom">{church.denomination || 'Church'}</p>
      {showLocation && (church.city || church.state) && (
        <p className="card-location">
          {[church.city, church.state].filter(Boolean).join(', ')}
        </p>
      )}
      <div className={`card-meta${church.review_count ? '' : ' card-meta-empty'}`}>
        {church.review_count ? (
          <>
            <Stars rating={church.avg_rating} />
            <span className="review-count">
              {church.avg_rating != null ? church.avg_rating.toFixed(1) : 'No rating'}
              {' '}({church.review_count} {church.review_count === 1 ? 'review' : 'reviews'})
            </span>
          </>
        ) : (
          <span className="profile-status">
            {hasWebsiteInsights ? 'Website profile available' : 'Website not read yet'}
          </span>
        )}
        {showDistance && <Distance church={church} />}
      </div>
      {fitReason && (
        <p className="card-fit">
          <Icon name="check" size={12} />
          {fitReason}
        </p>
      )}
      <div className="tag-list">
        {languageTags.map(language => (
          <span key={language} className="tag tag-lang">{language}</span>
        ))}
        {church.cultural_background && (
          <span className="tag tag-culture">{church.cultural_background}</span>
        )}
        {church.tags?.map(t => <span key={t} className="tag">{t}</span>)}
      </div>
      {hasWebsiteInsights && (
        <div className="website-card-insights">
          <span className="website-card-source">From their website</span>
          {websiteTags.map(tag => (
            <span key={tag} className="website-card-chip">{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function ChurchCard({ church, showDistance = false, showLocation = false, fitReason = '', onSelect }) {
  const accentColor = denomAccentColor(church.denomination)
  const sharedStyle = { borderLeft: `5px solid ${accentColor}` }

  if (onSelect) {
    return (
      <div
        className="church-card"
        style={sharedStyle}
        onClick={() => onSelect(church.id)}
        role="button"
        tabIndex={0}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(church.id) }
        }}
      >
        <CardBody church={church} showDistance={showDistance} showLocation={showLocation} fitReason={fitReason} />
      </div>
    )
  }

  return (
    <Link to={`/church/${church.id}`} className="church-card" style={sharedStyle}>
      <CardBody church={church} showDistance={showDistance} showLocation={showLocation} fitReason={fitReason} />
    </Link>
  )
}

export default memo(ChurchCard)
