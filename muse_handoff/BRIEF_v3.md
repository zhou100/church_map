# ChurchMap × Muse — research brief v3

**This file replaces `BRIEF_v2.md` and `BRIEF_FB_pass.md`.** It holds every rule in one place. Rules that are new in v3 are marked **[v3]**.

ChurchMap helps people find a Christian church that fits them: language, service times, children's programs, and where it actually meets. Your past batches were accurate. This round is bigger and more about **finding congregations our directory is missing**.

## Two tasks this round

You may run them in parallel and deliver each when it is done.

| Task | What | Input | Output |
|---|---|---|---|
| **C** | Verify 85 directory records in the rest of San Mateo County and in Palo Alto, Mountain View, Sunnyvale, and Cupertino. Then **find missing congregations** in those cities. | `batch_C_manifest.csv` (85 rows), `known_congregations_v3.csv` | `results_C.csv`, `new_candidates_C.csv`, `run_log_C.md` |
| **CN** | **Find Chinese-language congregations** (Mandarin, Cantonese, Taiwanese, or Chinese/English bilingual) across the Peninsula and South Bay. | `known_congregations_v3.csv` | `new_candidates_CN.csv`, `run_log_CN.md` |

Templates: `results_TEMPLATE_v3.csv` (40 columns) and `new_candidates_TEMPLATE_v3.csv` (43 columns).

### Task C details

