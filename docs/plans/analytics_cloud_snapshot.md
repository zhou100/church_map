# Analytics cloud snapshot and single-thread dbt

Scope: implement the code path for the existing private snapshot view. No role
LOGIN/password changes, production writes, Drive changes, publishing, rechecks,
geocoding or schedule activation are included. Visitor-facing hypothesis: a bad
or silently empty source read must not replace the last accepted directory used
by analytics. Counterchecks: empty/RLS-filtered read, >20% drop, changed source,
stale capture, duplicate IDs, failed COPY and overlapping jobs retain old state.

## Producer, identity and acceptance

Run from the repository root with the analytics Python environment:

```
python -m analytics.scripts.cloud_snapshot --report /private/new-inspection.json
```

This defaults to **source read only**. PROD_READONLY_DATABASE_URL must authenticate
as churchmap_snapshot_reader (non-superuser, no BYPASSRLS). Remote TLS is forced;
loopback-only fixtures use a non-TLS connection. prepare_threshold=None is retained.
The query reads only the exact 14 approved columns of churchmap_snapshot.churches,
rejects a changed full view shape and never selects raw google_address. A single
REPEATABLE READ, READ ONLY transaction fixes both rows and observation timestamp.
A named cursor fetches bounded batches, with at most 100,000 rows / 64 MiB canonical
payload. Duplicate IDs, non-boolean flags and nonfinite JSON numbers are rejected.
No business record is printed or included in the report; it contains hashes,
source identity, scope, counts, bytes, timestamp and whether install committed.
Report files are new mode-0600 files; use an ignored/private directory, not public
GitHub artifacts. Public success/failure output contains status/counts only.

Identity binds host, port, database, the fixed view and scope, without credentials.
A pooler endpoint change therefore requires deliberate identity reconciliation.
The only current scope is all_congregations_v1; California filtering belongs in
consumers, not in a changing partial snapshot. taken_at is the source transaction
start, not a new verification time for any congregation fact.

First install requires an independently reviewed private baseline JSON:

```
{"identity":"<inspection identity>","scope":"all_congregations_v1","expected_rows":12345}
```

The count shown is an example, not a known project count. Owner/source-side counts
must corroborate it under the same scope and cutoff; copying the inspection report
unreviewed is not independent validation. Exact equality is required on first load.
Legacy SQLite metadata with no identity also requires this explicit baseline.
After acceptance, metadata is authoritative: supplying another baseline cannot
silently override source/scope changes or a large drop. A new snapshot must be
newer than the accepted observation; equal/older timestamps fail. Exactly 20%
decrease is accepted, >20% or zero fails. Scope changes/resets need a separately
reviewed migration; there is no bypass flag.

## Atomic analytics install

Only an explicitly authorized invocation adds --apply:

```
python -m analytics.scripts.cloud_snapshot --apply \
  --baseline /private/approved-first-baseline.json \
  --capacity-evidence /private/current-capacity.json \
  --report /private/new-install-receipt.json
```

ANALYTICS_DATABASE_URL must authenticate as churchmap_analytics with neither
superuser nor BYPASSRLS. The raw schema must already exist with correct ownership.
The installer holds an advisory transaction lock shared with the cloud dbt runner;
it refuses concurrent work rather than waits indefinitely. It applies the numbered
**analytics-only** migration `analytics/migrations/0001_snapshot_gate.sql` inside
the same transaction. This is intentionally outside runtime `migrations/`, so
Render startup cannot create analytics state as a side effect. The migration
preserves legacy metadata columns consumed by mart_coverage_snapshot.

The accepted rows are staged in bounded memory before target mutation. The target
transaction locks/checks the latest metadata, DELETEs/COPYs raw.churches, and replaces
the singleton metadata only after all checks. It preserves table identity and dbt
view dependencies; no DROP/CASCADE or recreation of churches occurs. Rollback
restores the old rows and metadata on any failure, including COPY failure. Multiple
metadata rows fail closed. Statement/lock timeouts bound database operations.
A report filesystem error after DB commit is not proof of rollback: inspect
raw.snapshot_meta identity/hash/time before retrying. Reports never authorize publishing.

## Capacity evidence and cloud build

Before each load and each build, current database size must be <300,000,000 bytes,
and projected size must be <400,000,000. Growth reserve is the maximum of
128,000,000 bytes, twice current analytics relation size and (for loading) four
times canonical payload size. These are conservative budgets, not peak guarantees.
The private capacity JSON must contain:

