# ChurchMap: Map-Ready Data Quality, Source Expansion, and dbt Plan

**Prepared:** October 19, 2026 UTC / October 18 PDT · **Revised:** October 19, 2026 (after repo review)  
**Audience:** Yujun, the local implementation agent, and Muse (section 6 only)  
**Purpose:** Turn ChurchMap into a measurable, trustworthy map product and a credible analytics-engineering case study. This is an execution plan, not a claim that the proposed database, tests, dashboards, or research have been implemented.

### What changed in this revision

- Scope cut to what one person can finish in a week; ledger, campus modeling, incremental dbt and source pilots moved to **Later** (section 11).
- Two explicit tracks; the **product track wins** when time runs short.
- Evidence updated: PR39 deployment is recorded as verified in the maintainer's (uncommitted) `AGENTS.md`.
- New local baseline from `holyhub.db`: **the dominant gap is street addresses, not coordinates** (section 1).
- Baseline SQL corrected: a street name without a house number is not an address; coordinates checked against a US envelope; free `address` vs `google_address` conflict check; repeated-coordinate check.
- Facts about the current code: fetch semantics after PR39, and LLM token usage being discarded today (section 4).
- Export details: pooler port, sanitization list, Google content terms (section 7).
- **New section 6: a self-contained Muse handoff checklist** with exact input files, rules, output schema, and acceptance checks. A 77-record Peninsula seed manifest is already exported to `muse_handoff/peninsula_seed_v1.csv`.
- **Muse is Meta's own browsing agent**, so Facebook Pages are now an allowed source through Muse, ranked second after the congregation's website. Public Groups are leads only. Every fact needs a verbatim excerpt; raw returns stay out of git; Facebook URLs never enter the crawl queue.

---

## 1. Recommendation and current verdict

**The pipeline has useful foundations, but corpus-wide factual quality and map readiness are still unmeasured. Prioritize correct, routable locations and useful local coverage before increasing crawl volume.**

A successful HTTP request, a successful LLM response, a nonempty summary, a valid coordinate, and a correct church location are five different outcomes. Measure each separately. The central question: *Can someone find a real congregation and confidently travel to its current meeting location?*

### Two tracks

| Track | Goal | Week-one deliverables |
|---|---|---|
| **Product (wins conflicts)** | One trustworthy metro: San Mateo / Foster City first, then the Peninsula (same first area as `church_map_cold_start_refactor_plan.md`) | Production baseline counts, 30-record calibration audit, Muse batch A returned and scored, LLM usage capture |
| **Case study** | A small, tested analytics layer that explains the product numbers | dbt project over a sanitized snapshot with audit and Muse results as seeds, one map-readiness view |

Recommended order:

1. Count routable-address and coordinate coverage in production; compare with the local snapshot below.
2. Audit actual location correctness in the pilot metro, and use the same records to score Muse.
3. Fill the pilot metro's gaps (URL, Facebook Page, street address, phone, identity) through the Muse handoff, and discover Facebook-only congregations OSM is missing. Import to quarantine only.
4. Capture LLM token usage so cost reporting has real data from now on.
5. Build the minimal dbt layer and one map-readiness view.

### Evidence status

| Evidence | Dated result | Source / interpretation |
|---|---|---|
| PR39 merge | Merged 2026-10-19 05:30:28 UTC, revision `ad4b81c` | GitHub, verified |
| PR39 deployment | Render and Vercel production deployments succeeded for `ad4b81c`; post-deploy crawl verification passed: fetch run 1284 5/5, extract 1285 5/5, tag 1286 5 rows | Local uncommitted `AGENTS.md` (maintainer record). **Commit it.** |
| Pipeline health | `crawl.pipeline_ok=true` at 05:52:23 UTC; alert #37 auto-closed 05:33:35 UTC | Same source |
| Initial extraction state (Oct 18) | 6,200 attempted; 5,852 ok; 348 terminal errors | Current row statuses, not audited accuracy |
| Recovery (Oct 19 05:21 UTC) | 200 churches / 454 artifacts requeued; run 1283 extracted 10/10 | Maintainer-reported bounded recovery |
| Post-recovery snapshot | 2,518 stale; 1,638 awaiting requeue; 3,682 current prompt/model; 5,211 summaries | Maintainer-reported. Backlog not solved. Backfill enrollment re-checked 05:53 UTC. |
| Address and accurate-coordinate coverage in production | Unknown | Needs the section 2 query against production |

The 18-example evaluation set is a regression aid, not an accuracy estimate for 133,939 records. A model confidence score or model–model agreement is not factual accuracy.

### Local snapshot baseline (`holyhub.db`, last write 2026-05-08)

Read-only queries run during this revision against the local SQLite snapshot. `scripts/migrate_data.py` copies `church_id` explicitly, so IDs match production. Field values may have drifted since May (the snapshot has 8,508 websites; production reported 8,515). **Confirm in production before quoting.**

