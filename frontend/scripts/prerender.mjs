import { mkdir, readFile, writeFile } from 'node:fs/promises'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const SITE_NAME = 'ChurchMap'
const SITE_URL = process.env.VITE_SITE_URL || 'https://churchmap.vercel.app'
const API_URL = (
  process.env.PRERENDER_API_URL
  || process.env.VITE_API_URL
  || 'https://churchmap-api.onrender.com'
).replace(/\/$/, '')
const PAGE_SIZE = 500
const EXAMPLE_CHURCH_ID = 113184

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function replaceMeta(html, selector, value) {
  const attribute = selector.startsWith('og:') ? 'property' : 'name'
  const pattern = new RegExp(`<meta ${attribute}="${selector}" content="[^"]*" \\/>`)
  return html.replace(
    pattern,
    `<meta ${attribute}="${selector}" content="${escapeHtml(value)}" />`,
  )
}

function withSeo(html, {
  title,
  description,
  canonicalPath,
  type = 'website',
  jsonLd,
}) {
  const fullTitle = title.includes(SITE_NAME) ? title : `${title} | ${SITE_NAME}`
  const canonical = new URL(canonicalPath, SITE_URL).toString()
  let output = html
    .replace(/<title>[^<]*<\/title>/, `<title>${escapeHtml(fullTitle)}</title>`)
    .replace(
      /<link rel="canonical" href="[^"]*" \/>/,
      `<link rel="canonical" href="${escapeHtml(canonical)}" />`,
    )

  for (const [selector, value] of [
    ['description', description],
    ['og:title', fullTitle],
    ['og:description', description],
    ['og:type', type],
    ['og:url', canonical],
    ['twitter:title', fullTitle],
    ['twitter:description', description],
  ]) {
    output = replaceMeta(output, selector, value)
  }

  if (jsonLd) {
    const serialized = JSON.stringify(jsonLd).replaceAll('<', '\\u003c')
    output = output.replace(
      '</head>',
      `    <script type="application/ld+json" data-churchmap-jsonld>${serialized}</script>\n  </head>`,
    )
  }
  return output
}

function withRoot(html, markup = '') {
  return html.replace('<div id="root"></div>', `<div id="root">${markup}</div>`)
}

function withPrerenderData(html, data) {
  const serialized = JSON.stringify(data).replaceAll('<', '\\u003c')
  return html.replace(
    '</body>',
    `    <script id="churchmap-prerender-data" type="application/json">${serialized}</script>\n  </body>`,
  )
}

async function fetchJson(path) {
  let lastError
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(`${API_URL}${path}`, {
        signal: AbortSignal.timeout(30_000),
      })
      if (response.ok) return response.json()

      const error = new Error(`${path} returned ${response.status}`)
      error.status = response.status
      if (response.status < 500) throw error
      lastError = error
    } catch (error) {
      if (error.status && error.status < 500) throw error
      lastError = error
    }
    if (attempt < 3) {
      await new Promise(resolve => setTimeout(resolve, attempt * 500))
    }
  }
  throw lastError
}

async function loadPrerenderProfiles(exampleChurch) {
  const profiles = []
  let afterId = 0
  for (;;) {
    let rows
    try {
      rows = await fetchJson(
        `/api/churches/prerender?limit=${PAGE_SIZE}&after_id=${afterId}`,
      )
    } catch (error) {
      // During the one-time rollout, the old API interprets "prerender" as a
      // church id and returns 422. Keep the frontend build usable until Render
      // has the new route, but do not hide later server or network failures.
      if (afterId === 0 && (error.status === 404 || error.status === 422)) {
        console.warn(
          `Prerender feed unavailable (${error.message}); generating the audited example page only.`,
        )
        return [exampleChurch]
      }
      throw error
    }
    profiles.push(...rows)
    if (rows.length < PAGE_SIZE) return profiles
    afterId = rows.at(-1).id
  }
}

async function writeRoute(distUrl, route, html) {
  const relativePath = route.replace(/^\/|\/$/g, '')
  const outputUrl = new URL(`${relativePath}.html`, distUrl)
  await mkdir(new URL('./', outputUrl), { recursive: true })
  await writeFile(outputUrl, html)
}

const server = await createServer({
  appType: 'custom',
  logLevel: 'error',
  server: { middlewareMode: true },
})

try {
  const { default: Landing } = await server.ssrLoadModule('/src/pages/Landing.jsx')
  const { default: PrerenderedChurch } = await server.ssrLoadModule(
    '/src/components/PrerenderedChurch.jsx',
  )
  const { buildChurchSeo } = await server.ssrLoadModule('/src/seo/church.js')
  const exampleChurch = await fetchJson(`/api/churches/${EXAMPLE_CHURCH_ID}`)
  const profiles = await loadPrerenderProfiles(exampleChurch)
  const distUrl = new URL('../dist/', import.meta.url)
  const indexUrl = new URL('index.html', distUrl)
  const baseHtml = await readFile(indexUrl, 'utf8')

  const landingMarkup = renderToStaticMarkup(
    React.createElement(Landing, { exampleChurch }),
  )
  await writeFile(
    indexUrl,
    withPrerenderData(withRoot(baseHtml, landingMarkup), {
      landingExample: exampleChurch,
    }),
  )

  const staticRoutes = [
    {
      route: '/search',
      title: 'Search churches',
      description: 'Search ChurchMap by city, state, or church name.',
    },
    {
      route: '/status',
      title: 'Coverage and pipeline status',
      description: 'See ChurchMap data coverage and website-reading pipeline status.',
    },
    {
      route: '/privacy',
      title: 'Privacy',
      description: 'How ChurchMap handles location, account, and review data.',
    },
  ]
  await Promise.all(staticRoutes.map(({ route, ...seo }) => writeRoute(
    distUrl,
    route,
    withSeo(baseHtml, { ...seo, canonicalPath: route }),
  )))

  for (let start = 0; start < profiles.length; start += 100) {
    await Promise.all(profiles.slice(start, start + 100).map(church => {
      const markup = renderToStaticMarkup(
        React.createElement(PrerenderedChurch, { church }),
      )
      return writeRoute(
        distUrl,
        `/church/${church.id}`,
        withRoot(withSeo(baseHtml, buildChurchSeo(church)), markup),
      )
    }))
  }
  console.log(`Prerendered ${profiles.length} church profiles from ${API_URL}.`)
} finally {
  await server.close()
}
