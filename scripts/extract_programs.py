"""Extract children's, youth and childcare programs from archived church pages.

Dry run by default: reads the due churches' pages from R2 and reports how many
would need a model call and how much text they would send. Nothing is written
and no model is called. `--apply` makes the calls (paid, OpenRouter) and writes
church_programs, one transaction per church. Not on any schedule: each run is
a deliberate, bounded batch (plan D-A).

    DATABASE_URL=... R2_...=... python -m scripts.extract_programs --limit 20
    DATABASE_URL=... R2_...=... OPENROUTER_API_KEY=... \\
        python -m scripts.extract_programs --limit 20 --apply

`--church-ids 742,760` re-reads exactly those churches, due or not, after a
rule fix; `--sample-seed S` takes `--limit` due churches in a seeded random
order, for an evaluation sample, instead of oldest first.

Prints counts only, never page text, names or URLs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

MAX_LIMIT = 200


async def _run(url: str, limit: int, apply: bool, church_ids: list[int] | None,
               sample_seed: str | None) -> dict:
    from psycopg import AsyncConnection

    from backend.db.repository import ProgramRepository
    from backend.scrapers_v2.programs import run_program_batch
    from backend.scrapers_v2.r2 import R2Client

    # prepare_threshold=None: required by Supabase's transaction pooler (port 6543).
    con = await AsyncConnection.connect(url, autocommit=True, prepare_threshold=None)
    try:
        return await run_program_batch(ProgramRepository(con), R2Client(), limit=limit, apply=apply,
                                       church_ids=church_ids, sample_seed=sample_seed)
    finally:
        await con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=20, help=f"churches in this batch (1-{MAX_LIMIT})")
    ap.add_argument("--apply", action="store_true", help="call the model and write programs")
    pick = ap.add_mutually_exclusive_group()
    pick.add_argument("--church-ids", help="comma-separated church ids to re-read, due or not")
    pick.add_argument("--sample-seed", help="take due churches in a random order fixed by this seed")
    args = ap.parse_args(argv)
    church_ids = None
    if args.church_ids is not None:
        try:
            church_ids = sorted({int(x) for x in args.church_ids.split(",") if x.strip()})
        except ValueError:
            ap.error("--church-ids must be comma-separated integers")
        if not church_ids:
            ap.error("--church-ids is empty")
        args.limit = len(church_ids)
    if not 1 <= args.limit <= MAX_LIMIT:
        ap.error(f"--limit must be between 1 and {MAX_LIMIT}")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    counts = asyncio.run(_run(url, args.limit, args.apply, church_ids, args.sample_seed))
    print(json.dumps({"apply": args.apply, **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
