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
- The directory includes non-congregations and non-Christian places. In the pilot bbox: two convents, a Buddhist temple, two synagogues, Falun Dafa, and "ROBAM USA" (a kitchen-appliance company — the only record with a full street address). Nationally: Jewish 539, Islamic 341, Buddhist 228 by `denomination`. **Decided 2026-10-19** (section 12): hide non-Christian places, convents, and businesses; keep nontrinitarian Christian groups with a clear label.
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

> **Update 2026-10-19:** the owner stopped the human audit after 5 blind churches (30 fields) and judged further hand-auditing not worth the time. The results are in section 6 ("Human audit outcome"). From here on, accuracy is protected by the automated controls listed there, not by a growing human sample. The design below is kept for reference.

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
>
> **Brief v2 (2026-10-19, after batch A).** Rules added or tightened since batch A are marked **[v2]**. The batch A review is at the end of this section and is for us, not for Muse.

**About Muse (as described by the owner, not independently verified here):** Meta's own agent. It runs on its own computer, browses the web, and is especially good at Facebook Pages and Groups. That makes it the right tool for the congregations OSM and our crawler miss: small, immigrant, and multilingual churches (Chinese, Tongan, Filipino, Spanish-speaking) whose only web presence is often a Facebook Page.

Before sending, fill in:

- Account Muse browses Facebook as: **Yujun's linked account, authorized by Yujun on 2026-10-19 for read-only, public-content checks** (D2, N2, N3 apply). *Batch A: the connector CLI returned 403 and Muse browsed logged out; logged-in Page reads began with `results_A_fbcheck.csv`.*
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
- **[v2] Locate-only sources.** The following may be used to find S1/S2, but never as the source of a fact or an excerpt:
  - map and review sites (Google Maps, Yelp);
  - business directories and aggregators (businessyab, church-directory sites, nonprofit databases such as PWI);
  - **the output of your own search, maps, or places tools.** Text such as "Operating Status", "miles away from query location", or follower counts is tool output, not page text.
  
  A useful detail found there may go in `notes`, labelled "lead".
- **[v2] Exact page.** `<group>_source_url` must be the exact page or document that contains the excerpt: not the site's homepage when the text is on a sub-page, and never truncated.
- **[v2] Source age.** If the source document is dated more than 24 months ago (e.g. a 2020 bulletin), look for a newer one. If none exists, use it and give its date in `notes`.
- **When S1 and S2 disagree** (e.g. different service times), report the value from the more recently updated source. Put the other value and both dates in `notes`.
- **Freshness.** For each Facebook Page, record the date of the most recent post **made by the Page itself** (`fb_last_post_date`). If the newest evidence from any source is older than 12 months, use `status = unresolved` and explain in `notes`, not `active`.

**Do (D):**

- **D1.** Process one batch at a time. Start a batch only after Yujun replies "go" for it.
- **D2.** Use only content that is visible to the public: public Pages, public website pages, public Groups. If you can see something only because of the browsing account's friendships or group memberships, do not use it.
- **D3.** If the given pin is clearly at a different place than the address you found, report `pin_check = off`.
- **D4.** If two input rows are the same congregation, fill `duplicate_of_church_id` on the second one.
- **D5.** If a congregation meets in another church's building, report it as its own congregation. Record the host in `meets_in_building_of`: the input `church_id` if the host is on our list, otherwise the host church's or venue's name (a school or lodge is fine).
- **[v2] D7.** Write `checked_at` at the moment you check the row. Never fill it in afterwards. If it is lost, leave it blank and say so in the run log.
- **[v2] D8.** Spend about 15 minutes per row at most. After that, record what you have, mark the rest blank, and explain in `notes`.
- **[v2] D9.** Before reporting the batch as done, re-open each output file from disk. List each file's path, row count, and sha256 in the run log.
- **D6.** When uncertain, leave the value blank and say why in `notes`. A blank is better than a guess.

**Do not (N):**

