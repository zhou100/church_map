import { readFile, writeFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  appType: 'custom',
  logLevel: 'error',
  server: { middlewareMode: true },
})

try {
  const { default: Landing } = await server.ssrLoadModule('/src/pages/Landing.jsx')
  const markup = renderToStaticMarkup(React.createElement(Landing))
  const indexPath = new URL('../dist/index.html', import.meta.url)
  const html = await readFile(indexPath, 'utf8')
  await writeFile(
    indexPath,
    html.replace('<div id="root"></div>', `<div id="root">${markup}</div>`),
  )
} finally {
  await server.close()
}
