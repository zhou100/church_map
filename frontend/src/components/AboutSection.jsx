const WORSHIP_STYLE_LABEL = {
  liturgical: 'Liturgical',
  'traditional-hymns': 'Traditional hymns',
  blended: 'Blended worship',
  contemporary: 'Contemporary',
  charismatic: 'Charismatic',
}

export default function AboutSection({ summary, tags }) {
  const vibe = tags?.vibe_tags || []
  const programs = tags?.programs || []
  const langs = tags?.service_languages || []
  const theology = tags?.theology_summary
  const worshipStyle = tags?.worship_style
  const worshipDetail = tags?.worship_style_detail
  const pullQuote = tags?.pull_quote
  const faith = tags?.statement_of_faith || []

  const hasAnything = summary || theology || worshipStyle || worshipDetail
    || pullQuote || faith.length || vibe.length || programs.length || langs.length
  if (!hasAnything) return null

  return (
    <section className="about-section" aria-label="From this church's website">
      <p className="about-source">From this church&apos;s website</p>

      {summary && <p className="about-summary">{summary}</p>}

      {pullQuote && (
        <blockquote className="about-pullquote">{pullQuote}</blockquote>
      )}

      {vibe.length > 0 && (
        <div className="about-tags">
          {vibe.map(tag => <span key={tag} className="vibe-chip">{tag}</span>)}
        </div>
      )}

      {(theology || worshipStyle || worshipDetail) && (
        <div className="about-blocks">
          {theology && (
            <div className="about-block">
              <h4>What they teach</h4>
              <p>{theology}</p>
            </div>
          )}
          {(worshipStyle || worshipDetail) && (
            <div className="about-block">
              <h4>Worship style</h4>
              {worshipStyle && (
                <p className="about-block-lead">
                  {WORSHIP_STYLE_LABEL[worshipStyle] || worshipStyle}
                </p>
              )}
              {worshipDetail && <p>{worshipDetail}</p>}
            </div>
          )}
        </div>
      )}

      {faith.length > 0 && (
        <div className="about-block">
          <h4>Statement of faith</h4>
          <ul className="about-faith-list">
            {faith.map((item, index) => <li key={index}>{item}</li>)}
          </ul>
        </div>
      )}

      {(programs.length > 0 || langs.length > 0) && (
        <dl className="about-meta">
          {langs.length > 0 && (
            <>
              <dt>Languages</dt>
              <dd>{langs.join(', ')}</dd>
            </>
          )}
          {programs.length > 0 && (
            <>
              <dt>Programs</dt>
              <dd>{programs.join(' · ')}</dd>
            </>
          )}
        </dl>
      )}
    </section>
  )
}
