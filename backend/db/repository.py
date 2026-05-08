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
