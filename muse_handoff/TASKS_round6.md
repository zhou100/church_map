# ChurchMap × Muse — round 6: tasks H, S, W (finish what's started)

**Rules: `BRIEF_v3.md` (v3.2) applies in full.** The ones this round leans on:
- **N9:** excerpts are verbatim, never edited.
- **D4:** de-duplicate by name and by address.
- **D7:** a real per-row `checked_at`, in the form `YYYY-MM-DDTHH:MM:SSZ`.
- **D9:** the manifest lists the final files.
- **D11:** refs are permanent.
- **Own-source rule:** never take an address or phone from another congregation's site.
- **Pace yourself:** if rate-limited, deliver the finished part and list the rest as "not yet checked".

No new areas this round. Every row below is a gap we already know about.

Work order: **S → W → H**. S and W are small and go straight to the map. Deliver each task as its own part, with its own D9 manifest.

---

## Task S — complete service times (86 rows)

These 86 active congregations have service times we can't show yet. The recorded schedule (`recorded_service_times`) is longer than what its excerpt proves: usually the excerpt quotes one line (e.g. the Spanish Mass), while the record lists the whole week.

Our rule: a time is shown only if the excerpt states that time **with its day**, for the same kind of gathering and in the same language.

**Input:** `outbox/service_fix_S_input.csv`.
- Columns: `subject_type` (`church` / `candidate`), `subject_id`, `name`, `city`, `recorded_service_times`, `recorded_service_languages`, `current_source_url`, `reason`.
- 32 directory churches + 54 discoveries.

**What to do for each row:**

1. **Scope:** visitors need the **weekend worship services** (Saturday vigil and Sunday) and every **language-specific service**. Leave out weekday Masses, Bible studies, classes, and youth nights.
2. **Excerpt:** copy from the church's own page (or its denomination's page) a verbatim excerpt of **at most 200 characters** that states each kept time **together with its day**.
   - If the day heading and the times are in different places, join the pieces with ` … `. For example: `Sunday Masses … 8:00 AM, 10:00 AM … 12:00 PM (Spanish)`.
3. **Schedule:** set `service_times_verbatim` to **only what that excerpt states**, verbatim. Don't summarize, translate, or add anything the excerpt doesn't say.
4. **Languages:** set `service_languages` as stated (v3.1 format: `Mandarin;English`).
5. **No usable text:** if no page states the schedule as text (an image only, or stale), leave the times blank and say why in `notes`.

**Output:** `service_fixes_S.csv` (`service_fixes_S_TEMPLATE.csv`), exactly one row per input `subject_id`. Columns:
- `subject_type`, `subject_id`
- `service_times_verbatim`, `service_languages`
- `service_source_url`, `service_source_type`
- `service_excerpt`
- `checked_at`, `notes`

---

## Task W — is this address where they meet? (11 rows)

**Input:** `outbox/worship_location_W_input.csv`.

**Rows 1–8: otherwise map-ready.** Each has a verified address, a contact, and active status, but `address_is_worship_location` is `unknown` (or `no`). Answer from the church's own pages: is this the place where Sunday worship happens?
- If yes: answer `yes`, with an excerpt that says so (e.g. "Join us Sundays at 10am at 123 Main St"), or one that shows the address in a "Visit" / "Location" / "Worship with us" context.
- If they worship elsewhere: answer `no`, and give the worship address in `worship_street_address` / `worship_city` / `worship_zip`, with its own excerpt.

**Rows 9–11: specific address questions.**

| Row | Question |
|---|---|
| C-054 | Recorded as "1860 Grant Ave", but the own site says "1860 Grant **Road**". Which is right? |
| D-059 | Recorded as "5284 Monterey Rd.", but the own site says "5284 Monterey **Highway**". Give the street as the church states it. |
| 77533 | The own site prints "2411055th Avenue". Find another own or denomination source that states the house number. |

For these, put the corrected street in `worship_street_address`, with its excerpt.