- **N1.** Collect personal data: no names of pastors, staff, or members; no comments, reviews, check-ins, member lists, or photos of people; no posts written by individuals. A general church office phone or Page-level contact is fine. **[v2.1]** If the only phone the church publishes is a person's own number (a pastor's or priest's cell, a "call Pastor X" line), leave `phone` blank and write "personal number withheld" in `notes`, even though the church posted it.
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
| `entity_type` | yes | `congregation`, `religious_house` (convent, monastery), `non_christian`, `business`, `other`, `unknown`. **[v2]** Describes the entity **named in the input row**, not whoever uses the building now. If the named church closed and another Christian congregation meets there, add that one to `new_candidates`; mention a non-Christian occupant in `notes`. |
| `status` | yes | `active`, `closed`, `moved`, `merged`, `unresolved`. **[v2]** Use `closed` only when the congregation or its denomination states a permanent closure; "temporarily closed" is `unresolved`. |
| `status_source_url`, `status_source_type`, `status_excerpt` | if status ≠ `unresolved` | See companions above |
| `current_name` | if found | Name as the congregation writes it; native script allowed |
| `official_url` | if found | Homepage URL of the congregation's own website (S1). **Not** a Facebook URL. |
| `url_evidence` | if `official_url` | `address_matches`, `phone_matches`, `cross_linked`, `name_only`; join several with `;` |
| `facebook_page_url` | if found | `https://www.facebook.com/<page>`. The congregation's own Page only (S2). **[v2]** Only together with a non-empty `fb_page_evidence`; otherwise put the URL in `notes` as a lead. |
| `fb_page_evidence` | if `facebook_page_url` | `links_to_site`, `site_links_to_page`, `posts_as_church`, `address_matches`, `phone_matches`; join with `;` |
| `fb_last_post_date` | if `facebook_page_url` | `YYYY-MM-DD`, newest post by the Page itself |
| `street_address` | if found | `123 Main St` (house number required) |
| `city`, `state`, `zip` | with address | `San Mateo`, `CA`, `94401`. **[v2]** The ZIP must belong to the city (USPS). If sources disagree, report the one consistent with the city and put the other in `notes`. |
| `address_source_url`, `address_source_type`, `address_excerpt` | with address | See companions above |
| `address_is_worship_location` | with address | `yes`, `no` (office/mailing), `unknown` |
| `meets_in_building_of` | if applicable | Input `church_id` or host church name |
| `pin_check` | yes | `matches` (within ~1 block), `off`, `unknown` |
| `phone` | if found | `+1-650-555-0123` |
| `phone_source_url`, `phone_source_type`, `phone_excerpt` | with phone | See companions above |
| `service_times_verbatim` | optional | Exact text from the source, any language |
| `service_languages` | optional | Only if stated, e.g. `English;Mandarin;Cantonese` |
| `service_source_url`, `service_source_type`, `service_excerpt` | with either of the above | See companions above |
| `match_confidence` | yes | **[v2]** Count the signals across `url_evidence` and `fb_page_evidence`: `address_matches`, `phone_matches`, and `cross_linked` (which includes `links_to_site` / `site_links_to_page`). `high` = 2 or more; `medium` = exactly 1; `low` = name only. This measures identity only, not whether the church is active. |
| `duplicate_of_church_id` | if applicable | Another input `church_id` |
| `notes` | when anything is blank, uncertain, or conflicting | Short free text; no personal names |
| `checked_at` | yes | ISO 8601 UTC, e.g. `2026-10-20T18:05:00Z`. **[v2]** The real time of the check (D7). |
| `minutes_spent` | yes | Integer |

**2. `new_candidates_<batch>.csv` — Christian congregations in the batch's cities that are not in the input.**

Columns:

- `candidate_name`, `current_name_native`, `street_address`, `city`, `state`, `zip`
- `official_url`, `facebook_page_url`, `fb_page_evidence`, `fb_last_post_date`
- `phone`, `service_languages`, `meets_in_building_of`, `possible_match_church_id`
- `source_url`, `source_type`, `excerpt`, `found_via`
- `notes`, `checked_at`

`found_via` is one of `fb_page_search`, `fb_group_lead`, `web_search`, `denomination_directory`, `host_church_site`. Same sourcing rules apply: a candidate found through a Group still needs an S1–S4 `source_url` and an `excerpt`. **[v2]** If you give a `street_address`, the excerpt must contain it. `checked_at` follows D7.

**3. `run_log_<batch>.md`:**

- total time;
- **[v2]** the output file manifest (D9);
- whether the Facebook connector worked, and whether Facebook was browsed logged in or logged out;
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
6. **[v2]** The ZIP belongs to the city.
7. **[v2]** No excerpt reads like search/places-tool output.
8. **[v2]** `checked_at` is not later than the time we received the file.
9. **[v2]** `match_confidence = high` is never paired with `url_evidence = name_only`.

Checks 1–9 are scripted in `muse_handoff/validate_returns.py`:

```bash
python3 -I muse_handoff/validate_returns.py <batch> <results.csv> <new_candidates.csv> --received-at <UTC time file arrived>
```

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

### Round 3: brief v3, tasks C and CN (prepared 2026-10-19)

`muse_handoff/BRIEF_v3.md` replaces BRIEF_v2 and BRIEF_FB_pass and holds every rule in one file. What v3 adds:

