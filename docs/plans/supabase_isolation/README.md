# Supabase isolation proposal — NOT EXECUTED

## Dependency finding and limits

Code inspected at `43130d264942fd29341bc7188c7b886dd3ab3f86` (same application
code as the preceding documentation branch). No Supabase SDK, PostgREST,
`/rest/v1`, `/graphql/v1`, anon-key or service-role client was found in active
frontend, backend, scripts, analytics or workflows. Frozen v1 was not executed.

- `frontend/src/api/client.js` sends requests to `/api`, optionally under
  `VITE_API_URL`; `frontend/vercel.json` rewrites them to Render.
- `backend/db/pool.py` uses psycopg and `DATABASE_URL`, with
  `prepare_threshold=None`; no Supabase HTTP data client.
- `backend/auth.py` and `frontend/src/googleIdentity.js` use Google Identity
  Services and tokeninfo, not Supabase Auth.
- `frontend/package.json` has no Supabase dependency. Crawler workflows call
  the ChurchMap backend. Analytics/publisher use PostgreSQL connections.

Thus repository-defined ChurchMap flows do not depend on the Data API.
Production deployed revisions/environment overrides and external tools were
not audited, so this is not proof that disabling it has no other consumers.
Do not infer API usage from database connection counts. Before changing it,
review Data API request logs and deployed frontend network traffic, identify
external consumers, and record the Render runtime database role (no password).

Owner-exported SQL at 2026-11-04T06:03:57Z confirms a read-only transaction,
130,067,603 database bytes and 9/60 connections at that instant. Later supplied
UI shows 138.46 MB / 0.5 GB; do not silently equate the different observations.
The local analytics DB is 64,004,899 bytes, so static capacity looks sufficient;
full-refresh peak disk, CPU/RAM and WAL remain unmeasured.

Operational access findings are kept in the private owner handoff. Address any
confirmed access issue separately and before the analytics rollout, after
confirming the actual runtime role; do not wait for the full analytics audit.
The public document does not serve as an incident report. Earlier Git revisions
and review comments may retain removed text; this edit is not history erasure.

Project PostgreSQL version: **17.6 (major 17)**, supplied by the owner from SQL
Editor on 2026-11-04 PT. The owner also inspected the Render Environment database
role; the operational identity is retained in the private handoff, not published
here. This confirms configured identity, not a live backend session observation.
Revised SQL targets PG16+; validation must now use PG17 with Supabase-style roles
and a non-superuser provisioning account. No matching-version test has run.
PG15 needs a separate reviewed membership variant, not blind syntax substitution.

## Proposed sequence (requires approval, no changes made)

1. Record current dashboard settings, full table/column/sequence/function ACLs,
   default ACLs, memberships and runtime identity privately. Refresh observations
   before apply. Existing exports do not contain enough detail for exact ACL rollback.
2. If deployed/external consumer checks confirm Data API unused, disable the
   **Data API** in the dashboard. Do not simulate disabling it with undocumented
   SQL settings. This leaves PostgreSQL connections available. Separately turn
   off automatic exposure of new tables, recording any actual ACL changes.
   Turning off automatic exposure alone does not fix existing table grants.
3. Review `prepare.sql`: creates two dedicated NOLOGIN roles, three analytics
   schemas and an administrator-owned private snapshot schema/view. The view
   returns only has_google_address, never raw google_address. It fails
   on preexisting role/schema collisions and detected inherited write grants or
   callable SECURITY DEFINER functions in any non-system schema accessible to the role, plus sequence mutation grants. It neither edits production data
   nor revokes existing runtime access. Do not expose its schemas to Data API.
   Provisioner temporarily receives SET (not INHERIT) on churchmap_analytics,
   then loses SET at transaction end. PG16 creator ADMIN-only membership is
   retained to permit later containment/removal without superuser privileges;
   removing that as well would require another authorized role administrator.
   No application role becomes a member of a privileged role.
