// Google Identity Services is not on the initial HTML. It competes with the
// app bundle on mobile, and most visits never sign in. Load it on idle, or
// immediately when a sign-in button is actually on screen.

const GSI_SRC = 'https://accounts.google.com/gsi/client'

let pending = null

export function loadGoogleIdentity() {
  if (typeof window === 'undefined') return Promise.resolve()
  if (window.google?.accounts?.id) return Promise.resolve()
  if (pending) return pending

  pending = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GSI_SRC}"]`)
    const script = existing || document.createElement('script')
    const finish = () => resolve()
    const fail = () => {
      pending = null
      reject(new Error('Google sign-in failed to load'))
    }
    script.addEventListener('load', finish, { once: true })
    script.addEventListener('error', fail, { once: true })
    if (!existing) {
      script.src = GSI_SRC
      script.async = true
      document.head.appendChild(script)
    }
  })
  return pending
}

export function scheduleGoogleIdentity() {
  if (typeof window === 'undefined') return
  const start = () => { loadGoogleIdentity().catch(() => {}) }
  if (typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(start, { timeout: 3000 })
  } else {
    window.setTimeout(start, 1500)
  }
}
