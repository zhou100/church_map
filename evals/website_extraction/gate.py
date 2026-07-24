"""CI gate for the website-extraction eval — offline, no API key required.

`run.py --from-cache` can score a whole golden set without a single LLM
call, which is what makes gating a pull request practical. The catch is
that a cache is only meaningful for the prompt and golden set it was built
from, and both are easy to change without regenerating it. Scoring a
changed prompt against a stale cache doesn't fail — it passes, having
measured nothing. This module's job is to make that impossible:

1. `golden.jsonl` must match what `compile.py` produces from `golden.md`
   (someone edited the markdown and forgot to recompile).
2. The cache must contain an entry for every golden example (someone added
   examples; without this, `run.py` silently falls back to live LLM calls
   and CI dies on a missing API key instead of saying what's wrong).
3. The baseline's `prompt_fingerprint` must equal the current prompt's
   (someone edited the prompt; the cached extractions predate the edit).

Only then does it hand off to `run.py`'s regression comparison.

Usage:
    python -m evals.website_extraction.gate                  # baselines/CURRENT
    python -m evals.website_extraction.gate --threshold 0.05
    python -m evals.website_extraction.gate --baseline-stem 2026-07-24.v3

`baselines/CURRENT` holds one line — the stem of the active baseline, e.g.
`2026-07-24.v3`, which resolves to `baselines/<stem>.json` (report) and
`baselines/<stem>.cache.json` (extractions + judge verdicts).

## Changing the prompt

Editing `backend/scrapers_v2/prompts/website_v3.py` invalidates every
cached extraction, so the gate will fail until you refresh them:

    # 1. bump PROMPT_VERSION in the prompt module
    # 2. re-extract and re-judge the whole golden set (costs LLM calls)
    python -m evals.website_extraction.run --judge \\
        --save-cache evals/website_extraction/baselines/<today>.v4.cache.json \\
        --save       evals/website_extraction/baselines/<today>.v4.json
    # 3. point CURRENT at it and commit cache + baseline + CURRENT together
    echo <today>.v4 > evals/website_extraction/baselines/CURRENT

Read the diff in the new report before committing it: a baseline saved
from a worse prompt makes the regression permanent and invisible.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

from evals.website_extraction.compile import MD, compile_md
from evals.website_extraction.run import GOLDEN, cache_meta, load_cache, prompt_fingerprint
from evals.website_extraction.run import main as run_main

HERE = Path(__file__).parent
BASELINE_DIR = HERE / "baselines"
CURRENT = BASELINE_DIR / "CURRENT"


def read_current(path: Path = CURRENT) -> str:
    """The active baseline stem, ignoring blank lines and `#` comments."""
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    raise SystemExit(f"{path} names no baseline")


def check_golden_in_sync(md: Path = MD, jsonl: Path = GOLDEN) -> list[str]:
    """golden.jsonl must be exactly what compile.py makes from golden.md."""
    with tempfile.TemporaryDirectory() as tmp:
        rebuilt = Path(tmp) / "golden.jsonl"
        with contextlib.redirect_stdout(io.StringIO()):  # "wrote N examples" is noise here
            compile_md(md_path=md, out_path=rebuilt)
        if rebuilt.read_text() != jsonl.read_text():
            return [
                f"{jsonl.name} is stale — it does not match {md.name}. "
                "Run: python -m evals.website_extraction.compile"
            ]
    return []


def check_cache_covers_golden(cache: dict, golden: list[dict]) -> list[str]:
    """Every example needs a cached extraction, or the run goes live."""
    missing = [ex["name"] for ex in golden if ex["name"] not in cache]
    if not missing:
        return []
    listed = "\n".join(f"    - {n}" for n in missing[:10])
    more = f"\n    …and {len(missing) - 10} more" if len(missing) > 10 else ""
    return [
        "cache is missing entries for these golden examples, so scoring them "
        f"would need live LLM calls:\n{listed}{more}\n"
        "  Regenerate with --save-cache (see the module docstring)."
    ]


def check_prompt_fresh(baseline: dict, cache_meta: dict | None = None) -> list[str]:
    """The cached extractions must come from the prompt in this checkout.

    Both files carry a fingerprint and both are checked, because they can
    drift apart: re-saving a baseline from an old cache after a prompt edit
    would otherwise produce a baseline that looks current and extractions
    that aren't.
    """
    want = prompt_fingerprint()
    problems: list[str] = []
    stamped = False
    for label, got in (
        ("cache", (cache_meta or {}).get("prompt_fingerprint")),
        ("baseline", baseline.get("prompt_fingerprint")),
    ):
        if got is None:
            continue
        stamped = True
        if got != want:
            problems.append(
                f"prompt changed since the {label} was saved "
                f"({label} {got}, working tree {want}). Those extractions came "
                "from the old prompt, so scoring them proves nothing. Re-run "
                "with --save-cache/--save and update CURRENT — see the module "
                "docstring."
            )
    if not stamped:
        problems.append(
            "baseline and cache predate prompt fingerprinting — regenerate "
            "them with the current run.py so the gate can tell whether they "
            "are stale."
        )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline-stem", help="Override baselines/CURRENT")
    parser.add_argument("--threshold", type=float, default=0.10,
                        help="Precision drop that counts as a regression for deterministic fields (default 0.10)")
    parser.add_argument("--judge-threshold", type=float, default=0.15,
                        help="Same, for LLM-judged prose fields (default 0.15 — see run.threshold_for)")
    args = parser.parse_args(argv)

    stem = args.baseline_stem or read_current()
    baseline_path = BASELINE_DIR / f"{stem}.json"
    cache_path = BASELINE_DIR / f"{stem}.cache.json"

    problems: list[str] = []
    for p in (baseline_path, cache_path):
        if not p.exists():
            problems.append(f"missing {p.relative_to(HERE.parent.parent)} (CURRENT says '{stem}')")
    if problems:
        _report(problems)
        return 2

    baseline = json.loads(baseline_path.read_text())
    cache = load_cache(cache_path)
    golden = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]

    problems += check_golden_in_sync()
    problems += check_cache_covers_golden(cache, golden)
    problems += check_prompt_fresh(baseline, cache_meta(cache_path))
    if problems:
        _report(problems)
        return 2

    print(
        f"gate: baseline {stem}, {len(golden)} examples, "
        f"prompt {baseline['prompt_version']} ({baseline['prompt_fingerprint']}), "
        f"threshold {args.threshold:.2f} deterministic / {args.judge_threshold:.2f} judged "
        "— scoring from cache, no LLM calls"
    )
    return run_main([
        "--judge",
        "--from-cache", str(cache_path),
        "--baseline", str(baseline_path),
        "--threshold", str(args.threshold),
        "--judge-threshold", str(args.judge_threshold),
    ])


def _report(problems: list[str]) -> None:
    print("eval gate cannot run:", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
