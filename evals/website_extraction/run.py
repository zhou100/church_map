"""Evaluate website-extraction quality against a golden set.

Calls the live v3 extractor (scrapers_v2) on each example and scores
per-field precision. Structured fields (denomination, theological_stance,
service_languages, worship_style) score deterministically against the
golden `expected` dict; prose fields (summaries, tags, pull quote) are
scored by an LLM judge against the source text when --judge is passed
(see judge.py). Outputs a JSON report and exits non-zero if any field
drops >threshold vs --baseline (a previously saved report).

Usage:
    # Live: run the LLM on every golden, print scores
    python -m evals.website_extraction.run

    # Live with judge scoring for prose fields, persisting a cache
    python -m evals.website_extraction.run --judge --save-cache cache.json

    # Offline: score from a saved cache (no LLM, CI-safe)
    python -m evals.website_extraction.run --judge --from-cache cache.json

    # Save a baseline report (after a known-good run)
    python -m evals.website_extraction.run --judge --save baselines/2026-07-16.v3.json

    # Gate: fail the build if any field regresses >10% vs baseline
    python -m evals.website_extraction.run --judge \
        --from-cache cache.json \
        --baseline baselines/2026-07-16.v3.json \
        --threshold 0.10

Cache format (v2): {name: {"extraction": <normalize dict>, "judge": <verdicts|null>}}.
v1 caches ({name: <normalize dict>}) still load; their judge verdicts are
fetched live if --judge is set.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from backend.env_loader import load_env_local

load_env_local()

from backend.scrapers_v2.extract import call_llm, normalize_extraction
from backend.scrapers_v2.prompts.website_v3 import MODEL, PROMPT_VERSION, SYSTEM_PROMPT
from evals.website_extraction.judge import (
    JUDGE_FIELDS,
    JUDGE_MODEL,
    JUDGE_VERSION,
    judge_example,
    verbatim_pull_quote_ok,
)

GOLDEN = Path(__file__).parent / "golden.jsonl"


def prompt_fingerprint(model: str = MODEL) -> str:
    """Short hash of the exact prompt AND model that produced a report.

    Cached extractions are only meaningful for the prompt they were made
    with, and PROMPT_VERSION is a hand-maintained string that an edit can
    forget to bump. Stamping the real content hash into every report lets
    the CI gate (gate.py) refuse to score a changed prompt against a stale
    cache instead of passing vacuously.

    The model is in the hash for the same reason. Swapping
    gemini-2.5-flash for flash-lite changes the output every bit as much as
    editing the prompt does, and an earlier version of this function hashed
    only the prompt — so a model swap sailed through the gate against a
    cache built by a different model. Same failure, different lever.
    """
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    h.update(b"\0")
    h.update(SYSTEM_PROMPT.encode())
    h.update(b"\0")
    h.update(model.encode())
    return h.hexdigest()[:16]


def threshold_for(field: str, strict: float, judged: float) -> float:
    """Regression band for one field. Judged fields get a wider one.

    Measured 2026-07-24 by running the identical prompt twice over the same
    18 goldens: every deterministically scored field was bit-identical across
    runs, while `vibe_tags` moved 0.667 → 0.778. A 0.111 swing from nothing
    but sampling is already wider than the 0.10 default, so a single band
    would fail prompt PRs on noise — the fastest way to teach everyone to
    ignore the gate. The real fix is more examples (each one is worth ~0.056
    at n=18); until then, judged fields get room and the deterministic
    fields, which are the ones with a defensible right answer, stay strict.
    """
    return judged if field in JUDGE_FIELDS else strict


def _load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _norm(s):
    return (s or "").strip().lower()


def _norms(xs):
    return [_norm(x) for x in (xs or [])]


def score_one(expected: dict, fields: dict) -> dict[str, bool]:
    """Score a normalized extraction against a golden expected dict.

    `fields` is the flat field map from normalize_extraction(...)["fields"].
    `expected` may use exact keys (denomination, theological_stance,
    service_languages, worship_style) or *_must_include_any / *_min keys for
    soft-match fields.
    """
    scores: dict[str, bool] = {}
    if "denomination" in expected:
        exp = _norm(expected["denomination"])
        gn = _norm(fields.get("denomination"))
        scores["denomination"] = bool(exp) and bool(gn) and (exp in gn or gn in exp)
    if "theological_stance" in expected:
        scores["theological_stance"] = expected["theological_stance"] == fields.get("theological_stance")
    if "service_languages" in expected:
        exp_set = set(_norms(expected["service_languages"]))
        gn_set = set(_norms(fields.get("service_languages", [])))
        scores["service_languages"] = exp_set.issubset(gn_set)
    if "programs_must_include_any" in expected:
        gn = " ".join(_norms(fields.get("programs", [])))
        scores["programs"] = any(_norm(x) in gn for x in expected["programs_must_include_any"])
    if "vibe_tags_must_include_any" in expected:
        gn = " ".join(_norms(fields.get("vibe_tags", [])))
        scores["vibe_tags"] = any(_norm(x) in gn for x in expected["vibe_tags_must_include_any"])
    if "worship_style" in expected:
        scores["worship_style"] = expected["worship_style"] == fields.get("worship_style")
    if "community_summary_must_include_any" in expected:
        gn = _norm(fields.get("community_summary"))
        scores["community_summary"] = any(_norm(x) in gn for x in expected["community_summary_must_include_any"])
    if "theology_summary_must_include_any" in expected:
        gn = _norm(fields.get("theology_summary"))
        scores["theology_summary"] = any(_norm(x) in gn for x in expected["theology_summary_must_include_any"])
    if "worship_style_detail_must_include_any" in expected:
        gn = _norm(fields.get("worship_style_detail"))
        scores["worship_style_detail"] = any(_norm(x) in gn for x in expected["worship_style_detail_must_include_any"])
    if "pull_quote_must_include_any" in expected:
        gn = _norm(fields.get("pull_quote"))
        scores["pull_quote"] = any(_norm(x) in gn for x in expected["pull_quote_must_include_any"])
    if "statement_of_faith_min" in expected:
        scores["statement_of_faith"] = len(fields.get("statement_of_faith") or []) >= expected["statement_of_faith_min"]
    return scores


def merge_judge_scores(
    det_scores: dict[str, bool],
    verdicts: dict[str, dict],
    fields: dict,
    input_text: str,
) -> dict[str, bool]:
    """Fold judge verdicts into the deterministic scores.

    Deterministic wins: a field already scored from `expected` (hand-written
    canaries use *_must_include_any keys) keeps its score. Judge fills the
    rest. pull_quote additionally requires the quote to appear verbatim in
    the source text — that part never needs an LLM's opinion.
    """
    merged = dict(det_scores)
    for field, v in verdicts.items():
        if field in merged:
            continue
        ok = v["ok"]
        if field == "pull_quote":
            ok = ok and verbatim_pull_quote_ok(fields.get("pull_quote"), input_text)
        merged[field] = ok
    return merged


def load_cache(path: Path) -> dict[str, dict]:
    """Load a cache file, upgrading v1 entries ({name: <norm>}) to v2.

    Underscore-prefixed keys are metadata (`_meta`), not examples.
    """
    raw = json.loads(path.read_text())
    cache: dict[str, dict] = {}
    for name, entry in raw.items():
        if name.startswith("_"):
            continue
        if isinstance(entry, dict) and "extraction" in entry:
            cache[name] = entry
        else:
            cache[name] = {"extraction": entry, "judge": None}
    return cache


def cache_meta(path: Path) -> dict:
    """The `_meta` block of a cache file, or {} for caches written before it."""
    raw = json.loads(path.read_text())
    meta = raw.get("_meta")
    return meta if isinstance(meta, dict) else {}


async def _extract_live(text: str, model: str = MODEL) -> dict:
    """Call the live LLM and normalize. Returns the full normalize dict."""
    raw = await call_llm(text, model=model)
    return normalize_extraction(raw, text)


async def _run(
    cache: dict | None,
    save_cache_to: Path | None,
    use_judge: bool,
    model: str = MODEL,
) -> dict:
    examples = _load_golden(GOLDEN)
    per_example: list[dict] = []
    field_totals: dict[str, list[bool]] = {}
    new_cache: dict[str, dict] = {}

    for ex in examples:
        name = ex["name"]
        cached = cache.get(name) if cache is not None else None

        if cached is not None:
            norm = cached["extraction"]
        else:
            norm = await _extract_live(ex["input_text"], model)

        fields = norm["fields"]
        scores = score_one(ex["expected"], fields)

        verdicts: dict[str, dict] | None = None
        if use_judge:
            if cached is not None and cached.get("judge") is not None:
                verdicts = cached["judge"]
            else:
                verdicts = await judge_example(ex["input_text"], fields)
            scores = merge_judge_scores(scores, verdicts, fields, ex["input_text"])

        entry = {"name": name, "scores": scores, "fields": fields}
        if verdicts is not None:
            entry["judge"] = verdicts
        per_example.append(entry)
        for f, ok in scores.items():
            field_totals.setdefault(f, []).append(ok)

        if save_cache_to is not None:
            new_cache[name] = {"extraction": norm, "judge": verdicts}

    if save_cache_to is not None:
        # Stamp the prompt these extractions came from. Without it, a cache
        # that outlives a prompt edit looks indistinguishable from a fresh
        # one and the CI gate would score the new prompt against old output.
        new_cache["_meta"] = {
            "prompt_version": PROMPT_VERSION,
            "prompt_fingerprint": prompt_fingerprint(model),
            "model": model,
            "judge_model": JUDGE_MODEL if use_judge else None,
            "judge_version": JUDGE_VERSION if use_judge else None,
        }
        save_cache_to.write_text(json.dumps(new_cache, indent=2))
        print(f"cache → {save_cache_to}")

    summary = {
        "n": len(examples),
        "fields": {f: sum(xs) / len(xs) for f, xs in field_totals.items()},
    }
    report = {
        "summary": summary,
        "examples": per_example,
        "prompt_version": PROMPT_VERSION,
        "prompt_fingerprint": prompt_fingerprint(model),
        "model": model,
    }
    if use_judge:
        report["judge_model"] = JUDGE_MODEL
        report["judge_version"] = JUDGE_VERSION
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", type=Path, help="Write the full report (use for baselines)")
    parser.add_argument("--baseline", type=Path, help="Compare against prior report; gate on >threshold drop")
    parser.add_argument("--threshold", type=float, default=0.10,
                        help="Precision drop that counts as a regression for deterministically scored fields (default 0.10)")
    parser.add_argument("--judge-threshold", type=float, default=0.15,
                        help="Same, for LLM-judged prose fields, which are noisier (default 0.15)")
    parser.add_argument("--from-cache", type=Path,
                        help="Score from cached extractions instead of calling the LLM (CI-safe)")
    parser.add_argument("--save-cache", type=Path,
                        help="Persist live extractions (and judge verdicts) so future runs can use --from-cache")
    parser.add_argument("--judge", action="store_true",
                        help="Score prose fields with the LLM judge (cached verdicts are reused; missing ones call the judge model live)")
    parser.add_argument("--model", default=MODEL,
                        help=f"Extraction model to evaluate (default {MODEL}). Changing this changes the "
                             "prompt fingerprint, so a run under a different model can't be scored against "
                             "another model's baseline by accident.")
    args = parser.parse_args(argv)

    cache: dict | None = None
    if args.from_cache:
        if not args.from_cache.exists():
            print(f"--from-cache file not found: {args.from_cache}", file=sys.stderr)
            return 2
        cache = load_cache(args.from_cache)

    report = asyncio.run(
        _run(cache=cache, save_cache_to=args.save_cache, use_judge=args.judge, model=args.model)
    )
    print(json.dumps(report["summary"], indent=2))

    if args.save:
        args.save.write_text(json.dumps(report, indent=2))
        print(f"saved → {args.save}")

    if args.baseline and args.baseline.exists():
        prev = json.loads(args.baseline.read_text())["summary"]["fields"]
        regressed = []
        for f, score in report["summary"]["fields"].items():
            if f in prev and score < prev[f] - threshold_for(f, args.threshold, args.judge_threshold):
                regressed.append((f, prev[f], score))
        if regressed:
            print("REGRESSION vs baseline:")
            for f, p, n in regressed:
                band = threshold_for(f, args.threshold, args.judge_threshold)
                print(f"  {f}: {p:.2f} → {n:.2f} (allowed drop {band:.2f})")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