| Measure | Count | Share |
|---|---:|---:|
| Directory records | 133,939 (osm 133,929; manual 10) | — |
| Coordinates present | 133,929 | ~100% |
| Any `address` text | 13,805 | 10.3% |
| `address` starting with a house number | **592** | 0.4% |
| `google_address` present (from one-time Places enrichment) | 5,381 | 4.0% |
| House-numbered `address` **or** `google_address` | **5,935** | **4.4%** |
| ZIP present | 11,811 | 8.8% |
| Phone present | ~9,267 | 6.9% |
| Website present | 8,508 | 6.4% |
| Repeated coordinate clusters (>3 records at the same 4-decimal point) | 14 clusters / 86 records | — |
| Pilot bbox (lat 37.45–37.65, lon −122.50 to −122.18) | **77 records**: 6 websites, 1 house-numbered street, 7 likely out of scope | — |
| Wider Bay Area bbox (37.2–37.9, −122.55 to −121.75) | 708 records; 189 websites; 201 with street text | — |

What this changes:

- **Map pins are almost all present, but routable addresses are almost all missing.** Most OSM `address` values are a bare street name ("Oak Grove Avenue"). The first plan's `has_address` test would have counted those as complete.
- `city` is filled for every OSM record, probably derived from the coordinates. It is not independent evidence that a pin is right.
- The directory includes non-congregations and non-Christian places. In the pilot bbox: two convents, a Buddhist temple, two synagogues, Falun Dafa, and "ROBAM USA" (a kitchen-appliance company — the only record with a full street address). Nationally: Jewish 539, Islamic 341, Buddhist 228 by `denomination`. **Owner decision needed:** hide, keep, or label these (section 12).
- The pilot area is clearly under-covered by OSM (77 records for San Bruno–Redwood City). Discovering missing congregations matters as much as fixing existing rows.
- `dedup_report.csv` (114 candidate duplicate pairs from May) already exists and can be loaded as a seed.

---

## 2. Define quality around the map

Use two entities: **congregation/organization** and **meeting location/campus**. One congregation may have several campuses; different congregations may share a building. Keep the current `church_id`. Explicit location modeling is **Later**. An IRS mailing address or headquarters is not automatically a worship location.

### Quality scorecard

| Dimension | Metric and denominator | What it answers |
|---|---|---|
| Routable address | Records with house-numbered street (own or Google-enriched) + city + state / all records | Can someone navigate there? |
| Coordinate validity | Records with finite coordinates inside the US envelope / all records | Can the map technically place them? |
| Map candidates | Routable address and valid coordinates / all records | Which records deserve location validation? |
| Location accuracy | Audited correct meeting locations / audited locations with a verdict | Do pins represent the intended church? Disclose unresolved cases too. |
| Scope accuracy | Audited records that are active Christian congregations / audited records | Does the directory contain what the product claims? |
| Visit-ready coverage | Verified active locations with supported address, coordinates, and a contact/source link / scoped locations | Can a visitor act on the result? Service times are measured separately. |
| Fetch yield | Fetches yielding usable archived text / completed fetch attempts | Is crawling producing usable evidence? |
| Extraction precision | Supported extracted values / reviewed emitted values | Does the model invent or misattribute facts? |
| Extraction recall | Correctly extracted values / values present in reviewed source | What useful evidence is missed? |
| Entity matching | Correct accepted links / reviewed accepted links | Are URLs attached to the right congregation? |
| Freshness | Locations beyond field-specific verification age / scoped locations | Which information is becoming unreliable? |
| Incremental value | Newly visit-ready locations / (acquisition cost + human review minutes) | Is expansion efficient? |

Publish counts alongside rates, with exact denominators, snapshot time, and geographic scope. Directory coverage is not population coverage.

### First read-only SQL (production)

Run with a read-only role. Use the session pooler (port 5432) or a direct connection; the transaction pooler on 6543 is fine for single queries but not for `pg_dump`. All columns exist in `migrations/0001_initial.sql`.

