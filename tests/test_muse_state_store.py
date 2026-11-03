import io
import json
import logging

import pytest
from botocore.exceptions import ClientError

from scripts import muse_state_store as m


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.fail_blob = False

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, **kw):
        assert IfNoneMatch == "*"
        assert Key.startswith(m.PREFIX + "/")
        if self.fail_blob and "/blobs/" in Key:
            raise RuntimeError("private phone 650-555-0100 and secret")
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def source(tmp_path):
    root = tmp_path / "source"
    for name, data in {"muse_handoff/returns/received.csv": b"private\n",
                       "muse_handoff/returns/recheck/history/x.json": b'{"old":true}',
                       "muse_handoff/outbox/status.csv": b"state\n",
                       "analytics/exports/geocode_ledger.csv": b"ledger\n"}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / ".env").write_text("do not upload")
    return root


def test_roundtrip_preserves_bytes_and_excludes_unrelated_files(tmp_path):
    root, client = source(tmp_path), MemoryS3()
    store = m.Store(client, "private")
    receipt = m.save(store, root, "run-1", "a" * 40)
    assert receipt["files"] == 4
    target = tmp_path / "restored"
    assert m.restore(store, target, "run-1", receipt["manifest_sha256"])["files"] == 4
    assert sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file() and p.name != ".env") == sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())
    for path in target.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (root / path.relative_to(target)).read_bytes()
            assert path.stat().st_mode & 0o777 == 0o600
    assert b"do not upload" not in client.objects.values()
    assert m.save(store, root, "run-1", "a" * 40) == receipt


def test_changed_state_cannot_replace_completed_run(tmp_path):
    root, client = source(tmp_path), MemoryS3()
    store = m.Store(client, "private")
    m.save(store, root, "run-1", "a" * 40)
    old = client.objects[m.manifest_key("run-1")]
    (root / "muse_handoff/outbox/status.csv").write_text("new")
    with pytest.raises(ValueError):
        m.save(store, root, "run-1", "a" * 40)
    assert client.objects[m.manifest_key("run-1")] == old


def test_failed_upload_never_commits_manifest(tmp_path):
    root, client = source(tmp_path), MemoryS3()
    client.fail_blob = True
    with pytest.raises(RuntimeError):
        m.save(m.Store(client, "private"), root, "run-1", "a" * 40)
    assert m.manifest_key("run-1") not in client.objects


@pytest.mark.parametrize("damage", ["manifest", "blob", "missing_blob"])
def test_corruption_or_incomplete_remote_data_never_installs_destination(tmp_path, damage):
    root, client = source(tmp_path), MemoryS3()
    store = m.Store(client, "private")
    receipt = m.save(store, root, "run-1", "a" * 40)
    key = m.manifest_key("run-1") if damage == "manifest" else next(k for k in client.objects if "/blobs/" in k)
    if damage == "missing_blob":
        del client.objects[key]
    else:
        client.objects[key] = b"corrupt"
    with pytest.raises((ValueError, KeyError)):
        m.restore(store, tmp_path / "restored", "run-1", receipt["manifest_sha256"])
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".muse-restore-*"))


@pytest.mark.parametrize("bad", ["../../outside", "muse_handoff/returns/../../outside", "/etc/passwd", "raw_html/x", "muse_handoff/returns/./x", "muse_handoff/returns\\x"])
def test_manifest_paths_cannot_escape_state_trees(bad):
    with pytest.raises(ValueError):
        m.safe_path(bad)


def test_symlinks_and_existing_destination_are_rejected(tmp_path):
    root, client = source(tmp_path), MemoryS3()
    store = m.Store(client, "private")
    receipt = m.save(store, root, "run-1", "a" * 40)
    with pytest.raises(ValueError):
        m.restore(store, root, "run-1", receipt["manifest_sha256"])
    (root / "muse_handoff/returns/leak").symlink_to(root / ".env")
    with pytest.raises(ValueError):
        m.save(store, root, "run-2", "a" * 40)
    assert m.manifest_key("run-2") not in client.objects


def test_public_failure_log_does_not_echo_exception_or_sdk_logs(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("R2_PRIVATE_CONFIRMED", "true")
    def fail(self):
        print("private excerpt")
        logging.error("personal phone 6505550100")
        raise RuntimeError("token=SECRET")
    monkeypatch.setattr(m.R2Client, "_ensure", fail)
    assert m.main(["save", "--root", str(tmp_path), "--run-id", "r1", "--revision", "a" * 40, "--receipt", str(tmp_path / "receipt.json")]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"step": "state_save", "status": "failed"}
    assert captured.err == ""


def test_public_success_log_contains_only_status_and_counts(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("R2_PRIVATE_CONFIRMED", "true")
    client, root = MemoryS3(), source(tmp_path)
    monkeypatch.setattr(m.R2Client, "_ensure", lambda self: client)
    assert m.main(["save", "--root", str(root), "--run-id", "r1", "--revision", "a" * 40, "--receipt", str(tmp_path / "receipt.json")]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert set(result) == {"step", "status", "files", "bytes"}
    assert result["files"] == 4 and result["status"] == "ok"
    assert captured.err == ""
