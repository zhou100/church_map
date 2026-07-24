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
- [ ] **Prompt v4: fix `service_languages`.** The eval now measures this at
      **0.588**, the worst field by a wide margin, and the cause is one line of v3:
      "Empty list if unclear." Production returns `[]` for any page that doesn't
      name a language in so many words — which is most of them — so a
      language filter would find almost nothing. The goldens encode the rule the
      product needs (the page's own language is evidence for the primary service
      language). Changing the prompt means a `PROMPT_VERSION` bump plus a
      regenerated cache/baseline; the CI gate enforces that.
- [ ] **Prompt v4: denomination in the page's language.** KCPC (a Korean-language
      site) extracts `denomination: "장로교회"` — correct, and useless for any
      English-facing filter or facet. v3 never says what language the *output*
      should be in. Same v4 batch as above.

## Next (this month)

- [ ] **`/api/admin/crawl/status`-lite as a public `/api/stats` endpoint** — total
      churches, % with websites, % extracted, last successful crawl run per stage.
      No token-gating needed if it's just aggregate counts, not per-church detail.
      Surface it somewhere visible (README badge, tiny status page). This is the
      difference between "trust me, there's a pipeline" and a live number — and it
      would have caught the July workflow disable days earlier.
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
      normalized strings exactly, so "Kreyol" ≠ "Haitian Kreyol" (Saint Francis of
      Assisi) even though both name the same language and both appear on the page.
      `denomination` already does substring-either-direction and would have caught
      it. Left alone deliberately during the 2026-07-24 golden-set pass — it moves
      baseline numbers, so it wants its own commit and its own re-baseline. Worth
      doing before the gate's threshold gets tightened below 0.10, since a
      paraphrase shouldn't read as a regression.
- [ ] **Grow the golden set past 18.** Deterministic per-field precision on n=17-18
      moves in ~0.06 steps, which is most of the way to the 0.10 regression
      threshold — one example flipping looks like a real regression. `bootstrap.py`
      makes this cheap (`--city <X> --state <Y> --n 10`, review only the DRAFTs).
      Aim for 30+, weighted toward cities that are actually crawled.
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
