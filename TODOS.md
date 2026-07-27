# ChurchMap — Active TODOs

Rewritten 2026-07-24 (previous version was pre-Phase-A scaffolding for deleted
SQLite/`holyhub/` code — see git history if that's ever needed). Current state and
verification trail: [STATUS.md](STATUS.md).

---

## Now (this week)

- [ ] **Read the backfill failure breakdown, then decide about chunk 2.** The
      instrumentation shipped 2026-07-27 (see below); what's left is looking at
      the number once Render has redeployed and one extract run has gone
      through under the new code:

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

## Next (this month)

- [ ] **Finish the extraction backfill** — blocked on the failure-rate
      diagnosis above, not on effort. **Chunk 1 was queued 2026-07-27**
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
      (aggregate counts, prompt-version split, last successful run per stage,
      untokened). What's missing is somewhere a human actually looks: a README
      badge, a small status page, or a line on the frontend footer. A number
      nobody sees is the same as no number — that's how the July disable went
      8 days unnoticed.
- [ ] **Demand-driven fetch priority.** `churches_due_for_fetch` in
      `backend/db/repository.py` currently orders by `last_try ASC NULLS FIRST` —
      pure table order. Seed or reorder toward a top-N metro list (or actual search
      traffic once that's tracked) so coverage tracks where people look, not where
      church_ids happened to land. Brooklyn/NYC catching up this week was incidental
      (a bug fix + luck); the next demo city might not be.
- [ ] **Surface extracted data in the UI** — the remaining half of the Phase B
      payoff. The API side landed 2026-07-27: `GET /api/churches` now takes
      `language`, `worship_style` and `stance`, filtering on `extracted_tags`.
      What's missing is the frontend — filter controls wired to those params,
      and extracted tags rendered on result cards when review-derived tags are
      empty, which is most cards given near-zero organic reviews. Read
      [DESIGN.md](DESIGN.md) first; this is a UI change, so it should touch no
      API contract, auth or schema.

      Worth knowing before building the filters: a church with no extraction
      cannot match any of them, and `service_languages` is empty for most rows
      until the backfill drains. A language filter today returns very little.
      Either wait for `extraction.stale` to fall, or design the empty state to
      say "we haven't read this church's site yet" rather than implying no such
      church exists.

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
