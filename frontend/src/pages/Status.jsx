import { useEffect, useState } from 'react'
import Icon from '../components/Icon'
import Seo from '../components/Seo'
import { getStats } from '../api/client'

export default function Status() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getStats().then(setStats).catch(err => setError(err.message))
  }, [])

  return (
    <div className="content-page">
      <Seo
        title="Coverage & Status"
        description="Live ChurchMap website-reading coverage and crawl pipeline status."
        canonicalPath="/status"
      />
      <a className="content-wordmark" href="/">ChurchMap</a>
      <p className="eyebrow">Live data</p>
      <h1>Coverage &amp; status</h1>
      <p className="content-lede">
        ChurchMap publishes the limits of its data because a useful profile should never look more complete than it is.
      </p>

      {error && <p className="error-msg">{error}</p>}
      {!stats && !error && <p className="loading">Loading current coverage…</p>}
      {stats && (
        <>
          <div className="status-grid">
            <article>
              <span>Churches known</span>
              <strong>{stats.churches.total.toLocaleString()}</strong>
            </article>
            <article>
              <span>Websites recorded</span>
              <strong>{stats.churches.with_website.toLocaleString()}</strong>
              <small>{stats.churches.with_website_pct}% of the directory</small>
            </article>
            <article>
              <span>Website summaries</span>
              <strong>{stats.churches.with_summary.toLocaleString()}</strong>
            </article>
            <article className={stats.crawl.pipeline_ok ? 'status-good' : 'status-warning'}>
              <span>Reading pipeline</span>
              <strong><Icon name={stats.crawl.pipeline_ok ? 'check' : 'clock'} /> {stats.crawl.pipeline_ok ? 'Healthy' : 'Delayed'}</strong>
            </article>
          </div>
          <p className="status-updated">
            Last calculated {new Date(stats.generated_at).toLocaleString()} · refreshed by the API every {Math.round(stats.cache_ttl_seconds / 60)} minutes
          </p>
        </>
      )}
      <a className="primary-link" href="/search">Search churches <Icon name="arrow" /></a>
    </div>
  )
}
