# Phase B — R2-backed crawl pipeline (eng review + plan)

Status: review locked. Implementation can start.
Reviewer: Claude (Opus 4.7), auto mode.
Branch base: `main` @ f76a1e2.

---

## 0. Scope

**In scope (this PR):**
1. `migrations/0004_crawl_artifacts.sql` — `raw_crawl_artifacts`, `crawl_runs`, robots.txt cache.
2. `backend/scrapers_v2/` — `fetch.py`, `extract.py`, `tag.py`, plus `r2.py`, `robots.py`, `prompts/website_v2.py`.
3. `backend/routers/admin.py` — `X-Crawl-Token`-protected endpoints: `/api/admin/crawl/fetch`, `/extract`, `/tag`, `/status`.
4. `.github/workflows/crawl.yml` — scheduled cron driving the admin endpoints.
5. Tests: unit tests for hash/key derivation, prompt schema validation, robots cache; integration test with R2 mocked via `moto` or a tmpdir filesystem adapter.
6. `requirements.txt`: add `boto3` (R2 = S3-compatible).
7. `OVERVIEW.md` + `backend/scrapers/README.md`: update to point at `scrapers_v2`.

**NOT in scope (deferred, listed so they don't drop):**
- Embedding regeneration pipeline (`website_embed.py` rewrite). Phase B+1.
- Backfill of existing `website_pages.text` into R2. One-off script after this PR lands; not coupled to deploy.
- Replacing `enrichment.py` (Google Places). Stays put.
- Cost telemetry per-run beyond row counts. Add when we feel pain.
- LLM eval harness wiring. Prompt has `parser_version` + `model` stored; eval can come later.
- Frontend changes. None.

**What already exists (reused, not rebuilt):**
- `backend/scrapers/website_extract.py` SYSTEM_PROMPT — port verbatim.
- `backend/scrapers/website_fetch.py` candidate-path logic, `_normalize_url`, trafilatura extraction, content-hash. Port the pure functions; drop the sqlite plumbing.
- `backend/db/repository.py` pattern — add a `CrawlRepository`.
- `backend/auth.py` is **not** the auth path here. Admin endpoints use a static `X-Crawl-Token` shared with GH Actions, not GSI.

---

## 1. Architecture

```
GH Actions cron (hourly/daily)
  │
  │ POST /api/admin/crawl/fetch?batch=50  (X-Crawl-Token)
  ▼
FastAPI admin router  ──► CrawlRepository ──► Postgres
  │                                              │
  │ httpx fetch (politeness, robots cache)       │ crawl_runs row (started)
  │                                              │
  ▼                                              │
R2 PUT raw_html/{church_id}/{YYYY-MM-DD}/        │
       {content_hash}.html                       │
  │                                              │
  ▼                                              ▼
raw_crawl_artifacts row  ◄──────────  crawl_runs row (finished, counts)

  ─── separately, also cron-driven ───

POST /api/admin/crawl/extract?batch=20
  │
  ▼
For each artifact with extract_status='pending':
  GET R2 object → trafilatura → LLM (OpenRouter)
  → strict JSON → store extracted fields + confidence + source snippets
  → write to churches.website_summary, churches.extracted_tags
  → mark artifact extract_status='ok'|'error:<reason>'

POST /api/admin/crawl/tag?batch=100
  │
  ▼
Deterministic rules over extracted_tags JSON → name_tags table.
```

**Why three stages, not one:**
- Fetch is I/O-bound and slow per host. Run frequently, small batches.
- Extract costs money per LLM call. Run on cadence, with budget caps.
- Tag is pure CPU/SQL. Run after extract or backfill on rule changes.
- Each stage is independently re-runnable. Idempotent on `content_hash`.

**Boring tech check:** boto3 against R2 (S3 API) — Layer 1. `httpx` already in deps. `trafilatura` already in deps. GH Actions cron — Layer 1. Zero innovation tokens spent. Good.

**Failure scenarios:**
| Stage | Failure | Mitigation |
|-------|---------|------------|
| fetch | R2 PUT fails after HTTP 200 | Retry once; on second failure, write `crawl_runs.error`, no artifact row. Next run re-fetches (no artifact = pending). |
| fetch | Site times out | Record `status_code=0, error='timeout'` in artifact metadata, no R2 object. Re-tried next cron. |
| fetch | robots disallows | Write artifact row with `status='robots-disallow'`, no R2 object, no retry. |
| extract | LLM returns invalid JSON | Catch in `_parse_json_object`, mark `extract_status='error:json'`, store raw response in `extract_error_detail` (truncated 4KB). |
| extract | OpenRouter 429/5xx | Exponential backoff: 1s, 4s, 16s, then mark `error:upstream` and move on. Next run retries. |
| extract | R2 GET fails | Mark `extract_status='error:r2'`. Next run retries. |
| tag | Rule throws | Skip that church, log, continue batch. |
| cron | GH Actions fails to dispatch | We see it in Actions UI. No silent failure — `crawl_runs` is the source of truth. |

**Blast radius:** All endpoints write-only to new tables + R2. Only existing-table write is `churches.website_summary` / `extracted_tags` / `denomination` in extract stage — same fields the v1 pipeline already wrote. `READ_ONLY=1` middleware already covers admin endpoints because they're POST.

---

## 2. Schema — `migrations/0004_crawl_artifacts.sql`

```sql
-- crawl_runs: one row per cron invocation per stage
CREATE TABLE crawl_runs (
    id              BIGSERIAL PRIMARY KEY,
    stage           TEXT NOT NULL CHECK (stage IN ('fetch', 'extract', 'tag')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error', 'partial')),
    batch_size      INT,
    rows_processed  INT NOT NULL DEFAULT 0,
    rows_ok         INT NOT NULL DEFAULT 0,
    rows_error      INT NOT NULL DEFAULT 0,
    triggered_by    TEXT,                    -- 'github-actions', 'manual', etc.
    error           TEXT,                    -- terminal error if status='error'
    metadata        JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX idx_crawl_runs_stage_started ON crawl_runs (stage, started_at DESC);

-- raw_crawl_artifacts: one row per fetched page (homepage, about, beliefs, ...)
CREATE TABLE raw_crawl_artifacts (
    id                  BIGSERIAL PRIMARY KEY,
    church_id           INT NOT NULL REFERENCES churches(church_id) ON DELETE CASCADE,
    url                 TEXT NOT NULL,
    kind                TEXT NOT NULL,          -- homepage|about|beliefs|ministries|services
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status         INT NOT NULL,
    fetch_error         TEXT,                   -- timeout|robots-disallow|page-too-large|<exc>
    robots_allowed      BOOLEAN NOT NULL DEFAULT TRUE,
    content_hash        TEXT,                   -- sha256 of cleaned text; null if no body
    r2_key              TEXT,                   -- raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html; null if no body
    bytes_raw           INT,                    -- size of HTML in R2
    bytes_text          INT,                    -- size of cleaned text
    extract_status      TEXT NOT NULL DEFAULT 'pending'
                          CHECK (extract_status IN ('pending', 'ok', 'skipped', 'error')),
    extract_error_detail TEXT,
    extracted_at        TIMESTAMPTZ,
    crawl_run_id        BIGINT REFERENCES crawl_runs(id) ON DELETE SET NULL,
    UNIQUE (church_id, url, content_hash)       -- idempotency: same URL + same content = no dup row
);
CREATE INDEX idx_artifacts_church_kind ON raw_crawl_artifacts (church_id, kind);
CREATE INDEX idx_artifacts_extract_pending ON raw_crawl_artifacts (extract_status) WHERE extract_status = 'pending';
CREATE INDEX idx_artifacts_fetched_at ON raw_crawl_artifacts (fetched_at DESC);

-- robots.txt cache: keyed by host, refreshed daily
CREATE TABLE robots_cache (
    host            TEXT PRIMARY KEY,
    body            TEXT,                       -- raw robots.txt text; '' if 404 or unreachable
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL        -- fetched_at + 24h
);

-- Track LLM extraction provenance per church (latest extraction).
-- Existing fields on churches: website_summary, extracted_tags, extracted_at, extracted_status.
-- Add prompt_version + model_version + confidence (per-field), source_snippets.
ALTER TABLE churches
    ADD COLUMN IF NOT EXISTS extracted_prompt_version TEXT,
    ADD COLUMN IF NOT EXISTS extracted_model          TEXT,
    ADD COLUMN IF NOT EXISTS extracted_confidence     JSONB,    -- {field: 0.0-1.0}
    ADD COLUMN IF NOT EXISTS extracted_source_snippets JSONB;   -- {field: "verbatim quote..."}
```

**Idempotency rule:** `(church_id, url, content_hash)` is unique. Re-fetching the same page → same content → INSERT ON CONFLICT DO NOTHING. R2 PUT with same key is also idempotent (overwrite is fine but skipped by an `head_object` check first to save bandwidth).

**Pool note:** psycopg pool already uses `prepare_threshold=None` per CLAUDE.md. No changes needed.

---

## 3. R2 — `backend/scrapers_v2/r2.py`

```python
# Thin boto3 wrapper. Single client, lazy.
# Env: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
# Endpoint: https://{account_id}.r2.cloudflarestorage.com
```

API surface:
- `R2Client.put_html(church_id, content_hash, html: bytes, fetched_at: datetime) -> str` returns r2_key.
- `R2Client.get_html(r2_key: str) -> bytes`
- `R2Client.head(r2_key: str) -> bool` — for idempotency.
- Configure boto3 with `signature_version='s3v4'`, no region (R2 ignores it but accepts `auto`).

Key format: `raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html` — matches the locked spec. Date is fetch date (UTC).

---

## 4. Fetch — `backend/scrapers_v2/fetch.py`

Port from `website_fetch.py`, replacing sqlite with psycopg + R2:

```python
def fetch_batch(repo: CrawlRepository, r2: R2Client, batch_size: int, run_id: int) -> FetchSummary:
    targets = repo.churches_due_for_fetch(limit=batch_size, fresh_days=30)
    # ... per-domain politeness via PER_DOMAIN_DELAY_S=2.0
    for church_id, website in targets:
        try:
            results = fetch_church(client, repo, r2, church_id, website, run_id)
            repo.record_artifacts(results)
        except Exception as e:
            repo.mark_run_error(run_id, church_id, e)
```

**Robots cache:** `repo.get_robots(host)` → if expired/missing, fetch + parse + insert/update `robots_cache`. 24h TTL. Failure to fetch robots → cache empty body (treat as fully allowed, per existing behavior).

**Retry/backoff (fetch HTTP):** httpx already does redirects. On `TimeoutException` or 5xx: one retry after 5s. Two failures → record artifact with status_code=0, error, no R2 object.

**Freshness gate:** skip churches where `MAX(fetched_at)` for this church is < FRESH_DAYS old AND has a successful homepage artifact. Same as v1.

---

## 5. Extract — `backend/scrapers_v2/extract.py`

Strict additions over v1 prompt:

1. **Per-field confidence (0.0-1.0):** prompt asks model to emit `_confidence` map. Stored in `churches.extracted_confidence`.
2. **Source snippets:** prompt asks for `_source_snippets` map: `{denomination: "<verbatim phrase from text>"}`. Stored in `churches.extracted_source_snippets`. Useful for debugging hallucinations and surfacing in UI later.
3. **Parser/model versioning:** `PROMPT_VERSION = "2026-05-08.v3"` (new), `MODEL = "google/gemini-2.5-flash"`. Both written to `churches.extracted_prompt_version` and `churches.extracted_model`.

**Schema validation (strict JSON):** keep `response_format={"type": "json_object"}`. Add `_validate_extract(obj)` that asserts required keys present + types. On failure → `ExtractionError("schema:<reason>")` → `extract_status='error'` with detail.

**Backoff:** OpenRouter 429/5xx → 1s, 4s, 16s, then give up. `httpx.HTTPStatusError` retryable codes only. Non-retryable (auth, bad request) fail immediately.

**Ports the prompt verbatim** from `backend/scrapers/website_extract.py` lines 51-82. New addition appended:

```
ALSO RETURN:
  "_confidence": { "<field_name>": 0.0-1.0, ... },
  "_source_snippets": { "<field_name>": "<verbatim phrase from input text, <=160 chars>", ... }

Rules for _confidence and _source_snippets:
- Include only fields where you produced a non-null/non-empty value.
- _source_snippets values must be SUBSTRINGS of the input text. If you cannot produce a verbatim substring, omit the field.
- _confidence is your model's calibrated belief that the field is correct. Use 0.9+ only when the source text is unambiguous.
```

`gather_text` becomes: read all `raw_crawl_artifacts` rows for `church_id` with `http_status=200 AND extract_status='pending'`, fetch HTML from R2, run trafilatura per page, concat in same kind-priority order as v1, truncate to MAX_INPUT_CHARS=18,000.

---

## 6. Tag — `backend/scrapers_v2/tag.py`

Pure SQL/JSON, deterministic. Read `churches.extracted_tags`. Run rules:
- Mandarin/Cantonese/Korean/Spanish detection from `service_languages` → write to `name_tags` table.
- Denomination-family rollup (Baptist, Reformed, Catholic, etc.).

Port from `backend/scrapers/name_tags.py`. No LLM. Idempotent: clear and re-write tags for that church.

---

## 7. Admin router — `backend/routers/admin.py`

```python
from fastapi import APIRouter, Depends, Header, HTTPException
import os, secrets

router = APIRouter(prefix="/api/admin/crawl", tags=["admin"])

def require_crawl_token(x_crawl_token: str = Header(...)):
    expected = os.environ.get("CRAWL_TOKEN", "")
    if not expected or not secrets.compare_digest(x_crawl_token, expected):
        raise HTTPException(403, "invalid crawl token")

@router.post("/fetch", dependencies=[Depends(require_crawl_token)])
async def crawl_fetch(batch: int = 50): ...

@router.post("/extract", dependencies=[Depends(require_crawl_token)])
async def crawl_extract(batch: int = 20): ...

@router.post("/tag", dependencies=[Depends(require_crawl_token)])
async def crawl_tag(batch: int = 100): ...

@router.get("/status", dependencies=[Depends(require_crawl_token)])
async def crawl_status(): ...  # last 10 crawl_runs across stages
```

`secrets.compare_digest` to avoid timing side-channel. `CRAWL_TOKEN` is a Render env var (32+ random hex chars), mirrored as a GH Actions secret.

**Async vs sync:** fetch + extract are I/O-heavy and call `requests`/`httpx` synchronously in v1. Wrap in `asyncio.to_thread` to avoid blocking the event loop, or use `httpx.AsyncClient`. Recommend the latter — already an async stack. Keep boto3 calls inside `asyncio.to_thread` (boto3 is sync).

---

## 8. GH Actions — `.github/workflows/crawl.yml`

```yaml
name: crawl
on:
  schedule:
    - cron: '17 */4 * * *'   # fetch every 4h, offset to avoid the top of the hour
    - cron: '37 6,18 * * *'  # extract twice daily
  workflow_dispatch:
    inputs:
      stage: { type: choice, options: [fetch, extract, tag, all] }

jobs:
  fetch:
    if: github.event.schedule == '17 */4 * * *' || github.event.inputs.stage == 'fetch' || github.event.inputs.stage == 'all'
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -fsS -X POST \
            -H "X-Crawl-Token: ${{ secrets.CRAWL_TOKEN }}" \
            "${{ secrets.BACKEND_URL }}/api/admin/crawl/fetch?batch=50"
  extract:
    if: github.event.schedule == '37 6,18 * * *' || github.event.inputs.stage == 'extract' || github.event.inputs.stage == 'all'
    needs: [fetch]
    if: always()
    # ... same shape
```

`BACKEND_URL` and `CRAWL_TOKEN` in GH secrets. `-fsS` so non-2xx fails the workflow loudly.

---

## 9. Tests

`tests/scrapers_v2/`:
- `test_r2_key.py` — key derivation, hash stability.
- `test_robots_cache.py` — TTL, miss → fetch → hit, malformed bodies.
- `test_extract_schema.py` — happy path, missing field, bad type, wrong enum value, non-substring source snippet.
- `test_fetch_idempotency.py` — same URL + same content_hash → no duplicate artifact row.
- `test_admin_auth.py` — wrong token → 403, no token → 422, correct token → 200.
- `test_backoff.py` — mock OpenRouter 429 → retries → eventual success / give-up.

R2 is mocked via `moto` (`@mock_aws`) — already S3-compatible.

**Coverage diagram:**
```
[+] backend/scrapers_v2/fetch.py
    ├── fetch_church()
    │   ├── [TEST] homepage 200, R2 PUT, artifact row written
    │   ├── [TEST] homepage 404, no R2, artifact with http_status=404
    │   ├── [TEST] robots disallow → no fetch, artifact w/ robots_allowed=False
    │   ├── [TEST] timeout → retry → success
    │   ├── [TEST] timeout → retry → give up
    │   └── [TEST] same content_hash twice → idempotent
[+] backend/scrapers_v2/extract.py
    ├── extract_for_artifact()
    │   ├── [TEST] valid JSON → fields persisted + confidence + snippets
    │   ├── [TEST] invalid JSON → error status, raw response stored
    │   ├── [TEST] schema violation → error status
    │   ├── [TEST] OpenRouter 429 → backoff → success
    │   └── [TEST] non-substring snippet → field dropped, not error
[+] backend/routers/admin.py
    └── [TEST] auth: missing/wrong/correct token
COVERAGE: 14/14 paths
```

---

## 10. Open questions (genuine; need your call)

These are not blockers — pick a default and I'll proceed if no answer.

1. **Robots cache scope:** per-host or per-host+user-agent? Default: per-host. We only crawl as one UA.
2. **Re-fetch on prompt version bump:** when `PROMPT_VERSION` changes, do we re-extract all artifacts? Default: yes, lazily — extract stage marks artifacts whose church's `extracted_prompt_version != current` as pending. Cost: ~$5 to re-extract all churches at Flash prices.
3. **Crawl token rotation cadence:** any compliance need? Default: rotate annually or on suspected leak, no automation.
4. **HTML retention in R2:** keep forever or TTL-90-days? Default: forever. R2 is cheap ($0.015/GB-mo). 30k churches × 4 pages × 100KB = 12GB ≈ $0.18/mo. Don't bother with lifecycle rules now.
5. **Cron cadence:** every 4h fetch is aggressive given FRESH_DAYS=30. Default: keep 4h but the freshness gate will make most invocations no-ops; this gives quick recovery if backend was down. Alternative: daily.

---

## Worktree parallelization

Sequential. Migration → repo layer → fetch → extract → tag → admin router → workflow → tests. Each builds on the previous. No parallel lanes worth the merge tax for ~600 LOC.

## Failure modes — critical gaps

None flagged. Every codepath in the diagram has a test or explicit error handling. The one residual risk: GH Actions workflow secret leaking the crawl token. Mitigation: token only grants write to `raw_crawl_artifacts` + r/w on R2 bucket; can't read users, reviews, or modify churches beyond extracted_* fields. Worst case = poisoned scrape data, fixable by re-running with fixed prompt.

## Verdict

CLEAR — ready to implement. Start with `migrations/0004_crawl_artifacts.sql` and the `CrawlRepository` skeleton; that unlocks fetch, which unlocks extract, which unlocks tag. Workflow + admin router can land in the same PR or the one after; recommend same PR so the cron starts churning the moment Render picks up the deploy.

---
