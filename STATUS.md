# ChurchMap — Status Report (2026-07-16)

Written after a repo + live-system audit on 2026-07-16. Previous activity: last commit
2026-05-08 (`f428db2`), crawl pipeline ran unattended since then.

---

## TL;DR

- **The crawl pipeline worked.** It ran every few hours for 60 days (May 9 → July 8),
  ~483 stage-runs, virtually all green. Church detail data (LLM summaries, tags,
  languages, worship style) is now live in the API and UI for a meaningful slice of
  churches — this did not exist before Phase B.
- **It silently stopped on July 8.** GitHub auto-disables scheduled workflows after
  60 days without a commit (`disabled_inactivity`). Nobody was notified.
  **Fixed today: the workflow has been re-enabled** — but it will happen again in 60
  days unless we commit something or add a keepalive.
- **Everything else is healthy**: backend (Render) and frontend (Vercel) are up,
  `pytest` passes clean (64 passed, 11 DB-gated skips), Supabase reachable via the app.
- **Two months of eval-harness work is sitting uncommitted** in the working tree.
  It's good work (offline CI-safe eval gating for the v3 prompt) — it should be
  finished and committed.

---

## 1. Current Status

### Infrastructure (all verified live today)

| Component | Status | Evidence |
|---|---|---|
| Backend (Render, `churchmap-api`) | ✅ up | `/api/health` → `{"status":"ok","read_only":false}` |
| Frontend (Vercel) | ✅ up | `churchmap.vercel.app` → HTTP 200 |
| Database (Supabase Postgres) | ✅ up | API queries return data |
| GitHub Actions crawl | ⚠️ was `disabled_inactivity` since Jul 8 → **re-enabled 2026-07-16** | `gh workflow list --all` |
| Test suite | ✅ 64 passed, 11 skipped (need `DATABASE_URL`) | `pytest -q` local |

### Crawl pipeline (Phase B) — what actually ran

- **~483 stage-runs** between 2026-05-09 and 2026-07-08 (run_id 483 was the last),
  triggered by the three crons in `.github/workflows/crawl.yml`.
- All recent runs **succeeded**; last runs before shutdown:
  - fetch (Jul 8): `rows_processed: 50, rows_ok: 50, rows_error: 0` — the fetch queue
    was **not exhausted** when it stopped; it was mid-work.
  - extract (Jul 7): `rows_processed: 50, rows_ok: 42, rows_error: 8` — a normal
    ~15% per-batch error rate (broken sites, unparseable pages).
  - tag (Jul 7): `rows_processed: 500, rows_ok: 14–20` — tag scans 500 but only
    re-tags churches with new extractions, i.e. steady-state.
- Throughput at configured batch sizes: ~300 pages fetched/day, ~100 extractions/day,
  with 30-day re-fetch freshness and 48h failure backoff.
- Extraction model: `google/gemini-2.5-flash` (prompt v3, `backend/scrapers_v2/prompts/website_v3.py`).
  Cost is negligible at this volume.

### Data we have now

DB row counts can't be measured from this machine (no local `DATABASE_URL`), so these
are from the live public API, sampled today with `limit=200` per city:

| City | Churches returned | with website | with LLM `website_summary` |
|---|---|---|---|
| Houston, TX | 200 (capped) | 101 | 50 |
| Chicago, IL | 147 | 77 | 47 (62 with `extracted_tags`) |
| Los Angeles, CA | 99 | 67 | 33 |
| New York, NY | 43 | 30 | 1 |
| Seattle, WA | 64 | 24 | 0 |
| Brooklyn, NY | 200 (capped) | 27 | 0 |

Baseline corpus (unchanged from OVERVIEW.md): **~134k churches** (IRS + OSM),
**~5,400** Google-Places-enriched, 6-dimension review system.

