# Publisher role and shadow dry run — PR B

Owner decisions confirmed on 2026-11-06:

- Any actual `scope_status` or `display_tradition` write is a D-1 hit and makes
  the entire run pending. Phone-related evidence does **not** veto the gate;
  upstream personal-phone withholding stays unchanged. This supersedes the
  original plan's D-2 gate condition, not its display/privacy rules.
- `churches DELETE` is authorized to preserve existing inserted-row revert.
  This is table-level DELETE; it is not restricted by ACL to a particular run.
  Existing revert selects the run's inserted rows and `source='muse'`.

No apply is invoked by shadow or the gate. The existing publisher apply/revert
code and 50-row transactions remain unchanged. The role SQL is review-only,
NOLOGIN and ends in ROLLBACK. No production SQL was executed.

## Owner provisioning after review and merge

In SQL Editor, first inspect RLS read-only:

```sql
SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public'
  AND c.relname IN ('churches','church_fact_sources','publish_log');
```

Owner result 2026-11-06: `relrowsecurity` is true and `relforcerowsecurity` false on
all three, and `pg_policies` returned no rows for them. Never add BYPASSRLS or
disable RLS. prepare.sql instead adds seven policies scoped `TO churchmap_publisher`
only, which leave anon/authenticated/other roles unchanged and narrow the grants:
read all churches, update the granted columns, insert and delete only
`source = 'muse'` rows; full access to church_fact_sources; read and append
publish_log. It stops if a PUBLIC policy already exists on these tables or if the
provisioning account does not own them (CREATE POLICY requires ownership). Before
running it, re-run the RLS query above and
`SELECT tablename, policyname, roles FROM pg_policies WHERE schemaname='public' AND tablename IN ('churches','church_fact_sources','publish_log');`
to confirm nothing changed.

Without a SELECT policy RLS returns zero rows rather than an error, so the publisher
would plan every published congregation as a new insert. `check_visibility` in
`scripts/publish_verified.py` stops any plan when no church is visible or when a
congregation that `publish_log` records as inserted (and not reverted) is hidden.
Save current role/table/schema ACLs and confirm the provisioning account. Review
[prepare.sql](prepare.sql), run its default rollback first, then apply only the
approved version with an explicit COMMIT. It grants no service_role membership,
no DDL, and no unrelated application access. PUBLIC privileges are checked,
not silently revoked from other users. Existing `churchmap_snapshot.churches`
remains intact; no table or dependent view is replaced.

Provision LOGIN as for the [snapshot reader](../supabase_isolation/README.md):
generate a random password and its SCRAM-SHA-256 verifier locally, retain the
password in the password manager, and execute `ALTER ROLE churchmap_publisher LOGIN PASSWORD '<verifier>'`
in SQL Editor. Never paste password/verifier into logs or a public PR. Connect
through the **Session pooler**, using this role's pooler username and password,
and save the connection string as the Actions secret `PUBLISH_DATABASE_URL`.
`BACKEND_URL` is the existing backend secret. No schedule is added or changed.

For example, on a local trusted machine with Python 3, generate a private
SQL file (the password is entered through a hidden prompt, never an argument):

```python
import getpass
import os
import base64
import hashlib
import hmac
import secrets
password = getpass.getpass("Publisher password from password manager: ")
# Use a generated ASCII password so Unicode SASLprep is unnecessary.
assert password.isascii() and len(password) >= 32
salt = secrets.token_bytes(16)
salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
client_key = hmac.digest(salted, b"Client Key", "sha256")
stored_key = hashlib.sha256(client_key).digest()
server_key = hmac.digest(salted, b"Server Key", "sha256")
b64 = lambda value: base64.b64encode(value).decode()
verifier = f"SCRAM-SHA-256$4096:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"
fd = os.open("publisher-login.private.sql", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as out:
    out.write("ALTER ROLE churchmap_publisher LOGIN PASSWORD '" + verifier + "';\n")
```

Keep this file outside the repository and remove it after provisioning. Inspect
real login identity and role flags before using the credential. The
local fixture uses actual connections, not SET ROLE, to test publisher behavior.
Run `python docs/plans/publisher_role/validate_local.py` only on its hardcoded
fresh PG17 fixture at 127.0.0.1:55493, database `churchmap_publisher_test`, with
all migrations already applied. It deliberately rejects role reuse.

## Private evidence and public counts

