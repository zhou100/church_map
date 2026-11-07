import { useId } from 'react'
import { bandLabels, programGroups, programTypeLabel } from '../churchProfile'

// Kids, youth and childcare programs on a church's detail page, by age band.
// Each one is what the church's own page states (church_programs), with that
// page, the date we fetched it and the exact sentence, so a parent can check
// it. A program whose page gives no ages says so instead of guessing.
// Nothing here says a church lacks a program: no section means no evidence.

function checkedDate(iso) {
  const date = iso ? new Date(iso) : null
  if (!date || Number.isNaN(date.getTime())) return null
  // Checks are stamped in UTC; the UTC day is the day it was checked for everyone.
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

// Where a verified fact (scripts/publish_verified.py) was stated.
const SOURCE_TYPES = {
  own_site: "the church's website",
  fb_page: "the church's Facebook page",
  denomination: 'a denomination directory',
}

function SourceLine({ prefix, url, checkedAt }) {
  const date = checkedDate(checkedAt)
  return (
    <p className="program-source">
      {prefix}
      {date && <> · checked {date}</>}
      {url && (
        <>
          {' · '}
          <a href={url} target="_blank" rel="noopener noreferrer">View page</a>
        </>
      )}
    </p>
  )
}

function Program({ program, showBands }) {
  const facts = [
    programTypeLabel(program.program_type),
    showBands && program.age_bands.length > 1 ? bandLabels(program).join(', ') : null,
    program.ages_stated,
    program.schedule_stated,
    program.campus_stated,
  ].filter(Boolean)
  return (
    <li className="program-item">
      <p className="program-name">
        {program.name_stated || programTypeLabel(program.program_type) || 'Program'}
      </p>
      {facts.length > 0 && <p className="program-facts">{facts.join(' · ')}</p>}
      <SourceLine prefix="From the church's website" url={program.source_url} checkedAt={program.checked_at} />
      {program.excerpt && (
        <details className="program-evidence">
          <summary>What the page says</summary>
          <blockquote>&ldquo;{program.excerpt}&rdquo;</blockquote>
        </details>
      )}
    </li>
  )
}

export default function ProgramsSection({ church }) {
  const titleId = useId()
  const groups = programGroups(church)
  const verified = typeof church.kids_program === 'string' && church.kids_program.trim()
    ? church.kids_program.trim()
    : null
  if (!groups.length && !verified) return null
  const verifiedSource = church.fact_sources?.kids_program

  return (
    <section className="programs-section" aria-labelledby={titleId}>
      <h2 className="section-title" id={titleId}>Kids &amp; youth</h2>
      <p className="about-source">As stated by the church · confirm with them before you visit</p>
      {groups.map(group => (
        <div className="program-group" key={group.key}>
          <h3 className="program-group-title">{group.heading}</h3>
          <ul className="program-list">
            {group.programs.map((program, index) => (
              <Program key={index} program={program} showBands={group.key !== 'unstated'} />
            ))}
          </ul>
        </div>
      ))}
      {verified && (
        <div className="program-group">
          <h3 className="program-group-title">Checked by ChurchMap</h3>
          <ul className="program-list">
            <li className="program-item">
              <p className="program-name">{verified}</p>
              <SourceLine
                prefix={`Stated on ${SOURCE_TYPES[verifiedSource?.source_type] ?? 'a source we checked'}`}
                url={verifiedSource?.source_url}
                checkedAt={verifiedSource?.checked_at}
              />
            </li>
          </ul>
        </div>
      )}
    </section>
  )
}
