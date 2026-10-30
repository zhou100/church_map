import { createElement } from 'react'

// The landing page is rendered to static HTML without a browser router.
// Client navigations use the real react-router; this shim only has to
// print the same anchors the prerender used to emit as <a href>.

export function useNavigate() {
  return () => {}
}

export function Link({ to = '', children, ...rest }) {
  const href = typeof to === 'string' ? to : ''
  return createElement('a', { ...rest, href }, children)
}
