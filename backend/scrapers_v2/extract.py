"""Extract stage: read R2 HTML for pending artifacts, call LLM, write structured JSON.

Reads grouped pending artifacts (one church at a time, all kinds combined),
runs trafilatura per page, concatenates in kind-priority order, calls
OpenRouter/Gemini Flash with the v3 prompt, validates the response, writes
extracted_tags + confidence + source snippets back to churches.

Backoff: 1s, 4s, 16s on 429/5xx. Non-retryable on 4xx auth/bad request.

Failure routing matters more than it looks, because two of the four outcomes
are irreversible — `requeue` only ever puts 'ok' artifacts back, so anything
marked 'skipped' or 'error' is out of the corpus for good:

    cause                     artifacts   church status     way back
    ------------------------  ----------  ----------------  ------------------
    R2 unreachable            pending     transient:r2-...  automatic, next run
    R2 key absent             skipped     no-html:n/m       re-fetch the site
    page has no usable text   skipped     no-text           none (correct)
    model returned junk       error       error:...         none (correct)
    LLM/network blip          pending     transient:...     automatic, next run

The first row is the one worth being careful about: an unreachable bucket
produces exactly the same "no text" symptom as an empty page, and routing it
to the second row would quietly delete the backfill one batch at a time.

Source-snippet validation: the model must return verbatim substrings of the
input text. Non-substrings are dropped silently rather than failing the
entire extraction — confidence drop is the signal, not a hard error.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
import trafilatura

from backend.db.repository import CrawlRepository
from backend.scrapers_v2 import r2 as r2mod
from backend.scrapers_v2.prompts.website_v3 import (
    MODEL,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    THEOLOGICAL_STANCES,
    WORSHIP_STYLES,
)

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_INPUT_CHARS = 18_000
HTTP_TIMEOUT_S = 60.0
RETRY_DELAYS_S = [1.0, 4.0, 16.0]
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class ExtractionError(Exception):
    """Terminal extraction error: bad JSON, schema mismatch, response shape.
    These are about the model's output, not the upstream connection — retrying
    won't help, so artifacts get marked 'error'."""


class TransientExtractionError(Exception):
    """Recoverable extraction error: upstream timeouts/5xx/429 after retries,
    missing API key, network failures. Artifacts stay 'pending' so the next
    cron run picks them up once the underlying issue clears."""


def _truncate(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...truncated]"


@dataclass
class GatheredText:
    """What came back from R2, and why it was thin if it was.

    "No text" used to be one outcome with three causes — the object is gone,
    the bucket is unreachable, or the page really is empty — and they need
    opposite responses: re-fetch, retry, and give up respectively. Collapsing
    them meant a re-extraction batch could report a wall of `no-text` that
    said nothing about which. Counting them here is what makes the answer
    readable off `/api/stats` instead of off the Render logs.
    """
    text: str
    keys: int = 0
    missing: int = 0      # R2 says the object is not there — needs re-fetching
    unreadable: int = 0   # R2 could not be read at all — transient, retry


def _gather_text_from_r2(
    r2: r2mod.R2Client, kinds: list[str], r2_keys: list[str]
) -> GatheredText:
    """Read raw HTML from R2 and run trafilatura per page; concatenate in
    kind-priority order (already sorted by SQL)."""
    parts: list[str] = []
    out = GatheredText(text="", keys=len(r2_keys))
    for kind, key in zip(kinds, r2_keys):
        try:
            raw = r2.get_html(key)
        except r2mod.R2NotFound:
            # The archive does not have this page. Nothing to extract, ever.
            out.missing += 1
            log.warning("R2 key absent: %s", key)
            continue
        except r2mod.R2Error as e:
            # Auth, throttling, a Cloudflare 5xx, missing credentials. The page
            # may well be fine — do not let this masquerade as an empty page.
            out.unreadable += 1
            log.warning("R2 get failed for %s: %s", key, e)
            continue
        try:
            html = raw.decode("utf-8", errors="replace")
            text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
            text = text.strip()
        except Exception:
            text = ""
        if text:
            parts.append(f"# {kind}\n{text}")
    out.text = _truncate("\n\n".join(parts))
    return out


