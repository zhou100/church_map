import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, Marker } from 'react-leaflet'
import DimensionBars from './DimensionBars'
import ReviewForm from './ReviewForm'
import ChurchCard from './ChurchCard'
import AboutSection from './AboutSection'
import Icon from './Icon'
import { churchMarkerIcon } from './mapMarker'
import { enrichChurch, getChurch, getReviews, getSimilarChurches } from '../api/client'

function Stars({ rating }) {
  if (rating == null) return <span className="stars">—</span>
  const full = Math.round(rating)
  return <span className="stars">{'★'.repeat(full)}{'☆'.repeat(5 - full)}</span>
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

export default function ChurchDetailPanel({ churchId, onBack, onSelect }) {
  const [church, setChurch] = useState(null)
  const [reviewData, setReviewData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [reviewCount, setReviewCount] = useState(0)
  const [similarChurches, setSimilarChurches] = useState(null)
  const [enrichData, setEnrichData] = useState(null)
  const [photoIdx, setPhotoIdx] = useState(0)
  const [churchError, setChurchError] = useState(null)
  const [reviewsError, setReviewsError] = useState(null)

  async function fetchChurch() {
    try {
      setChurch(await getChurch(churchId))
    } catch (e) { setChurchError(e.status === 404 ? 'Church not found' : e.message) }
  }

  async function fetchSimilar() {
    try {
      setSimilarChurches(await getSimilarChurches(churchId))
    } catch {
      // Similar churches are supplementary and should not block the panel.
    }
  }

  async function fetchEnrich() {
    try {
      const data = await enrichChurch(churchId)
      if (data.photos?.length || data.hours?.length) setEnrichData(data)
    } catch {
      // Enrichment is best-effort and should not block the church profile.
    }
  }

  async function fetchReviews() {
    try {
      const data = await getReviews(churchId)
      setReviewData(data)
      setReviewCount(data.reviews.length)
    } catch (e) { setReviewsError(e.message) }
  }

  useEffect(() => {
    setLoading(true)
    setEnrichData(null)
    setPhotoIdx(0)
    setChurch(null)
    setReviewData(null)
    setSimilarChurches(null)
    setChurchError(null)
    setReviewsError(null)
    Promise.allSettled([fetchChurch(), fetchReviews(), fetchSimilar()])
      .then(() => { setLoading(false); fetchEnrich() })
  }, [churchId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="loading" style={{ padding: '2rem 0' }}>Loading…</div>

  return (
    <div className="detail-panel">
      <button className="back-link" onClick={onBack}>← Back to results</button>

      {churchError
        ? <p className="error-msg">{churchError}</p>
        : church && (
          <>
            {church.latitude && church.longitude && (
              <div className="panel-map">
                <MapContainer
                  center={[church.latitude, church.longitude]}
                  zoom={15}
                  style={{ height: '180px', width: '100%' }}
                  zoomControl={false}
                  dragging={false}
                  scrollWheelZoom={false}
                  doubleClickZoom={false}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <Marker position={[church.latitude, church.longitude]} icon={churchMarkerIcon()} />
                </MapContainer>
              </div>
            )}

            <div className="detail-header" style={{ marginTop: '0.75rem' }}>
              <h1>{church.name}</h1>
              {church.denomination && <p className="denom">{church.denomination}</p>}
              {(church.address || church.city) && (
                <p className="address">
                  {[church.address, church.city, church.state].filter(Boolean).join(', ')}
                </p>
              )}
              {church.service_times && (
                <p className="service-times"><Icon name="clock" size={15} /> {church.service_times}</p>
              )}
              {enrichData?.editorial && (
                <p className="church-editorial">{enrichData.editorial}</p>
              )}

              <div className={`meta${reviewCount ? '' : ' meta-empty'}`}>
                {reviewCount > 0 ? (
                  <>
                    <Stars rating={church.avg_rating} />
                    <span className="avg-rating">
                      {church.avg_rating != null ? church.avg_rating.toFixed(1) : 'No rating'}
                    </span>
                    <span className="review-count">
                      (<span className="review-count-badge" key={reviewCount}>{reviewCount}</span>
                      {' '}{reviewCount === 1 ? 'review' : 'reviews'})
                    </span>
                  </>
                ) : <span className="profile-status">No community reviews yet</span>}
                {enrichData?.rating != null && (
                  <span className="google-rating">
                    <span className="stars">★</span> {enrichData.rating} Google ({enrichData.review_count?.toLocaleString()})
                  </span>
                )}
                {enrichData?.wheelchair && <span className="tag"><Icon name="accessible" size={14} /> Accessible</span>}
                {church.tags?.map(t => <span key={t} className="tag">{t}</span>)}
              </div>

              {(church.website || church.phone || church.latitude) && (
                <div className="detail-info-bar">
                  {church.website && (
                    <a href={church.website} target="_blank" rel="noopener noreferrer" className="info-link">
                      <Icon name="globe" /> Website
                    </a>
                  )}
                  {church.phone && (
                    <a href={`tel:${church.phone}`} className="info-link">
                      <Icon name="phone" /> {church.phone}
                    </a>
                  )}
                  {church.latitude && church.longitude && (
                    <a
                      href={`https://www.google.com/maps/search/?api=1&query=${church.latitude},${church.longitude}`}
                      target="_blank" rel="noopener noreferrer" className="info-link"
                    >
                      <Icon name="pin" /> Directions
                    </a>
                  )}
                </div>
              )}

              <AboutSection summary={church.website_summary} tags={church.extracted_tags} />

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
              <div className="detail-photos" style={{ marginTop: '1rem' }}>
                <img src={enrichData.photos[photoIdx]} alt={church.name} className="detail-photo-main" />
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
          {enrichData.reviews.map((r, i) => (
            <div key={i} className="review-card">
              <div className="review-stars">{'★'.repeat(r.rating || 0)}{'☆'.repeat(5 - (r.rating || 0))}</div>
              {r.text && <p className="review-comment">{r.text}</p>}
              <div className="review-date">{r.author}{r.time ? ` · ${r.time}` : ''}</div>
            </div>
          ))}
        </>
      )}

      <h2 className="section-title">Dimension ratings</h2>
      {reviewsError
        ? <p className="error-msg">{reviewsError}</p>
        : <DimensionBars dimensions={reviewData?.dimensions} animKey={reviewCount} />
      }

      <h2 className="section-title">Reviews ({reviewCount})</h2>
      {!reviewsError && (reviewData?.reviews.length === 0
        ? <p style={{ color: 'var(--text-3)', fontSize: '0.88rem' }}>No reviews yet — be the first!</p>
        : reviewData?.reviews.map(r => <ReviewCard key={r.id} review={r} />)
      )}

      {!churchError && church && similarChurches?.length > 0 && (
        <>
          <h2 className="section-title">Similar churches</h2>
          <div className="similar-panel-list">
            {similarChurches.map(c => (
              <div key={c.id} className="card-wrapper" onClick={() => onSelect(c.id)} style={{ cursor: 'pointer' }}>
                <ChurchCard church={c} />
              </div>
            ))}
          </div>
        </>
      )}

      {!churchError && church && (
        <>
          <h2 className="section-title">Leave a review</h2>
          <ReviewForm churchId={Number(churchId)} onSubmitted={async () => {
            await Promise.allSettled([fetchChurch(), fetchReviews()])
          }} />
        </>
      )}
    </div>
  )
}