```sql
WITH flags AS (
  SELECT church_id, source,
    NULLIF(BTRIM(address), '') IS NOT NULL                       AS has_street_text,
    COALESCE(address ~ '^\s*[0-9]', FALSE)                        AS has_house_number,
    NULLIF(BTRIM(google_address), '') IS NOT NULL                AS has_google_address,
    NULLIF(BTRIM(city), '') IS NOT NULL
      AND NULLIF(BTRIM(state), '') IS NOT NULL                   AS has_city_state,
    -- Coarse US envelope incl. AK, HI, PR, territories; catches swaps and junk, not wrong-but-plausible pins.
    COALESCE(latitude BETWEEN -15 AND 72
      AND (longitude BETWEEN -180 AND -64 OR longitude BETWEEN 144 AND 180)
      AND NOT (latitude = 0 AND longitude = 0), FALSE)           AS coords_ok,
    NULLIF(BTRIM(website), '') IS NOT NULL                       AS has_website,
    NULLIF(BTRIM(phone), '') IS NOT NULL                         AS has_phone
  FROM churches
)
SELECT COALESCE(source, '(all)') AS source,
  COUNT(*)                                                         AS total,
  COUNT(*) FILTER (WHERE has_street_text)                          AS street_text,
  COUNT(*) FILTER (WHERE has_house_number)                         AS house_numbered,
  COUNT(*) FILTER (WHERE has_google_address)                       AS google_address,
  COUNT(*) FILTER (WHERE (has_house_number OR has_google_address)
                     AND has_city_state)                           AS routable_address,
  COUNT(*) FILTER (WHERE coords_ok)                                AS coords_ok,
  COUNT(*) FILTER (WHERE (has_house_number OR has_google_address)
                     AND has_city_state AND coords_ok)             AS map_candidates,
  COUNT(*) FILTER (WHERE has_website)                              AS website,
  COUNT(*) FILTER (WHERE has_phone)                                AS phone
FROM flags
GROUP BY ROLLUP (source)
ORDER BY source NULLS LAST;
```

Two cheap follow-ups, with no external API calls:

```sql
-- Repeated coordinates (city/ZIP centroids, bulk imports)
SELECT ROUND(latitude::numeric, 4) AS lat4, ROUND(longitude::numeric, 4) AS lon4,
       COUNT(*) AS n, ARRAY_AGG(church_id ORDER BY church_id) AS ids
FROM churches WHERE latitude IS NOT NULL
GROUP BY 1, 2 HAVING COUNT(*) > 3 ORDER BY n DESC;

-- First-pass address conflict screen: OSM street vs Google-enriched address
SELECT church_id, name, address, city, google_address
FROM churches
WHERE NULLIF(BTRIM(address), '') IS NOT NULL
  AND NULLIF(BTRIM(google_address), '') IS NOT NULL
  AND STRPOS(LOWER(google_address),
             LOWER(SPLIT_PART(REGEXP_REPLACE(BTRIM(address), '^[0-9]+\s+', ''), ' ', 1))) = 0;
```

The conflict screen is crude (it checks whether the first street word appears in the Google address). Use it to choose review cases, not as a verdict. Do not delete uncertain rows; give them a review status.

---

## 3. Establish an honest quality baseline

### Week one: 30-record calibration, overlapped with Muse

- **19 records = Muse batch A** (every San Mateo + Foster City record in the seed manifest). Audited independently by Yujun **before** reading Muse's output, so they also serve as Muse's answer key.
- **11 records** drawn at random from Muse batch B with a saved seed (e.g. `random.seed(20261019)` over the batch-B `church_id`s sorted ascending).

The 120-record design (80 random from the metro frame + 40 targeted high-risk) remains the target, but it is **Later**. Report random and targeted samples separately and never pool targeted cases into a population rate.

For each record, review: in scope (active Christian congregation?), identity, active status, meeting street address, pin location, official website, phone, and service times when present. For records with extractions, also check 3–5 extracted fields. Verdicts: `correct`, `incorrect`, `unsupported`, `unresolved`, `not_applicable`. Missing evidence is not proof of absence.

**Storage:** `analytics/dbt/seeds/quality_reviews.csv`. One row per record × field, with columns `review_id, church_id, sample_frame, stratum, field, verdict, error_category, evidence_url, retrieved_at, reviewer, minutes`. No personal data. It doubles as a dbt seed and as the truth set for scoring Muse.

**Initial release gate (pilot metro):** every displayed pin has valid coordinates and a traceable address source. Severe wrong-church/wrong-place errors are corrected before promotion. Numerical precision targets are set only after the first audit, with sample sizes and confidence intervals. Hiding or marking unresolved pins needs a status column, an API field, and UI work under `DESIGN.md`. That is a separate approved change and is **not** in week one.

---

## 4. Improve the existing pipeline before expanding it

How the code works today (verified in this revision):

- **Fetch:** a failed fetch inserts its own row with `content_hash = NULL`, so failures are already recorded one row per attempt. Since PR39, an unchanged successful fetch hits `ON CONFLICT (church_id, url, content_hash) DO UPDATE SET fetched_at = EXCLUDED.fetched_at` (`backend/db/repository.py`). So for 200 rows, **`fetched_at` now means "last seen"**: the time content was first seen is overwritten, and `crawl_run_id` keeps the run that first archived the content.
- **Extract:** `call_llm` in `backend/scrapers_v2/extract.py` reads the OpenRouter response body and keeps only the parsed content. **Token usage is discarded**, so no historical cost data exists. Model: `google/gemini-2.5-flash-lite`, prompt `2026-07-24.v3.1`.

### Week one: capture LLM usage (small PR)

