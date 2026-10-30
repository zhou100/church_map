import { StrictMode, Suspense, lazy } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Landing from './pages/Landing'
import { loadPreferences } from './preferences'
import { prefetchFirstPage } from './searchScope'
import { scheduleGoogleIdentity } from './googleIdentity'
import './index.css'

const Search = lazy(() => import('./pages/Search'))
const ChurchDetail = lazy(() => import('./pages/ChurchDetail'))
const Status = lazy(() => import('./pages/Status'))
const Privacy = lazy(() => import('./pages/Privacy'))

// Each lazy route gets its own boundary. The prerendered landing page has no
// Suspense markers, so a boundary above it would fail hydration.
function lazyRoute(Page) {
  return (
    <Suspense fallback={<p className="loading">Loading…</p>}>
      <Page />
    </Suspense>
  )
}

scheduleGoogleIdentity()

// Start the first page of a city search while the Search chunk downloads.
const startParams = new URLSearchParams(window.location.search)
if (window.location.pathname.replace(/\/+$/, '') === '/search' && !startParams.get('name')) {
  prefetchFirstPage(startParams, loadPreferences())
}

function readPrerenderData() {
  const element = document.getElementById('churchmap-prerender-data')
  if (!element) return {}
  try {
    return JSON.parse(element.textContent)
  } catch {
    return {}
  }
}

const prerenderData = readPrerenderData()
const app = (
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing exampleChurch={prerenderData.landingExample} />} />
          <Route path="/search" element={lazyRoute(Search)} />
          <Route path="/church/:id" element={lazyRoute(ChurchDetail)} />
          <Route path="/status" element={lazyRoute(Status)} />
          <Route path="/privacy" element={lazyRoute(Privacy)} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>
)

const root = document.getElementById('root')
if (window.location.pathname === '/' && root.hasChildNodes()) {
  hydrateRoot(root, app)
} else {
  root.replaceChildren()
  createRoot(root).render(app)
}
