"""A church whose fetch can't be recorded is re-selected first in every batch.

churches_due_for_fetch orders by the last homepage attempt, NULLS FIRST. A
church that raises before its homepage artifact is written keeps its old (or
NULL) attempt time, so it heads every batch and fails every batch: from
2026-10-26 every fetch run came back `partial` with the same 2 errors.

The cause found: robots.txt bodies Postgres can't store. Three hosts send
robots.txt Brotli-compressed despite `Accept-Encoding: gzip, deflate`; httpx
without a Brotli decoder hands back the compressed bytes, NULs included. A
fourth serves a 128 KB page full of NULs at /robots.txt.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest

from backend.scrapers_v2 import fetch as fetch_mod
from backend.scrapers_v2.robots import get_parser

# The first bytes oneholyfamily.org returned for /robots.txt on 2026-11-03.
BROTLI_ROBOTS = b"\xa18\x02\x00 \xe66\xeaW\xd2\xe5\x81\xd2/\x1b\x9a\x18\xe2\xc2\xc0\x0fWt\x8c"


class Repo:
    """Refuses NUL in text like psycopg does, and records what was written."""

    def __init__(self):
        self.robots: dict[str, str] = {}
        self.inserts: list[dict] = []

    async def get_robots(self, host):
        return None

    async def upsert_robots(self, host, body, ttl_seconds):
        if "\x00" in body:
            raise ValueError("PostgreSQL text fields cannot contain NUL (0x00) bytes")
        self.robots[host] = body

    async def insert_artifact(self, **kw):
        self.inserts.append(kw)
        return 1


def _client(robots_body: bytes, headers=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, content=robots_body, headers=headers or {})
        return httpx.Response(200, content=b"<html><body><p>Sunday worship 10am.</p></body></html>")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_an_unreadable_robots_txt_disallows_and_is_not_cached():
    async def main():
        repo = Repo()
        async with _client(BROTLI_ROBOTS, {"content-encoding": "identity"}) as client:
            rp = await get_parser(repo, client, "https://www.oneholyfamily.org/")
        return repo, rp

    repo, rp = asyncio.run(main())
    assert repo.robots == {}  # never handed to Postgres
    assert not rp.can_fetch(fetch_mod.USER_AGENT, "https://www.oneholyfamily.org/")


def test_a_church_with_unreadable_robots_gets_an_artifact_and_backs_off(monkeypatch):
    monkeypatch.setattr(fetch_mod, "PER_DOMAIN_DELAY_S", 0)

    async def main():
        repo = Repo()
        async with _client(BROTLI_ROBOTS, {"content-encoding": "identity"}) as client:
            await fetch_mod.fetch_church(client, repo, None, 23227, "https://www.oneholyfamily.org/", 9)
        return repo

    repo = asyncio.run(main())
    assert [(r["kind"], r["fetch_error"], r["robots_allowed"]) for r in repo.inserts] == \
        [("homepage", "robots-disallow", False)]


def test_a_readable_robots_txt_still_allows():
    async def main():
        repo = Repo()
        async with _client(b"User-agent: *\nDisallow: /private\n") as client:
            rp = await get_parser(repo, client, "https://example.org/")
        return repo, rp

    repo, rp = asyncio.run(main())
    assert repo.robots == {"example.org": "User-agent: *\nDisallow: /private\n"}
    assert rp.can_fetch(fetch_mod.USER_AGENT, "https://example.org/")
    assert not rp.can_fetch(fetch_mod.USER_AGENT, "https://example.org/private")


class BatchRepo(Repo):
    con = SimpleNamespace(transaction=nullcontext)

    def __init__(self, targets):
        super().__init__()
        self.targets = targets

    async def churches_due_for_fetch(self, limit, fresh_days):
        return self.targets


@pytest.mark.parametrize("error", [ValueError, TimeoutError])
def test_a_church_that_raises_is_recorded_so_it_backs_off(monkeypatch, error):
    async def boom(client, repo, r2, church_id, website, crawl_run_id, **kw):
        if church_id == 2:
            raise error("fetch failed independently of the batch deadline")
        return 1

    monkeypatch.setattr(fetch_mod, "fetch_church", boom)
    repo = BatchRepo([{"church_id": 1, "website": "https://a.example/"},
                      {"church_id": 2, "website": "https://b.example/"}])
    out = asyncio.run(fetch_mod.run_fetch_batch(repo, None, batch_size=50, fresh_days=30, crawl_run_id=9))

    assert (out["rows_processed"], out["rows_ok"], out["rows_error"]) == (2, 1, 1)
    assert out["errors"] == [{"church_id": 2, "error": error.__name__}]
    assert [(r["church_id"], r["kind"], r["http_status"], r["fetch_error"], r["content_hash"])
            for r in repo.inserts] == [(2, "homepage", 0, f"exception:{error.__name__}", None)]


def test_a_failure_to_record_the_failure_does_not_stop_the_batch(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("x")

    class NoWrites(BatchRepo):
        async def insert_artifact(self, **kw):
            raise RuntimeError("database gone")

    monkeypatch.setattr(fetch_mod, "fetch_church", boom)
    repo = NoWrites([{"church_id": 1, "website": "https://a.example/"},
                     {"church_id": 2, "website": "https://b.example/"}])
    out = asyncio.run(fetch_mod.run_fetch_batch(repo, None, batch_size=50, fresh_days=30, crawl_run_id=9))
    assert (out["rows_processed"], out["rows_error"]) == (2, 2)
