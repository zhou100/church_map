# ChurchMap

Find your church, rated on what actually matters.

ChurchMap is a church discovery app for searching churches by city/state, viewing them on a map, and reading or leaving reviews across six fit dimensions: worship energy, community warmth, sermon depth, children's programs, theological openness, and facilities.

The repo is named `church_map` (formerly `holyhub`); the product UI is branded as ChurchMap.

## What Is Actually Used

| Area | Used in this repo |
|------|-------------------|
| Backend | FastAPI (async), Uvicorn, psycopg 3 + AsyncConnectionPool, Pydantic, HTTPX |
| Database | Supabase Postgres + pgvector, transaction pooler on port 6543 |
| Frontend | React 18, Vite, React Router, Leaflet, React Leaflet |
| Styling | Plain CSS in `frontend/src/index.css`, Fraunces (serif) + Plus Jakarta Sans |
| Auth | Google Identity Services in the browser, Google `tokeninfo` verification in FastAPI |
| Enrichment | Google Places API (lazy, capped at 10,800 calls/month) |
| Location | `ipapi.co` for first-visit city/state detection |
| Hosting | Vercel (frontend) + Render Web Service Starter (backend) |
| Migrations | Numbered `migrations/*.sql` + `backend/db/migrate.py` runner |
| Tests | pytest (17 active, parity tests gated on `DATABASE_URL`) |

## Features

- Search churches by `city` + `state`, or by `zip_code` through the API
- See results in a list and on a Leaflet/OpenStreetMap map
- Sort by nearest, rating, or review count
- Filter by computed tags, language, and cultural background when data is available
- Open an inline church detail panel from search results
- View a full church detail page at `/church/:id`
- Sign in with Google to submit reviews
- Rate churches on the six fit dimensions
- See aggregate dimension bars and computed tags once enough review data exists
- Find similar churches using Euclidean distance across the six review dimensions
- Lazily enrich church details from Google Places when `GOOGLE_PLACES_KEY` is configured

## Local Setup

Prerequisites:

- Python 3.11+
- Node 18+
- npm
- A Supabase Postgres URL (free tier is fine for local dev). See [the Phase A migration plan](.gstack/projects/zhou100-holyhub/zhou100-backend_migration-eng-review-test-plan-20260507.md) for provisioning details.

```bash
git clone https://github.com/zhou100/church_map.git
cd church_map

# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

Set environment variables (see next section), then apply schema migrations:

```bash
export DATABASE_URL='postgresql://postgres.xxx:PWD@aws-0-...:6543/postgres'
python -m backend.db.migrate
# applies migrations/0001_initial.sql, 0002_pgvector.sql, 0003_indexes.sql
```

The data load is a one-shot from a SQLite snapshot (used during the Phase A cutover; for fresh local dev you start with an empty schema and seed via the API).

## Environment Variables

Backend:

```bash
DATABASE_URL=postgresql://postgres.xxx:PWD@aws-0-us-west-1.pooler.supabase.com:6543/postgres
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_PLACES_KEY=your-google-places-api-key
ENV=development                  # set to "production" on Render
READ_ONLY=0                      # flip to 1 during cutover windows
DB_POOL_MAX=10                   # psycopg pool max size
```

Frontend (`.env.local` or Vercel project env):

```bash
VITE_API_URL=http://localhost:8000
VITE_GOOGLE_CLIENT_ID=your-google-oauth-client-id
```

Notes:

- `DATABASE_URL` must use the **transaction pooler port (6543)**, not the direct port (5432). Direct exhausts the 60-conn limit under FastAPI workers.
- `GOOGLE_CLIENT_ID` is optional on the backend, but when set it verifies that Google ID tokens were issued for the expected client.
- `VITE_GOOGLE_CLIENT_ID` is required for the review form to show Google Sign-In.
- `GOOGLE_PLACES_KEY` is optional. Without it, enrichment endpoints return cached data if present or skip safely.

## Running Locally

```bash
# Terminal 1: backend at http://localhost:8000
uvicorn backend.main:app --reload

