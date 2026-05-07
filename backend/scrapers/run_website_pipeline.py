"""Website pipeline CLI runner.

Top-priority order (mirrors batch_enrich.py):
  1. Churches with reviews
  2. Churches in major US cities
  3. Everything else with a website

Phases (each can run independently):
  --phase fetch     Crawl websites, populate website_pages
  --phase extract   Run OpenRouter LLM over cached pages, populate extracted_*
  --phase embed     Run Voyage embedding over extracted text, populate church_embeddings
  --phase all       Fetch + extract + embed (default)

Usage:
  python -m backend.scrapers.run_website_pipeline --limit 10 --dry-run
  python -m backend.scrapers.run_website_pipeline --limit 50 --phase fetch
  python -m backend.scrapers.run_website_pipeline --phase extract --limit 50
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from backend.env_loader import load_env_local

load_env_local()

from backend.scrapers import website_embed, website_extract, website_fetch

PRIORITY_CITIES = {
    "new york", "brooklyn", "los angeles", "chicago", "houston", "phoenix",
    "philadelphia", "san antonio", "san diego", "dallas", "san jose",
    "austin", "jacksonville", "fort worth", "columbus", "charlotte",
    "indianapolis", "san francisco", "seattle", "denver", "washington",
    "nashville", "oklahoma city", "el paso", "boston", "portland",
    "las vegas", "memphis", "louisville", "baltimore", "milwaukee",
    "atlanta", "miami", "minneapolis", "tulsa", "cleveland",
    "raleigh", "colorado springs", "virginia beach", "omaha", "long beach",
}

log = logging.getLogger(__name__)


def candidates(con: sqlite3.Connection, limit: int) -> list[tuple[int, str, str | None]]:
    rows = con.execute(
        """
        SELECT c.church_id, c.website, c.city,
               (SELECT COUNT(*) FROM Reviews r WHERE r.church_id = c.church_id) AS review_count
        FROM Churches c
        WHERE c.website IS NOT NULL AND c.website != ''
        """
    ).fetchall()

    def priority(row):
        cid, website, city, rc = row
        if rc and rc > 0:
            tier = 0
        elif city and city.lower() in PRIORITY_CITIES:
            tier = 1
        else:
            tier = 2
        return (tier, -(rc or 0), cid)

    rows.sort(key=priority)
    return [(r[0], r[1], r[2]) for r in rows[:limit]]


def phase_fetch(con: sqlite3.Connection, targets: list[tuple[int, str, str | None]], dry_run: bool) -> None:
    print(f"[fetch] {len(targets)} churches")
    if dry_run:
        for cid, web, city in targets[:10]:
            print(f"  would fetch: church={cid} city={city} url={web}")
        return
    for i, (cid, web, city) in enumerate(targets, 1):
        try:
            results = website_fetch.fetch_church(con, cid, web)
            ok = sum(1 for r in results if r.status_code == 200)
            print(f"  [{i}/{len(targets)}] church={cid} ({city}) pages_ok={ok}/{len(results)}")
        except Exception as e:
            log.exception("fetch failed for church %s: %s", cid, e)


def phase_extract(con: sqlite3.Connection, targets: list[tuple[int, str, str | None]], dry_run: bool) -> None:
    eligible = [
        (cid, city) for cid, _, city in targets
        if con.execute(
            "SELECT 1 FROM website_pages WHERE church_id=? AND status_code=200 LIMIT 1",
            (cid,),
        ).fetchone()
    ]
    print(f"[extract] {len(eligible)} churches with usable pages")
    if dry_run:
        for cid, city in eligible[:10]:
            print(f"  would extract: church={cid} city={city}")
        return
    for i, (cid, city) in enumerate(eligible, 1):
        norm = website_extract.extract_for_church(con, cid)
        marker = "ok" if norm else "skipped"
        print(f"  [{i}/{len(eligible)}] church={cid} ({city}) → {marker}")


def phase_embed(con: sqlite3.Connection, targets: list[tuple[int, str, str | None]], dry_run: bool) -> None:
    eligible = [
        cid for cid, _, _ in targets
        if con.execute(
            "SELECT 1 FROM Churches WHERE church_id=? AND extracted_status='ok'",
            (cid,),
        ).fetchone()
    ]
    print(f"[embed] {len(eligible)} churches with extracted data")
    if dry_run:
        print(f"  would embed {len(eligible)} churches in batches of {website_embed.BATCH_SIZE}")
        return
    written = website_embed.embed_many(con, eligible)
    print(f"  embedded {written} churches")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Website pipeline runner")
    parser.add_argument("--phase", choices=["fetch", "extract", "embed", "all"], default="all")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default="holyhub.db")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    con = sqlite3.connect(args.db)
    try:
        targets = candidates(con, args.limit)
        print(f"Selected {len(targets)} top-priority churches (limit={args.limit})")

        if args.phase in ("fetch", "all"):
            phase_fetch(con, targets, args.dry_run)
        if args.phase in ("extract", "all"):
            phase_extract(con, targets, args.dry_run)
        if args.phase in ("embed", "all"):
            phase_embed(con, targets, args.dry_run)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
