# ChurchMap

Find your church, rated on what actually matters.

ChurchMap is a church discovery app for searching churches by city/state, viewing them on a map, and reading or leaving reviews across six fit dimensions: worship energy, community warmth, sermon depth, children's programs, theological openness, and facilities.

This repository is named `holyhub`, but the current product UI is branded as ChurchMap.

## What Is Actually Used

| Area | Used in this repo |
|------|-------------------|
| Backend | FastAPI, Uvicorn, raw `sqlite3`, Pydantic, HTTPX, Requests |
| Database | SQLite file at `holyhub.db`, migrated at container startup |
| Frontend | React 18, Vite, React Router, Leaflet, React Leaflet |
| Styling | Plain CSS in `frontend/src/index.css` |
| Auth | Google Identity Services in the browser, Google `tokeninfo` verification in FastAPI |
| Enrichment | Google Places API for photos, hours, ratings, reviews, contact info, and accessibility |
| Location | `ipapi.co` for first-visit city/state detection |
| Data pipeline | IRS Pub 78 import, OpenStreetMap scraping, reverse geocoding, fuzzy deduplication |
| Tests | pytest, 31 collected tests |
| Deployment | Fly.io for the API, Vercel config for the SPA, GitHub Actions for Fly deploys |

The root `requirements.txt` is the active Python dependency file. It is used by `Makefile` and `Dockerfile`.

`holyhub/requirements.txt` appears to be legacy. It includes `streamlit` and `sqlite3`, but the current app does not use Streamlit, and the standard-library `sqlite3` module is used directly.

## Features

- Search churches by `city` + `state`, or by `zip_code` through the API.
- See results in a list and on a Leaflet/OpenStreetMap map.
- Sort by nearest, rating, or review count.
- Filter by computed tags, language, and cultural background when data is available.
- Open an inline church detail panel from search results.
- View a full church detail page at `/church/:id`.
- Sign in with Google to submit reviews.
- Rate churches on the six fit dimensions.
- See aggregate dimension bars and computed tags once enough review data exists.
- Find similar churches using distance across the six review dimensions.
- Lazily enrich church details from Google Places when `GOOGLE_PLACES_KEY` is configured.

## Setup

Prerequisites:

- Python 3.10+
- Node 18+
- npm

```bash
git clone https://github.com/zhou100/holyhub.git
cd holyhub

make install
make seed
```

`make seed` recreates `holyhub.db` with demo churches and reviews. The production-style database is a SQLite file committed or baked into the Docker image.

## Environment Variables

Backend:

```bash
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_PLACES_KEY=your-google-places-api-key
```

Frontend:

```bash
VITE_API_URL=http://localhost:8000
VITE_GOOGLE_CLIENT_ID=your-google-oauth-client-id
```

Notes:

- `GOOGLE_CLIENT_ID` is optional on the backend, but when set it verifies that Google ID tokens were issued for the expected client.
- `VITE_GOOGLE_CLIENT_ID` is required for the review form to show Google Sign-In.
- `GOOGLE_PLACES_KEY` is optional. Without it, enrichment endpoints return cached data if present or skip safely.

## Running Locally

```bash
# Terminal 1: backend at http://localhost:8000
make dev-backend

# Terminal 2: frontend at http://localhost:5173
make dev-frontend
```

Open [http://localhost:5173](http://localhost:5173). Try `Brooklyn, NY` if location detection does not find local results.

## Commands

```bash
make install       Create venv, install backend deps, install frontend deps
make seed          Recreate holyhub.db with demo data
make dev-backend   Start FastAPI with reload on port 8000
make dev-frontend  Start the Vite dev server
make test          Run pytest against tests/
```

Frontend-only commands:

```bash
cd frontend
npm run dev
npm run build
npm run lint
npm run preview
```

Data pipeline commands:

```bash
python -m backend.scrapers.run_pipeline --source migrate
python -m backend.scrapers.run_pipeline --source osm
python -m backend.scrapers.run_pipeline --source irs --limit 500
python -m backend.scrapers.run_pipeline --source dedup --dry-run
python -m backend.scrapers.run_pipeline --all
```

Google Places batch enrichment:

```bash
python -m backend.scrapers.batch_enrich --dry-run
```

## API

```text
GET  /api/health
GET  /api/churches?city=Brooklyn&state=NY&limit=50&offset=0
GET  /api/churches?zip_code=11201&limit=50&offset=0
GET  /api/churches/{church_id}
GET  /api/churches/{church_id}/similar
POST /api/churches/{church_id}/enrich
GET  /api/reviews/{church_id}
POST /api/reviews
POST /api/auth/verify
```

`POST /api/reviews` requires an `Authorization: Bearer <google_id_token>` header. Reviews are not anonymous in the current code path; they are tied to a Google-authenticated user record and store reviewer display metadata.

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
backend/                  FastAPI app, routers, dependencies, seed script
backend/scrapers/         Migration, import, enrichment, geocoding, dedup tools
holyhub/                  SQLite database wrapper, schema, domain services
frontend/                 React + Vite app
frontend/src/pages/       Search and church detail pages
frontend/src/components/  Cards, detail panels, ratings, review form
tests/                    pytest suite
Dockerfile                Fly.io backend image
fly.toml                  Fly.io app config
frontend/vercel.json      SPA rewrite config for Vercel
```

## Deployment

The backend Docker image installs from the root `requirements.txt`, copies the repo, runs the database migration against `holyhub.db`, then starts Uvicorn:

```bash
python -m backend.scrapers.migrate holyhub.db
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

`fly.toml` configures the API as `holyhub-api` with scale-to-zero behavior. `.github/workflows/fly-deploy.yml` deploys the Fly app on pushes to `main` when `FLY_API_TOKEN` is configured.

The frontend is a Vite SPA. `frontend/vercel.json` rewrites all routes to `index.html` so `/church/:id` works on refresh.

## More Docs

- [Project overview](OVERVIEW.md)
- [Design system](DESIGN.md)
- [Project instructions](CLAUDE.md)
- [TODOs](TODOS.md)