4. Provision passwords privately and enable LOGIN only after grant verification.
   Use Session pooler + TLS; custom-role usernames include the project reference.
   Analytics builds as churchmap_analytics; never as postgres. The existing profile still has threads=4: LOGIN and execution remain blocked
   until a tested TLS/cloud-profile change ships with threads=1. The proposed
   120s statement timeout is unmeasured; benchmark it on the isolated matching
   version and review any adjustment before activation.
   Do not give either role publisher privileges, pg_read_all_data, membership in
   service_role, or database CREATE. Runtime DATABASE_URL stays unchanged.
5. Configure Actions ANALYTICS_DATABASE_URL and PROD_READONLY_DATABASE_URL.
   Current dbt profiles separately consume ANALYTICS_PG* variables and need an
   explicit adapter/configuration update, TLS and threads=1. load_snapshot.py
   still reads SQLite; a bounded production reader of churchmap_snapshot.churches must be implemented.
   Its admin-owned view uses the owner's RLS permissions. An ownership/RLS change
   can produce a successful but empty SELECT; a raised SQL error is not assured.
   The future reader must fail closed BEFORE replacing raw.churches: materialize
   one bounded, consistent source snapshot, validate its schema/identity and count,
   abort on zero rows or a >20% decrease from the last accepted count for the same
   source/scope. The 20% threshold is a proposed reviewable safeguard, not a
   measured quality tolerance. First load requires an independently checked
   nonzero baseline; missing/mismatched baseline blocks, rather than auto-resets.
   raw.snapshot_meta currently has no accepted row count/scope/hash fields: the
   reader change must add them (or equivalent immutable metadata), preserve the
   previous snapshot on failure, and atomically commit data plus metadata after
   checks. Do not run the old DROP/reload path first. Legitimate large decreases
   require an explicitly reviewed new baseline. Tests must cover empty reads,
   exactly 20%, >20%, first load, changed scope, concurrent changes and failures.
   No broad snapshot-reader policy on production tables is intended. This gate
   is not implemented by the SQL drafts; reader activation remains blocked.
   Do not run the current loader against production as postgres. Publisher
   check_schema currently lacks schema qualification and must be corrected
   before coexistence with raw.churches and churchmap_snapshot.churches; unqualified runtime/publisher queries
   must keep the intended public search path.
6. Before BOTH load and build, execute `capacity_gate.sql` with stop-on-error.
   It blocks at 300,000,000 current bytes, or projected bytes >=400,000,000 using
   an incremental reserve of max(128,000,000, twice current analytics relation
   bytes). These are conservative proposed budgets, not measured guarantees.
   A fresh disk/WAL/free-space observation and bounded input-growth estimate are
   also mandatory; missing evidence blocks execution. Serialize analytics stages;
   recheck between stages. Never run on the assumption that initial size is peak.
   Shared quota exhaustion affects production writes as well as analytics.
7. Test exact allow/deny behavior on isolated Postgres before any production
   application. Use the same PostgreSQL major version with the local Supabase
   stack, or fixtures reproducing anon/authenticated/service_role, PUBLIC/default
   ACLs, existing functions and a non-superuser CREATEROLE administrator. Vanilla
   PG14/superuser-only tests cannot establish Supabase membership behavior.
   Then re-check effective privileges using the actual login roles.
   Verify analytics DDL only in its schemas, denied production writes (including
   column grants), denied access to users/reviews, boolean-only snapshot view with raw google_address/base-table access denied,
   denied anon/authenticated access to private objects, and function bypasses.
   An administrator's SET ROLE alone is not a complete login/default-settings test.
   Then a separately authorized manual import/dbt parity run, measuring peak
   resources. No schedule or publish authorization is implied.

## Production migration dependency (before rollout and every schema change)

If installed, churchmap_snapshot.churches depends on selected columns of
public.churches. Dropping/retyping a referenced column or dropping/recreating the
base table can fail on the view dependency. The Render entrypoint executes
backend.db.migrate before Uvicorn, so a failed migration can prevent API startup.
The optional view is not currently in the numbered migration sequence; ordinary
migration CI without it does not cover that deployment state.

