"""
Static checks that runtime route code never reaches for SQLite or its
SQLite-era patterns. Scrapers and migration scripts are exempt because
they're one-shot offline work.

Catches:
  * sqlite3.connect() in routers / main / enrichment / auth
  * `?` placeholders in those files (psycopg uses %s)
  * .lastrowid (psycopg has no equivalent; use RETURNING)

The holyhub/ directory was removed in Phase A; this test makes sure no
stray import sneaks back in via copy-paste from old code or scrapers.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

ROUTE_FILES = [
    REPO / "backend" / "main.py",
    REPO / "backend" / "auth.py",
    REPO / "backend" / "enrichment.py",
    REPO / "backend" / "routers" / "churches.py",
    REPO / "backend" / "routers" / "reviews.py",
    REPO / "backend" / "routers" / "auth.py",
    REPO / "backend" / "db" / "pool.py",
    REPO / "backend" / "db" / "repository.py",
]

# `?` placeholder pattern: a `?` followed by `,` or `)` after optional
# whitespace, which matches SQLite parameterized queries without false-
# positiving Python ternary ops or type hints.
SQLITE_PLACEHOLDER = re.compile(r"\?\s*[,\)]")


def _read(p: Path) -> str:
    return p.read_text() if p.is_file() else ""


def _strip_docs_and_comments(src: str) -> str:
    """Remove module/function docstrings and `#` comments so checks don't
    false-positive on commentary about the SQLite-era patterns we banned.
    Crude but sufficient: toggles on any line that starts or ends with
    triple quotes; drops `#`-prefixed and trailing-`#` comments."""
    out = []
    in_doc = False
    for line in src.splitlines():
        stripped = line.strip()
        triples = stripped.count('"""') + stripped.count("'''")
        if in_doc:
            if triples >= 1:
                in_doc = False
            continue
        if triples == 1 and (stripped.startswith('"""') or stripped.startswith("'''")):
            in_doc = True
            continue
        if triples >= 2:
            # Single-line docstring like `"""one liner"""`; drop it.
            continue
        if stripped.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return "\n".join(out)


@pytest.mark.parametrize("path", ROUTE_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_sqlite_in_route_files(path: Path):
    raw = _read(path)
    if not raw:
        pytest.skip(f"{path} not present")
    code = _strip_docs_and_comments(raw)

    assert "sqlite3.connect" not in code, f"sqlite3.connect found in {path}"
    assert "from holyhub.database import Database" not in code, (
        f"Database import found in {path}"
    )
    assert "holyhub.database.Database" not in code, (
        f"Database reference found in {path}"
    )
    assert ".lastrowid" not in code, (
        f".lastrowid found in {path}; psycopg requires RETURNING"
    )

    matches = SQLITE_PLACEHOLDER.findall(code)
    assert not matches, (
        f"SQLite-style `?` placeholder found in {path}: {matches!r}"
    )
