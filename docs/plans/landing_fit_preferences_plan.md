# Landing page: ask what fits, then recommend

**Prepared:** 2026-10-23 · **Status:** plan, under design review (`/plan-design-review`)

## Problem

The map-first landing page (DESIGN.md, 2026-10-22) tells a visitor what ChurchMap
is within seconds, but it only learns one thing about them: the city. Without
knowing what they want, "Start here" can only rank by how well documented a
church is, not by fit. There is also no moment that gives a visitor a reason to
sign in or leave a review.

## Proposal

An optional "What matters to you?" step inside the existing hero card, after the
city input. It does not gate the map.

(Layout superseded by "Design decisions" below.)

Rules:

1. **Only ask what the data can answer.** Language → `service_languages`;
   worship → `worship_style`; kids → verified `kids_program` (migration 0006),
   extracted `programs` naming children/kids/youth/nursery/Sunday school, or a
   community `childrens_programs` rating.
   No questions whose answers cannot move results.
2. **Rank, never filter.** Coverage is thin (Brooklyn, 200 rows: 8 with
   `service_languages`, 6 with `worship_style`; TODOS F4). Matches rise to the top
   with a one-line reason; churches we have not read stay visible and say so.
3. **Value before sign-in.** Preferences live in localStorage first, like
   `churchmap_last_search`. Sign-in is offered after the visitor has got
   something: "save across devices", "tell others how your visit went".
4. **Reviews come from return visits.** We know which churches a visitor opened.
   On a later visit: "Last time you looked at Grace Church — did you visit?"

## Design decisions (design review, 2026-10-23)

### Information hierarchy

The first five seconds stay exactly as they are today. The question appears only
once there are churches on screen to make better: we show an answer first, then
ask the question.

**Desktop (> 760px), hero card, top to bottom:**

```
1  h1  New in town? Find a church that fits.          (unchanged)
2  City input + "Use my location"                       (unchanged)
3  "Start here in Oakland"  — 3 picks                   (unchanged until prefs set)
4  ┌ Make these fit you  ·  language, worship, kids  → ┐ one line, sienna text link
   └────────────────────────────────────────────────────┘
       click → expands in place, between 3 and 5:
         Language   [English] [Spanish] [Korean] …   (max 6 chips)
         Worship    [Liturgical] [Hymns] [Blended] [Contemporary] [Charismatic]
         Kids       [We're bringing kids]
         [Done]                       Clear
5  See every church in Oakland →                        (unchanged)
```

Once preferences are set, row 4 collapses to a summary that edits on click:
`For you: Spanish · Contemporary · Kids  ·  Edit`, and the eyebrow on row 3
becomes "Start here in Oakland — for you".

**Mobile (≤ 760px):** the card already hides the picks to keep the map visible
(`index.css:1378-1379`); that stays. Row 4 shows as a second line under
"See every church": `Make these fit you →`. Tapping opens a bottom sheet
with the same three groups and a full-width primary button
`Show churches that fit (N)`, which goes to `/search` with the preferences
applied.

**Questions asked: three.** Language, worship style, kids. Theological stance is
**not** asked on the landing page: as a first question it reads as a political
sort, and the value is an LLM inference that is costly when wrong. It stays
visible on church profiles and available as a Search filter.

**Chip sources:**
- Language: English and Spanish always, then the most common other
  `service_languages` values among this city's loaded rows, 6 chips max.
- Worship: the five `worship_style` buckets, with user-facing labels:
  `liturgical` → Liturgical, `traditional-hymns` → Hymns, `blended` → Blended,
  `contemporary` → Contemporary, `charismatic` → Charismatic.
- Kids: a single toggle.

Within a group, multiple chips mean "any of". Across groups, each group that
matches adds to the score.

### Interaction states

Rule for every state: **unknown is never shown as no.** A reason line lists only
what matched ("Spanish service · Kids program"). We never print "No kids
program" or "English only": a church we have not read has not told us.

