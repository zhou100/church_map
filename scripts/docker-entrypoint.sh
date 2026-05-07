#!/bin/sh
# docker-entrypoint.sh — bootstrap DB on /data volume, run migrations, exec uvicorn.
#
# Logic:
#   1. If DATABASE_PATH is unset, fall back to /data/holyhub.db (matches fly.toml).
#   2. Ensure the parent dir exists (volume mount creates /data; this is defensive).
#   3. If the DB file doesn't exist on the volume:
#       a. If a baked seed exists at /app/holyhub.db.seed, copy it in.
#       b. Otherwise leave the file absent — the migrations below will create it.
#   4. Run the baseline migration (idempotent) + the website-pipeline migration
#      (idempotent). If the DB was empty, we also need to create the schema first
#      via holyhub/schema.sql (the legacy Database._initialize_database does this
#      lazily, but we want the migrations to find a Churches table to ALTER).
#   5. Hand off to uvicorn.

set -e

DB_PATH="${DATABASE_PATH:-/data/holyhub.db}"
SEED_PATH="/app/holyhub.db.seed"

mkdir -p "$(dirname "$DB_PATH")"

if [ ! -f "$DB_PATH" ]; then
    if [ -f "$SEED_PATH" ] && [ -s "$SEED_PATH" ]; then
        echo "[entrypoint] seeding $DB_PATH from $SEED_PATH"
        cp "$SEED_PATH" "$DB_PATH"
    else
        echo "[entrypoint] no seed available; creating empty DB at $DB_PATH from schema.sql"
        python -c "import sqlite3; con = sqlite3.connect('$DB_PATH'); con.executescript(open('holyhub/schema.sql').read()); con.commit(); con.close()"
    fi
fi

echo "[entrypoint] running baseline migration"
python -m backend.scrapers.migrate "$DB_PATH"

echo "[entrypoint] running website-pipeline migration"
python -m backend.scrapers.migrate_website_pipeline "$DB_PATH"

echo "[entrypoint] starting uvicorn"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