Keep the `usage` object from the OpenRouter response (prompt/completion tokens, plus cost if OpenRouter returns it). Add it up per run in the existing `crawl_runs.metadata` JSONB. That needs **no migration**, and it isn't a prompt/model change, so the eval gate does not apply. Add a unit test with a stubbed response. Unknown usage stays null, never zero. Per-call storage (an `llm_attempts` table) is **Later**.

### Later (unchanged intent, deferred)

- Add `content_first_seen_at` to artifacts (migration) before more history is lost; separate attempt rows from content versions.
- Store raw-byte hash, normalized-text hash, and cleaner version.
- Detect challenge pages, parked domains, login walls, and empty JS shells.
- Prioritize service/location/contact pages for the map use case, with bounded same-domain discovery and private-network URL blocking.
- Report eligible queue depth, oldest eligible age, deliberate unqueued backlog, and terminal failures as separate numbers.
- Never let an incomplete new extraction silently overwrite a supported field.
- Expand JS rendering only for a demonstrated failure class.

Re-extraction stays opt-in through `/api/admin/crawl/requeue` (CLAUDE.md). Do not repeat the already-enrolled 200-church batch.

---

## 5. Find more churches and better URLs

There are three expansion goals: missing official URLs for existing records, better data for existing locations, and genuinely new congregations. Track yield and duplicate rate separately for each.

Order:

