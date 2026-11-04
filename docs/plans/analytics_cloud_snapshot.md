# Disposable analytics jobs and private snapshot acceptance

PR #77 was revised after review: analytics uses a fresh Postgres service per job,
not permanent schemas in production Supabase. All dbt models are views/tables,
rebuilt with --full-refresh; no incremental models or dbt snapshots need a permanent
analytics database. Research returns, receive timestamps, recheck/geocode history
and other file inputs must still be restored from their selected private R2 state.
This does not imply that all required inputs have been restored into a cloud job.

Visitor-facing hypothesis: an empty/partial/stale source read must not become the
accepted directory input to analytics. Counterchecks include empty reads, >20%
drops, source/scope changes, delayed results, failed COPY/dbt builds, and two jobs
racing to advance the same accepted state. No command publishes facts.

## Read-only source and first baseline

```
python -m analytics.scripts.cloud_snapshot --report /private/inspection.json
```

PROD_READONLY_DATABASE_URL authenticates as churchmap_snapshot_reader, with neither
superuser nor BYPASSRLS. Remote TLS is forced and prepare_threshold=None retained.
REPEATABLE READ + READ ONLY fixes the observation time and rows. The complete view
shape must match the 14 approved columns of churchmap_snapshot.churches; raw
Google address is replaced by has_google_address. A bounded cursor rejects empty
reads, duplicate IDs, non-boolean flags, nonfinite numbers, >100,000 rows or >64 MiB.
Rows (including phones) remain private and never enter public logs or receipts.

Identity hashes host/port/database/view/scope; changing pooler endpoint needs
explicit reconciliation. Scope is all_congregations_v1, not an implicitly changing
California subset. Capture time is not a congregation fact's verification time.
The inspection report contains only identity, scope, hash, counts, size and time;
it is NOT acceptance. Files are created atomically, mode 0600, without overwriting.
A read failure leaves no empty report, so the same filename can be retried.

The first accepted run needs a private independent baseline JSON:

```
{"identity":"<inspection identity>","scope":"all_congregations_v1","expected_rows":12345}
```

12345 is an example. The owner/source-side count must corroborate the same scope
and cutoff; blindly copying an inspection receipt is not independent validation.
Subsequent runs compare to R2 accepted state, never a replacement baseline: reject
zero, >20% decline, source/scope change, or non-increasing observation time. Exactly
20% decline is allowed. A new source/scope needs separately reviewed reconciliation.

## Disposable database and manual job

The caller provisions a new empty local Postgres database per run, named
churchmap_run_<8-to-32 lowercase hex characters>, and destroys it when the job
ends. A future Actions job can use a postgres service with a generated database
name. No workflow is activated in this PR, and no existing database is dropped by
these scripts. The service/database lifecycle remains the caller's responsibility.

ANALYTICS_DATABASE_URL must use a literal loopback host (127.0.0.1/localhost/::1)
and this disposable name. Remote hosts, alternate libpq hostaddr/services/options,
and databases containing user schemas/tables/functions are refused. The guarded
loader creates raw tables and COPYs the snapshot in one transaction. COPY failure
rolls back newly created objects. Existing raw tables or dependent views are never
dropped/replaced; even a previously failed job database is not reused after load.
There is no production analytics migration, capacity JSON or hourly human check.