Before a relevant migration, inspect pg_depend and retain the exact view
SQL, owner, grants and current source/snapshot identities privately. Test both
states (optional view present and absent) on the matching-major isolated database.
Pause snapshot readers. In the same authorized migration transaction/window,
drop only the view with RESTRICT, change the base schema, recreate a compatible
sanitized view with its original approved owner and narrowly scoped grants,
then verify view shape, permissions and a nonempty same-scope result. Do not
recreate it as the analytics role or change runtime credentials. No CASCADE.
If these operations cannot be transactional, stop and design an explicit staged
migration/recovery plan before deployment; do not leave a missing view unnoticed.

A transaction failure should roll back both table and view changes. For a
committed migration rollback, restore the compatible base schema and saved view
in the same reviewed window, preserving owner/grants, and rerun reader guards.
A view drop/recreate is not an analytics data reset; retain the last accepted
raw snapshot throughout. Restart readers only after the gate succeeds.

## Rollback

Every SQL draft ends in ROLLBACK. Nothing here is connected to the migration
runner or Actions. Only replace it with COMMIT after review and explicit apply
authorization; containment and empty removal are separate files and separate authorizations.

- Before commit: ROLLBACK undoes provisioning atomically.
- After import: stop analytics jobs, use `contain.sql` to make only the two new roles NOLOGIN and
  drain their existing sessions. Retain the schemas and all evidence. Existing
  application credentials/connections remain unchanged. Restore a previous
  analytics snapshot only under a separate checked recovery operation.
- Before any import: optional RESTRICT cleanup in remove_empty.sql removes only
  the newly provisioned empty schemas and roles. It fails if data/objects or
  new dependencies exist. Never use DROP ... CASCADE or DROP OWNED here.
- Dashboard change: if a confirmed dependent consumer fails, restore the recorded
  Data API configuration after explicit incident approval. Reopening it may
  restore the earlier access configuration; prefer fixing that consumer with restricted access.
  Restore changed ACLs only from the exact pre-change snapshot, not blanket GRANT
  ALL. No ACL rollback SQL is invented from the incomplete nine-row report.

## Validation status

Passed: repository dependency searches, producer/consumer review, documentation
link existence and git diff --check. No dependency added or application changed.
NOT RUN: all SQL drafts, local migrations/tests, production changes, browser
QA, Data API request-log audit, actual-role privilege tests, dbt load test.
The owner explicitly requested preparation without execution; these SQL files
are review drafts, not tested or approved deployment artifacts.

Sources: [Supabase secure data](https://supabase.com/docs/guides/database/secure-data),
[connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres),
[PG16 role creation](https://www.postgresql.org/docs/16/sql-createrole.html),
[role membership](https://www.postgresql.org/docs/16/role-membership.html).

## Review follow-up

Nine review topics addressed in draft source: public operational detail removed;
PG16 SET membership added with ADMIN-only lifecycle authority retained; capacity
abort gate added; boolean-only admin view; accessible-schema function and sequence
guards; split containment/removal; matching-version Supabase fixture requirements;
cloud-profile/timeout activation gates; PR link and pg_catalog-first search path.
Version and Render configured-role identity were subsequently supplied by the owner
(see above). Actual-role tests and live runtime verification remain pending. No
SQL was run by the agent.

Second review: documented optional-view migration dependencies and recovery;
required a future fail-closed snapshot-count gate; extended both new roles'
SELECT guard to all public application relations; replaced ineffective membership
normalization with an all-grantor SET/INHERIT assertion. Removed the unnecessary
security_barrier option on the projection-only view. No SQL executed. The gate
and membership cases need the matching-major fixture tests before activation.

Third review confirmed the second-round items. The optional AGENTS wording nit
is addressed with a general dependency-inspection rule, including an owner-run
read-only fallback when the agent cannot inspect the target database. SQL is
unchanged; no runtime validation or execution is implied by review acceptance.
