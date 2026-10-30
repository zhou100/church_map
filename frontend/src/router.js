// Re-exported so the landing prerender can substitute a static-HTML shim.
// The browser bundle still uses react-router. (Not under src/lib: that path
// is gitignored.)
export { Link, useNavigate } from 'react-router-dom'
