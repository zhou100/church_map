const API_BASE = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(body?.detail || options.errorMessage || 'Request failed', response.status)
  }
  return response.json()
}

export function listChurches(search, { limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (search.type === 'name') {
    params.set('name', search.name)
  } else {
    params.set('city', search.city)
    params.set('state', search.state)
  }
  return request(`/api/churches?${params}`, { errorMessage: 'Failed to fetch churches' })
}

export function getChurch(churchId) {
  return request(`/api/churches/${churchId}`, { errorMessage: 'Failed to load church' })
}

export function getSimilarChurches(churchId) {
  return request(`/api/churches/${churchId}/similar`, { errorMessage: 'Failed to load similar churches' })
}

export function enrichChurch(churchId) {
  return request(`/api/churches/${churchId}/enrich`, {
    method: 'POST',
    errorMessage: 'Failed to load church details',
  })
}

export function getReviews(churchId) {
  return request(`/api/reviews/${churchId}`, { errorMessage: 'Failed to load reviews' })
}

export function submitReview(review, token) {
  return request('/api/reviews', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(review),
    errorMessage: 'Submission failed',
  })
}

export function verifyGoogleCredential(token) {
  return request('/api/auth/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
    errorMessage: 'Auth failed',
  })
}

export function getStats() {
  return request('/api/stats', { errorMessage: 'Coverage is temporarily unavailable' })
}

export async function detectLocation() {
  const response = await fetch('https://ipapi.co/json/')
  if (!response.ok) throw new ApiError('Could not detect your location', response.status)
  const data = await response.json()
  if (!data.city || !data.region_code || data.country_code !== 'US') {
    throw new ApiError('Location detection is only available in the US', 422)
  }
  return {
    city: data.city,
    state: data.region_code,
    lat: data.latitude || null,
    lon: data.longitude || null,
  }
}
