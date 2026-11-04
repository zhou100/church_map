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

The export shows anon/authenticated CRUD on churches, church_fact_sources and
publish_log, all without RLS. UI exposes public/graphql_public and automatically
exposes new tables. No external write probe was attempted. The full set of
11 public tables, 91 exposed functions, views and column-level grants still
needs an access review; the three-table finding is not a complete security audit.

## Proposed sequence (requires approval, no changes made)

1. Record current dashboard settings, full table/column/sequence/function ACLs,
   default ACLs, memberships and runtime identity privately. Refresh observations
   before apply. Existing exports do not contain enough detail for exact ACL rollback.
2. If deployed/external consumer checks confirm Data API unused, disable the
   **Data API** in the dashboard. Do not simulate disabling it with undocumented
   SQL settings. This leaves PostgreSQL connections available. Separately turn
   off automatic exposure of new tables, recording any actual ACL changes.
   Turning off automatic exposure alone does not fix existing table grants.
3. Review `prepare.sql`: creates two dedicated NOLOGIN roles, three private
   schemas, restricted snapshot column access and private defaults. It fails
   on preexisting role/schema collisions and detected inherited write grants or
   callable public SECURITY DEFINER functions. It neither edits production data
   nor revokes existing runtime access. Do not expose its schemas to Data API.
4. Provision passwords privately and enable LOGIN only after grant verification.
   Use Session pooler + TLS; custom-role usernames include the project reference.
   Analytics builds as churchmap_analytics; never as postgres. Start dbt threads=1.
   Do not give either role publisher privileges, pg_read_all_data, membership in
   service_role, or database CREATE. Runtime DATABASE_URL stays unchanged.
5. Configure Actions ANALYTICS_DATABASE_URL and PROD_READONLY_DATABASE_URL.
   Current dbt profiles separately consume ANALYTICS_PG* variables and need an
   explicit adapter/configuration update, TLS and threads=1. load_snapshot.py
   still reads SQLite; a bounded sanitized production reader must be implemented.
   Do not run the current loader against production as postgres. Publisher
   check_schema currently lacks schema qualification and must be corrected
   before coexistence with raw.churches; unqualified runtime/publisher queries
   must keep the intended public search path.
6. Test exact allow/deny behavior on isolated Postgres before any production
   application, then re-check effective privileges using the actual login roles.
   Verify analytics DDL only in its schemas, denied production writes (including
   column grants), denied access to users/reviews, restricted snapshot columns,
   denied anon/authenticated access to private objects, and function bypasses.
   An administrator's SET ROLE alone is not a complete login/default-settings test.
   Then a separately authorized manual import/dbt parity run, measuring peak
   resources. No schedule or publish authorization is implied.

## Rollback

Every SQL draft ends in ROLLBACK. Nothing here is connected to the migration
runner or Actions. Only replace it with COMMIT after review and explicit apply
authorization; never paste both rollback alternatives as one operation.

- Before commit: ROLLBACK undoes provisioning atomically.
- After import: stop analytics jobs, make only the two new roles NOLOGIN and
  drain their existing sessions. Retain the schemas and all evidence. Existing
  application credentials/connections remain unchanged. Restore a previous
  analytics snapshot only under a separate checked recovery operation.
- Before any import: optional RESTRICT cleanup in rollback.sql removes only
  the newly provisioned empty schemas and roles. It fails if data/objects or
  new dependencies exist. Never use DROP ... CASCADE or DROP OWNED here.
- Dashboard change: if a confirmed dependent consumer fails, restore the recorded
  Data API configuration after explicit incident approval. Reopening it may
  restore the known exposure; prefer fixing that consumer with restricted access.
  Restore changed ACLs only from the exact pre-change snapshot, not blanket GRANT
  ALL. No ACL rollback SQL is invented from the incomplete nine-row report.

## Validation status

Passed: repository dependency searches, producer/consumer review, documentation
link existence and git diff --check. No dependency added or application changed.
NOT RUN: either SQL draft, local migrations/tests, production changes, browser
QA, Data API request-log audit, actual-role privilege tests, dbt load test.
The owner explicitly requested preparation without execution; these SQL files
are review drafts, not tested or approved deployment artifacts.

Sources: [Supabase secure data](https://supabase.com/docs/guides/database/secure-data),
[connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).
