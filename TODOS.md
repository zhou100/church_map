# ChurchMap — Active TODOs

Rewritten 2026-07-24 (previous version was pre-Phase-A scaffolding for deleted
SQLite/`holyhub/` code — see git history if that's ever needed). Current state and
verification trail: [STATUS.md](STATUS.md).

**Current product bottleneck (2026-07-27): data coverage.** Search now exposes
website-derived content, identifies enriched cards, supports church-name lookup,
and has a reliable home/reset action. But only 8,514 of 133,939 churches (6.4%)
have a website recorded, 5,326 (4.0%) have a successful extraction, and 4,332
(3.2%) have a summary. The immediate work is making a useful church profile the
default experience, not adding more UI around sparse data.

The frontend revamp (#30) shipped the landing page, mobile layout, honest empty
states, per-church SEO and enriched-first ranking — see
[FRONTEND_PLAN.md](FRONTEND_PLAN.md) for the plan it executed. A post-deploy
audit of the live site found three gaps; the first is a trust issue and heads
the "Fix first" section below.

---

## Fix first — #30 follow-ups (live audit, 2026-07-27)

Small, self-contained, and all three are regressions against claims the product
now makes out loud. They come before the coverage work below because the landing
page is what new visitors see first.

- [x] **The landing page's example profile is hand-edited but presented as
      verbatim.** `frontend/src/pages/Landing.jsx:9-18` hardcodes
      `EXAMPLE_PROFILE`, rendered through the real `AboutSection` under the
      heading "A real profile, not a promise" and the source line "From this
      church's website". All four fields differ from what the extractor actually
      produced for church 113184:

      | field | landing page | live API |
      |---|---|---|
      | `pull_quote` | "…the **Pentecostal born again experience**…" | "…the **PENTECOSTAL BORN AGAIN EXPERIENCE**…" |
      | `theology_summary` | "They **affirm** the Bible as the word of God…" | "They **believe in** the Bible as the **infallible** word of God… are also **cent**" |
      | `summary` | "A multi-branch **Brooklyn** church… **practical care**…" | "This is a multi-branch church **in Brooklyn**… **They emphasize helping residents…**" |
      | `programs` | 4 items, Title Case | 8 items, lowercase |

      The `pull_quote` edit is the one that matters. The extraction system's
      whole trust story rests on that field being verbatim — prompt v3.1 keeps
      it in the source language precisely "because it's validated as a substring
      of the source text" (STATUS.md §7), and F6 below calls that validation
      "the strongest trust signal we have". The church wrote it in caps; the
      landing page sentence-cases it and still presents it in quotation marks as
      their words. F5 exists to stop machine-read claims looking like community
      consensus; this is the same failure aimed at the church itself.

      The `theology_summary` edit *rewrites away* the 240-char truncation rather
      than showing it fixed. The `_clamp` fix landed in the same PR, but 113184
      has not been re-extracted, so "See the full church profile" still lands on
      "…are also cent". The landing page is clean and the page it links to is
      not.

      Fix: source it from `/api/churches/113184` at prerender time so it cannot
      drift, or paste the exact API strings. Do not hand-polish extracted text
      anywhere it is labelled as coming from the church.

      Done 2026-07-28: the build now fetches church 113184 directly and passes
      that same response through SSR and hydration. The example no longer has
      a hand-maintained copy of any website-derived field.

- [x] **Prerendering covers `/` only; every other route serves that same HTML.**
      `curl` of `/`, `/search` and `/church/113184` returns byte-identical
      documents. `Seo.jsx` is correct — after JS runs, the church page has its
      own title, description, `og:url`, canonical and JSON-LD — but it runs too
      late for the consumers that matter most:

      - Social scrapers (WhatsApp, iMessage, Facebook, Twitter) do not execute
        JS, so sharing any church still yields the generic landing card. That
        was the main point of the SEO work.
      - Every church URL's raw HTML embeds Gospel Tabernacle's summary and pull
        quote, because that is what is baked into the prerendered landing page.
      - 4,332 church URLs serve duplicate initial HTML.

      Fix: extend `frontend/scripts/prerender.mjs` to emit per-church HTML for
      churches that have extracted content (only those — thin pages hurt more
      than they help), or add an edge function that injects meta tags for bot
      user-agents. Gate the church-page half on coverage; the landing page and
      top-N city pages are worth doing regardless.

      Done 2026-07-28: `/api/churches/prerender` exposes a keyset-paginated
      build feed gated on a non-empty website summary (not `extracted_at`).
      Vite emits clean-URL HTML for every qualifying church plus distinct
      `/search`, `/status`, and `/privacy` documents. Church pages carry their
      own title, description, canonical, Open Graph data and JSON-LD; the
      filesystem is checked before the SPA fallback, so thin profiles remain
      client-only rather than becoming indexable placeholder pages.

- [x] **The nav's primary CTA reads as disabled.** "Search churches" computes to
      `color: #6B6560`, `font-weight: 600` — identical to the plain "How it
      works" link beside it — distinguished only by a sienna border. Contrast is
      5.16:1 so it passes AA; the problem is hierarchy, not accessibility: the
      primary action looks weaker than the secondary link. Give it the sienna
      fill used by "Explore churches" in the hero, or at minimum sienna text.

      Done 2026-07-28: it now uses the hero CTA's sienna fill, white text and
      dark-sienna hover state.

---

## Recently completed (2026-07-27)

- [x] **Frontend revamp (#30)** — executed [FRONTEND_PLAN.md](FRONTEND_PLAN.md)
      Phases 1-3. Verified against the live site after deploy:

      - **Landing page at `/`, search moved to `/search`**, `/` prerendered
        (hero copy is in the raw HTML). Wordmark overload from #28 resolved:
        "Near me" is now its own control rather than a logo click.
      - **Mobile works.** Was: map rendered at width 0 at 390px and the 420px
        list panel clipped every card. Now: list/map toggle, map 390x489 with
        49 pins, zero overflowing elements.
      - **Fixture reviews removed in production** (`migrations/0005`). Brooklyn
        now returns 0 reviews; it previously showed 32 anonymous fixtures on
        church IDs 1-7, including one whose text was `test`, on the demo city's
        top results. The migration is guarded to anonymous, pre-2026-03-23 rows
        on those ids only, so later real reviews survive.
      - **Enriched-first ranking**, server-side in `repository.py` for both
        location and name search. Brooklyn's 14 enriched churches now occupy the
        first 17 slots (was 1 of 50); Chicago shows 44 enriched in the first 50.
      - **Honest empty state** — cards say "Website not read yet" rather than
        rendering as a failed load. This is the card half of F4.
      - Per-church SEO client-side (title, description, `og:*`, canonical,
        JSON-LD), real favicon, social card, `/status`, `/privacy`, footer.
      - `frontend/src/api/client.js` — the 12 scattered `fetch()` calls and the
        `ipapi.co` call now go through one module, per the `CLAUDE.md`
        convention.
      - Design fixes: custom map pin on `/church/:id` (the default blue Leaflet
        marker is gone), SVG icons replacing emoji.
      - `_clamp` in `backend/scrapers_v2/extract.py` now trims on a word
        boundary and appends an ellipsis instead of cutting mid-word. Affects
        rows written after deploy only — existing truncated summaries persist
        until re-extraction.

      Three gaps found in the same audit are open at the top of this file.

- [x] **Read the backfill failure breakdown, then decide about chunk 2.** Read
      2026-07-27 after Render redeployed: 5,463 attempted, 131 failed (2.4%).
      The breakdown was `error=125`, `transient=6`, `no_html=0`,
      `no_text=0`; pipeline health was green. That is an acceptable terminal
      floor plus a small self-retrying bucket, so **chunk 2 is safe to queue**.

      ```bash
      curl -sS https://churchmap-api.onrender.com/api/stats \
        | python3 -c 'import json,sys; d=json.load(sys.stdin)["extraction"]; print(json.dumps({k:d[k] for k in ("attempts","attempted","failed","failed_pct","stale","awaiting_queue")}, indent=2))'
      ```

      What each answer means:

      | dominant bucket | reading | next move |
      |---|---|---|
      | `no_html` | R2 has no page behind those artifacts — the premise of the backfill was wrong for them | re-**fetch** those churches; re-queueing does nothing. Needs a way to select them, which doesn't exist yet |
      | `transient` | LLM/network/R2 flakiness | nothing — they retry themselves; just watch the rate |
      | `no_text` / `error` | genuinely unextractable pages | accept as the floor; chunk 2 is safe |

      **Do not queue chunk 2 until this is read.** If over half of each batch
      fails terminally, more queueing spends money and marks more artifacts
      unrecoverable. Note the pre-existing `no-text` rows from before this
      change are ambiguous by construction — they were written when the two
      causes were one status — so judge from failures recorded *after* the
      deploy.

- [x] **Diagnose the 55% backfill extraction failure** — instrumented
      2026-07-27. Run 577 came back `75 processed / 34 ok / 41 error` against
      `50/50/0` on freshly-fetched work, and nothing exposed *why*. Three
      things landed:

      - `/api/stats` now carries `extraction.attempts` — a bucketed count of
        how attempts ended (`ok` / `no_html` / `no_text` / `error` /
        `transient` / `unknown` / `other`) — plus `attempted`, `failed`,
        `failed_pct` and `awaiting_queue`. Bucketed in SQL because the raw
        status strings embed exception text and this endpoint is public.
      - **`no-text` was hiding two different failures.** An R2 object that is
        *absent* and an R2 bucket that is *unreachable* both surfaced as "no
        text", identical to a genuinely empty page. Absent now reports
        `no-html:n/m` (the church needs re-fetching); unreachable is now
        **transient**, leaving artifacts `pending`.
      - That second one was a live data-loss path, not a reporting nit:
        rotated R2 credentials or a Cloudflare outage would have marked every
        artifact in every batch `skipped` — permanently excluded, since
        `requeue` only touches `ok` artifacts — silently, at cron cadence.

- [x] **Loosen the fetch staleness budget, 8h -> 12h.** Done 2026-07-27, and
      the same pass found a second, larger miscalibration: **a stage's
      freshness clock only advanced on a *flawless* run.** `_run_stage` writes
      `status='ok'` only when `rows_error == 0`, so any batch with one bad row
      is `partial` — and `crawl_health` counted only `'ok'`. Measured live that
      afternoon: `extract.last_success` was 21h old and closing on its 24h
      budget while the stage ran on schedule and extracted churches. For the
      duration of a backfill with any error rate, `pipeline_ok` would have been
      false continuously — including for the auto-close below, which is gated
      on it. Staleness now keys on `last_progress` (finished, and at least one
      row through); `last_success` is still reported, just not alerted on.

- [x] **Auto-close the `crawl-alert` issue on a green run.** Done 2026-07-27 —
      a `resolve` job in `crawl.yml`, gated on `/api/stats` reporting
      `pipeline_ok: true` rather than on the one stage that happened to run.
      A backend that can't answer counts as unhealthy and leaves the issue
      open, so a cold-start 502 can't auto-close anything (nor paint a
      successful crawl run red, which `set -e` plus `jq` on an HTML error page
      would otherwise do).

## Now — data coverage

Ordered by product impact. Finish the already-started backfill, point new crawl
work at user demand, then expand beyond the website-only ceiling.

- [ ] **Finish the extraction backfill.** The failure-rate gate passed
      2026-07-27; the next action is queueing chunk 2 with the Render-held
      crawl token. **Chunk 1 was queued 2026-07-27**
      (1,500 churches / 3,539 artifacts); `stale_churches` 5,413 →
      **awaiting_queue 3,330** still to hand over. Runbook:

      ```bash
      # Read the token from Render (dashboard -> churchmap-api -> Environment).
      # GitHub's copy exists but is unreadable by design, and it already works —
      # you only touch GitHub when rotating.
      read -rs CRAWL_TOKEN && export CRAWL_TOKEN
      BACKEND=https://churchmap-api.onrender.com

      # size it — dry_run is the default, nothing is written
      curl -sS -X POST -H "X-Crawl-Token: $CRAWL_TOKEN" \
        "$BACKEND/api/admin/crawl/requeue?dry_run=true"

      # queue a chunk, then let the extract cron drain it
      curl -sS -X POST -H "X-Crawl-Token: $CRAWL_TOKEN" \
        "$BACKEND/api/admin/crawl/requeue?dry_run=false&limit=1500"
      ```

      `-sS`, not `-s`: plain `-s` silences curl's *own* errors, so an unset
      variable makes a malformed URL and the command prints nothing at all,
      which reads like a broken endpoint. Triage: a token-less call returns
      `403`; a `404` means the route isn't deployed; silence means curl never
      made the request.

      `stale_churches` is the size of the job and only falls as churches are
      actually re-extracted. `awaiting_queue` is what's left to hand to the
      pipeline and falls per chunk. Both are now on public `/api/stats`
      (`extraction.stale` / `extraction.awaiting_queue`), so watching the
      backfill no longer needs the token — only queueing does. **Chunk, don't
      dump** —
      `pending_extract_targets` orders by `MIN(fetched_at) ASC` and re-queued
      artifacts keep their original timestamps, so every backfilled church
      sorts ahead of every newly crawled page; queueing all of them at once
      parks fresh crawl output behind the whole backfill.

- [x] **Surface `/api/stats` somewhere visible.** Done 2026-07-27 in #30, in
      both registers the original note asked for. Users get one honest sentence
      on the landing page, driven live from the endpoint ("We've read 4,332
      church websites so far, out of 133,939 churches we know about"). Operators
      get `/status`, linked from the footer, carrying the counts and pipeline
      health. Confirmed live: the number moved 4,332 → 4,342 between two reads
      forty minutes apart, so it is genuinely fetched rather than baked in.
      `pipeline_ok` / `attempts` / `stale` stayed out of the product UI.
- [ ] **Demand-driven fetch priority.** `churches_due_for_fetch` in
      `backend/db/repository.py` currently orders by `last_try ASC NULLS FIRST` —
      pure table order. Seed or reorder toward a top-N metro list (or actual search
      traffic once that's tracked) so coverage tracks where people look, not where
      church_ids happened to land. Brooklyn/NYC catching up this week was incidental
      (a bug fix + luck); the next demo city might not be.

- [ ] **Define and track "useful profile" coverage, not just extraction
      activity.** `/api/stats` can say whether an extraction ran, but the product
      needs a church-level completeness measure. Define the minimum fields that
      make a result worth opening, report the count and percentage publicly, and
      break it down by metro so work can target the thinnest high-demand areas.
      Do not use `extracted_at` as the KPI: failures stamp it too, and even a
      successful extraction can return little useful content.

- [ ] **Build a coverage path for the 125,425 churches with no website
      recorded.** The R2/LLM pipeline can never enrich 93.6% of the corpus in its
      current form. First audit whether these are truly website-less versus
      missing URLs; then rank safe sources and contribution paths (denomination
      directories, existing Google Places fields, church-submitted corrections,
      community submissions) by coverage, freshness, provenance and cost. Start
      with one metro pilot before any corpus-wide spend or schema expansion.

## After coverage — frontend search and filters

Read [DESIGN.md](DESIGN.md) before touching any of this. Ordered by
payoff-per-risk. F1 and F2 shipped; F3/F4 should follow better coverage because
filters over sparse machine-read data amplify unknowns into misleading absence.

**The measurement that should shape all of it** (live API, 2026-07-27,
`?city=Brooklyn&state=NY&limit=200`):

| | Brooklyn, of 200 returned |
|---|---|
| has a website at all | 28 |
| has `website_summary` | 14 |
| has `programs` / `pull_quote` | 16 |
| has `theology_summary` | 15 |
| has `vibe_tags` | 14 |
| has `theological_stance` | 11 |
| has `service_languages` | **8** |
| has `worship_style` | **6** |

So **~8% of cards in the demo city have anything to show**, and the
distribution is lopsided — prose fields land far more often than the two
enum-ish fields the filters key on. Design for the 93% first: a UI that looks
broken when data is absent is worse than one that never promised it. Coverage
rises as the backfill drains (`extraction.stale` on `/api/stats`), but the
long tail of website-less churches never gets extracted at all.

- [x] **F1. Show extracted data in the search detail panel.** Done 2026-07-27:
      `AboutSection` now lives in `components/` and is shared by the
      standalone route and the card/map detail panel. The primary search path
      now shows summaries, pull quotes, vibe tags, theology, worship style,
      statement of faith, languages and programs without an API or schema
      change.

- [x] **F2. Identify website-enriched churches on result cards.** Done
      2026-07-27: cards with a website summary or extracted fields now show a
      compact "From their website" row and up to two extracted language/vibe
      tags. The warm-surface block and outlined sienna pills remain visually
      distinct from community-rated tags; cards without extracted data are
      unchanged.

- [x] **Make discovery navigation and search scope explicit.** Done 2026-07-27
      in #28: the wordmark resets to default location, location search is labeled
      separately from global church-name search, and name results include
      city/state so similarly named churches are distinguishable.

- [ ] **F3. Filtering is client-side over one page of 50, so the #23 filters
      are unreachable.** Unchanged by #30 — re-checked 2026-07-27 against the
      current file. `pages/Search.jsx:203-205` builds `availableTags` /
      `availableLangs` from whatever rows are currently loaded and
      `Search.jsx:209-210` filters with JS `.filter()`. Consequences: the filter
      bar only ever offers values present in the loaded page, a filter "finds"
      nothing that hasn't been paged in, and `Search.jsx:460` hides Load More
      whenever a tag filter is active — an existing admission that client
      filtering and pagination don't compose.

      Note what #30 *did* change, so this doesn't get conflated: default
      ordering moved into SQL (`repository.py`, enriched-first). The sort
      controls and the tag/language filters in the UI are still client-side over
      loaded rows.

      `GET /api/churches` has taken `language`, `worship_style` and `stance`
      since #23 and nothing calls them. The fix is to move filter state into
      the URL (`useSearchParams`, alongside city/state) and refetch, so
      filters run over the whole city rather than the first 50 rows, Load
      More keeps working, and a filtered search is linkable.

      Bigger than F1/F2 — it touches the fetch/pagination/sort path, so it
      wants its own PR. Do it after F1 and F2, and note the sort controls are
      also client-side over loaded rows; don't quietly convert those too.

- [ ] **F4. Empty states have to distinguish "no such church" from "we
      haven't read this one yet".** With 8/200 Brooklyn churches carrying a
      `service_languages` value, a language facet is mostly a machine for
      producing empty result sets. "No churches match" is then factually
      wrong — a Spanish-speaking congregation with no website, or one the
      crawler hasn't reached, is not absent from Brooklyn, only from what
      we've read. Getting this wrong attacks the core product intent
      (`CLAUDE.md`: help people find a church that fits) more than shipping
      no filter at all would.

      Options that keep it honest: show the count next to each facet before
      it is clicked, so an empty result is predicted rather than discovered;
      or say "we haven't read this church's site yet" on the card and "N of M
      churches here have been read" on the empty state. Either way the filter
      should not silently imply absence.

      **Card half done 2026-07-27 in #30** — unread churches now say "Website
      not read yet" instead of rendering as a failed load, and the landing page
      states corpus-wide coverage. What remains is the *filter* half: per-facet
      counts before a facet is clicked, and a result-count sentence on the empty
      state. That half is coupled to F3 (facet counts need server-side
      filtering to be accurate), so do them together.

- [x] **F5. Define a treatment for machine-extracted data.** Decided
      2026-07-27: website-derived content sits in a warm-surface,
      sienna-bordered section labeled "From this church's website"; extracted
      pills use a white background with sienna text/border. `DESIGN.md` now
      requires the source line. We intentionally omitted a "checked <date>"
      claim, so this needed no `extracted_at` API change.

- [ ] **F6. Nothing in the UI reflects data quality per church.**
      `extracted_confidence` and `extracted_source_snippets` are written for
      every extraction and never leave the database. Not urgent, and possibly
      never user-facing — but a low-confidence summary currently renders
      identically to a high-confidence one, and the pull quote's verbatim
      validation (the strongest trust signal we have) is invisible. Revisit
      after F1-F5, and only if it makes a visible claim more trustworthy
      rather than adding developer-facing complexity to the UI.

## Backlog (not urgent, revisit on trigger)

- [ ] **Synonym-tolerant scoring for `service_languages`.** `score_one` compares
      normalized strings exactly, so "Kreyol" ≠ "Haitian Kreyol". v3.1 sidestepped
      the live instance by requiring English language names, but the brittleness
      is still there for the next near-synonym ("Mandarin" vs "Chinese"),
      and `denomination` already does substring-either-direction. Low urgency now,
      not zero.
- [ ] **Grow the golden set past 18 — the gate's accuracy depends on it.**
      Measured 2026-07-24: running the *identical* prompt twice moved `vibe_tags`
      0.667 → 0.778, a 0.111 swing from sampling alone, which is why judged fields
      now get a 0.15 band instead of 0.10. One example is worth ~0.056 at n=18; at
      n=40 it's 0.025 and both bands could tighten. `bootstrap.py` makes this cheap
      (`--city <X> --state <Y> --n 10`, review only the DRAFTs). Weight toward
      cities that are actually crawled.
- [ ] **Sermon transcript embeddings** — Whisper-transcribe published sermon
      audio/video, embed, rank by what's actually preached. Effort ~3-5 days for a
      10-church v1; ~$3 in Whisper cost for 50 ten-minute sermons. Needs an
      opt-out path (some churches will object) and a real signal users want this —
      revisit after search/filter on extracted data ships and query logs show
      sermon-style questions.
- [ ] **Public API + dataset publication** — rate-limited `GET /api/v1/churches` +
      a static CSV/parquet dump. Backlinks, SEO, credibility with
      researchers/journalists. Don't do this before extraction quality and
      coverage are solid — premature exposure of thin data damages trust more than
      it builds it. Trigger: eval precision >0.85 on high-impact fields AND >60%
      of churches with non-empty extractions.
- [ ] **Migrate church_embeddings off SQLite BLOB storage** — N/A, already done;
      the app runs on Supabase Postgres + pgvector (Phase A). Remove this line once
      confirmed there's no lingering reference anywhere.
- [ ] **sqlite-vec** — N/A for the same reason. Remove once confirmed unused.

---

## Not in scope right now

- Auth changes beyond the existing GSI/tokeninfo path (see `CLAUDE.md` guardrails —
  don't reintroduce JWT/sessions).
- Re-running Google Places enrichment (one-time $194 spend already done;
  `backend/routers/churches.py`'s `/enrich` endpoint stays cap-safe and idempotent
  for incremental use, not a bulk re-run).
- Touching `backend/scrapers/` (v1) — frozen, reference-only.