**Output:** `worship_location_W.csv` (`worship_location_W_TEMPLATE.csv`), exactly one row per input `subject_id`. Columns:
- `subject_type`, `subject_id`
- `address_is_worship_location`: `yes` / `no` / `unknown`, never True/False
- `worship_street_address`, `worship_city`, `worship_zip`
- `source_url`, `source_type`, `excerpt`
- `checked_at`, `notes`

---

## Task H — harvest the leads you already found (60 rows)

**Input:** `outbox/harvest_H_input.csv`.

**`kind = fill_directory_row` (8 rows: 76442, 77552, 77539, 77547, 77654, 77487, 77513, 76402).** These F directory rows were left blank, but you noted an S1–S4 source exists. Return each as a full v3 results row.

**`kind = new_lead` (52 rows, H-001…H-052).** These congregations you located in rounds 4–5 but didn't verify:
- 16 in Oakland (St. Columba, Sacred Heart, St. Jarlath, Lakeshore Avenue Baptist, Beebe Memorial, …);
- leads in Alameda, Hayward, Castro Valley, San Leandro, Pinole, Rodeo, El Sobrante, San Lorenzo, Concord, and Livermore;
- Korean, Vietnamese, Spanish, Ukrainian, and Samoan congregations from task L.

`hint` carries what you noted at the time.

- Return **every lead exactly once**, as a full v3 candidate row with `candidate_ref` = its `lead_id` and `task = H`.
- If a lead turns out to be already known, set `possible_match_id` to its `known_id` in `outbox/known_congregations_v7.csv`. Report it only if you add language, service, or kids facts; otherwise give `status = unresolved` and a note.
- If a lead can't be confirmed from an S1–S4 source, return it `unresolved` with a note.
- Congregations you newly find along the way: `H-101`, `H-102`, ….
- Still skip the sites that blocked you (Faith Tabernacle AOH Richmond, Hope Lutheran El Sobrante, St. Mark's Episcopal Berkeley). Don't retry or route around a block.

**De-duplication:** `outbox/known_congregations_v7.csv` (1,289 known), which includes your F and L results.

**Output:**
- `results_H.csv` (`results_TEMPLATE_v3.csv`), the 8 fill rows;
- `new_candidates_H.csv` (`new_candidates_TEMPLATE_v3.csv`);
- `run_log_H.md`.

---

## Run logs

One per task (`run_log_S.md`, `run_log_W.md`, `run_log_H.md`), each with:
- the D9 manifest;
- how many rows were completed, left blank, or not yet checked;
- blocked sites;
- any rule you were unsure about.

## Input files

| File | Rows | sha256 |
|---|---:|---|
| `outbox/service_fix_S_input.csv` | 86 | `c42503290557a3857ef52a9aa4ac177465c1291bedff490e26bd5bb83fc9cf96` |
| `outbox/worship_location_W_input.csv` | 11 | `1d292359b9d3ade43f4b358d82a27645213d03aadc5de42b8f29871cb96afd4f` |
| `outbox/harvest_H_input.csv` | 60 | `d64f7f41ded6b29fa35549fac9b95c967cbc5e4bfe29dea211484d45b6a276f5` |
| `outbox/known_congregations_v7.csv` | 1,289 | `6d866977e5cb0359d46f1a1ca72e297d4d50eb4b1f69a610a76d1d129503dccf` |
| `service_fixes_S_TEMPLATE.csv`, `worship_location_W_TEMPLATE.csv` | — | new this round |
| `results_TEMPLATE_v3.csv`, `new_candidates_TEMPLATE_v3.csv`, `BRIEF_v3.md` | — | unchanged |

## How we will check it

```bash
python3 -I muse_handoff/validate_returns.py ALL muse_handoff/returns/results_H.csv muse_handoff/returns/new_candidates_H.csv --redo --manifest muse_handoff/batch_F_manifest.csv --received-at <UTC>
```

**S:** each excerpt is re-verified on its page, and each kept time must appear with its day in the excerpt (the same rule the map uses).

**W:** each excerpt is re-verified, and a changed street must be stated in full (house number + every street word).
