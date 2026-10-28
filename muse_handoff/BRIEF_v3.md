# ChurchMap × Muse — research brief v3

**This file replaces `BRIEF_v2.md` and `BRIEF_FB_pass.md`.** It holds every rule in one place. Rules that are new in v3 are marked **[v3]**.

> **v3.6 (2026-10-28, after WP-0042). Finish the directory sweep; applies to WP-0042's fix and from WP-0043.** Marked **[v3.6]**:
> - In WP-0042, the churchfinder pages of 18 cities listed about 250 congregations. 2 were already known, and 23 were reported: about one per city. The other listings were never researched. **A6 is about the quality of each row. It is never a reason to leave directory listings unresearched.** Below a city's cap, research every new listing (D12) and report it, as `unresolved` if nothing dated turns up.
> - Read **every page** of a directory's results. A count of exactly 20 is usually only the first page.
> - Each sweep line now ends with `unresearched U` for each directory (D12). Our intake rejects a package with `U` above 0 unless that line also says `cap reached`, or `DONE.md` says `partial: yes` because you were rate-limited or out of time (README step 4); then we queue the rest.
>
> **v3.5 (2026-10-25, after WP-0033). Cite what our checker can read; applies from WP-0034.** Marked **[v3.5]**:
> - In WP-0031–0033, 111 of 213 `active` rows still failed our re-check. The quote must be **text a reader sees on the page**: not a metadata timestamp (`Published: 2026-09-18T19:18:23+00:00` is JSON-LD, not page text), and not a homepage item that will rotate off by the time we check. Cite the event, post, sermon or bulletin page itself (A3).
> - **Video channels (YouTube, Vimeo) are leads only**: their dates are relative ("5 days ago") and our checker can't read them. Find the same sermon on the church's own site, or use its Facebook post (A3). The validator rejects both from WP-0034.
> - Facebook evidence (F6): the excerpt is the date as Facebook shows it plus **the post's own words**; never a date joined to the Page's Intro. A post whose own text contradicts the year (e.g. "Friday, October 31st" in 2026, when Oct 31 is a Saturday) does not establish the year.
> - A fact stated only in a source older than 12 months (e.g. a 2022 post announcing classes) is not current: leave it blank and say so in `notes`.
>
> **v3.4 (2026-10-22, after WP-0019). Sweep the church directories; applies from WP-0020.** Marked **[v3.4]**:
> - Discovery now starts from the multi-church directories (S5): the churchfinder.com city page and the church.oursweb.net search for every city in the package. Web search alone missed many congregations in big cities.
> - A congregation found there has `found_via = church_directory`, with the listing URL in `notes` as `lead: <url>`. Directories are locate-only: every fact still comes from S1–S3, and section A still applies.
> - `run_log.md` reports the sweep per city (D12). Our intake rejects a discovery package whose run log has no sweep.
>
> **v3.3 (2026-10-21, after WP-0010). Search deeper; applies from WP-0011.** Marked **[v3.3]**:
> - Reading the homepage is not enough. Before a row may be `unresolved`, or a fact left blank, you must search the pages where churches put dates and details: events, news, sermons, bulletins, and the church's Facebook Page (A1–A6).
> - `unresolved` rows must say in `notes` exactly what was checked (A4). Our validator rejects them otherwise.
> - A copyright year is never evidence of activity. `status_excerpt` must contain the date (A3).
> - A row with `facebook_page_url` needs `fb_last_post_date` (F4).
> - Why: in WP-0001 to WP-0010, 433 of 624 congregations came back `unresolved`, almost all because "the fetched homepage has no date". Facebook was never opened. Those rows can't go on the map.
>
> **v3.2 (2026-10-20, after round 4).** Four clarifications, marked **[v3.2]**:
> - `candidate_ref`s are permanent: never renumber; a removed row leaves a gap (D11).
> - The service excerpt must contain the service **times**; join two verbatim pieces with " … " if the languages are stated elsewhere.
> - `checked_at` is exactly `YYYY-MM-DDTHH:MM:SSZ`, taken from a correct UTC clock at the moment of the check (D7).
> - An "excerpt" is text copied from the page, never a description of the page (N9).
>
> **v3.1 (2026-10-20, after task CN).** Three clarifications, marked **[v3.1]**:
> - Excerpts are never edited to pass our checks (N9).
> - De-duplicate by address as well as name (D4).
> - Use one language separator format.

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
- **[v3.4] S5. Church directories** list many congregations at once. They are **locate-only**, like map sites: use them to find congregations, never cite them as `<group>_source_url` or quote them in an excerpt. A detail seen there (an address, a time) goes in `notes` as a lead until the church's own source states it.
  - **churchfinder.com:** one page per city, `https://www.churchfinder.com/churches/ca/<city>` (for example `/churches/ca/sacramento`; multi-word cities use hyphens, `/churches/ca/san-jose`). Open every page of the city's list. Its `/search/` path is closed to robots (N4): use the city pages.
  - **church.oursweb.net (華人教會名錄):** search by city or address, and by the city's Chinese name if it has one (for example 洛杉磯, 舊金山, 聖荷西). Its `/html/` path is closed to robots.
  - **church.org "Find a Church"** (`app.church.org/find-a-church`) works only with JavaScript. Use it if you can render pages; otherwise say so once in `run_log.md`.
  - Other directories you meet (a denomination's finder is S3, not S5) may be used the same way.

**Using the sources:**
- **Locate-only.** The following may be used to find S1–S4, but never as a fact source or excerpt:
  - map and review sites;
  - business directories and aggregators;
  - **your own search, maps, or places tool output.**

  A useful detail from them may go in `notes`, labelled "lead".
- **Exact page.** `<group>_source_url` is the exact page or document (or Facebook post permalink, or the Page's About URL) that contains the excerpt. Never a bare homepage when the text is on a sub-page, and never truncated.
- **Source age.** **[v3.5]** A fact stated only in a source older than 12 months is not current: leave it blank, and give that source and its date in `notes` (N6). This covers every fact — address, phone, service times and children's programs alike.
- **Conflicts.** When sources disagree, report the more recent value. Put the other value and both dates in `notes`.
- **Freshness.** If the newest evidence from any source is older than 12 months, use `status = unresolved`, not `active`. **[v3.3]** "No date on the homepage" is not a reason for `unresolved`: search as A1–A4 require first.

## Activity and missing facts (A) [v3.3]

Every row, discovery or verification, goes through this search. It is required, not optional.

- **A1. Pages to open on the church's own site** (follow the menu, the footer, the sitemap, or the site's search):
  - **events**: events, calendar, "what's happening", upcoming;
  - **news**: news, blog, announcements, newsletter, pastor's letter;
  - **sermons**: sermons, messages, media, podcast, watch, livestream (the newest sermon date);
  - **bulletin**: weekly bulletin or worship folder (PDFs count, including ones on the parish's bulletin host such as ecatholic or discovermass);
  - **visit**: plan your visit, contact, about, ministries, children/kids/family.
- **A2. The church's Facebook Page** (F1), always, whether or not the site links one. If the site links none, search Facebook for the church name and city. Open the Page's own newest posts, its events, and its About section. If you can't open Facebook at all, say so in `run_log.md` once and in each row's A4 note (`facebook=no access`).
- **A3. Dated evidence** means a date tied to the congregation's activity: an event date, a sermon date, a bulletin date, a post date, a "posted on" or "updated" date on a news item. Not a copyright footer year, not a date in a URL alone. It must be within 12 months of `checked_at`. Cite that exact page as `status_source_url` and copy the date into `status_excerpt` verbatim (for example `Sunday, September 14, 2026 · Fall Kickoff Picnic`).
  - **[v3.5]** The excerpt is text a reader sees on the page. Never a metadata timestamp (JSON-LD `datePublished`, `<meta>` tags, sitemap `lastmod`, anything like `2026-09-18T19:18:23`); never a prefix you added such as `Published:`.
  - **[v3.5]** Cite the stable page: the event's own page, the post, the sermon page, the bulletin PDF. A homepage's "upcoming" box changes weekly, so a date on it is often gone when we check.
  - **[v3.5]** Video channels (YouTube, Vimeo) are leads, not citations: find the same sermon on the church's own site, or the Facebook post. The validator rejects a video URL in `status_source_url`.
- **A4. `unresolved` only after A1 and A2 found nothing dated within 12 months.** Then `notes` must contain this line, with the URL you opened or `none` when the site has no such page:
  `activity checked: events=<url|none>; news=<url|none>; sermons=<url|none>; bulletin=<url|none>; facebook=<url|none|no access>; newest date seen=<date|none>`
  The validator rejects an `unresolved` row without it, or with any of the five keys missing.
- **A5. The same pages fill missing facts.** Before leaving the address, service times, or children's program blank, look on the visit/contact page, the bulletin masthead, the Facebook About section and pinned posts, and the kids/family ministry page. An address seen only on a map or directory site is a lead (S rules): use it to find the church's own statement of it.
- **A6. Depth over count.** The per-city caps are maximums, not targets. One row with dated activity, an address, and service times is worth more than three rows with only a name and a homepage. Budget about 8 minutes per discovered congregation. **[v3.6]** Depth applies to each row you research. It does not let you stop below the cap: every new directory listing is researched (D12).

## Facebook (F)

- **F1.** **[v3.3] Use** the linked Facebook account Yujun authorized (required by A2), **read-only and public content only**: a Page's intro/About section, the Page's own posts, and public events created by the Page.
  - Never use friends-only content, private or closed groups, personal profiles, comments, reactions, follower or member lists, or Messenger.
  - If you can't tell whether something is public, skip it.
- **F2.** No actions as the account: no likes, follows, joins, messages, comments, RSVPs, invites, or settings changes. Contact no one.
- **F3.** Report a Page in `facebook_page_url` only with non-empty `fb_page_evidence`; otherwise put the URL in `notes` as a lead. `posts_as_church` shows the Page is run by the congregation, but does not count toward `match_confidence`.
- **F4.** `fb_last_post_date` is the newest post **by the Page itself**. If posts announce services in another city or online only, set `address_is_worship_location = unknown` and explain.
- **F5.** Public Facebook **Groups are leads only**. Confirm from S1–S4; never cite a Group post as a source.
- **[v3.5] F6. Facebook as activity evidence.** `status_source_url` is the Page (or the post); `status_excerpt` is the date as Facebook shows it, then ` — `, then the post's own words, verbatim (replace a person's name with `[removed]`). Never join a date to the Page's Intro or About text. If the post's text contradicts the year Facebook implies (a weekday that doesn't fit, last year's event), the year is not established: use another post or leave the row `unresolved`.

## Do (D)

- **D1.** Keep `church_id` exactly as given. Produce one results row per manifest row, with no extras.
- **D2.** Use only public content (F1).
- **D3.** If the pin is clearly at a different place than the address you found, set `pin_check = off`.
- **D4.** Mark duplicates: for directory rows, use `duplicate_of_church_id`; for discoveries, use `possible_match_id` with the `known_id`.
  - **[v3.1]** Match on the **street address** too, not only the name: the same house number and street in the same city is a likely match.
  - The same applies within your own output. Two of your rows at one address are either the same congregation (keep one) or two congregations sharing a building (D5, explained in `match_note`).
- **D5.** For a congregation meeting in another church's or a venue's building, set `meets_in_building_of` to the host `known_id`/`church_id`, or the host's name.
- **D6.** When uncertain, leave the value blank and say why in `notes`.
- **D7.** Write `checked_at` at the real time of each check. Never fill it in afterwards.
  - **[v3.2]** Format: exactly `2026-10-21T18:05:09Z`, from a UTC clock. In round 4:
    - 29 rows had malformed stamps such as `16:508Z`;
    - 17 rows had times later than the moment the files reached us;
    - all 23 rows of `new_candidates_E` shared one stamp.
- **D8.** Time box: about 10 minutes per verification row. For discovery, stop at the per-city cap. **[v3.3]** About 8 minutes per discovered congregation (A6); the caps are maximums.
- **D9.** Before reporting done, re-open each output file from disk. List each file's path, row count, and sha256 in the run log.
- **[v3.2] D11.** A `candidate_ref` is permanent once delivered. If a row is merged or removed, leave its ref unused and say so in the run log. In round 4, CN-038 to CN-040 were renumbered after a merge, which breaks every reference to them.
- **[v3.4] D12. Directory sweep (discovery packages).** For every city in the package, before web search:
  1. go through the churchfinder.com city list and the church.oursweb.net results for that city, **every page of them [v3.6]**;
  2. compare each listed congregation with `known_congregations.csv` and your own rows (D4); skip the known ones;
  3. research every new one as section A requires, until the city's cap is reached. A listing is not evidence that the church meets today: closed and moved churches stay listed for years.

  Then search the web for what the directories missed. In `run_log.md`, report per city one line per directory: `<city> — churchfinder: listed N, already known K, reported R, unresearched U; oursweb: listed N, already known K, reported R, unresearched U` (and `cap reached` when it stopped you).

  **[v3.6]** `U` counts the new listings you did not research. Some listings are researched and then left out, because they are a duplicate listing, in another city, not a congregation, or closed. Those don't count in `U`; name them in the prose under the sweep. `U` must be 0 unless the line says `cap reached`, and our intake rejects the package otherwise. If you were rate-limited or ran out of time, deliver what is finished with `partial: yes` in `DONE.md` (README step 4) and keep the true `U`: we queue the rest.
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
  - **[v3.5]** A fact stated only in a source older than 12 months is not current: leave it blank and say so in `notes`.
- **N7.** Take screenshots.
- **[v3.2]** Put a description of the page in an excerpt field. Text such as "homepage carries current service schedule…" or "Updated August 23, 2024 (latest own-site date)" belongs in `notes`. The excerpt is only text that appears on the page.
- **[v3.1] N9.** Edit an excerpt to satisfy our validator. Excerpts are verbatim, always. If a verbatim excerpt fails a check (for example, a time written as 一時半), leave it, add "verbatim; validator flag" in `notes`, and we will fix the validator.
  - The only allowed changes are removing an email address or a personal name: replace it with `[removed]`.
  - In task CN, 4 excerpts were rewritten to add time tokens. That makes them unverifiable.
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
| `service_times_verbatim`, `service_languages` + service companions | **[v3.2]** `service_excerpt` must contain the times. If the languages are stated in a different place on the same page, join both verbatim pieces with ` … ` (for example `Sunday Worship 10:00 AM … English · 中文 · 한국어`). Times without a time in the excerpt are not published. Languages only as stated. **[v3.1]** Use English names joined by `;` with no spaces, e.g. `Mandarin;Cantonese;English` (`Chinese` only when the source doesn't say which). |
| `kids_program_verbatim` + kids companions | As in results |
| `possible_match_id`, `match_note` | `known_id` from the known list if it may be the same congregation, and why |
| `found_via` | `fb_page_search`, `fb_group_lead`, `web_search`, `denomination_directory`, `host_church_site`, **[v3.4]** `church_directory` (S5; listing URL in `notes`) |
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