After dbt and counts, shadow runs `scripts.publish_gate` with only the publisher
URL, ephemeral analytics URL, backend URL and allowlisted process settings.
The production transaction is REPEATABLE READ, READ ONLY. The plan and revert
history come from that same snapshot. Neither writer API is called.
The gate associates staging candidate identity fields and withheld-phone evidence
with the marts without changing dbt model columns, eligibility or business rules.
The as-of date comes from `private/dbt/accepted.json`; current day uses Pacific time.

The archive includes `private/publish/publish_diff_<run>.csv`, `rows.json` and
`run.json`. The latter two bind the exact diff hash; run evidence also records
receipt/results hashes. Fields, old/new values and reasons remain private.
No publication files enter `analytics/exports` or the state snapshot.
Public output allowlists integer row/reason counts and `publish_gate`:
`auto_eligible`, `pending`, or `not_configured`. Unconfigured counts are zero
**observed publication decisions**, not proof of zero changes in production.
Configured query failures fail shadow and retain private diagnostics; unavailable
health instead completes adjudication with every change pending.

Rows are churches, not fields. Any replacement blocks its whole row, including
coordinate changes at or below 50 m; movement above 50 m has an additional reason.
The 200 limit counts the row-eligible subset before run-level vetoes. A revert
marker after the most recent insert/update log id blocks the run; a subsequent
publication resets that condition. Identical addresses are whitespace/case-folded
(address, city, state, ZIP) tuples; differing normalized names block both inserts.

## Investigating the historical 173-row difference

The reported 3,762 cloud versus 3,935 May-local directory mart difference is not
explained by this PR. After merge and provisioning, download the first private
archive using the existing shadow comparison commands. Preserve revision,
receipt date, source cutoff, input/seed hashes and run ID. Compare local and
cloud marts at **church_id grain** using the same accepted inputs/date. Export
both ID sets privately; anti-join in each direction and reconcile additions minus
removals to the net difference (173 is a net count, not necessarily 173 records).

Join those IDs to the production dry-run field diff to identify changed fields,
then inspect the original local snapshot and current production/source evidence.
A dry run alone cannot explain excluded mart rows: unchanged rows, rows missing
from production, and rows excluded by mart predicates do not appear in the diff.
For those, inspect each mart's producer inputs and eligibility. Categorize only
supported causes; keep unexplained residuals explicit. Do not attribute them to
production edits solely because the counts differ. Never publish names, addresses,
URLs, phone numbers, or the detailed comparison in Actions logs or the PR.

## Validation limits

Production role creation, real production dry run, apply and revert: **not run**.
No cutover or deployment claim is made. The gate follows the eight conditions with the owner-approved phone exception.
This local validation does not establish production readiness.

Local verification, 2026-11-06 PT, base `babedda`:

- **Passed:** confirmed isolated loopback PG17.6 at 127.0.0.1:55493;
  backend database `churchmap_publisher_backend_test`; migrations 0001–0006
  including pgvector applied using `python -m backend.db.migrate`.
- **Passed:** full `python -m pytest -q -rs`: 718 passed, 5 skipped,
  10 subtests passed. Three skips require populated SF parity data; two legacy
  modules are superseded. No database integration test skipped. Existing
  Starlette/httpx warning remains.
- **Passed:** 49 focused publisher/gate/shadow tests, including real SQL dry-run
  with unchanged production-fixture rows, exact field/diff comparison, health
  failure, schema/view collision, limits and coordinate boundaries. Configured
  archive/environment tests substitute the publish child; real dry-run SQL is
  tested separately. Existing synthetic dbt pipeline runs a real full refresh.
- **Passed:** role validation in separate `churchmap_publisher_test`, with a
  dependent snapshot view and non-superuser provisioning account: real login,
  dry run, apply, idempotency, update/insert revert, cascading fact-source deletion and forbidden actions.
- **Passed:** D-1 whole-run veto and nonblocking phone-exception regressions;
  inserted-church revert succeeds with the owner-approved DELETE grant.
- **Passed:** local documentation links and `git diff --check`.
- Initial verification failures: older Python environment lacked dbt; reused
  fixture schema and an orphan test role collided with existing suite setup.
  Reused the complete existing environment and separated/cleaned synthetic test
  fixtures, then reran successfully. No production object was touched.
- Historical/private corpus dbt, production role creation, production dry run,
  production apply/revert, Actions activation and browser checks: **not run**.
