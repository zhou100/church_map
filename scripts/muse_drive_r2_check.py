"""Bounded manual check: read WP-0048 CSV, verify DONE hash, save/restore via R2.

No source rechecks, dbt, extraction, publishing, or Drive mutations. This is not
an hourly intake pipeline or a migration of the owner's complete local state.
"""
from contextlib import redirect_stderr, redirect_stdout
import csv
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from backend.scrapers_v2.r2 import R2Client
from scripts.muse_state_store import MAX_FILE, Store, save, restore

API = "https://www.googleapis.com/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"


class DriveReader:
    def __init__(self, session):
        self.session = session

    def children(self, folder_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
            raise ValueError("invalid Drive id")
        results, token, tokens = [], None, set()
        while True:
            params = {"q": f"'{folder_id}' in parents and trashed = false",
                      "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
                      "pageSize": 1000, "supportsAllDrives": "true",
                      "includeItemsFromAllDrives": "true"}
            if token:
                params["pageToken"] = token
            response = self.session.get(API, params=params, timeout=30, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError("Drive listing failed")
            body = response.json()
            results.extend(body.get("files", []))
            if len(results) > 10000:
                raise ValueError("Drive listing too large")
            token = body.get("nextPageToken")
            if not token:
                return results
            if token in tokens:
                raise ValueError("repeated Drive page")
            tokens.add(token)

    def named(self, folder_id, name, mime):
        matches = [f for f in self.children(folder_id) if f["name"] == name]
        if len(matches) != 1 or matches[0]["mimeType"] != mime:
            raise ValueError("missing, ambiguous or wrong-type Drive entry")
        return matches[0]

    def download(self, file_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise ValueError("invalid Drive id")
        response = self.session.get(API + "/" + file_id,
            params={"alt": "media", "supportsAllDrives": "true"},
            timeout=60, allow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                raise ValueError("Drive download failed")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_FILE:
                    raise ValueError("Drive file too large")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()


def verified_sample(reader, root_folder):
    returns = reader.named(root_folder, "returns", FOLDER)
    package = reader.named(returns["id"], "WP-0048", FOLDER)
    done = reader.named(package["id"], "DONE.md", "text/markdown")
    candidate = reader.named(package["id"], "new_candidates.csv", "text/csv")
    marker = reader.download(done["id"])
    hashes = re.findall(r"(?m)^- new_candidates\.csv: ([0-9a-f]{64})\s*$", marker.decode("utf-8"))
    if len(hashes) != 1:
        raise ValueError("ambiguous DONE hash")
    data = reader.download(candidate["id"])
    if hashlib.sha256(data).hexdigest() != hashes[0] or reader.download(done["id"]) != marker:
        raise ValueError("package changed or hash mismatch")
    # Parse CSV records, not newline counts (quoted fields may span lines).
    rows = len(list(csv.DictReader(io.StringIO(data.decode("utf-8-sig")))))
    return data, marker, rows


def check(session, store, root_folder, run_id, revision):
    data, marker, rows = verified_sample(DriveReader(session), root_folder)
    with tempfile.TemporaryDirectory(prefix="muse-drive-r2-") as tmp:
        root = Path(tmp) / "input"
        folder = root / "muse_handoff/returns/download_check/WP-0048"
        folder.mkdir(parents=True)
        (folder / "new_candidates.csv").write_bytes(data)
        (folder / "DONE.md").write_bytes(marker)
        receipt = save(store, root, run_id, revision)
        target = Path(tmp) / "restored"
        restore(store, target, run_id, receipt["manifest_sha256"])
        if (target / folder.relative_to(root) / "new_candidates.csv").read_bytes() != data:
            raise ValueError("roundtrip mismatch")
    return {"step": "drive_r2_check", "status": "ok", "files": 2, "rows": rows, "bytes": len(data)}


def main():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            if os.environ.get("R2_PRIVATE_CONFIRMED") != "true":
                raise ValueError("private bucket settings not confirmed")
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GDRIVE_SA_JSON"]),
                scopes=["https://www.googleapis.com/auth/drive.readonly"])
            r2 = R2Client()
            store = Store(r2._ensure(), r2.bucket)
            # Auth refresh and SDK exceptions stay inside the private-output boundary.
            with AuthorizedSession(credentials) as session:
                result = check(session, store, os.environ["GDRIVE_FOLDER_ID"],
                               "drive-check-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"],
                               os.environ["GITHUB_SHA"])
    except Exception:
        result = {"step": "drive_r2_check", "status": "failed"}
    finally:
        logging.disable(previous)
    print(json.dumps(result))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
