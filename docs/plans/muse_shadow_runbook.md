# Manual Muse shadow run (PR A)

This job is manual-only and main-only. It does not replace `ChurchMapMusePull`.
No Drive write API, production writer, publication, Census fetch or paid model
call is used. The only mutable remote pointer is the existing cloud snapshot
`accepted.json`, advanced by `cloud_dbt` after successful dbt, using its existing
CAS rule. A later archive/count failure does not undo that acceptance.

## Owner sequence

1. Run **muse-storage-check** on main first and verify success. Confirm bucket
   privacy using [the storage runbook](muse_storage_runbook.md); a prefix alone
   is not access control.
2. Wait for the local hourly pull to finish. Capture a quiescent initial snapshot
   under the existing lock; independent intake/geocode writers must also be idle:

   ```bash
   flock -n muse_handoff/returns/.drive_pull.lock \
     python -m scripts.muse_state_store save --root ~/llm_projects/holyhub \
     --run-id shadow-input-YYYYMMDD --revision "$(git rev-parse HEAD)" \
     --receipt /private/new-input-receipt.json
   ```

   `/private` is an example existing private directory, not a required path.
   Keep the receipt private. Restore requires its exact manifest hash. Capture
   all three state trees, including the package definitions/status, received
   records, recheck history and geocode ledgers. The runner rejects missing trees.
3. Configure Actions values below. For the first source baseline provide the
   independently checked identity, scope and row count. The owner previously
   reported 134,377 rows; reconfirm the scope/cutoff if using that count later.
   Subsequent jobs use R2 `accepted.json`; inputs cannot replace an accepted baseline.
4. After this code is reviewed and merged, manually run **muse-shadow** on main.
   No production job was triggered as part of implementing this PR. Each job
   gets a fresh Postgres service and a loopback-only `churchmap_run_00000000`
   database; the name may repeat because the service is destroyed after the job.
5. Compare the selected shadow with the local run immediately following the
   **same initial snapshot and delivery cutoff**. Do not compare an arbitrary
   later local state. Hold the local lock while capturing files and sidecar counts;
   independent state writers must also be idle:

   ```bash
   python -m scripts.muse_shadow_compare download --run-id shadow-RUN-ATTEMPT \
     --destination /private/new-shadow-download
   ANALYTICS_DATABASE_URL=postgresql://analytics@127.0.0.1:5433/churchmap_analytics \
     flock -n muse_handoff/returns/.drive_pull.lock \
     python -m scripts.muse_shadow_compare capture --root . \
     --drive "/mnt/g/My Drive/churchmap-handoff" \
     --as-of-date YYYY-MM-DD --output /private/new-local-report.json
   python -m scripts.muse_shadow_compare compare \
     --shadow /private/new-shadow-download --local /private/new-local-report.json \
     --output /private/new-comparison.json
   ```

   Use the actual local dbt `as_of_date`, not the report creation date. Capture
   records the code revision. Compare exits 1 for unresolved differences. Reports
   contain private identifiers, timestamps and hashes; never paste them into
   public logs/issues. R2 download requires the same privacy confirmation and
   credentials as save. It creates a new directory and checks every object hash.

## Configuration

