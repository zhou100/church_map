"""Evaluate website-extraction quality against a golden set.

Calls the live OpenRouter extractor on each example and scores per-field
precision. Outputs a JSON report and exits non-zero if any field drops
>10% vs --baseline (a previously saved report).

Usage:
    python -m evals.website_extraction.run                    # run, print scores
    python -m evals.website_extraction.run --save report.json # save report
    python -m evals.website_extraction.run --baseline old.json  # gate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.env_loader import load_env_local

load_env_local()

from backend.scrapers import website_extract

GOLDEN = Path(__file__).parent / "golden.jsonl"


def _load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _score_one(expected: dict, got: dict) -> dict[str, bool]:
    def _norm(s):  return (s or "").strip().lower()
    def _norms(xs): return [_norm(x) for x in (xs or [])]

    scores = {}
    if "denomination" in expected:
        exp = _norm(expected["denomination"])
        gn = _norm(got.get("denomination"))
        scores["denomination"] = bool(exp) and (exp in gn or gn in exp)
    if "theological_stance" in expected:
        scores["theological_stance"] = expected["theological_stance"] == got.get("theological_stance")
    if "service_languages" in expected:
        exp = set(_norms(expected["service_languages"]))
        gn = set(_norms(got.get("service_languages", [])))
        scores["service_languages"] = exp.issubset(gn)
    if "programs_must_include_any" in expected:
        gn = " ".join(_norms(got.get("programs", [])))
        scores["programs"] = any(_norm(x) in gn for x in expected["programs_must_include_any"])
    if "vibe_tags_must_include_any" in expected:
        gn = " ".join(_norms(got.get("vibe_tags", [])))
        scores["vibe_tags"] = any(_norm(x) in gn for x in expected["vibe_tags_must_include_any"])
    return scores


def run() -> dict:
    examples = _load_golden(GOLDEN)
    per_example = []
    field_totals: dict[str, list[bool]] = {}
    for ex in examples:
        got = website_extract.call_llm(ex["input_text"])
        norm = website_extract._normalize(got)
        scores = _score_one(ex["expected"], norm)
        per_example.append({"name": ex["name"], "scores": scores, "got": norm})
        for f, ok in scores.items():
            field_totals.setdefault(f, []).append(ok)
    summary = {
        "n": len(examples),
        "fields": {f: sum(xs) / len(xs) for f, xs in field_totals.items()},
    }
    return {"summary": summary, "examples": per_example, "prompt_version": website_extract.PROMPT_VERSION}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", type=Path)
    parser.add_argument("--baseline", type=Path, help="Compare against prior report; gate on >10% drop")
    args = parser.parse_args(argv)

    report = run()
    print(json.dumps(report["summary"], indent=2))

    if args.save:
        args.save.write_text(json.dumps(report, indent=2))
        print(f"saved → {args.save}")

    if args.baseline and args.baseline.exists():
        prev = json.loads(args.baseline.read_text())["summary"]["fields"]
        regressed = []
        for f, score in report["summary"]["fields"].items():
            if f in prev and score < prev[f] - 0.10:
                regressed.append((f, prev[f], score))
        if regressed:
            print(f"REGRESSION vs baseline:")
            for f, p, n in regressed:
                print(f"  {f}: {p:.2f} → {n:.2f}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
