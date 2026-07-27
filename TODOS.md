# ChurchMap — Active TODOs

Rewritten 2026-07-24 (previous version was pre-Phase-A scaffolding for deleted
SQLite/`holyhub/` code — see git history if that's ever needed). Current state and
verification trail: [STATUS.md](STATUS.md).

---

## Now (this week)

- [ ] **Diagnose the 55% backfill extraction failure — blocks everything else
      about the backfill.** The first re-extraction batch (run 577, 2026-07-27
      10:37) came back `rows_processed: 75, rows_ok: 34, rows_error: 41`. The
      batch immediately before it, on normal freshly-fetched work, was
      `50/50/0`. So re-extraction fails far more than new extraction, and at
      ~34/run x 3 runs/day the backfill is back to ~53 days — the cadence
      increase in #22 is cancelled out by the error rate.

      **This may be worse than slow.** `extract_for_church` has three failure
      paths and they are not equivalent:

      | failure | artifacts become | consequence |
      |---|---|---|
      | `no-text` (nothing readable in R2) | `skipped` | **permanently excluded** — `requeue` only touches `ok` artifacts |
      | `ExtractionError` | `error` | same |
      | transient (LLM/network) | stays `pending` | retried next run, self-healing |

      If those 41 are `no-text`, the premise of the backfill is wrong: the R2
      archive does not actually hold readable HTML for older artifacts, and
      those churches need re-*fetching*, not re-extracting. It would also fail
      silently — `stale_churches` plateaus while `awaiting_queue` marches to
      zero, which looks exactly like completion.

      `churches.extracted_status` already records which (`no-text`,
      `error:*`, `transient:*`). Nothing exposes it. Either read the Render
      logs, or add the breakdown to `/api/stats` (one `GROUP BY` on an
      existing column) so the answer is permanent rather than one-off.

      **Do not queue backfill chunk 2 until this is understood.** If over half
      of each batch fails permanently, more queueing spends money and marks
      more artifacts unrecoverable.

- [ ] **Loosen the fetch staleness budget, 8h -> 12h.** `crawl.stages.fetch`
      allows 8h against a 4h cron, so a *single* failed run always trips
      `pipeline_ok` — the next attempt is 4h out, and age passes 8h before
      recovery is even possible. Observed exactly that on 2026-07-27: one
      transient failure at 04:04 left `pipeline_ok: false` for hours while
      nothing was actually wrong. 12h (three cadences) tolerates one failure
      and still catches a real outage within half a day.

- [ ] **Auto-close the `crawl-alert` issue on a green run.** The alert job
      files/comments but never closes, so the issue lingers as stale noise
      after recovery (#19 sat open through five green runs). `/api/stats` is
      public and needs no token — a step can check `pipeline_ok` after a
      successful run and close any open `crawl-alert` issue, gated on the
      whole pipeline being healthy rather than just the stage that ran.

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
      pipeline and falls per chunk. **Chunk, don't dump** —
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
