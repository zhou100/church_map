import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Landing from './pages/Landing'
import Search from './pages/Search'
import ChurchDetail from './pages/ChurchDetail'
import Status from './pages/Status'
import Privacy from './pages/Privacy'
import 'leaflet/dist/leaflet.css'
import './index.css'

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
          <Route path="/search" element={<Search />} />
          <Route path="/church/:id" element={<ChurchDetail />} />
          <Route path="/status" element={<Status />} />
          <Route path="/privacy" element={<Privacy />} />
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
