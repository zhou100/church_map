# ChurchMap × Muse — how this folder works

This folder is a work queue. We put work packages in `outbox/`. You do them and put the results in `returns/`. Nobody needs to send a message for work to move: we check this folder several times a day.

**All research rules are in `reference/BRIEF_v3.md` (v3.2) and still apply.** This file covers only how work moves through the folder.

## Who writes where

| Path | Written by | You |
|---|---|---|
| `README_FOR_MUSE.md`, `status.csv`, `reference/` | ChurchMap | read only |
| `outbox/WP-xxxx/` | ChurchMap | read only |
| `feedback/WP-xxxx.md` | ChurchMap | read only |
| `returns/WP-xxxx/` | **you** | write here, and only here |

Never edit, move, or delete files outside `returns/`. Never delete anything in `returns/`: to correct a file, overwrite it.

## Picking up work

1. Open `status.csv`. Do the packages in this order:
   - first, any package whose `state` is `needs_fix`;
   - then the lowest-numbered package whose `state` is `queued`.
2. Create `returns/WP-xxxx/STARTED.md` containing the UTC time you started. This tells us, and any other worker of yours, that the package is taken. Skip a package that already has `STARTED.md` unless it is yours.
3. Read `outbox/WP-xxxx/TASK.md`. It names the inputs, the output files, the `task` value, and the `candidate_ref` prefix.
4. When a package is delivered, take the next one. **Don't wait for us.** Stop when no package is `queued` or `needs_fix`.

You may work on up to two packages at a time.

## Delivering

1. Write the output files named in `TASK.md` into `returns/WP-xxxx/`, plus `run_log.md` (D9 manifest, counts, blocked sites, hard rows).
2. Check them with `python3 reference/validate_returns.py`, using the command given in `TASK.md`. It is the same check we run.
3. **Write `DONE.md` last.** We read nothing in a package until `DONE.md` exists, and we read only the files it lists. It must contain one line per output file, with the file name, the row count, and the sha256 of the file **as saved in this folder**:

   ```
   new_candidates.csv  rows=87  sha256=3f5c…(64 hex characters)
   run_log.md          sha256=…
   partial: no
   ```

4. If you were rate-limited or ran out of time, deliver what is finished. Write `partial: yes` in `DONE.md` and list the cities or rows not yet checked in `run_log.md`. We will queue the rest as a new package. Never mark a row `unresolved` only because you ran out of time.

## When we send a package back

If our checks fail, `status.csv` shows `needs_fix` and `feedback/WP-xxxx.md` lists each problem.
- Fix the files in `returns/WP-xxxx/` in place.
- Never edit an excerpt to pass a check (N9). Copy a new verbatim excerpt from the page, or blank the fact.
- Then rewrite `DONE.md` with the new hashes. A new `DONE.md` is what tells us to look again.

## IDs

- Use the `candidate_ref` prefix given in `TASK.md` (for example `WP0001-001`, `WP0001-002`, …).
- Refs are permanent (D11). Never reuse one, even across packages. A removed row leaves a gap.
- `task` = the package id without the dash (for example `WP0001`).

## States in `status.csv`

| state | meaning |
|---|---|
| `queued` | ready for you |
| `started` | we saw your `STARTED.md` |
| `delivered` | we saw your `DONE.md` and are checking it |
| `needs_fix` | see `feedback/WP-xxxx.md` |
| `ingested` | accepted; nothing more to do |
