# Muse Drive → private R2: setup and bounded verification

This is the storage portion of execution-plan PR 1, not the hourly pipeline.
No production database, extraction, requeue, source recheck, publishing, or Drive
write is included. Do not disable `ChurchMapMusePull` yet.

## Owner configuration (one time)

1. In Google Cloud Console, select/create a project and enable **Google Drive API**
   (APIs & Services → Library → Google Drive API → Enable).
2. IAM & Admin → Service Accounts → Create service account, e.g.
   `churchmap-drive-reader`. No project IAM role and no domain-wide delegation
   are needed for reading a folder explicitly shared with this account.
3. Copy the service account email (`…@….iam.gserviceaccount.com`). In the existing
   `churchmap-handoff` folder's **Share** dialog, add it as **Viewer**. Keep the
   folder restricted; do not enable public-link sharing. This implementation
   requests only `https://www.googleapis.com/auth/drive.readonly`.
4. On the service account, **Keys → Add key → Create new key → JSON**. In
   [repository Actions secrets](https://github.com/zhou100/church_map/settings/secrets/actions),
   add **`GDRIVE_SA_JSON`** containing the complete downloaded JSON. Do not paste
   it into chat, repository files, workflow source, or logs. The optional
   `google-auth[requests]` dependency performs signing and token refresh; it is
   installed only for this CLI, not into the runtime API image.
5. In repository **Settings → Secrets and variables → Actions → Variables**, add:

   | Variable | Value |
   |---|---|
   | `GDRIVE_FOLDER_ID` | `1yGFH8BWjtYZz0o-wU9TTmDG4BmTlcmb0` |
   | `R2_PRIVATE_CONFIRMED` | `true`, **only after the check below** |

   Existing secrets are reused unchanged: `R2_ACCOUNT_ID`, `R2_BUCKET`,
   `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. The repository secret-name list was
   inspected; secret values were never read.

**R2 privacy check:** in Cloudflare → R2 → the existing bucket → Settings, verify
that public `r2.dev` access is disabled and no public custom-domain/Worker route
exposes `analytics_private/`. A prefix is not an access control boundary. The
confirmation variable is an operator assertion, not an automated audit. If the
bucket is public, do not set it; an access change needs separate review before
uploading private returns.

**Drive write limitation:** a service account has no personal Drive storage
quota and cannot own new files. Viewer + read-only scope is sufficient here.
The plan's earlier blanket instruction to give the account Editor access does
not establish that it can create new status files or WP packages in My Drive.
Future writes need a separately approved user OAuth identity or a suitable
Shared Drive. No write credentials or consent screen are needed for this step.

References: [enable APIs](https://developers.google.com/workspace/guides/enable-apis),
[direct service-account access](https://developers.google.com/workspace/guides/create-credentials),
[create JSON keys](https://docs.cloud.google.com/iam/docs/keys-create-delete),
[Drive download scopes](https://developers.google.com/workspace/drive/api/guides/manage-downloads),
[service-account storage limitation](https://developers.google.com/workspace/drive/api/guides/about-shareddrives).

## Manual verification workflow

After review and authorized merge, use Actions → **muse-storage-check** → Run
workflow on **main**. Other refs are skipped. The workflow is manual-only;
`concurrency: muse-pull` with `cancel-in-progress: false` prevents overlapping
runs. It has no `pull_request_target` trigger and no scheduled trigger.

The job resolves `returns/WP-0048` under the configured folder, rejects duplicate
names or unexpected MIME types, reads the CSV as original bytes (`alt=media`),
checks its SHA-256 against DONE, and re-reads DONE to reject a changed package.
It saves a two-file snapshot and restores into a new temporary directory. The
public result has only step, status, file/row/byte counts. No CSV, hashes,
provider errors, object URLs, signed URLs, or detailed diff is echoed/uploaded
as a GitHub artifact. The two-file snapshot stays in private R2 for inspection.
An unsuccessful result is generic by design; do not enable SDK debug logging
or print the credential/HTTP body to diagnose it.

Snapshot run ID is `drive-check-<GitHub run ID>-<attempt>`; it is separate from
any production-state snapshot. A successful check proves only this bounded
Drive → R2 round trip. It does not migrate geocode ledgers, recheck history,
received.csv, status.csv or analytics, nor establish 24-hour operation.

## Snapshot layout and recovery

Only these local, gitignored trees are captured by `scripts.muse_state_store`:

- `muse_handoff/returns/` (including received.csv and recheck history)
- `muse_handoff/outbox/` (including status.csv and package definitions)
- `analytics/exports/` (including geocoding ledgers, history, reconciliation and reports)

The exact source file `analytics/exports/irs/eo_ca.csv` is excluded at capture.
It is a public IRS download, reproducible from
[the IRS source](https://www.irs.gov/pub/irs-soi/eo_ca.csv) using the command in
`analytics/scripts/irs_leads.py`; neither pull nor dbt consumes it. Derived leads,
package inputs, recheck history and geocode ledgers are **not** excluded. The
manifest records this exact-path policy, source URL and reason. The local file
is untouched; all other per-file/total limits and symlink checks remain in force.
Older manifests without this metadata still restore their exact recorded files.
Use a new run ID after this policy change; never replace an earlier manifest.

For a complete Python 3.11 uploader setup, hidden credential prompts, bucket-scoped
local token and private receipt directory, follow
[shadow runbook step 2](muse_shadow_runbook.md#owner-sequence). GitHub secrets do
not automatically supply local credentials.

Missing trees are allowed for bounded checks; file counts are not proof of a
complete migration. `holyhub.db`, analytics Postgres, repository files and env
files outside these trees are not captured. The complete initial migration
still needs the owner's local state and a cloud analytics destination.

Objects use:

```
analytics_private/v1/blobs/<sha256>
analytics_private/v1/runs/<run-id>/manifest.json
```

All puts use `If-None-Match: *`. Existing objects are reused only after exact
byte comparison. All blobs precede the manifest, so interrupted uploads cannot
publish a complete snapshot. A retry with the same run ID/content is idempotent;
changed content under that run ID fails. Unreferenced blobs may remain after
failure; there is no automatic deletion or rollback.

The manifest binds schema version, run ID, full code revision, exact relative
paths, sizes and hashes. There is deliberately no mutable `latest` pointer:
restore requires a chosen run ID **and** the independently retained manifest
hash. A delayed run cannot replace the current state. The future hourly runner
must choose the appropriate committed snapshot; this PR does not implement that
selection or publication authorization.

Local save (credentials supplied through the environment; never add literal
secret values to this command):

```bash
# Run with other state writers idle. This lock coordinates the existing hourly
# pull only; ensure no independent geocoder/intake process is writing as well.
flock muse_handoff/returns/.drive_pull.lock \
  python -m scripts.muse_state_store save --root . \
  --run-id initial-state-YYYYMMDD \
  --revision FULL_40_CHARACTER_GIT_SHA \
  --receipt analytics/exports/private-state-receipt.json
```

Set `R2_PRIVATE_CONFIRMED=true` only after checking the bucket. The receipt must
be a new path with an existing parent; it is written mode 0600 and contains the
manifest hash needed for restore. Store it privately. If receipt writing fails
after remote commit, the snapshot can still exist; fix the receipt path and
retry the same unchanged run to recover the receipt.

```bash
python -m scripts.muse_state_store restore \
  --destination /tmp/NEW-state-directory \
  --run-id initial-state-YYYYMMDD \
  --manifest-sha256 HASH_FROM_PRIVATE_RECEIPT
```

Restore verifies every file before installing the tree, refuses existing
local destinations and symlinks, and never overwrites live state. Verify current
scope/input identity before adopting recovered files. File **bytes** are
preserved; filesystem modification times are not. Fact/check timestamps inside
CSV/JSON remain unchanged. Limits: 10,000 files, 32 MiB per file, 256 MiB total,
4 MiB manifest. Capture requires a quiescent writer; per-file mutation checks
are not a multi-file transaction.

[R2 conditional writes](https://developers.cloudflare.com/r2/api/s3/extensions/)
provide atomic create-once behavior. No code accesses the crawler's `raw_html/`
namespace, changes its content hash, or deletes remote objects.

## Evidence and remaining gates

- 2026-11-03: connector download of WP-0048 CSV succeeded: 165,790 bytes, 86 CSV
  records, SHA-256 `7d5b0b23fd01c4e44ac7ed525f19778e6140a5d6d766314bf15f0851a934db9b`,
  identical to DONE. Stored locally under ignored returns/download_check/.
  Drive search omitted the CSV, but direct folder fetch exposed it. Do not
  interpret connector search absence as a missing file.
- Synthetic tests cover byte-preserving round trip, immutable run collisions,
  interrupted writes, corrupt/missing objects, path traversal, symlinks,
  duplicate Drive names, pagination/cycles, changed DONE, CSV embedded newlines,
  and public success/failure output. They do not prove live R2 access or privacy.
- Actual R2 save/restore and Actions service-account access: **not run**, local
  R2 and Drive credentials unavailable. Repository secrets cannot be read back.
- Full historical migration, cloud analytics/dbt parity, auto-publish gate,
  hourly orchestration and 24-hour observation: **not implemented/verified by
  this storage step**. Keep the Windows task until those gates pass.

- Full backend check: Python 3.11.15, new local `churchmap_storage_test` at
  `127.0.0.1:55472`, pgvector 0.8.1; actual migrations 0001–0006 passed.
  `python -m pytest -q`: **593 passed, 5 skipped, 10 subtests passed**.
  Skips: three parity cases need SF data; two legacy tests are superseded.
  Optional Drive auth dependency installed/imported in the temporary test env.
  Workflow YAML and local documentation links checked; `git diff --check` passed.
  dbt not run: complete private source/state and analytics sidecar unavailable.
  No frontend changes, so frontend/browser checks not run.
