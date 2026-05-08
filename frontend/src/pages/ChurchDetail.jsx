import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, Marker } from 'react-leaflet'
import DimensionBars from '../components/DimensionBars'
import ReviewForm from '../components/ReviewForm'
import ChurchCard from '../components/ChurchCard'

const API = import.meta.env.VITE_API_URL || ''

function Stars({ rating }) {
  if (rating == null) return <span className="stars">—</span>
  const full = Math.round(rating)
  return <span className="stars">{'★'.repeat(full)}{'☆'.repeat(5 - full)}</span>
}

const WORSHIP_STYLE_LABEL = {
  'liturgical': 'Liturgical',
  'traditional-hymns': 'Traditional hymns',
  'blended': 'Blended worship',
  'contemporary': 'Contemporary',
  'charismatic': 'Charismatic',
}

function AboutSection({ summary, tags }) {
  const vibe = tags?.vibe_tags || []
  const programs = tags?.programs || []
  const langs = tags?.service_languages || []
  const theology = tags?.theology_summary
  const worshipStyle = tags?.worship_style
  const worshipDetail = tags?.worship_style_detail
  const pullQuote = tags?.pull_quote
  const faith = tags?.statement_of_faith || []

  const hasAnything = summary || theology || worshipStyle || worshipDetail
    || pullQuote || faith.length || vibe.length || programs.length || langs.length
  if (!hasAnything) return null

  return (
    <div className="about-section">
      {summary && <p className="about-summary">{summary}</p>}

      {pullQuote && (
        <blockquote className="about-pullquote">{pullQuote}</blockquote>
      )}

      {vibe.length > 0 && (
        <div className="about-tags">
          {vibe.map(t => <span key={t} className="vibe-chip">{t}</span>)}
        </div>
      )}

      {(theology || worshipStyle || worshipDetail) && (
        <div className="about-blocks">
          {theology && (
            <div className="about-block">
              <h4>What they teach</h4>
              <p>{theology}</p>
            </div>
          )}
          {(worshipStyle || worshipDetail) && (
            <div className="about-block">
              <h4>Worship style</h4>
              {worshipStyle && (
                <p className="about-block-lead">
                  {WORSHIP_STYLE_LABEL[worshipStyle] || worshipStyle}
                </p>
              )}
              {worshipDetail && <p>{worshipDetail}</p>}
            </div>
          )}
        </div>
      )}

      {faith.length > 0 && (
        <div className="about-block">
          <h4>Statement of faith</h4>
          <ul className="about-faith-list">
            {faith.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}

      {(programs.length > 0 || langs.length > 0) && (
        <dl className="about-meta">
          {langs.length > 0 && (
            <>
              <dt>Languages</dt>
              <dd>{langs.join(', ')}</dd>
            </>
          )}
          {programs.length > 0 && (
            <>
              <dt>Programs</dt>
              <dd>{programs.join(' · ')}</dd>
            </>
          )}
        </dl>
      )}
    </div>
  )
}

function ReviewCard({ review }) {
  const full = Math.round(review.rating || 0)
  return (
    <div className="review-card">
      <div className="review-stars">{'★'.repeat(full)}{'☆'.repeat(5 - full)}</div>
      {review.comment && <p className="review-comment">{review.comment}</p>}
      <div className="review-date">
        {review.created_at ? new Date(review.created_at).toLocaleDateString() : ''}
      </div>
    </div>
  )
}

export default function ChurchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [church, setChurch] = useState(null)
  const [reviewData, setReviewData] = useState(null)
  const [churchError, setChurchError] = useState(null)
  const [reviewsError, setReviewsError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [reviewCount, setReviewCount] = useState(0)
  const [similarChurches, setSimilarChurches] = useState(null)
  const [similarError, setSimilarError] = useState(null)
  const [enrichData, setEnrichData] = useState(null)
  const [photoIdx, setPhotoIdx] = useState(0)

  async function fetchChurch() {
    try {
      const res = await fetch(`${API}/api/churches/${id}`)
      if (!res.ok) throw new Error(res.status === 404 ? 'Church not found' : 'Failed to load')
      setChurch(await res.json())
    } catch (e) {
      setChurchError(e.message)
    }
  }

  async function fetchSimilar() {
    try {
      const res = await fetch(`${API}/api/churches/${id}/similar`)
      if (!res.ok) throw new Error('Failed to load')
      setSimilarChurches(await res.json())
    } catch (e) {
      setSimilarError(e.message)
    }
  }

  async function fetchEnrich() {
    try {
      const res = await fetch(`${API}/api/churches/${id}/enrich`, { method: 'POST' })
      if (!res.ok) return
      const data = await res.json()
      if (data.photos?.length || data.hours?.length) setEnrichData(data)
    } catch {
      // enrichment is best-effort, never blocks the page
    }
  }

  async function fetchReviews() {
    try {
      const res = await fetch(`${API}/api/reviews/${id}`)
      if (!res.ok) throw new Error('Failed to load reviews')
      const data = await res.json()
      setReviewData(data)
      setReviewCount(data.reviews.length)
    } catch (e) {
      setReviewsError(e.message)
    }
  }

  useEffect(() => {
    setLoading(true)
    setEnrichData(null)
    setPhotoIdx(0)
    Promise.allSettled([fetchChurch(), fetchReviews(), fetchSimilar()]).then(() => {
      setLoading(false)
      fetchEnrich()
    })
  }, [id])

  async function handleReviewSubmitted() {
    await Promise.allSettled([fetchChurch(), fetchReviews()])
  }

  if (loading) return <div className="loading">Loading…</div>

  return (
    <div className="detail-page">
      <button className="back-link" onClick={() => navigate(-1)}>← Back to search</button>

      {churchError
        ? <p className="error-msg">{churchError}</p>
        : church && (
          <>
            {church.latitude && church.longitude && (
              <div className="detail-map">
                <MapContainer
                  center={[church.latitude, church.longitude]}
                  zoom={15}
                  style={{ height: '220px', width: '100%' }}
                  zoomControl={false}
                  dragging={false}
                  scrollWheelZoom={false}
                  doubleClickZoom={false}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <Marker position={[church.latitude, church.longitude]} />
                </MapContainer>
              </div>
            )}

            <div className="detail-header">
              <h1>{church.name}</h1>
              {church.denomination && <p className="denom">{church.denomination}</p>}
              {(church.address || church.city) && (
                <p className="address">
                  {[church.address, church.city, church.state].filter(Boolean).join(', ')}
                </p>
              )}
              {church.service_times && (
                <p className="service-times">🕐 {church.service_times}</p>
              )}
              {enrichData?.editorial && (
                <p className="church-editorial">{enrichData.editorial}</p>
              )}

              <div className="meta">
                <Stars rating={church.avg_rating} />
                <span className="avg-rating">
                  {church.avg_rating != null ? church.avg_rating.toFixed(1) : '—'}
                </span>
                <span className="review-count">
                  (<span className="review-count-badge" key={reviewCount}>{reviewCount}</span>
                  {' '}{reviewCount === 1 ? 'review' : 'reviews'})
                </span>
                {enrichData?.rating != null && (
                  <span className="google-rating">
                    ⭐ {enrichData.rating} Google ({enrichData.review_count?.toLocaleString()})
                  </span>
                )}
                {enrichData?.wheelchair && (
                  <span className="tag">♿ Accessible</span>
                )}
                {church.tags?.map(t => <span key={t} className="tag">{t}</span>)}
              </div>

              {(church.website || church.phone || church.latitude) && (
                <div className="detail-info-bar">
                  {church.website && (
                    <a href={church.website} target="_blank" rel="noopener noreferrer" className="info-link">
                      🌐 Website
                    </a>
                  )}
                  {church.phone && (
                    <a href={`tel:${church.phone}`} className="info-link">
                      📞 {church.phone}
                    </a>
                  )}
                  {church.latitude && church.longitude && (
                    <a
                      href={`https://www.google.com/maps/search/?api=1&query=${church.latitude},${church.longitude}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="info-link"
                    >
                      📍 Get directions
                    </a>
                  )}
                </div>
              )}

              {(church.website_summary || church.extracted_tags) && (
                <AboutSection summary={church.website_summary} tags={church.extracted_tags} />
              )}

              {enrichData?.hours?.length > 0 && (
                <div className="opening-hours">
                  <h3 className="hours-title">Opening hours</h3>
                  <ul className="hours-list">
                    {enrichData.hours.map((line, i) => <li key={i}>{line}</li>)}
                  </ul>
                </div>
              )}
            </div>

            {enrichData?.photos?.length > 0 && (
              <div className="detail-photos">
                <img
                  src={enrichData.photos[photoIdx]}
                  alt={church.name}
                  className="detail-photo-main"
                />
                {enrichData.photos.length > 1 && (
                  <div className="photo-dots">
                    {enrichData.photos.map((_, i) => (
                      <button
                        key={i}
                        className={`photo-dot${i === photoIdx ? ' active' : ''}`}
                        onClick={() => setPhotoIdx(i)}
                        aria-label={`Photo ${i + 1}`}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )
      }

      {enrichData?.reviews?.length > 0 && (
        <>
          <h2 className="section-title">Google reviews</h2>
          <div className="google-reviews-list">
            {enrichData.reviews.map((r, i) => (
              <div key={i} className="review-card">
                <div className="review-stars">{'★'.repeat(r.rating || 0)}{'☆'.repeat(5 - (r.rating || 0))}</div>
                {r.text && <p className="review-comment">{r.text}</p>}
                <div className="review-date">{r.author}{r.time ? ` · ${r.time}` : ''}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <h2 className="section-title">Dimension ratings</h2>
      {reviewsError
        ? <p className="error-msg">{reviewsError}</p>
        : (
          <DimensionBars
            dimensions={reviewData?.dimensions}
            animKey={reviewCount}
          />
        )
      }

      <h2 className="section-title">
        Reviews ({reviewCount})
      </h2>
      {reviewsError
        ? null
        : reviewData?.reviews.length === 0
          ? <p className="empty-state">No reviews yet — be the first!</p>
          : reviewData?.reviews.map(r => <ReviewCard key={r.id} review={r} />)
      }

      {!churchError && church && similarChurches !== null && similarChurches.length > 0 && (
        <>
          <h2 className="section-title">Similar churches</h2>
          {similarError
            ? <p className="error-msg">{similarError}</p>
            : (
              <div className="similar-churches-grid">
                {similarChurches.map(c => <ChurchCard key={c.id} church={c} />)}
              </div>
            )
          }
        </>
      )}

      {!churchError && church && (
        <>
          <h2 className="section-title">Leave a review</h2>
          <ReviewForm churchId={Number(id)} onSubmitted={handleReviewSubmitted} />
        </>
      )}
    </div>
  )
}
