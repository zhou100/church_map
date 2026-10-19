# ChurchMap × Muse — research brief v2 (batch B)

Extracted from `churchmap_data_quality_dbt_plan.md` §6.1–6.6. Rules marked **[v2]** are new or tightened since batch A.
This round: **batch B** (`batch = B_main`, 58 rows), after Yujun's "go". If Yujun also sends a list of batch A rows to redo, do those first and return them as `results_A_redo.csv`. Output files: `results_B.csv`, `new_candidates_B.csv`, `run_log_B.md`.

**Batch A feedback, in short:**

- **Timestamps.** Record `checked_at` at the moment of each check (D7). In batch A, 10 timestamps were filled in later.
- **Sources.** Never cite search, maps, or places tool output as a source (row 76681).
- **ZIP codes.** The ZIP must match the city (row 76675).
- **`match_confidence = high`** needs two independent identity signals. `name_only` never counts.

Thank you for the careful `unresolved` calls and the disambiguation work. That is exactly what we want.

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