```
FEATURE                 | LOADING                  | EMPTY / NONE                     | ERROR                          | SUCCESS                         | PARTIAL
------------------------|--------------------------|----------------------------------|--------------------------------|---------------------------------|---------------------------------
"Make these fit you"    | hidden until picks are   | hidden if the city has no picks  | hidden if the preview failed   | one-line link                   | —
link (row 4)            | ready                    | (nothing to improve)             |                                |                                 |
Preference panel        | —                        | language row shows only English  | localStorage throws → panel    | chips toggle instantly,         | —
                        |                          | + Spanish when the city has no   | still works for this page view;| aria-pressed, picks re-rank     |
                        |                          | read rows with languages         | nothing is said                | as each chip is pressed         |
Re-ranked picks         | existing "Finding        | see "zero matches" decision      | existing preview error path    | eyebrow "— for you"; each pick  | pick matches 1 of 3 groups:
                        | churches near…" line     | below                            |                                | shows a reason line of what     | reason line lists that one;
                        |                          |                                  |                                | matched, gold check icon        | ranks below 2-of-3 matches
Summary chip row        | —                        | not shown when no prefs set      | —                              | "For you: Spanish · Kids · Edit"| —
Mobile sheet button     | —                        | "Show churches in Oakland"       | —                              | "Show churches that fit"        | —
                        |                          | (no prefs = plain search)        |                                | (no count in phase 1: we only   |
                        |                          |                                  |                                | see 100 rows, a count would lie)|
Search page re-rank     | existing skeleton        | same zero-match treatment        | existing error                 | same reason line on cards       | same as picks
```

**Zero matches (decision 3A).** Keep the three documented picks and put one
line above them, in `--text-2`:

> None of the 38 churches we have details on in Fresno mention Korean services yet —
> most haven't told us. These are still good places to start.

The eyebrow stays "Start here in Fresno" (not "for you"). The number appears only
when it is exact: `sort=starting_point` puts every read church first, so the
count of read rows in the preview is exact when it is below the row limit. At the
limit, drop the number ("None of the churches we have details on in Fresno…"). Name the
unmatched preference in the sentence; with more than one, name them all
("Korean services or a kids program").

### Journey

```
STEP | USER DOES                           | USER FEELS                    | SUPPORTED BY
-----|-------------------------------------|-------------------------------|--------------------------------
1    | Lands, sees their city's map        | "This finds churches"         | unchanged first screen
2    | Sees 3 picks, opens "Make these fit"| Curious, willing to say more  | row 4 link, after picks exist
3    | Picks Spanish + kids; picks re-rank | "It heard me"                 | instant re-rank, reason lines
4    | Opens a church profile              | Deciding whether to go        | existing page; view is recorded
5    | Comes back days later               | May have gone already         | return-visit prompt (below)
6    | Answers "I went"                    | Remembered; willing to share  | lands on that church's review form
7    | Signs in to post the review         | Signing in to do what I chose | ReviewForm's existing GSI button
```

Five seconds: unchanged. Five minutes: the picks visibly respond to them. Long
term: ChurchMap remembers what they looked at and asks once how it went.

### Return-visit prompt (phase 3, decision 4A)

Lives in the hero card, above the picks, on desktop and mobile:

```
Did you visit Grace Church?            ×
[ I went ]   Not yet
```

- **Recorded:** opening `/church/:id` (standalone or search panel) appends
  `{id, name, viewed_at}` to localStorage `churchmap_viewed` (last 20, newest wins).
- **Eligible:** a Sunday has passed since `viewed_at`, the church was not
  dismissed, and it was not already reviewed in this browser.
- **Shown:** at most one prompt per page load, for the most recently viewed
  eligible church. Never on the first visit.
- **I went** → `/church/:id#review`. The review form scrolls into view, with its
  existing Google sign-in button if signed out. After a successful post, mark the
  church reviewed.
- **Not yet** → hide now; eligible again after the next Sunday. After the
  second "Not yet", stop asking about that church.
- **×** → never ask about that church again.
- Church name in Fraunces, as everywhere. "I went" is the sienna primary
  button; "Not yet" is a text button.

### Sign-in moments

Sign-in is never asked for up front. It appears in two places only:

1. The review form, reached from "I went" or from a church page (existing).
2. Phase 2: the summary row gains `Save to your account` once preferences
   are set. Signing in there uploads the localStorage preferences. Signed-in
   users' saved preferences win over local ones on a new device.

### Copy and design-system alignment

- **Group labels are questions a newcomer asks, not field names:**
  `Services in` (language), `Sunday feels like` (worship),
  `We're bringing kids` (one toggle). Entry link: `Make these fit you`.
  No "Personalize your experience", no quiz framing, no progress bar, no emoji.
