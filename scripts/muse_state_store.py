"""Immutable private R2 snapshots for Muse/analytics files; no pipeline activation.

Only the three gitignored state trees are eligible. A snapshot is committed by
its manifest after all blobs exist. Restore selects an explicit run and manifest
hash, verifies every byte, and installs into a NEW directory. No latest pointer,
no remote deletes, no overwriting a working checkout, no raw_html/ access.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

from backend.scrapers_v2.r2 import R2Client

PREFIX = "analytics_private/v1"
ROOTS = ("muse_handoff/returns", "muse_handoff/outbox", "analytics/exports")
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_FILES = 10000
SHA = re.compile(r"[0-9a-f]{64}\Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_key(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("invalid run id")
    return f"{PREFIX}/runs/{run_id}/manifest.json"


def safe_path(name):
    if not isinstance(name, str):
        raise ValueError("invalid path")
    path = PurePosixPath(name)
    if (path.is_absolute() or ".." in path.parts or "\\" in name or
            str(path) != name or not any(name.startswith(root + "/") for root in ROOTS)):
        raise ValueError("invalid path")
    return path


class Store:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def get(self, key, limit):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read(limit + 1)
        finally:
            body.close()
        if len(data) > limit:
            raise ValueError("oversized object")
        return data

    def put_once(self, key, data):
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                   ContentType="application/octet-stream",
                                   IfNoneMatch="*")
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code not in {"PreconditionFailed", "412"}:
                raise
            # Reusing a key is only safe when the committed bytes are identical.
            if self.get(key, len(data)) != data:
                raise ValueError("immutable object conflict") from None


def inventory(root):
    root = Path(root).resolve()
    files, total = [], 0
    for scope in ROOTS:
        directory = root / scope
        if not directory.exists():
            continue
        if directory.is_symlink() or directory.parent.is_symlink() or not directory.is_dir():
            raise ValueError("unsafe state directory")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("state symlink")
            if path.is_dir():
                continue
            if not path.is_file() or path.stat().st_size > MAX_FILE:
                raise ValueError("invalid state file")
            name = path.relative_to(root).as_posix()
            safe_path(name)
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("state changed during capture")
            total += len(data)
            if len(data) > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
                raise ValueError("state limits exceeded")
            files.append((name, data))
    if not files:
        raise ValueError("empty snapshot")
    return files


def save(store, root, run_id, revision):
    key = manifest_key(run_id)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("expected full code revision")
    files = inventory(root)  # Capture before uploads; caller must exclude concurrent writers.
    entries = [{"path": name, "size": len(data), "sha256": digest(data)} for name, data in files]
    manifest = json.dumps({"version": 1, "run_id": run_id, "revision": revision,
                           "roots": list(ROOTS), "files": entries}, sort_keys=True,
                          separators=(",", ":")).encode()
    if len(manifest) > MAX_MANIFEST:
        raise ValueError("manifest too large")
    for (_, data), entry in zip(files, entries):
        store.put_once(f"{PREFIX}/blobs/{entry['sha256']}", data)
    store.put_once(key, manifest)  # Only completed snapshots get a manifest.
    return {"files": len(entries), "bytes": sum(e["size"] for e in entries),
            "manifest_sha256": digest(manifest)}


def restore(store, destination, run_id, expected_sha256):
    key = manifest_key(run_id)
    if not SHA.fullmatch(expected_sha256):
        raise ValueError("invalid manifest hash")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("restore destination must be new")
    raw = store.get(key, MAX_MANIFEST)
    if digest(raw) != expected_sha256:
        raise ValueError("manifest hash mismatch")
    manifest = json.loads(raw)
    if (manifest.get("version") != 1 or manifest.get("run_id") != run_id or
            manifest.get("roots") != list(ROOTS) or
            not re.fullmatch(r"[0-9a-f]{40}", manifest.get("revision", ""))):
        raise ValueError("snapshot identity mismatch")
    entries = manifest["files"]
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES:
        raise ValueError("invalid inventory")
    seen, total = set(), 0
    for entry in entries:
        name = str(safe_path(entry["path"]))
        if name in seen or not SHA.fullmatch(entry["sha256"]):
            raise ValueError("duplicate path or invalid hash")
        seen.add(name)
        size = entry["size"]
        if type(size) is not int or not 0 <= size <= MAX_FILE:
            raise ValueError("invalid size")
        total += size
    if total > MAX_TOTAL:
        raise ValueError("snapshot too large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".muse-restore-", dir=destination.parent))
    try:
        for entry in entries:
            data = store.get(f"{PREFIX}/blobs/{entry['sha256']}", entry["size"])
            if len(data) != entry["size"] or digest(data) != entry["sha256"]:
                raise ValueError("blob integrity failure")
            path = staging / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as out:
                os.chmod(path, 0o600)
                out.write(data)
        # Completed staging is the only tree exposed to downstream consumers.
        if destination.exists() or destination.is_symlink():
            raise ValueError("restore destination appeared")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"files": len(entries), "bytes": total}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        print('{"step":"state_arguments","status":"failed"}')
        raise SystemExit(2)


def main(argv=None):
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    upload = sub.add_parser("save")
    upload.add_argument("--root", type=Path, required=True)
    upload.add_argument("--revision", required=True)
    upload.add_argument("--receipt", type=Path, required=True)
    download = sub.add_parser("restore")
    download.add_argument("--destination", type=Path, required=True)
    download.add_argument("--manifest-sha256", required=True)
    for child in (upload, download):
        child.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    # Allowlist public output. SDK exception strings/debug logs may include URLs
    # or keys; neither successful operations nor failures relay them to Actions.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            if os.environ.get("R2_PRIVATE_CONFIRMED") != "true":
                raise ValueError("private bucket settings not confirmed")
            r2 = R2Client()
            store = Store(r2._ensure(), r2.bucket)
            if args.command == "save":
                if args.receipt.exists() or args.receipt.is_symlink():
                    raise ValueError("receipt must be new")
                result = save(store, args.root, args.run_id, args.revision)
                with args.receipt.open("x", encoding="utf-8") as receipt:
                    os.chmod(args.receipt, 0o600)
                    json.dump({**result, "run_id": args.run_id, "revision": args.revision}, receipt)
            else:
                result = restore(store, args.destination, args.run_id, args.manifest_sha256)
    except Exception:
        print(json.dumps({"step": "state_" + args.command, "status": "failed"}))
        return 1
    finally:
        logging.disable(previous)
    # Hash is returned to the caller but never printed to the public log.
    print(json.dumps({"step": "state_" + args.command, "status": "ok",
                      "files": result["files"], "bytes": result["bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
