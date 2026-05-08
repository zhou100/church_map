# ChurchMap — Project Overview

## What is ChurchMap?

ChurchMap is a church discovery platform that helps people find a church that actually fits them, not just the nearest one but the *right* one. Instead of relying on generic star ratings or outdated directories, ChurchMap surfaces what matters to churchgoers: worship energy, community warmth, sermon depth, children's programs, theological stance, and facilities.

**Live:** [churchmap.vercel.app](https://churchmap.vercel.app)

---

## The Problem

Finding a new church is notoriously hard. Google Maps shows you a star rating and hours. Church websites are marketing material. Word-of-mouth only works if you know people. There's no Yelp for churches, and generic restaurant-style reviews don't capture what people actually want to know before walking through the door on a Sunday.

---

## What It Does

- **Search by city/state** — auto-detects your location via IP geolocation on first visit
- **Map + list view** — Google Maps-style: clicking a card flies the map to that church and opens an inline detail panel without leaving the page
- **6-dimension ratings** — Worship Energy, Community Warmth, Sermon Depth, Children's Programs, Theological Stance, Facilities
- **Smart tags** — derived from aggregate dimension scores (e.g., "Vibrant worship", "Deep sermons", "Progressive")
- **Photos, hours, and contact info** — enriched from Google Places for ~5,400 churches
- **Similar churches** — Euclidean-distance matching on dimension ratings to surface churches that feel alike
- **Google Sign-In** — authenticated reviews tied to real Google accounts
- **Filter + sort** — by distance, rating, review count, denomination, language, cultural background

---

## Data Pipeline

| Stage | Source | Scale |
|-------|--------|-------|
| Church roster | IRS 990 tax exemption database + OpenStreetMap | ~134k US churches |
| Deduplication | Name + address fuzzy match | ~134k unique |
| Geocoding | Nominatim (OSM) | Lat/lon for ~134k entries |
| Enrichment | Google Places API (Text Search + Place Details) | ~5,400 enriched ($194 one-time) |
| Storage | Supabase Postgres (transaction pooler) | ~80 MB live |

The Phase B pipeline (under construction, see `backend/scrapers/README.md`) will add:
- **Raw HTML capture** to Cloudflare R2 (object key + content_hash in Postgres)
- **LLM extraction** of worship style, languages, programs, theological stance from church websites
- **Deterministic tagging** from extracted attributes into product-facing tags
- Execution via GitHub Actions cron, not in-request

---

## System Design

### Architecture (after Phase A migration)

```
Browser (Vercel)          Backend (Render)          Database (Supabase)
──────────────────        ──────────────────        ─────────────────────
React + Leaflet   ──────► FastAPI 3.11      ──────► Postgres + pgvector
Vite / SPA                Starter $7/mo             Transaction pooler :6543
                          Docker, no sleep          ~80 MB

Google GSI ──────────────► /api/auth/verify
                           (tokeninfo verification on every protected request)
```

The full Phase A architecture lives in [`~/.gstack/projects/zhou100-holyhub/zhou100-backend_migration-eng-review-test-plan-20260507.md`](.gstack/projects/zhou100-holyhub/) (locked-in plan v2 after `/plan-eng-review` + `/codex` review).

### Why Postgres + Render?

The Phase A migration (May 2026) replaced a SQLite-baked-in-image setup running on Fly.io. The forced moves:

- **Fly's two machines couldn't share writes.** A review submitted to machine A wasn't visible on machine B until the next deploy. Acceptable for a demo, broken for real use.
- **SQLite-in-image meant no out-of-band data updates.** Every enrichment batch needed a `fly deploy` to propagate. Migrations were tied to Docker image rebuilds.

Why these specific choices:

| Concern | Choice | Why |
|---------|--------|-----|
| Frontend | **Vercel** | Already worked. Zero-config SPA, GitHub auto-deploy, global CDN, free tier. |
| Backend | **Render Starter $7/mo** | No cold-start sleep (free tier sleeps after 15 min and breaks GSI sign-in). Real Docker. |
| Database | **Supabase Postgres** | Free tier covers current size + headroom. Transaction pooler on port 6543 stops connection exhaustion under FastAPI gunicorn workers. |
| Vector search | **pgvector** | One extension, no separate vector DB. The `church_embeddings` BLOBs were already typed-vector-shaped. |
| ORM | **None** | psycopg 3 async + raw SQL, matching the existing ethos. ChurchRepository / ReviewRepository / UserRepository wrap the SQL; no SQLAlchemy. |

### Why FastAPI?

- Native async, fits psycopg 3's `AsyncConnectionPool` cleanly
- Automatic OpenAPI docs at `/docs`
- Thin, no ORM overhead, query-shape stays explicit
- Python ecosystem for the upcoming Phase B scraping/enrichment pipeline

---

## Auth Design

Google Sign-In uses the GSI (Google Identity Services) library directly in the browser. The ID token returned by Google is sent to the backend, which verifies it against Google's `tokeninfo` endpoint, no JWT library, no session store, no cookies. The token is re-verified on every protected request (review submission).

The verification logic is consolidated in [`backend/auth.py`](backend/auth.py) so both `/auth/verify` and `/reviews` use the same path. (Pre-Phase A, this was duplicated in two routers and had drifted slightly.)

```
Browser                    Backend                    Google
───────                    ───────                    ──────
[Sign In with Google] ───► POST /api/auth/verify ──► tokeninfo?id_token=...
                           ◄── { user_id, name }  ◄── { sub, email, name }
Store token in localStorage
[Submit Review] ──────────► POST /api/reviews
                            Authorization: Bearer <id_token>
```

---

## Value Proposition

**For churchgoers:** The only platform that rates churches on dimensions that actually matter for fit, not "good service" or star rating.

**For churches:** Honest feedback across six dimensions surfaces specific strengths and growth areas that generic reviews can't.

**For the market:** No direct competitor. Google Maps and Yelp treat churches like restaurants. ChurchMap is purpose-built for the discovery problem specific to faith communities.

---

## Numbers

- **~134k** US churches in the database
- **~5,400** enriched with Google Photos, hours, contact info, and editorial summaries
- **6** rating dimensions per review
- **$194** total data enrichment cost (one-time Google Places API spend)
- **~$7/month** infrastructure cost (Render Starter; Vercel + Supabase + Cloudflare on free tiers)
- **< 500ms** typical API response time on warm path

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, React Router, Leaflet (maps) |
| Styling | CSS custom properties, Fraunces (serif) + Plus Jakarta Sans |
| Backend | FastAPI 3.11 (async), psycopg 3 + AsyncConnectionPool |
| Database | Supabase Postgres + pgvector, transaction pooler (:6543) |
| Auth | Google Identity Services (GSI) + tokeninfo verification |
| Data enrichment | Google Places API (Text Search + Place Details) |
| Data sources | IRS 990 database, OpenStreetMap |
| Hosting | Vercel (frontend) + Render Web Service Starter (backend) |
| Deploy | GitHub → Vercel auto-deploy; Render auto-deploy from `main` via `render.yaml` |
| Migrations | Numbered `migrations/*.sql` + `backend/db/migrate.py` runner |
