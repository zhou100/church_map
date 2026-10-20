# ChurchMap analytics sidecar (dbt)

A small, tested analytics layer that explains the product numbers (plan §7–8 in
`churchmap_data_quality_dbt_plan.md`). It never touches the production database:
it reads a sanitized snapshot plus seeds built from the Muse returns.

```
holyhub.db (local SQLite snapshot) ──load_snapshot.py──▶ raw.churches ─┐
muse_handoff/returns/*.csv (gitignored) ──build_seeds.py──▶ seeds/*.csv ─┼─▶ dbt build ─▶ marts
denomination_scope.csv, fact_holds.csv (hand-maintained)                ─┘
```

## Run it

```bash
# 1. One-time: tools and a local Postgres cluster (no Docker needed)
python3 -m venv analytics/.venv && analytics/.venv/bin/pip install -r analytics/requirements.txt
/usr/lib/postgresql/14/bin/initdb -D analytics/.pgdata -U analytics --auth=trust -E UTF8
/usr/lib/postgresql/14/bin/pg_ctl -D analytics/.pgdata -o "-p 5433 -k $PWD/analytics/.pgdata -c listen_addresses=localhost" -l analytics/.pgdata/server.log start
createdb -h localhost -p 5433 -U analytics churchmap_analytics

# 2. Load the snapshot and rebuild seeds. muse_results / muse_candidates / quality_reviews
#    are gitignored (public repo; Muse terms pending): they need muse_handoff/returns/ locally.
analytics/.venv/bin/python analytics/scripts/load_snapshot.py
python3 analytics/scripts/build_seeds.py

# 3. Re-verify cited excerpts against their pages (network; polite, robots-aware, never Facebook)
analytics/.venv/bin/python analytics/scripts/recheck_sources.py muse_handoff/returns/results_current.csv
python3 analytics/scripts/build_seeds.py   # picks up returns/recheck/results_current.csv as source_checks

# 4. Build models and run all tests
DBT_PROFILES_DIR=analytics/dbt analytics/.venv/bin/dbt build --project-dir analytics/dbt
```

## Models and grains

| Model | Grain | Purpose |
|---|---|---|
| `stg_churches` | church | Cleaned directory record; house-number and US-envelope flags |
| `stg_muse_results` / `stg_muse_candidates` | church / candidate | Muse verdicts (no excerpts, no notes) |
| `int_scope` | church | Decision D-1 (`in_scope`, `in_scope_labeled`, `out_of_scope`, `not_a_congregation`, `pending`, `duplicate`) |
| `int_coordinate_clusters` | church in a dense point | Centroid / bulk-import pins |
| `int_location_readiness` | church | Readiness flags; D-3 display rules; `visit_ready` |
| `dim_church` | church | Display-ready attributes, only rule-passing facts |
| `mart_coverage_snapshot` | geo_scope × source | Map-readiness funnel (national, peninsula pilot) |
| `mart_muse_scorecard` | Muse pass (+ all) | Yield per pass |
| `mart_new_congregations` | candidate | Congregations the directory lacks |
| `mart_quality_audit` | field (+ all) | Owner's blind audit vs Muse |

`visit_ready` = in scope, active per Muse, an address from the church's own site or
its denomination **whose excerpt our re-check found on the cited page**, or (D-3) from
its fresh Facebook Page; valid coordinates; pin not off; and a verified website,
fresh Page or displayable phone.

## Source re-verification

`analytics/scripts/recheck_sources.py` replaces further human audit. For every
non-Facebook fact it fetches the cited URL (ChurchMapBot user agent, robots.txt,
2 s per host, public addresses only, redirects re-checked, PDFs supported) and
looks for the excerpt: whole, then fragment by fragment, with whitespace,
punctuation and zero-width characters normalized.

| Verdict | Meaning |
|---|---|
| `verified` | the excerpt (or every fragment) is on the page |
| `partial` | some fragments found, not all |
| `not_found` | page fetched, excerpt absent (page changed, JS-rendered, or not verbatim) |
| `not_an_excerpt` | the "excerpt" describes the page instead of quoting it |
| `fetch_failed` / `robots_blocked` / `unsupported` / `unsafe_url` | could not check |
| `skipped_facebook` | Page facts follow D-3; we never fetch Facebook |

Only `verified` lets a website or denomination fact through. Everything else needs
another source or another pass.

## Rules enforced by tests

- A street name without a house number is never a routable address.
- Exactly one Muse verdict per manifest church; every Muse fact has a source.
- D-1: hidden records are never visit-ready. D-2: personal phones are never kept.
- D-3: Facebook-only facts appear only for active rows with a Page post in the last 12 months, never when on hold.
- A shown website or denomination fact was re-verified on its cited page.
- No join inflates church counts.

`as_of_date` (dbt var) pins the D-3 freshness date for reproducible builds.
CI is not wired yet: the snapshot is a local file. A fixture-based CI job is Later work.
