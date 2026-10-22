import { useState } from 'react'
import GoogleSignInButton from './GoogleSignInButton'
import StarInput from './StarInput'
import { useAuth } from '../context/AuthContext'
import { submitReview } from '../api/client'

const DIM_FIELDS = [
  { key: 'worship_energy',       label: 'Worship energy' },
  { key: 'community_warmth',     label: 'Community warmth' },
  { key: 'sermon_depth',         label: 'Sermon depth' },
  { key: 'childrens_programs',   label: "Children's programs" },
  { key: 'theological_openness', label: 'Theological stance' },
  { key: 'facilities',           label: 'Facilities' },
]

const REVIEW_BUTTON = {
  type: 'standard',
  theme: 'outline',
  size: 'large',
  text: 'signin_with',
  shape: 'rectangular',
  logo_alignment: 'left',
}

export default function ReviewForm({ churchId, onSubmitted }) {
  const { user, token, handleGoogleCredential, logout } = useAuth()
  const [rating, setRating] = useState(null)
  const [comment, setComment] = useState('')
  const [dims, setDims] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState(null)

  function setDim(key, val) {
    setDims(prev => ({ ...prev, [key]: val }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!rating) { setError('Please select an overall rating.'); return }
    if (!token) { setError('Please sign in first.'); return }
    setSubmitting(true)
    setError(null)
    try {
      await submitReview({
        church_id: churchId,
        rating,
        comment: comment.trim() || null,
        ...Object.fromEntries(Object.entries(dims).filter(([, v]) => v != null)),
      }, token)
      setSuccess(true)
      setRating(null)
      setComment('')
      setDims({})
      await onSubmitted()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <div className="review-form">
        <p className="submit-success">✓ Review submitted! Thank you, {user?.name}.</p>
        <button type="button" className="submit-btn" onClick={() => setSuccess(false)} style={{ marginTop: '0.5rem' }}>
          Write another review
        </button>
      </div>
    )
  }

  // Not signed in — show sign-in gate
  if (!user) {
    return (
      <div className="review-form review-signin-gate">
        <p className="signin-prompt">Sign in to share your experience with this church.</p>
        <GoogleSignInButton onCredential={handleGoogleCredential} options={REVIEW_BUTTON} />
      </div>
    )
  }

  // Signed in — show form
  return (
    <form className="review-form" onSubmit={handleSubmit}>
      <div className="reviewer-bar">
        {user.avatar_url && (
          <img src={user.avatar_url} alt={user.name} className="reviewer-avatar" referrerPolicy="no-referrer" />
        )}
        <span className="reviewer-name">Reviewing as <strong>{user.name}</strong></span>
        <button type="button" className="signout-btn" onClick={logout}>Sign out</button>
      </div>

      <div className="form-row">
        <label>Overall rating <span style={{ color: '#e53e3e' }}>*</span></label>
        <StarInput value={rating} onChange={setRating} name="overall" />
      </div>

      <div className="form-row">
        <label>Comment <span className="optional">(optional)</span></label>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="What was your experience like?"
          maxLength={1000}
        />
      </div>

      <div className="form-row">
        <label>Dimension ratings <span className="optional">(all optional)</span></label>
        <div className="dim-inputs">
          {DIM_FIELDS.map(({ key, label }) => (
            <div key={key}>
              <label style={{ fontSize: '0.78rem', marginBottom: '0.2rem', display: 'block', color: '#666' }}>
                {label}
              </label>
              <StarInput value={dims[key] ?? null} onChange={v => setDim(key, v)} name={label} />
            </div>
          ))}
        </div>
      </div>

      {error && <p className="submit-error">{error}</p>}

      <button type="submit" className="submit-btn" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Submit review'}
      </button>
    </form>
  )
}