# Terminal 2: frontend at http://localhost:5173
cd frontend && npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Try `Brooklyn, NY` if location detection does not find local results.

## Tests

```bash
pytest -q                                    # unit + static checks (17 active)
DATABASE_URL=... pytest tests/test_parity.py # endpoint parity against Postgres
```

`tests/test_no_sqlite_in_routes.py` is a CI grep that fails if anything reintroduces `sqlite3.connect`, `?` placeholders, or `.lastrowid` into runtime route code.

### Crawl reliability and rollout

The [October 14 failed fetch job](https://github.com/zhou100/church_map/actions/runs/38630161317/job/116079431356)
started at 20:13 UTC and hit curl's 600-second limit at 20:23 with zero response
bytes. This establishes a request timeout, **not its backend root cause**. The
old 50-church serial request, end-of-batch commit, synchronous storage calls and
success counters provided several independent ways to lose or hide progress.
Production impact and the existence/size of any stranded queue remain unverified.

Fetch now defaults to 5 churches (maximum 25), with a 240-second loop budget,
45 seconds per church, a 300-second runner limit, and a 330-second request budget
covering claim and finalization. Database transactions use LOCAL 10-second statement
and 3-second lock timeouts; error cleanup gets a separate 10-second limit. A timed-out church rolls
back; earlier churches and their run counters are already committed. A failed
church gets an attempt record and the usual 48-hour backoff. Unstarted targets
remain due for a later request. Scheduled Actions makes up to ten sequential
5-church requests, preserving the nominal 50/run capacity, and stops on an empty
selection. Manual dispatch makes one request. No new worker is required.

Fetch uses a 540-second database lease, committed before network work, to reject
overlap with HTTP 409. An optional `Idempotency-Key` (1–128 characters) identifies
one invocation: the same key replays its counters without starting more work.
A running replay is HTTP 202; a failed/expired replay is HTTP 500. Use a new key
for a deliberate new attempt. Actions uses the run id plus pass number and also
checks the JSON status, so HTTP success alone does not imply completed work.
The lease is longer than the runner limit; after a process dies, a later claim
reconciles its expired run without erasing committed counters.

Fetch `rows_ok` counts churches with at least one usable HTML page verified in R2.
`rows_error` counts churches with no usable pages and a failure; `rows_skipped`
counts churches excluded by robots. `pages_ok/error/skipped` expose optional-page
failures, and `budget_exhausted`/`targets_remaining` expose incomplete batches.
Any page error or exhausted budget makes a run partial. `/api/admin/crawl/status`
includes committed counters, heartbeat/progress timestamps and metadata while
the run is active. A hard process kill can leave it running until lease expiry.

R2 uses 3-second connect and 10-second read socket timeouts and at most two total
SDK attempts. Fetch runs these synchronous SDK operations in a thread so they
cannot block async cancellation. Cancellation cannot kill an already-running
SDK thread: an idempotent upload may finish without a DB reference, and a later
fetch safely verifies/reuses the object. Socket limits do not establish a hard
wall-clock bound for DNS or a peer that keeps trickling bytes.

Extract selection, requeue eligibility and stats share one consumable predicate:
HTTP 200, nonempty R2 key, no fetch error, robots allowed. New failed fetches are
skipped rather than pending; historical invalid pending rows no longer block
requeue. Stats counts them as `crawl.queue.invalid_pending`, and extract reports
`state=degraded` until those historical rows are investigated separately.
`state=idle` requires both an empty consumable queue and a recent clean check-in;
backlog with overdue progress is `stalled`. `pipeline_ok` gates alert resolution
and the public status display; a green Actions run alone is not full health.
Tag progress uses committed processed rows because even unmatched church names
advance its watermark; fetch and extract require successful content work.

Same-content refetches update verified storage references and fetch timestamps.
They retain successful extraction results and `error`/`no-text` terminal states.
Only artifacts explicitly skipped for `no-html:*` become pending when their HTML
is restored. A missing-object observation only marks an artifact terminal if its
R2 reference and fetch timestamp still match, so a concurrent extraction cannot
undo that repair even when a same-day fetch restores the same key.
Re-extracting an older model's successful result still requires the
existing explicit, bounded requeue operation. No automatic paid backfill is added.

On an approved deployment, apply migration `0006_crawl_reliability.sql` before
running the new backend. The existing container entrypoint does this. It adds
run columns, a request-key index and a small lease table; it rewrites no church or
artifact rows. Index creation runs in the migration transaction and briefly locks
`crawl_runs`. Coordinate backend deployment with the new workflow's batch size
and header. A code rollback can leave the additive schema in place; do not drop
it while new workers are live. Rolling back code also restores the old reliability
risks. Deployment, production queue cleanup, actual refetches and paid requeue
must be authorized separately; none are part of this patch's validation.
The root and frontend Vercel configs disable automatic deployment for this exact
repair branch using [Vercel's branch configuration](https://vercel.com/docs/project-configuration/git-configuration#git.deploymentenabled),
so the authorized push/PR does not request a preview deployment. Other branches
retain their existing deployment policy.

Regression tests use frozen synthetic HTML and mocked HTTP/R2. SQL tests run in
the existing CI Postgres service with the real migration runner. On Windows use
`PYTHONUTF8=1` and a private `--basetemp` if the shared pytest temp directory has
restrictive ACLs. No live origin, R2, model or production DB is needed.

## API

```text
GET  /api/health
GET  /api/stats
GET  /api/churches?city=Brooklyn&state=NY&limit=50&offset=0
GET  /api/churches?city=Brooklyn&state=NY&language=Spanish&worship_style=liturgical&stance=traditional
GET  /api/churches?zip_code=11201&limit=50&offset=0
GET  /api/churches/{church_id}
GET  /api/churches/{church_id}/similar
POST /api/churches/{church_id}/enrich
GET  /api/reviews/{church_id}
POST /api/reviews
POST /api/auth/verify
```

`GET /api/stats` reports corpus and crawl-pipeline health — how many churches
have a website, how many are extracted, which prompt version *and model* they
were extracted under, why extraction attempts ended, and how recently each
crawl stage did any work. Aggregates only, so it needs no token, and cached
in-process for 5 minutes.

Read `crawl.pipeline_ok` and `crawl.stages[*].stale`, not `crawl.runs.error`.
A stage that dies before it can write its `crawl_runs` row — a database it
can't reach, say — contributes no error at all, so an error count of zero is
not evidence of health. Age since the last *progress* is the signal an absent
row can't fake. A stage that has never made progress reports `null` and counts
as stale rather than being omitted; the crawl going quiet is the failure this
is meant to make visible (it was auto-disabled for 8 days in July 2026 and
nothing said so).

Progress, not perfection: a batch is `status='ok'` only when *zero* rows
failed, so one bad row makes it `partial`. Staleness therefore keys on
`stages[*].last_progress` (a run that finished and got at least one row
through), while `last_success` reports the last flawless run alongside it.
Keying on the strict one meant a backfill with any error rate reported its
stage as dead while it worked normally.

`extraction.attempts` breaks down why attempts ended, and it is the first thing
to read when coverage stops moving. `churches.extracted` counts
`extracted_at IS NOT NULL`, which failures stamp too — so `attempts.ok` is the
honest success count and `attempts` sums to `churches.extracted`. The buckets
that matter: `no_html` means R2 holds no page behind the artifact, so those
churches need re-**fetching** and re-queueing them achieves nothing; `no_text`
and `error` are terminal and correctly so; `transient` retries itself. Watch
`extraction.awaiting_queue` against `extraction.stale` during a backfill —
falling together is progress, `awaiting_queue` hitting zero while `stale` sits
still means the backfill has failed to a halt, which otherwise looks exactly
like completion.

`language`, `worship_style` and `stance` filter on `extracted_tags` — what the
crawler read off each church's own website, not review-derived tags. They
combine with AND. `worship_style` and `stance` are validated against the
extraction schema and return 400 on an unknown value, because zero results for
a typo is indistinguishable from "no churches like that near you". `language`
is open-ended, since the extractor emits whatever the site says.

A church with no extraction cannot match any of these filters — we don't know
its service language until something has read its site. So their usefulness
tracks extraction coverage: check `extraction.stale` on `/api/stats`.

`POST /api/reviews` requires an `Authorization: Bearer <google_id_token>` header. Reviews are tied to a Google-authenticated user record and store reviewer display metadata.

When `READ_ONLY=1`, all `POST/PUT/PATCH/DELETE` requests outside the exempt list (`/api/health`, `/api/auth/verify`) return 503 with a `Retry-After` header. Used during cutover windows to backstop the frontend banner.

## Review Dimensions

Each review can rate:

- **Worship energy**: lively to contemplative
- **Community warmth**: how welcoming the community feels
- **Sermon depth**: how substantive the teaching feels
- **Children's programs**: quality of kids ministry
- **Theological openness**: traditional to progressive
- **Facilities**: building, amenities, and accessibility signals

Tags such as `Vibrant worship`, `Deep sermons`, `Progressive`, or `Traditional` are computed from aggregate dimension scores once a church has at least 3 reviews.

## Project Structure

```text
backend/
  main.py               FastAPI app: lifespan, READ_ONLY middleware, CORS
  auth.py               Consolidated GSI tokeninfo verification
  enrichment.py         Google Places enrichment (sync psycopg)
  db/
    pool.py             AsyncConnectionPool factory (transaction pooler)
    migrate.py          Migration runner
    repository.py       ChurchRepository, ReviewRepository, UserRepository
  routers/              FastAPI route handlers
  scrapers/             FROZEN — see backend/scrapers/README.md (Phase B rewrite)

migrations/
  0001_initial.sql      Lowercase tables, JSONB, TIMESTAMPTZ
  0002_pgvector.sql     CREATE EXTENSION vector + church_embeddings.vector
  0003_indexes.sql      Indexes ported from SQLite

scripts/
  migrate_data.py       SQLite -> Postgres one-shot (used during cutover)
  docker-entrypoint.sh  Run migrations, then exec uvicorn

tests/                  pytest suite
frontend/               React + Vite SPA
Dockerfile              Render Web Service image
render.yaml             Render Blueprint
frontend/vercel.json    SPA rewrite config for Vercel
```

## Deployment

**Backend (Render):**

`render.yaml` defines a single Docker Web Service on the Starter plan. Auto-deploys from `main` on every push. Set the four `sync: false` env vars (`DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_PLACES_KEY`) in the Render dashboard.

The container entrypoint runs `python -m backend.db.migrate` before starting Uvicorn. New migrations land automatically on the next deploy.

**Frontend (Vercel):**

Vite SPA. `frontend/vercel.json` rewrites all routes to `index.html` so `/church/:id` works on refresh. Auto-deploys from `main`.

**Database (Supabase):**

Free-tier Postgres is sufficient at current scale (~80 MB). Use the transaction pooler URL (port 6543), not the direct connection (5432). pgvector ships preinstalled and is enabled by `migrations/0002_pgvector.sql`.

## More Docs

- [Project overview](OVERVIEW.md)
- [Design system](DESIGN.md)
- [Project instructions](CLAUDE.md)
- [TODOs](TODOS.md)
- Phase A migration plan: `~/.gstack/projects/zhou100-holyhub/zhou100-backend_migration-eng-review-test-plan-20260507.md`
