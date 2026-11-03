"""Check a private JSONL manifest against local archived HTML; no network calls.

Each row: subject_id, html_path, source_url, fetched_at, reference. Reference
fields are documented in backend.scrapers_v2.identity. Use one archived page per
subject; duplicate subjects are rejected rather than picking a campus or silently
replacing evidence. This is the offline PR 2 adapter; runtime integration and
Muse dispatch are separate consumers, not implied by generating this report.

Run: python -m scripts.check_website_identity --input PRIVATE.jsonl --output PRIVATE.jsonl
Only aggregate counts reach stdout; errors do not echo input or file contents.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from backend.scrapers_v2.identity import check_identity


def build_report(manifest: Path) -> list[dict]:
    reports = []
    seen = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        subject = row["subject_id"]
        if not isinstance(subject, str) or not subject or subject in seen:
            raise ValueError("invalid or repeated subject")
        seen.add(subject)
        reference = row["reference"]
        if not isinstance(reference, dict):
            raise ValueError("invalid reference")
        for key in ("source_url", "fetched_at", "html_path"):
            if not isinstance(row[key], str) or not row[key]:
                raise ValueError("missing provenance")
        raw_path = Path(row["html_path"])
        if not raw_path.is_absolute():
            raw_path = manifest.parent / raw_path
        result = check_identity(raw_path.read_bytes(), reference,
                                source_url=row["source_url"], fetched_at=row["fetched_at"])
        reports.append({"subject_id": subject, **result.report()})
    return reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        reports = build_report(args.input)
        # Exclusive create avoids destroying an earlier evidence bundle or input.
        with args.output.open("x", encoding="utf-8") as out:
            for row in reports:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        print("Identity report failed; check private inputs and output destination.", file=sys.stderr)
        return 1
    counts = Counter(row["verdict"] for row in reports)
    print(json.dumps({"subjects": len(reports), **{key: counts[key] for key in
                      ("match", "conflict", "no_comparable")}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
