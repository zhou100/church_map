# ChurchMap — Status Report (2026-07-16, updated 2026-07-24)

Written after a repo + live-system audit on 2026-07-16. Previous activity: last commit
2026-05-08 (`f428db2`), crawl pipeline ran unattended since then.

**2026-07-24 update:** PR [#13](https://github.com/zhou100/church_map/pull/13) (eval
harness) merged 2026-07-16. Two more commits landed on `main` the same window:
`c46a56f` (fixes a real fetch-queue bug — malformed-URL churches were burning entire
batches on instant fast-fails because their attempts never got recorded) and `ecac87b`
(frontend cleanup). The crawl workflow has run cleanly for 8 straight days since
re-enabling — see [§5](#5-2026-07-24-follow-up) for current numbers and the updated
next-steps list. Sections 1–4 below are left as originally written (2026-07-16) for
the historical record; §5 is the current state.

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

---

## 5. 2026-07-24 follow-up

### What changed since the audit

- **PR #13 merged** (2026-07-16): LLM-bootstrapped golden set + judge scoring for the
  extraction eval (see below). Also reset GitHub's 60-day inactivity clock.
- **Crawl workflow: stable for 8 days.** 39 stage-runs from Jul 21–24 alone, all
  `success`, still running on the same three-cron schedule. No re-disable, no
  intervention needed.
- **A real fetch-queue bug got fixed in-flight** (`c46a56f`, landed the same day as
  the merge, not part of this session's work): churches with malformed website URLs
  hit an early-return in `fetch_church` that never wrote an artifact row, so
  `churches_due_for_fetch`'s 48h backoff never kicked in — those churches got
  re-picked every single cron run and burned whole batches in ~90ms with zero actual
  work done. Now every bad-URL attempt writes `http_status=0, fetch_error="bad-url"`
  so the backoff evicts them properly. This directly explains why coverage moved
  as much as it did this week (see below) — batches are no longer being wasted.

### Coverage, re-sampled today

| City | with website | with `website_summary` | Jul 16 → Jul 24 |
|---|---|---|---|
| New York, NY | 30 | **15** | 1 → 15 |
| Brooklyn, NY | 27 | **14** | 0 → 14 |
| Chicago, IL | 77 | 47 | 47 → 47 (already saturated) |
| Seattle, WA | 24 | 0 | 0 → 0 (queue hasn't reached it yet) |

**Brooklyn and NYC — the demo cities — went from essentially zero coverage to roughly
half their website-having churches extracted in 8 days**, entirely from the bad-URL
backoff fix plus normal table-order crawling catching up. P3 (crawl order ignores
demand) is still real — Seattle is still untouched, and this was luck-of-table-order,
not a deliberate priority change — but the most visible instance of it (the city the
search page suggests) has resolved itself.

### Eval harness: landed, review queue confirmed

`golden.md` on `main` now has **18 compiled examples**: 4 original hand-written
(`Example:`), 6 pre-existing hand-authored templates that were already marked
`DRAFT:` before this session (Megachurch multi-site, AME, Eastern Orthodox, Korean
immigrant bilingual, Quaker meeting, Sparse low-info page — these need real source
URLs, not disagreement review), and 8 auto-bootstrapped from real Brooklyn churches
(3 landed as trusted `Example:`, 5 as `DRAFT:` from production/reference
disagreement). **11 DRAFT entries total** are the open review queue — two different
kinds mixed together, see next steps below.

### Next steps (supersedes §4 — current priority order)

| # | Action | Effort | Why |
|---|---|---|---|
| 1 | ~~Clear the 11-item `DRAFT:` backlog in `golden.md`~~ **done 2026-07-24** — see [§6](#6-2026-07-24-delivery) | — | Baseline is only as trustworthy as the reviewed fraction; also unblocks #2 |
| 2 | ~~Wire the CI gate~~ **done 2026-07-24** — `.github/workflows/evals.yml` + `gate.py` | — | Mechanics all exist (`run.py`, cached verdicts) — this is the piece that makes the eval enforce itself instead of relying on memory |
| 3 | ~~Add a crawl keepalive + failure notification~~ **done 2026-07-24** — `.github/workflows/keepalive.yml` + an `alert` job in `crawl.yml` | — | The Jul 8 disable was silent; nothing prevents a repeat once the 60-day clock runs out again, and there's still no alert on a failed run (bad `CRAWL_TOKEN`, Render outage) |
| 4 | ~~`/api/stats` endpoint~~ **done 2026-07-27** (#16, hardened in #20) — surfacing it in the UI is still open, see [§8](#8-2026-07-27--observability-the-backfill-starts-and-what-it-found) | — | No live observability today outside token-gated admin endpoints or manual API sampling like this report did |
| 5 | Demand-driven fetch priority — seed/reorder `churches_due_for_fetch` toward top-N metro areas instead of relying on table order + luck (Seattle is still at 0) | S | Brooklyn/NYC catching up was incidental (bug fix + table order), not by design; the next demo city might not be so lucky |
| 6 | ~~Search/filter on `extracted_tags`~~ **API done 2026-07-27** (#23: `language`, `worship_style`, `stance`); the frontend half is still open | — | The actual product payoff of Phase B — extraction coverage doubling in NYC/Brooklyn this week doesn't help users until search uses it |
| 7 | Refresh `TODOS.md` (done alongside this update — replaced pre-Phase-A content with the active backlog) and `OVERVIEW.md` (crawl numbers are stale — still says the pipeline is aspirational/"adds", not that it's been running successfully for months) | S | Docs undersell working infrastructure |

Item 6 is now the highest-leverage *product* item — the data exists, coverage in the
demo cities is real, and nothing downstream of extraction uses it yet.

---

## 6. 2026-07-24 delivery

Items 1–3 of §5 shipped. Items 4–6 (`/api/stats`, demand-driven fetch priority,
search on `extracted_tags`) are untouched and remain the queue.

### Golden set: 11 DRAFTs → 0, still n=18

Two kinds of DRAFT, handled differently:

**The 5 auto-bootstrapped disagreements** were adjudicated one at a time; each
section now carries a `Reviewed 2026-07-24:` line saying which way it went and why.
Three kept the reference labels (real production misses), two corrected them:

- *First Church of Christ, Scientist* — the reference model had echoed the
  congregation's **name** back as its denomination. Corrected to "Christian
  Science"; production was right.
- *The Gospel Tabernacle* — `worship_style: "charismatic"` dropped. The reference
  inferred it from "Pentecostal", but the page never describes a service, and v3
  says to bucket worship style from explicit cues only. Production's `null` was
  correct.

**The 6 hand-authored templates** were "chase down a real URL, or delete". All six
categories were chased: real pages were fetched and labeled for each. Three
replaced their template outright — Mother Bethel A.M.E. (Philadelphia), the Greek
Orthodox Cathedral of the Holy Trinity (NYC), and Korean Central Presbyterian
(Vienna VA), which is genuinely bilingual and names both congregations explicitly.
Three did not: lifepoint.church cleaned to marketing fragments with no structured
signal, fmcquaker.org to seven lines of duplicated calendar notices, and there is
no real page that reliably tests "returns nothing when there's nothing there". Those
three stayed as `URL: synthetic` canaries with the reasoning written into the file.

Two goldens turned out to be **unsatisfiable by construction**: they expected
`worship_style: "gospel"` and `"silent"`, neither of which is in `WORSHIP_STYLES`,
so no schema-valid extraction could ever have matched them. They had been quietly
costing 2 of the 12 `worship_style` scores since they were written.

### What the baseline says now (`baselines/2026-07-24.v3.json`)

| field | Jul 16 | Jul 24 | |
|---|---|---|---|
| worship_style | 0.750 | **1.000** | the two impossible goldens are gone |
| statement_of_faith | 0.944 | **1.000** | |
| community_summary | 0.889 | 0.944 | |
| denomination | 0.867 | 0.867 | |
| theological_stance | 0.909 | 0.909 | |
| theology_summary | 0.833 | 0.833 | |
| worship_style_detail | 0.944 | 0.944 | |
| programs / vibe_tags / pull_quote | 1.000 / 0.833 / 0.833 | 0.944 / 0.778 / 0.778 | one example each, on harder real pages |
| **service_languages** | 0.706 | **0.588** | ← the finding |

The two baselines aren't strictly comparable (three examples were swapped), but
the direction on `service_languages` is not noise. **Production returns `[]` for
any page that doesn't name a language in so many words**, which is most pages: 7 of
17 goldens now fail this field, including three where the page is unambiguously
English end to end. v3 says "Empty list if unclear" and the model takes it
literally. That single line is why a language filter would find almost nothing —
and it's a prompt fix, now scoped in TODOS.md as the v4 batch, along with KCPC
extracting `denomination: "장로교회"` (correct, and useless to an English facet).

This is the eval doing its job: it turned "search on extracted tags" from a feature
request into a measured, named defect with a number attached.

### CI gate (`.github/workflows/evals.yml`, `evals/website_extraction/gate.py`)

Runs on PRs touching `evals/**` or `backend/scrapers_v2/prompts/**`. Scores from
cached extractions and cached judge verdicts, so it needs no API key, no database
and no network, and costs nothing.

The trap it exists to avoid is that `--from-cache` **cannot fail** on a stale
cache — it would score the old prompt's output and report no regression. So the
gate refuses to run at all unless three things hold: `golden.jsonl` matches
`golden.md`, every golden has a cache entry (otherwise `run.py` silently falls
back to live LLM calls and CI dies on a missing key instead of saying what's
wrong), and the prompt's content hash matches the one stamped into both the
baseline and the cache. Verified by editing the prompt without bumping
`PROMPT_VERSION` — the gate caught it on the content hash and exited 2.

`baselines/CURRENT` names the active baseline stem, so re-baselining is a one-line
change rather than a workflow edit. 14 tests in `tests/test_eval_gate.py` cover the
refusal paths, including the one defeat move worth blocking: refreshing a baseline
from extractions that predate the prompt edit.

### Crawl keepalive + alerting

`keepalive.yml` runs every ~10 days and does two things. It re-enables any workflow
sitting in a `disabled_*` state (a no-op when everything is active), and it pushes
an **empty commit only if the last commit is more than 30 days old** — resetting
GitHub's 60-day inactivity clock without adding a single line of log noise during
normal development. The 30-day threshold leaves several runs of slack before
anything could be disabled.

`crawl.yml` gains an `alert` job (`if: failure()`, `needs` all three stages) that
opens a `crawl-alert` issue on failure, or comments on the open one rather than
filing duplicates. No new secrets — `GITHUB_TOKEN` only.

**One manual step remains**: the repo's default workflow permission is `read`. Both
new jobs request more explicitly (`issues: write`, `contents: write`,
`actions: write`). If either 403s on its first run, flip Settings → Actions →
General → Workflow permissions to "Read and write". Dispatching `keepalive`
manually is the cheapest way to find out — it no-ops while the repo is active.

---

## 7. Prompt v3.1 — the eval's first real catch

The `service_languages` finding from §6 turned into a prompt fix, and the gate
built in §6 blocked it until the cache was regenerated, exactly as designed.

**Two rule changes, same schema** (so `v3.1`, not `v4` — no new module, no import
churn): `service_languages` now falls back to the language the page is written in
when no service language is named, and every extracted value must be in English
except `pull_quote`, which stays verbatim because it's validated as a substring
of the source.

| field | v3 | v3.1 run 1 | v3.1 run 2 | |
|---|---|---|---|---|
| **service_languages** | 0.588 | **1.000** | **1.000** | the target |
| **denomination** | 0.867 | **1.000** | **1.000** | |
| theology_summary | 0.833 | 0.944 | 0.944 | |
| pull_quote | 0.778 | 0.889 | 0.889 | |
| theological_stance | 0.909 | 0.818 | 0.818 | consistent 1-example loss |
| vibe_tags | 0.778 | 0.667 | 0.778 | **noise** |

Concretely: `"장로교회"` → `"Presbyterian"`, `["교사모집", "자녀 세미나", …]` →
`["teacher recruitment", "parenting seminar", …]`, `"Kreyol"` → `"Haitian Creole"`,
and Gospel Tabernacle's `"Non-denominational"` → `"Pentecostal"`. The one
consistent loss is Mother Bethel's `theological_stance` going `"progressive"` →
`null` — an example flagged as borderline when it was first reviewed. It was left
as a recorded miss rather than softening the golden to match the new prompt.

### The gate needed calibrating, and now there's a number behind it

The first v3.1 run tripped the gate on `vibe_tags` (0.778 → 0.667). Rather than
wave it through, the identical prompt was run a second time: every
deterministically scored field came back bit-identical, while `vibe_tags` moved
0.111 — wider than the gate's own 0.10 threshold. **The regression was sampling
noise, and as shipped the gate would have failed this PR, and every future prompt
PR, on nothing.**

So judged fields now get a 0.15 band and deterministic fields stay at 0.10
(`run.threshold_for`, with the measurement in its docstring). Verified from both
sides: the noisy second run passes, and an injected 0.182 drop on a deterministic
field still fails. The real fix is more examples — one is worth ~0.056 at n=18 —
which is now filed with the measurement attached rather than as a vague "more
would be better".

### Two things worth knowing

**A prompt fix is not a data fix.** Extraction is driven by
`extract_status = 'pending'`, not by prompt version, so every already-extracted
church keeps its v3 values — empty languages, Korean denomination strings. Filed
as a backfill task, and it's a prerequisite for search/filter on `extracted_tags`
being worth much.

**`call_llm` crashed on an empty completion.** A 200 response carrying
`"content": null` hit `None.strip()` and took a whole eval run with it — ~17
completed extractions of spend, discarded. In production that raised an
`AttributeError`, which is neither of the two error classes the extract loop
routes on. It now retries like any other blip, with tests. Found by hitting it,
not by reading for it.

---

## 8. 2026-07-27 — observability, the backfill starts, and what it found

Seven PRs landed between §7 and here. The through-line: each one's findings
generated the next one's work, and the last one found something that
questions the premise of the backfill itself.

### What shipped

| PR | What | Why it mattered |
|---|---|---|
| #16 | Public `GET /api/stats` | No way to tell a working pipeline from a dead one without a token |
| #17 | flash-lite + `requeue` backfill mechanism | Prompt fixes don't touch already-extracted rows |
| #18 | Fixed the backfill runbook | It printed *nothing* and looked like a dead endpoint |
| #20 | Crawl health visibility | "No errors" was reading as healthy |
| #21 | CI that runs the test suite | Backend changes had been shipping with no CI at all |
| #22 | Extract cadence 50x2 → 75x3 | Backfill was a ~54-day job |
| #23 | Search filters on `extracted_tags` | The crawl data finally reaches search |

Two of those exist only because something went wrong first, and both are
worth remembering:

**The runbook printed nothing (#18).** It used `$BACKEND`, a variable
defined nowhere in this repo, together with `curl -s` — which silences
curl's *own* errors, not just progress. Unset variable → malformed URL →
exit 3 → total silence, indistinguishable from a dead endpoint. The endpoint
had been fine the whole time. `-sS` now, and a triage line: 403 means it
works, 404 means it isn't deployed, silence means curl never made the call.

**Backend changes had no CI (#21).** `evals.yml` only fires on `evals/**`
and the prompts directory, so #16, #17 and #20 each merged showing nothing
but a Vercel preview. The suite now runs against a real Postgres with real
migrations, which matters more than the unit tests: **149 pass in CI versus
134 locally** — fifteen DB-gated tests that had been silently skipping. The
re-queue stall and the stats/re-queue disagreement in #20 were both found by
a real database and agreed with by the mocks.

### The 2026-07-27 incident: alerting worked, and exposed a structural gap

A scheduled fetch failed at 04:04 with a bare 500. The `alert` job filed
issue #19 eleven seconds later — the first real test of it, and the thing
that would have been silence a week earlier.

The diagnosis came from an absence: `_run_stage` writes a `crawl_runs` row
before returning 500, but `/api/stats` reported `error: 0` across the whole
window. No row was written, which put the failure *before* `start_run` — and
the only step there is acquiring a connection. If the database is
unreachable there is nowhere to write "the database was unreachable."

That can't be recorded, so #20 stopped the health signal depending on it:
per-stage `age_seconds` against a budget, plus `pipeline_ok`. Age since the
last success is the one signal an absent row cannot fake. Five green runs
followed; the failure was a transient Supabase refusal.

**The budget is mis-tuned, though.** Fetch allows 8h against a 4h cron, so a
single failure always trips `pipeline_ok` — the next attempt is 4h out and
age passes 8h before recovery is possible. Filed to move to 12h.

### The backfill started, and the first batch is a problem

Chunk 1 queued 2026-07-27: **1,500 churches / 3,539 artifacts**, leaving
`awaiting_queue` at 3,330. `stale_churches` stayed at 5,413, correctly — a
church stays stale until extraction rewrites its row.

The first re-extraction batch came back:

```
run 577  rows_processed: 75  rows_ok: 34  rows_error: 41     (55% failure)
run 572  rows_processed: 50  rows_ok: 50  rows_error:  0     (normal work, for contrast)
```

At ~34/run x 3 runs/day that is ~53 days — the #22 cadence increase is
cancelled out by the error rate. But the arithmetic is the smaller worry.
`extract_for_church` has three failure paths with very different
consequences: `no-text` marks artifacts **`skipped`** and `ExtractionError`
marks them **`error`**, and `requeue` only touches `ok` artifacts — so both
are *permanently excluded* from future passes. Only transient failures
retry.

If those 41 are `no-text`, the premise of the backfill is wrong: the R2
archive doesn't hold readable HTML for older artifacts, and those churches
need re-*fetching*. It would also fail silently, with `stale_churches`
plateauing while `awaiting_queue` marches to zero — indistinguishable from
completion.

`churches.extracted_status` already records which, and nothing exposes it.
That is the next thing to build, and chunk 2 should wait for the answer.

### Also worth recording

**A model swap defeated the eval gate.** `prompt_fingerprint()` hashed the
prompt but not `MODEL`, so switching to flash-lite would have scored the new
model against the old model's cache and passed clean. Same vacuous pass the
gate exists to prevent, reached by a different lever. Now hashed, with
`run.py --model` for evaluating a candidate without touching production.

**`/api/stats` and the re-queue disagreed about "stale"** — stats grouped on
prompt version alone while the re-queue keys on version *and* model. Fixing
it immediately found **150 churches being reported as done** that the
re-queue considered stale.

**The re-queue could stall permanently.** Churches that are stale with
nothing re-queueable consumed a `limit` slot, updated nothing, and never
gained a `pending` artifact — so they sat at the head of the queue on every
pass. `awaiting_queue` could never reach zero, which is exactly what the
runbook says to wait for. Found by seeding a scratch Postgres.

---

## 9. 2026-07-27 (later) — instrumenting the failure, and two bugs found doing it

§8 ended with "`churches.extracted_status` already records which, and nothing
exposes it. That is the next thing to build." This is that, plus the two
defects that turned up while building it — both bigger than the reporting gap
that led to them.

### The reporting gap, closed

`/api/stats` now carries `extraction.attempts`: how extraction attempts ended,
bucketed `ok` / `no_html` / `no_text` / `error` / `transient` / `unknown` /
`other`, alongside `attempted`, `failed`, `failed_pct` and `awaiting_queue`.
Bucketed in SQL rather than returned raw, because the status strings embed
exception text (`transient:unexpected:...`) — unbounded cardinality, and the
wrong thing to put on an unauthenticated endpoint.

It also settles a quieter inaccuracy: `churches.extracted` counts
`extracted_at IS NOT NULL`, and **failures stamp that column too**. The
headline "5,463 extracted / 64.2% of website-havers" has always included
churches where nothing was extracted. `attempts.ok` is the honest number, and
the buckets sum to the headline by construction — asserted in a test, against a
real database.

### Bug 1: `no-text` was three different failures wearing one name

`_gather_text_from_r2` caught `R2Error` per key, logged a warning, and moved
on. So a church whose R2 objects were **absent**, one whose bucket was
**unreachable**, and one whose pages were genuinely **empty** all arrived at
the same branch and were marked identically. Which means the 41 failures in run
577 were unreadable *even from the Render logs* — the distinction was never
recorded anywhere.

They need opposite responses. Absent → the archive lost the page, so the church
needs re-**fetching** and re-queueing it achieves nothing. Unreachable → retry.
Empty → give up, correctly. Now: `R2NotFound` splits out from `R2Error`, the
gather counts each cause, and the status says which (`no-html:2/2`).

### Bug 2: the same code path could have deleted the backfill

The one worth writing down. `requeue` only ever puts `'ok'` artifacts back in
the queue, so `'skipped'` is terminal. Under the old code, **any** R2 read
failure led to `'skipped'`.

Rotate the R2 credentials, or catch a Cloudflare outage, and every artifact in
every batch gets permanently excluded from the corpus — silently, at three
batches a day, while `/api/stats` reports rising "extracted" counts because
failures stamp `extracted_at`. The pipeline would have looked like it was
working. Nothing in the system would have said otherwise, and there is no
recovery path short of re-fetching thousands of sites.

Unreachable-R2 is now transient: artifacts stay `pending` and the next run
retries them. Tested from both sides — an unreachable bucket writes no terminal
status at all, and a mix of absent-and-unreachable resolves to the recoverable
reading, because retrying a church whose HTML is truly gone costs one wasted
read while the reverse costs the church.

### Bug 3: the health signal was about to go permanently red

Found by reading the live endpoint rather than the code. `_run_stage` writes
`status='ok'` only when `rows_error == 0`, and `crawl_health` counted only
`'ok'` runs — so **a stage's freshness clock only advanced on a flawless
batch.** With the backfill failing on a real fraction of churches, essentially
no batch is flawless.

Measured at 17:03 UTC: `extract.last_success` was 76,643s old (21.3h) against
its 24h budget, and would have crossed it that evening. Not because anything
was wrong — the stage ran on schedule and extracted churches — but because
every recent batch had an error in it. `pipeline_ok` would then have been false
for the entire remaining backfill, including for the auto-close job below,
which is gated on it. An alarm that is always on is the same as no alarm, which
is the failure mode this whole endpoint exists to prevent.

Staleness now keys on `last_progress` — a run that finished *and* got at least
one row through. `rows_ok > 0` is load-bearing in the other direction: a stage
that runs on time and fails every single row is not working and must not read
as fresh. `last_success` is still reported, just not alerted on.

The fetch budget went 8h → 12h in the same pass (filed in §8). Every budget now
clears two cadences, since after a failure the next attempt is one cadence out
— under 2x, a single miss always alerts.

### Alert lifecycle closed

`crawl.yml` gains a `resolve` job: on a run where nothing failed, it reads
public `/api/stats` and closes any open `crawl-alert` issue **gated on
`pipeline_ok`**, not on the one stage that happened to run — a green fetch says
nothing about extract, and scheduled runs only ever exercise one stage. #19 sat
open through five green runs; an alert label nobody believes is worth about as
much as no alert.

A backend that can't answer counts as unhealthy and leaves the issue open. That
is deliberate in two directions: an unreachable backend is evidence against
closing, and under `set -e` piping a cold-start HTML 502 into `jq` would fail
the step and paint a successful crawl run red.

### Verification

`pytest -q` — **193 passed, 5 skipped** against a real Postgres (`initdb` +
migrations 0001/0003/0004 locally; 0002 is pgvector, which no query here
touches). Locally without a database it's 158 passed / 40 skipped, so 35 of
these tests only mean anything with the database CI now provides — which is the
point of #21, and why the two SQL-side rules (`partial` counts as progress,
`rows_ok > 0` does not) are tested there rather than against mocks.

New: `tests/scrapers_v2/test_extract_failures.py` (9 tests over the failure
routing — none of it was covered), `tests/test_stats_queries.py` (8 DB-gated
tests over the two new queries). `yaml.safe_load` + `bash -n` over every
workflow and every `run:` block.

### What this does *not* answer

The breakdown reports the state after Render redeploys and one extract run goes
through under the new code. Pre-existing `no-text` rows are ambiguous by
construction — they were written when the two causes shared a status — so the
call on chunk 2 has to be made from failures recorded *after* the deploy.
That's the first item in TODOS.md, with the reading of each outcome written
down so it's a lookup rather than a re-derivation.

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

**2026-07-24 delivery verification:** `pytest -q` (103 passed, 11 DB-gated skips),
`python -m evals.website_extraction.gate` (exit 0 against its own baseline, and
exit 2 with a content-hash mismatch after a simulated prompt edit — reverted),
`python -m evals.website_extraction.bootstrap --urls ... --dry-run` (5 real pages
fetched and labeled before any of them were committed to the set), `yaml.safe_load`
+ `bash -n` over every workflow and every `run:` block,
`gh api repos/.../actions/permissions/workflow` (default is `read` — hence the
manual step above). The new baseline was re-scored from cache, so the only live
LLM calls in this session were the bootstrap labeling of 5 candidate pages and the
extract+judge of the 3 that were kept.

**2026-07-24 re-verification:** `gh pr view 13` (merged), `git log` on `main` (confirmed
`c46a56f`/`ecac87b` landed alongside the merge), `gh run list --limit 50` (39 successful
runs Jul 21–24, no gaps), re-sampled `/api/churches?city=...` for NYC/Brooklyn/Chicago/
Seattle, `grep -c "^## DRAFT:\|^## Example:"` + a full listing of `golden.md` headings
against the compiled `golden.jsonl` to confirm the 11-item DRAFT backlog and its two
distinct origins (pre-existing hand templates vs. auto-bootstrapped disagreements).
