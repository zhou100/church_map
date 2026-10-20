# ChurchMap × Muse — round 5: tasks F and L

**All rules come from `BRIEF_v3.md` (v3.2).** The most important ones:
- **N9:** excerpts are verbatim, never edited to pass a check.
- **D4:** match duplicates by address as well as name, including against your own outputs.
- **D7:** write `checked_at` at the real time of each check.
- **D9:** re-open your files from disk and give a manifest. The manifest must list the **final** files; re-hash after any merge or fill pass.
- **[v3.2]** `candidate_ref`s are permanent (D11). Service excerpts contain the times. `checked_at` is `YYYY-MM-DDTHH:MM:SSZ` from a UTC clock, per row, at the time of the check; no shared or after-the-fact stamps.
- **Pace yourself.** Round 4 hit HTTP 429 halfway and left 200 rows unresolved.
  - Keep to about one request every few seconds per site, and fewer parallel workers.
  - If you are rate-limited, stop, deliver what is finished as a part with its own manifest, and resume later. Don't mark rows unresolved just because the limit hit; list them as "not yet checked" in the run log.
- **A fact must come from the congregation's own sources** (S1/S2) or its denomination (S3). Never take an address or phone from **another congregation's** website, even one that shares the building. In round 4, D-107's address was cited from its host church's site.

**De-duplicate against `known_congregations_v6.csv`.** It replaces v5 and already includes every directory row and every discovery from A through E (C, CN, D, and E included), with current names, addresses, and status.

Work order: **F verification** → **L** → **F discovery**. Deliver each part when it is done. Each part needs its own D9 manifest.

---

## Task F — East Bay

**Verification (404 rows).** Input: `muse_handoff/batch_F_manifest.csv` (same columns as batches C and D).
- `handling`: 355 `full`, 37 `scope_check_only`, 12 `labeled_minimal`.
- The manifest's cities come from the pin and are often wrong (e.g. many "San Leandro" rows may be in Oakland). Correct them with the USPS city (D10).

| Area | Manifest cities (rows) |
|---|---|
| Oakland / Alameda / Emeryville / Piedmont | San Leandro 52, Alameda 45, Oakland 30, Emeryville 14, Piedmont 14 |
| Richmond area | Richmond 47, North Richmond 12, San Pablo 12, El Cerrito 8, El Sobrante 3, Pinole 1, Rodeo 3 … |
| Hayward area | Hayward 23, San Lorenzo 12, Cherryland 6, Ashland 5, Castro Valley 1 |
| East Contra Costa | Pittsburg 19, Antioch 18, Brentwood 7, Oakley 5, Bay Point 1, Knightsen 1 |
| Berkeley / Albany / Kensington | Berkeley 9, Kensington 2, Albany 1 |
| Tri-Valley and central Contra Costa | Livermore 7, Concord 7, San Ramon 5, Dublin 3, Pleasanton 3, Danville 2, Walnut Creek 2 … |
| Other | Benicia 13, and single rows |

**Discovery.** Find congregations missing from `known_congregations_v6.csv`. Report every language the church states.

| City | Cap |
|---|---:|
| Oakland (including Chinatown) | 60 |
| Berkeley | 25 |
| Richmond | 25 |
| Hayward | 25 |
| San Leandro | 20 |
| Alameda | 20 |
| Castro Valley | 15 |
| Dublin | 20 |
| Pleasanton | 20 |
| San Ramon | 20 |
| Danville | 15 |
| Livermore | 20 |
| Walnut Creek | 20 |
| Concord | 20 |
| Antioch | 15 |
| Pittsburg | 15 |
| Brentwood | 15 |
| Any other East Bay city | 10 |

Fremont, Newark, and Union City were covered in round 4 (task D); don't repeat them.

**Output:**

| File | Contents |
|---|---|
| `results_F.csv` | 404 rows, `results_TEMPLATE_v3.csv` |
| `new_candidates_F.csv` | `new_candidates_TEMPLATE_v3.csv`, `task = F`, `candidate_ref` `F-001`… |
| `run_log_F.md` | D9 manifest; discovery sources per city; counts per city (found, already known, with kids program, by stated language, Facebook-only); blocked sites; hard rows |

---

## Task L — Other language communities in the areas already covered

The areas covered so far:
- San Mateo County;
- Palo Alto through Cupertino;
- San Francisco;
- the South Bay core (San Jose, Santa Clara, Milpitas, Campbell, Saratoga, Los Gatos);
- Fremont, Newark, and Union City.

Task CN covered Chinese-language congregations. **L covers the other languages.** Find congregations whose own source states services in these languages:

| Language | Cap |
|---|---:|
| Korean | 50 |
| Vietnamese | 40 |
| Spanish (including bilingual Spanish/English services or ministries of a larger church) | 60 |
| Tagalog / Filipino | 30 |
| Any other non-English language (e.g. Japanese, Indonesian, Portuguese, Russian, Arabic, Amharic, Hindi, Malayalam, Telugu, Tongan, Samoan) | 40 total |

Rules for this task:
- A congregation already in `known_congregations_v6.csv` is reported **only if you add stated languages, service times, or a children's program**. Set `possible_match_id` to its `known_id` (D4).
- The language must be **stated by the congregation** (N5). A name like "Korean …" is a search clue, not proof.
- Use `task = L`, `candidate_ref` `L-001`….

**Output:** `new_candidates_L.csv` (`new_candidates_TEMPLATE_v3.csv`) and `run_log_L.md` (D9 manifest; sources used; counts by language and city; already-known rows; with kids program; Facebook-only).

---

## Input files

| File | Notes |
|---|---|
| `BRIEF_v3.md` | v3.2 |
| `muse_handoff/batch_F_manifest.csv` | 404 rows, sha256 `7de32c6fac00b1b680851d0b2a65f20b0d1fd515f3105c145aa12fc1e06db57b` |
| `muse_handoff/outbox/known_congregations_v6.csv` | 1,150 known, sha256 `31e0a8c2af04f5801f276009113110d4a3bcf96b723936b846ba4154098c1f84`: 869 directory records (all areas, East Bay included, with your verified names/addresses/status where you checked them) and 281 discoveries (A/B as rebuilt in E, CN, C, D) |
| `results_TEMPLATE_v3.csv`, `new_candidates_TEMPLATE_v3.csv` | Unchanged |

## How we will check it

```bash
python3 -I muse_handoff/validate_returns.py F_main muse_handoff/returns/results_F.csv muse_handoff/returns/new_candidates_F.csv --manifest muse_handoff/batch_F_manifest.csv --received-at <UTC>
python3 -I muse_handoff/validate_returns.py ALL - muse_handoff/returns/new_candidates_L.csv --received-at <UTC>
```

Plus the automated source re-check: every non-Facebook excerpt must appear on its cited page.
