# ChurchMap: from verified data to the live map

**Prepared:** 2026-10-20 · **Owner:** Yujun · **Status:** plan only. Workstream A goes to a separate agent; workstream B needs the owner's approval before anything touches production.

## Where we are

Everything below lives in the local analytics sidecar (`analytics/`, PR #41). **None of it is on the live map yet.**

| Area | Records | Verified active | Verified address | Visit-ready |
|---|---:|---:|---:|---:|
| Peninsula pilot (San Mateo → Redwood City) | 77 | 56 | 37 | 34 |
| C: rest of San Mateo County + Palo Alto–Cupertino | 85 | 54 | 35 | 26 |
| D: SF, South Bay core, Fremont area | 294 | 95 | 77 | 39 |

**New congregations** (not in the directory): **261**. Of these, 143 are active, 158 have a verified address, and **102 have a complete profile**. None of them has coordinates, so none can get a pin yet.

**How a fact counts as verified:**

1. Muse cites a page and quotes it.
2. Our re-check (`recheck_sources.py`) finds the quote on that page, bound by fingerprint to the exact value.
3. Scope, personal-phone, and Facebook rules apply (D-1, D-2, D-3 in `churchmap_data_quality_dbt_plan.md` §12).

**Sequence:** A (geocoding) and Muse round 5 can run now, in parallel. B (publishing) waits for A and for the owner's go-ahead on its open decisions.

---

## Workstream A — Geocoding (handoff to a separate agent)

### Goal

Coordinates for every verified address that needs a pin:
- new congregations;
- directory churches whose pin Muse found to be off;
- directory churches whose pin was never checked.

### Input

`analytics/exports/geocode_input.csv`: 208 rows, sha256 `531451dfc475b2778392e157f5b6b50567c62d2a17b6c96629f09c75fcf9eb75`. The file is gitignored because it is built from Muse-derived data. Regenerate it from dbt with the query in the appendix.

| Column | Meaning |
|---|---|
| `geo_id` | `candidate:<candidate_id>` or `church:<church_id>`. Copy unchanged. |
| `name`, `street`, `city`, `state`, `zip` | The verified address (displayable under our rules). 15 rows have no ZIP. |
| `current_lat`, `current_lon` | The existing pin for directory churches; blank for new congregations |
| `reason` | `new_congregation` (158), `pin_off` (25: Muse saw the pin at a different place), `verify_pin` (25: pin never checked) |
| `profile_ready` | Whether the record is otherwise ready to publish. Do these first if time is short. |

### Rules

1. **Geocoder: the US Census Bureau Geocoder** (`geocoding.geo.census.gov`, batch endpoint, `Public_AR_Current` benchmark). It's free, needs no key, and its results can be stored.
   - **No Google Maps/Places.** It brings re-spend, and its terms restrict storing results.
   - **No scraping of any map site.**
   - Respect the service's batch size and rate limits.
2. **Never change the input address.** If the geocoder normalizes it, report the normalized form in `matched_address` and leave `street` as given.
3. **Rooftop or interpolated street-segment matches only.** A ZIP or city centroid is a failure, not a result: it recreates the "repeated centroid" problem dbt already flags.
4. For rows that already have a pin, report the distance from the new point to the old pin.
5. Rows without a ZIP: try them anyway. If the match is ambiguous (`Tie`), report `needs_review` and don't pick one.

### Output

`analytics/exports/geocode_output.csv`, one row per input `geo_id`:

| Column | Format |
|---|---|
| `geo_id` | From input |
| `status` | `ok`, `needs_review`, `failed` |
| `latitude`, `longitude` | Decimal degrees, 6 decimals; blank unless `ok` |
| `match_type` | The Census `Exact` / `Non_Exact` / `Tie` / `No_Match` |
| `matched_address` | The geocoder's normalized address |
| `tiger_line_id`, `side` | From the Census response, for traceability |
| `distance_from_current_pin_m` | For `church:` rows with a current pin |
| `geocoder`, `benchmark`, `geocoded_at` | e.g. `census`, `Public_AR_Current`, ISO 8601 UTC |
| `notes` | Why something is `needs_review` or `failed` |

**`status` rules:**
- `ok` only for an `Exact` match whose matched house number and street name equal the input's.
- A `Non_Exact` match is `ok` only if the house number and street name still agree; otherwise `needs_review`.
- `Tie` and `No_Match` are `needs_review` and `failed`.

Also produce a short `geocode_run_log.md`: counts by status and `match_type`, any rows that moved more than 150 m from their current pin, and the time spent.

### Acceptance (checked on our side)

- Every input `geo_id` appears exactly once.
- Every `ok` row lies inside the US-envelope check in `stg_churches` and within the right county for its city.
- No two `ok` rows share coordinates unless they share the same address (D-107 and CN-014 legitimately share 137 Dempsey Rd).
- `pin_off` rows: report how far each new point is from the old pin. These are the corrections we expect.

### What I do when it comes back

- Add a `geocodes` seed and an `int_geocodes` model.
- New congregations with `ok` coordinates become map-ready.
- `pin_off` and `verify_pin` directory rows get a proposed new pin; how it is applied is decided in B2.
- dbt tests:
  - one geocode per `geo_id`;
  - `ok` coordinates inside the envelope;
  - no `ok` row at a known centroid.

### Status 2026-10-21: workstream A returned and wired into dbt

- **Census scripts committed:** `geocode_census.py` (batch run), `reconcile_geocodes_census.py` (reuse unchanged results for a regenerated input), `review_geocodes_census.py` (the nine reviewed rows). Their evidence stays in the gitignored `analytics/exports/`.
- **Result:** 196 rows geocoded, 185 `ok`, 11 `failed` (see `geocode_run_log.md`).
- **`geocodes` seed** (`build_seeds.py`): each pin carries the address it was geocoded from, taken from the input whose sha256 the run recorded. If no input matches, no pins are used.
- **`int_geocodes`:** `pin_usable` only while the record still has that address (case and spacing ignored). A later address correction needs a new geocode.
- **New congregations:** `map_ready` = `profile_ready` + a usable pin. **87 of 165** profile-ready congregations are map-ready. The other 78 are in rows added to `geocode_input.csv` after this run (107 rows not yet geocoded).
- **Two duplicates found by their pins:** C-030 Ladera Community Church (= 76688) and C-064 Trinity Church of Sunnyvale (= 77437) had the same name, address and website as a directory church. They are now in `CANDIDATE_DUPLICATES`. The dbt test `assert_new_congregations_are_not_in_the_directory` fails on any new congregation with a directory church's name at its address (same street and city, or same Census match). Different names at one address are congregations sharing a building and pass.
- **Directory churches:** `proposed_latitude` / `proposed_longitude` on `dim_church` for 37 churches, 15 of them more than 150 m from today's pin. `visit_ready` is unchanged until B2 decides how a proposed pin replaces the directory one.
- **dbt tests:** new congregations not already in the directory; one geocode per subject; usable pins inside the US envelope; no two usable pins at one point unless Census matched the same address; `map_ready` only with a current pin. A unit test covers the address binding.

~~**Next for A:** geocode the 107 new rows. `reconcile_geocodes_census.py` is pinned to the 196-row snapshot, so this needs an incremental runner that submits only rows without a result for their current address.~~

### Status 2026-10-21 (later): incremental geocoding, run by the hourly pull

- **`geocode_incremental.py`:** a ledger keyed by `geo_id` plus the exact address. Only rows without a result for their current address go to Census. See `analytics/README.md` § Geocoding.
- **Acceptance outside the four Bay Area counties:** the matched ZIP must equal the input ZIP, or, without an input ZIP, the matched city must equal the input city. The Bay Area box became a California box. The county table still decides for the cities it lists.
- **`drive_sync.py pull`** geocodes after every rebuild, so delivered packages get pins within the hour.
- **Result:** 596 rows: 526 `ok`, 52 `failed`, 18 `needs_review`. **191 of 225** profile-ready new congregations are map-ready.
- **Open:**
  - 12 direction-only rows (e.g. input "W Eaton Ave", Census "EATON AVE") wait for the range check in `review_geocodes_census.py`, which isn't automated yet.
  - 4 rows have an input ZIP that differs from Census's.
  - 2 rows are Census ties.

---

## Workstream B — Publishing to production (owner approval needed)

Everything here changes production (Supabase Postgres, the Render API, the Vercel UI). Each step below is a separate PR that you approve, and the data writes are a manual, out-of-band step with a dry run first.

### B0. Decisions needed before any write

| # | Decision | Recommendation |
|---|---|---|
| 1 | **Muse's terms on reusing its output publicly** (open since §12 of the data-quality plan). Publishing makes Muse-sourced facts public. | Confirm before B4. We only publish facts re-verified on the church's own page, so the published value is the church's own statement; the excerpt and Muse's notes are never published. |
| 2 | First release scope | **San Mateo / Foster City only** (the cold-start pilot), then the rest of the Peninsula pilot, then C, then D |
| 3 | Overwriting existing production values (e.g. an OSM phone) when a verified value differs | Overwrite only with a verified value, and log the old value (B2). Never blank a field. |
| 4 | How hidden records leave the map (D-1: non-Christian places, convents, businesses, duplicates) | A `scope_status` column filtered by the API. No deletes. |
| 5 | Facebook-sourced facts (D-3) | Show them with the label "From the church's Facebook page, checked <date>". This was already decided; confirm the UI wording. |

### B1. Schema: migration `0006_verified_facts.sql` (additive only)

On `churches`, add:

| Column | Purpose |
|---|---|
| `scope_status text` | `NULL` = legacy (treated as in scope) |
| `display_tradition text` | Label for in-scope-labeled traditions (D-1) |
| `kids_program text` | Verbatim children's program |
| `facebook_url text` | Only a Page with evidence. **Never written into `website`**, which feeds the crawler. |
| `verified_at timestamptz` | When the record was last verified |
| `verified_by text` | e.g. `muse+recheck` |

New table `church_fact_sources`, one row per published fact:
- `church_id`, `field`, `value`, `source_url`, `source_type`, `checked_at`, `recheck_verdict`, `batch`.

This keeps provenance in production without exposing excerpts.

New table `publish_log`, one row per written field:
- `run_id`, `church_id`, `field`, `old_value`, `new_value`, `published_at`.

This is the rollback record.

**Not changed:** `website_summary`, `extracted_tags`, and everything the crawl and extract pipeline owns.

Render runs the migration on deploy (`scripts/docker-entrypoint.sh`). It is additive, so no `READ_ONLY` window is needed.

### B2. Publish script: `scripts/publish_verified.py` (one-off tool, not a route)

- **Input:** dbt exports. Two new marts: `mart_publish_churches` (existing churches: verified fields to write) and `mart_publish_new` (new congregations with geocodes).
- **Dry run by default.** It prints a per-field diff against production (read-only connection) and writes `analytics/exports/publish_diff_<run>.csv` for the owner to read.
- **`--apply --scope pilot`** writes only the approved scope, in one transaction per 50 churches. It logs every old value to `publish_log`, writes `church_fact_sources`, and sets `verified_at`.
- **Write rules:**
  - **An address is written only if its excerpt states that exact street address:** house number + every street word, normalized (`excerpt_supports_street`). A repaired or re-sourced excerpt proves only that the passage is on the page; it is not a publish decision by itself (review of PR #41: "107 San Mateo Avenue" had counted as evidence for "107 San Pedro Road").
  - Fill blanks freely.
  - Replace a non-blank value only if ours is verified and different (logged).
  - Never write a field whose fact failed re-check, is `stale`, or is on hold.
  - Never touch `website` with a Facebook URL.
  - Coordinates: write a new pin for `pin_off` rows only when the geocode is `ok` and more than 50 m away; otherwise keep the current pin.
- **New congregations:**
  - insert with `source = 'muse'`, `external_id = <candidate_id>`, coordinates from A, and `scope_status` from dbt;
  - insert only `profile_ready` rows with an `ok` geocode;
  - re-running is idempotent on `external_id`.
- **Rollback:** `--revert <run_id>` restores the old values from `publish_log` and deletes rows inserted in that run.
- It is an out-of-band script like `scripts/migrate_data.py`, so it may use psycopg directly. CLAUDE.md's rule is that **routers** never do. The API side of B3 goes through `backend/db/repository.py`.

### B3. API (contract change: additive)

- `GET /churches` and the search endpoints exclude `scope_status IN ('out_of_scope','not_a_congregation','duplicate','pending')`. `NULL` stays visible.
- Responses gain `kids_program`, `facebook_url`, `display_tradition`, `verified_at`, and `fact_sources` (field → `source_url`, `checked_at`; detail endpoint only).
- Existing fields keep their meaning; the frontend tolerates new fields.
- **Tests:**
  - repository tests for the scope filter and the new fields;
  - `test_no_sqlite_in_routes` still passes;
  - parity tests updated for the added columns.

### B4. UI (read `DESIGN.md` first; follow its existing colours, fonts, and component patterns, with nothing new or off-system)

- **Detail panel:**
  - a "Children" row for `kids_program`;
  - "Checked <date>" provenance under service times, address, and phone, linking to the source page;
  - Facebook-sourced facts labelled "From the church's Facebook page";
  - a tradition label for `display_tradition` (e.g. "The Church of Jesus Christ of Latter-day Saints").
- **Card:** language chips already exist (`extracted_tags.service_languages`); add verified `service_languages` the same way.
- **No new filters** in the first release. A language or tradition filter is a separate design decision.

### B5. Rollout

1. PR 1: migration plus the API filter, tested locally against Postgres with all migrations. Merge → Render deploys → check `/api/health` and the counts on `/status`.
2. Geocodes (A) arrive → dbt → publish marts.
3. **Dry-run diff against production for the pilot scope.** The owner reads `publish_diff_<run>.csv`.
4. `--apply --scope pilot` (San Mateo / Foster City). Spot-check 10 churches on churchmap.vercel.app.
5. PR 2: UI (B4). Vercel preview review, then merge.
6. Expand the scope: the rest of the pilot → C → D, one dry run and diff each time.
7. **Re-verification cadence:** re-run `recheck_sources.py` on published facts monthly. A fact that stops verifying is flagged in dbt and, after a second miss, hidden.

### B6. Risks

| Risk | Mitigation |
|---|---|
| A wrong fact reaches users | Only re-verified facts; spot-check after each apply; `--revert` |
| Overwriting a better production value | Fill-blank-first rule; diff review; `publish_log` |
| Personal data | D-2 enforced in seeds; excerpts and notes never published |
| Muse terms forbid reuse | Decision B0-1 before any write |
| Duplicate pins (new row + existing OSM row for the same church) | dbt duplicate checks plus `possible_match_*`; inserts skip anything matched; geocode distance check against existing pins within 50 m |
| Stale data (published, then the church moves or closes) | Monthly re-check; "Checked <date>" shown to users |

---

## Workstream C — Muse

**Round 5:** `muse_handoff/TASKS_round5.md`, ready to send. It covers F (East Bay, 404 records plus discovery) and L (Korean, Vietnamese, Spanish, Tagalog, and other languages in the covered areas). Inputs: `BRIEF_v3.md` (v3.2), `batch_F_manifest.csv`, `outbox/known_congregations_v6.csv`.

**Intake on return:**

```bash
analytics/scripts/muse_intake.sh results_F.csv new_candidates_F.csv --received-at <UTC>
analytics/.venv/bin/python analytics/scripts/repair_excerpts.py <files> --resource-blocked
analytics/.venv/bin/python analytics/scripts/recheck_sources.py <files>
```

Then rebuild seeds and dbt. Owner-level calls go into the data-quality plan.

**Owner calls:** none open. D-035 and 76280 are two cathedrals (6210 Geary Blvd and 864 Fulton St). D-035's newly sourced address is included in the current `geocode_input.csv`.

---

## Appendix: regenerating the geocoding input

After any dbt build, run from the repo root:

```sql
\copy (
  select 'candidate:'||candidate_id as geo_id, candidate_name as name, display_street_address as street,
         city, 'CA' as state, display_zip as zip, null::float8 as current_lat, null::float8 as current_lon,
         'new_congregation' as reason, profile_ready
    from analytics.mart_new_congregations where address_displayable
  union all
  select 'church:'||d.church_id, d.display_name, d.display_street_address, d.city, coalesce(d.state,'CA'),
         d.display_zip, d.latitude, d.longitude,
         case when r.pin_check = 'off' then 'pin_off' else 'verify_pin' end, d.visit_ready
    from analytics.dim_church d join analytics.int_location_readiness r using (church_id)
   where r.address_displayable and coalesce(r.pin_check, 'unknown') in ('off', 'unknown')
  order by 1
) to 'analytics/exports/geocode_input.csv' with csv header
```
