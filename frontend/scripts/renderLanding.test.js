import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { createServer } from 'vite'
import { renderLanding } from './renderLanding.js'

test('homepage prerender preserves adjacent text boundaries for hydration', async () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const routerShim = fileURLToPath(new URL('./prerenderRouterShim.js', import.meta.url))
  const server = await createServer({
    root,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false },
    plugins: [{
      name: 'test-prerender-router-shim',
      enforce: 'pre',
      resolveId(source, importer) {
        if (importer?.endsWith('/src/pages/Landing.jsx') && source === '../router') {
          return routerShim
        }
        return null
      },
    }],
  })
  try {
    const { default: Landing } = await server.ssrLoadModule('/src/pages/Landing.jsx')
    const markup = renderLanding(Landing, {
      id: 7,
      name: 'Grace & Peace',
      city: 'Brooklyn',
      state: 'NY',
      denomination: 'Baptist',
    })
    // These are distinct text children in Landing. Static rendering merges
    // them, producing React 425/418 and a full client render during hydration.
    assert.ok(markup.includes('<p>Brooklyn, NY<!-- --> · Baptist</p>'))
    assert.ok(markup.includes('Grace &amp; Peace'))
    assert.ok(markup.includes('href="/search"'))
  } finally {
    await server.close()
  }
})
