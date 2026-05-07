# HolyHub — Implementation TODOs
Updated by /plan-ceo-review on 2026-03-22
Design doc: ~/.gstack/projects/holyhub/yujunz-unknown-design-20260321-231618.md
CEO plan: ~/.gstack/projects/holyhub/ceo-plans/2026-03-22-holyhub-hackathon.md

## CEO Review decisions (2026-03-22)

- **Demo CTA:** Add "Try: Brooklyn, NY →" hint link below search form (Search.jsx)
- **Animated bars:** CSS `fillBar` keyframe 0→value over 600ms ease-out (DimensionBars.jsx); `prefers-reduced-motion` override
- **Gradient photos:** Deterministic HSL gradient `hue = (church.id * 37) % 360` on ChurchCard.jsx
- **Post-submit animation:** `key={reviewCount}` on DimensionBars re-triggers animation; disable submit button while `isSubmitting` to prevent race
- **Theological stance label:** Rename "Theological openness" bar → "Theological stance" with sublabel `← Traditional / Progressive →`
- **ReviewForm:** Inline at bottom of ChurchDetail (not modal)
- **Null dimension bars:** Show muted empty bar with "No ratings yet" tooltip (not "0")
- **`avg_rating = null`:** Frontend shows "—" for churches with 0 reviews (not NaN/error)
- **ChurchDetail errors:** Individual error boundaries for each parallel fetch (`Promise.all` → separate try/catch per request)

---

## Architecture decisions locked in
- **1A** — `backend/deps.py` owns `db` singleton + `get_db()` FastAPI dependency (breaks circular import)
- **2A** — All service imports changed to `from holyhub.X import X` (fixes ModuleNotFoundError at runtime)
- **3A** — `with self.db:` blocks removed from ReviewServices (prevents closing shared connection on every call)
- **4A** — `compute_tags` uses `(dims.get("key") or 0)` guard (prevents `TypeError: None > float` crash)

---

## Step 0 — Package marker + schema + database.py (15 min)

- [ ] Create `holyhub/__init__.py` (empty — makes it importable as `holyhub.database`, etc.)
- [ ] Edit `holyhub/schema.sql`: add `denomination TEXT`, `service_times TEXT` to Churches; add 6 dim columns + drop `user_id` FK + remove `username` from Reviews (see design doc for exact SQL)
- [ ] Edit `holyhub/database.py`:
  - Add `self.connection.row_factory = sqlite3.Row` inside `connect()` after `sqlite3.connect()`
  - Add `execute_insert(query, params) -> int` method returning `cursor.lastrowid`
- [ ] Delete `holyhub.db` if it exists: `rm -f holyhub.db`

## Step 1 — Adapt existing services (20 min)

- [ ] Edit `holyhub/location_services.py`:
  - Change `from database import Database` → `from holyhub.database import Database`
  - Remove dead code: `get_location_by_ip` method + `import requests` + `import sqlite3` (startup crash risk)
  - Fix Bug 2: `SELECT id, name...` → `SELECT church_id AS id, name, address, city, state, denomination, service_times`
