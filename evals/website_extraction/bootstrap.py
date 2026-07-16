"""Bootstrap golden examples from real church websites — no hand-labeling.

Samples churches with websites from the live public API (or a URL list),
fetches and cleans each homepage the same way the production pipeline does
(trafilatura), then labels it with a *stronger* model than production using
the identical v3 prompt. The strong model's structured fields become the
golden `expected`; prose fields are left to the LLM judge (judge.py).

Disagreement mining: the production model (gemini flash) also extracts each
page, and its structured fields are compared against the reference labels.
Pages where both models agree are appended as `Example:` (trusted); pages
where they disagree are appended as `DRAFT:` — those few are the only ones
worth a human glance. Disagreements are listed in the section metadata.

Usage:
    # Sample 10 churches with websites from a city via the live API
    python -m evals.website_extraction.bootstrap --city Brooklyn --state NY --n 10

    # Label specific URLs (one per line; blank lines and # comments ignored)
    python -m evals.website_extraction.bootstrap --urls urls.txt

    # Preview sections without touching golden.md
    python -m evals.website_extraction.bootstrap --city Chicago --state IL --n 3 --dry-run

Appends to golden.md and recompiles golden.jsonl. Already-present URLs are
skipped, so re-running is idempotent.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import trafilatura

from backend.env_loader import load_env_local

load_env_local()

from backend.scrapers_v2.extract import (
    MAX_INPUT_CHARS,
    call_llm,
    normalize_extraction,
)
from backend.scrapers_v2.prompts.website_v3 import MODEL as PRODUCTION_MODEL
from evals.website_extraction.compile import compile_md
from evals.website_extraction.run import score_one

HERE = Path(__file__).parent
GOLDEN_MD = HERE / "golden.md"

REF_MODEL = os.environ.get("EVAL_REF_MODEL", "google/gemini-2.5-pro")
DEFAULT_API_BASE = "https://churchmap-api.onrender.com"
PAGE_TIMEOUT_S = 30.0
USER_AGENT = "ChurchMapBot/eval-bootstrap (+https://churchmap.vercel.app)"

# Structured fields the deterministic scorer handles; everything else is
# judged against the source text at eval time, not baked into `expected`.
STRUCTURED_FIELDS = ("denomination", "theological_stance", "service_languages", "worship_style")


def build_expected(ref_fields: dict) -> dict:
    """Golden `expected` from reference labels: structured fields only,
    omitting null/empty ones (the scorer skips absent keys — we can't
    reliably assert absence)."""
    expected: dict = {}
    if ref_fields.get("denomination"):
        expected["denomination"] = ref_fields["denomination"]
    if ref_fields.get("theological_stance"):
        expected["theological_stance"] = ref_fields["theological_stance"]
    if ref_fields.get("service_languages"):
        expected["service_languages"] = ref_fields["service_languages"]
    if ref_fields.get("worship_style"):
        expected["worship_style"] = ref_fields["worship_style"]
    return expected


def find_disagreements(expected: dict, flash_fields: dict) -> list[str]:
    """Structured fields where production output fails the reference labels,
    formatted for the section metadata."""
    scores = score_one(expected, flash_fields)
    out = []
    for field, ok in scores.items():
        if ok:
            continue
        ref_v = expected.get(field)
        got_v = flash_fields.get(field)
        out.append(f"{field} (production: {json.dumps(got_v, ensure_ascii=False)} / reference: {json.dumps(ref_v, ensure_ascii=False)})")
    return out


def _sanitize_text(text: str) -> str:
    """Keep the text safe inside a ```text fence."""
    return text.replace("```", "'''").replace("\x00", "")


def _sanitize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lstrip("#").strip() or "Unnamed church"


def render_section(
    *,
    name: str,
    url: str,
    church_id: int | None,
    input_text: str,
    expected: dict,
    disagreements: list[str],
    ref_model: str = REF_MODEL,
    today: dt.date | None = None,
) -> str:
    today = today or dt.date.today()
    status = "DRAFT" if disagreements else "Example"
    lines = [
        f"## {status}: {_sanitize_name(name)} (auto)",
        "",
        f"- URL: {url}",
        f"- Church ID: {church_id if church_id is not None else 'null'}",
        f"- Labeled by: {ref_model} on {today.isoformat()} (bootstrap)",
    ]
    if disagreements:
        lines.append(f"- Disagreements vs {PRODUCTION_MODEL}: " + "; ".join(disagreements))
    else:
        lines.append(f"- Agreement: {PRODUCTION_MODEL} matched all structured reference labels")
    lines += [
        "",
        "```text",
        _sanitize_text(input_text),
        "```",
        "",
        "```json",
        json.dumps(expected, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def existing_urls(md_text: str) -> set[str]:
    urls = set()
    for m in re.finditer(r"(?m)^\s*-\s*URL:\s*(\S+)", md_text):
        u = m.group(1).strip().strip("_*` ")
        if u.lower() not in {"synthetic", "null", "none"}:
            urls.add(u.rstrip("/"))
    return urls


def _normalize_url(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


async def _candidates_from_api(
    client: httpx.AsyncClient, api_base: str, city: str, state: str
) -> list[dict]:
    url = f"{api_base}/api/churches?city={quote(city)}&state={quote(state)}&limit=200"
    r = await client.get(url)
    r.raise_for_status()
    return [
        {"name": c["name"], "church_id": c["id"], "url": _normalize_url(c["website"])}
        for c in r.json()
        if c.get("website")
    ]


def _candidates_from_file(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url = _normalize_url(line)
        name = re.sub(r"^www\.", "", httpx.URL(url).host or url)
        out.append({"name": name, "church_id": None, "url": url})
    return out


async def _fetch_clean_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n\n[...truncated]"
    return text


async def _bootstrap(args: argparse.Namespace) -> int:
    if args.urls:
        candidates = _candidates_from_file(args.urls)
    else:
        async with httpx.AsyncClient(timeout=30.0) as api_client:
            candidates = await _candidates_from_api(api_client, args.api_base, args.city, args.state)

    md_text = GOLDEN_MD.read_text()
    seen = existing_urls(md_text)

    added: list[str] = []
    flagged: list[str] = []
    skipped: list[tuple[str, str]] = []
    sections: list[str] = []

    page_client = httpx.AsyncClient(
        timeout=PAGE_TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    llm_client = httpx.AsyncClient(timeout=90.0)
    try:
        for cand in candidates:
            if len(added) + len(flagged) >= args.n:
                break
            url = cand["url"]
            if url.rstrip("/") in seen:
                skipped.append((cand["name"], "already in golden set"))
                continue

            text = await _fetch_clean_text(page_client, url)
            if text is None or len(text) < args.min_chars:
                skipped.append((cand["name"], "fetch failed or too little text"))
                continue

            try:
                ref_raw = await call_llm(text, client=llm_client, model=args.ref_model)
                flash_raw = await call_llm(text, client=llm_client)
            except Exception as e:
                skipped.append((cand["name"], f"LLM error: {type(e).__name__}"))
                continue

            ref_fields = normalize_extraction(ref_raw, text)["fields"]
            flash_fields = normalize_extraction(flash_raw, text)["fields"]

            if not any(ref_fields.get(k) for k in (*STRUCTURED_FIELDS, "community_summary")):
                skipped.append((cand["name"], "reference model found no signal (junk page?)"))
                continue

            expected = build_expected(ref_fields)
            disagreements = find_disagreements(expected, flash_fields)
            sections.append(
                render_section(
                    name=cand["name"],
                    url=url,
                    church_id=cand["church_id"],
                    input_text=text,
                    expected=expected,
                    disagreements=disagreements,
                    ref_model=args.ref_model,
                )
            )
            seen.add(url.rstrip("/"))
            if disagreements:
                flagged.append(cand["name"])
                print(f"  DRAFT   {cand['name']} — {'; '.join(disagreements)}")
            else:
                added.append(cand["name"])
                print(f"  Example {cand['name']}")
    finally:
        await page_client.aclose()
        await llm_client.aclose()

    if not sections:
        print("nothing to add", file=sys.stderr)
        for name, why in skipped:
            print(f"  skipped {name}: {why}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n--- dry run: sections not written ---\n")
        print("\n---\n\n".join(sections))
    else:
        with GOLDEN_MD.open("a") as f:
            f.write("\n---\n\n" + "\n---\n\n".join(sections))
        compile_md()

    print(
        f"\nadded {len(added)} trusted, {len(flagged)} DRAFT (model disagreement — "
        f"review these), skipped {len(skipped)}"
    )
    if flagged:
        print("review the DRAFT sections in golden.md, then rename to 'Example:' to include them as trusted")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--city", help="Sample churches from this city via the live API (requires --state)")
    src.add_argument("--urls", type=Path, help="File of website URLs, one per line")
    parser.add_argument("--state", help="Two-letter state for --city")
    parser.add_argument("--n", type=int, default=10, help="Examples to add (default 10)")
    parser.add_argument("--min-chars", type=int, default=400,
                        help="Skip pages whose cleaned text is shorter than this (default 400)")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--ref-model", default=REF_MODEL,
                        help=f"Reference labeling model (default {REF_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="Print sections instead of writing golden.md")
    args = parser.parse_args(argv)

    if args.city and not args.state:
        parser.error("--city requires --state")

    return asyncio.run(_bootstrap(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