```
{"database_identity":"<hash>","observed_at":"<UTC timestamp>","disk_free_bytes":123456789}
```

This is an operator observation of current free disk after WAL/system use, at
most one hour old, bound to the target host/port/database hash. It must cover the
computed reserve. It is not inferred from pg_database_size. For the approved
shared-project layout and the same session-pooler endpoint, the inspection report's
database_identity also identifies the analytics target. A different endpoint or
database needs its own reviewed identity; do not copy evidence between targets.
Missing, stale, future-dated, mismatched or insufficient evidence fails closed.

```
python -m analytics.scripts.cloud_dbt \
  --capacity-evidence /private/current-capacity.json \
  --private-dir /private/new-dbt-run
```

Install `analytics/requirements.txt` in that environment. The runner parses
ANALYTICS_DATABASE_URL into the cloud profile env variables in memory; no shell
expansion, owner fallback or printed connection string. Cloud uses TLS require,
Session pooler port 5432, schema analytics, threads=1, no retries. Local profile
remains unchanged and is not selected by this runner. The cloud runner requires
accepted snapshot_gate_v1 metadata, rechecks capacity and holds the shared lock
through dbt completion (15-minute subprocess timeout). It runs build --full-refresh
with today's America/Los_Angeles as_of_date explicitly, addressing the existing
local project's frozen default date for cloud runs. Model SQL/seeds are unchanged.

stdout/stderr, target artifacts and dbt logs stay under a new mode-0700 directory;
only step/status reaches the public log. Anonymous dbt telemetry is disabled.
The runner does not automatically archive that directory to R2 yet. Operators
must retain private reports before discarding a runner; no workflow activates this
code. Partial dbt builds are possible: failure blocks downstream publishing, does
not pretend to roll back all dbt models, and leaves the source snapshot intact.

## Verification and remaining limits

Regression tests are `tests/test_cloud_snapshot.py`: pure gates and real SQL tests
use only an explicitly identified loopback test database. They cover exact-20%
boundary, source/scope identity, first baseline, stale captures, repeatable-read
under concurrent source changes, failed COPY rollback, view/OID preservation,
empty/shape errors, legacy metadata, advisory-lock exclusion, capacity evidence,
and private stdout on successful/failed snapshot/dbt commands.

The shared-project provisioning roles remain NOLOGIN in production. No production
connection or acceptance test is implied by local checks. Before activation:
finish source count adjudication and disk evidence, private seed/state restore
selection, hosted role/TLS verification, actual cloud dbt parity/resource checks,
private report persistence, and separately approved login/manual execution. The
SQL publisher's unqualified check_schema remains a known separate prerequisite
before publication; these commands never invoke the publisher. Timers stay off.


### Checks actually run (2026-11-04 UTC)

- Fresh loopback-only PostgreSQL 17.6 database
  `churchmap_snapshot_acceptance_test`, port 55473, pgvector 0.8.1. Confirmed test
  target before `python -m backend.db.migrate`; migrations 0001–0006 applied.
- `python -m pytest -q` (Python 3.11.15): **611 passed, 5 skipped,
  10 subtests passed**. New cloud tests: 18 passed. Two legacy modules are
  superseded; three parity cases lack SF/CA fixture rows. No cloud SQL test skipped.
  Existing Starlette/httpx deprecation warning remains.
- Required `DBT_PROFILES_DIR=analytics/dbt analytics/.venv/bin/dbt build
  --project-dir analytics/dbt --full-refresh` on a separate isolated PG17.6
  analytics restore: **28 successful build nodes, 90 passing tests**, no failures.
  Private inputs/logs remained ignored/private. This used the local profile and
  its existing default date; it does not establish cloud/current-date parity.
- `dbt parse --target cloud --no-partial-parse` with synthetic connection values:
  passed; no database connection. Command/timeout/private-output behavior is
  tested with a subprocess substitute, not a hosted dbt build.
- Initial restore failed because the temporary PG17 client lacked compression;
  the first build consequently failed on missing raw tables. Recreated only the
  isolated analytics test database, restored with the available PG14 client
  (exit 0), and then completed the full dbt build above.
- Frontend/browser checks not run: no UI changes. Production queries, writes,
  login activation, hosted TLS/pooler checks, timers and paid calls not run.