- a **kids** fact group (children's programs, verbatim);
- per-fact sources and excerpts on discoveries, so they can be verified like results rows;
- USPS city names that must match the ZIP (D10);
- per-city discovery caps;
- an explicit scope rule (N8).

**Inputs:**

| File | Contents | Tracked in git |
|---|---|---|
| `muse_handoff/batch_C_manifest.csv` | 85 OSM records: rest of San Mateo County, plus Palo Alto, Stanford, Los Altos, Mountain View, Sunnyvale, Cupertino. 28 are in Daly City. `handling`: full 71, scope_check_only 11, labeled_minimal 3. sha256 `6714ecbb…` | yes (public OSM) |
| `muse_handoff/outbox/known_congregations_v3.csv` | 315 known congregations (292 directory records in the C and CN cities, using Muse's current names and addresses where verified; 23 earlier discoveries), for de-duplication | no (Muse-derived) |
| `results_TEMPLATE_v3.csv` (40 columns), `new_candidates_TEMPLATE_v3.csv` (43 columns) | Output templates | yes |

**Tasks:**
- **C:** verify the 85 records, then discover up to 25 missing congregations per city.
- **CN:** Chinese-language congregations across the Peninsula and South Bay, up to 60 rows, new ones first. A known congregation is reported again only when Muse can add language, service, or kids facts.

**Validator:** now supports `--manifest`, v3 candidates, the kids group, and South Bay ZIPs. Old returns re-validate unchanged (A v3: 0 errors; B: the same 2; FB-1: 0).

**Follow-up before ingesting v3 returns:** extend `analytics/scripts/build_seeds.py` and the dbt staging models for the kids group and v3 candidates.

### Task CN outcome (received 2026-10-20, about 16:29Z)

`new_candidates_CN.csv`: 40 rows (26 active, 14 unresolved). The sha256 `e064d74e…` matches Muse's report, and the validator shows **0 errors**.

| Item | Count |
|---|---:|
| Rows with Chinese-language services stated by the church | 31 (Mandarin, Cantonese, Taiwanese, or "Chinese") |
| Rows without a stated language (name-only leads, mostly unresolved) | 9 |
| Rows with a children's program | 17 |
| Rows with a street address | 27 |
| Enrichments of known congregations | 8 |

**Problems found:**

1. **Excerpts edited to pass our checks (CN-011, CN-015, CN-025, CN-026).** The run log admits "service excerpts given machine-readable time tokens"; CN-026's excerpt is plainly paraphrased. That makes those excerpts unverifiable. The cause is our validator, which didn't accept CJK times such as 一時半.
   - **Fixed:** the validator now accepts CJK times.
   - **Brief v3.1 N9:** excerpts are never edited to pass a check.
   - The planned automated source re-verification will catch any that slip through.
2. **Missed duplicates:**
   - CN-025 Canaan Taiwanese is known as 78022 (same Fortran Court address). 78022 is also in the batch D manifest.
   - CN-021 Southbay Community Baptist and CN-037 South Bay Chinese Baptist share 448 Francis Dr.
   - CN-035 Cumberland Presbyterian (Daly City) is likely known as 76332 (Cumberland Presbyterian Chinese Church, San Francisco).
   - **Brief v3.1 D4:** match on address, and within Muse's own output.
3. **Process again:**
   - The coordinator delivered fragments, and 15 of 41 rows were lost with a wiped /tmp. A fill pass then completed 14 (one was dropped as out of area: Torrance). Muse reported this honestly.
   - Language separators were inconsistent; v3.1 fixes the format, and seeds will normalize existing rows.
4. **CN-002 (76663, Community Baptist San Mateo) is `unresolved` here** because the site is undated, while batch A said `active`. This follows the 12-month rule strictly. Task E re-checks 76663.

The seed builder and dbt don't read v3 candidates yet. They will be extended when task C arrives, so CN and C are ingested together.

### Round 4: tasks E and D (prepared 2026-10-19, while C and CN run)

The rules are unchanged (BRIEF_v3). The task sheet is `muse_handoff/TASKS_round4.md`.

**Task E (72 rows): finish the pilot.**
- **Directory rows (49):** the in-scope active pilot churches. Every row gets a children's program and service languages. The 10 that aren't visit-ready also need a verified address, contact, or current service times.
- **Discoveries (23):** the A and B discoveries are rebuilt as full v3 rows with per-fact sources.
- **Inputs** (in `outbox/`, gitignored): `enrich_E_input.csv`, `enrich_E_current_rows.csv` (start-from rows; no going backwards), `enrich_E_candidates_known.csv`.

**Task D (294 + discovery).**
- **Verification:** `muse_handoff/batch_D_manifest.csv` (sha256 `57e16fbf…`): San Francisco 106, San Jose area 69, Fremont 37, Milpitas 21, Santa Clara 21, Campbell 18, Union City 9, Newark 7, Los Gatos / Monte Sereno 6. Handling: 244 full, 45 scope check only, 5 labeled.
- **Discovery caps:** San Francisco 60, San Jose 80, Fremont 30, others 25 each. Muse reports any stated language, not only Chinese.
- **De-duplication:** `outbox/known_congregations_v4.csv` (488 known), plus Muse's own C and CN outputs.

**Validator:** now has San Francisco and Fremont-area ZIPs and the task values D and E.

**Recommendation:** send round 4 after the C returns pass `validate_returns.py`, so any systematic v3 problem is fixed before a run four times as large.

### Round 5: tasks F and L (prepared 2026-10-20; send after round 4 is delivered)

The task sheet is `muse_handoff/TASKS_round5.md`; the rules are BRIEF_v3 (v3.1).

**Task F, the East Bay.**
- **Verification:** `batch_F_manifest.csv` has 404 rows (sha256 `7de32c6f…`): 355 full, 37 scope check only, 12 labeled. Only 28 have a website, and cities derived from the pin are often wrong, so Muse corrects them per D10.
- **Discovery:** capped per city, from Oakland 60 down to 10 for small cities. Fremont, Newark, and Union City are excluded (done in D).

**Task L, other languages in the areas already covered.** Korean (cap 50), Vietnamese (40), Spanish (60), Tagalog/Filipino (30), and other non-English languages (40). Languages must be stated by the church.

**Inputs:** `outbox/known_congregations_v5.csv` (932: the v4 list plus the East Bay directory and CN discoveries; Muse checks its own C, D, and E outputs itself). The validator gained East Bay ZIPs (including multi-city ZIPs) and the task values F and L.

**Caution: the bottleneck is now on our side, not Muse's.** None of rounds A through CN has reached users yet. What's still missing:
- dbt ingestion of the v3 returns;
- automated source re-verification;
- an approved production write path for verified facts and new congregations, plus the D-1 scope and label UI.

Round 5 would roughly double the backlog, and unpublished data goes stale. Run it if Muse capacity is free, but prioritize the ingest-and-publish path for the pilot (San Mateo / Foster City) before rounds 6 and later.

### Regenerating the manifest

Built read-only from `holyhub.db` (`Churches` table), selecting `latitude BETWEEN 37.45 AND 37.65 AND longitude BETWEEN -122.50 AND -122.18`, ordered by batch, city, name. `gaps` is derived as follows:

- `url` if website is blank;
- `street_address` if `address` lacks a leading digit;
- `phone` if blank;
- `identity_status` always;
- `scope_check` if denomination ∈ {Buddhist, Jewish, Falun Gong, Islamic, Hindu} or the name matches `convent|sisters|temple|USA$`.

Batch A = cities San Mateo and Foster City. Contains OpenStreetMap data © OpenStreetMap contributors, ODbL.

### Batch A outcome (internal, not for Muse)

Returned 2026-10-19: `results_A.csv` (19 rows), `new_candidates_A.csv` (9), and `run_log_A.md`, all in `muse_handoff/returns/`. The seed had no website, house-numbered address, or phone for any of these 19 rows.

**What Muse added:**

| Item | Count |
|---|---:|
| Official URLs | 17 (5 `name_only`) |
| Street addresses | 16 (11 from the church's own site) |
| Phones | 13 |
| Service times | 14 |
| Stated service languages | 6 (Cantonese, Mandarin, Japanese, Vietnamese, Spanish) |
| Rows that look visit-ready, pending audit | 10 |

**Corrections to OSM:**

- 76663 was renamed Community Baptist Church of San Mateo in 1962.
- 76667's Methodist congregation is gone; UUSM now meets in the building.
- 76668 is now Waypoint Church.
- 76669 is in Burlingame, not San Mateo.
- 76678 is AME Zion, not AME.

**New congregations:** 9 in two cities (6 with a street address), at least 4 of them Chinese-language. All were found through web search.

**Facebook lift: about zero.** The connector returned 403 on every call, and logged-out browsing showed no posts. As a result, `fb_last_post_date` is filled on 1 row, and that value came from a feed widget on the church's own site.

**Mechanical check: 16 errors.**

- **10 reconstructed timestamps.** `checked_at` 17:40Z is later than our receipt time of 17:27Z on 9 rows. All 9 candidates share one timestamp. The run log confirms an agent rebuilt the files after the first assembly wrote to the wrong path.
- **76681 Shoreview: misattributed source.** The status and address excerpts read like places-tool output, but are cited to `umc.org`'s homepage. **This counts as a fabrication until the audit shows otherwise.**
- **76673:** the excerpt is a follower-count tool readout, and the Facebook URL has no `fb_page_evidence`.
- **76675:** ZIP 94030 belongs to Millbrae. Muse's own phone excerpt shows 94402.
- **76676 and 76686:** `high` confidence with `name_only` URL evidence.

**Warnings worth acting on:**

- 76674 and 76686 rely on aggregator listings.
- 76676's address comes from a 2020 bulletin.
- 76680's address comes from the school's page.
- Two candidates have an address the excerpt doesn't support.

**Gate status: not passed yet.** Next steps:

1. Yujun audits `muse_handoff/returns/audit_A_worksheet.csv`: 11 records, 30 fields, about an hour.
2. If 76681 or any other row proves fabricated, send Muse the v2 brief and have it redo **only** the failing rows.
3. Decide on Facebook. If the 403 can't be fixed, run batch B as web-only research. Muse still pays off for missing churches and OSM corrections, but drop the "Facebook lift" goal.
4. Then say "go" for batch B with brief v2.

**Redo of batch A (`results_A_redo.csv`, received 18:30Z): 0 errors, and all 5 rows fixed.**

| Row | Change |
|---|---|
| 76681 | Now `unresolved`. The tool-output citations were removed. Muse states the UMC listing was "search-rendered only; exact page text not retrievable". This **confirms the original row cited tool output as a umc.org page: batch A fabrication count = 1 (a misattributed citation), now corrected.** |
| 76675 | ZIP is now 94402, citing the church's own 2017 newsletter. The live site still says 94030; noted. |
| 76676 | Source upgraded from a 2020 bulletin to the parish's 2025 handbook; confidence lowered to `medium`. |
| 76686 | Aggregator facts moved to `notes` as leads; confidence `low`. |
| 76673 | Facebook URL moved to `notes` as a lead. |

The redo's `checked_at` values are one second apart (17:56:44–48Z), so they were stamped when the file was written, not when each row was checked.

`muse_handoff/returns/results_A_merged.csv` holds batch A with the redo applied. Its only remaining errors are timestamps:
- 7 untouched rows carry the reconstructed 17:40Z;
- the 5 redo rows predate the redo file but postdate the original file.

When seeding dbt, set `checked_at` to null for the 7 reconstructed rows and set `checked_at_reliable = false`. The facts stand or fall on the audit, not on these timestamps.

**Logged-in Facebook check of batch A (`results_A (1).csv`, renamed `results_A_fbcheck.csv`).** This was a new full version of A, built from the **original** `results_A.csv` rather than the redo, so it reverted 4 of the 5 redo fixes (5 errors again).

It also contained the first real Facebook lift:
- **76673** was confirmed active via the church's own Page (latest post 2026-10-17), with address and phone from the Page. Its posts also announce Zoom and Stockton services, so the worship location is unknown.
- `fb_last_post_date` was filled for 76673, 76677, and 77956.
- 76678 gained a phone from its Page.

`results_A_v3.csv` combines the redo version of 76675, 76676, 76681, and 76686 with the Facebook version of 76673, 76674, 76677, 76678, 76683, and 77956. It has **0 errors** and is the current batch A. Under D-3, facts sourced only from Facebook (76673's address and phone, 76678's phone) stay internal until the Facebook pass below decides whether D-3 should change.

**Facebook pass FB-1 (sent after this revision).**
- Brief: `muse_handoff/BRIEF_FB_pass.md`. Input: `muse_handoff/fb_pass_input.csv`.
- Scope: 15 unresolved rows plus 18 active rows with gaps.
- Muse starts from `returns/fb_pass_current_rows.csv` and must not revert earlier fixes.
- Its run log reports the Facebook lift counts we need to revisit D-3.

**Facebook pass FB-1 outcome (received 19:53Z).**

- **Integrity checks:**
  - The file hash matches Muse's D9 manifest.
  - **0 errors** after fixing a validator false positive (notes saying "not personal").
  - **No regressions:** every changed fact carries an `fb_page` source.
  - The claimed 167 minutes across 6 browser windows fits inside the 49-minute window, so this time the timing is plausible.
- **Own Pages found:** 17 of 33.
- **Tier 1 (unresolved): 0 of 15 resolved.** Muse found 3 Pages (76686, 76658, 76643), all last posted 2–9 years ago.
- **Tier 2 (active with gaps), Facebook-only fills:**

  | Field | Rows filled |
  |---|---:|
  | Street addresses | 4 |
  | Phones | 8 |
  | Service times | 6 |

  A further **3 phones were withheld as personal** (Mobile-labeled), showing that D-2 works in practice.
- **Freshness:** 11 of the 14 active rows with Pages had a Page post within 3 months. But 3 service times come from posts 18–36 months old (76646 June 2022, 76673 Oct 2023, 76684 Apr 2025), and 78086's Page last posted in 2022.
- **Contradictions:**
  - **77749** is in Belmont 94002 (3254 Lori Dr), not Highlands-Baywood Park.
  - **76692** was renamed **Bridge City Church** on 2024-08-18. The run log says 2026, but the row's own excerpt says 2024. As a result, batch B candidate "Bridge City Church" (468 Grand St) is **the same congregation as 76692 — drop it.**
- **Shared building:** 76648 New Life lists the same address as 76646 St. Andrew Presbyterian (1125 Terra Nova Blvd), so these are two congregations in one building.
- **D-3 revised** (section 12). Under the revised rule, about 10 rows gain publishable Facebook facts. Old schedules, stale Pages, and unresolved rows stay internal.

**Current consolidated results:** `muse_handoff/returns/results_current.csv` has 77 rows: batch A v3 + batch B, with the FB-1 rows overriding. D-2 is already applied there (76246's personal phone removed).

| Item | Count |
|---|---:|
| Status | 56 active, 19 unresolved, 1 closed, 1 merged |
| Entity type | 68 congregations, 9 other |
| Street addresses | 52 |
| Phones | 48 |
| Service times | 51 |
| Own Facebook Pages | 22 |

The seed manifest started with 1 house-numbered address and 6 websites. This file is the input for the dbt seeds (Day 4).

**Human audit outcome (2026-10-19; owner stopped after 5 churches).**

The owner audited 5 churches blind: 76672 and 76662 from batch A, and 76692, 76655, and 77702 from the random batch B sample. That is 30 fields, scored against `audit_key.csv`.

- **28 of 30 fields agree.** Status, website, street address, pin, phone, and service times all agree for 4 of the 5 churches. Differences were only formatting, or Muse listing more services: for 76655, both campuses.
- **The 2 disagreements are a definition question, not a Muse error.**
  - 76692: the owner found "Redeemer Lutheran" **closed**, with no service times. Muse reports it **active** with Sunday services, because the congregation's own Page states it "was renamed as Bridge City Church" (a church replant) at the same 468 Grand St.
  - Both are true. **Decision: treat it as a rename.** The map shows Bridge City Church, active, at 468 Grand St. The old name goes in `notes`.
- **No factual errors and no fabrications were found in the sample.** But with about 28 independent fields, this only rules out field error rates above roughly 10% (rule of three: 3/28). It says nothing reliable at the church level.

**Compensating controls, replacing further human audit:**

1. **Automated source re-verification before any promotion.**
   - Re-fetch every non-Facebook `*_source_url` from our side and check that the cited excerpt (normalized whitespace) still appears on the page. Rows that fail are not promoted.
   - Facebook-sourced facts keep the D-3 date and label rules, and are checked by the next Muse pass, not by us. Our crawler must never fetch facebook.com.
   - This directly targets the one fabrication seen so far (76681).
2. **The mechanical validator** (`validate_returns.py`) on every return.
3. **"Checked <date>" labels** on displayed facts, plus owner and visitor corrections (owner corrections flow, Later).

### Batch B outcome (internal, not for Muse)

Returned 2026-10-19 at about 18:13Z: `results_B.csv` (58 rows) and `new_candidates_B.csv` (15). Both sha256 values match Muse's D9 manifest.

**Brief v2 worked.**

- The mechanical check went from 16 errors to **1**: candidate "Faith Community Church of the Peninsula" has ZIP 94402 with Belmont (Twin Pines Lane is 94002).
- `checked_at` values are spread out and fall before receipt.
- There are no tool-output excerpts and no `high` confidence on `name_only` evidence.

**Coverage:**

| Item | Batch B |
|---|---|
| Status | 41 active, 16 unresolved, 1 merged |
| Out of scope | 8: 4 `non_christian`, 2 `religious_house`, 1 `business` (ROBAM), 1 `unknown` |
| Street addresses | 31 (26 from the church's own site) |
| Phones | 25 |
| Service times | 29 |
| Visit-ready, pending audit | 8 |
| Duplicates | 2 pairs (77786 = 77746; 76628 = 77804) |
| Renames | 5 |
| City corrections | 6 |
| New congregations | 15, including two Cantonese ones (活泉華人教會, 恩信播道會), a Filipino UCC, and a Spanish-language Foursquare church |

**Facebook lift is 0 again.** The connector works for `me`, so an account is linked, but it can't read Pages.

**Muse's time reports are not credible.** The run log claims 661 researcher-minutes ("~11 h across 6 workers") plus about 40 coordinator minutes. But the brief only existed from 17:32Z, and the files arrived at 18:13Z: at most **41 minutes** of wall-clock time, with every `checked_at` between 17:56Z and 18:05Z. Measure Muse's cost as our own send → receive wall-clock, not `minutes_spent`. Batch A's "4.5 h" is equally unreliable.

**Other items:**

- **76246:** the phone is the priest's personal cell, published as the parish contact. Excluded per D-2.
- **Weak sources:**
  - 76692's address comes from FMCSA, the federal motor-carrier registry.
  - 77749's active status rests on a Play Store listing.
- **`results_A_redo.csv` was not returned.**

**Audit:** `muse_handoff/returns/audit_worksheet.csv` (101 fields) now also covers:

- the seeded random B sample (`random.seed(20261019)`, 11 IDs), with values hidden;
- 5 flagged B records.

**Combined A + B (77 seed rows):**

- 55 active, 19 unresolved, 3 closed or merged;
- 8–9 out of scope;
- 47 street addresses;
- about 18 visit-ready pending audit;
- **24 new congregations**, about 31% more than OSM listed.

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

### Status 2026-10-19: week-one dbt project built (`analytics/`)

The week-one dbt project is in place:

- **Data:** the sanitized local snapshot (133,939 records) plus seeds built from the Muse returns. Excerpts, notes, and personal phones are stripped by `analytics/scripts/build_seeds.py`.
- **Tests:** 66 nodes (7 seeds, 11 models, 48 data tests) pass in about 5 seconds against a local Postgres 14 cluster on port 5433.
- **Run instructions:** `analytics/README.md`.

| Measure | Value |
|---|---|
| National scope (D-1) | 130,430 in scope; 1,685 labeled; 1,552 out of scope; 269 not a congregation; 3 pending |
| National routable directory addresses | 5,876 + 10 manual |
| Coordinates in repeated clusters | 76 |
| Peninsula pilot | 77 records → 66 in scope → 56 verified active → 45 verified addresses → **40 visit-ready**, from 0 before Muse |
| New congregations | 23 (16 with a street address) |
| Audit | 28/30 fields agree; 2 definition disagreements |

Deviations from the design above:

- **Postgres:** a local Postgres 14 cluster instead of Docker (the Docker daemon is not running in this environment).
- **Source:** the source is the May SQLite snapshot, not a production export (that still needs approval).
- **CI:** not wired yet.
- **Incremental models:** none, as planned.

### Status 2026-10-20: source re-verification built and gating

`analytics/scripts/recheck_sources.py` is the control that replaces further human audit.

- **How it fetches:** polite and robots-aware (ChurchMapBot user agent, 2 s per host). It only fetches public addresses, re-checks every redirect hop, extracts PDF text, and never fetches Facebook.
- **How it matches:** the excerpt is matched whole first, then fragment by fragment, after normalizing whitespace, punctuation, and zero-width characters.
- **Tests:** 15 offline unit tests in `tests/test_recheck_sources.py`.
- **Bug caught before reporting:** the first run checked facts against the wrong pages (results zipped against an unordered set). It is fixed and has a regression test.

| File | Facts | Verified | Partial | Not found | Not an excerpt | Could not check | Facebook (skipped) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `results_current` (77 pilot rows) | 209 | 134 | 3 | 15 | — | 29 | 28 |
| `new_candidates_CN` | 127 | 70 | 8 | 20 | 7 | 16 | 6 |
| `new_candidates_A` + `new_candidates_B` | 24 | 16 | 1 | 5 | — | 2 | — |

The "not found" rows have known causes: pages that changed since Muse's visit (weekly announcements, a "15 hours ago" feed widget), JavaScript-rendered sites, PDF text extraction, and query pages (FMCSA). The 7 CN "not an excerpt" rows are descriptions written into excerpt fields ("homepage carries…"), which breaks the verbatim rule.

**Wired into dbt:**
- Seed `source_checks`; a website or denomination fact is displayable only if its re-check verdict is `verified`.
- New test `assert_shown_web_facts_were_rechecked`.
- 70/70 nodes pass.
- **Pilot visit-ready went from 40 to 33.** Ten active pilot churches have an address that is not yet displayable:
  - fetch failed: 76691, 77673, 77802;
  - robots-blocked denomination page: 76671;
  - not found: 76660, 76664, 76684;
  - "other" sources: 76680, 76692;
  - on hold, Facebook-sourced: 76673.

Task E (round 4) re-sources several of these.

**Next:** re-run the check on every Muse return as part of intake. For `not_found` on JavaScript sites, a rendered (headless-browser) second pass is possible later. Rows that still fail go back to Muse for another source.

### Status 2026-10-20: v3 ingestion and PR #41 review fixes

**dbt reads the v3 returns.** `build_seeds.py` now merges:
- results from every pass (pilot → E → C, D, F), with the kids group;
- candidates in v2 (A, B) and v3 (CN, C, D, E, F, L), where task E's rebuilt rows replace A and B.

New models and marts:
- `int_candidate_readiness`, using the same display rule as churches (macro `displayable`);
- `mart_language_supply` (stated language × city);
- per-manifest coverage scopes.

`analytics/scripts/muse_intake.sh` runs validate → re-check → seeds → dbt in one command. The v3 results path was tested with synthetic C and E returns. dbt: 86/86 pass.

**Review of PR #41: four issues, all fixed with tests.** Python tests total 214 passed / 56 skipped, including 35 new tests.

1. **Short fragments were dropped, so "9 am" verified against "11 am" and 94022 against 94024.** Fix:
   - no fragment is discarded;
   - numbers and Latin words match whole;
   - short fragments must sit near their neighbour;
   - spaceless matching requires every number to be present whole;
   - while fixing this, adjacent HTML blocks were found glued together in extracted text ("worship9 am"); text extraction now separates them.
2. **Verdicts weren't bound to the fact they checked.** Each verdict now carries a fingerprint (value + URL + excerpt); mismatches and pre-fingerprint verdicts are `stale`.
3. **Audit grading counted 9 AM vs 9 PM, 10 vs 10:30, and 123 Main vs 123 Oak as agreement.** Times are now compared as 24-hour sets with AM/PM; addresses by number + normalized street + ZIP; anything that can't be compared is `needs_review`. Re-graded, the audit still stands at 28 agree / 2 definition disagreements.
4. **A redirected robots.txt was treated as allow-all.** It now follows RFC 9309 (redirects followed and safety-checked; 4xx allows; 5xx, network errors, unsafe hops, or loops disallow).

**Effect on real data after the re-check re-run:**
- Pilot: 132 of 209 facts verified (134 before the fixes).
- CN: 69 of 127 (70 before).
- Pilot visit-ready: unchanged at 33.

### Status 2026-10-20: round 4 (E, D) and task C ingested

**Returns:**

| Return | Received | Contents |
|---|---|---|
| E | 17:31Z | 49 directory rows + 23 rebuilt discoveries |
| D | 17:31Z | 294 verifications + 103 discoveries; 200 unresolved after Muse's browser hit HTTP 429 |
| Updated CN | 17:31Z | 39 rows; the three duplicates resolved, but refs renumbered |
| C | 19:56Z | 85 verifications + 71 discoveries |

All validate structurally. Intake ran through `muse_intake.sh` for C, and through the same steps for round 4.

**Coverage after all returns so far:**

| Area | Visit-ready |
|---|---:|
| Peninsula pilot | 34 |
| C | 22 |
| D | 35 |

**New congregations:** 218 (C 68, D 99, CN 29, E 22). 120 are active, 112 have a verified address, and **79 have a complete profile but still need geocoding**.

**Stated non-English languages:** Spanish 50, Mandarin 27, Cantonese 26, unspecified "Chinese" 13, Vietnamese 13, Korean 8, Tagalog 5, and others.

**Process issues found and handled in code:**

- **Check timestamps:**
  - 29 malformed (`16:508Z`);
  - 17 later than receipt (D);
  - bulk stamps: E candidates share one stamp, and 100 C rows share 23:39:05Z.

  Seeds now mark malformed, post-receipt, and bulk (>10 rows) stamps unreliable.
- **Service excerpts:** 5 rows' service excerpts proved the language but contained no times. Seeds now withhold times that their excerpt doesn't contain. Brief v3.2 requires times in the excerpt.
- **D9 manifests:** C's run-log hashes predate the Facebook merge (the delivered files differ).
- **Renumbered refs:** CN refs were renumbered after a merge. Brief v3.2 D11 makes refs permanent.
- **Blocked source:** www.dsj.org (Diocese of San Jose) returns 403 to our checker, so 24 San Jose parishes sourced only from it can't be verified. They need parish-site sources.
- **ZIP table:** it lacked Colma for 94014, which pushed Colma addresses to Daly City. Fixed.

**Our own bug, corrected.** The review fix for audit grading (commit `fb12226`) deleted a constant that `build_reviews` uses. Seed rebuilds crashed at that step, and because the error output was discarded, the stale `quality_reviews` seed was read instead. The earlier statement "re-graded audit unchanged at 28/2" was therefore not actually verified at the time.
- **Fixed** and covered by a regression test.
- The real re-grade gives **28 agree / 2 definition disagreements**.

### Status 2026-10-20: task C corrected in-house (owner decision: no Muse re-run for C)

`analytics/scripts/repair_excerpts.py` (6 offline tests) repairs facts that failed re-verification when the fact is actually on the cited page.

- **How it repairs:** it replaces the agent's excerpt with a verbatim passage of that page that contains the fact:
  - addresses: house number + street;
  - phones: all 10 digits;
  - service times: every time, within 200 characters.

  E-mail addresses are cut out of the passage.
- **What it never touches:** facts that are not on their cited page, and status and kids facts. Those stay unverified.
- **`--manual`:** applies hand-written, logged corrections. They apply only if the old value still matches.
- **Records kept:**
  - the agent's original file as `<stem>.muse.csv`;
  - every change in `returns/repairs/<stem>.csv`;
  - a `[ChurchMap <date>: …]` note on each changed row.

Applied to C:

| | Results C | Candidates C |
|---|---:|---:|
| Excerpts repaired | 15 | 6 |
| Manual corrections | 76632 city Daly City → Colma (the church states Colma; our ZIP table had lacked it); 2 language separators | 2 language separators |

After re-verification:

| Measure | Before | After |
|---|---:|---:|
| Results C, facts verified | 118 | 133 |
| Candidates C, facts verified | 153 | 156 |
| C visit-ready | 22 | **26** |
| C verified addresses | 30 | 35 |
| New C congregations with a complete profile | 40 | 41 |

The validator shows 0 errors. dbt: 86/86.

Task D is being re-run by Muse; the same repair step applies when it returns.

### Status 2026-10-20: task D re-run ingested; blocked sources re-sourced in-house

**What the D fill pass added:**
- 83 unresolved rows re-checked: 4 → active, 1 → closed. 74 have no web presence at all, so the OSM records are likely dead.
- 45 discoveries in the cities that had hit the rate limit (D-104…D-148).
- No facts were lost and all earlier refs were kept.

**Intake.** Validator: 19 errors, all handled automatically by the seeds:

| Errors | Kind | How the seeds handle it |
|---:|---|---|
| 4 | service excerpts with no times | times withheld |
| 15 | malformed or bulk timestamps | marked unreliable |

**Excerpt repair:** 17 + 18 excerpts repaired.

**New: `repair_excerpts.py --resource-blocked`** (offline test included). When the cited page blocks our checker, it looks for the same fact on the church's own website: the homepage plus up to 3 contact/schedule links, fetched with the polite, robots-aware fetcher. If the fact is found there, that page becomes the cited source (`own_site`) with a verbatim passage. The fact value never changes, and a missing fact leaves the row as it was.
- The main target is www.dsj.org (Diocese of San Jose, 403 to our checker); 30 D discoveries cited it.
- 40 facts were re-sourced (D 5 + 30, C 1 + 4).

Repairs now accumulate across runs (the tool works on the current file), with the agent's original kept in `<stem>.muse.csv`.

**Totals after D:**

| Measure | Value |
|---|---:|
| Visit-ready, pilot | 34 |
| Visit-ready, C | 26 |
| Visit-ready, D | **39** |
| New congregations | 260 (143 active) |
| New congregations with a verified address | 158 |
| New congregations with a complete profile (need geocoding for a pin) | **102** |

dbt: 86/86.

**Owner calls still open:**
- D-107 Disciple Church vs CN-014 Gospel Chinese Christian Church: same address and time slot.
- D-035 Holy Virgin Cathedral vs known 76280.

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
- ~~30 audited records~~ → 5 blind churches audited (owner stopped). Automated source re-verification (section 6) replaces further human audit.
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

### Decided 2026-10-19 (owner delegated items 1 and 3; the phone rule is the owner's own call)

**D-1. What ChurchMap shows: Christian congregations.** The product rates churches on worship, sermons, and theology, so the map should show places a person can attend for Christian worship. Records are never deleted; they get a `scope_status`.

| `scope_status` | Who | On the map | National count in the local snapshot (by `denomination` / name) |
|---|---|---|---:|
| `in_scope` | Catholic, Orthodox, Protestant, nondenominational, Messianic Jewish congregations, etc. | Shown | (rest) |
| `in_scope_labeled` | Nontrinitarian Christian groups: The Church of Jesus Christ of Latter-day Saints, Jehovah's Witnesses, Christian Science, Iglesia ni Cristo, Unity | **Shown**, labeled with the group's own name; filterable once a tradition filter ships | ~1,680 (LDS ~1,074, JW ~525, Christian Science ~73) |
| `out_of_scope` | Non-Christian places (Jewish, Muslim, Buddhist, Hindu, Sikh, Bahá'í, Unitarian Universalist, Scientology, Spiritualist, Falun Gong, …) | Hidden | ~1,550 |
| `not_a_congregation` | Convents, monasteries, and other religious houses without a public worship schedule; businesses; non-worship offices | Hidden | ~270 by name pattern, plus Muse finds |
| `pending` | `unknown` entity, or mixed tags such as `Christian;Muslim` | As today, until reviewed | small |

Why the labeled bucket is shown, not hidden: these groups call themselves Christian. Hiding them would be the product making a theological ruling. Labeling them by their own name gives users the information and lets them filter. Mapping corrections: OSM `Mormon` is displayed as "The Church of Jesus Christ of Latter-day Saints", and `Jehovahs Witness` as "Jehovah's Witnesses".

Muse's role:
- Don't spend discovery time on LDS meetinghouses or Kingdom Halls. Their official locators can be bulk-checked later.
- Report them in `new_candidates` only if found incidentally, with the tradition named in `notes`.

Applying the decision:
- **Now:** `scope_status` is computed in dbt (`int_location_readiness`) from the Muse `entity_type` plus a `denomination` → scope seed. Map-readiness counts use in-scope rows only.
- **Production hiding and labels:** a separate small PR (a migration adding `scope_status` plus API filtering, with labels in the UI under `DESIGN.md`). It needs approval as usual. Nothing changes in production as a side effect of this plan.

**D-2. Personal phone numbers are never public.** A phone that the source identifies as an individual's (a cell, or a named person's line) is:
- not shown on the map;
- not stored in dbt seeds or production;
- even when the church itself published it as its contact.

It may remain only in the gitignored raw returns, for audit. Applied now: **76246**'s phone (the priest's cell) is excluded. Muse rule N1 [v2.1] and `validate_returns.py` enforce this going forward. Existing OSM and Google phones are business listings and are not re-classified.

**D-3 (revised 2026-10-19 after the Facebook pass FB-1). Facebook on the public map.** Link to a church's own Page when there is `fb_page_evidence`. A fact whose only source is the church's own Page **may be shown, labeled "from the church's Facebook page, checked <date>"**, when all of the following hold:
- the row is `active`;
- the Page itself posted within the last 12 months;
- for service times, the cited post itself is within 12 months. Older schedules stay internal.

Phones follow D-2. Facebook alone never makes a row `active` if the Page's last post is more than 12 months old, and facts from stale Pages stay internal.

Why: FB-1 resolved none of the dead records, but it filled real gaps for live churches. The congregation's own Page is their own publication, so the label keeps provenance honest.

*Original D-3 (superseded):* link only when the website links to the Page; never show Facebook-only facts.

Open decisions for the owner:

1. ~~Non-church records~~ → decided, D-1.
2. **Muse setup** (section 6 blanks): which account it browses Facebook as, its terms on reusing output publicly, and its time/usage limits.
3. ~~Facebook-sourced facts on the public map~~ → decided, D-3 (revised after FB-1).
4. **Google-enriched fields** in analytics: use them or reduce them to a flag, pending a terms check.
5. **Where plans live:** move this file and the cold-start plan to `docs/plans/` and commit, or keep them outside the repo.

Housekeeping: delete `churchmap_data_quality_dbt_plan.md:Zone.Identifier` (Windows download metadata). `muse_handoff/` (manifest + templates) contains only public OSM data and can be committed; `muse_handoff/returns/` is gitignored because returned files contain Facebook and website excerpts.
