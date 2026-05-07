"""Schema migration for the website extraction pipeline.

Adds:
  - Churches columns: website_summary, extracted_tags, extracted_at,
    extracted_prompt_version, extracted_status
  - church_embeddings table: vector BLOB (float32 array), model + dim
  - website_pages table: per-URL HTML+text cache with fetched_at, status_code,
    robots_allowed, content_hash; deduped by (church_id, url)

Idempotent. Safe to re-run. Run from project root:

    python -m backend.scrapers.migrate_website_pipeline
"""
from __future__ import annotations

import sqlite3
import sys


CHURCH_COLUMNS = [
    ("website_summary",          "TEXT"),
    ("extracted_tags",           "TEXT"),
    ("extracted_at",             "TEXT"),
    ("extracted_prompt_version", "TEXT"),
    ("extracted_status",         "TEXT"),
]


def migrate(db_path: str = "holyhub.db") -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    existing = {row[1] for row in cur.execute("PRAGMA table_info(Churches)")}
    for col, typedef in CHURCH_COLUMNS:
        if col not in existing:
            cur.execute(f"ALTER TABLE Churches ADD COLUMN {col} {typedef}")
            print(f"  added Churches.{col}")
        else:
            print(f"  already exists: Churches.{col}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS website_pages (
            page_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            church_id     INTEGER NOT NULL REFERENCES Churches(church_id),
            url           TEXT    NOT NULL,
            kind          TEXT,
            status_code   INTEGER,
            fetched_at    TEXT    NOT NULL,
            robots_allowed INTEGER NOT NULL DEFAULT 1,
            content_hash  TEXT,
            text          TEXT,
            error         TEXT,
            UNIQUE(church_id, url)
        )
    """)
    print("  ensured: website_pages")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS church_embeddings (
            church_id   INTEGER PRIMARY KEY REFERENCES Churches(church_id),
            model       TEXT NOT NULL,
            dim         INTEGER NOT NULL,
            vector      BLOB NOT NULL,
            source_text TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    print("  ensured: church_embeddings")

    for name, ddl in [
        ("idx_website_pages_church",
         "CREATE INDEX IF NOT EXISTS idx_website_pages_church ON website_pages(church_id)"),
        ("idx_churches_extracted_at",
         "CREATE INDEX IF NOT EXISTS idx_churches_extracted_at ON Churches(extracted_at)"),
    ]:
        cur.execute(ddl)
        print(f"  index ensured: {name}")

    con.commit()
    con.close()
    print("Website-pipeline migration complete.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "holyhub.db"
    migrate(db_path)
