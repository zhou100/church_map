import AboutSection from './AboutSection'

export default function PrerenderedChurch({ church }) {
  const location = [church.address, church.city, church.state].filter(Boolean).join(', ')

  return (
    <main className="detail-page prerendered-church">
      <a className="content-wordmark" href="/">ChurchMap</a>
      <article>
        <header className="detail-header">
          <h1>{church.name}</h1>
          {church.denomination && <p className="denom">{church.denomination}</p>}
          {location && <p className="address">{location}</p>}
          {church.website && (
            <p><a className="info-link" href={church.website}>Church website</a></p>
          )}
        </header>
        <AboutSection
          summary={church.website_summary}
          tags={church.extracted_tags}
        />
      </article>
    </main>
  )
}
