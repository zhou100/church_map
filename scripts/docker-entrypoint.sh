#!/bin/sh
# docker-entrypoint.sh — Phase A
#
# Apply Postgres schema migrations, then exec uvicorn. No SQLite, no
# /data volume seed. DATABASE_URL must be set (Render env var pointing
# at Supabase pooler on port 6543).

set -e

if [ -z "$DATABASE_URL" ]; then
    echo "[entrypoint] FATAL: DATABASE_URL is not set" >&2
    exit 2
fi

echo "[entrypoint] applying Postgres migrations"
python -m backend.db.migrate

PORT="${PORT:-8000}"
echo "[entrypoint] starting uvicorn on :${PORT}"
exec uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
