import { Link } from 'react-router-dom'

const DENOM_COLORS = {
  baptist:     '#7C3AED',
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

function haversine(lat1, lon1, lat2, lon2) {
  const R = 3958.8
  const dLat = (lat2 - lat1) * Math.PI / 180
  const dLon = (lon2 - lon1) * Math.PI / 180
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function Distance({ church, userLat, userLon }) {
  if (userLat == null || !church.latitude || !church.longitude) return null
  const miles = haversine(userLat, userLon, church.latitude, church.longitude)
  const label = miles < 0.1 ? 'nearby'
    : miles < 10 ? `${miles.toFixed(1)} mi`
    : `${Math.round(miles)} mi`
  return <span className="card-distance">📍 {label}</span>
}

function CardBody({ church, userLat, userLon }) {
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

  return (
    <div className="card-body">
      <h3>{church.name}</h3>
      <p className="card-denom">{church.denomination || 'Church'}</p>
      <div className="card-meta">
        <Stars rating={church.avg_rating} />
        <span className="review-count">
          {church.avg_rating != null ? church.avg_rating.toFixed(1) : '—'}
          {' '}({church.review_count} {church.review_count === 1 ? 'review' : 'reviews'})
        </span>
        <Distance church={church} userLat={userLat} userLon={userLon} />
      </div>
      <div className="tag-list">
        {church.language && church.language !== 'English' && (
          <span className="tag tag-lang">{church.language}</span>
        )}
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

export default function ChurchCard({ church, userLat, userLon, onSelect }) {
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
        onKeyDown={e => e.key === 'Enter' && onSelect(church.id)}
      >
        <CardBody church={church} userLat={userLat} userLon={userLon} />
      </div>
    )
  }

  return (
    <Link to={`/church/${church.id}`} className="church-card" style={sharedStyle}>
      <CardBody church={church} userLat={userLat} userLon={userLon} />
    </Link>
  )
}
