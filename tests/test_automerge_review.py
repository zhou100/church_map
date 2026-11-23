"""Tests for the OpenRouter review call (.github/scripts/automerge_review.py).

No network: `post` is injected. Every failure path must return review=None so
the gate fails closed to needs_human.
"""

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ap = _load("automerge_policy")
ar = _load("automerge_review")
POLICY = ap.load_policy(ROOT / ".github" / "automerge-policy.yml")
FILES = [{"filename": "docs/a.md", "status": "modified", "additions": 1, "deletions": 0,
          "patch": "+hello\n"}]
GOOD = {"blocking": False, "change_kind": "docs", "summary": "typo fix", "issues": []}


def completion(content, finish="stop"):
    return {"model": "anthropic/claude-opus-5.5",
            "choices": [{"finish_reason": finish, "message": {"content": content}}]}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")


def run(post, **kw):
    return ar.review_pr("t", "b", FILES, POLICY, post=post, sleep=lambda s: None, **kw)


def test_payload_uses_policy_model_schema_and_effort():
    p = ar.build_payload("t", "b", FILES, POLICY["review"])
    assert p["model"] == POLICY["review"]["model"] == "anthropic/claude-opus-5.5"
    assert p["response_format"]["json_schema"]["strict"] is True
    assert p["reasoning"] == {"effort": "medium"}
    assert p["provider"] == {"require_parameters": True}
    assert "<pr>" in p["messages"][1]["content"] and "+hello" in p["messages"][1]["content"]


def test_valid_review_is_returned():
    review, note = run(lambda *a: (200, completion(json.dumps(GOOD))))
    assert review == GOOD and "claude-opus-5.5" in note


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    calls = []
    review, note = run(lambda *a: calls.append(a))
    assert review is None and "OPENROUTER_API_KEY" in note and calls == []


@pytest.mark.parametrize("resp,why", [
    (completion("not json"), "合法 JSON"),
    (completion(json.dumps({**GOOD, "change_kind": "trivial"})), "格式"),
    (completion(json.dumps({k: v for k, v in GOOD.items() if k != "blocking"})), "格式"),
    (completion(json.dumps(GOOD), finish="length"), "finish_reason=length"),
    (completion(json.dumps(GOOD), finish="content_filter"), "content_filter"),
    (completion(None), "合法 JSON"),
    ({"error": {"code": 402, "message": "insufficient credits"}}, "错误"),
    ({"choices": []}, "格式异常"),
])
def test_bad_completion_fails_closed(resp, why):
    review, note = run(lambda *a: (200, resp))
    assert review is None and why in note


def test_non_retryable_http_error_stops_immediately():
    calls = []
    def post(*a):
        calls.append(1)
        return 401, None
    review, note = run(post)
    assert review is None and "401" in note and len(calls) == 1


def test_retryable_error_then_success():
    seq = iter([(503, None), (200, completion(json.dumps(GOOD)))])
    review, _ = run(lambda *a: next(seq))
    assert review == GOOD


def test_connection_errors_exhaust_retries():
    def post(*a):
        raise urllib.error.URLError("down")
    review, note = run(post)
    assert review is None and "连接失败" in note


def test_oversized_diff_is_skipped_not_truncated():
    big = [{**FILES[0], "patch": "+" + "x" * (POLICY["review"]["max_diff_chars"] + 1)}]
    calls = []
    review, note = ar.review_pr("t", "b", big, POLICY, post=lambda *a: calls.append(a))
    assert review is None and "不截断" in note and calls == []
