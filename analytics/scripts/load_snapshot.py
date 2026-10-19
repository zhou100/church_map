"""Load a sanitized churches snapshot into the analytics sidecar's `raw` schema.

Week one reads the local SQLite snapshot (`holyhub.db`). A production read-only
export can replace it later, with separate approval. Only map-relevant columns
are copied: no Google reviews, editorial, photos or hours, and no users or reviews.
`google_address` is reduced to a boolean until the Google terms check is done.

    analytics/.venv/bin/python analytics/scripts/load_snapshot.py [--sqlite holyhub.db]

Connection: ANALYTICS_DATABASE_URL (default: local sidecar on port 5433).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DEFAULT_URL = "postgresql://analytics@localhost:5433/churchmap_analytics"
COLUMNS = [
    ("church_id", "bigint primary key"),
    ("name", "text"),
    ("address", "text"),
    ("city", "text"),
    ("state", "text"),
    ("zip_code", "text"),
    ("latitude", "double precision"),
    ("longitude", "double precision"),
    ("website", "text"),
    ("phone", "text"),
    ("source", "text"),
    ("external_id", "text"),
    ("denomination", "text"),
    ("has_google_address", "boolean"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="holyhub.db")
    args = ap.parse_args()
    path = Path(args.sqlite)
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = src.execute(
        """SELECT church_id, name, address, city, state, zip_code, latitude, longitude,
                  website, phone, source, external_id, denomination,
                  TRIM(COALESCE(google_address, '')) != ''
           FROM Churches"""
    ).fetchall()
    taken_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    with psycopg.connect(os.environ.get("ANALYTICS_DATABASE_URL", DEFAULT_URL), autocommit=False) as con:
        cur = con.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute("DROP TABLE IF EXISTS raw.churches")
        cur.execute("CREATE TABLE raw.churches (" + ", ".join(f"{c} {t}" for c, t in COLUMNS) + ")")
        with cur.copy("COPY raw.churches (" + ", ".join(c for c, _ in COLUMNS) + ") FROM STDIN") as cp:
            for r in rows:
                cp.write_row(list(r[:-1]) + [bool(r[-1])])
        cur.execute("DROP TABLE IF EXISTS raw.snapshot_meta")
        cur.execute("CREATE TABLE raw.snapshot_meta (snapshot_source text, snapshot_taken_at timestamptz, loaded_at timestamptz)")
        cur.execute("INSERT INTO raw.snapshot_meta VALUES (%s, %s, now())", (f"sqlite:{path.name}", taken_at))
        con.commit()
    print(f"loaded {len(rows)} churches from {path} (snapshot {taken_at:%Y-%m-%d})")


if __name__ == "__main__":
    main()
