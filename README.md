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

## API

```text
GET  /api/health
GET  /api/stats
GET  /api/churches?city=Brooklyn&state=NY&limit=50&offset=0
GET  /api/churches?zip_code=11201&limit=50&offset=0
GET  /api/churches/{church_id}
GET  /api/churches/{church_id}/similar
POST /api/churches/{church_id}/enrich
GET  /api/reviews/{church_id}
POST /api/reviews
POST /api/auth/verify
```

`GET /api/stats` reports corpus and crawl-pipeline health — how many churches
have a website, how many are extracted, which prompt version they were
extracted under, and the last successful run of each crawl stage. Aggregates
only, so it needs no token, and cached in-process for 5 minutes. A stage that
has never succeeded reports `null` rather than being omitted; the crawl going
quiet is the failure this is meant to make visible (it was auto-disabled for 8
days in July 2026 and nothing said so).

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
