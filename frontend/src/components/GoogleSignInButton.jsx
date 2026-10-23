import { useEffect, useRef } from 'react'
import { GOOGLE_CLIENT_ID } from '../context/AuthContext'

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

export default function GoogleSignInButton({ onCredential, options, minHeight = 44 }) {
  const btnRef = useRef(null)
  handleCredential = onCredential

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return

    function init() {
      if (window.google && btnRef.current) renderInto(btnRef.current, options)
    }

    if (window.google) {
      init()
    } else {
      // GSI script is async — poll until loaded
      const iv = setInterval(() => {
        if (window.google) { clearInterval(iv); init() }
      }, 100)
      return () => clearInterval(iv)
    }
  }, [options])

  if (!GOOGLE_CLIENT_ID) {
    return (
      <p style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>
        Sign-in unavailable — VITE_GOOGLE_CLIENT_ID not configured.
      </p>
    )
  }

  return <div ref={btnRef} style={{ minHeight }} />
}
