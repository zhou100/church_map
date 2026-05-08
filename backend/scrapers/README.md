# Scrapers (frozen — superseded by `backend/scrapers_v2/`)

**Phase B shipped.** The active crawl pipeline lives in
[`backend/scrapers_v2/`](../scrapers_v2/): R2-backed raw HTML, async psycopg
against Supabase Postgres, LLM extraction with confidence + verbatim source
snippets, and X-Crawl-Token-protected admin endpoints driven by
[`.github/workflows/crawl.yml`](../../.github/workflows/crawl.yml).

The modules in this directory are kept only as reference. Do not import or
run them — they reach for `sqlite3` and `holyhub.database.Database`, both
of which were removed in Phase A. The CI grep test in
`tests/test_no_sqlite_in_routes.py` blocks any of those patterns from
re-entering runtime code.

What was ported into v2:

| v1 file (here)         | v2 location                                     | Notes |
|------------------------|--------------------------------------------------|-------|
| `website_extract.py`   | `scrapers_v2/prompts/website_v3.py` + `extract.py` | Prompt extended with `_confidence` and `_source_snippets`; substring validation added. Bumped to `2026-05-08.v3`. |
| `website_fetch.py`     | `scrapers_v2/fetch.py` + `scrapers_v2/r2.py`     | Async httpx, R2 PUT keyed `raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html`, idempotent on `(church_id, url, content_hash)`. |
| `name_tags.py` rules   | `scrapers_v2/tag.py`                             | Same regex table; runs over psycopg, gated by NULL language/cultural_background. |
| robots.txt handling    | `scrapers_v2/robots.py` + `robots_cache` table   | 24h TTL cache in Postgres instead of per-process. |
| `website_embed.py`     | (still pending)                                  | Embedding regeneration is Phase B+1. |

What did **not** carry over: every `db_path: str = "holyhub.db"` argument,
every direct `sqlite3.connect`, the standalone migration scripts (replaced
by numbered `migrations/*.sql` + `backend/db/migrate.py`), and the
synchronous run-loops (replaced by async batch handlers callable from the
admin router).