1. **Existing data reconciliation:** `google_address` vs `address`, `dedup_report.csv`, phone numbers. Confirm the Google terms before reusing enriched fields (section 7).
2. **Muse pilot on the Peninsula seed manifest** (section 6): website and Facebook Page, street address, phone, identity/scope, plus missing congregations found through Facebook Pages and the web.
3. **Official denomination and regional directories:** pilot one with clear permitted use and stable IDs; keep its license and attribution.
4. **Church-owned sites and owner submissions:** verified links and corrections, with review history.
5. **Open geographic sources:** check license, freshness, and duplicate rate before import; keep source IDs and attribution (OSM is ODbL).
6. **Facebook-only congregations, via Muse:** Muse is Meta's own browsing agent (section 6). Reading Pages through it is Meta's first-party product doing what it was built for, not our own crawler scraping Facebook, which stays prohibited ([Meta](https://about.fb.com/news/2021/04/how-we-combat-scraping/)). Two questions stay open: which account Muse browses as, and whether Muse's terms let us reuse its output in a public product (section 12). Our own crawler must never fetch facebook.com.

---

## 6. Muse handoff checklist

> Sections 6.1–6.6 are written to be handed to Muse as-is, together with the input files. Yujun sends them; this plan does not contact Muse.

**About Muse (as described by the owner, not independently verified here):** Meta's own agent. It runs on its own computer, browses the web, and is especially good at Facebook Pages and Groups. That makes it the right tool for the congregations OSM and our crawler miss: small, immigrant, and multilingual churches (Chinese, Tongan, Filipino, Spanish-speaking) whose only web presence is often a Facebook Page.

Before sending, fill in:

- Account Muse browses Facebook as (logged out / a dedicated account / Yujun's personal account): `__________`
- Muse's terms on reusing its output in a public website: `__________`
- Time or usage limits per task: `__________`

If Muse browses as Yujun's personal account, rule 6.3-D2 matters most: it must not use anything visible only because of that account's friends or group memberships.

### 6.1 Task in one paragraph

You are given a list of places in San Mateo County, California, taken from OpenStreetMap, that our church-finder map currently shows as churches. For each row, decide whether it is a **real, currently active Christian congregation** meeting near the given pin. If it is, find its **official website** and/or **its own Facebook Page**, its **full street address with house number**, its **main phone number**, and (if stated by the congregation itself) **service times and service languages**. Every fact you report needs a public source URL **and a short verbatim excerpt** from that source. Separately, use Facebook Pages and the web to list Christian congregations in the same cities that are **missing** from our list, including congregations that rent space in another church's building.

### 6.2 Input Muse receives

| File | Contents |
|---|---|
| `muse_handoff/peninsula_seed_v1.csv` | 77 rows, UTF-8, sha256 `c44d208b875c705b2a656b8ad03958b1dc5745aebed3c44dee2b7ef3e39f7d0c`. Batch A = 19 rows (San Mateo, Foster City). Batch B = 58 rows (San Bruno → Menlo Park). |
| This section (6.1–6.6) | Task, rules, output schema |
| `muse_handoff/results_TEMPLATE.csv`, `muse_handoff/new_candidates_TEMPLATE.csv` | Header-only templates matching 6.4 |

Input columns:

| Column | Meaning |
|---|---|
| `church_id` | Our stable ID. **Copy unchanged** into the output. |
| `name` | Name as it appears in OSM. May be outdated, anglicized, or misspelled. Search the native-language name too if the congregation uses one. |
| `known_city`, `state` | City is probably derived from the pin, not from an address. |
| `latitude`, `longitude` | Current map pin (5 decimals). |
| `known_street`, `known_website`, `known_phone` | What we already have. Often blank; a street is usually just a street name without a house number. |
| `osm_ref` | `osm:<node id>` for reference. |
| `denomination_hint` | OSM tag; often generic ("Christian"). |
| `gaps` | `;`-separated list of what we need: `url`, `street_address`, `phone`, `identity_status`, `scope_check` (likely not a church: temple, convent, business). |
| `batch` | `A_calibration` or `B_main`. |

Muse does **not** receive: ChurchMap database or R2 credentials, API keys, ChurchMap user data, reviews, or any non-public data.

### 6.3 Rules

**Sources (S), in priority order:**

- **S1.** The congregation's own website.
- **S2.** The congregation's **own Facebook Page**: a Page run by the congregation, not an auto-generated place page or a fan page. Treat it as the congregation's own when at least one of these holds:
  - its website links to the Page, or the Page links to the website;
  - the Page posts as the church;
  - its address or phone matches.
  
  Record which of these held in `fb_page_evidence`.
- **S3.** The denomination or diocese directory page.
- **S4.** Another official listing (government, nonprofit registry).
- **Public Facebook Groups are leads only.** Use them to learn that a congregation exists, then confirm it from S1–S4. Never report a fact whose only source is a Group post.
- **Map and review sites** (Google Maps, Yelp, etc.) are for locating S1/S2 only. Do not copy facts from them.
- **When S1 and S2 disagree** (e.g. different service times), report the value from the more recently updated source. Put the other value and both dates in `notes`.
- **Freshness.** For each Facebook Page, record the date of the most recent post **made by the Page itself** (`fb_last_post_date`). If the newest evidence from any source is older than 12 months, use `status = unresolved` and explain in `notes`, not `active`.

**Do (D):**

- **D1.** Process **batch A only** first and return it. Batch B starts after Yujun replies "go".
- **D2.** Use only content that is visible to the public: public Pages, public website pages, public Groups. If you can see something only because of the browsing account's friendships or group memberships, do not use it.
- **D3.** If the given pin is clearly at a different place than the address you found, report `pin_check = off`.
- **D4.** If two input rows are the same congregation, fill `duplicate_of_church_id` on the second one.
- **D5.** If a congregation meets in another church's building, report it as its own congregation. Record the host church in `meets_in_building_of`, using the input `church_id` if the host is on our list, otherwise its name.
- **D6.** When uncertain, leave the value blank and say why in `notes`. A blank is better than a guess.

**Do not (N):**

- **N1.** Collect personal data: no names of pastors, staff, or members; no comments, reviews, check-ins, member lists, or photos of people; no posts written by individuals. A general church office phone or Page-level contact is fine.
- **N2.** Open private or closed Groups, or friends-only content, even if the browsing account can see them.
- **N3.** Take actions as the account: no likes, follows, joining groups, messages, comments, or friend requests. Do not contact any church by any channel.
- **N4.** Bypass login walls, CAPTCHAs, paywalls, robots blocks, or rate limits on any site.
- **N5.** Infer anyone's religion, ethnicity, or language from names, photos, or neighbourhoods. Report service languages only when the congregation states them.
- **N6.** Invent or "normalize" facts beyond formatting. Copy service times verbatim.
- **N7.** Take screenshots. Short text excerpts are enough and contain no faces.

### 6.4 Required output (per batch)

Three files. The two CSVs are UTF-8 with a header row. Fact groups are `status`, `address`, `phone`, and `service`. For each fact group you fill, give three companion columns:

- `<group>_source_url`
- `<group>_source_type`: `own_site`, `fb_page`, `denomination`, or `other`
- `<group>_excerpt`: verbatim text of at most 200 characters from that source that contains the fact

**1. `results_<batch>.csv` — exactly one row per input `church_id` in that batch, no extra IDs.**

| Column | Required | Allowed values / format |
|---|---|---|
| `church_id` | yes | From input, unchanged |
| `entity_type` | yes | `congregation`, `religious_house` (convent, monastery), `non_christian`, `business`, `other`, `unknown` |
| `status` | yes | `active`, `closed`, `moved`, `merged`, `unresolved` |
| `status_source_url`, `status_source_type`, `status_excerpt` | if status ≠ `unresolved` | See companions above |
| `current_name` | if found | Name as the congregation writes it; native script allowed |
| `official_url` | if found | Homepage URL of the congregation's own website (S1). **Not** a Facebook URL. |
| `url_evidence` | if `official_url` | `address_matches`, `phone_matches`, `cross_linked`, `name_only`; join several with `;` |
| `facebook_page_url` | if found | `https://www.facebook.com/<page>`. The congregation's own Page only (S2). |
| `fb_page_evidence` | if `facebook_page_url` | `links_to_site`, `site_links_to_page`, `posts_as_church`, `address_matches`, `phone_matches`; join with `;` |
| `fb_last_post_date` | if `facebook_page_url` | `YYYY-MM-DD`, newest post by the Page itself |
| `street_address` | if found | `123 Main St` (house number required) |
| `city`, `state`, `zip` | with address | `San Mateo`, `CA`, `94401` |
| `address_source_url`, `address_source_type`, `address_excerpt` | with address | See companions above |
| `address_is_worship_location` | with address | `yes`, `no` (office/mailing), `unknown` |
| `meets_in_building_of` | if applicable | Input `church_id` or host church name |
| `pin_check` | yes | `matches` (within ~1 block), `off`, `unknown` |
| `phone` | if found | `+1-650-555-0123` |
| `phone_source_url`, `phone_source_type`, `phone_excerpt` | with phone | See companions above |
| `service_times_verbatim` | optional | Exact text from the source, any language |
| `service_languages` | optional | Only if stated, e.g. `English;Mandarin;Cantonese` |
| `service_source_url`, `service_source_type`, `service_excerpt` | with either of the above | See companions above |
| `match_confidence` | yes | `high` (≥2 independent signals agree), `medium` (1 signal plus name), `low` (name only) |
| `duplicate_of_church_id` | if applicable | Another input `church_id` |
| `notes` | when anything is blank, uncertain, or conflicting | Short free text; no personal names |
| `checked_at` | yes | ISO 8601 UTC, e.g. `2026-10-20T18:05:00Z` |
| `minutes_spent` | yes | Integer |

**2. `new_candidates_<batch>.csv` — Christian congregations in the batch's cities that are not in the input.**

Columns:

- `candidate_name`, `current_name_native`, `street_address`, `city`, `state`, `zip`
- `official_url`, `facebook_page_url`, `fb_page_evidence`, `fb_last_post_date`
- `phone`, `service_languages`, `meets_in_building_of`, `possible_match_church_id`
- `source_url`, `source_type`, `excerpt`, `found_via`
- `notes`, `checked_at`

`found_via` is one of `fb_page_search`, `fb_group_lead`, `web_search`, `denomination_directory`, `host_church_site`. Same sourcing rules apply: a candidate found through a Group still needs an S1–S4 `source_url` and an `excerpt`.

**3. `run_log_<batch>.md`:**

- total time;
- whether Facebook was browsed logged in or logged out;
- search methods used;
- pages or sites that required login or blocked access;
- paid tools or cost incurred (or "none");
- rows you found hard and why;
- any rule you were unsure about.

### 6.5 Acceptance checks on return (run by us before anything is used)

Mechanical, scripted:

1. Every input `church_id` of the batch appears exactly once; no unknown IDs.
2. Enum columns contain only allowed values. URLs parse and use http(s). `official_url` is never a facebook.com URL, and `facebook_page_url` always is.
3. Every non-empty fact group has all three companion columns. The excerpt contains the fact: the house number for an address, the last 4 digits for a phone, and a time token or a stated language for services.
4. `street_address` begins with a house number; `state = CA`; `zip` is 5 digits; `fb_last_post_date` is a valid date not in the future.
5. No email addresses or personal names in `notes` or excerpts (regex screen plus a manual skim).

Scored against Yujun's independent audit of the 19 batch-A rows (section 3). Yujun may check Facebook Pages manually, since a person viewing a Page is not automated collection.

- Entity/scope accuracy, website and Page match precision, address correctness, and the share of rows marked `unresolved`.
- **Fabrication count:** facts whose source or excerpt does not support them. This must be **zero** for batch B to proceed. Otherwise, revise the brief and rerun A.
- **Facebook lift:** rows where the only usable source was `fb_page`, and new candidates found through Facebook. This is the number that justifies using Muse.
- Our review minutes per row, plus Muse's `minutes_spent`, give the cost of each newly visit-ready record.

### 6.6 What happens to the results

- **Raw returns stay local and out of git.** Put them in `muse_handoff/returns/` and add that folder to `.gitignore`, because the excerpts are Facebook and website content.
- **dbt reads a reduced copy.** Seeds `analytics/dbt/seeds/muse_results_<batch>.csv` and `muse_new_candidates_<batch>.csv` drop the excerpt columns and keep URLs, source types, dates, and verdicts. They are joined in dbt against `stg_churches`. No production write happens in week one.
- **Facebook URLs never go into `churches.website`.** That column feeds the crawl queue, and nothing in `backend/scrapers_v2/fetch.py` explicitly skips facebook.com (robots.txt probably blocks it, but don't rely on that). Before any Facebook URL reaches production, a separate approved change must:
  - add a dedicated column via a migration; and
  - add a host denylist (facebook.com, instagram.com) to fetch.
- **Showing facts sourced from Facebook on the public map** (addresses, times, a "Facebook" link on profiles) waits for the owner's terms decision (section 12). Linking to a church's own Page is the lowest-risk first step.
- **Before any later promotion,** re-read the affected rows from production (the manifest comes from the May snapshot). Promote only `match_confidence = high` facts, through a reviewed write path that needs separate approval.
- **New candidates are never auto-inserted as pins.** Each needs review, geocoding from its stated address, and a duplicate check against existing `church_id`s. Use `meets_in_building_of` to avoid merging two congregations that share a building.
- **Accepted website URLs may later enter the crawl queue.** Paid extraction for them is a separate, deliberate `requeue`/backfill decision.

### Regenerating the manifest

Built read-only from `holyhub.db` (`Churches` table), selecting `latitude BETWEEN 37.45 AND 37.65 AND longitude BETWEEN -122.50 AND -122.18`, ordered by batch, city, name. `gaps` is derived as follows:

- `url` if website is blank;
- `street_address` if `address` lacks a leading digit;
- `phone` if blank;
- `identity_status` always;
- `scope_check` if denomination ∈ {Buddhist, Jewish, Falun Gong, Islamic, Hindu} or the name matches `convent|sisters|temple|USA$`.

Batch A = cities San Mateo and Foster City. Contains OpenStreetMap data © OpenStreetMap contributors, ODbL.

---

## 7. Database architecture: extend what already exists

ChurchMap already uses PostgreSQL for application data and R2 for HTML. Do not start a second operational database. Add an **analytics sidecar**: a separate local PostgreSQL loaded from a sanitized snapshot. Avoid heavy analytical scans on the application database.

**dbt transforms loaded data. It does not crawl, fetch R2 objects, or provide a database.**

### Snapshot export

- **Connection:** use a dedicated read-only role. `pg_dump` needs the session pooler (5432) or a direct connection; it does not work reliably through the transaction pooler on 6543.
- **Include:** `churches` (minus the columns below), `raw_crawl_artifacts` (metadata only), `crawl_runs`, `schema_migrations`.
- **Exclude or strip:**
  - `users` entirely, and reviewer name/avatar/`user_id` from `reviews` (or exclude `reviews`).
  - `google_reviews`, `google_editorial`, and `google_photos`: Google content stored under the Places terms.
  - `church_embeddings`.
- **Google-sourced fields:** check the current Google Maps Platform terms on storing Places content (other than `place_id`) before using `google_address`, `google_hours`, or ratings in analytics. If the terms don't allow storing them, use only a boolean "was enriched" flag. The plan does not assume the answer.

### Tables

| Relation | When | Grain / key |
|---|---|---|
| Snapshot tables above | Week one | As in production |
| `quality_reviews` (seed) | Week one | One reviewer verdict per record × field / `review_id` |
| `muse_results_*`, `muse_new_candidates_*` (seeds) | Week one | One row per `church_id` / one per candidate |
| `dedup_candidates` (seed from `dedup_report.csv`) | Week one | One candidate pair |
| `source_registry`, `church_sources` | Later | One source / one church–source link |
| `church_locations` (campuses, shared buildings) | Later — affects reviews, API and frontend keyed on `church_id` | One meeting location |
| `fetch_attempts`, `content_versions` | Later | One HTTP attempt / one deduplicated version |
| `extraction_requests`, `llm_attempts`, `extraction_inputs` | Later | One intended extraction / one provider call / request–artifact link |
| `field_assertions` | Later — this is the Phase C decomposition of the wide `churches` row deferred in `0001` | One extracted field assertion |

Never invent history that was not recorded. Keep model confidence, source reliability, and human verification separate. Costs are estimated or reconciled, with currency and price version; unknown cost is null.

---

## 8. Build the dbt project

Week one uses **views and full-refresh tables only**. At ChurchMap's volume (tens of fetch/extract rows per run), incremental models add test burden without a performance need.

```text
analytics/dbt/
  dbt_project.yml
  models/sources.yml
  models/staging/stg_churches.sql
  models/staging/stg_crawl_artifacts.sql
  models/staging/stg_crawl_runs.sql
  models/intermediate/int_location_readiness.sql
  models/marts/dim_church.sql
  models/marts/mart_coverage_snapshot.sql
  models/marts/mart_quality_audit.sql
  models/marts/mart_muse_scorecard.sql
  seeds/quality_reviews.csv
  seeds/muse_results_A_calibration.csv
  seeds/muse_new_candidates_A_calibration.csv
  seeds/dedup_candidates.csv
  tests/
```

Declare grains in model descriptions. `dim_church` has one row per church. `int_location_readiness` has one row per church in week one (per location later). `mart_coverage_snapshot` has one row per snapshot × geographic scope × source, carrying the snapshot timestamp. Current-state tables cannot recreate history from before observation began.

### Week-one tests

- `unique` / `not_null` on all keys; `relationships` from seeds to `dim_church.church_id`.
- `accepted_values` on audit verdicts and all Muse enum columns.
- Custom failing-row tests:
  - A street name without a house number is never `routable_address`.
  - (0,0), out-of-envelope, and repeated-cluster coordinates get distinct statuses.
  - Every Muse fact has a source URL.
  - Exactly one Muse row exists per manifest ID.
  - An HTTP 200 artifact with no `r2_key` never counts as extractable.
  - Joining artifacts to churches does not inflate church counts.

Pin compatible dbt Core and `dbt-postgres` versions. CI runs against an isolated Postgres built from repository migrations plus fixtures, with no production credentials and no paid calls: deps → seed → `dbt build` → `dbt docs generate`, keeping `manifest.json` and `run_results.json` as artifacts. Adding this as a new workflow is fine. Do not modify `tests.yml` or `evals.yml` as a side effect.

### Later

- Incremental `fct_llm_attempts` once per-call usage exists. Keep the delete+insert design from the first draft: a stable `attempt_id`, a monotonic `loaded_at`, and an overlap window.
- Fixtures for retries, replays, late corrections, and incremental-vs-full-refresh parity.
- Source freshness checks on export arrival.

---

## 9. Views

Week one: **one map-readiness view**, built as dbt docs exposures or a static HTML page generated from `mart_coverage_snapshot`. It shows:

- Funnel counts: street text → house-numbered → routable → coordinates OK → audited correct → visit-ready.
- A breakdown by source and pilot city.
- An explicit bucket for unknown geography.

Do **not** add internal dashboards to the product SPA. CLAUDE.md says to avoid developer-facing complexity in the UI. At most, a later approved change can add map-readiness counts to the existing `/status` page.

Later: a pipeline value-and-cost view (once usage is captured), and an audit/discovery view (precision with counts and uncertainty, Muse yield per review minute). Every chart states date range, timezone, model/prompt version, denominator, and refresh time. No raw provider logs, personal data, or licensed content.

---

## 10. One-week delivery sequence

| Day | Product track | Case-study track |
|---|---|---|
| **1** | Commit `AGENTS.md`. Run section 2 queries on production read-only; compare with the local snapshot. **Yujun sends batch A** (manifest + templates already in `muse_handoff/`) (owner action). | — |
| **2** | Independently audit the 19 batch-A records + 11 seeded batch-B records → `quality_reviews.csv`. Draft the error taxonomy. | — |
| **3** | LLM usage capture PR (`crawl_runs.metadata`, unit test). Score Muse batch A against the audit; go/no-go for batch B. | Sanitized snapshot export into the local sidecar. |
| **4** | Send batch B if approved. | dbt staging, `int_location_readiness`, `mart_coverage_snapshot`, seeds, week-one tests, CI workflow. |
| **5** | Write up pilot-metro findings: routable-address gap, scope errors, Muse yield. | Map-readiness view, `mart_muse_scorecard`, `dbt docs generate`. |

If the week slips, drop the case-study cells first.

### Definition of done

- Production routable-address / coordinate counts are reproducible from the committed SQL, with snapshot time and denominators.
- 30 audited records, with verdicts, evidence URLs, and minutes, stored as a seed.
- Muse batch A returned, mechanically validated, and scored against the audit, including a fabrication count and minutes per row.
- LLM usage is recorded for every new extraction run (or null with a reason).
- A fresh clone reproduces the dbt build, tests, and map-readiness view from fixtures and seeds.
- The write-up separates implemented work, measured outcomes, maintainer-reported recovery, and future work. No claims of national accuracy.

---

## 11. Later (explicitly not week one)

120-record probability audit with double review · held-out eval expansion · `content_first_seen_at` migration and attempt/content split · per-call `llm_attempts` and the incremental fact · campus/location modeling · `field_assertions` · status column and UI for withheld/marked pins · denomination directory pilot · owner corrections flow · `facebook_url` column + crawler host denylist · public display of Facebook-sourced facts · promotion of Muse results to production · pipeline cost and discovery views.

---

## 12. Scope, permissions, and open decisions

This document authorizes no external action by itself. Sending the Muse brief is Yujun's action. Production schema changes, persistent credential setup, paid extraction or enrichment, source imports, production writes, and deployment each need specific owner approval. Implement locally on a branch, with fixtures first.

Open decisions for the owner:

1. **Non-church records** (synagogues, temples, mosques, convents, businesses): hide from the map, keep but label, or keep as is?
2. **Muse setup** (section 6 blanks): which account it browses Facebook as, its terms on reusing output publicly, and its time/usage limits.
3. **Facebook-sourced facts on the public map:** link only to the church's own Page, show facts with a "from Facebook, checked <date>" label, or keep them internal until verified elsewhere.
4. **Google-enriched fields** in analytics: use them or reduce them to a flag, pending a terms check.
5. **Where plans live:** move this file and the cold-start plan to `docs/plans/` and commit, or keep them outside the repo.

Housekeeping: delete `churchmap_data_quality_dbt_plan.md:Zone.Identifier` (Windows download metadata). `muse_handoff/` (manifest + templates) contains only public OSM data and can be committed; `muse_handoff/returns/` is gitignored because returned files contain Facebook and website excerpts.
