import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, Marker } from 'react-leaflet'
import DimensionBars from '../components/DimensionBars'
import ReviewForm from '../components/ReviewForm'
import ChurchCard from '../components/ChurchCard'
import AboutSection from '../components/AboutSection'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { churchMarkerIcon } from '../components/mapMarker'
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
      setChurch(await getChurch(id))
    } catch (e) {
      setChurchError(e.status === 404 ? 'Church not found' : e.message)
    }
  }

  async function fetchSimilar() {
    try {
      setSimilarChurches(await getSimilarChurches(id))
    } catch (e) {
      setSimilarError(e.message)
    }
  }

  async function fetchEnrich() {
    try {
      const data = await enrichChurch(id)
      if (data.photos?.length || data.hours?.length) setEnrichData(data)
    } catch {
      // enrichment is best-effort, never blocks the page
    }
  }

  async function fetchReviews() {
    try {
      const data = await getReviews(id)
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
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleReviewSubmitted() {
    await Promise.allSettled([fetchChurch(), fetchReviews()])
  }

  if (loading) {
    return (
      <>
        <Seo title="Loading church profile" description="Loading a ChurchMap church profile." canonicalPath={`/church/${id}`} />
        <div className="loading">Loading…</div>
      </>
    )
  }

  const place = church ? [church.city, church.state].filter(Boolean).join(', ') : ''
  const description = church?.website_summary
    || (church ? `Church profile for ${church.name}${place ? ` in ${place}` : ''}, with website details and community ratings where available.` : 'Church profile on ChurchMap.')
  const jsonLd = church ? {
    '@context': 'https://schema.org',
    '@type': 'Church',
    name: church.name,
    url: `https://churchmap.vercel.app/church/${church.id}`,
    description,
    telephone: church.phone || undefined,
    sameAs: church.website ? [church.website] : undefined,
    address: (church.address || church.city) ? {
      '@type': 'PostalAddress',
      streetAddress: church.address || undefined,
      addressLocality: church.city || undefined,
      addressRegion: church.state || undefined,
    } : undefined,
    geo: (church.latitude && church.longitude) ? {
      '@type': 'GeoCoordinates',
      latitude: church.latitude,
      longitude: church.longitude,
    } : undefined,
  } : null

  return (
    <div className="detail-page">
      <Seo
        title={church ? `${church.name}${place ? ` — ${place}` : ''}` : 'Church not found'}
        description={description}
        canonicalPath={`/church/${id}`}
        type="place"
        jsonLd={jsonLd}
      />
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
                  <Marker position={[church.latitude, church.longitude]} icon={churchMarkerIcon()} />
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
                {enrichData?.wheelchair && (
                  <span className="tag"><Icon name="accessible" size={14} /> Accessible</span>
                )}
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
                      target="_blank"
                      rel="noopener noreferrer"
                      className="info-link"
                    >
                      <Icon name="pin" /> Get directions
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
