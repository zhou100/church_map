import Seo from '../components/Seo'

export default function Privacy() {
  return (
    <div className="content-page prose-page">
      <Seo
        title="Privacy"
        description="How ChurchMap handles location, account, and review data."
        canonicalPath="/privacy"
      />
      <a className="content-wordmark" href="/">ChurchMap</a>
      <h1>Privacy</h1>
      <p>ChurchMap uses only the information needed to help people find and review churches.</p>
      <h2>Location</h2>
      <p>
        If you choose “Near me,” or visit the landing page, a third-party IP location service may suggest
        a city and state. ChurchMap does not store your precise location on its servers.
      </p>
      <h2>Accounts and reviews</h2>
      <p>
        Google sign-in supplies your account identity so reviews can be attributed and protected from abuse.
        Reviews you submit are public. ChurchMap does not sell personal information.
      </p>
      <h2>Church information</h2>
      <p>
        Directory data comes from public records and public websites. Website-derived summaries are labeled
        so they are not mistaken for community opinion.
      </p>
      <p>
        Questions or correction requests can be filed through the project&apos;s{' '}
        <a href="https://github.com/zhou100/church_map/issues">public issue tracker</a>.
      </p>
    </div>
  )
}
