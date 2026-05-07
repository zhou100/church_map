# CLAUDE.md — ChurchMap (holyhub)

This file provides guidance for AI assistants (Claude and others) working on this codebase. The goal is consistent, project-aware behavior — not maximum verbosity.

---

## Project Overview

ChurchMap is a church discovery platform that rates churches on dimensions that actually matter for fit (worship energy, community warmth, sermon depth, children's programs, theological stance, facilities) — not generic star ratings. Read [OVERVIEW.md](OVERVIEW.md) for the full product/system writeup. Live at churchmap.vercel.app.

The core product intent: **help people find a church that fits them**. Don't erode this with restaurant-review-style thinking or developer-facing complexity in the UI.

---

## Repository Structure

```
backend/      FastAPI app, SQLite queries, auth, enrichment scripts
frontend/    React + Vite + Leaflet SPA
tests/       Backend tests
holyhub.db   SQLite database (baked into Docker image at deploy)
Dockerfile   Backend image (Fly.io)
fly.toml     Fly.io config (2 machines, scale-to-zero)
DESIGN.md    Design system — read before any UI change
OVERVIEW.md  Product + architecture writeup
TODOS.md     Active work list
```

The `holyhub/` directory is a legacy artifact — do not edit unless the task is specifically about cleanup.

---

## Tech Stack

- **Frontend:** React 18, Vite, React Router, Leaflet
- **Backend:** FastAPI (Python 3.11), raw `sqlite3` (no ORM)
- **Database:** SQLite, baked into Docker image (~45 MB)
- **Auth:** Google Identity Services (GSI) + tokeninfo verification (no JWT lib, no session store)
- **Hosting:** Vercel (frontend) + Fly.io (backend, scale-to-zero)

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

**Deployment mode** — distinguish local, Vercel preview, and Fly.io production. SQLite writes don't replicate across Fly machines — keep this in mind for any review/write feature. Summarize manual deploy steps clearly.

### Context loading by task type

- **Frontend** — relevant components, DESIGN.md, routing, API client
- **Backend** — the relevant route file, SQL queries, schemas if shapes change
- **Auth** — current GSI/tokeninfo flow only; do NOT reintroduce JWT/session-store paths
- **Database** — `holyhub.db` schema; any schema change requires a migration script and a rebuild of the Docker image
- **Data pipeline** — identify the specific stage (scrape, dedup, geocode, enrich); enrichment costs real money (~$194 spent), don't re-run blindly
- **Deployment** — `fly.toml`, `Dockerfile`, Vercel config, env var names, CORS origins

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
- Don't touch the `holyhub/` legacy directory unless cleanup is the task
- Don't change auth, DB schema, API contracts, or deploy config as a side effect of a UI task
- Don't change enrichment scripts or re-run Google Places calls as a side effect of unrelated work
- Don't introduce new libraries without explaining why existing tools are insufficient
- Don't remove tests to make a build pass
- Don't silently rename environment variables
- Don't reintroduce purple/violet (#6c63ff) — retired, see Design System below

If a broader change seems necessary, pause and explain the proposed expansion before editing.

### When you make a mistake

Identify the failure mode before patching on top: misread product intent, edited legacy code, broke auth/session assumptions, changed API contract without updating the consumer, added DB fields without a migration, fixed local but broke production, over-refactored, solved symptom not root cause. If it's likely to recur, add a guardrail below.

---

## Project-Specific Guardrails

- **Auth — active path:** Google Identity Services (GSI) in browser → `POST /api/auth/verify` → Google `tokeninfo`. **Don't** reintroduce JWT libraries, server-side sessions, or cookie-based auth — the design is intentionally tokeninfo-on-every-protected-request.
- **Database — active path:** SQLite file baked into the Docker image (`holyhub.db`). **Don't** add a hosted DB dependency (Postgres/RDS/Turso) without explicit approval — the architecture relies on in-process queries and image-baked data.
- **Deploys — Fly machines don't share writes:** review data written on one Fly machine isn't visible on the other in real time. Don't add features that assume cross-machine write consistency without flagging the limitation.

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
uvicorn backend.main:app --reload          # local dev
pytest tests/                              # tests
fly deploy                                 # deploy backend (rebuilds Docker image with current holyhub.db)

# Frontend
cd frontend && npm run dev                 # local dev
cd frontend && npm run build               # production build (Vercel auto-deploys on push to main)
```

---

## Conventions

- Backend uses raw `sqlite3` queries — no ORM. Keep queries explicit and parameterized.
- Frontend API calls go through a single client module; don't `fetch` directly from components.
- Errors raised from FastAPI use `HTTPException` with explicit status codes.
- Auth-protected endpoints expect `Authorization: Bearer <google_id_token>` and re-verify via tokeninfo.

---

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

Available skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`.

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.

---

## Common Pitfalls

- *(grow this from real experience, not anticipation)*
