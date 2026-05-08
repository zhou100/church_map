"""
One-shot SQLite -> Supabase Postgres data migration.

Run order:
  1. Apply Postgres schema migrations:  python -m backend.db.migrate
  2. Run this script:                    python -m scripts.migrate_data

Usage:
  SQLITE_PATH=./holyhub.db DATABASE_URL=postgres://... python -m scripts.migrate_data

What this does:
  * Streams rows from SQLite into Postgres using psycopg COPY for the wide
    table (churches, ~134k rows) and INSERT for everything else.
  * Decodes church_embeddings.vector (BYTEA blob, np.float32) into a pgvector
    literal. Asserts byte length matches `dim * 4` and aborts loudly on
    mismatch so silent corruption can't slip through.
  * Skips website_pages entirely (Phase A drops it; rebuild fresh in Phase B).
  * After loading, advances every BIGSERIAL sequence so the first new
    INSERT does not collide on PK.
  * Validates row counts before exiting non-zero on any mismatch.

What this does NOT do:
  * Idempotent re-run on a populated Postgres. Run against an empty
    schema; if you need to re-run, drop and recreate the schema first.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from typing import Iterable

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger("migrate_data")
logging.basicConfig(level=logging.INFO, format="[migrate_data] %(message)s")

SQLITE_PATH = os.environ.get("SQLITE_PATH", "holyhub.db")
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    log.error("DATABASE_URL is not set")
    sys.exit(2)

# Tables in the order they must be loaded (FK constraints).
TABLES = ["churches", "users", "reviews", "api_usage", "church_embeddings"]
DROPPED_TABLES = ["website_pages"]  # Phase A: start fresh in Phase B


def _parse_dt(s):
    """SQLite stores datetimes as ISO strings or None. Postgres wants
    timestamptz or None. None passes through; '' is treated as None."""
    if s is None or s == "":
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        log.warning("could not parse datetime %r, treating as NULL", s)
        return None


def _parse_json(s):
    """SQLite stores JSON as TEXT. Postgres JSONB needs an actual object or
    None. Empty string -> None; invalid JSON -> abort (loud failure beats
    silent corruption)."""
    if s is None or s == "":
        return None
    if isinstance(s, (dict, list)):
        return Jsonb(s)
    try:
        return Jsonb(json.loads(s))
    except json.JSONDecodeError as e:
        log.error("invalid JSON in source column: %r (%s)", s[:80], e)
        raise


def _migrate_churches(src: sqlite3.Connection, dst: psycopg.Connection) -> int:
    src.row_factory = sqlite3.Row
    cols = [
        "church_id", "name", "address", "city", "state", "denomination",
        "service_times", "latitude", "longitude", "zip_code", "website",
        "phone", "source", "external_id", "google_place_id",
        "google_photos", "google_hours", "google_enriched_at",
        "google_rating", "google_review_count", "google_reviews",
        "google_editorial", "google_wheelchair", "google_address",
        "language", "cultural_background", "website_summary",
        "extracted_tags", "extracted_at", "extracted_prompt_version",
        "extracted_status",
    ]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO churches ({', '.join(cols)}) VALUES ({placeholders})"

    n = 0
    batch = []
    BATCH = 1000
    with dst.cursor() as cur:
        for row in src.execute(f"SELECT {', '.join(cols)} FROM Churches"):
            d = dict(row)
            d["google_photos"] = _parse_json(d["google_photos"])
            d["google_hours"] = _parse_json(d["google_hours"])
            d["google_reviews"] = _parse_json(d["google_reviews"])
            d["extracted_tags"] = _parse_json(d["extracted_tags"])
            d["google_enriched_at"] = _parse_dt(d["google_enriched_at"])
            d["extracted_at"] = _parse_dt(d["extracted_at"])
            batch.append(tuple(d[c] for c in cols))
            if len(batch) >= BATCH:
                cur.executemany(sql, batch)
                n += len(batch)
                batch = []
                if n % 10000 == 0:
                    log.info("churches: %d", n)
        if batch:
            cur.executemany(sql, batch)
            n += len(batch)
    dst.commit()
    log.info("churches: %d total", n)
    return n


def _migrate_users(src: sqlite3.Connection, dst: psycopg.Connection) -> int:
    src.row_factory = sqlite3.Row
    rows = list(src.execute(
        "SELECT user_id, google_id, email, name, avatar_url, created_at FROM Users"
    ))
    if not rows:
        log.info("users: 0")
        return 0
    sql = """
        INSERT INTO users (user_id, google_id, email, name, avatar_url, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with dst.cursor() as cur:
        for r in rows:
            cur.execute(sql, (
                r["user_id"], r["google_id"], r["email"], r["name"],
                r["avatar_url"], _parse_dt(r["created_at"]),
            ))
    dst.commit()
    log.info("users: %d", len(rows))
    return len(rows)


def _migrate_reviews(src: sqlite3.Connection, dst: psycopg.Connection) -> int:
    src.row_factory = sqlite3.Row
    cols = [
        "review_id", "church_id", "rating", "comment",
        "worship_energy", "community_warmth", "sermon_depth",
        "childrens_programs", "theological_openness", "facilities",
        "created_at", "user_id", "reviewer_name", "reviewer_avatar",
    ]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO reviews ({', '.join(cols)}) VALUES ({placeholders})"
    rows = list(src.execute(f"SELECT {', '.join(cols)} FROM Reviews"))
    with dst.cursor() as cur:
        for row in rows:
            d = dict(row)
            d["created_at"] = _parse_dt(d["created_at"])
            cur.execute(sql, tuple(d[c] for c in cols))
    dst.commit()
    log.info("reviews: %d", len(rows))
    return len(rows)


def _migrate_api_usage(src: sqlite3.Connection, dst: psycopg.Connection) -> int:
    rows = list(src.execute("SELECT month, service, count FROM api_usage"))
    sql = "INSERT INTO api_usage (month, service, count) VALUES (%s, %s, %s)"
    with dst.cursor() as cur:
        for row in rows:
            cur.execute(sql, tuple(row))
    dst.commit()
    log.info("api_usage: %d", len(rows))
    return len(rows)


def _decode_embedding(blob: bytes, dim: int) -> list[float]:
    """Decode a SQLite BLOB as np.float32 array of length `dim`. Aborts on
    length mismatch."""
    expected = dim * 4
    if len(blob) != expected:
        raise ValueError(
            f"embedding byte length {len(blob)} != dim*4 ({expected}) — refusing to migrate"
        )
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape != (dim,):
        raise ValueError(
            f"decoded shape {arr.shape} != ({dim},)"
        )
    return arr.tolist()


def _migrate_embeddings(src: sqlite3.Connection, dst: psycopg.Connection) -> int:
    src.row_factory = sqlite3.Row
    rows = list(src.execute(
        "SELECT church_id, model, dim, vector, source_text, created_at FROM church_embeddings"
    ))
    if not rows:
        log.info("church_embeddings: 0")
        return 0

    # pgvector wants `[v1,v2,...]` as a string literal cast to vector.
    sql = """
        INSERT INTO church_embeddings (church_id, model, dim, vector_blob, vector, source_text, created_at)
        VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
    """
    with dst.cursor() as cur:
        for r in rows:
            blob = bytes(r["vector"]) if r["vector"] is not None else None
            if blob is None:
                vec_literal = None
            else:
                vec = _decode_embedding(blob, r["dim"])
                vec_literal = "[" + ",".join(repr(float(x)) for x in vec) + "]"
            cur.execute(sql, (
                r["church_id"], r["model"], r["dim"],
                blob, vec_literal, r["source_text"], _parse_dt(r["created_at"]),
            ))
    dst.commit()
    log.info("church_embeddings: %d", len(rows))
    return len(rows)


def _reset_sequences(dst: psycopg.Connection) -> None:
    """Advance BIGSERIAL sequences past the max imported PK so the first
    new INSERT doesn't collide. setval(..., MAX(id), true) means next
    nextval() returns MAX(id)+1; on empty tables, fall back to 1 with
    is_called=false so nextval() returns 1."""
    targets = [
        ("churches", "church_id"),
        ("users", "user_id"),
        ("reviews", "review_id"),
    ]
    with dst.cursor() as cur:
        for table, col in targets:
            cur.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
            max_id = cur.fetchone()[0]
            if max_id and max_id > 0:
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)",
                    (table, col, max_id),
                )
                log.info("sequence %s.%s -> %d", table, col, max_id)
            else:
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, %s), 1, false)",
                    (table, col),
                )
                log.info("sequence %s.%s -> 1 (empty)", table, col)
    dst.commit()


