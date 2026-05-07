"""Voyage embedding step.

Embeds a per-church source string (summary + tags + denomination) using
voyage-3-lite (1024-dim, ~$0.02/1M tokens). Stores as float32 BLOB in
church_embeddings, keyed by church_id.

Use the in-memory numpy matmul path for similarity queries — fine up to
~50k vectors. Past that, swap for sqlite-vec (deferred TODO).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Iterable

import httpx

log = logging.getLogger(__name__)

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-3-lite"
DIM = 512
HTTP_TIMEOUT_S = 60.0
BATCH_SIZE = 32   # Voyage allows up to 128; keep batches small for backoff friendliness


class EmbeddingError(Exception):
    pass


def source_text_for(con: sqlite3.Connection, church_id: int) -> str | None:
    row = con.execute(
        "SELECT name, denomination, website_summary, extracted_tags FROM Churches WHERE church_id=?",
        (church_id,),
    ).fetchone()
    if not row:
        return None
    name, denom, summary, tags_json = row
    if not (summary or tags_json):
        return None
    parts: list[str] = [name or ""]
    if denom:
        parts.append(f"Denomination: {denom}")
    if summary:
        parts.append(summary)
    if tags_json:
        try:
            tags = json.loads(tags_json)
            for k in ("theological_stance", "service_languages", "programs", "vibe_tags"):
                v = tags.get(k)
                if not v:
                    continue
                if isinstance(v, list):
                    parts.append(f"{k.replace('_',' ')}: {', '.join(v)}")
                else:
                    parts.append(f"{k.replace('_',' ')}: {v}")
        except Exception:
            pass
    return "\n".join(p for p in parts if p).strip() or None


def _pack(vec: list[float]) -> bytes:
    if len(vec) != DIM:
        raise EmbeddingError(f"unexpected vector dim {len(vec)} (expected {DIM})")
    return struct.pack(f"{DIM}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))


def embed_batch(texts: list[str], *, api_key: str | None = None, client: httpx.Client | None = None) -> list[list[float]]:
    api_key = api_key or os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        raise EmbeddingError("VOYAGE_API_KEY not set")
    payload = {"input": texts, "model": MODEL, "input_type": "document"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns = client is None
    if owns:
        client = httpx.Client(timeout=HTTP_TIMEOUT_S)
    try:
        r = client.post(VOYAGE_URL, json=payload, headers=headers)
        if r.status_code != 200:
            raise EmbeddingError(f"Voyage HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        return [item["embedding"] for item in body["data"]]
    finally:
        if owns:
            client.close()


def embed_church(con: sqlite3.Connection, church_id: int, *, api_key: str | None = None) -> bool:
    text = source_text_for(con, church_id)
    if not text:
        return False
    [vec] = embed_batch([text], api_key=api_key)
    _store(con, church_id, vec, text)
    return True


def embed_many(con: sqlite3.Connection, church_ids: Iterable[int], *, api_key: str | None = None) -> int:
    pairs: list[tuple[int, str]] = []
    for cid in church_ids:
        txt = source_text_for(con, cid)
        if txt:
            pairs.append((cid, txt))
    if not pairs:
        return 0
    written = 0
    with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
        for i in range(0, len(pairs), BATCH_SIZE):
            chunk = pairs[i : i + BATCH_SIZE]
            vecs = embed_batch([t for _, t in chunk], api_key=api_key, client=client)
            for (cid, txt), vec in zip(chunk, vecs):
                _store(con, cid, vec, txt)
                written += 1
            con.commit()
    return written


def _store(con: sqlite3.Connection, church_id: int, vec: list[float], source_text: str) -> None:
    con.execute(
        """
        INSERT INTO church_embeddings (church_id, model, dim, vector, source_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(church_id) DO UPDATE SET
          model=excluded.model, dim=excluded.dim, vector=excluded.vector,
          source_text=excluded.source_text, created_at=excluded.created_at
        """,
        (church_id, MODEL, DIM, _pack(vec), source_text, datetime.now(timezone.utc).isoformat()),
    )
