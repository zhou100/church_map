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
DBT_PROFILES_DIR=analytics/dbt analytics/.venv/bin/dbt build --project-dir analytics/dbt --full-refresh  # seeds are small; refresh picks up new columns
```

## Ingesting a Muse return

```bash
analytics/scripts/muse_intake.sh results_C.csv new_candidates_C.csv --received-at <UTC time received>
```

The intake script runs four steps:

1. Validate. It stops on errors, which go back to Muse.
2. Re-check the cited sources.
3. Rebuild the seeds.
4. Run `dbt build`.

### Through the shared Drive queue

From round 7 on, work moves through a Google Drive folder that Muse reads and writes. Google Drive for desktop mirrors it at `/mnt/f/My Drive/churchmap-handoff`; override with `CHURCHMAP_DRIVE`. The protocol Muse follows is [`muse_handoff/drive/README_FOR_MUSE.md`](../muse_handoff/drive/README_FOR_MUSE.md).

```bash
python3 muse_handoff/drive_sync.py new-discovery --title "Marin County" --state CA --cities "San Rafael=25,Novato=20"
python3 muse_handoff/drive_sync.py new-recheck --title "Unresolved congregations"   # brief section A again, 100 per package; rows replace the earlier ones by candidate_ref
python3 muse_handoff/drive_sync.py publish WP-0003    # after reading its TASK.md
python3 muse_handoff/drive_sync.py pull               # validate, re-check and ingest finished packages, rebuild
python3 muse_handoff/drive_sync.py status
```

What `pull` does:
- It reads a package only after Muse writes `DONE.md`, and only if every listed file matches its sha256.
- A package that fails validation is not ingested. It goes back to Muse as `feedback/WP-xxxx.md`, with the state set to `needs_fix`.
- Ingested files land in `muse_handoff/returns/` as `<kind>_WP0001.csv`, with their receive times in `received.csv`. `build_seeds.py` picks them up after the lettered rounds.
- Excerpt repair (`repair_excerpts.py`) stays a manual step.
- After the rebuild, every pull geocodes the addresses that have no pin yet (`geocode_incremental.py --fetch`) and rebuilds again if any result changed. Skip it with `--no-geocode`.

`pull` runs every hour from the Windows scheduled task `ChurchMapMusePull`, through [`muse_handoff/drive_pull_hourly.sh`](../muse_handoff/drive_pull_hourly.sh). The script does three things:
- re-mounts F: if WSL lost the mount;
- starts the local Postgres;
- appends its output to `muse_handoff/returns/drive_pull.log`.

Remove the task with `schtasks.exe /Delete /TN ChurchMapMusePull /F`.

## Geocoding

```bash
analytics/.venv/bin/python analytics/scripts/geocode_incremental.py           # how many addresses are pending
analytics/.venv/bin/python analytics/scripts/geocode_incremental.py --fetch   # submit them to the Census geocoder
```

- The input is the plan's appendix query, run against the sidecar and saved as `exports/geocode_input_<sha8>.csv`.
- Results live in `exports/geocode_ledger.csv`, keyed by `geo_id` plus the exact street, city, state and ZIP. A result is reused only for the address it was made from. A corrected address goes back to Census.
- Only pending rows are submitted, in one batch. The raw response and its metadata go to `exports/geocode_history/census_<time>_*`.
- `geocode_reconciliation.json` binds `geocode_output.csv` to its input; `build_seeds.py` uses no pin without that binding.
- **Acceptance (`classify` in `geocode_census.py`):**
  - House number and street must match. A ZIP or city centroid fails.
  - The pin must fall inside California.
  - For San Francisco, Santa Clara, San Mateo and the listed Alameda cities, Census must return the expected county.
  - Elsewhere, the matched ZIP must equal the input ZIP, or, without an input ZIP, the matched city must equal the input city.
- After a rule change, `--reclassify census_<time>_raw.csv` re-applies the rules to a saved batch without resubmitting it.
- **Direction-only matches** (input "W Eaton Ave", Census "EATON AVE") are settled from the county's Census TIGER/Line address ranges and feature names, cached in `exports/geocode_review_evidence/` with their hashes:
  - A match is accepted when the ZIPs agree and Census's segment is the only one in that ZIP that covers the house number for that street name, in any direction.
  - Two stated directions that disagree ("W" against "E") stay `needs_review`.
  - Each decision and its evidence are in `geocode_direction_reviews.json`, once per exact address.
- `reconcile_geocodes_census.py` and `review_geocodes_census.py` describe the first 196-row run and are kept as history. Don't re-run them: they overwrite `geocode_output.csv`.

`build_seeds.py` merges every pass it finds, so files that haven't arrived yet are simply skipped. The merge order:

- **Results:** pilot (A, B, Facebook passes) → E → C, D, F. A later pass wins for the same `church_id`.
- **Candidates:** v2 rows from A and B are unified with v3 rows from CN, C, D, E, F, and L. Task E's full rows replace the A/B rows they rebuild.
- **Re-check verdicts:** each row takes the verdicts from the file it came from. A returned file without a re-check is reported, and its web facts stay hidden.

## Repairing excerpts in-house

When a fact is on its cited page but the agent's excerpt isn't (paraphrased, stitched, truncated), `repair_excerpts.py` swaps in a verbatim passage of that page:

```bash
analytics/.venv/bin/python analytics/scripts/repair_excerpts.py muse_handoff/returns/results_C.csv \
    --manual muse_handoff/returns/repairs/manual_results_C.csv   # optional hand-written corrections