- **Chips** reuse Search's `tag-filter-pill` / `tag-active` (white, sienna when
  selected, per DESIGN.md "Active/selected"). They are controls, so they must not
  borrow any of the four tag-pill styles.
- **Reason line merges sources, unlabeled** (eng review decision 1C, owner
  approved): `Spanish service · Kids program`. This is a deliberate exception to
  DESIGN.md's rule that machine-read claims carry a source line. Record it in the
  DESIGN.md decisions log in the same PR. The card's existing `✓ Website read`
  row still shows where a profile came from. Text `--text-2`; matched values in
  sienna. No gold: gold is reserved for stars, the active pin and dimension bars.
- **Signal sources** (one helper, `fitSignals(church)` in `churchProfile.js`,
  used by landing and Search). Each signal keeps its `source` internally, so
  labeling can return without touching the matching:

  | Preference | Sources in the list API row | `source` |
  |---|---|---|
  | Language | `service_languages` (verified facts, migration 0006) | `verified` |
  |          | `extracted_tags.service_languages` | `website` |
  |          | `language` (legacy directory field) | `directory` |
  | Worship  | `extracted_tags.worship_style` | `website` |
  | Kids     | `kids_program` (verified) | `verified` |
  |          | `extracted_tags.programs` matching children/kids/youth/nursery/Sunday school | `website` |
  |          | `tags` includes `"Kids programs"` (≥ 3 reviews, avg > 4.0, `backend/utils.py`) | `community` |

  The list endpoint does not return raw dimension averages (`include_dims` is
  detail-only), so "rated well for kids by N people" cannot be computed. The
  community tag is the only kids signal from reviews.
- Church names in the return prompt use Fraunces.
- No new colors, shadows or fonts.

### Responsive and accessibility

**Desktop (> 760px):** the panel expands inside the card. The card already scrolls
at `max-height: calc(100% - 48px)`; the expanded panel must fit within 560px
(the hero `min-height`) without the picks scrolling out of view. If it does
not, the picks collapse to names only while the panel is open.

**Mobile (≤ 760px):** a bottom sheet, not an inline expansion.
- Rises from the bottom over the map, max 80dvh, 16px radius on top corners,
  `--surface`, a drag handle and a visible `×`.
- Chip groups wrap; every chip is at least 44px tall.
- Footer pinned to the bottom: a full-width primary button `Show churches that fit`
  and a `Clear` text button.
- The map stays visible above the sheet. Closing the sheet without pressing the
  button keeps the choices (they are already saved).

**Keyboard and screen readers:**
- The entry link is a `<button aria-expanded aria-controls>`; on desktop, focus
  moves to the first chip when it opens.
- Each group is a `role="group"` with `aria-labelledby` on its question.
  Chips are `<button aria-pressed>`.
- The mobile sheet is a `role="dialog" aria-modal="true"` with a focus trap.
  `Esc` closes it and returns focus to the button that opened it.
- Re-ranking announces through a polite live region: "Picks updated for Spanish
  services and kids."
- The return prompt is a `role="region" aria-label="Did you visit"`.
  `×` has `aria-label="Don't ask about Grace Church again"`.
