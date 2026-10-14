"""Frozen origin HTML + in-memory R2; no origin, bucket or model access."""
import asyncio
import copy
from types import SimpleNamespace
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from backend.scrapers_v2 import fetch
from backend.scrapers_v2.r2 import R2Error

HTML = (Path(__file__).parent / 'fixtures' / 'church.html').read_bytes()


class MemoryRepo:
    def __init__(self, size=3):
        self.targets = [dict(church_id=i, website=f'https://church{i}.test/') for i in range(1, size + 1)]
        self.artifacts = []
        self.progress = []
        self.con = self
        self.robots = ''

    async def commit(self):
        pass

    async def bound_fetch_transaction(self):
        pass

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy((self.artifacts, self.progress))
        try:
            yield
        except BaseException:
            self.artifacts, self.progress = before
            raise

    async def churches_due_for_fetch(self, **kw):
        return self.targets[:kw['limit']]

    async def insert_artifact(self, **kw):
        self.artifacts.append(kw)
        return len(self.artifacts)

    async def get_robots(self, host):
        return {'body': self.robots}

    async def update_run_progress(self, run_id, counts):
        self.progress.append(dict(counts))


class MemoryR2:
    def __init__(self, fail=False):
        self.objects = {}
        self.fail = fail

    def head(self, key):
        if self.fail:
            raise R2Error('fixture storage outage')
        return key in self.objects

    def put_html(self, key, body):
        self.objects[key] = body


@pytest.fixture
def offline(monkeypatch):
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(fetch.httpx, 'AsyncClient', lambda **kw: real_client(
            transport=httpx.MockTransport(handler), **kw,
        ))
    install(lambda req: httpx.Response(200, content=HTML, headers={'content-type': 'text/html'}))
    monkeypatch.setattr(fetch, 'PER_DOMAIN_DELAY_S', 0)
    return install


def run(repo, r2):
    return asyncio.run(fetch.run_fetch_batch(repo, r2, batch_size=25, fresh_days=30, crawl_run_id=1))


def test_success_requires_stored_html_and_keeps_page_errors(offline):
    offline(lambda req: httpx.Response(
        200 if req.url.path == '/' else 404, content=HTML,
        headers={'content-type': 'text/html'},
    ))
    repo, r2 = MemoryRepo(1), MemoryR2()
    counts = run(repo, r2)
    assert counts['rows_ok'] == 1
    assert counts['rows_error'] == 0
    assert counts['pages_ok'] == counts['pages_error'] == 1
    assert len(r2.objects) == 1
    assert repo.progress[-1] == counts


@pytest.mark.parametrize('case', ['http-error', 'not-html', 'no-text', 'bad-url', 'r2-error', 'robots'])
def test_failure_artifacts_never_count_as_success(case, offline):
    repo, r2 = MemoryRepo(1), MemoryR2(fail=case == 'r2-error')
    if case == 'http-error':
        offline(lambda req: httpx.Response(404))
    elif case == 'not-html':
        offline(lambda req: httpx.Response(200, json={'message': 'not a web page'}))
    elif case == 'no-text':
        offline(lambda req: httpx.Response(200, text='<html></html>', headers={'content-type': 'text/html'}))
    elif case == 'bad-url':
        repo.targets[0]['website'] = 'not a url'
    elif case == 'robots':
        repo.robots = 'User-agent: *\nDisallow: /'
    counts = run(repo, r2)
    assert counts['rows_ok'] == counts['pages_ok'] == 0
    assert counts['rows_skipped'] == (case == 'robots')
    assert counts['rows_error'] == (case != 'robots')
    assert counts['rows_processed'] == 1
    assert all(a['r2_key'] is None for a in repo.artifacts)


def test_church_failure_rolls_back_only_that_church(offline, monkeypatch):
    repo = MemoryRepo()
    real_fetch = fetch.fetch_church

    async def one(*args, **kw):
        if args[3] == 2:
            await repo.insert_artifact(church_id=2, fetch_error='must roll back')
            raise RuntimeError('one bad church')
        return await real_fetch(*args, **kw)

    monkeypatch.setattr(fetch, 'fetch_church', one)
    counts = run(repo, MemoryR2())
    assert (counts['rows_processed'], counts['rows_ok'], counts['rows_error']) == (3, 2, 1)
    failed = [a for a in repo.artifacts if a['church_id'] == 2]
    assert len(failed) == 1
    assert failed[0]['fetch_error'] == 'church-failed:RuntimeError'
    assert [c['rows_processed'] for c in repo.progress] == [1, 2, 3]


def test_deleted_church_cannot_abort_rest_of_batch(offline, monkeypatch):
    from psycopg.errors import ForeignKeyViolation
    repo = MemoryRepo()
    real_insert = repo.insert_artifact

    async def insert(**kw):
        if kw['church_id'] == 2:
            raise ForeignKeyViolation('fixture church deleted')
        return await real_insert(**kw)

    monkeypatch.setattr(repo, 'insert_artifact', insert)
    counts = run(repo, MemoryR2())
    assert (counts['rows_processed'], counts['rows_ok'], counts['rows_error']) == (3, 2, 1)
    assert repo.progress[-1]['rows_error'] == 1


def test_church_timeout_isolated_and_next_church_continues(offline, monkeypatch):
    repo = MemoryRepo()

    async def one(*args, **kw):
        if args[3] == 2:
            await repo.insert_artifact(church_id=2, fetch_error='unfinished')
            await asyncio.sleep(10)
        return fetch.FetchResult(pages_ok=1)

    monkeypatch.setattr(fetch, 'fetch_church', one)
    monkeypatch.setattr(fetch, 'CHURCH_BUDGET_S', .02)
    counts = run(repo, MemoryR2())
    assert (counts['rows_ok'], counts['rows_error']) == (2, 1)
    assert repo.artifacts[0]['fetch_error'] == 'church-failed:TimeoutError'


def test_batch_budget_leaves_unstarted_targets_for_next_request(offline, monkeypatch):
    repo = MemoryRepo(4)
    clock = [0.0]

    async def one(*args, **kw):
        clock[0] = 2.0
        raise TimeoutError('fixture deadline')

    monkeypatch.setattr(fetch, 'fetch_church', one)
    monkeypatch.setattr(fetch, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(fetch, 'BATCH_BUDGET_S', 1.0)
    counts = run(repo, MemoryR2())
    assert counts['budget_exhausted']
    assert counts['rows_processed'] == 1
    assert counts['targets_remaining'] == 3


def test_cancellation_keeps_previous_commit_and_progress(offline, monkeypatch):
    repo = MemoryRepo()

    async def go():
        entered = asyncio.Event()

        async def one(*args, **kw):
            await repo.insert_artifact(church_id=args[3])
            if args[3] == 2:
                entered.set()
                await asyncio.sleep(10)
            return fetch.FetchResult(pages_ok=1)

        monkeypatch.setattr(fetch, 'fetch_church', one)
        task = asyncio.create_task(fetch.run_fetch_batch(
            repo, MemoryR2(), batch_size=3, fresh_days=30, crawl_run_id=1,
        ))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert [a['church_id'] for a in repo.artifacts] == [1]
    assert repo.progress[-1]['rows_ok'] == repo.progress[-1]['rows_processed'] == 1
