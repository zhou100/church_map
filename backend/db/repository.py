"""
Repository layer. All runtime SQL lives here; routers do not touch psycopg
directly. Two SQLite-era practices are intentionally undone:

  * `?` placeholders → `%s` (psycopg pyformat style)
  * `cursor.lastrowid` → `INSERT ... RETURNING id`

Tables are lowercase (`churches`, `reviews`, `users`, `api_usage`,
`church_embeddings`) per migration 0001. Postgres folds unquoted identifiers
to lowercase, so passing `Churches` would silently return zero rows.
"""
from __future__ import annotations

import json
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


# ----- Churches ------------------------------------------------------------

# `_DIM_QUERY` produces the fields routers expect, including review aggregates.
# LEFT JOIN keeps churches with zero reviews; AVG returns NULL when no rows
# exist on the right side, matching the SQLite behavior the routers already
# handle.
_DIM_SELECT = """
    SELECT
        c.church_id                                AS id,
        c.name,
        c.address,
        c.city,
        c.state,
        c.denomination,
        c.service_times,
        c.website,
        c.phone,
        c.language,
        c.cultural_background,
        c.website_summary,
        c.extracted_tags,
        c.latitude,
        c.longitude,
        ROUND(AVG(r.rating)::numeric, 1)::float8   AS avg_rating,
        COUNT(r.review_id)                         AS review_count,
        AVG(r.worship_energy)                      AS avg_worship_energy,
        AVG(r.community_warmth)                    AS avg_community_warmth,
        AVG(r.sermon_depth)                        AS avg_sermon_depth,
        AVG(r.childrens_programs)                  AS avg_childrens_programs,
        AVG(r.theological_openness)                AS avg_theological_openness,
        AVG(r.facilities)                          AS avg_facilities
    FROM churches c
    LEFT JOIN reviews r ON c.church_id = r.church_id
"""


def _normalize_extracted_tags(value: Any) -> Any:
    """
    Postgres JSONB returns dict/list directly via psycopg's default adapters,
    while the existing API contract returns a parsed object. SQLite stored
    JSON as TEXT, so the old code did json.loads(row["extracted_tags"]). Any
    callers expecting that should pass the value through here.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


class ChurchRepository:
    def __init__(self, con: AsyncConnection):
        self.con = con

    async def list_by_zip(self, zip_code: str, limit: int, offset: int) -> list[dict]:
        sql = _DIM_SELECT + """
            WHERE c.zip_code = %s
            GROUP BY c.church_id
            LIMIT %s OFFSET %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (zip_code, limit, offset))
            return await cur.fetchall()

    async def list_by_city_state(
        self, city: str, state: str, limit: int, offset: int
    ) -> list[dict]:
        sql = _DIM_SELECT + """
            WHERE LOWER(c.city) = LOWER(%s) AND LOWER(c.state) = LOWER(%s)
            GROUP BY c.church_id
            ORDER BY review_count DESC
            LIMIT %s OFFSET %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (city, state, limit, offset))
            return await cur.fetchall()

    async def get(self, church_id: int) -> dict | None:
        sql = _DIM_SELECT + """
            WHERE c.church_id = %s
            GROUP BY c.church_id
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (church_id,))
            return await cur.fetchone()

    async def similar(self, church_id: int, k: int = 3) -> list[dict]:
        # Squared Euclidean distance on the 6 dimension averages of the target
        # church vs. every other church with at least one review. Inlined
        # rather than using pgvector because reviews aren't embeddings and
        # this keeps the query close to the SQLite original.
        sql = """
            WITH t AS (
                SELECT
                    COALESCE(AVG(worship_energy),       0) AS we,
                    COALESCE(AVG(community_warmth),     0) AS cw,
                    COALESCE(AVG(sermon_depth),         0) AS sd,
                    COALESCE(AVG(childrens_programs),   0) AS cp,
                    COALESCE(AVG(theological_openness), 0) AS to_,
                    COALESCE(AVG(facilities),           0) AS fac
                FROM reviews WHERE church_id = %s
            )
            SELECT
                c.church_id AS id, c.name, c.address, c.city, c.state,
                c.denomination, c.service_times, c.website, c.phone,
                c.language, c.cultural_background,
                c.latitude, c.longitude,
                ROUND(AVG(r.rating)::numeric, 1)::float8 AS avg_rating,
                COUNT(r.review_id)                       AS review_count,
                AVG(r.worship_energy)                    AS avg_worship_energy,
                AVG(r.community_warmth)                  AS avg_community_warmth,
                AVG(r.sermon_depth)                      AS avg_sermon_depth,
                AVG(r.childrens_programs)                AS avg_childrens_programs,
                AVG(r.theological_openness)              AS avg_theological_openness,
                AVG(r.facilities)                        AS avg_facilities,
                (
                  POWER(COALESCE(AVG(r.worship_energy),       0) - t.we,  2) +
                  POWER(COALESCE(AVG(r.community_warmth),     0) - t.cw,  2) +
                  POWER(COALESCE(AVG(r.sermon_depth),         0) - t.sd,  2) +
                  POWER(COALESCE(AVG(r.childrens_programs),   0) - t.cp,  2) +
                  POWER(COALESCE(AVG(r.theological_openness), 0) - t.to_, 2) +
                  POWER(COALESCE(AVG(r.facilities),           0) - t.fac, 2)
                ) AS dist_sq
            FROM churches c
            JOIN reviews r ON c.church_id = r.church_id
            CROSS JOIN t
            WHERE c.church_id <> %s
            GROUP BY c.church_id, t.we, t.cw, t.sd, t.cp, t.to_, t.fac
            ORDER BY dist_sq ASC
            LIMIT %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (church_id, church_id, k))
            return await cur.fetchall()

    async def get_enrichment_cache(self, church_id: int) -> dict | None:
        sql = """
            SELECT google_photos, google_hours
            FROM churches
            WHERE church_id = %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (church_id,))
            return await cur.fetchone()


