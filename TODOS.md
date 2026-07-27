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

---

## Recently completed (2026-07-27)

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

- [ ] **Surface `/api/stats` somewhere visible.** The endpoint exists now
      (aggregate counts, prompt-version split, per-stage freshness, the
      `extraction.attempts` failure breakdown, untokened). What's missing is
      somewhere a human actually looks: a README badge, a small status page,
      or a line on the frontend footer. A number nobody sees is the same as no
      number — that's how the July disable went 8 days unnoticed.

      Keep the audience straight. `pipeline_ok` / `attempts` / `stale` are
      *operator* numbers and do not belong in the product UI — that is exactly
      the developer-facing complexity `CLAUDE.md` warns against. The
      user-facing version of this is one honest sentence about coverage
      ("we've read N of M church websites"), which is really F4 in the
      frontend section. A separate `/status` page can be as technical as it
      likes.
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
      are unreachable.** `pages/Search.jsx:149-156` builds `availableTags` /
      `availableLangs` from whatever rows are currently loaded and filters
      with JS `.filter()`. Consequences: the filter bar only ever offers
      values present in the loaded page, a filter "finds" nothing that hasn't
      been paged in, and `Search.jsx:330` hides Load More whenever a tag
      filter is active — an existing admission that client filtering and
      pagination don't compose.

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
