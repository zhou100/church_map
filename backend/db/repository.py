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

    async def count_stale_extractions(self, prompt_version: str, model: str) -> dict:
        """Churches whose extraction predates the current prompt or model.

        Two numbers, because they answer different questions:

        `total` is the size of the whole backfill. It only falls as churches
        are actually re-extracted — re-queueing does not change it, because
        `churches.extracted_prompt_version` keeps its old value right up
        until the extract stage overwrites it.

        `awaiting_queue` is what the re-queue can actually act on right now:
        stale, not already queued, and holding at least one 'ok' artifact to
        put back. That last condition matters — a church can be stale with
        nothing re-queueable (artifacts all errored, or never written), and
        counting those would leave `awaiting_queue` permanently above zero
        while the re-queue reports nothing done. The runbook says "repeat
        until it reaches zero", so it has to be able to reach zero.
        """
        sql = """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE NOT EXISTS (
                        SELECT 1 FROM raw_crawl_artifacts a
                         WHERE a.church_id = c.church_id
                           AND a.extract_status = 'pending'
                    )
                    AND EXISTS (
                        SELECT 1 FROM raw_crawl_artifacts a
                         WHERE a.church_id = c.church_id
                           AND a.extract_status = 'ok'
                    )
                ) AS awaiting_queue
              FROM churches c
             WHERE extracted_at IS NOT NULL
               AND (extracted_prompt_version IS DISTINCT FROM %s
                    OR extracted_model IS DISTINCT FROM %s)
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (prompt_version, model))
            return await cur.fetchone()

    async def requeue_stale_extractions(
        self, prompt_version: str, model: str, *, limit: int
    ) -> list[int]:
        """Flip already-extracted artifacts back to 'pending' for re-extraction.

        The extract stage picks work up by `extract_status = 'pending'` and
        knows nothing about prompt versions, so re-extracting after a prompt
        or model change means putting artifacts back in that queue. Doing it
        this way rather than with a bespoke script means the backfill inherits
        everything the normal pipeline already has: batch limits, crawl_runs
        bookkeeping, error handling, and the GitHub Actions schedule that
        paces it.

        Only artifacts currently 'ok' are touched:
          - 'pending' is already queued, and re-queueing would be a no-op
          - 'error' and 'skipped' failed for a reason that a new prompt won't
            fix; re-queueing them just spends the same money to fail again

        `limit` bounds the number of *churches*, so this can be run in small
        passes and watched, rather than dumping the whole corpus into the
        queue at once. Returns the affected church ids.

        Churches that already have a queued artifact are skipped, so calling
        this repeatedly walks forward through the corpus. Without that, every
        pass would re-target the same lowest church_ids — a church stays
        "stale" until the extract stage actually rewrites its row, which is
        long after it was queued — and the backfill would never advance past
        its first batch.

        Churches with nothing re-queueable are skipped for the same reason.
        A stale church whose artifacts all errored (or were never written)
        would otherwise consume a `limit` slot, update no rows, and — never
        gaining a 'pending' artifact — sit at the head of the queue on every
        subsequent pass, blocking the backfill permanently.

        NOTE: no crawl_runs row — that table's CHECK constraint only allows
        the three pipeline stages, and this is a queue manipulation, not a
        stage.
        """
        sql = """
            WITH stale AS (
                SELECT church_id
                  FROM churches c
                 WHERE extracted_at IS NOT NULL
                   AND (extracted_prompt_version IS DISTINCT FROM %s
                        OR extracted_model IS DISTINCT FROM %s)
                   AND NOT EXISTS (
                        SELECT 1 FROM raw_crawl_artifacts a
                         WHERE a.church_id = c.church_id
                           AND a.extract_status = 'pending'
                   )
                   AND EXISTS (
                        SELECT 1 FROM raw_crawl_artifacts a
                         WHERE a.church_id = c.church_id
                           AND a.extract_status = 'ok'
                   )
                 ORDER BY church_id
                 LIMIT %s
            )
            UPDATE raw_crawl_artifacts a
               SET extract_status       = 'pending',
                   extract_error_detail = NULL
              FROM stale s
             WHERE a.church_id = s.church_id
               AND a.extract_status = 'ok'
            RETURNING a.church_id
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (prompt_version, model, limit))
            return [r[0] for r in await cur.fetchall()]

    async def mark_church_extract_error(self, church_id: int, status: str) -> None:
        sql = """
            UPDATE churches
               SET extracted_status = %s,
                   extracted_at     = NOW()
             WHERE church_id = %s
        """
        async with self.con.cursor() as cur:
            await cur.execute(sql, (status, church_id))


class StatsRepository:
    """Aggregate counts for the public /api/stats endpoint.

    Deliberately aggregate-only: no per-church detail, so it needs no token
    the way /api/admin/crawl/status does. Every query here is a full scan of
    a 134k-row table or a small scan of crawl_runs — cheap, but not free,
    which is why the router caches the result rather than the queries being
    optimized into unreadability.
    """

    def __init__(self, con: AsyncConnection):
        self.con = con

    async def church_counts(self) -> dict:
        """One pass over churches for every headline count."""
        sql = """
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER (
                    WHERE website IS NOT NULL AND website <> ''
                )                                                   AS with_website,
                COUNT(*) FILTER (WHERE extracted_at IS NOT NULL)    AS extracted,
                COUNT(*) FILTER (
                    WHERE website_summary IS NOT NULL AND website_summary <> ''
                )                                                   AS with_summary,
                COUNT(*) FILTER (WHERE google_enriched_at IS NOT NULL) AS enriched
              FROM churches
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql)
            return await cur.fetchone()

    async def extraction_by_prompt_version(self) -> list[dict]:
        """Extraction counts per (prompt version, model), largest first.

        This is what sizes a re-extraction backfill: the extract stage
        selects on artifact status, not prompt version, so churches keep
        whatever version *and model* they were last extracted under.

        The model has to be in the grouping. `CrawlRepository`'s staleness
        predicate treats a model change exactly like a prompt change, so
        grouping on version alone made this endpoint report churches as
        current that the re-queue would immediately pick up — two numbers
        for the same question, disagreeing.
        """
        sql = """
            SELECT COALESCE(extracted_prompt_version, 'unknown') AS version,
                   COALESCE(extracted_model, 'unknown')          AS model,
                   COUNT(*)                                      AS count
              FROM churches
             WHERE extracted_at IS NOT NULL
             GROUP BY 1, 2
             ORDER BY count DESC, version, model
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql)
            return await cur.fetchall()

    async def crawl_health(self, window_days: int = 7) -> dict:
        """Last successful run per stage, plus recent run outcomes.

        The "last successful run" half is the outage detector: the pipeline
        going quiet looks exactly like success from the outside, which is
        how the 2026-07-08 auto-disable went unnoticed for 8 days.
        """
        last_sql = """
            SELECT stage, MAX(finished_at) AS last_success
              FROM crawl_runs
             WHERE status = 'ok'
             GROUP BY stage
        """
        window_sql = """
            SELECT status, COUNT(*) AS count
              FROM crawl_runs
             WHERE started_at >= NOW() - make_interval(days => %s)
             GROUP BY status
        """
        async with self.con.cursor(row_factory=dict_row) as cur:
            await cur.execute(last_sql)
            last = await cur.fetchall()
            await cur.execute(window_sql, (window_days,))
            window = await cur.fetchall()
        return {"last_success": last, "window": window, "window_days": window_days}
