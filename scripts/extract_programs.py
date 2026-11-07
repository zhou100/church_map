"""Extract children's, youth and childcare programs from archived church pages.

Dry run by default: reads the due churches' pages from R2 and reports how many
would need a model call and how much text they would send. Nothing is written
and no model is called. `--apply` makes the calls (paid, OpenRouter) and writes
church_programs, one transaction per church. Not on any schedule: each run is
a deliberate, bounded batch (plan D-A).

    DATABASE_URL=... R2_...=... python -m scripts.extract_programs --limit 20
    DATABASE_URL=... R2_...=... OPENROUTER_API_KEY=... \\
        python -m scripts.extract_programs --limit 20 --apply

Prints counts only, never page text, names or URLs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

MAX_LIMIT = 200


async def _run(url: str, limit: int, apply: bool) -> dict:
    from psycopg import AsyncConnection

    from backend.db.repository import ProgramRepository
    from backend.scrapers_v2.programs import run_program_batch
    from backend.scrapers_v2.r2 import R2Client

    # prepare_threshold=None: required by Supabase's transaction pooler (port 6543).
    con = await AsyncConnection.connect(url, autocommit=True, prepare_threshold=None)
    try:
        return await run_program_batch(ProgramRepository(con), R2Client(), limit=limit, apply=apply)
    finally:
        await con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=20, help=f"churches in this batch (1-{MAX_LIMIT})")
    ap.add_argument("--apply", action="store_true", help="call the model and write programs")
    args = ap.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        ap.error(f"--limit must be between 1 and {MAX_LIMIT}")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    counts = asyncio.run(_run(url, args.limit, args.apply))
    print(json.dumps({"apply": args.apply, **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
