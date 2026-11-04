// Directory numbers a visitor reads on the landing and status pages.
// `churches.visible` excludes places the scope decision hides from every
// search, so "churches we know about" never counts one nobody can find. The
// whole-table fields are kept only for an API that predates `visible`
// (a frontend deployed before the backend).
export function directoryCounts(churches) {
  const source = churches?.visible ?? churches ?? {}
  return {
    total: source.total ?? 0,
    withWebsite: source.with_website ?? 0,
    withWebsitePct: source.with_website_pct ?? 0,
    withSummary: source.with_summary ?? 0,
  }
}
