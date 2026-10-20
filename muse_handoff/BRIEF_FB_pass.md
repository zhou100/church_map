# ChurchMap × Muse — Facebook pass brief (FB-1)

**Purpose.** Batches A and B used Facebook very little. In one logged-in check, the congregation's own Facebook Page resolved a row the web couldn't (76673 Macedonia COGIC). This pass measures how much Facebook adds across the rows that are still unresolved or incomplete. The result decides whether ChurchMap will show facts that come only from a church's Facebook Page.

**All rules in `BRIEF_v2.md` still apply** (S1–S4, D1–D9, N1–N7, and the [v2.1] personal-phone rule), except where this brief changes them. Rules specific to this pass are F1–F8 below.

## Input

| File | Contents |
|---|---|
| `muse_handoff/fb_pass_input.csv` | 33 rows, sha256 `35c6d103927a0080b3f05908e0208b1f9e555ed004624789c2f380ee05ea2efa`. Tier `1_unresolved` = 15 rows whose status is still unresolved. Tier `2_fill_gaps` = 18 active congregations missing an address, phone, or service times. Columns: `church_id, tier, osm_name, current_name, city, latitude, longitude, current_status, official_url, known_facebook_url, needs` |
| `fb_pass_current_rows.csv` | Our **current** value for each of the 33 rows, in the results template format, including your batch A redo fixes. **Start every row from this file** (F5). sha256 `fc11c2af78b7440b260d48d1bec1029979eba844bacec06de952fbcebb252bd3` |
| `muse_handoff/results_TEMPLATE.csv`, `muse_handoff/new_candidates_TEMPLATE.csv` | Output headers |

`needs` lists what is missing: `status`, `street_address`, `phone`, `service_times`.

Out of scope for this pass, so don't spend time on them: Falun Dafa (78050), Sisters of the Holy Family (76682), the Kingdom Hall (77672), the LDS meetinghouse (76664), and duplicates 77786 and 76628.

## Rules for this pass

**F1. Account and visibility.** Yujun has authorized you to use the linked Facebook account for this pass only. Use only content that **anyone can see on a public Page**:
- the Page's intro/About section;
- the Page's own posts;
- public events created by the Page.

Do not use any of the following, even if the account can see it:
- friends-only content, or private or closed groups;
- personal profiles;
- comments, reactions, or follower and member lists;
- Messenger.

If you can't tell whether something is public, skip it.

**F2. No actions as the account.** Read only. Never like, follow, join, message, comment, RSVP, accept invites, or change settings. Contact no one.

**F3. Finding the congregation's own Page.**
- Search Facebook for the name plus the city. Also try the native-language name, and check the Pages of churches that might host the congregation.
- Report a Page in `facebook_page_url` only with non-empty `fb_page_evidence`. If the evidence is missing, put the URL in `notes` as a lead.
- `posts_as_church` shows the Page is run by the congregation. It does **not** count toward `match_confidence`. Only `address_matches`, `phone_matches`, and `cross_linked` against an independent source count.

**F4. Facts from the Page.** Set `<group>_source_type = fb_page`. Make `<group>_source_url` the **exact post permalink**, or the Page's About URL for intro facts. The excerpt must be verbatim and at most 200 characters.
- **`status = active`:** the Page itself posted about services or events within the last 12 months, at a location consistent with the pin.
- **`closed` or `merged`:** only when the Page itself says so, for example in a farewell or merger post.
- **Otherwise:** `unresolved`.
- **`fb_last_post_date`:** the newest post **by the Page itself**, as `YYYY-MM-DD`.
- **Services in another city or online only** (as with 76673's Zoom and Stockton posts): set `address_is_worship_location = unknown` and explain in `notes`.
- **Personal numbers:** a pastor's or member's own number stays out of `phone`. Write "personal number withheld" in `notes` (rule v2.1).

**F5. Editing rows: never go backwards.**
- Start from the row in `fb_pass_current_rows.csv`. Change only fields where Facebook gives new or better evidence.
- Keep existing facts from S1/S3/S4. If the Page contradicts one, report the more recent value and put the other value, with both dates, in `notes`.
- **Do not reuse values from any earlier file of yours.** In particular, don't reuse the original `results_A.csv` values that the redo removed (76681's places-tool text, 76675's ZIP 94030, 76686's aggregator facts).
- Append to `notes` with the prefix `FB pass:`.

**F6. Time box.** Do tier 1 first, at most 10 minutes per row. Then tier 2, at most 5 minutes per row. Write `checked_at` at the real time you check each row (D7). `minutes_spent` covers this pass only.

**F7. No Page found.** Keep the row's values. Update `checked_at` and append `FB pass: no own Page found (searched: <terms>)` to `notes`.

**F8. Congregations you notice along the way.** For example, a congregation renting a host church's building, announced on the host's Page. Add these to `new_candidates_FB.csv` with `found_via = fb_page_search`. Don't search for new congregations on purpose in this pass.

## Required output

1. **`results_FB.csv`** — exactly 33 rows, one per input `church_id`, as **full rows** in the results template format (not just the changes).
2. **`new_candidates_FB.csv`** — template header; may have no rows.
3. **`run_log_FB.md`**, containing:
   - The D9 manifest: path, row count, and sha256 for each file, re-read from disk.
   - How Facebook was accessed: connector or browser, logged in, and anything that needed more than public view.
   - **Facebook lift counts:**
     - tier-1 rows resolved by Facebook (→ active / closed / merged);
     - tier-2 fields filled by Facebook (address / phone / service times / languages);
     - rows where a Facebook Page is the **only** source of a fact we would show;
     - rows where Facebook contradicted an existing fact.
   - Hard rows, and any rule you were unsure about.

## How we will check it

```bash
python3 -I muse_handoff/validate_returns.py ALL muse_handoff/returns/results_FB.csv muse_handoff/returns/new_candidates_FB.csv --redo --received-at <UTC time received>
```

Beyond the v2 checks, we will diff each row against `fb_pass_current_rows.csv`. Any change that isn't backed by a `fb_page` source (or explained in `notes`) counts as a regression. Yujun will manually open a sample of the cited posts.
