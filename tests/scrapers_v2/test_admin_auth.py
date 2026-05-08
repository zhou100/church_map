"""Admin auth: token must match exactly. Missing/wrong → 4xx."""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.admin import require_crawl_token


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("CRAWL_TOKEN", "secret-token-abc123")
    app = FastAPI()

    @app.get("/protected")
    def _protected(_: None = __import__("fastapi").Depends(require_crawl_token)):
        return {"ok": True}

    return app


def test_missing_header_rejected(app):
    client = TestClient(app)
    r = client.get("/protected")
    # No header → empty string compared against expected → 403
    assert r.status_code == 403


def test_wrong_token_rejected(app):
    client = TestClient(app)
    r = client.get("/protected", headers={"X-Crawl-Token": "wrong"})
    assert r.status_code == 403


def test_correct_token_passes(app):
    client = TestClient(app)
    r = client.get("/protected", headers={"X-Crawl-Token": "secret-token-abc123"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_unconfigured_returns_503(monkeypatch):
    monkeypatch.delenv("CRAWL_TOKEN", raising=False)
    app = FastAPI()

    @app.get("/protected")
    def _protected(_: None = __import__("fastapi").Depends(require_crawl_token)):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/protected", headers={"X-Crawl-Token": "anything"})
    assert r.status_code == 503
