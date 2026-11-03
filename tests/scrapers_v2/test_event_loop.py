"""The crawl stages run inside the API process (the cron only POSTs to
/api/admin/crawl/*), so a blocking call in their coroutines freezes every
search request until it returns. trafilatura parsing and boto3 R2 calls are
both blocking; these tests fail if either runs on the event loop again.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from backend.scrapers_v2 import extract as extract_mod
from backend.scrapers_v2 import fetch as fetch_mod
from backend.scrapers_v2 import r2 as r2mod

BLOCK_S = 0.3


async def _ticks_while(coro) -> tuple[object, int]:
    """Run coro alongside a 10 ms ticker; a blocked loop starves the ticker."""
    ticks = 0
    done = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # let the ticker start before the work does
    try:
        result = await coro
    finally:
        done.set()
        await t
    return result, ticks


class SlowR2:
    """Blocks like a boto3 call, then fails transiently so extract stops early."""

    def get_html(self, key: str) -> bytes:
        time.sleep(BLOCK_S)
        raise r2mod.R2Error("503 SlowDown")


class Repo:
    async def mark_artifacts_status(self, *a, **kw):
        pass

    async def mark_church_extract_error(self, *a, **kw):
        pass


def test_extract_reads_r2_off_the_event_loop():
    async def main():
        return await _ticks_while(extract_mod.extract_for_church(
            Repo(), SlowR2(), church_id=1, artifact_ids=[1], kinds=["homepage"],
            r2_keys=["raw_html/1/2026-11-03/a.html"]))

    ok, ticks = asyncio.run(main())
    assert ok is False
    assert ticks >= 10  # ~30 expected over 0.3 s; 0-1 when the read blocks the loop


class AllowAll:
    def can_fetch(self, *_):
        return True


def test_fetch_parses_html_off_the_event_loop(monkeypatch):
    def slow_extract(html: str) -> str:
        time.sleep(BLOCK_S)
        return "We gather every Sunday."

    monkeypatch.setattr(fetch_mod, "extract_clean_text", slow_extract)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"<html>Sunday</html>"))

    async def main():
        async with httpx.AsyncClient(transport=transport) as client:
            return await _ticks_while(fetch_mod._fetch_one_page(
                client, None, AllowAll(), "https://example.org/", "homepage"))

    outcome, ticks = asyncio.run(main())
    assert outcome.text == "We gather every Sunday."
    assert ticks >= 10