- Contrast: the `--text-2` (#6B6560) reason line on white passes AA at 13px+.
  Sienna on white passes AA for the bold matched values.
- `prefers-reduced-motion`: the sheet appears without the slide.

### Search page (decision 5A)

- A `For you` sort pill joins the existing sort bar. It is selected by default
  when preferences exist and is absent when they don't.
- Above the list: `For you: Spanish · Kids · Edit`. Edit opens the same panel
  component as the landing page: inline on desktop, sheet on mobile.
- Cards show the same reason line as the landing picks.
- Same limitation as every Search sort today (TODOS F3): it orders the loaded
  rows, not the whole city.

### Persistence

- localStorage key `churchmap_preferences`:
  `{languages: string[], worship: string[], kids: boolean, updated_at}`.
  It is global, not per city: language and kids don't change with the city.
- A selected language that the new city's chip list lacks still shows, selected.
- Every read and write sits in try/catch. With storage blocked, preferences live
  for the page view only, and nothing is said.

## Engineering notes (eng review, 2026-10-23)

```
                  localStorage "churchmap_preferences"
                               │  load() in useEffect, never during render
                               ▼
  preferences.js ── load / save / normalize (pure, node --test)
        │
        ▼  prefs state lifted into the page (Landing.jsx / Search.jsx)
  ┌───────────────────────┐        ┌──────────────────────────────────┐
  │ FitPreferences.jsx    │ change │ churchProfile.js                 │
  │ inline panel (desktop)│──────► │ fitSignals(church) → [{pref,     │
  │ <dialog> sheet (mob.) │        │   value, source}]                │
  │ summary row + Edit    │        │ fitScore(church, prefs) → 0..3   │
  └───────────────────────┘        │ rankForYou(rows, prefs)          │
                                   │   = stable sort by fitScore,     │
                                   │     ties keep API order          │
                                   │ zeroMatchSentence(rows, prefs,   │
                                   │   limit)                         │
                                   └──────────────┬───────────────────┘
                                                  ▼
                  Landing: pickStartingPoints(rankForYou(rows)) → 3 picks
                  Search:  "For you" sort = rankForYou(loadedRows)
```

- **Hydration.** `/` is prerendered. Reading preferences during the first render
  would make the client tree differ from the prerendered HTML. Read them in
  `useEffect`, the same way `churchmap_last_search` is read today
  (`Landing.jsx:80-94`). The first paint is always the no-preference state.
- **Ranking, not filtering.** `rankForYou` is a stable sort: with no preferences
  it returns rows in API order, so "no prefs → identical to today" holds by
  construction. `pickStartingPoints` still runs after it, so `isChurch` and
  `hasSomethingToShow` keep applying.
- **Normalization.** Compare languages case-insensitively and trimmed.
  `service_languages` from the extractor is English-named per the prompt; legacy
  `language` values may differ in case.
- **Mobile sheet is a native `<dialog>` opened with `showModal()`.** That gives
  focus trapping, `Esc`, an inert background and focus return without a library
  or hand-written trap.
- **One language helper (eng decision 2A).** `churchLanguages(church)` in
  `churchProfile.js` unions the three language sources. It is used by
  `fitSignals`, the existing Search language filter (`Search.jsx:198-203`, which
  today reads only `language`) and the card language tags (`ChurchCard.jsx:52`).
  One church then has one answer to "which languages" everywhere.
  `cultural_background` is not a language. It stays its own filter pill, as it is
  today.
- **Chip list.** `cityLanguageChips(rows, selected)` (pure) returns English,
  Spanish, then the most frequent other `churchLanguages` values in the rows, 6
  max, always including any selected language.
- **No new state library or context.** State lives in the page component; the
  panel is controlled through props.
- **Phase 2 (when it comes):** `PUT /api/me/preferences` validates against the
  same enums (languages: ≤ 10 strings ≤ 40 chars; worship: the five buckets;
  kids: bool) and returns 422 otherwise. It is subject to `READ_ONLY` (503); on
  any failure the client keeps the local copy and says nothing.

## Phases

| Phase | What | Touches |
|---|---|---|
| 1 | Shared preference panel (inline + sheet); row-4 link and summary on the landing card; "For you" re-rank with reason lines and the zero-match sentence on landing picks and Search ("For you" sort pill) | Frontend only: `Landing.jsx`, `Search.jsx`, `ChurchCard.jsx` (language tags via `churchLanguages`), new `components/FitPreferences.jsx`, new `preferences.js`, `churchProfile.js` (+ tests), `index.css`, DESIGN.md decisions log |
| 2 | Signed-in users sync preferences; "Save to your account" in the summary row | `migrations/0007_user_preferences.sql`, `GET/PUT /api/me/preferences` (via `get_current_user`), two `client.js` functions |
| 3 | Return-visit prompt | Frontend only: `churchmap_viewed` recording in `ChurchDetail.jsx` / `ChurchDetailPanel.jsx`, prompt in `Landing.jsx`, `#review` anchor on the review form |

Phase 1 limitation: the landing preview loads 100 rows (`sort=starting_point`),
so client-side re-ranking only sees those. `GET /api/churches` already accepts
`language`, `worship_style` and `stance` (since #23, unused; TODOS F3), and server-side
matching is the follow-up once F3 lands.

## What already exists (reuse, don't rebuild)

- `tag-filter-pill` / `tag-active` chip styles (`Search.jsx`, `index.css`).
- `map-hero-picks` list and the `✓ Website read` row (`Landing.jsx:193-220`).
- `hasWebsiteProfile`, `pickStartingPoints`, `isChurch` (`churchProfile.js`).
  Match scoring is a re-rank on top of `pickStartingPoints`, never a replacement
  for its not-a-church filter.
- The `churchmap_last_search` localStorage pattern with try/catch (`Landing.jsx:82-87`).
- `ReviewForm`'s inline GSI sign-in button (`ReviewForm.jsx:23-27`).
- The mobile rule that hides picks to keep the map visible (`index.css:1378-1379`).

## NOT in scope

- **Theological stance on the landing page.** It reads as a political sort and is
  an LLM inference; it stays a Search filter.
- **Server-side matching across the whole city.** Needs F3's URL-driven filters first.
- **Match counts on the mobile button.** A count over 100 loaded rows would be wrong.
- **Email or push reminders after a visit.** Needs an email channel and consent
  design. The in-page return prompt comes first.
- **Free-text "tell us about yourself".** It cannot move results.
- **Weighting community dimension ratings by preference.** Ratings are too sparse
  today to rank on.

## Not touched

Auth flow, existing API response shapes, `backend/scrapers/`, the map-first
first five seconds.

## Tests (eng decision 3A: pure-function units + browser QA, no new dependencies)

Components only render. Every decision lives in a pure function under
`node --test` (the existing `npm test`).

```
CODEPATH                                   | UNIT TEST (node --test)
-------------------------------------------|-----------------------------------------------------
preferences.js load / save / normalize     | bad JSON; storage throws on read and on write; unknown
                                           | keys dropped; unknown worship values dropped; dedupe
churchLanguages(church)                    | each of 3 sources alone; union; case/trim; dedupe; nulls
fitSignals / fitScore                      | each pref × each source; kids keywords (kids, children,
                                           | youth, nursery, Sunday school); "Kids programs" tag;
                                           | no signal when unmatched; never emits a negative
rankForYou                                 | no prefs → same array order; stable on ties; 2-of-3
                                           | above 1-of-3
pickStartingPoints(rankForYou(rows))       | a matching not-a-church row is still never picked
zeroMatchSentence                          | exact count below limit; no number at limit; one vs
                                           | several unmatched prefs; null when something matched
cityLanguageChips                          | English + Spanish first; ≤ 6; selected always present
returnPromptCandidate(viewed, now)         | first visit → none; Sunday rule across week boundary;
                                           | "Not yet" ×2 stops; × stops; reviewed stops; newest wins
Search language filter via churchLanguages | verified- and website-sourced languages now match
```

Browser QA checklist (`/qa`, real browser; written to the gstack test plan):

- No preferences → landing picks and Search order identical to production.
- Prerendered `/`: no hydration warning in the console with preferences saved.
- Desktop: open panel → focus on first chip; chips toggle `aria-pressed`; picks
  re-rank live; live region announces; summary row + Edit.
- Mobile 375px: sheet opens with `showModal()`; Tab stays inside; `Esc` closes and
  focus returns; chips ≥ 44px; map visible with the sheet closed; "Show churches
  that fit" lands on Search with "For you" selected.
- Private window / storage blocked: panel works, nothing throws.
- Zero-match city: sentence shows, picks stay.
- Return prompt: seeded `churchmap_viewed` from before last Sunday → prompt; "I
  went" scrolls to the review form with the GSI button.

## Failure modes

| Codepath | Realistic failure | Test | Handling | User sees |
|---|---|---|---|---|
| preferences load | corrupted JSON from an older build | unit | normalize → defaults | no prefs, no error |
| preferences save | Safari private mode throws | unit | try/catch | prefs last for the page view |
| prerendered `/` | prefs read during render → hydration mismatch | QA | read in `useEffect` | first paint = no prefs |
| rankForYou | unstable sort shuffles equal rows | unit | stable sort | today's order |
| fitSignals | `extracted_tags` missing or a non-array | unit | `hasValue` guards | no reason line |
| `<dialog>` | older browser without `showModal` | QA | fall back to inline panel | inline panel |
| return prompt | viewed church later removed → 404 | none | existing 404 page | 404 page (acceptable) |

No critical gaps: every row has a test or handling, and none fails silently in a
harmful way.