Use an environment with analytics/requirements.txt and the existing boto3 storage
client (already used by #73). No new dependency is introduced. Restore private
seeds from the selected R2 inputs before building. Then, only after authorization:

```
python -m analytics.scripts.cloud_dbt --run \
  --baseline /private/approved-first-baseline.json \
  --revision <full-40-character-code-SHA> \
  --private-dir /private/new-run
```

Supply the existing R2_* variables and R2_PRIVATE_CONFIRMED=true.
Actions reuses R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET;
no new storage secret is required. After separate approval, the remaining production
setup is enabling the existing source reader's LOGIN and configuring its connection
as PROD_READONLY_DATABASE_URL. ANALYTICS_DATABASE_URL is generated for the ephemeral
service by the job, not an owner-provided hosted database secret. --baseline is only
needed when accepted.json does not exist. The job performs, serially:

Before source/database work, inventory every `analytics/dbt/seeds/*.csv` by basename
and SHA-256. All five private seeds (muse_results, muse_candidates, quality_reviews,
source_checks, geocodes) are required. Missing files fail with public fixed error
code `seed_missing`; invalid/symlink files use `seed_invalid`. Hashes are rechecked
after dbt, and changes fail with `seed_changed` before accepting the run. Run in an
exclusive checkout: this check detects persistent changes, not a malicious writer
changing and restoring files during dbt. Hashes establish input identity, not that
the selected R2 inputs are current or independently verified.

1. Read private R2 accepted metadata and its ETag; only NoSuchKey means absent.
2. Capture the source and validate against that metadata or the first baseline.
3. Load the new disposable database.
4. Run dbt build --full-refresh with target job, threads=1, no retries, a 15-minute
   timeout and explicit today's America/Los_Angeles as_of_date. Both successful
   exit and nonempty run_results containing only success/pass are required.
5. Store an immutable build receipt and conditionally advance accepted.json.

The job profile uses non-TLS only for its loopback service; production snapshot
reads retain TLS. The dbt child receives job connection variables but no production
connection string, R2 credentials or ambient PG* defaults. Its logs/compiled output
stay under the new mode-0700 private directory; public output is counts/status
only, on success and failure. Telemetry is disabled. The job leaves the local
marts available for a separately authorized downstream step until service teardown.

## R2 concurrency, failure and recovery

Private prefix: analytics_private/v1/snapshot_gate/.
- runs/<run-id>.json is an immutable successful-build receipt.
- accepted.json is the authoritative cross-run count/source/time/hash baseline.

Both runs/<run-id>.json and accepted.json include `seed_sha256`, mapping every seed
filename to its SHA-256 without its content. Previously created metadata without
this field may still serve as a source-count baseline, but cannot attest seed
provenance; all new accepted runs include it. The owner confirmed in round 2 that
acceptance follows dbt success, without waiting for publish dry run: this is only
the source snapshot baseline, and publication keeps its independent gate.

First creation uses If-None-Match: *; replacement uses If-Match with the exact ETag
read before capture. R2 evaluates these conditions atomically ([R2 consistency
contract](https://developers.cloudflare.com/r2/reference/consistency/)). Two jobs
reading the same baseline cannot both advance it. A conflict fails the run and
blocks downstream use; it is never retried as an unconditional write. Future
Actions orchestration should also serialize the entire analytics/publish job with
cancel-in-progress:false. CAS is a state guard, not a production publishing lock.

A failed capture/load/build leaves accepted.json unchanged. A receipt uploaded
before a failed CAS is only build evidence, not acceptance. A network failure after
PUT or failure writing the local receipt has an ambiguous acknowledgement: compare
accepted.json's run_id/revision/hash with the immutable run receipt before retrying.
Never reset/delete accepted.json to bypass a rejected count. After failure discard
the disposable DB; do not publish its marts. R2 permission/server errors, invalid
metadata/version, and oversized state fail closed instead of becoming first runs.
The actual R2 conditional-write integration has not yet been exercised live.

## Security boundary and activation limits

A dedicated reader protects source credentials only while the job has no writable
production credential. Putting reader and publisher secrets in the same process
or job weakens that separation; this code never receives a production writer URL
for its operations. Future workflow design must scope secrets by step/job and keep
untrusted PR jobs away from all production/R2 secrets. A loopback/name check guards
against accidental targeting; it is not protection against a malicious local proxy.

Do not enable the production churchmap_analytics role. Existing NOLOGIN roles and
schemas created during #76 are untouched; any cleanup is a separate reviewed SQL
change. Only source-reader login/transport verification will eventually be needed.
No production connection, write, role change, schedule or paid call was made here.

Before activation: approve the first count baseline, verify the real source reader,
restore/verify all private inputs, test live R2 CAS and report retention, and compare
actual cloud job outputs. Detailed logs are private locally, but automatic R2 log
archiving is still a separate step. Publishing still requires its schema handling,
exact diff gate and authorization. An accepted source snapshot is not authorization
to publish. No hosted persistent analytics database is required by this path.

## Verification — second review, 2026-11-04 PT

Passed:
- Confirmed fresh loopback test DB churchmap_pr77_round2_test, PostgreSQL 17.6,
  port 55473, pgvector 0.8.1. `python -m backend.db.migrate`: 0001–0006 applied.
- `python -m pytest -q -rs`: **633 passed, 5 skipped, 10 subtests passed**;
  all 40 snapshot/job tests ran. New cases cover every required private seed
  missing before dbt, all-CSV hashing, changed inputs blocking acceptance, identical
  seed hashes in immutable/current receipts, and a public fixed error code.
- Three fresh local job databases, same raw rows/timestamp and the same nine seeds:
  local target at 2026-10-19; job target at 2026-10-19; job target at 2026-11-04.
  Each full build: **28 success, 90 pass, no errors/skips**. dbt models/tests unchanged.
- `git diff --check`: passed.

The local invocation used the required command with explicit isolated connection
variables and date override:

```
DBT_PROFILES_DIR=analytics/dbt analytics/.venv/bin/dbt build \
  --project-dir analytics/dbt --full-refresh --vars '{"as_of_date":"2026-10-19"}'
```

The job invocations used run_build's real subprocess, target job, threads=1,
--full-refresh and explicit date. All build logs/target paths remained private.
The local target retains threads=4. Seed hashes were compared before and after
every build; no inputs changed. Input identity:

- Canonical raw rows SHA-256:
  `9564031e42e572f180bda77ff30ce0d6a68db409286e7f75ba293f3db4be6491`.
- SHA-256 of sorted compact JSON filename→seed-hash manifest:
  `3e91dd2bf36e27459e4134795a2b76e7e04b7586698d26707e6f2308f23754b0`.
- Reproduction script: private `/tmp/churchmap-pg17-build/compare-pr77-round2.py`;
  complete row comparisons/input hashes: private `round2-comparison/evidence.json`
  under that directory; per-entity date-cause evidence stays private there too.

### Same-date parity and date-only delta

Implementation clarification: mart_coverage_snapshot has **visit_ready**, not
map_ready. Its grain is geo_scope × source; mart_new_congregations has map_ready
and one row per new-congregation candidate. These quantities are not added.

For the same date (2026-10-19), all columns of all **six coverage rows** matched
exactly, including source observation metadata; candidate counts and readiness
flags also matched. Queries used `SELECT * FROM analytics.mart_coverage_snapshot
ORDER BY geo_scope,source NULLS FIRST` and counts filtered by profile_ready/map_ready
in analytics.mart_new_congregations. Date-only comparisons exclude as_of_date itself.

| Metric / grain | local 10-19 | job 10-19 | job 11-04 | Date delta |
|---|---:|---:|---:|---:|
| Directory records, national scope | 133939 | 133939 | 133939 | 0 |
| Directory visit_ready, national scope | 103 | 103 | 103 | 0 |
| New-congregation candidates | 2394 | 2394 | 2394 | 0 |
| Candidate profile_ready | 1168 | 1168 | 1167 | -1 |
| Candidate map_ready | 1052 | 1052 | 1051 | -1 |

All 14 coverage count fields across all six groups remain unchanged with the date
advance. National counts aggregate only national rows across sources, never the
additional overlapping Muse scopes. Candidate denominator is the 2,394 rows of
mart_new_congregations in this fixed input, not production or all raw churches.

Cause verified by entity comparison: no directory research row crosses the date
boundary; two candidates' fb_last_post_date are in [2025-10-19, 2025-11-04).
Their fb_page_fresh flags expire under the model's exact as_of_date - 365 rule.
One previously map-ready candidate relies on fb_page status evidence and loses
verified_active, profile_ready and map_ready. There is one loss and zero gains;
this explains the entire -1, rather than a target/thread regression. No model or
freshness rule was changed to make the builds agree.

Limits / not run:
- This private legacy sidecar snapshot contains 133,939 rows, above capture()'s
  100,000-row limit. The matrix loaded the already available snapshot into isolated
  databases; it is **not** end-to-end production capture acceptance. Real source
  size is unverified; a source exceeding the existing limit will fail closed.
  The limit was not increased. Bounded capture is separately tested with synthetic
  data and a real local reader role.
- Five pytest skips: two superseded modules and three missing SF/CA parity inputs.
  Existing Starlette/httpx deprecation warning remains.
- R2 tests are offline CAS simulation plus SDK parameter validation, not live R2.
  Production reader login/TLS, Actions lifecycle and automatic private-log archival
  remain unverified. No frontend/browser checks (no UI changes), production SQL,
  login activation, timers, publishing or paid calls were run.
