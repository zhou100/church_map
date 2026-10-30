import React from 'react'
import { renderToString } from 'react-dom/server'

export function renderLanding(Landing, exampleChurch) {
  // Unlike static markup, this retains the adjacent-text separators that
  // hydrateRoot needs to reuse the homepage DOM rather than replace it.
  return renderToString(React.createElement(Landing, { exampleChurch }))
}