- [ ] Edit `holyhub/review_services.py`:
  - Change imports: `from holyhub.database import Database`, `from holyhub.models import Review` (drop `auth_services` import)
  - Change constructor: `def __init__(self, db: Database)` (accept injected db, don't create own)
  - `get_reviews`: remove `with self.db:`, use named column access (`row['rating']`), return 6 dimension fields, remove Users JOIN
  - `submit_review(church_id, review)`: remove auth entirely, use `execute_insert()`, return `review_id`
- [ ] Edit `holyhub/models.py`:
  - Add 6 `Optional[float]` fields to `Review.__init__`: `worship_energy`, `community_warmth`, `sermon_depth`, `childrens_programs`, `theological_openness`, `facilities`

## Step 2 — Backend scaffold (15 min)

- [ ] Create `backend/__init__.py` (empty)
- [ ] Create `backend/routers/__init__.py` (empty)
- [ ] Create `backend/deps.py`:
  ```python
  from holyhub.database import Database
  db = Database()
  def get_db() -> Database:
      return db
  ```
- [ ] Create `backend/utils.py` — `compute_tags(dims, review_count)` with `(dims.get("key") or 0)` guard (Issue 4A)
- [ ] Create `backend/main.py` — FastAPI app, CORS `allow_origins=["http://localhost:5173"]`, startup hook that calls `deps.db.connect()`

## Step 3 — Routers (25 min)

- [ ] Create `backend/routers/churches.py`:
  - `GET /api/churches?city=&state=` — LEFT JOIN Reviews, GROUP BY church_id, compute_tags per church
  - `GET /api/churches/{id}` — same JOIN, plus `dimensions` dict embedded in response; 404 if not found
- [ ] Create `backend/routers/reviews.py`:
  - `GET /api/reviews/{church_id}` — returns `{dimensions: {...}, reviews: [...]}`
  - `POST /api/reviews` — Pydantic `ReviewCreate(BaseModel)` for validation, calls `execute_insert`, returns `{review_id: N}`

## Step 4 — Seed data (20 min)

- [ ] Create `backend/seed.py`:
  - 10 churches, **at least 5 in Brooklyn, NY** (for demo search)
  - 3-5 anonymous reviews each with realistic dimension scores
  - Run as: `python backend/seed.py` (deletes DB first, recreates from seed)

## Step 5 — React scaffold + Search page (30 min)

- [ ] Scaffold frontend: `npm create vite@latest frontend -- --template react`, install deps
- [ ] `frontend/src/pages/Search.jsx` — city/state input → `GET /api/churches` → ChurchCard list + loading state
- [ ] `frontend/src/components/ChurchCard.jsx` — name, denomination, avg_rating stars, tag chips, review count

## Step 6 — ChurchDetail page (30 min)

- [ ] `frontend/src/pages/ChurchDetail.jsx` — `Promise.all([GET /api/churches/{id}, GET /api/reviews/{id}])`, loading state until both resolve
- [ ] `frontend/src/components/DimensionBars.jsx` — 6 horizontal bars (0-5 scale, labelled)
- [ ] Individual review cards in ChurchDetail

## Step 7 — ReviewForm (15 min)

- [ ] `frontend/src/components/ReviewForm.jsx` — overall rating + comment + 6 dimension star inputs (optional per dim)
- [ ] `frontend/src/components/StarInput.jsx` — reusable 1-5 star selector
- [ ] On POST success: refetch `GET /api/reviews/{id}` + `GET /api/churches/{id}` to update bars + avg

## Step 8 — Polish (20 min)

- [ ] Empty states: "No churches found in {city}, {state}" and "No reviews yet — be the first!"
- [ ] Error toasts: failed review submission, API unreachable
- [ ] Verify `npm run dev` + `uvicorn backend.main:app --reload` both start clean from project root

---

## Tests (write alongside Step 2–4)

- [ ] Install test deps: `pip install pytest httpx`
- [ ] Create `tests/__init__.py`
- [ ] `tests/test_database.py` — execute_query returns Row, execute_insert returns lastrowid
- [ ] `tests/test_churches.py` — GET /api/churches returns list; GET /api/churches/{id} returns 200 + dims, 404 for missing
- [ ] `tests/test_reviews.py` — GET returns {dimensions, reviews}; POST returns {review_id}
- [ ] `tests/test_utils.py` — compute_tags: None inputs return [], count < 3 returns [], threshold conditions

Run with: `pytest tests/ -v` from project root

---

## Not in scope for demo

- Auth / login / signup
- IP geolocation (IPINFO cut)
- Map view
- Admin panel / moderation
- Photo uploads
- Production deployment

---

## Phase 3: Real Church Data Pipeline (next big piece)

**Goal:** Replace seeded fake data with every actual church in the US — ~380k records.

**Why:** The app is useless at scale without real church listings. Reviews mean nothing if the church isn't in the database. Multi-city support (Phase 2 backlog) depends on this.

**How to apply:** Before building this, decide whether to run it as a one-time import or a recurring sync. One-time is fine for launch; recurring keeps data fresh.

---

### Data sources (all free)

| Source | Coverage | Format | Cost |
|--------|----------|--------|------|
| OpenStreetMap Overpass API | ~200–300k US churches with lat/lon, name, denomination | GeoJSON/XML via HTTP | Free |
| IRS Tax-Exempt Orgs (Pub 78) | ~450k religious 501(c)(3)s, name + address + EIN | CSV bulk download | Free |
| Nominatim geocoder | Converts IRS addresses → lat/lon | REST API, 1 req/sec | Free |

*Google Places would give better data quality but costs ~$6,500 for 380k churches. Not worth it.*

---

### Schema changes needed

Add columns to `Churches` table:

```sql
ALTER TABLE Churches ADD COLUMN latitude  REAL;
ALTER TABLE Churches ADD COLUMN longitude REAL;
ALTER TABLE Churches ADD COLUMN website   TEXT;
ALTER TABLE Churches ADD COLUMN phone     TEXT;
ALTER TABLE Churches ADD COLUMN zip_code  TEXT;
ALTER TABLE Churches ADD COLUMN source    TEXT;   -- 'osm' | 'irs' | 'manual'
ALTER TABLE Churches ADD COLUMN external_id TEXT; -- OSM node ID or IRS EIN
```

---

### Implementation plan

**Step A — OSM scraper** (`backend/scrapers/osm_scraper.py`)

- Tile the continental US into a ~15×10 grid of bounding boxes (150 tiles)
- For each tile: query Overpass API for `amenity=place_of_worship`

  ```overpassql
  [out:json];
  node["amenity"="place_of_worship"]({south},{west},{north},{east});
  out body;
  ```

- Parse each node: `name`, `addr:street`, `addr:city`, `addr:state`, `addr:postcode`, `denomination`, `religion`, lat/lon
- Write to a staging CSV, then bulk-insert into `Churches`
- Rate limit: 1 request per 2 seconds to be polite. ~150 tiles × 2s = 5 minutes total.

**Step B — IRS importer** (`backend/scrapers/irs_importer.py`)

- Download IRS Publication 78 data from `apps.irs.gov/pub/epostcard/data-download-pub78.zip`
- Filter rows where `NTEE_CD` starts with `X` (religion) or `SUBSECTION_CODE = 03` (religious)
- Dedup against existing OSM records by name+city fuzzy match (or EIN if we later find EIN→address mapping)
- Geocode new-only records via Nominatim: `nominatim.openstreetmap.org/search?q={address}&format=json`
  - Rate limit: 1 req/sec → ~1 hour for 3,600 records in a batch; run overnight for full set
- Insert non-duplicate records into `Churches` with `source='irs'`

**Step C — Deduplication** (`backend/scrapers/dedup.py`)

- After both imports: find pairs with Levenshtein distance < 3 on name AND same city
- Keep OSM record (has lat/lon), merge in IRS EIN as `external_id`
- Flag duplicates in a `duplicates.csv` for manual review

**Step D — CLI runner** (`backend/scrapers/run_pipeline.py`)

```bash
python -m backend.scrapers.run_pipeline --source osm    # ~5 min
python -m backend.scrapers.run_pipeline --source irs    # ~hours (geocoding)
python -m backend.scrapers.run_pipeline --source dedup  # ~1 min
python -m backend.scrapers.run_pipeline --all           # full pipeline
```

**Step E — Search API update** (`backend/routers/churches.py`)

- Add `GET /api/churches/nearby?lat=&lon=&radius_km=` endpoint for map-based search
- Keep existing `?city=&state=` search working
- Add `zip_code` as optional search param

---

### Effort estimate

| Task | Human team | CC+gstack |
| ---- | ---------- | --------- |
| Schema migration | 1 hour | 5 min |
| OSM scraper + tile logic | 4 hours | 15 min |
| IRS importer + geocoder | 3 hours | 15 min |
| Deduplication script | 2 hours | 10 min |
| Search API update | 2 hours | 10 min |
| **Total** | **~12 hours** | **~55 min** |

**Priority:** P1 — blocks multi-city launch
**Depends on:** Nothing (can start now)
**Effort:** M (CC: ~1 hour)

---

## Phase 2 backlog (post-hackathon)

- [ ] **Tag filter on search results** — Client-side filter by tag chip click. `activeTag` state in Search.jsx filters the already-fetched church array. No API call needed. Effort: S (CC: ~4 min). Depends on: tags showing on cards (in scope).
- [ ] **Similar churches on ChurchDetail** — `GET /api/churches/{id}/similar` returning top 3 by cosine similarity of 6-dim vectors. Small card row at bottom of detail page. Best with real crowdsourced data (weak on 10 seeded churches). Effort: M (CC: ~8 min). Depends on: churches having dimension scores in DB.
- [ ] **Church leader profile claiming** — Church can claim listing, add official description, respond to reviews. Requires auth layer first. Phase 3+.
- [ ] **Optional auth / user profiles** — Let reviewers optionally sign in to claim their reviews. No breaking change to anonymous reviews. Effort: L (CC: ~M).
- [ ] **Multi-city support** — Search any US city. Requires real crowdsourced data, not seed data. Phase 3+.

---

## Website pipeline follow-ups (deferred from /plan-eng-review 2026-05-06)

- [ ] **Migrate to Supabase + pgvector when SQLite hurts** — Today the website pipeline + embeddings live in baked SQLite (vectors stored as BLOB in `church_embeddings`). Triggers to revisit: (a) >50k churches in DB, (b) need for filter-aware vector queries (WHERE + cosine), (c) need for cross-Fly-machine write consistency. The BLOB column maps cleanly to `vector(1536)` in pgvector — migration is mostly schema + a one-time copy. Why captured now: future-you will see "why are vectors in SQLite?" and need the WHY, not just the trigger. Depends on: real scale or feature pressure that doesn't exist yet.
- [ ] **sqlite-vec migration if staying on SQLite past 50k** — If migration to hosted DB doesn't happen but church count grows past ~50k, swap numpy in-memory matmul for sqlite-vec (`.so` extension loaded by sqlite3.enable_load_extension). Numpy matmul is fine at 5k, gets wasteful past 50k. Cost: one new native dep in Docker image. Depends on: scale or pain that doesn't exist yet.
- [ ] **Eval gating in CI for prompt versions** — Block merges that bump `PROMPT_VERSION` if golden-set per-field precision drops >10%. Prevents silent prompt regressions, which are the #1 LLM-product failure mode. Setup: GitHub Action runs `python -m evals.website_extraction.run --baseline=PRIOR_PROMPT_VERSION` and fails on regression threshold. Depends on: eval harness existing (M1 deliverable) and at least one prior prompt version baseline.

---

## Phase 2 candidates (deferred from /plan-ceo-review 2026-05-06, SELECTIVE EXPANSION)

- [ ] **Sermon transcript embeddings (Phase 2 differentiation move)** — Many churches publish sermon audio (RSS, podcasts, embedded video). Pipeline: Whisper transcribe → embed → rank by what the pastor actually preaches, not what the beliefs page says. No other church directory can do this. Effort: M (~3-5 days for 10-church v1). Cost: Whisper API ~$0.006/min audio (~$3 for 50 sermons of 10 minutes each). Risks: transcription quality varies; copyright/licensing brief needed before going broad; some churches will object — provide opt-out. Depends on: M3 of the website pipeline shipped, eval suite working, and a real signal that users want sermon-style matching (interview a few users post-launch). Trigger to revisit: after v1 ships and query logs show users asking sermon-style questions.
- [ ] **Public API + dataset publication** — `GET /api/v1/churches` rate-limited public endpoint with auth keys. Static dataset download (CSV/parquet of tags + embeddings, license TBD). Researchers, journalists, denomination orgs build on it; backlinks + SEO; dataset citations build credibility. Effort: S (~1 day for endpoint, ~0.5 day for dataset packaging + license). Risks: premature exposure when data quality is poor damages brand; abuse without rate limits. Depends on: eval suite showing >0.85 precision on high-impact fields AND >60% of churches with non-empty extractions. Trigger to revisit: when both conditions met, after M3.