| Kind | Name | Purpose |
|---|---|---|
| Secret | `GDRIVE_SA_JSON` | Existing Viewer service account; only `drive.readonly` scope |
| Variable | `GDRIVE_FOLDER_ID` | Existing shared root folder |
| Secrets | `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Existing private R2 store |
| Variable | `R2_PRIVATE_CONFIRMED=true` | Owner assertion after checking public access settings |
| Secret | `PROD_READONLY_DATABASE_URL` | Existing source snapshot reader through Session pooler |
| Variable | `MUSE_STATE_RUN_ID` | Explicit selected initial snapshot |
| Secret | `MUSE_STATE_MANIFEST_SHA256` | Exact hash from private receipt; never a dispatch input or public output |
| Dispatch inputs | `baseline_identity`, `baseline_scope`, `baseline_rows` | Independently approved first baseline; blank identity after acceptance exists |

`ANALYTICS_DATABASE_URL` is generated/configured by the ephemeral job, not a
production secret. No `DATABASE_URL` or publisher credential is supplied. Pull,
validator, rechecker and seed children receive no Drive/R2/production credentials.
Only cloud_dbt receives the read-only source and R2 credentials it requires.

## Evidence and comparison semantics

The runner uses a new private temp code copy, restores the selected snapshot to a
new directory, then copies only those restored state trees into the temp checkout.
It never installs them into the owner's working tree. Tracked seed inputs,
including `dedup_report.csv`, accompany the code. All Drive `returns/WP-xxxx`
files are bounded (32 MiB each, 256 MiB total, 10,000 entries, depth 12); unsupported
native Drive documents, ambiguous names, traversal and cycles fail closed.
Oversized files remain absent and existing pull refuses to ingest their listed
outputs. DONE hashes are checked by **the existing pull**, not a duplicate parser.
A changed DONE during download fails before intake. Drive modification times are
preserved because pull uses DONE's mtime as `received_at`. Check this against the
local Drive desktop mirror; an mtime discrepancy is reported, not normalized away.

The existing `pull --no-build --no-geocode` runs validation and source rechecking,
then `build_seeds.py`, then `cloud_dbt --run` builds the empty disposable database.
Pending-geocode count reuses the geocoder's SQL and exact-address ledger key,
without fetching or changing geocode state. Counts of `mart_publish_churches` and
`mart_publish_new` are observations only, not a publish dry run.

Archive prefix: `analytics_private/v1/shadow/shadow-RUN-ATTEMPT/`. Every object uses
`put_once`; the archive manifest is written last and binds hashes and sizes.
The archive includes before/after private comparison reports, downloaded Drive
input hashes/times, the full local Drive mirror (including reference, feedback
and status files that would have been written), child logs, dbt logs/target,
cloud receipt/failure diagnostics, and a shadow status digest. Its state receipt
selects the separate `shadow-RUN-ATTEMPT-state` snapshot saved through
`muse_state_store`. The initial snapshot and local authoritative state remain intact.
Failures also attempt archival; an R2 outage/limit can prevent a complete archive.
Do not interpret missing archive or public failure as a successful comparison.
There are no public GitHub artifact uploads. Public application output and step
summary contain only fixed step/status/error code and integer counts. Provider
errors, names, URLs, excerpts, phones and connection strings stay private.

The digest records WP states/times and available counts. Crawler fetch/extract/tag
are **not observed**, publishing is **not run**, and a full rolling 24-hour reject
history is **not measured**: this one shadow run has no authoritative event ledger.
No invented zeros or raw log tails substitute for these unavailable fields.

Comparison retains every package field, received additions/replacements, exact
seed hashes, recheck verdict distributions by file, and mart counts. A successful
shadow leaves `pending_build`/`build_failed` as recorded by `--no-build`; local
`ingested` is an explicitly expected state difference when DONE hashes agree.
Other field differences remain unresolved. There is no authoritative state update
just to make these statuses match. Live recheck timestamps, later site edits,
local geocode results and a different dbt date may create differences; inspect
and explain them rather than accepting them automatically.

The known directory baseline difference (local May SQLite 133,939; cloud observed
134,377) is separated from unresolved differences. It does **not** automatically
excuse all mart differences: trace affected rows before attributing a change to
those 438 directory records. New deliveries during either run invalidate a claim
of equal inputs; inspect archived input hashes and the local delivery files first.
The comparator checks local delivery hashes, mtimes and inventory against the archived
Drive inputs. It cannot prevent a writer changing files after capture; keep the
comparison window controlled.

## Verification

See the PR's check results. Real Actions/Drive/R2 execution is **not run** in this
PR; it requires merger followed by an owner-triggered manual run. Synthetic tests
cannot prove live access, cloud-versus-local parity or a successful cutover.

Local verification on 2026-11-04, based on main `418806c`:

- **Passed:** Python 3.11.15; fresh PostgreSQL 17.6 at 127.0.0.1:55483,
  database `churchmap_shadow_test`, pgvector; migrations 0001–0006.
- **Passed:** `python -m pytest -q -rs`: 680 passed, 5 skipped,
  10 subtests passed. Three SF parity tests lack directory fixtures; two legacy
  modules are superseded. No SQL integration tests were skipped.
- **Passed:** eight shadow tests, including actual pull/validator/rechecker/seeds,
  accepted/rejected/hash-mismatch packages, fixed public output on success/failure,
  immutable original state, archive download integrity, Drive bounds, and real
  disposable dbt `--full-refresh` with synthetic directory/state and offline S3.
  The synthetic audit input must be nonempty: the existing quality_reviews seed
  infers an integer verdict for an empty audit and dbt rejects it. This PR does
  not change that existing seed behavior or claim incomplete snapshots build.
- **Passed:** workflow trigger/ref/concurrency/permission checks, local runbook
  link, `git diff --check`.
- **Not run:** real Actions, Drive, R2, production read or local/cloud parity.
  Full private historical corpus dbt and frontend/browser checks were not run;
  the dbt result above is bounded synthetic regression evidence.
