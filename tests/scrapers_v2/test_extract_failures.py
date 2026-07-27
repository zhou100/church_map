"""How the extract stage routes its failures.

This is the highest-consequence branching in the pipeline and none of it was
covered. `requeue` only puts 'ok' artifacts back in the queue, so 'skipped'
and 'error' are terminal — a mis-routed failure removes a church from the
corpus permanently, and does it silently, at the rate the cron runs.

The specific trap: an unreachable R2 bucket and a genuinely empty page both
surface as "no text". Rotated credentials would have burned every artifact in
every batch until someone noticed the numbers plateau.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.scrapers_v2 import extract as extract_mod
from backend.scrapers_v2 import r2 as r2mod

CHURCH = 4242
ARTIFACTS = [11, 12]
KINDS = ["homepage", "about"]
KEYS = ["raw_html/4242/2026-05-01/aaa.html", "raw_html/4242/2026-05-01/bbb.html"]

PAGE = b"<html><body><h1>Grace Chapel</h1><p>" + b"We gather every Sunday. " * 20 + b"</p></body></html>"


class FakeR2:
    """Serves bytes, or raises, per key."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def get_html(self, key: str) -> bytes:
        r = self.responses.get(key, r2mod.R2NotFound(key))
        if isinstance(r, Exception):
            raise r
        return r


class FakeRepo:
    """Records the calls that decide an artifact's fate."""

    def __init__(self):
        self.artifact_calls: list[tuple[list[int], str, str | None]] = []
        self.church_status: str | None = None
        self.wrote_extraction = False

    async def mark_artifacts_status(self, artifact_ids, *, status, error_detail=None):
        self.artifact_calls.append((list(artifact_ids), status, error_detail))

    async def mark_church_extract_error(self, church_id, status):
        self.church_status = status

    async def write_extraction(self, church_id, **kw):
        self.wrote_extraction = True


def _run(r2, repo, **kw):
    return asyncio.run(
        extract_mod.extract_for_church(
            repo, r2,
            church_id=CHURCH,
            artifact_ids=ARTIFACTS,
            kinds=KINDS,
            r2_keys=KEYS,
            **kw,
        )
    )


# --- the branch that must never mark anything terminal ---------------------


def test_unreachable_r2_leaves_artifacts_pending():
    """The bug this file exists for. A bucket that cannot be read is not an
    empty page: the artifacts have to stay 'pending' so the next cron run
    retries them once R2 (or the credential) comes back."""
    r2 = FakeR2({k: r2mod.R2Error("503 SlowDown") for k in KEYS})
    repo = FakeRepo()

    assert _run(r2, repo) is False
    # Nothing terminal was written — no 'skipped', no 'error'.
    assert repo.artifact_calls == []
    assert repo.church_status.startswith("transient:")
    assert "r2-unreadable:2/2" in repo.church_status


def test_missing_credentials_are_transient_too():
    """R2Client raises R2Error (not a ClientError) when env vars are unset.
    That is a config mistake, which is the most likely way this branch is
    ever reached in bulk — and the most expensive to treat as terminal."""
    r2 = FakeR2({k: r2mod.R2Error("R2 credentials missing") for k in KEYS})
    repo = FakeRepo()

    assert _run(r2, repo) is False
    assert repo.artifact_calls == []
    assert repo.church_status.startswith("transient:")


def test_unreadable_wins_over_missing_when_both_happen():
    """Mixed causes resolve to the recoverable one. Retrying a church whose
    HTML is genuinely gone costs one wasted R2 read; the reverse costs the
    church."""
    r2 = FakeR2({KEYS[0]: r2mod.R2NotFound("gone"), KEYS[1]: r2mod.R2Error("403")})
    repo = FakeRepo()

    assert _run(r2, repo) is False
    assert repo.artifact_calls == []
    assert repo.church_status.startswith("transient:")


# --- terminal, and correctly so --------------------------------------------


def test_absent_r2_objects_report_no_html_not_no_text():
    """The distinction the backfill diagnosis turns on. `no-html` means the
    archive lost the page and the church needs re-*fetching*; `no-text` means
    the page was read and had nothing in it. Same symptom, opposite fix."""
    r2 = FakeR2({k: r2mod.R2NotFound(k) for k in KEYS})
    repo = FakeRepo()

    assert _run(r2, repo) is False
    ids, status, detail = repo.artifact_calls[0]
    assert (ids, status) == (ARTIFACTS, "skipped")
    assert detail == "no-html:2/2"
    assert repo.church_status == "no-html:2/2"


def test_readable_but_empty_pages_are_no_text():
    r2 = FakeR2({k: b"<html><body></body></html>" for k in KEYS})
    repo = FakeRepo()

    assert _run(r2, repo) is False
    assert repo.artifact_calls[0][1] == "skipped"
    assert repo.artifact_calls[0][2] == "no-text"
    assert repo.church_status == "no-text"


# --- a partial archive is still worth extracting ---------------------------


def test_one_good_page_extracts_even_if_the_other_is_gone(monkeypatch):
    """Missing artifacts must not veto a church that still has readable HTML —
    otherwise one expired object discards everything else we hold on it."""
    r2 = FakeR2({KEYS[0]: PAGE, KEYS[1]: r2mod.R2NotFound(KEYS[1])})
    repo = FakeRepo()

    async def fake_llm(text, **kw):
        # Only the surviving page reaches the model, tagged with its kind.
        assert text.startswith("# homepage")
        assert "We gather every Sunday." in text
        return {"community_summary": "A Sunday-gathering congregation."}

    monkeypatch.setattr(extract_mod, "call_llm", fake_llm)

    assert _run(r2, repo) is True
    assert repo.wrote_extraction is True
    assert repo.artifact_calls[-1][1] == "ok"


# --- the counting itself ---------------------------------------------------


def test_gather_counts_each_cause_separately():
    r2 = FakeR2({
        KEYS[0]: r2mod.R2NotFound(KEYS[0]),
        KEYS[1]: r2mod.R2Error("throttled"),
    })
    got = extract_mod._gather_text_from_r2(r2, KINDS, KEYS)

    assert (got.keys, got.missing, got.unreadable) == (2, 1, 1)
    assert got.text == ""


@pytest.mark.parametrize("exc", [r2mod.R2NotFound, r2mod.R2Error])
def test_r2_not_found_is_catchable_as_r2_error(exc):
    """R2NotFound has to stay a subclass — callers that only care about
    "R2 failed" must keep working."""
    assert issubclass(r2mod.R2NotFound, r2mod.R2Error)
    with pytest.raises(r2mod.R2Error):
        raise exc("x")
