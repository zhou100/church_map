import hashlib
import json

import pytest

from scripts import muse_drive_r2_check as d
from scripts import muse_state_store as m
from tests.test_muse_state_store import MemoryS3


CSV = b'id,note\n1,"private excerpt\n650-555-0100"\n'
DONE = ('- new_candidates.csv: ' + hashlib.sha256(CSV).hexdigest() + '\n').encode()


class Response:
    def __init__(self, body=None, content=b'', status=200):
        self.body, self.content, self.status_code = body, content, status
    def json(self):
        return self.body
    def iter_content(self, size):
        yield self.content
    def close(self):
        pass


class Session:
    def __init__(self):
        self.bad_hash = False
        self.changed_marker = False
        self.done_reads = 0
        self.fail = False
        self.duplicate = False
    def get(self, url, *, params, timeout, allow_redirects, **kwargs):
        assert allow_redirects is False
        if self.fail:
            return Response(status=403, content=b'private provider message')
        if 'q' in params:
            folder = params['q'].split("'")[1]
            files = {
                'root': [{'id': 'returns', 'name': 'returns', 'mimeType': d.FOLDER}],
                'returns': [{'id': 'wp48', 'name': 'WP-0048', 'mimeType': d.FOLDER}],
                'wp48': [{'id': 'done', 'name': 'DONE.md', 'mimeType': 'text/markdown'},
                         {'id': 'csv', 'name': 'new_candidates.csv', 'mimeType': 'text/csv'}],
            }[folder]
            if self.duplicate:
                files = files + files
            return Response({'files': files})
        assert params['alt'] == 'media'
        if url.endswith('/done'):
            self.done_reads += 1
            content = DONE + (b'changed' if self.changed_marker and self.done_reads > 1 else b'')
        else:
            content = b'wrong' if self.bad_hash else CSV
        return Response(content=content)


def test_verified_download_and_r2_roundtrip_count_csv_records():
    client = MemoryS3()
    result = d.check(Session(), m.Store(client, 'private'), 'root', 'r1', 'a' * 40)
    assert result == {'step': 'drive_r2_check', 'status': 'ok', 'files': 2, 'rows': 1, 'bytes': len(CSV)}
    assert m.manifest_key('r1') in client.objects
    assert 'private excerpt' not in json.dumps(result)


@pytest.mark.parametrize('problem', ['bad_hash', 'changed_marker', 'fail', 'duplicate'])
def test_bad_or_ambiguous_package_never_writes_r2(problem):
    client, session = MemoryS3(), Session()
    setattr(session, problem, True)
    with pytest.raises(ValueError):
        d.check(session, m.Store(client, 'private'), 'root', 'r1', 'a' * 40)
    assert client.objects == {}


def test_pagination_is_followed_and_cycles_are_rejected():
    class Paged:
        def get(self, url, *, params, **kwargs):
            if 'pageToken' not in params:
                return Response({'files': [{'id': '1'}], 'nextPageToken': 'next'})
            return Response({'files': [{'id': '2'}]})
    assert [f['id'] for f in d.DriveReader(Paged()).children('root')] == ['1', '2']
    class Cyclic:
        def get(self, *args, **kwargs):
            return Response({'files': [], 'nextPageToken': 'same'})
    with pytest.raises(ValueError):
        d.DriveReader(Cyclic()).children('root')


def test_missing_private_confirmation_fails_without_credentials_or_content(monkeypatch, capsys):
    monkeypatch.delenv('R2_PRIVATE_CONFIRMED', raising=False)
    assert d.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {'step': 'drive_r2_check', 'status': 'failed'}
    assert captured.err == ''


@pytest.mark.parametrize('fail', [False, True])
def test_main_suppresses_private_client_output_on_success_and_failure(monkeypatch, capsys, fail):
    import sys
    import types
    import logging
    for name in ['google', 'google.oauth2', 'google.auth', 'google.auth.transport', 'google.auth.transport.requests']:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    class Credentials:
        @staticmethod
        def from_service_account_info(info, scopes):
            assert scopes == ['https://www.googleapis.com/auth/drive.readonly']
            return object()
    sys.modules['google.oauth2'].service_account = types.SimpleNamespace(Credentials=Credentials)
    class Authorized:
        def __init__(self, credentials):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    sys.modules['google.auth.transport.requests'].AuthorizedSession = Authorized
    for key, value in {'R2_PRIVATE_CONFIRMED': 'true', 'GDRIVE_SA_JSON': '{}', 'GDRIVE_FOLDER_ID': 'root',
                       'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(d.R2Client, '_ensure', lambda self: MemoryS3())
    def noisy(*args):
        print('PRIVATE CSV excerpt')
        print('secret download URL', file=sys.stderr)
        logging.error('6505550100')
        if fail:
            raise RuntimeError('PRIVATE credential')
        return {'step': 'drive_r2_check', 'status': 'ok', 'files': 2, 'rows': 1, 'bytes': 9}
    monkeypatch.setattr(d, 'check', noisy)
    assert d.main() == int(fail)
    result = capsys.readouterr()
    assert result.err == ''
    assert json.loads(result.out)['status'] == ('failed' if fail else 'ok')
    assert 'PRIVATE' not in result.out and 'secret' not in result.out
