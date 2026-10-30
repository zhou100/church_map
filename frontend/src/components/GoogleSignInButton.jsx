import { useEffect, useRef } from 'react'
import { GOOGLE_CLIENT_ID } from '../context/AuthContext'
import { loadGoogleIdentity } from '../googleIdentity'

// Google Identity Services wants `initialize` called once per page; several
// buttons (the header and the review form) share it and the latest handler.
let initialized = false
let handleCredential = null

function renderInto(element, options) {
  if (!initialized) {
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: res => handleCredential?.(res.credential),
    })
    initialized = true
  }
  window.google.accounts.id.renderButton(element, options)
}

export default function GoogleSignInButton({ onCredential, options, minHeight = 44, immediate = false }) {
  const btnRef = useRef(null)
  handleCredential = onCredential

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
    let cancelled = false
    let idleId = 0
    let timeoutId = 0

    function render() {
      loadGoogleIdentity()
        .then(() => {
          if (!cancelled && window.google && btnRef.current) renderInto(btnRef.current, options)
        })
        .catch(() => {})
    }

    // Header buttons can wait for idle. A review form is sign-in the visitor
    // asked for, so it loads the script immediately.
    if (immediate || window.google?.accounts?.id) {
      render()
    } else if (typeof window.requestIdleCallback === 'function') {
      idleId = window.requestIdleCallback(render, { timeout: 3000 })
    } else {
      timeoutId = window.setTimeout(render, 1500)
    }

    return () => {
      cancelled = true
      if (idleId) window.cancelIdleCallback(idleId)
      if (timeoutId) window.clearTimeout(timeoutId)
    }
  }, [options, immediate])

  if (!GOOGLE_CLIENT_ID) {
    return (
      <p style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>
        Sign-in unavailable — VITE_GOOGLE_CLIENT_ID not configured.
      </p>
    )
  }

  return <div ref={btnRef} style={{ minHeight }} />
}
