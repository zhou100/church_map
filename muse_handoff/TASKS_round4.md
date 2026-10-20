# ChurchMap × Muse — round 4: tasks E and D

**All rules come from `BRIEF_v3.md`** (S, F, D, N, the output columns, and the kids group). This file only defines the tasks. Nothing in v3 changes.

Work order: **E first** (small, and it goes straight into the product), then the **D verification**, then the **D discovery**. Deliver E as soon as it's done; don't wait for D.

---

## Task E — Finish the pilot churches (72 rows)

The 77-church Peninsula pilot plus the 23 congregations you discovered in batches A and B are the first churches ChurchMap will show. Visitors choose by **language, service time, and children's program**, and batches A and B didn't collect children's programs yet.

**Input** (in `muse_handoff/outbox/`):

| File | Contents |
|---|---|
| `enrich_E_input.csv` | 72 rows, columns `ref, kind, name, city, visit_ready, needs` |
| `enrich_E_current_rows.csv` | Our current value for the 49 directory rows, in the v3 results format with empty kids columns. **Start each row from this file** and never go backwards: keep existing sourced facts unless a newer source contradicts them (note both values). |
| `enrich_E_candidates_known.csv` | What we know about the 23 discoveries (name, city, address, website, Page, earlier source) |

- **`kind = directory`** (49 rows, `ref` = `church_id`): fill what `needs` lists.
  - `kids` and `service_languages` are needed on every row.
  - Some rows also need `verified_street_address` (an address from the church's own site, its denomination, or its fresh Page), `contact` (a website, office phone, or fresh Page), or `current_service_times`.
- **`kind = candidate`** (23 rows, `ref` = `A-01`…`B-15`): produce a **complete v3 candidate row** with every fact group sourced, including kids. Keep `candidate_ref` = the given `ref`.

**Output:**

| File | Contents |
|---|---|
| `results_E.csv` | 49 full rows, `results_TEMPLATE_v3.csv` columns, one per directory `ref` |
| `new_candidates_E.csv` | 23 rows, `new_candidates_TEMPLATE_v3.csv` columns, `task = E`, `candidate_ref` = given ref |
| `run_log_E.md` | D9 manifest. Counts: rows with a children's program found; rows with stated languages; how many `needs` were filled, per need; rows whose facts come only from a Facebook Page. Hard rows. |

---

## Task D — San Francisco, South Bay core, and the Fremont area

**Verification (294 rows).** Input: `muse_handoff/batch_D_manifest.csv` (same columns as batch C, including `handling`).

| City | Rows |
|---|---:|
| San Francisco | 106 |
| San Jose (incl. Seven Trees, Cambrian Park, East Foothills, Alviso, Burbank) | 69 |
| Fremont | 37 |
| Milpitas | 21 |
| Santa Clara | 21 |
| Campbell | 18 |
| Union City | 9 |
| Newark | 7 |
| Los Gatos / Monte Sereno | 6 |

`handling`: 244 `full`, 45 `scope_check_only`, 5 `labeled_minimal`. These follow the same depth rules as task C.

**Discovery.** Find Christian congregations in these cities that are **not** in `muse_handoff/outbox/known_congregations_v4.csv` (488 known), and not already in your own task C / CN outputs. If one is in your C/CN output, set `possible_match_id` to that `candidate_ref`.

Per-city caps, best-sourced first:

| City | Cap |
|---|---:|
| San Francisco | 60 |
| San Jose | 80 |
| Fremont | 30 |
| Each other city above | 25 |

Report `service_languages` for every congregation where it is stated, whatever the language. Chinese-, Korean-, Vietnamese-, Spanish-, Tagalog-, and other-language congregations are all in scope. Use `task = D`.

**Output:**

| File | Contents |
|---|---|
| `results_D.csv` | 294 rows, `results_TEMPLATE_v3.csv` |
| `new_candidates_D.csv` | `new_candidates_TEMPLATE_v3.csv`, `candidate_ref` `D-001`… |
| `run_log_D.md` | D9 manifest; discovery sources per city; counts per city (found, already known, with kids program, by stated language, Facebook-only); blocked sites; hard rows |

You may deliver D in two parts (for example, San Francisco first). Each part needs its own D9 manifest.

---

## How we will check it

```bash
python3 -I muse_handoff/validate_returns.py ALL muse_handoff/returns/results_E.csv muse_handoff/returns/new_candidates_E.csv --redo --received-at <UTC>
python3 -I muse_handoff/validate_returns.py D_main muse_handoff/returns/results_D.csv muse_handoff/returns/new_candidates_D.csv --manifest muse_handoff/batch_D_manifest.csv --received-at <UTC>
```

For task E we also diff every row against `enrich_E_current_rows.csv`. A change without a newer source counts as a regression.
