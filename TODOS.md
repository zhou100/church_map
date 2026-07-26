# ChurchMap — Active TODOs

Rewritten 2026-07-24 (previous version was pre-Phase-A scaffolding for deleted
SQLite/`holyhub/` code — see git history if that's ever needed). Current state and
verification trail: [STATUS.md](STATUS.md).

---

## Now (this week)

- [ ] **Confirm Actions can write.** The repo's default workflow permission is
      `read` (`gh api repos/zhou100/church_map/actions/permissions/workflow`).
      The new `alert` job in `crawl.yml` needs `issues: write` and `keepalive.yml`
      needs `contents: write` + `actions: write`; both request it explicitly, but
      if either 403s, flip Settings → Actions → General → Workflow permissions to
      "Read and write". Verify by running `keepalive` via `workflow_dispatch` with
      `force_commit: false` — it should re-check workflow states and no-op.
- [ ] **Run the extraction backfill.** The mechanism is built and tested
      (`POST /api/admin/crawl/requeue`, `X-Crawl-Token`); what remains is running
      it, which costs money and so is a deliberate call, not something a cron
      should start on its own. Every church extracted before 2026-07-26 holds
      v3-era data — empty `service_languages`, Korean/Russian denomination and
      program strings — because the extract stage selects on `extract_status`,
      never on prompt version or model. Runbook:

      ```bash
      # 1. size it — dry_run is the default, nothing is written.
      #    `GET /api/stats` reports the same number as extraction.stale.
      curl -sX POST -H "X-Crawl-Token: $CRAWL_TOKEN" \
        "$BACKEND/api/admin/crawl/requeue?dry_run=true"

      # 2. queue a first pass and let the normal extract cron drain it
      curl -sX POST -H "X-Crawl-Token: $CRAWL_TOKEN" \
        "$BACKEND/api/admin/crawl/requeue?dry_run=false&limit=200"

      # 3. repeat until awaiting_queue_after is 0, watching /api/stats
      ```

      `stale_churches` is the size of the whole job and only falls as churches
      are actually re-extracted; `awaiting_queue` is what's left to hand to the
      pipeline and falls per pass. Extraction runs twice daily at 50/batch, so
      200 queued churches take ~2 days to drain — start small and check the
      output before scaling the limit. **Search/filter on `extracted_tags` is
      worth much less until this finishes** — the fix is in the prompt, not yet
      in the data.
- [ ] **Watch prose quality after the flash-lite switch.** The model moved to
      `gemini-2.5-flash-lite` on 2026-07-26. Measured over two runs of the golden
      set: deterministic fields improved (+0.023 mean; `theological_stance`
      0.818 → 0.909), but judged prose fields dropped a reproducible −0.044 mean
      — `programs`, `statement_of_faith`, `worship_style_detail` and
      `theology_summary` each lose one example in *both* runs, with the judge
      citing incompleteness. No single field crosses the gate's 0.15 band, so
      this is a real-but-small tradeoff, not a regression: better structured data
      (what search filters on) for slightly thinner summaries (what users read on
      detail pages). Revisit if detail pages start looking sparse; reverting is a
      one-line `MODEL` change plus a re-baseline.

## Next (this month)

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
- [ ] **Search/filter on `extracted_tags`.** This is the actual product payoff of
      the whole Phase B crawl and it's currently unused downstream: `list_churches`
      still filters/ranks on review-derived tags only, and with near-zero organic
      reviews most of the 134k churches show empty dimension bars. Add
      language/worship-style/vibe filters backed by `extracted_tags`, and show
      extracted tags on result cards when review tags are empty. Coverage in
      NYC/Brooklyn is already real (see STATUS.md §5) — search just doesn't use it
      yet.

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
