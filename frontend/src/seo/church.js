const SITE_URL = import.meta.env.VITE_SITE_URL || 'https://churchmap.vercel.app'

export function buildChurchSeo(church) {
  const place = [church.city, church.state].filter(Boolean).join(', ')
  const description = church.website_summary
    || `Church profile for ${church.name}${place ? ` in ${place}` : ''}, with website details and community ratings where available.`
  const canonicalPath = `/church/${church.id}`

  return {
    title: `${church.name}${place ? ` — ${place}` : ''}`,
    description,
    canonicalPath,
    type: 'place',
    jsonLd: {
      '@context': 'https://schema.org',
      '@type': 'Church',
      name: church.name,
      url: new URL(canonicalPath, SITE_URL).toString(),
      description,
      telephone: church.phone || undefined,
      sameAs: church.website ? [church.website] : undefined,
      address: (church.address || church.city) ? {
        '@type': 'PostalAddress',
        streetAddress: church.address || undefined,
        addressLocality: church.city || undefined,
        addressRegion: church.state || undefined,
      } : undefined,
      geo: (church.latitude && church.longitude) ? {
        '@type': 'GeoCoordinates',
        latitude: church.latitude,
        longitude: church.longitude,
      } : undefined,
    },
  }
}
