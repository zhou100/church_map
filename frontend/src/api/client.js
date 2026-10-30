// Same-origin `/api` when VITE_API_URL is unset or blank. Production relies on
// the Vercel rewrite to the Render API. Set VITE_API_URL to call another host
// (local dev against uvicorn).
function resolveApiBase() {
  const configured = import.meta.env.VITE_API_URL
  if (typeof configured !== 'string') return ''
  const trimmed = configured.trim().replace(/\/$/, '')
  return trimmed
}

const API_BASE = resolveApiBase()

// One page of Search results. The prefetch below asks for exactly the page
// Search would ask for, so it can stand in for that first request.
export const SEARCH_PAGE = 50

export function prefetchCitySearch(city, state) {
  if (typeof window === 'undefined' || !city || !state) return
  const existing = window.__churchmapSearchPrefetch
  if (existing && existing.city === city && existing.state === state) return
  const promise = listChurches({ type: 'location', city, state }, { limit: SEARCH_PAGE, offset: 0 })
  // Consumed by Search, which falls back to its own request on failure.
  promise.catch(() => {})
  window.__churchmapSearchPrefetch = { city, state, promise }
}

export function takeCitySearchPrefetch(city, state) {
  if (typeof window === 'undefined') return null
  const slot = window.__churchmapSearchPrefetch
  if (!slot || slot.city !== city || slot.state !== state) return null
  window.__churchmapSearchPrefetch = null
  return slot.promise
}

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

export function listChurches(search, { limit = 50, offset = 0, sort } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (sort) params.set('sort', sort)
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