**What the 60 days of crawling changed:** before Phase B, a church detail page had
only Places data (photos, hours, phone). Now, for extracted churches, the API returns
a real editorial summary, vibe tags, languages, programs, worship style, theology
summary, and a verbatim pull quote — e.g. church 99360 (New Mount Sinai Missionary
Baptist, Chicago): summary + `vibe_tags: [family-oriented, community-focused,
welcoming]` + pull quote, all sourced from its own website with verbatim-snippet
validation. Plus a raw-HTML archive in R2 (dedup'd by content hash) that makes every
future re-extraction free of re-crawling.

**Coverage is real but uneven** — roughly 40–50% of website-having churches in
LA/Chicago/Houston have extractions, ~0% in NYC/Brooklyn/Seattle. The fetch queue
processes never-tried churches first in table order, so coverage tracks church_id
ranges, not user demand.

### Uncommitted work in the tree (since ~May 11)

- `evals/website_extraction/run.py` — rewired from the frozen v1 scraper to the live
  v3 extractor; adds `--save-cache` / `--from-cache` so CI can gate on eval scores
  **without LLM calls**; configurable regression threshold.
- `evals/website_extraction/golden.md` + `compile.py` — human-editable golden set
  compiled to `golden.jsonl`; grew from 4 to ~9 examples (some still marked `DRAFT:`).
- `evals/website_extraction/baselines/2026-05-11.v3.json` (+ cache) — v3 baseline:
  most fields at 1.0 precision on n=4; `vibe_tags` 0.5, `service_languages` 0.75.
- `tests/test_eval_scoring.py` — unit tests for the scorer.

---

## 2. Problems

**P1 — The pipeline can silently die (it just did).** `disabled_inactivity` after 60
commit-free days, zero notification, discovered 8 days later by accident. Re-enabled
today, but the failure mode is still armed. There is also no alerting on run failure —
a broken `CRAWL_TOKEN` or Render outage would fail silently too.

**P2 — No observability without DB credentials.** Run history lives in `crawl_runs`
and behind the token-gated `/api/admin/crawl/status`. From a fresh machine there is no
way to answer "how many churches have extractions?" — I had to sample the public API
city by city. Neither users nor interviewers can see the pipeline working.

**P3 — Crawl order ignores demand.** Coverage is dense where church_id ranges landed
(Chicago/Houston/LA) and empty in the demo city (Brooklyn — the search page literally
suggests "Try: Brooklyn, NY"). The best data is where nobody's looking.

**P4 — Extracted data barely changes the product.** Summaries/tags render on the
detail page, but search and filtering still run on review-derived tags — and with
near-zero organic reviews, most of 134k churches show empty bars and no tags. The
crawl solves the cold-start problem in principle; the product doesn't use it yet.

**P5 — Eval work is unfinished and unenforced.** Two months uncommitted, golden set
has `DRAFT:` entries, n=4 baseline, and the CI gate (deferred in TODOS.md) still
doesn't exist. Prompt regressions would ship silently.

**P6 — Docs are stale.** TODOS.md is pre-Phase-A (references SQLite,
`holyhub/database.py`, seeding scripts — all deleted). OVERVIEW.md predates the
60-day crawl run and undersells the working pipeline.

---

## 3. Suggestions

**For users** (make the crawl data earn its keep):

1. **Demand-driven crawl priority** — order `churches_due_for_fetch` by cities with
   search traffic / review counts, or simply seed the queue with the top-30 metro
   areas. One `ORDER BY` change + a priority column.
2. **Search on extracted data** — filter/facet by `extracted_tags` (languages,
   worship style, vibe) in `list_churches`, and show extracted tags on result cards
   when review-derived tags are empty. This is the cold-start fix: every crawled
   church becomes discoverable by "contemporary worship, Spanish service" instead
   of a blank card.
3. **Show provenance** — "From their website, checked June 2026" under the summary.
   Cheap trust win; the verbatim-snippet validation already exists to back it.

**For interviewers** (make the engineering visible):

4. **A public `/api/stats` + tiny status page** — total churches, % with websites,
   % extracted, last crawl time, runs in the past week. Turns "trust me, there's a
   pipeline" into a live dashboard. This also would have caught the July 8 outage.
5. **Ship the eval story** — commit the harness, finish the DRAFT goldens (aim for
   25–30 covering denominations/languages/edge cases), wire the `--from-cache`
   gate into CI on `PROMPT_VERSION` bumps. "LLM extraction with verbatim-source
   validation and CI-gated prompt regression evals" is a strong interview line.
6. **Write up the incident** — the 60-day auto-disable is a genuinely good ops story
   (silent failure mode, detection gap, fix + prevention). A short postmortem section
   in OVERVIEW.md shows operational maturity.

---

## 4. Next Steps (priority order)

| # | Action | Effort | Why now |
|---|---|---|---|
| 1 | ~~Re-enable crawl workflow~~ **done 2026-07-16** — verify next scheduled fetch fires (cron `17 */4 * * *`) | — | Pipeline resumes |
| 2 | ~~Commit the eval-harness WIP~~ **done 2026-07-16** — landed as an LLM-bootstrapped golden set (strong-model reference labels from real crawled pages, disagreement mining) + LLM judge for prose fields; n=18 baseline saved | — | Unblocks CI gate; **also resets GitHub's 60-day inactivity timer** |
| 3 | Guard against re-disable + silent failure: keepalive step (workflow re-enables itself via API) + failure notifications (GitHub → email is one checkbox; or a final `if: failure()` step) | S | Prevents P1 recurring |
| 4 | `/api/stats` endpoint + surface it (README badge or small status page) | S | P2; observability for you *and* interviewers |
| 5 | Demand-driven fetch priority (Brooklyn/NYC/Seattle first) | S | P3; makes the demo city work |
| 6 | Backfill extraction backlog: manual `workflow_dispatch stage=extract` with larger batch a few times | S | Fetch outran extract; cheap catch-up |
| 7 | Search/filter on `extracted_tags` + extracted tags on cards | M | P4; the actual product payoff of Phase B |
| 8 | Eval gate in CI on `PROMPT_VERSION` bump (already spec'd in TODOS.md deferred items) | S–M | P5 |
| 9 | Refresh TODOS.md (delete pre-Phase-A content) and OVERVIEW.md (add crawl numbers, incident writeup) | S | P6 |

Items 2–6 are each under an hour and compound: after them the pipeline is
self-healing, observable, and pointed at the cities people actually search.

---

## Appendix: how this was verified (2026-07-16)

- `gh run list` / `gh run view <id> --log` — run history + stage JSON results
- `gh workflow list --all` — `disabled_inactivity` state; `gh workflow enable crawl` — fix
- `curl https://churchmap-api.onrender.com/api/health` and `/api/churches?...` — live data sampling
- `pytest -q` — 64 passed, 11 skipped (DB-gated)
- `git status` / `git diff` — uncommitted eval work
- No local `DATABASE_URL`, so exact DB counts (total artifacts in R2/`raw_crawl_artifacts`,
  extraction totals) are estimates from API sampling; run `/api/admin/crawl/status`
  with the `CRAWL_TOKEN` or query Supabase directly for exact numbers.
