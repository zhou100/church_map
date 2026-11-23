"""Tests for the auto-merge gate (.github/scripts/automerge_policy.py).

Two halves: synthetic PRs that must land on each side of every rule, and a
replay of real merged PRs (#84, #85, #86) whose GitHub file lists are frozen
in tests/fixtures/automerge/. The replay's expected verdicts were set from
reading those PRs, not from running the classifier.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "automerge_policy", ROOT / ".github" / "scripts" / "automerge_policy.py")
ap = importlib.util.module_from_spec(_spec)
sys.modules["automerge_policy"] = ap  # dataclasses look the module up here
_spec.loader.exec_module(ap)

POLICY = ap.load_policy(ROOT / ".github" / "automerge-policy.yml")
FIXTURES = ROOT / "tests" / "fixtures" / "automerge"


def f(path, patch="+x\n", status="modified", adds=None, dels=0, prev=None):
    adds = sum(1 for l in patch.splitlines() if l.startswith("+")) if adds is None else adds
    d = {"filename": path, "status": status, "additions": adds, "deletions": dels, "patch": patch}
    if prev:
        d["previous_filename"] = prev
    return d


def classify(*files):
    return ap.classify(list(files), POLICY)


GOOD_PR = {"draft": False, "base": "main", "cross_repository": False,
           "author_association": "OWNER", "mergeable": "MERGEABLE"}
CLEAN_REVIEW = {"blocking": False, "change_kind": "small_bugfix", "summary": "ok", "issues": []}


def decide(result, review=CLEAN_REVIEW, pr=None, checks=("pytest",)):
    return ap.decide(result, review, {**GOOD_PR, **(pr or {})}, POLICY,
                     required_checks=list(checks))


# ── globs ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("glob,path,ok", [
    ("**/*.md", "README.md", True),
    ("**/*.md", "docs/a/b.md", True),
    ("migrations/**", "migrations/0008_x.sql", True),
    ("frontend/src/**/*.css", "frontend/src/index.css", True),
    ("frontend/src/**/*.css", "frontend/src/components/a/b.css", True),
    ("scripts/**", ".github/scripts/x.py", False),
    ("*.md", "docs/a.md", False),
])
def test_glob(glob, path, ok):
    assert bool(ap.glob_to_regex(glob).match(path)) is ok


# ── auto ────────────────────────────────────────────────────────────────────

def test_docs_only_is_auto():
    r = classify(f("docs/guide.md"), f("README.md", "+Use `make test`.\n-old\n", dels=1))
    assert r.verdict == ap.AUTO and r.code_files == []
    assert decide(r).verdict == ap.AUTO


def test_markdown_mentioning_sql_and_tokens_is_not_content_scanned():
    r = classify(f("docs/plan.md", "+Run SELECT count(*) FROM churches; CRAWL_TOKEN stays secret.\n"))
    assert r.verdict == ap.AUTO, r.reasons


def test_tests_only_is_auto():
    r = classify(f("tests/test_utils.py", "+def test_slug():\n+    assert slug('A B') == 'a-b'\n"),
                 f("frontend/src/searchScope.test.js", "+it('keeps scope', () => {})\n"))
    assert r.verdict == ap.AUTO and set(r.categories) == {"tests"}


def test_css_only_is_auto():
    r = classify(f("frontend/src/index.css", "+.card { gap: 8px; }\n"))
    assert r.verdict == ap.AUTO and r.categories == {"frontend_style": ["frontend/src/index.css"]}
    assert decide(r, review={**CLEAN_REVIEW, "change_kind": "copy_style"}).verdict == ap.AUTO


def test_small_jsx_copy_fix_is_auto_when_review_agrees():
    r = classify(f("frontend/src/pages/Landing.jsx", "-<p>Find a chruch</p>\n+<p>Find a church</p>\n", dels=1))
    assert r.verdict == ap.AUTO and r.code_files == ["frontend/src/pages/Landing.jsx"]
    assert decide(r, review={**CLEAN_REVIEW, "change_kind": "copy_style"}).verdict == ap.AUTO


def test_exactly_200_lines_is_allowed():
    r = classify(f("docs/a.md", "", adds=150, dels=50))
    assert r.changed_lines == 200 and r.verdict == ap.AUTO


# ── needs_human: deterministic rules ────────────────────────────────────────

@pytest.mark.parametrize("file,why", [
    (f("migrations/0009_add_col.sql", "+ALTER TABLE churches ADD COLUMN x int;\n"), "迁移或 SQL"),
    (f("backend/routers/churches.py", '+    rows = cur.execute("SELECT id FROM churches")\n'), "迁移或 SQL"),
    (f("backend/db/repository.py", "+    return x\n"), "迁移或 SQL"),
    (f("backend/routers/reviews.py", "+GRANT SELECT ON reviews TO anon;\n"), "权限"),
    (f("backend/auth.py", "+    pass\n"), "登录"),
    (f("backend/main.py", '+    url = os.environ["DATABASE_URL"]\n'), "环境变量"),
    (f("frontend/src/api/client.js", "+const base = import.meta.env.VITE_API\n"), "环境变量"),
    (f("requirements.txt", "-fastapi==0.110\n+fastapi==0.115\n", dels=1), "依赖"),
    (f("frontend/package.json", '+    "leaflet": "^1.9.5",\n'), "依赖"),
    (f("Dockerfile", "+RUN apt-get update\n"), "Docker"),
    (f("render.yaml", "+    plan: standard\n"), "部署"),
    (f(".github/workflows/tests.yml", "+      - run: echo hi\n"), "CI"),
    (f("scripts/publish_verified.py", "+    print('x')\n"), "生产数据"),
    (f("backend/scrapers_v2/fetch.py", "+    timeout = 30\n"), "生产数据"),
    (f("backend/routers/admin.py", '+    cmd = ["python", "-m", "crawl", "--apply"]\n'), "生产数据"),
    (f("backend/utils.py", "+import anthropic\n"), "付费模型"),
])
def test_protected_change_needs_human(file, why):
    r = classify(file)
    assert r.verdict == ap.NEEDS_HUMAN
    assert any(why in reason for reason in r.reasons), r.reasons
    assert decide(r).verdict == ap.NEEDS_HUMAN


def test_deleted_file_needs_human():
    r = classify(f("docs/old.md", "-gone\n", status="removed", adds=0, dels=1))
    assert r.verdict == ap.NEEDS_HUMAN and any("删除文件" in x for x in r.reasons)


def test_rename_needs_human():
    r = classify(f("docs/new.md", "", status="renamed", adds=0, prev="docs/old.md"))
    assert any("重命名" in x for x in r.reasons)


def test_201_lines_needs_human():
    r = classify(f("docs/a.md", "", adds=151, dels=50))
    assert r.verdict == ap.NEEDS_HUMAN and any("201" in x for x in r.reasons)


@pytest.mark.parametrize("path", [
    ".github/automerge-policy.yml",
    ".github/workflows/automerge.yml",
    ".github/scripts/automerge_policy.py",
    "tests/test_automerge_policy.py",
])
def test_changing_the_gate_itself_needs_human(path):
    r = classify(f(path, "+# tweak\n"))
    assert r.verdict == ap.NEEDS_HUMAN
    assert any("策略/流程本身" in x for x in r.reasons), r.reasons


def test_missing_patch_needs_human():
    d = f("docs/diagram.md", adds=3)
    d.pop("patch")
    r = classify(d)
    assert any("不可检查" in x for x in r.reasons)


def test_one_bad_file_poisons_an_otherwise_doc_pr():
    r = classify(f("docs/a.md"), f("migrations/0010.sql", "+SELECT 1;\n"))
    assert r.verdict == ap.NEEDS_HUMAN


# ── needs_human: review and GitHub state ────────────────────────────────────

def test_code_change_needs_review_to_call_it_small():
    r = classify(f("frontend/src/pages/Landing.jsx", "+const x = 1\n"))
    d = decide(r, review={**CLEAN_REVIEW, "change_kind": "feature"})
    assert d.verdict == ap.NEEDS_HUMAN and any("feature" in x for x in d.reasons)


def test_blocking_review_needs_human():
    r = classify(f("docs/a.md"))
    review = {**CLEAN_REVIEW, "issues": [
        {"severity": "blocking", "file": "docs/a.md", "line": 1, "description": "wrong command"}]}
    assert decide(r, review=review).verdict == ap.NEEDS_HUMAN
    assert decide(r, review={**CLEAN_REVIEW, "blocking": True}).verdict == ap.NEEDS_HUMAN


def test_missing_review_fails_closed():
    d = decide(classify(f("docs/a.md")), review=None)
    assert d.verdict == ap.NEEDS_HUMAN and any("没有跑成" in x for x in d.reasons)


@pytest.mark.parametrize("pr,why", [
    ({"mergeable": "CONFLICTING"}, "冲突"),
    ({"mergeable": "UNKNOWN"}, "mergeable=UNKNOWN"),
    ({"draft": True}, "draft"),
    ({"cross_repository": True}, "fork"),
    ({"author_association": "CONTRIBUTOR"}, "CONTRIBUTOR"),
    ({"base": "release"}, "目标分支"),
])
def test_github_state_needs_human(pr, why):
    d = decide(classify(f("docs/a.md")), pr=pr)
    assert d.verdict == ap.NEEDS_HUMAN and any(why in x for x in d.reasons), d.reasons


def test_review_only_runs_when_it_can_change_the_outcome():
    docs = classify(f("docs/a.md"))
    assert ap.review_needed(docs, GOOD_PR, POLICY, ["pytest"])
    # rules already block → no paid call
    assert not ap.review_needed(classify(f("migrations/0010.sql", "+SELECT 1;\n")),
                                GOOD_PR, POLICY, ["pytest"])
    # GitHub state already blocks → no paid call (fork spam cannot spend money)
    for pr in ({"cross_repository": True}, {"draft": True}, {"mergeable": "CONFLICTING"}):
        assert not ap.review_needed(docs, {**GOOD_PR, **pr}, POLICY, ["pytest"])
    assert not ap.review_needed(docs, GOOD_PR, POLICY, [])
    # opt-out restores review on every PR
    always = {**POLICY, "review": {**POLICY["review"], "skip_when_needs_human": False}}
    assert ap.review_needed(classify(f("migrations/0010.sql", "+SELECT 1;\n")), GOOD_PR, always, [])


def test_skipped_review_does_not_add_noise_reason():
    d = decide(classify(f("migrations/0010.sql", "+SELECT 1;\n")), review=None)
    assert d.verdict == ap.NEEDS_HUMAN
    assert not any("没有跑成" in x for x in d.reasons)


def test_no_required_checks_refuses_to_arm():
    # Without required checks GitHub would merge immediately, before CI.
    d = decide(classify(f("docs/a.md")), checks=())
    assert d.verdict == ap.NEEDS_HUMAN and any("required status checks" in x for x in d.reasons)


# ── replay of real PRs ──────────────────────────────────────────────────────
# #84 publisher RLS policies + publish_verified.py change (196 lines)
# #85 AGENTS.md wording cleanup (25 lines, one .md file)
# #86 migration 0008 locking down public tables with RLS + its test

def replay(n):
    return ap.classify(json.loads((FIXTURES / f"pr{n}.json").read_text(encoding="utf-8")), POLICY)


def test_replay_pr84_needs_human():
    r = replay(84)
    assert r.verdict == ap.NEEDS_HUMAN
    text = "\n".join(r.reasons)
    for why in ("数据库迁移或 SQL", "RLS / 数据库权限", "生产数据", "scripts/publish_verified.py"):
        assert why in text


def test_replay_pr85_is_auto_eligible():
    r = replay(85)
    assert r.verdict == ap.AUTO and r.categories == {"docs": ["AGENTS.md"]}
    assert decide(r, review={**CLEAN_REVIEW, "change_kind": "docs"}).verdict == ap.AUTO


def test_replay_pr86_needs_human():
    r = replay(86)
    assert r.verdict == ap.NEEDS_HUMAN
    text = "\n".join(r.reasons)
    assert "migrations/0008_lock_down_public_tables.sql" in text
    assert "RLS / 数据库权限" in text