# ----- Reviews -------------------------------------------------------------


class ReviewRepository:
    def __init__(self, con: AsyncConnection):
        self.con = con

    async def list_by_church(self, church_id: int) -> list[dict]:
        sql = """
            SELECT review_id, church_id, rating, comment,
                   worship_energy, community_warmth, sermon_depth,
                   childrens_programs, theological_openness, facilities,
                   created_at, reviewer_name, reviewer_avatar
            FROM reviews
            WHERE church_id = %s
            ORDER BY created_at DESC
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (church_id,))
            rows = await cur.fetchall()
        return [
            {
                "id": r["review_id"],
                "rating": r["rating"],
                "comment": r["comment"],
                "worship_energy": r["worship_energy"],
                "community_warmth": r["community_warmth"],
                "sermon_depth": r["sermon_depth"],
                "childrens_programs": r["childrens_programs"],
                "theological_openness": r["theological_openness"],
                "facilities": r["facilities"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "reviewer_name": r["reviewer_name"],
                "reviewer_avatar": r["reviewer_avatar"],
            }
            for r in rows
        ]

    async def insert(
        self,
        *,
        church_id: int,
        rating: float,
        comment: str | None,
        worship_energy: float | None,
        community_warmth: float | None,
        sermon_depth: float | None,
        childrens_programs: float | None,
        theological_openness: float | None,
        facilities: float | None,
        user_id: int,
        reviewer_name: str,
        reviewer_avatar: str,
    ) -> int:
        sql = """
            INSERT INTO reviews (
                church_id, rating, comment,
                worship_energy, community_warmth, sermon_depth,
                childrens_programs, theological_openness, facilities,
                user_id, reviewer_name, reviewer_avatar
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING review_id
        """
        async with self.con.cursor() as cur:
            await cur.execute(
                sql,
                (
                    church_id, rating, comment,
                    worship_energy, community_warmth, sermon_depth,
                    childrens_programs, theological_openness, facilities,
                    user_id, reviewer_name, reviewer_avatar,
                ),
            )
            row = await cur.fetchone()
        return row[0]


# ----- Users ---------------------------------------------------------------


class UserRepository:
    def __init__(self, con: AsyncConnection):
        self.con = con

    async def upsert(
        self, *, google_id: str, email: str, name: str, avatar_url: str
    ) -> dict:
        # ON CONFLICT updates name/email/avatar so a user changing their
        # Google profile picture is reflected next sign-in. RETURNING means
        # one round-trip for the whole upsert+fetch.
        sql = """
            INSERT INTO users (google_id, email, name, avatar_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (google_id) DO UPDATE SET
                email      = EXCLUDED.email,
                name       = EXCLUDED.name,
                avatar_url = EXCLUDED.avatar_url
            RETURNING user_id, name, email, avatar_url
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (google_id, email, name, avatar_url))
            return await cur.fetchone()


# ----- Crawl pipeline (Phase B) --------------------------------------------


class CrawlRepository:
    """SQL surface for the R2-backed crawl pipeline.

    Three stages share one repository:
      fetch   reads churches needing a crawl, writes raw_crawl_artifacts rows
      extract reads pending artifacts, writes back extract_status + churches.*
      tag     reads churches.extracted_tags, writes deterministic tags

    All methods take an AsyncConnection so callers can compose them inside
    a single transaction when desired.
    """

    def __init__(self, con: AsyncConnection):
        self.con = con

    # ----- crawl_runs ------------------------------------------------------

    async def start_run(self, stage: str, batch_size: int, triggered_by: str) -> int:
        sql = """
            INSERT INTO crawl_runs (stage, batch_size, triggered_by)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (stage, batch_size, triggered_by))
            row = await cur.fetchone()
        return row[0]

    async def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        rows_processed: int,
        rows_ok: int,
        rows_error: int,
        error: str | None = None,
    ) -> None:
        sql = """
            UPDATE crawl_runs
               SET finished_at    = NOW(),
                   status         = %s,
                   rows_processed = %s,
                   rows_ok        = %s,
                   rows_error     = %s,
                   error          = %s
             WHERE id = %s
        """
        async with self.con.cursor() as cur:
            await cur.execute(
                sql,
                (status, rows_processed, rows_ok, rows_error, error, run_id),
            )

    async def recent_runs(self, limit: int = 20) -> list[dict]:
        sql = """
            SELECT id, stage, started_at, finished_at, status,
                   batch_size, rows_processed, rows_ok, rows_error,
                   triggered_by, error
              FROM crawl_runs
             ORDER BY started_at DESC
             LIMIT %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (limit,))
            return await cur.fetchall()

    # ----- robots_cache ----------------------------------------------------

    async def get_robots(self, host: str) -> dict | None:
        sql = """
            SELECT host, body, fetched_at, expires_at
              FROM robots_cache
             WHERE host = %s AND expires_at > NOW()
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (host,))
            return await cur.fetchone()

    async def upsert_robots(self, host: str, body: str, ttl_seconds: int) -> None:
        sql = """
            INSERT INTO robots_cache (host, body, fetched_at, expires_at)
            VALUES (%s, %s, NOW(), NOW() + (%s || ' seconds')::interval)
            ON CONFLICT (host) DO UPDATE SET
                body       = EXCLUDED.body,
                fetched_at = EXCLUDED.fetched_at,
                expires_at = EXCLUDED.expires_at
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (host, body, str(ttl_seconds)))

    # ----- fetch stage -----------------------------------------------------

    async def churches_due_for_fetch(
        self, limit: int, fresh_days: int, *, failure_backoff_hours: int = 48
    ) -> list[dict]:
        # Two CTEs: latest_ok tracks the freshness window for successful
        # homepage fetches (skip for fresh_days). latest_attempt tracks ANY
        # homepage attempt — successful or not — so a church that timed out
        # / robots-disallowed / 5xx'd doesn't get retried every 4 hours.
        # Without this backoff, a few hundred permanently-broken sites would
        # consume every batch and starve never-tried churches.
        sql = """
            WITH latest_ok AS (
                SELECT church_id, MAX(fetched_at) AS last_ok
                  FROM raw_crawl_artifacts
                 WHERE kind = 'homepage' AND http_status = 200
                 GROUP BY church_id
            ),
            latest_attempt AS (
                SELECT church_id, MAX(fetched_at) AS last_try
                  FROM raw_crawl_artifacts
                 WHERE kind = 'homepage'
                 GROUP BY church_id
            )
            SELECT c.church_id, c.website
              FROM churches c
              LEFT JOIN latest_ok      l ON l.church_id = c.church_id
              LEFT JOIN latest_attempt a ON a.church_id = c.church_id
             WHERE c.website IS NOT NULL AND c.website <> ''
               AND (l.last_ok IS NULL OR l.last_ok < NOW() - (%s || ' days')::interval)
               AND (a.last_try IS NULL OR a.last_try < NOW() - (%s || ' hours')::interval)
             ORDER BY a.last_try ASC NULLS FIRST
             LIMIT %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (str(fresh_days), str(failure_backoff_hours), limit))
            return await cur.fetchall()

    async def insert_artifact(
        self,
        *,
        church_id: int,
        url: str,
        kind: str,
        http_status: int,
        fetch_error: str | None,
        robots_allowed: bool,
        content_hash: str | None,
        r2_key: str | None,
        bytes_raw: int | None,
        bytes_text: int | None,
        crawl_run_id: int | None,
    ) -> int | None:
        # ON CONFLICT DO NOTHING on (church_id, url, content_hash) gives us
        # idempotency: re-fetching the same body of the same URL is a no-op.
        # Returns the artifact id on insert, None if a duplicate was skipped.
        sql = """
            INSERT INTO raw_crawl_artifacts (
                church_id, url, kind, http_status, fetch_error,
                robots_allowed, content_hash, r2_key, bytes_raw, bytes_text,
                crawl_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (church_id, url, content_hash) DO NOTHING
            RETURNING id
        """
        async with self.con.cursor() as cur:
            await cur.execute(
                sql,
                (
                    church_id, url, kind, http_status, fetch_error,
                    robots_allowed, content_hash, r2_key, bytes_raw, bytes_text,
                    crawl_run_id,
                ),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    # ----- extract stage ---------------------------------------------------

    async def pending_extract_targets(self, limit: int) -> list[dict]:
        # Group pending artifacts by church so a single LLM call covers all
        # pages for that church. Returns one row per church with a list of
        # artifact ids and their R2 keys + kinds.
        sql = """
            SELECT
                a.church_id,
                ARRAY_AGG(a.id ORDER BY
                    CASE a.kind
                        WHEN 'homepage'   THEN 0
                        WHEN 'about'      THEN 1
                        WHEN 'beliefs'    THEN 2
                        WHEN 'ministries' THEN 3
                        WHEN 'services'   THEN 4
                        ELSE 5
                    END
                ) AS artifact_ids,
                ARRAY_AGG(a.r2_key ORDER BY
                    CASE a.kind
                        WHEN 'homepage'   THEN 0
                        WHEN 'about'      THEN 1
                        WHEN 'beliefs'    THEN 2
                        WHEN 'ministries' THEN 3
                        WHEN 'services'   THEN 4
                        ELSE 5
                    END
                ) AS r2_keys,
                ARRAY_AGG(a.kind ORDER BY
                    CASE a.kind
                        WHEN 'homepage'   THEN 0
                        WHEN 'about'      THEN 1
                        WHEN 'beliefs'    THEN 2
                        WHEN 'ministries' THEN 3
                        WHEN 'services'   THEN 4
                        ELSE 5
                    END
                ) AS kinds
              FROM raw_crawl_artifacts a
             WHERE a.extract_status = 'pending'
               AND a.http_status = 200
               AND a.r2_key IS NOT NULL
             GROUP BY a.church_id
             ORDER BY MIN(a.fetched_at) ASC
             LIMIT %s
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (limit,))
            return await cur.fetchall()

    async def mark_artifacts_status(
        self,
        artifact_ids: list[int],
        *,
        status: str,
        error_detail: str | None = None,
    ) -> None:
        if not artifact_ids:
            return
        sql = """
            UPDATE raw_crawl_artifacts
               SET extract_status       = %s,
                   extract_error_detail = %s,
                   extracted_at         = NOW()
             WHERE id = ANY(%s)
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (status, error_detail, artifact_ids))

    async def write_extraction(
        self,
        church_id: int,
        *,
        website_summary: str | None,
        extracted_tags: dict,
        denomination: str | None,
        prompt_version: str,
        model: str,
        confidence: dict,
        source_snippets: dict,
    ) -> None:
        sql = """
            UPDATE churches
               SET website_summary           = %s,
                   extracted_tags            = %s::jsonb,
                   extracted_at              = NOW(),
                   extracted_prompt_version  = %s,
                   extracted_model           = %s,
                   extracted_status          = 'ok',
                   extracted_confidence      = %s::jsonb,
                   extracted_source_snippets = %s::jsonb,
                   denomination              = COALESCE(%s, denomination)
             WHERE church_id = %s
        """
        async with self.con.cursor() as cur:
            await cur.execute(
                sql,
                (
                    website_summary,
                    json.dumps(extracted_tags, ensure_ascii=False),
                    prompt_version,
                    model,
                    json.dumps(confidence, ensure_ascii=False),
                    json.dumps(source_snippets, ensure_ascii=False),
                    denomination,
                    church_id,
                ),
            )

    async def mark_church_extract_error(self, church_id: int, status: str) -> None:
        sql = """
            UPDATE churches
               SET extracted_status = %s,
                   extracted_at     = NOW()
             WHERE church_id = %s
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (status, church_id))
