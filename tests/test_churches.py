"""
Phase A: this file used to inject a SQLite Database via `backend.deps.db`,
which no longer exists. The same endpoint coverage is now in
tests/test_parity.py, which runs against a real Postgres pool.

If you want unit-level tests for the churches router again, mock the
ChurchRepository (backend.db.repository.ChurchRepository) instead.
"""
import pytest

pytestmark = pytest.mark.skip(reason="superseded by tests/test_parity.py")


def test_placeholder():
    pass