**Verification (85 rows).** Produce one results row per manifest `church_id`, using the same method as batches A and B. The manifest's `handling` column sets the depth:
- `full`: do everything.
- `scope_check_only` (11 rows; likely a temple, synagogue, convent, etc.): set `entity_type` and `status` only, then move on.
- `labeled_minimal` (3 rows; LDS, Jehovah's Witnesses): confirm the place exists. Don't search for service details.

**Discovery.** For each of these cities, list Christian congregations that meet there and are **not** in `known_congregations_v3.csv`:
- Daly City, Colma, Brisbane, South San Francisco
- Half Moon Bay and the coast (El Granada, Montara, Moss Beach, Pescadero)
- Woodside, Portola Valley, Atherton, Menlo Park, East Palo Alto
- Palo Alto, Stanford, Los Altos, Los Altos Hills
- Mountain View, Sunnyvale, Cupertino

Report **at most 25 per city**, prioritizing the ones whose facts you can source best. Use `task = C`.

### Task CN details

**Discovery** of congregations whose own source states services in Mandarin, Cantonese, Taiwanese, or Chinese, including the Chinese-language ministry of a larger church.

Area: Daly City, South San Francisco, San Bruno, Millbrae, Burlingame, San Mateo, Foster City, Belmont, San Carlos, Redwood City, Menlo Park, Palo Alto, Los Altos, Mountain View, Sunnyvale, Cupertino, Santa Clara, San Jose, Milpitas, Saratoga, Campbell, and Los Gatos.

Rules for this task:
- **At most 60 rows.** Put new congregations first.
- If a Chinese-language congregation **is already in the known list**, still report it **if you can add language, service, or children's facts**. Set `possible_match_id` to its `known_id`.
- Use `task = CN`.
- A Chinese name or "Chinese" in the name is a search clue, not proof. Report `service_languages` only as the church states them (N5).

## Sources (S)

- **S1.** The congregation's own website.
- **S2.** The congregation's own Facebook Page (rules F1–F5).
- **S3.** Denomination or diocese directory page, including the directory pages of Chinese church associations and networks.
- **S4.** Another official listing (government, nonprofit registry).

**Using the sources:**
- **Locate-only.** The following may be used to find S1–S4, but never as a fact source or excerpt:
  - map and review sites;
  - business directories and aggregators;
  - **your own search, maps, or places tool output.**

  A useful detail from them may go in `notes`, labelled "lead".
- **Exact page.** `<group>_source_url` is the exact page or document (or Facebook post permalink, or the Page's About URL) that contains the excerpt. Never a bare homepage when the text is on a sub-page, and never truncated.
- **Source age.** Prefer sources dated within 24 months. If you must use an older one, give its date in `notes`. **Service times and children's programs from a source older than 12 months:** report them, and put the source date in `notes`.
- **Conflicts.** When sources disagree, report the more recent value. Put the other value and both dates in `notes`.
- **Freshness.** If the newest evidence from any source is older than 12 months, use `status = unresolved`, not `active`.

## Facebook (F)

- **F1.** You may use the linked Facebook account Yujun authorized, **read-only and public content only**: a Page's intro/About section, the Page's own posts, and public events created by the Page.
  - Never use friends-only content, private or closed groups, personal profiles, comments, reactions, follower or member lists, or Messenger.
  - If you can't tell whether something is public, skip it.
- **F2.** No actions as the account: no likes, follows, joins, messages, comments, RSVPs, invites, or settings changes. Contact no one.
- **F3.** Report a Page in `facebook_page_url` only with non-empty `fb_page_evidence`; otherwise put the URL in `notes` as a lead. `posts_as_church` shows the Page is run by the congregation, but does not count toward `match_confidence`.
- **F4.** `fb_last_post_date` is the newest post **by the Page itself**. If posts announce services in another city or online only, set `address_is_worship_location = unknown` and explain.
- **F5.** Public Facebook **Groups are leads only**. Confirm from S1–S4; never cite a Group post as a source.

## Do (D)

- **D1.** Keep `church_id` exactly as given. Produce one results row per manifest row, with no extras.
- **D2.** Use only public content (F1).
- **D3.** If the pin is clearly at a different place than the address you found, set `pin_check = off`.
- **D4.** Mark duplicates: for directory rows, use `duplicate_of_church_id`; for discoveries, use `possible_match_id` with the `known_id`.
- **D5.** For a congregation meeting in another church's or a venue's building, set `meets_in_building_of` to the host `known_id`/`church_id`, or the host's name.
- **D6.** When uncertain, leave the value blank and say why in `notes`.
- **D7.** Write `checked_at` at the real time of each check. Never fill it in afterwards.
- **D8.** Time box: about 10 minutes per verification row. For discovery, stop at the per-city cap.
- **D9.** Before reporting done, re-open each output file from disk. List each file's path, row count, and sha256 in the run log.
- **[v3] D10.** Use the **USPS city name** that matches the ZIP (e.g. "Los Altos" for a Loyola address in 94024). The ZIP must belong to that city.

## Do not (N)

- **N1.** Collect personal data: no names of pastors, staff, or members; no comments, reviews, or photos of people. A church office phone or general contact is fine.
  - If the only published phone is a person's own number (a cell, "call Pastor X"), leave `phone` blank and write "personal number withheld" in `notes`.
  - **[v3]** A children's program contact person's name or phone is personal too.
- **N2.** Open private or closed groups or friends-only content.
- **N3.** Take actions as the account, or contact any church.
- **N4.** Bypass login walls, CAPTCHAs, paywalls, robots blocks, or rate limits.
- **N5.** Infer anyone's religion, ethnicity, or language from names, photos, or neighbourhoods. Report languages only when the congregation states them.
- **N6.** Invent or normalize facts beyond formatting. Copy service times and children's program text verbatim.
- **N7.** Take screenshots.
- **N8.** Spend time on non-Christian places, convents, or businesses beyond setting `entity_type`. Don't search for LDS meetinghouses or Kingdom Halls; if you meet one incidentally, name its tradition in `notes`.

## Output columns

Every fact group has three companions:
- `<group>_source_url`
- `<group>_source_type`: `own_site`, `fb_page`, `denomination`, or `other`
- `<group>_excerpt`: verbatim text of at most 200 characters containing the fact

The groups are `status`, `address`, `phone`, `service`, and **[v3] `kids`**.

### `results_C.csv` (`results_TEMPLATE_v3.csv`)

The columns are the same as batch B, plus the **kids** group after the service group:

| Column | Format |
|---|---|
| `kids_program_verbatim` | **[v3]** What the church states about children: Sunday school, kids' ministry, nursery or childcare during service, with times or ages if given. Verbatim. Blank if nothing is stated. A youth group for teenagers alone does not count. |
| `kids_source_url`, `kids_source_type`, `kids_excerpt` | Companions |

Definitions unchanged from v2:
- **`entity_type`** describes the entity named in the row.
- **`status`:** `closed` only when the congregation or its denomination states a permanent closure; "temporarily closed" is `unresolved`.
- **`match_confidence`:** count `address_matches`, `phone_matches`, and `cross_linked` (which includes `links_to_site` / `site_links_to_page`) across `url_evidence` and `fb_page_evidence`. 2 or more = `high`, exactly 1 = `medium`, name only = `low`.
- **`street_address`** must start with a house number.

### `new_candidates_C.csv` and `new_candidates_CN.csv` (`new_candidates_TEMPLATE_v3.csv`)

**[v3]** Discoveries now carry the same per-fact sourcing as results rows, so we can verify each fact the same way.

| Column | Format |
|---|---|
| `candidate_ref` | Your unique ID per row: `C-001`… or `CN-001`… |
| `task` | `C` or `CN` |
| `candidate_name` | Name as the congregation writes it in English, or its main name |
| `current_name_native` | Name in its own script, if it uses one |
| `denomination_stated` | Only if the church states it |
| `city`, `state` | USPS city (D10), `CA` |
| `official_url`, `url_evidence` | As in results |
| `facebook_page_url`, `fb_page_evidence`, `fb_last_post_date` | As in results (F3–F4) |
| `status` + companions | `active` (evidence within 12 months) or `unresolved` |
| `street_address`, `zip` + address companions | House number required |
| `address_is_worship_location`, `meets_in_building_of` | As in results |
| `phone` + companions | Office phone only (N1) |
| `service_times_verbatim`, `service_languages` + service companions | Languages only as stated, e.g. `Mandarin;English` |
| `kids_program_verbatim` + kids companions | As in results |
| `possible_match_id`, `match_note` | `known_id` from the known list if it may be the same congregation, and why |
| `found_via` | `fb_page_search`, `fb_group_lead`, `web_search`, `denomination_directory`, `host_church_site` |
| `match_confidence` | Identity confidence, defined as in results |
| `notes`, `checked_at`, `minutes_spent` | As in results |

### Run logs (`run_log_C.md`, `run_log_CN.md`)

Each run log contains:
- The D9 file manifest.
- How Facebook was accessed.
- The discovery sources and directories you used, **per city** (C) or per area (CN).
- Counts:
  - found per city;
  - rows already in the known list;
  - rows with a children's program;
  - rows whose only source is a Facebook Page.
- Sites that blocked access.
- Paid tools (or none).
- Hard rows, and any rule you were unsure about.

## How we check your files

```bash
python3 -I muse_handoff/validate_returns.py C_main muse_handoff/returns/results_C.csv muse_handoff/returns/new_candidates_C.csv --manifest muse_handoff/batch_C_manifest.csv --received-at <UTC>
python3 -I muse_handoff/validate_returns.py ALL - muse_handoff/returns/new_candidates_CN.csv --received-at <UTC>
```

Beyond these mechanical checks, before anything is published we re-open every non-Facebook source URL and confirm the excerpt is on that page.
