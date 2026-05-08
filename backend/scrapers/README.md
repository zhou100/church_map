# Scrapers (frozen, pending Phase B rewrite)

These modules were written against the SQLite-baked-in-image setup. After
Phase A (backend migration to Render + Supabase Postgres), they no longer
import: every file referenced `from holyhub.database import Database` or
opened `sqlite3.connect("holyhub.db")` directly, and both paths are gone.

**Do not run these.** They will fail on import.

They live here as reference for the Phase B rewrite, which will:
- Move scraping execution to GitHub Actions cron
- Write raw HTML to Cloudflare R2 (object key + content_hash in Postgres)
- Run extraction as a separate stage that reads from R2
- Use psycopg against Supabase Postgres instead of sqlite3

The pieces worth preserving in the rewrite:
- `website_extract.py` — v2 LLM extraction prompt (refined to richer output
  in commit af93e1b). The prompt is the IP; the SQLite plumbing is not.
- `website_fetch.py` — fetch politeness, robots.txt handling, content_hash.
- `website_embed.py` — embedding shape (np.float32, dim from model).
- `name_tags.py` — deterministic tag rules (Mandarin, Cantonese, etc.).

The pieces to discard:
- All `db_path: str = "holyhub.db"` arguments.
- All migration scripts (`migrate.py`, `migrate_website_pipeline.py`) —
  superseded by `migrations/*.sql` + `backend/db/migrate.py`.
- Direct `sqlite3.connect` and `Database(...)` usage.
