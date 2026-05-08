"""
Tiny migration runner. Applies migrations/*.sql in lexical order, tracks
applied versions in `schema_migrations`. Idempotent — already-applied
migrations are skipped.

Run via: `python -m backend.db.migrate`

Each .sql file is treated as a single transaction. If you need a
non-transactional DDL (e.g. CREATE INDEX CONCURRENTLY), put it in its own
file and the runner will execute it inside a transaction anyway — that's
fine for everything in scope here.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg

log = logging.getLogger("migrate")
logging.basicConfig(level=logging.INFO, format="[migrate] %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set")
        sys.exit(2)
    return url


def _ensure_table(con: psycopg.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    con.commit()


def _applied(con: psycopg.Connection) -> set[str]:
    rows = con.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _run_one(con: psycopg.Connection, path: Path) -> None:
    log.info("applying %s", path.name)
    sql = path.read_text()
    with con.transaction():
        con.execute(sql)
        con.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s)",
            (path.stem,),
        )


def run() -> int:
    if not MIGRATIONS_DIR.is_dir():
        log.error("migrations dir not found: %s", MIGRATIONS_DIR)
        return 2

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        log.warning("no migrations found in %s", MIGRATIONS_DIR)
        return 0

    with psycopg.connect(_dsn()) as con:
        _ensure_table(con)
        applied = _applied(con)
        new = [p for p in files if p.stem not in applied]
        if not new:
            log.info("up to date (%d migrations applied)", len(applied))
            return 0
        for p in new:
            _run_one(con, p)
        log.info("applied %d migration(s)", len(new))
    return 0


if __name__ == "__main__":
    sys.exit(run())
