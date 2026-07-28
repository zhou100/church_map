# ChurchMap — Landing Page & Frontend Revamp Plan

Written 2026-07-27, after a live audit of `churchmap.vercel.app` and the public
`/api/stats`. Companion docs: [STATUS.md](STATUS.md) (system state),
[TODOS.md](TODOS.md) (active backlog), [DESIGN.md](DESIGN.md) (design system).

Everything below is measured, not assumed. Numbers came from the live API and
from driving the deployed site in a headless browser at 390px, 768px and 1440px.

---

## TL;DR

**The backend is done waiting on itself.** The crawl pipeline is healthy, the
terminal failure rate is 2.5%, and the only remaining backend work of substance
is queueing backfill chunks — a runbook, not engineering. One real backend bug
turned up in this audit (a mid-word text truncation, [§2.7](#27-backend-defect-theology_summary-is-cut-mid-word)).

**But "waiting for the crawl" understates the problem.** 93.6% of the corpus has
no website recorded, so crawling cannot reach it *in principle*. Coverage is not
a queue that drains; it's a ceiling.

**The frontend is where the value is trapped.** The site currently leads with its
weakest asset — an empty map of unrated churches in whatever city your IP
resolves to — and buries its strongest, the website-extracted church profile,
which is genuinely good and which nobody else in this space has.

**The one fact that should reshape the product story:** every review in the
entire product is seed data on church IDs 1–7. Chicago, Houston and Seattle have
**zero** reviews across 547 churches. The homepage tagline promises churches
"rated on what actually matters"; that promise is currently backed by seven
fixtures, one of which is a review whose text is `test`.

So the revamp is not a visual refresh. It is **re-pointing the product at the
claim it can actually keep.**

---

## 1. Backend status — answering "是不是差不多了"

Live `/api/stats`, 2026-07-27 23:01 UTC:

| Measure | Value |
|---|---:|
| Pipeline healthy | `pipeline_ok: true` |
| Stage freshness | fetch, extract, tag all inside budget |
| Runs, last 7 days | 54 ok / 0 error / 7 partial / 1 running |
| Extraction attempts | 5,463 attempted, 5,326 ok, 137 failed (**2.5%**) |
| Failure breakdown | `error: 135`, `transient: 2`, `no_html: 0`, `no_text: 0` |

That is a healthy pipeline. `no_html: 0` and `no_text: 0` are the important
entries — they were the failure modes that would have meant the backfill's
premise was wrong (see STATUS.md §8–9), and they are empty.

Coverage, same snapshot:

| | Count | Share of corpus |
|---|---:|---:|
| Total churches | 133,939 | 100% |
| With a website recorded | 8,514 | **6.4%** |
| Successful extraction | 5,326 | **4.0%** |
| With a website summary | 4,332 | **3.2%** |
| Stale vs. current prompt/model | 5,316 | 97.3% of attempted |
| Not yet queued for re-extraction | 3,330 | — |

**Verdict: yes, the backend is essentially done except for the crawl — with two
caveats that are not "wait longer" problems.**

1. **The 93.6% ceiling is structural.** 125,425 churches have no website
   recorded. The R2/LLM pipeline can never enrich them in its current form. This
   is already the last item in TODOS.md's "Now" section and it deserves to be
   treated as a product question (what is a minimum useful profile, and what
   other sources fill it), not a pipeline question.

2. **97.3% of extractions are stale.** Users are seeing pre-v3.1 output right
   now. The single enriched card visible on the first page of Brooklyn results
   displays the language as `Kreyol` — the exact value prompt v3.1 was written to
   fix (`Haitian Creole`). The backfill isn't cosmetic; it's visibly wrong data
   on screen.

Neither blocks frontend work. Both should inform what the frontend promises.

---

## 2. What the live site actually does

### 2.1 There is no landing page

`https://churchmap.vercel.app/` immediately redirects to
`/?city=San+Mateo&state=CA` via an `ipapi.co` call fired from
[Search.jsx:165](frontend/src/pages/Search.jsx#L165). The app has exactly two
routes ([main.jsx](frontend/src/main.jsx)): `/` and `/church/:id`.

A first-time visitor never sees a sentence explaining what ChurchMap is, what the
six dimensions mean, where the data comes from, or why they should trust it. They
see a map and sixteen cards that all read `— (0 reviews)`.

The entire page contains **one link** (the wordmark). No footer, no about, no
methodology, no contact, no privacy.

### 2.2 The default experience is an empty product

The IP-detected city was San Mateo, CA. All 16 results: no rating, no reviews, no
extracted content, no tags. That is the honest state of 96% of the corpus, and it
is what an unlucky first-time visitor gets as their entire first impression.

### 2.3 Mobile is broken, in a product called ChurchMap

At a 390px viewport the map renders at **width 0**. It is not collapsed or
stacked — it is absent.

Cause, [index.css:87-98](frontend/src/index.css#L87-L98):

```css
.list-panel { width: 420px; flex-shrink: 0; }
.map-panel  { flex: 1; }
```

The list panel is fixed at 420px and refuses to shrink, so in a 390px viewport it
consumes the full width (clipping card content by ~30px, with no horizontal
scroll to recover it) and leaves `flex: 1` with zero space.

There is exactly **one layout media query in 837 lines of CSS**
([index.css:399](frontend/src/index.css#L399)), and it governs `.about-blocks`,
not the page layout. At 768px the map gets 348px — cramped but alive.

Church discovery is overwhelmingly a phone activity. This is the highest-severity
defect in the product.

### 2.4 Every review is seed data

Brooklyn church IDs 1–7 are the only churches in the product with any reviews —
32 in total. Chicago, Houston and Seattle: **0 reviews across 547 churches.**

Worse, those seed rows sort to the top of the demo city and are the only cards
that look "complete," so the best-presented results are fabricated. Opening
Brooklyn Tabernacle shows ten reviews dated `3/22/2026`, several with empty text
and one whose entire content is `test`.

Any landing page claiming community ratings is, today, claiming these.

### 2.5 The real data is buried

Of 50 Brooklyn cards loaded on the first page, **1** shows the "From their
website" row (14 of 200 have summaries). The default sort returns `0` —
i.e. API order — with no ranking by data richness
([Search.jsx:206-215](frontend/src/pages/Search.jsx#L206-L215)).

So PR #27's enriched-card treatment shipped correctly and is nearly invisible in
practice, because nothing sorts enriched churches toward the user.

Name search has the same problem: "Best match" for `Gospel Tabernacle` returns
Abilene, Asheboro, Beaumont, Belmont, Berea… — alphabetical by city. The Brooklyn
one, the only result with an extracted profile, is sixth, behind five visually
identical blank cards.

### 2.6 Zero SEO

| | |
|---|---|
| `<title>` | `ChurchMap — Find Your Church` on **every** page, including `/church/:id` |
| meta description | none |
| Open Graph tags | none |
| Twitter card | none |
| canonical | none |
| favicon | `/vite.svg` — the default Vite logo |
| rendering | client-side SPA, no prerender |

4,332 genuinely useful church profiles exist and **not one is indexable or
shareable**. Sharing a church to WhatsApp or iMessage produces a naked URL with
no title, image or description. For a discovery product this is the single
largest growth miss, and it is largely mechanical to fix.

### 2.7 Backend defect: `theology_summary` is cut mid-word

[extract.py:250](backend/scrapers_v2/extract.py#L250) hard-clamps to 240
characters:

```python
"theology_summary": _clamp(obj.get("theology_summary"), 240),
```

The prompt asks for 60–200 chars; when the model overshoots, `_clamp`
guillotines mid-word with no ellipsis. Live example, church 113184:

> …Divine healing and the baptism of the Holy Spirit with speaking in tongues are also **cent**

Measured in Chicago: 2 of 47 theology summaries hit exactly 240 and are cut
mid-word. Low frequency, but it lands on the most trust-sensitive block on the
page — the one that says "From this church's website."

### 2.8 Design system violations

- **Default blue Leaflet pin on `/church/:id`.** DESIGN.md: "Custom SVG teardrop
  pins — never use default Leaflet blue markers." The search map uses correct
  sienna pins; the detail page does not.
- **The most common accent color in the product is violet.** `baptist: '#7C3AED'`
  ([ChurchCard.jsx:4](frontend/src/components/ChurchCard.jsx#L4)) is a violet, and
  Baptist is the largest denomination in the corpus. DESIGN.md's denomination
  table specifies it while DESIGN.md's own "Do Not" list bans purple and the
  aesthetic direction says "Not a purple tech startup." The design system
  contradicts itself and should be resolved deliberately.
- **`.about-blocks` renders half-width with dead space** when only one of its two
  grid columns has data — visible on church 113184, where "What they teach" sits
  in a narrow column beside an empty half.
- **Raw emoji as UI icons** (📍 ★ 💬) against a design direction of "typography
  and color do all the work."

### 2.9 Convention violation: no API client

CLAUDE.md states: "Frontend API calls go through a single client module; don't
`fetch` directly from components." There are **12 direct `fetch()` calls** across
five files, plus a third-party call to `ipapi.co` fired straight from
`Search.jsx`. There is no client module at all.

---

## 3. The strategic problem

The product has two stories. Only one of them is true today.

| | Story | Backed by |
|---|---|---|
| Told now | "Churches rated by the community on six dimensions" | 32 seed reviews on 7 fixture churches |
| Actually true | "We read the church's own website so you know what a Sunday is like before you show up" | 4,332 real extracted profiles |

The site leads with the first and hides the second. That is backwards, and it is
the root cause of most of what §2 lists: the empty default city, the blank cards,
the buried enriched results, the credibility risk of a review that says `test`.

**The revamp's organizing principle: lead with what we actually have.**

The website-extraction story is also the more defensible one. Anyone can build a
review site and wait for reviews that may never come (cold-start is brutal for
local discovery). Almost nobody reads 8,500 church websites with an LLM and
publishes verbatim-validated summaries. That is the moat, it already works, and
it is currently invisible above the fold.

The six-dimension review system stays — as the **second** act, an invitation
rather than a headline. It is what the product grows into once it has traffic.

---

## 4. The landing page

### 4.1 Routing decision

Move search to `/search`; make `/` a real landing page.

This directly conflicts with the wordmark-as-home behavior shipped in #28
(wordmark resets to default location discovery). Resolution:

- Wordmark → `/` (the landing page). Standard, and what users expect.
- The "reset to my location" action becomes an explicit control **inside** search
  (e.g. "Near me" beside the search inputs), not an overloaded logo click.
- Returning visitors (a stored last search in `localStorage`) get a
  **"Continue in {city} →"** button at the top of the landing page, so the extra
  click costs them nothing.

`/` must stay static and prerenderable — it is the SEO entry point and must not
depend on an `ipapi.co` round trip to render.

### 4.2 Content, in order

1. **Hero.** The honest claim, in Fraunces:
   > **Know what a Sunday is actually like — before you walk in.**
   > We read what churches say about themselves, so you don't have to click
   > through twelve websites.

   Primary action: a single search field ("Find churches in…"), defaulted to the
   detected city but not blocking render. Secondary: "Or browse a city we've read
   thoroughly →".

2. **Show, don't claim.** Immediately below the fold, **one real extracted
   profile rendered inline** — pull quote, vibe pills, what-they-teach, service
   languages, sourced to the church's own site. Pick from the highest-confidence
   extractions. This is the product's best artifact and it should be the first
   concrete thing a visitor sees.

3. **How it works — three steps, honest about provenance.** Search a city → read
   what we found on their site → see community ratings where they exist. Name the
   verbatim-snippet validation; it's the strongest trust signal we have and it is
   currently invisible ([TODOS.md](TODOS.md) F6).

4. **Coverage, stated plainly.** One sentence, driven live from `/api/stats`:
   > We've read **4,332** church websites so far, out of **133,939** churches we
   > know about. We're adding more every day.

   This is TODOS.md's F4 promoted to the landing page. Disclosing the limit is
   what makes the rest of the page believable, and it converts the product's
   biggest weakness into evidence of an honest, working system. It also gives the
   pipeline a public heartbeat, which is the "somewhere a human actually looks"
   that TODOS.md asks for.

5. **The six dimensions — as the invitation.** Explain what they are and ask for
   the first review. Do not present them as an existing corpus of community
   wisdom.

6. **Footer.** About, methodology/how we read websites, data sources (IRS 990,
   OpenStreetMap, Google Places), a link to `/status`, contact, privacy. Any one
   of these is more credibility than the current zero links.

### 4.3 Explicitly not on the landing page

No stock photography of church interiors (DESIGN.md: no generic stock-photo
heroes, and data is the hero). No fabricated testimonials. No "trusted by N
churches." No operator metrics — `pipeline_ok`, `attempts`, `stale` belong on
`/status`, not in the product UI.

---

## 5. Frontend workstreams

Ordered by payoff per unit of risk. W1–W3 are independent of coverage; W5–W6
should follow it.

### W1. Make mobile work — *highest severity*

Add a real responsive layout below ~840px: list and map as switchable views
(segmented control, list default), `.list-panel` width `min(420px, 100%)`, and a
map that gets real dimensions when shown. Verify at 390px that the map is
non-zero and no card is clipped.

Touches layout only. No API, auth or schema involvement.

### W2. SEO and shareability — *highest leverage, mostly mechanical*

- Per-page `<title>` and `<meta name="description">` for `/church/:id`.
- Open Graph + Twitter card tags. A church share should read
  *"Grace Lutheran Church — Brooklyn, NY | ChurchMap"* with the summary as
  description.
- Replace the Vite favicon with a real mark.
- `<link rel="canonical">`.
- **Prerendering.** A client-only SPA cannot be indexed usefully. Options in
  increasing order of effort: `vite-plugin-ssg` / prerender for the landing page
  plus top-N city pages; or static generation for the ~4,332 churches that have
  extracted content (only those — thin pages hurt more than they help).
- `JSON-LD` (`schema.org/Church`) on detail pages.

Start with meta tags and the landing page prerender; treat per-church static
generation as a follow-up sized against the coverage number.

### W3. Landing page

Per §4. New route, static, prerendered. Includes the routing change and the
`localStorage` "continue" affordance.

### W4. Honest empty states and the seed-review problem

- **Decide what to do about IDs 1–7.** Either remove the seeded reviews, or label
  them unmistakably as sample data. Shipping a landing page that talks about
  community ratings while the flagship church shows a review reading `test` is a
  credibility risk that compounds with every new visitor. Recommend removal, with
  the dimension-bar UI demonstrated on the landing page instead.
- **Distinguish "no such church" from "we haven't read this one yet"**
  (TODOS.md F4). A card with no data should say so; an empty result set should
  say how much of that city has been read.
- Replace `— (0 reviews)` with something that doesn't read as a failed load.

### W5. Rank by usefulness

Sort enriched churches toward the top by default so PR #27's work is visible, and
make "Best match" in name search mean relevance-then-richness rather than
alphabetical-by-city. This is a small change with a large perceived-quality
effect: it is the difference between "1 of 50 cards has content" and "the first
several do."

Do this *before* filters (W6) — it improves the sparse-data experience without
promising precision the data can't support.

### W6. Filters over the whole city (TODOS.md F3)

Move filter state into the URL and refetch server-side, so filters run over the
city rather than the loaded page. Unchanged from TODOS.md, including its
sequencing note: **after** coverage and honest empty states, because precise
filters over 4% coverage mostly manufacture confident-looking empty results.

### W7. Design-system cleanup

Fix the blue Leaflet pin on `/church/:id`; resolve the violet-Baptist
contradiction in DESIGN.md and the code; fix `.about-blocks` collapsing to
half-width with one populated block; replace emoji icons with inline SVG.

### W8. Extract an API client

One module, per the CLAUDE.md convention, consolidating the 12 scattered
`fetch()` calls and the `ipapi.co` call. Do this as the *first* step of whichever
workstream touches data fetching, not as a standalone refactor — CLAUDE.md
prohibits broad refactors that aren't requested.

### W9. Backend: fix the mid-word clamp

`_clamp` should trim at a sentence or word boundary and append an ellipsis, or
the field should be regenerated. Note the guardrail: this is `extract.py`, not
the prompt, so it does **not** invalidate the eval baselines — but it only
affects rows written after deploy unless they're re-extracted.

---

## 6. Sequencing

**Phase 1 — Stop the bleeding (no new surface area).**
W1 mobile, W9 clamp fix, W7 design violations. Everything here is a defect in
something already shipped.

**Phase 2 — Make the good data findable.**
W2 SEO/meta, W5 ranking, W4 empty states + the seed-review decision. After this,
the product's real asset is both visible in-app and reachable from search and
shared links.

**Phase 3 — The landing page.**
W3, on the foundation of Phases 1–2. Building it earlier means driving traffic to
a site that's broken on phones and shows fixture reviews.

**Phase 4 — Depth.**
W6 filters, per-church prerendering, and TODOS.md F6 (confidence/provenance),
each gated on coverage having actually improved.

Running in parallel, unblocked: the backfill runbook in TODOS.md, and the
demand-driven fetch priority so Seattle (0 of 64 extracted) stops being empty
while Chicago is saturated.

---

## 7. Risks and open decisions

**Decisions this plan makes that deserve an explicit yes/no:**

1. **Lead with website extraction, not community ratings.** The biggest call
   here. It reframes the product's headline promise. It is right because it's the
   only claim currently backed by data — but it is a positioning change, not just
   copy.
2. **Move search off `/`.** Costs returning users a click (mitigated by
   "Continue in {city}") and partially reverses #28's wordmark behavior. Bought
   with an indexable, prerenderable entry point.
3. **Remove or label the seeded reviews.** Removing them makes the product look
   emptier in the short term and makes the demo city less impressive. It also
   removes a review that says `test` from the flagship church.

**Risks:**

- **Prerendering adds build complexity** to a currently trivial Vercel SPA
  deploy. Scope it to the landing page and city pages first; per-church static
  generation is a separate decision sized against coverage.
- **Publishing a coverage number is a commitment.** If the backfill stalls, the
  number stalls publicly. That is the point — it's the same argument STATUS.md
  makes for `/api/stats` — but it should be a conscious choice.
- **Ranking by data richness biases discovery** toward churches with good
  websites, which correlates with size and budget. A small church with no site
  becomes less findable. Worth naming now; mitigate by keeping distance and name
  search as first-class paths that ignore richness entirely.

**Out of scope**, per CLAUDE.md guardrails: auth changes, re-running Google
Places enrichment, touching `backend/scrapers/` (v1), and any schema change made
as a side effect of UI work.
