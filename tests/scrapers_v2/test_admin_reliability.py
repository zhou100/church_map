import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend.db.repository import CrawlBusy
from backend.routers import admin


def setup_stage(monkeypatch, *, replay=False, busy=False):
    events = []
    row = dict(id=7, status='running', rows_processed=1, rows_ok=1, rows_error=0, rows_skipped=0)

    class Connection:
        async def commit(self):
            events.append('commit')

        async def rollback(self):
            events.append('rollback')

    class Repo:
        def __init__(self, con):
            self.con = con

        async def claim_run(self, *args, **kw):
            if busy:
                raise CrawlBusy('already running')
            return row, replay

        async def bound_fetch_transaction(self):
            pass

        async def update_run_progress(self, run_id, counts):
            row.update(counts)

        async def finish_run(self, run_id, **kw):
            row.update(kw)

        async def fail_run(self, run_id, error):
            events.append('fail')
            row['status'] = 'error'

        async def release_run(self, run_id):
            events.append('release')

    @asynccontextmanager
    async def acquire():
        yield Connection()

    monkeypatch.setattr(admin.pool, 'acquire', acquire)
    monkeypatch.setattr(admin, 'CrawlRepository', Repo)
    return events, row


@pytest.mark.parametrize('error', [TimeoutError, asyncio.CancelledError])
def test_interrupted_stage_keeps_progress_rolls_back_and_releases_lease(monkeypatch, error):
    events, row = setup_stage(monkeypatch)

    async def runner(repo, run_id):
        raise error()

    with pytest.raises(asyncio.CancelledError if error is asyncio.CancelledError else HTTPException):
        asyncio.run(admin._run_stage('fetch', 5, runner, 'fixture'))
    assert events == ['commit', 'rollback', 'fail', 'release', 'commit']
    assert row['status'] == 'error'
    assert row['rows_ok'] == row['rows_processed'] == 1


def test_repeated_request_returns_original_counts_without_running_again(monkeypatch):
    events, row = setup_stage(monkeypatch, replay=True)
    row['status'] = 'ok'

    async def runner(*args):
        pytest.fail('replayed request started another fetch')
    result = asyncio.run(admin._run_stage('fetch', 5, runner, 'fixture'))
    assert result['replayed'] and result['run_id'] == 7
    assert result['rows_ok'] == 1
    assert events == ['commit']


@pytest.mark.parametrize('status,code', [('running', 202), ('error', 500)])
def test_replay_does_not_claim_completion_of_unfinished_or_failed_run(monkeypatch, status, code):
    _, row = setup_stage(monkeypatch, replay=True)
    row['status'] = status

    async def runner(*args):
        pytest.fail('replay invoked fetch')
    result = asyncio.run(admin._run_stage('fetch', 5, runner, 'fixture'))
    assert result.status_code == code


def test_overlapping_request_is_409(monkeypatch):
    setup_stage(monkeypatch, busy=True)

    async def runner(*args):
        pytest.fail('busy request started another fetch')
    with pytest.raises(HTTPException) as raised:
        asyncio.run(admin._run_stage('fetch', 5, runner))
    assert raised.value.status_code == 409


@pytest.mark.parametrize('operation', ['claim_run', 'finish_run'])
def test_request_budget_includes_claim_and_finalization(monkeypatch, operation):
    setup_stage(monkeypatch)
    monkeypatch.setattr(admin, 'FETCH_REQUEST_TIMEOUT_S', .02)

    async def stuck(*args, **kw):
        await asyncio.sleep(10)

    monkeypatch.setattr(admin.CrawlRepository, operation, stuck)

    async def runner(*args):
        return dict(rows_processed=1, rows_ok=1, rows_error=0)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(admin._run_stage('fetch', 5, runner))
    assert raised.value.status_code == 504


def test_fetch_route_default_bounds_and_request_key(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    seen = []

    async def stage(stage, batch_size, runner, request_key=None):
        seen.append((stage, batch_size, request_key))
        return {'status': 'ok'}

    monkeypatch.setenv('CRAWL_TOKEN', 'fixture-token')
    monkeypatch.setattr(admin, '_run_stage', stage)
    monkeypatch.setattr(admin, 'R2Client', lambda: object())
    app = FastAPI()
    app.include_router(admin.router)
    client = TestClient(app)
    headers = {'X-Crawl-Token': 'fixture-token', 'Idempotency-Key': 'fixture-key'}
    assert client.post('/admin/crawl/fetch', headers=headers).status_code == 200
    assert seen == [('fetch', 5, 'fixture-key')]
    assert client.post('/admin/crawl/fetch?batch=26', headers=headers).status_code == 422
    assert client.post('/admin/crawl/fetch', headers={**headers, 'Idempotency-Key': 'x' * 129}).status_code == 422
    assert client.post('/admin/crawl/fetch').status_code == 403
    assert len(seen) == 1


def test_optional_page_failures_make_the_run_partial(monkeypatch):
    events, row = setup_stage(monkeypatch)

    async def runner(*args):
        return dict(rows_processed=1, rows_ok=1, rows_error=0, pages_error=1)
    result = asyncio.run(admin._run_stage('fetch', 5, runner))
    assert result['status'] == 'partial'
    assert events[-2:] == ['release', 'commit']
