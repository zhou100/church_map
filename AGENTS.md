# ChurchMap: repository status and agent guide

Updated **2026-10-18 (America/Los_Angeles)**. Public stats snapshot generated at
2026-10-19 05:52:23 UTC (October 18, 22:52 PDT); uncached backfill enrollment
verified at 05:53:06 UTC (22:53 PDT). Counts below are dated snapshots; refresh
them before making operational decisions.

## Scope and sources

ChurchMap is the product; this checkout is named `holyhub`, and the remote is
[`zhou100/church_map`](https://github.com/zhou100/church_map).
React/Vite/Leaflet runs on Vercel; FastAPI runs on Render; Supabase Postgres
stores application data; Cloudflare R2 stores crawled HTML.

- Deployed code and local `main`: `ad4b81c`, merged in
  [PR #39](https://github.com/zhou100/church_map/pull/39) on October 18 at
  22:30 PDT. Both Render and Vercel production deployments succeeded for that
  exact revision. This document includes the subsequent backfill enrollment.
- Implementation is authoritative for shipped behavior. Read
  [CLAUDE.md](CLAUDE.md) for conventions and [DESIGN.md](DESIGN.md) before UI work.
- [STATUS.md](STATUS.md) and [TODOS.md](TODOS.md) contain July history and the
  backfill runbook. Their old counts and outstanding-work claims need to be
  checked against this snapshot and current code.
- `church_map_cold_start_refactor_plan.md` is an untracked local September
  proposal for a small Bay Area pilot, **not shipped behavior or a confirmed
  product decision**; it is not included in this release.

## What has been done

- **Postgres migration shipped.** Runtime routes use async psycopg repositories
  in [backend/db/repository.py](backend/db/repository.py); numbered migrations
  live in `migrations/`. SQLite is a historical import source.
- **Website crawling is deployed and scheduled.** Phase B lives in
  [backend/scrapers_v2/](backend/scrapers_v2/), with token-protected admin routes
  in [backend/routers/admin.py](backend/routers/admin.py). Migration `0004`
  added `raw_crawl_artifacts`, `crawl_runs`, `robots_cache`, and extraction metadata.
  `backend/scrapers/` is frozen v1 reference code; do not run or repair it.
- **Queue repair deployed (#39).** Unchanged-content fetches refresh their
  freshness timestamp while preserving archived source and extraction state.
  Requeue counts, selection, and updates now use the same HTTP 200 / non-null R2
  key eligibility rules as extraction. Failed-fetch `pending` rows no longer
  block otherwise usable archived pages.
- **Extraction produces product data.** Website summaries, denomination,
  languages, programs, worship style, theology, and pull quotes reach profiles
  and search details. Confidence and validated verbatim source snippets are
  persisted. Current prompt: `2026-07-24.v3.1`; model:
  `google/gemini-2.5-flash-lite` through OpenRouter.
- **Quality checks shipped.** The 18-example golden set, cached extraction/judge
  baseline, and prompt/model fingerprint gate run in `.github/workflows/evals.yml`.
  `baselines/CURRENT` points to `2026-07-26.v3.1-flash-lite`. Backend CI runs
  pytest against Postgres with pgvector and the real migrations (`tests.yml`).
- **Operational protections shipped.** Public `/api/stats` and frontend `/status`
  expose coverage and stage freshness. Failed stages and unexpected stage
  cancellations create/comment on `crawl-alert` issues; recovery closes an issue
  only when the whole pipeline is fresh. Keepalive attempts to prevent the
  inactivity shutdown that stopped crawling July 8–16.
- **Discovery frontend shipped.** Location/name search, website-derived profile
  content, enriched-first ranking, mobile list/map controls, honest review empty
  states, landing page, and prerendered church pages are implemented. July 28
  follow-ups source the landing example from the API, add per-church initial HTML
  and metadata, and strengthen the primary search CTA. Fixture reviews were
  removed by migration `0005`.

## How the daily website jobs work

Source: [.github/workflows/crawl.yml](.github/workflows/crawl.yml). **Cron times
are UTC**, independent of local daylight saving. These are bounded batches,
not a daily crawl of every website.

| Stage | UTC schedule | Default scheduled batch | Nominal daily capacity |
| --- | --- | ---: | ---: |
| Fetch | `17 */4 * * *` (every 4 hours) | 50 churches | 300 church attempts |
| Extract | `37 2,10,18 * * *` (3/day) | 75 churches | 225 church attempts |
| Name tag | `47 7 * * *` (daily) | 500 churches | 500 rows examined |

Actual execution can be delayed; attempts are not guaranteed successful or new
profiles. The extract endpoint itself defaults to 20; the workflow overrides it
to 75. Manual `workflow_dispatch` accepts `fetch`, `extract`, `tag`, or `all` and
an optional batch override; `all` orders the jobs fetch → extract → tag. Each
stage is a synchronous HTTP POST to the Render backend.

- **Fetch:** selects churches with a recorded URL. Default freshness is 30 days,
  with a 48-hour attempt backoff; oldest/never-tried attempts go first. HTTPX
  fetches the homepage plus up to three same-host linked pages from about,
  beliefs, ministries, and services candidates. It respects robots.txt (24-hour
  Postgres cache), waits 2 seconds between same-site requests, and retries a
  timeout/5xx once. It does not render JavaScript or discover missing website URLs.
- **Archive:** R2 keys are
  `raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html`; the hash is SHA-256 of
  cleaned text. Postgres deduplicates `(church_id, url, content_hash)`. Unchanged
  content does not automatically create new extraction work.
- **Extract:** groups eligible pending artifacts by church, oldest artifact
  first, reads R2, cleans text, calls the LLM, validates output, and writes
  church-level fields/provenance. Selection requires `extract_status='pending'`,
  `http_status=200`, and a non-null `r2_key`. A new prompt/model does **not**
  automatically revisit existing extractions.
- **Name tag:** incrementally applies name/denomination regex rules and stamps
  `name_tagged_at`, including non-matches. This is a separate heuristic, not LLM
  extraction or confirmation of actual service languages.
- **Keepalive:** `.github/workflows/keepalive.yml` runs at 05:23 UTC on days
  1, 11, and 21. It re-enables disabled workflows and pushes an empty commit if
  the latest commit is at least 30 days old.

Required runtime configuration: Render needs `DATABASE_URL`, `CRAWL_TOKEN`,
`OPENROUTER_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, and `R2_BUCKET`. GitHub needs secrets `BACKEND_URL` and
`CRAWL_TOKEN`; issue/action/content write permissions support alerts and keepalive.
The checked-in `render.yaml` does not declare the crawl/R2/OpenRouter variables;
verify dashboard provisioning when setting up another environment. Never print
or commit secret values.

## Verified live status: October 18

Evidence: public [`/api/stats`](https://churchmap-api.onrender.com/api/stats),
uncached admin requeue checks, GitHub deployment statuses, workflow logs, and
alert #37. Production work was performed through the existing admin API and
crawl workflow; no direct production DB/R2 inspection was performed.

- All four workflows (`crawl`, `keepalive`, `tests`, `evals`) were **active**.
  The ten most recent crawl runs returned `success`. The three latest keepalive
  runs (September 21, October 1, October 11 UTC) also succeeded.
- **The pipeline is healthy:** `crawl.pipeline_ok=true`; every stage is inside
  its freshness budget (fetch 12 hours, extract 24 hours, tag 48 hours). The
  initial audit found extraction idle since October 11; recovery is recorded below.
- The post-deploy [crawl verification](https://github.com/zhou100/church_map/actions/runs/39205060810)
  succeeded on `ad4b81c`: fetch run 1284 processed **5 / 5 ok / 0 errors**;
  extract run 1285 processed **5 / 5 ok / 0 errors**; tag run 1286 examined
  **5 rows / 0 rule matches / 0 errors**. Zero tag matches do not mean failure.
- [Alert #37](https://github.com/zhou100/church_map/issues/37) was automatically
  **closed** by that workflow at October 18, 22:33:35 PDT
  (`2026-10-19T05:33:35Z`). Backend health/search and frontend `/` and `/status`
  also passed HTTP smoke checks after deployment.

| Coverage metric | July 27 historical snapshot | October 18 latest snapshot |
| --- | ---: | ---: |
| Total churches | 133,939 | 133,939 |
| With website URL | 8,514 | 8,515 (6.4% of directory) |
| Successful extraction status (`attempts.ok`) | 5,326 | 5,852 (4.4% of directory) |
| With website summary | 4,332 | 5,212 (3.9% of directory) |
| Stale against current prompt/model | 5,316 | 2,513 |
| Stale, eligible, and awaiting requeue | 3,330 | **0 after enrollment** |

The zero comes from the uncached admin dry run at 22:53 PDT. The preceding
public stats response still reported 1,982 awaiting queue; its 300-second cache
can lag enrollment. There are **3,687** current-prompt/model rows. Enrollment
does not update church-level extraction provenance, so the stale count remains
2,513 until extractions actually succeed.

Other live counts: 6,200 churches have an extraction-attempt timestamp; 348 have
terminal `error` status (5.6% of attempts); 5,416 are Google-enriched. The current
snapshot has zero `no_html`, `no_text`, or `transient` church statuses. These are
current row states, not cumulative historical failure totals. Over the last
seven days, `crawl_runs` reports 57 `ok` runs and zero `partial`/`error` runs.

**Read the counters correctly:** `churches.extracted` includes failed attempts;
`attempts.ok` is the successful-status count; neither guarantees a useful profile.
`last_success` includes a zero-row `ok` run. `last_progress` requires a completed
run with `rows_ok>0`. Fetch `rows_ok` means `fetch_church` returned without raising,
not that HTML was archived: recorded HTTP/robots/storage errors can still count
as an ok church attempt. Inspect artifact outcomes before claiming crawl yield.

### October 18 recovery and reproduced queue defects

The follow-up investigation used the existing local crawl token without printing
it. Admin `/status?limit=100` showed 38 extract runs processing only 22 churches
in total, with recent extract runs consistently empty. The requeue dry run still
reported 1,838 available stale churches. The immediate cause of idle extraction
was an empty eligible queue; stale prompt/model rows are not automatically queued.

Live recovery: manually requeued **200 churches / 454 artifacts**, then called
extract with `batch=10`. Run **1283** completed with **10 processed, 10 successful,
zero errors**. Fresh public stats at **2026-10-19 05:21:35 UTC (October 18,
22:21 PDT)** confirmed **`pipeline_ok=true`**, extraction fresh again, **2,518
stale / 1,638 awaiting queue**, 3,682 current-prompt/model rows, and 5,211 website
summaries. At that point 190 churches from this batch remained for scheduled work;
the later post-deploy verification successfully extracted five more.
Public stats can lag changes by their 300-second cache. No prompt/model change or
automatic requeue schedule was introduced.

Two additional defects were reproduced against an isolated Postgres database:

- **Unchanged fetches stayed due forever.** Artifact dedup used `ON CONFLICT DO
  NOTHING`, preserving the old `fetched_at` used to select the next fetch batch.
  The fix refreshes that timestamp on conflict while preserving the archived
  source, extraction status, and extraction timestamp. Changed content still
  creates a new pending artifact.
- **Requeue and extract disagreed about eligibility.** Failed fetches default to
  `pending` even without HTTP 200 or an R2 key. They blocked requeue despite being
  impossible for extraction to consume. The fix applies the extractor's HTTP/R2
  predicates to requeue counts, candidate selection, and artifact updates.
  Truly eligible pending work still prevents duplicate requeueing.

The source fix is in `backend/db/repository.py`, with regression coverage in
`tests/scrapers_v2/test_requeue.py`. Ten new reproduction cases failed before the
patch; the final suite passed **215 tests, 5 skipped**. Local Postgres 14 applied
migrations 0001/0003/0004/0005; pgvector migration 0002 was unavailable locally.
Skips were two superseded legacy tests and three parity cases needing populated
San Francisco data. PR CI and merged-main CI then passed **215 tests, 5 skipped**
against Postgres 16 with pgvector and all five migrations applied. The deployed
repair made **344 additional churches** eligible for requeue: the uncached count
rose from 1,638 before deployment to 1,982 after deployment, confirming the
pending-eligibility defect's production impact. Individual production artifact
rows have not been inspected directly.

### Deployment and remaining backfill enrollment

[PR #39](https://github.com/zhou100/church_map/pull/39) merged as
`ad4b81c79c7cbf8eda8f26ebac59134aa737d9f7` at 22:30:28 PDT. Render reported
success at 22:31:33 PDT and Vercel at 22:31:11 PDT, both for that exact SHA.
The successful workflow and alert closure above verified the live pipeline.

At the user's explicit request, the remaining eligible backfill was enrolled
once at **22:53 PDT** through `POST /api/admin/crawl/requeue`:

- **1,982 additional churches / 4,552 artifacts**, in **10 bounded batches**:
  nine batches of 200 churches and one of 182.
- An uncached dry run verified the decreasing count after every batch:
  `1982 → 1782 → 1582 → 1382 → 1182 → 982 → 782 → 582 → 382 → 182 → 0`.
- Final dry run: **2,513 stale churches, 0 awaiting queue, 0 would requeue**.
  No further enrollment is needed for the currently requeueable stale set.
- The existing schedule remains **75 churches per extract run, three runs/day**.
  Queueing lets those scheduled runs perform paid extraction later; it does not
  mean the 1,982 churches have already been processed. No extra extraction run
  was triggered during this enrollment operation.

Including the earlier recovery, 2,182 churches have been enrolled in this
session. Fifteen were verified successfully extracted before the latest
enrollment, leaving an inferred **2,167 enrolled churches** for the daily jobs
at that moment. The public API does not expose exact eligible pending queue
depth, so this arithmetic is not a fresh DB measurement. The difference of
**346** between 2,513 stale and 2,167 enrolled is not automatically recoverable
work; terminal/unusable artifact cases need separate inspection. `awaiting_queue=0`
means enrollment is complete, **not that the backfill is finished**.

## Remaining gaps and next actions, in priority order

1. **Let scheduled extraction drain the enrolled backfill.** Deployment and
   enrollment are verified; the current requeueable stale set is fully enrolled.
   Monitor actual `rows_processed` / `rows_ok` / `rows_error`, stage freshness,
   current-prompt/model counts, and summary coverage. Stale should fall as
   re-extractions succeed. If progress stops, distinguish an empty eligible queue
   from terminal failures instead of requeueing blindly. Investigate the inferred
   346 remaining stale cases against artifact status, HTTP code, and R2 keys;
   `no_html` requires refetching, while transient failures should remain retryable.
   Keep requeue out of cron. Future prompt/model changes still require deliberate,
   bounded enrollment, using the dry-run-first runbook in [TODOS.md](TODOS.md).
2. **Make operational health describe useful work.** Separate eligible queue
   depth, expected idle stages, extraction yield, terminal failures, and real
   archived-page yield. Distinguish an intentionally empty queue from an
   unqueued backfill. Measure whether unchanged homepage refetches now leave the
   due queue and other sites advance; the timestamp fix is deployed and regression
   tested, but per-site production queue movement is not directly exposed.
   Alerting currently reacts to workflow failures; it
   does not independently open an issue merely because `/api/stats` is stale.
   Keepalive also cannot recover itself if it stops running. An independent
   freshness check would cover both silent-failure paths.
3. **Address missing URLs and demand priority.** 125,424 churches have no recorded
   URL, so raising crawl frequency cannot reach them. Audit missing versus truly
   absent websites; pilot URL discovery/verification using directories, existing
   Places data, and corrections with provenance and cost tracking. Prioritize
   a chosen metro or actual search demand rather than artifact age alone. The
   September proposal suggests 20–30 curated Bay Area profiles; adoption and
   implementation remain open. Define a useful/visit-ready profile and report
   completeness by metro before expanding nationally.
4. **Reduce cadence only after the backfill is accounted for.** The 75 × 3/day
   extract schedule was temporary backfill capacity, with an old estimate of
   roughly 28 days. It has not completed months later; do not repeat that ETA.
   Once queued work and terminal cases are understood, reassess steady-state
   cadence (the workflow suggests 50 × 2/day) and update freshness budgets with it.
5. **Close product and eval gaps.** Backend language/worship-style/stance filters
   exist, but `Search.jsx` still filters tags/language locally over loaded pages
   instead of wiring those website-derived filters through the API. Improve
   coverage-aware empty states and visible source/freshness/confidence. Expand
   the 18-example eval set across languages, denominations, and failure cases;
   successful cached evals do not establish corpus-wide quality.

## Working and verification rules

- Keep runtime SQL in repositories, use `%s` placeholders, and add numbered SQL
  migrations for schema changes. Do not reintroduce SQLite in routes.
- Preserve Google Identity Services user auth and separate `X-Crawl-Token` admin
  auth. Do not rerun paid Places enrichment or a corpus-wide re-extraction as a
  side effect of unrelated work.
- Prompt edits require a `PROMPT_VERSION` bump; model changes also invalidate
  the eval fingerprint. Regenerate and review the baseline/cache and update
  `baselines/CURRENT` together. Never bless a regression by merely rebaselining.
- For crawl changes, run `python -m pytest -q` with an isolated Postgres/pgvector
  test database and applied migrations; without `DATABASE_URL`, report DB-gated
  skips explicitly. Run `python -m evals.website_extraction.gate` for prompt/eval
  changes and `npm run build` in `frontend/` for frontend changes.
- To refresh this status, read public `/api/stats`, use `gh run list/view` for
  actual stage results, and inspect `crawl-alert` issues. Admin `/status` needs
  the crawl token. Record snapshot time, deployed prompt/model, queue counts,
  and data-quality outcomes; green workflow badges alone do not establish health.
- The initial audit was documentation-only. Subsequent authorized work deployed
  PR #39, verified 15 successful paid extractions, and enrolled 2,182 churches
  across the initial recovery and the remaining bounded backfill. The latest
  enrollment added queue work only. Production schema, secrets, prompt/model,
  crawl cadence, and Google Places enrichment were not changed.