def _parse_json_object(content: str) -> dict[str, Any]:
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise ExtractionError(f"no JSON object in model output: {content[:200]}")
    return json.loads(s[start : end + 1])


async def call_llm(
    text: str,
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    model: str = MODEL,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        # Treat as transient: ops can fix the env var and the next run picks up.
        raise TransientExtractionError("OPENROUTER_API_KEY not set")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Website text follows:\n\n{text}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://churchmap.vercel.app",
        "X-Title": "ChurchMap website extraction",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    try:
        last_err: str | None = None
        for attempt, delay in enumerate([0.0] + RETRY_DELAYS_S):
            if delay:
                await asyncio.sleep(delay)
            try:
                r = await client.post(OPENROUTER_URL, json=payload, headers=headers)
            except httpx.HTTPError as e:
                last_err = f"http:{type(e).__name__}"
                continue
            if r.status_code == 200:
                body = r.json()
                try:
                    content = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as e:
                    raise ExtractionError(f"unexpected response shape: {e}")
                # A 200 with null/empty content happens (upstream filtering, a
                # reasoning-only completion). Retry it like any other blip
                # rather than dying on `None.strip()` — an empty completion is
                # exactly the kind of thing that succeeds on the next attempt.
                if not isinstance(content, str) or not content.strip():
                    last_err = "empty-content"
                    continue
                return _parse_json_object(content)
            if r.status_code in RETRYABLE_STATUS:
                last_err = f"upstream-{r.status_code}"
                continue
            # Non-retryable (auth, bad request, etc.) — treat as transient
            # because it's almost always a config or quota issue ops can fix
            # without resetting per-artifact state.
            raise TransientExtractionError(
                f"OpenRouter HTTP {r.status_code}: {r.text[:200]}"
            )
        raise TransientExtractionError(f"upstream gave up after retries: {last_err}")
    finally:
        if owns_client:
            await client.aclose()


def _s(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) else None


def _clamp(v: Any, n: int) -> str:
    s = _s(v) or ""
    return s[:n].rstrip()


def _lst(v: Any, item_max: int | None = None) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        t = _s(x) or ""
        if not t:
            continue
        if item_max:
            t = t[:item_max].rstrip()
        out.append(t)
    return out


def normalize_extraction(obj: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Validate and normalize the model's JSON. Drops bad source snippets;
    coerces enum fields to None on miss."""
    stance = obj.get("theological_stance")
    style = obj.get("worship_style")

    norm = {
        "denomination":         _s(obj.get("denomination")),
        "theological_stance":   stance if stance in THEOLOGICAL_STANCES else None,
        "service_languages":    _lst(obj.get("service_languages")),
        "programs":             _lst(obj.get("programs")),
        "vibe_tags":            _lst(obj.get("vibe_tags")),
        "community_summary":    _clamp(obj.get("community_summary") or obj.get("summary"), 240),
        "theology_summary":     _clamp(obj.get("theology_summary"), 240),
        "worship_style":        style if style in WORSHIP_STYLES else None,
        "worship_style_detail": _clamp(obj.get("worship_style_detail"), 160),
        "pull_quote":           _clamp(obj.get("pull_quote"), 240),
        "statement_of_faith":   _lst(obj.get("statement_of_faith"), item_max=160)[:8],
    }

    raw_conf = obj.get("_confidence") or {}
    confidence: dict[str, float] = {}
    if isinstance(raw_conf, dict):
        for k, v in raw_conf.items():
            if not isinstance(k, str):
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if 0.0 <= f <= 1.0:
                confidence[k] = f

    raw_snip = obj.get("_source_snippets") or {}
    snippets: dict[str, str] = {}
    if isinstance(raw_snip, dict):
        for k, v in raw_snip.items():
            s = _s(v)
            if not isinstance(k, str) or not s:
                continue
            # Verbatim substring check — drop if the model fabricated.
            if s[:160] in source_text:
                snippets[k] = s[:160]

    return {"fields": norm, "confidence": confidence, "snippets": snippets}


async def extract_for_church(
    repo: CrawlRepository,
    r2: r2mod.R2Client,
    *,
    church_id: int,
    artifact_ids: list[int],
    kinds: list[str],
    r2_keys: list[str],
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    got = _gather_text_from_r2(r2, kinds, r2_keys)
    text = got.text
    if not text:
        # Three different reasons to have no text, and only one of them means
        # "give up on this church". Marking artifacts 'skipped' is permanent —
        # `requeue` only puts 'ok' artifacts back — so a bucket that is merely
        # unreachable must never reach that branch. Rotated R2 credentials
        # would otherwise burn every artifact in the batch, silently, at the
        # rate the cron runs.
        if got.unreadable:
            detail = f"r2-unreadable:{got.unreadable}/{got.keys}"
            log.warning("extract cannot read R2 for church=%s: %s", church_id, detail)
            await repo.mark_church_extract_error(church_id, f"transient:{detail}")
            return False
        if got.missing:
            # The archive lost (or never held) the HTML. Re-extraction can
            # never fix this; re-*fetching* is the only route back, so say so
            # in the status rather than filing it under "page was empty".
            detail = f"no-html:{got.missing}/{got.keys}"
            await repo.mark_artifacts_status(artifact_ids, status="skipped", error_detail=detail)
            await repo.mark_church_extract_error(church_id, detail)
            return False
        await repo.mark_artifacts_status(artifact_ids, status="skipped", error_detail="no-text")
        await repo.mark_church_extract_error(church_id, "no-text")
        return False

    try:
        raw = await call_llm(text, api_key=api_key, client=client)
    except TransientExtractionError as e:
        # Leave artifacts as 'pending' so the next cron run retries them
        # automatically once OpenRouter recovers / API key is restored.
        # Just bump the church-level status so /status visibility shows it.
        log.warning("extract transient failure church=%s: %s", church_id, e)
        await repo.mark_church_extract_error(church_id, f"transient:{type(e).__name__}")
        return False
    except ExtractionError as e:
        detail = str(e)[:4000]
        await repo.mark_artifacts_status(artifact_ids, status="error", error_detail=detail)
        await repo.mark_church_extract_error(church_id, f"error:{type(e).__name__}")
        return False
    except Exception as e:
        # Unknown failure mode — keep artifacts retryable, log loudly.
        log.exception("extract unexpected failure church=%s: %s", church_id, e)
        detail = f"unexpected:{type(e).__name__}:{str(e)[:200]}"
        await repo.mark_church_extract_error(church_id, f"transient:unexpected:{detail[:100]}")
        return False

    norm = normalize_extraction(raw, text)
    fields = norm["fields"]

    tags = {
        "theological_stance":   fields["theological_stance"],
        "service_languages":    fields["service_languages"],
        "programs":             fields["programs"],
        "vibe_tags":            fields["vibe_tags"],
        "theology_summary":     fields["theology_summary"] or None,
        "worship_style":        fields["worship_style"],
        "worship_style_detail": fields["worship_style_detail"] or None,
        "pull_quote":           fields["pull_quote"] or None,
        "statement_of_faith":   fields["statement_of_faith"],
    }

    await repo.write_extraction(
        church_id,
        website_summary=fields["community_summary"] or None,
        extracted_tags=tags,
        denomination=fields["denomination"],
        prompt_version=PROMPT_VERSION,
        model=MODEL,
        confidence=norm["confidence"],
        source_snippets=norm["snippets"],
    )
    await repo.mark_artifacts_status(artifact_ids, status="ok")
    return True


async def run_extract_batch(
    repo: CrawlRepository,
    r2: r2mod.R2Client,
    *,
    batch_size: int,
) -> dict:
    targets = await repo.pending_extract_targets(limit=batch_size)
    rows_processed = 0
    rows_ok = 0
    rows_error = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        for t in targets:
            rows_processed += 1
            try:
                ok = await extract_for_church(
                    repo, r2,
                    church_id=t["church_id"],
                    artifact_ids=list(t["artifact_ids"]),
                    kinds=list(t["kinds"]),
                    r2_keys=list(t["r2_keys"]),
                    client=client,
                )
                if ok:
                    rows_ok += 1
                else:
                    rows_error += 1
            except Exception as e:
                log.exception("extract failed church=%s: %s", t["church_id"], e)
                rows_error += 1
    return {"rows_processed": rows_processed, "rows_ok": rows_ok, "rows_error": rows_error}
