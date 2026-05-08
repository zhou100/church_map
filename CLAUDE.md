# CLAUDE.md — ChurchMap (holyhub)

This file provides guidance for AI assistants (Claude and others) working on this codebase. The goal is consistent, project-aware behavior — not maximum verbosity.

---

## Project Overview

ChurchMap is a church discovery platform that rates churches on dimensions that actually matter for fit (worship energy, community warmth, sermon depth, children's programs, theological stance, facilities) — not generic star ratings. Read [OVERVIEW.md](OVERVIEW.md) for the full product/system writeup. Live at churchmap.vercel.app.

The core product intent: **help people find a church that fits them**. Don't erode this with restaurant-review-style thinking or developer-facing complexity in the UI.

---

## Repository Structure

```
backend/
  main.py            FastAPI app: lifespan, READ_ONLY middleware, CORS lockdown
  auth.py            Consolidated GSI tokeninfo verification
  enrichment.py      Google Places enrichment (sync psycopg)
  db/                psycopg pool + migration runner + repository layer
  routers/           Route handlers (async)
  scrapers/          FROZEN — see backend/scrapers/README.md (Phase B rewrite)
migrations/          Numbered .sql files run by backend/db/migrate.py
scripts/             migrate_data.py (one-shot SQLite -> Postgres), entrypoint
frontend/            React + Vite + Leaflet SPA
tests/               pytest suite (parity tests gated on DATABASE_URL)
Dockerfile           Render Web Service image
render.yaml          Render Blueprint
DESIGN.md            Design system — read before any UI change
OVERVIEW.md          Product + architecture writeup
TODOS.md             Active work list
```

The `holyhub/` directory was removed in Phase A. The `backend/scrapers/` directory is frozen pending Phase B rewrite — do not run those modules; they will fail on import.

---

## Tech Stack

- **Frontend:** React 18, Vite, React Router, Leaflet
- **Backend:** FastAPI 3.11 async, psycopg 3 + AsyncConnectionPool, raw SQL via repositories (no ORM)
- **Database:** Supabase Postgres + pgvector, transaction pooler on port 6543
- **Auth:** Google Identity Services (GSI) + tokeninfo verification (no JWT lib, no session store)
- **Hosting:** Vercel (frontend) + Render Web Service Starter (backend)
- **Migrations:** Numbered `migrations/*.sql` files + `backend/db/migrate.py` runner; `schema_migrations` table tracks applied versions

---

## Environment Setup

Backend:
```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Frontend:
```
cd frontend && npm install && npm run dev
```

---

## Workflow Philosophy

This repo treats AI-assisted development as a structured engineering workflow, not ad-hoc prompting. Behave like a project-aware collaborator, not a search box.

### Before editing — classify the task

Decide what kind of change this is: Product/UX, Frontend UI, Backend/API, Auth/session, Database/migration, Data pipeline/enrichment, Deployment/infra, Bug investigation, Refactor, Docs.

For anything non-trivial, produce a short plan before editing code naming:

1. Which files are likely relevant
2. Which system boundaries are involved (frontend ↔ backend contract, auth, DB schema, deploy)
3. What should **not** be touched
4. What needs to be tested afterward
5. Any risk to auth, data, or deployment

Prefer small, reversible changes. If the task is growing, stop and narrow scope rather than expanding into unrelated cleanup.

### Mode switching

**Design mode** — read [DESIGN.md](DESIGN.md) first. Preserve core product intent. Avoid feature-list thinking and developer-facing complexity in the UI.

**Engineering mode** — respect existing architecture boundaries (backend routes ↔ frontend API client). Make small patches. Keep request/response contracts aligned. Add or update tests when behavior changes.

**Deployment mode** — distinguish local, Vercel preview, and Render production. Render auto-deploys from `main` via `render.yaml`. Schema changes ride with code: add a numbered file under `migrations/`, the entrypoint runs `python -m backend.db.migrate` before Uvicorn starts. Summarize manual deploy steps clearly when something needs to happen out-of-band (e.g., data backfills, env-var rotation).

### Context loading by task type

- **Frontend** — relevant components, DESIGN.md, routing, API client
- **Backend** — the relevant route file, the repository in `backend/db/repository.py`, SQL queries
- **Auth** — `backend/auth.py` (consolidated tokeninfo path); do NOT reintroduce JWT/session-store paths
- **Database** — Postgres schema lives in `migrations/*.sql`; new tables/columns require a new numbered migration file. `psycopg` uses `%s` placeholders, never `?`
- **Data pipeline** — currently FROZEN. The Phase B rewrite (R2 + GitHub Actions) is the next major workstream; see `backend/scrapers/README.md`. Existing enrichment cost ~$194 (one-time Google Places spend); don't re-run blindly
- **Deployment** — `render.yaml`, `Dockerfile`, `scripts/docker-entrypoint.sh`, Vercel config, env var names, CORS origins

### Review as a separate phase

Don't blend implementation and review:

1. Understand the task
2. Inspect relevant files
3. Plan the change
4. Implement the smallest viable patch
5. Review the diff against the original task
6. Run or specify the appropriate tests
7. Summarize what changed, why, and what remains risky

For code-review tasks, do NOT rewrite immediately. First identify correctness issues, architecture-boundary violations, hidden coupling, missing tests, regression risk, security/data-leakage risk, and UX regressions. Then propose or apply fixes.

### Preventing uncontrolled changes

Hard rules:

- No broad refactors unless explicitly requested
- No renames of core files, routes, models, or components unless the task requires it
- Don't touch `backend/scrapers/` — frozen pending Phase B rewrite
- Don't change auth, DB schema, API contracts, or deploy config as a side effect of a UI task
- Don't change enrichment scripts or re-run Google Places calls as a side effect of unrelated work
- Don't reintroduce `sqlite3.connect`, `?` placeholders, `.lastrowid`, or any `holyhub.database.Database` import in runtime route code; the CI grep test in `tests/test_no_sqlite_in_routes.py` will fail
- Don't introduce new libraries without explaining why existing tools are insufficient
- Don't remove tests to make a build pass
- Don't silently rename environment variables
- Don't reintroduce purple/violet (#6c63ff) — retired, see Design System below

If a broader change seems necessary, pause and explain the proposed expansion before editing.

### When you make a mistake

Identify the failure mode before patching on top: misread product intent, edited legacy code, broke auth/session assumptions, changed API contract without updating the consumer, added DB fields without a migration, fixed local but broke production, over-refactored, solved symptom not root cause. If it's likely to recur, add a guardrail below.

---

## Project-Specific Guardrails

- **Auth — active path:** Google Identity Services (GSI) in browser → `POST /api/auth/verify` → Google `tokeninfo`. Verification logic is consolidated in [`backend/auth.py`](backend/auth.py). **Don't** reintroduce JWT libraries, server-side sessions, or cookie-based auth — the design is intentionally tokeninfo-on-every-protected-request.
- **Database — active path:** Supabase Postgres via psycopg 3 async pool, transaction pooler on port 6543. All runtime SQL goes through [`backend/db/repository.py`](backend/db/repository.py); routers do not touch `psycopg` directly. Schema changes are numbered SQL files under `migrations/`.
- **Cutover safety:** The `READ_ONLY=1` env var makes the app return 503 on all writes (except `/api/health` and `/api/auth/verify`). Use during database upgrades or DNS flips so a stale frontend tab cannot silently lose a review.
- **Pool config:** `psycopg_pool.AsyncConnectionPool` is configured with `prepare_threshold=None`. This is required for Supabase's transaction-mode pooler; do not remove without testing connection reuse under load.
- **Scrapers frozen:** `backend/scrapers/` does not import after the Phase A migration removed `holyhub/`. Phase B will rewrite these against R2 + GitHub Actions. Do not "fix" the scrapers as a side effect of unrelated work; the rewrite is the fix.

---

## Design System

Always read [DESIGN.md](DESIGN.md) before any visual or UI decision. Fonts, colors, spacing, and aesthetic direction live there. Do not deviate without explicit user approval. Highlights:

- Never use purple/violet (#6c63ff) — retired in favor of sienna (#8B5E3C)
- Church names always use Fraunces serif
- Wordmark always uses Fraunces serif
- Stars/ratings use gold (#D4A853)
- Dimension bars use sienna→gold gradient fill

In QA mode, flag any code that doesn't match DESIGN.md.

---

## Common Commands

```
# Backend
DATABASE_URL=postgresql://...:6543/postgres uvicorn backend.main:app --reload   # local dev
pytest -q                                                                       # unit + static checks
DATABASE_URL=... pytest tests/test_parity.py                                    # parity against Postgres
DATABASE_URL=... python -m backend.db.migrate                                   # apply new migrations
DATABASE_URL=... SQLITE_PATH=./holyhub.db python -m scripts.migrate_data        # one-shot data migration

# Frontend
cd frontend && npm run dev                                                      # local dev
cd frontend && npm run build                                                    # production build (Vercel auto-deploys on push to main)

# Deploy
# Render auto-deploys backend from main on every push (render.yaml).
# Vercel auto-deploys frontend from main.
```

---

## Conventions

- All runtime SQL goes through `backend/db/repository.py`. Routers never call `psycopg` directly.
- psycopg uses `%s` placeholders and `INSERT ... RETURNING id` (no `?`, no `lastrowid`).
- Table names are lowercase (`churches`, `reviews`, `users`, `api_usage`, `church_embeddings`). Postgres folds unquoted identifiers; never use `Churches`.
- New schema = new file in `migrations/` with the next sequential prefix. Runner applies in order.
- Frontend API calls go through a single client module; don't `fetch` directly from components.
- Errors raised from FastAPI use `HTTPException` with explicit status codes.
- Auth-protected endpoints depend on `backend.auth.get_current_user`, which re-verifies the bearer token via tokeninfo on every call.

---

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

Available skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`.

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.

---

## Common Pitfalls

- *(grow this from real experience, not anticipation)*
