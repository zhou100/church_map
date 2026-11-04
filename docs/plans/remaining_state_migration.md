# Remaining local state migration — 2026-11-03 PT

Goal: recover the existing research state without depending on the owner's
computer. Acceptance is an exact byte comparison after remote restore, plus a
usable database backup. A local archive alone does not meet that acceptance.

## Observed and prepared

Source checkout: `/home/yujunz/llm_projects/holyhub`, revision
`2a2f598571f4d1077921620fccf1c8d75ea3f972`.

| State tree | Files | Bytes |
|---|---:|---:|
| muse_handoff/returns | 354 | 16,470,453 |
| muse_handoff/outbox | 118 | 2,259,048 |
| analytics/exports | 270 | 110,195,270 |
| Total | 742 | 128,924,771 |

Required geocode ledger, history, reconciliation, recheck history, status.csv
and received.csv all exist. No symlinks or credential-like filenames were found
in these trees; that filename check is not a semantic secret audit. No known
intake, geocode, source-recheck or seed-build writer was running. Capture held
the existing intake flock and rechecked every source hash after copying.
Original file bytes were not modified. This is a snapshot of local state, not
proof that every current Drive return has already been ingested.

One IRS CSV exceeds the existing 32 MiB object limit. Instead of weakening the
storage limits or omitting it, the prepared archive is divided into eight
16 MiB-or-smaller parts under `analytics/exports/initial_migration/` in a staging
root. `archive.json` records ordered parts, sizes and SHA-256 hashes. The gzip
tar archive contains all original paths, an inventory with source hashes and
mtimes, and `migration_backups/` with SQLite and analytics backups. This envelope
requires reconstruction before use; restoring the R2 envelope alone does not
install live state.

Private local preparation directory: `/tmp/churchmap-state-migration-20261104/`.
It contains `prepare.py`, `verify.py`, `payload/`, `snapshot/`, `state.tar.gz`, and
`verification.json`. Permissions are restricted through umask 077. Temporary
storage is not a durable remote backup; retain it until remote verification.

## Checks actually run

- Local analytics identity explicitly checked: `churchmap_analytics` on
  `127.0.0.1:5433`, 64,004,899 database bytes. Started its existing cluster only
  for backup; no ingestion, dbt rebuild, recheck, geocoding or publishing ran.
- SQLite read-only connection → SQLite backup API; `PRAGMA integrity_check`: ok.
- `pg_dump --format=custom --no-owner --no-acl`: passed.
- `pg_restore --exit-on-error --no-owner --no-acl` into new isolated
  `churchmap_migration_restore_test`, `127.0.0.1:55472`: passed.
- All 20 restored table row counts match the captured local counts. This is
  restoration evidence, not semantic validation or cloud dbt parity.
- Eight archive part hashes and all 742 archived source hashes: passed.
- Archive size: 131,339,044 bytes, including database backups and inventory.
- First identity check stopped because `inet_server_addr()::text` includes
  `/32`; corrected with `host(inet_server_addr())` and reran the identity check.
  No identity assertion was removed.
- R2 upload/remote restore: **passed**, completed 2026-11-04T05:39:12Z
  (2026-11-03 PT), run `initial-state-20261104T053851Z`. Nine snapshot objects
  (eight archive parts plus archive metadata), 131,340,484 payload bytes. All
  742 source files and both database backups match after remote retrieval.
- Downloaded analytics dump restored into new isolated `churchmap_r2_restore_test`
  at `127.0.0.1:55472`; all 20 table counts match. Downloaded SQLite integrity
  check passed. Test Postgres stopped afterward.
- Owner supplied an ignored, untracked local credential file; its permissions
  were tightened from 0644 to 0600. Values were never logged. No GitHub secret
  changes or public artifact uploads were performed.
- No application code changed. Backend/frontend/dbt suites are not rerun for
  this operational backup/documentation step; no claim of fresh dbt success.

## Completed remote backup and recovery

The existing `scripts.muse_state_store` saved root `snapshot/` under immutable
run `initial-state-20261104T053851Z`, with storage-code revision `43130d2`.
Remote restore into a new directory used the receipt manifest hash; every part,
reconstructed archive, original inventory and database backup was verified.
Private `remote-receipt.json` and `remote-verification.json` are committed with
conditional writes under the same R2 run directory and read back byte-for-byte.
Independent local copies are in `/home/yujunz/.config/churchmap/migration-receipts/`
(mode 0600). The immutable manifest does not list these companion receipts.
This completes backup migration of the captured local state, not adoption by
a live hourly pipeline. Current Drive completeness and cloud analytics/dbt
parity remain unverified.
Do not overwrite working state or adopt a stale snapshot automatically. Keep
the receipt in durable private storage. Do not print credentials, raw state,
private URLs or detailed manifests in public Actions logs.

## Existing Supabase feasibility (proposal, not applied)

Supabase supports private custom schemas. Existing code uses `raw`, `analytics`
and `analytics_seeds`; these must remain outside the exposed Data API schemas
and use a dedicated restricted role, with no production-table write grants.
Check schema collisions and effective grants before provisioning. The current
loader drops/recreates `raw.churches` and `raw.snapshot_meta`, so it must never
run under the runtime owner role against production unchecked.

Sharing the existing project avoids a new project compute charge but shares
storage, CPU, memory and connections with the API. Current plan, remaining
capacity, existing schemas/grants and rebuild peak usage have not been checked.
The local ~61 MiB database is only a starting capacity estimate. Free includes
500 MB database size; Pro includes 8 GB disk, then usage-based charges. Do not
promise zero additional cost or create roles/schemas based on this proposal.

Sources checked 2026-11-03 PT:
[custom schemas](https://supabase.com/docs/guides/api/using-custom-schemas),
[pricing](https://supabase.com/pricing),
[database size](https://supabase.com/docs/guides/platform/database-size).

Plan §1 currently proposes a separate hosted database. Sharing the existing
project changes that isolation assumption; record an explicit owner decision
before implementing it. No production access or new paid service was used here.
