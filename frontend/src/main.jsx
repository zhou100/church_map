import { StrictMode, Suspense, lazy } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Landing from './pages/Landing'
import { scheduleGoogleIdentity } from './googleIdentity'
import './index.css'

const Search = lazy(() => import('./pages/Search'))
const ChurchDetail = lazy(() => import('./pages/ChurchDetail'))
const Status = lazy(() => import('./pages/Status'))
const Privacy = lazy(() => import('./pages/Privacy'))

function RouteFallback() {
  return <p className="loading">Loading…</p>
}

scheduleGoogleIdentity()

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
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<Landing exampleChurch={prerenderData.landingExample} />} />
            <Route path="/search" element={<Search />} />
            <Route path="/church/:id" element={<ChurchDetail />} />
            <Route path="/status" element={<Status />} />
            <Route path="/privacy" element={<Privacy />} />
          </Routes>
        </Suspense>
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
