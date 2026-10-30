// Same-origin `/api` when VITE_API_URL is unset or blank. Production relies on
// the Vercel rewrite to the Render API. Set VITE_API_URL to call another host
// (local dev against uvicorn).
function resolveApiBase() {
  // `env` is Vite's; plain Node (the unit tests) has none.
  const configured = import.meta.env?.VITE_API_URL
  if (typeof configured !== 'string') return ''
  const trimmed = configured.trim().replace(/\/$/, '')
  return trimmed
}

const API_BASE = resolveApiBase()

// One page of Search results, and the first page started early. Landing
// starts the exact request Search will make (same scope, sort and
// preferences, keyed by searchScope's queryKey) so it can stand in for it.
export const SEARCH_PAGE = 20

export function prefetchSearch(key, search, options) {
  if (typeof window === 'undefined' || !key) return
  if (window.__churchmapSearchPrefetch?.key === key) return
  const promise = listChurches(search, { ...options, limit: SEARCH_PAGE, offset: 0 })
  // Consumed by Search, which falls back to its own request on failure.
  promise.catch(() => {})
  window.__churchmapSearchPrefetch = { key, promise }
}

export function takeSearchPrefetch(key) {
  if (typeof window === 'undefined') return null
  const slot = window.__churchmapSearchPrefetch
  if (!slot || slot.key !== key) return null
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

// One page per call; callers ask for the next page only when the visitor
// does. `sort: 'nearest' | 'for_you'` is ranked by the server over the whole
// scope before paging, so page 2 continues page 1's order. `radiusMiles` on
// the search makes the circle (around lat/lon) the scope instead of the city.
export function listChurches(search, { limit = 50, offset = 0, sort, prefs, signal } = {}) {
  if (limit <= 0) throw new RangeError('Search page size must be positive')
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (sort) params.set('sort', sort)
  if (search.type === 'name') {
    params.set('name', search.name)
  } else if (search.radiusMiles != null) {
    params.set('lat', search.lat)
    params.set('lon', search.lon)
    params.set('radius_miles', search.radiusMiles)
  } else {
    params.set('city', search.city)
    params.set('state', search.state)
  }
  if (sort === 'for_you' && prefs) {
    for (const language of prefs.languages) params.append('prefer_language', language)
    for (const style of prefs.worship) params.append('prefer_worship', style)
    if (prefs.kids) params.set('prefer_kids', 'true')
  }
  return request(`/api/churches?${params}`, { errorMessage: 'Failed to fetch churches', signal })
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

export function getSearchCenter(city, state, { signal } = {}) {
  return request(`/api/churches/search-center?${new URLSearchParams({ city, state })}`, {
    errorMessage: 'No mapped churches to center on in this city', signal,
  })
}