analytics/.venv/bin/python analytics/scripts/recheck_sources.py muse_handoff/returns/results_C.csv
```

- The original file is kept as `<stem>.muse.csv`.
- Every change is logged in `returns/repairs/`.
- Facts that aren't on their page are left alone.
- Service times are repaired only when the recorded schedule itself is on the page. Seeds publish times only if the excerpt states the same times on the same days, for the same kind of gathering and language (`excerpt_supports_service`).
- Repairs accumulate across runs. Re-check between runs.
- `--resource-blocked`: if the cited page blocks our checker (403, robots.txt), look for the same fact on the church's own site (homepage plus up to 3 contact/schedule links) and cite that page instead.

## Models and grains

| Model | Grain | Purpose |
|---|---|---|
| `stg_churches` | church | Cleaned directory record; house-number and US-envelope flags |
| `stg_muse_results` / `stg_muse_candidates` | church / candidate | Muse verdicts across all passes (no excerpts, no notes) |
| `stg_source_checks` | subject x fact group | Re-check verdicts for churches and candidates |
| `int_scope` | church | Decision D-1 (`in_scope`, `in_scope_labeled`, `out_of_scope`, `not_a_congregation`, `pending`, `duplicate`) |
| `int_coordinate_clusters` | church in a dense point | Centroid / bulk-import pins |
| `int_location_readiness` | church | Readiness flags; display rule (macro `displayable`); `visit_ready` |
| `stg_geocodes` | subject | Census pin from `analytics/exports/geocode_output.csv`, with the address it was geocoded from |
| `int_geocodes` | subject | `pin_usable`: an `ok` pin whose geocoded address is still the record's address |
| `int_candidate_readiness` | candidate | Same display rule; `profile_ready`; `map_ready` = profile-ready with a usable pin |
| `dim_church` | church | Display-ready attributes, only rule-passing facts; `proposed_*` Census pin (applied at publishing, plan B2) |
| `mart_coverage_snapshot` | geo_scope × source | Map-readiness funnel: national, plus one scope per Muse manifest |
| `mart_muse_scorecard` | Muse pass (+ all) | Yield per pass |
| `mart_new_congregations` | candidate | Congregations the directory lacks (duplicates and enrichments excluded) |
| `mart_language_supply` | language × city × origin | Where a service in a given language exists, and how much of it can be shown |
| `mart_quality_audit` | field (+ all) | Owner's blind audit vs Muse |

`visit_ready` = in scope, active per Muse, **an address stated to be where they meet**
(`address_is_worship_location = yes`; an office or unknown address stays contact-only), from the church's own site or
its denomination **whose excerpt our re-check found on the cited page**, or (D-3) from
its fresh Facebook Page; valid coordinates; pin not off; and a verified website,
fresh Page or displayable phone.

## Source re-verification

`analytics/scripts/recheck_sources.py` replaces further human audit. For every non-Facebook fact, it fetches the cited URL and checks that the excerpt is on the page.

How it fetches:
- the ChurchMapBot user agent, robots.txt (RFC 9309: redirects followed and safety-checked; 4xx allows; 5xx or unreachable disallows), 2 s per host;
- public addresses only, with every redirect hop re-checked;
- HTML and PDF.

How it matches:
- The excerpt is tried whole, then fragment by fragment. All fragments must be found.
- Punctuation, table borders, line breaks, zero-width characters, and digit/letter spacing are ignored. Numbers and Latin words must match whole: 94022 ≠ 94024, "23 Main" is not in "123 Main".
- Short fragments ("9 am") must sit within 300 characters of the previous fragment.
- Spaceless matching keeps the gap between numbers. Number boundaries are checked at the same occurrence, so "23 Main" never matches inside "123 Main".
- A word cut by the 200-character excerpt cap may match as a prefix; a cut number may not.

Each verdict carries a **fact fingerprint** (`analytics/scripts/fact_fingerprint.py`): value + source URL + excerpt. `build_seeds.py` only accepts a verdict whose fingerprint matches the row it publishes. A later correction is `stale` until it is re-checked.

| Verdict | Meaning |
|---|---|
| `verified` | the excerpt (or every fragment) is on the page |
| `partial` | some fragments found, not all |
| `not_found` | page fetched, excerpt absent (page changed, JS-rendered, or not verbatim) |
| `not_an_excerpt` | the "excerpt" describes the page instead of quoting it |
| `fetch_failed` / `robots_blocked` / `unsupported` / `unsafe_url` | could not check |
| `skipped_facebook` | Page facts follow D-3; we never fetch Facebook |
| `source_gone` | the cited page returns 404/410 |
| `stale` | the fact, its URL or excerpt changed since the check; re-run the check |

A transient `fetch_failed` doesn't undo a recent `verified`. Transient means no response (timeout or connection error), 408, 425, 429, or 5xx. The seed keeps the earlier `verified`, with `carried_over = true` and the original check time (history in `returns/recheck/history/`), only if all of these hold:
- the fact fingerprint is the same;
- that verification is at most 30 days old;
- the latest verdict that judged the fact (`verified`, `not_found`, `partial`, `not_an_excerpt`, `source_gone`) is that verification.

A 404/410 is `source_gone` and never carries; a 403 doesn't carry either.

Only `verified` lets a website or denomination fact through. Everything else needs
another source or another pass.

## Rules enforced by tests

- A street name without a house number is never a routable address.
- Exactly one Muse verdict per manifest church; every Muse fact has a source.
- D-1: hidden records are never visit-ready. D-2: personal phones are never kept.
- D-3: Facebook-only facts appear only for active rows with a Page post in the last 12 months, never when on hold.
- A shown website or denomination fact was re-verified on its cited page (churches and candidates).
- For every returned batch, each manifest church has exactly one verdict.
- Duplicates and enrichments never count as new congregations.
- No join inflates church counts.

`as_of_date` (dbt var) pins the D-3 freshness date for reproducible builds.
CI is not wired yet: the snapshot is a local file. A fixture-based CI job is Later work.
