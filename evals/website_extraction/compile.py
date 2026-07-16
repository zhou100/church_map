"""Compile golden.md → golden.jsonl.

golden.md is the human-editable source of truth; golden.jsonl is the
machine-readable artifact consumed by run.py. Always regenerate by running:

    python -m evals.website_extraction.compile

Format expected in golden.md (per example):

    ## <Name>

    - URL: <url or "synthetic">
    - Church ID: <int or "null">

    ```text
    <cleaned input text fed to the LLM>
    ```

    ```json
    { "denomination": "...", ... }
    ```

Anything above the first `## ` heading is treated as documentation and ignored.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
MD = HERE / "golden.md"
OUT = HERE / "golden.jsonl"

# Match a fenced block starting with ```<lang>\n ... \n```
# Use re.DOTALL on the body. lang is optional; we filter by lang after.
_FENCE = re.compile(r"^```([a-zA-Z0-9_-]*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


_PLACEHOLDER_RE = re.compile(r"^[\(\[]?\s*fill\s+in\b", re.IGNORECASE)


def _is_placeholder(val: str) -> bool:
    """True for editor-placeholder strings like `_(fill in — ...)_`."""
    return bool(_PLACEHOLDER_RE.match(val)) or val.lower() in {"null", "none", "n/a", "synthetic", ""}


def _parse_meta(section: str) -> tuple[str | None, int | None]:
    """Extract `- URL:` and `- Church ID:` from the bullet block."""
    url, cid = None, None
    for line in section.splitlines():
        m = re.match(r"\s*-\s*URL:\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip("_*` ")
            if not _is_placeholder(val):
                url = val
            continue
        m = re.match(r"\s*-\s*Church ID:\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip("_*` ")
            if not _is_placeholder(val):
                try:
                    cid = int(val)
                except ValueError:
                    pass
    return url, cid


def _extract_blocks(section: str) -> tuple[str | None, dict | None]:
    """Pull the first text/plain fence and the first json fence."""
    input_text: str | None = None
    expected: dict | None = None
    for lang, body in _FENCE.findall(section):
        lang = lang.lower()
        if input_text is None and lang in {"", "text", "txt", "plain"}:
            input_text = body.rstrip("\n")
        elif expected is None and lang == "json":
            try:
                expected = json.loads(body)
            except json.JSONDecodeError as e:
                raise SystemExit(f"invalid JSON in section: {e}\n---\n{body}\n---")
    return input_text, expected


def compile_md(md_path: Path = MD, out_path: Path = OUT) -> int:
    text = md_path.read_text()
    # Split on top-level H2 headings. Keep the heading itself with each chunk.
    parts = re.split(r"(?m)^##\s+", text)
    # parts[0] is preamble before the first heading — discard.
    examples: list[dict] = []
    for chunk in parts[1:]:
        head, _, body = chunk.partition("\n")
        name = head.strip()
        if not name:
            continue
        # Only treat sections whose heading begins with Example:/DRAFT: as data.
        # Everything else (e.g. `## Format`) is documentation.
        if not re.match(r"(?i)^(example|draft)\s*:", name):
            continue
        url, cid = _parse_meta(body)
        input_text, expected = _extract_blocks(body)
        if input_text is None:
            print(f"warn: '{name}' has no input-text fence — skipped", file=sys.stderr)
            continue
        if expected is None:
            print(f"warn: '{name}' has no json fence — using empty expected", file=sys.stderr)
            expected = {}
        record: dict = {
            "church_id": cid,
            "name": name,
            "input_text": input_text,
            "expected": expected,
        }
        if url and url.lower() != "synthetic":
            record["url"] = url
        examples.append(record)

    lines = [json.dumps(rec, ensure_ascii=False) for rec in examples]
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(examples)} examples → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(compile_md())
