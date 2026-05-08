FROM python:3.11-slim

WORKDIR /app

# Build deps for psycopg[binary] are bundled, but a few transitive packages
# still want a compiler around for sdist fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Phase A: SQLite is gone. Strip any stray .db files that might have made
# it into the build context so we never accidentally ship one again.
RUN find /app -maxdepth 2 -name "*.db" -delete \
    && find /app -maxdepth 2 -name "*.db-shm" -delete \
    && find /app -maxdepth 2 -name "*.db-wal" -delete

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