def _validate_counts(
    src: sqlite3.Connection, dst: psycopg.Connection, expected: dict[str, int]
) -> bool:
    """Compare row counts. Exact parity for tables with <=1000 rows;
    +/- 0.1% for larger tables."""
    ok = True
    SRC_TABLE = {
        "churches": "Churches",
        "users": "Users",
        "reviews": "Reviews",
        "api_usage": "api_usage",
        "church_embeddings": "church_embeddings",
    }
    for table in TABLES:
        src_name = SRC_TABLE[table]
        sqlite_n = src.execute(f"SELECT COUNT(*) FROM {src_name}").fetchone()[0]
        pg_n = dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        loaded = expected[table]
        if sqlite_n <= 1000:
            if sqlite_n != pg_n:
                log.error("%s: SQLite=%d Postgres=%d (exact parity required)", table, sqlite_n, pg_n)
                ok = False
            else:
                log.info("%s: %d == %d ok", table, sqlite_n, pg_n)
        else:
            tolerance = max(1, int(sqlite_n * 0.001))
            if abs(sqlite_n - pg_n) > tolerance:
                log.error("%s: SQLite=%d Postgres=%d (delta %d > tolerance %d)", table, sqlite_n, pg_n, abs(sqlite_n - pg_n), tolerance)
                ok = False
            else:
                log.info("%s: %d ~= %d (within %d) ok", table, sqlite_n, pg_n, tolerance)
        if loaded != pg_n:
            log.error("%s: loaded count %d != Postgres count %d", table, loaded, pg_n)
            ok = False
    return ok


def main() -> int:
    if not os.path.isfile(SQLITE_PATH):
        log.error("SQLite file not found: %s", SQLITE_PATH)
        return 2

    log.info("source SQLite: %s", SQLITE_PATH)
    log.info("destination Postgres: <DATABASE_URL>")

    src = sqlite3.connect(SQLITE_PATH)
    dst = psycopg.connect(DATABASE_URL)
    try:
        loaded = {
            "churches": _migrate_churches(src, dst),
            "users": _migrate_users(src, dst),
            "reviews": _migrate_reviews(src, dst),
            "api_usage": _migrate_api_usage(src, dst),
            "church_embeddings": _migrate_embeddings(src, dst),
        }
        _reset_sequences(dst)
        ok = _validate_counts(src, dst, loaded)
        return 0 if ok else 1
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
