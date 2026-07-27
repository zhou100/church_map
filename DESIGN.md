# Design System — HolyHub

## Product Context
- **What this is:** Church discovery and community ratings platform — find a church by location, culture, language, and what actually matters (worship energy, community warmth, sermon depth, etc.)
- **Who it's for:** People new to a city, people switching churches, people seeking a culturally-specific congregation
- **Space/industry:** Local discovery / community directory (peers: Airbnb, Yelp, Nextdoor — not ChurchFinder)
- **Project type:** Web app with split-pane map+list search, and enriched detail pages

## Design Principle
**Data-first, not photo-first.** Every local discovery competitor (Airbnb, Nextdoor, Yelp) bets on photography. Churches mostly don't have professional photos. HolyHub's competitive advantage is data richness — dimension ratings, cultural tags, Google enrichment, community reviews. The design makes data look beautiful rather than hiding behind photo placeholders.

## Aesthetic Direction
- **Direction:** Warm Humanist Editorial — trusted local publication meets community board. Substack meets a well-designed church bulletin.
- **Decoration level:** Minimal — typography and color do all the work. No patterns, no textures, no shadows-for-shadows-sake.
- **Mood:** Warm, trustworthy, grounded. Not a purple tech startup. Not religious iconography. Universally welcoming.
- **Reference sites:** Substack, Airbnb (layout discipline), Nextdoor (community warmth)

## Typography
- **Display / Church Names:** `Fraunces` (variable, optical-size aware serif) — unexpected in a directory, adds gravitas. Every other directory uses sans everywhere; a serif on the church name signals "this place has history and weight."
  - `font-optical-sizing: auto` — critical, lets the font adjust weight at different sizes
  - Use for: wordmark, church names in cards, church names on detail page, section headings (`h1`, `h2`)
- **Body / UI:** `Plus Jakarta Sans` — clean humanist sans, humanist stroke endings, great readability at small sizes. Not overused.
  - Use for: all body copy, labels, tags, buttons, inputs, meta text
- **Loading:** Google Fonts CDN
  ```html
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  ```
- **Scale:**
  - `xs`: 11px / 0.69rem
  - `sm`: 12px / 0.75rem
  - `base`: 14–15px / 0.875–0.94rem
  - `md`: 16px / 1rem
  - `lg`: 20px / 1.25rem (section headings — use Fraunces)
  - `xl`: 26px / 1.625rem (detail page church name — Fraunces)
  - `2xl`: 36px / 2.25rem (wordmark — Fraunces)

## Color
- **Approach:** Restrained — sienna and gold are rare and meaningful. Color is earned.
- **Primary (Sienna):** `#8B5E3C` — warm earth tone, earthy and faith-community-coded. Used for: primary buttons, active state, map pins, left-border card accents, links.
  - Dark variant: `#6B4529` (hover states)
  - Light variant: `#C4875A` (subtle tints)
- **Accent (Gold):** `#D4A853` — stained glass, candlelight, quality. Used for: star ratings, active map pin (hovered), dimension bar fill gradient endpoint, CTA for directions.
  - Light variant: `#F0CC80`
- **Background:** `#F7F4F0` — warm off-white. Keep. It's lovely and unusual (not #FFFFFF, not #F9FAFB).
- **Surface:** `#FFFFFF` — cards, modals, inputs
- **Warm surface:** `#EDE9E2` — secondary backgrounds, filter bar, tag hover states
- **Text:** `#1C1917` — warm near-black (slight brown tint, not pure black)
- **Text secondary:** `#6B6560` — denomination, meta, labels
- **Text tertiary:** `#9C9590` — timestamps, placeholders
- **Border:** `#E4DED6` — warm gray border
- **Semantic:**
  - Success / Accessible: `#2D6A4F` (forest green) + `#D1FAE5` (bg)
  - Warning: `#D97706` + `#FEF3C7` (bg)
  - Error: `#DC2626` + `#FEE2E2` (bg)
- **Dark mode:** Shift all surfaces to warm darks (`#1A1714`, `#231F1B`, `#2A2520`). Reduce sienna saturation slightly. Gold stays vivid.

## Tags & Pills
Four distinct types — never mix styles:
- **Quality tags** (Vibrant worship, Deep sermons, etc.): `background: #EEE8F0; color: #5B3E7A` — subtle purple tint signals "community rating"
- **Language tags** (Spanish, Korean, etc.): `background: #FEF3C7; color: #92400E` — amber/warm, non-English indicator
- **Culture tags** (Hispanic/Latino, African American, etc.): `background: #D1FAE5; color: #2D6A4F` — green, community identity
- **Website-extracted tags:** white background, sienna text/border — only inside
  a warm-surface block labeled "From this church's website." This source line
  is required so machine-read claims never look like community consensus. On
  compact result cards, abbreviate the label to "From their website" and show
  at most two extracted tags.
- **Active/selected:** `background: #8B5E3C; color: white`

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable — not cramped, not bloated
- **Scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64px

## Layout
- **Approach:** Grid-disciplined with editorial touches on detail pages
- **Search page:** Full-viewport split-pane — list panel (380px fixed) + map panel (flex: 1). No page scroll — each panel scrolls independently.
- **List panel cards:** Horizontal row layout (not grid) — left accent border (4–5px, denomination-coded) + body. No photo placeholder. Data is the hero.
- **Detail page:** Max-width 720px, centered. Map strip at top (180–220px), content below.
- **Border radius:** `sm: 6px` / `md: 10px` / `lg: 16px` / `full: 9999px`
- **Card left-border accent (denomination coding):**
  - Baptist: `#7C3AED`
  - Catholic: `#1D4ED8`
  - Episcopal / Anglican: `#B45309`
  - Methodist: `#0891B2`
  - Non-denominational / default: `#8B5E3C` (sienna)
  - Spanish/Latino churches: `#B45309` (warm amber)

## Map Pins
Custom SVG teardrop pins — never use default Leaflet blue markers.
- **Default:** Sienna `#8B5E3C` body, white inner circle
- **Hovered/Active:** Gold `#D4A853` body, white inner circle, scale 1.3×
- Implementation: `L.divIcon` with inline SVG

## Motion
- **Approach:** Minimal-functional — only transitions that aid comprehension
- **Card hover:** `box-shadow` transition 0.2s ease, `translateY(-1px)`
- **Active card highlight:** `box-shadow: 0 0 0 2px #8B5E3C` (sienna ring, no animation)
- **Pin hover:** `fill` color transition 0.15s, scale via CSS transform 0.15s
- **Page transitions:** none — fast navigation is better than fancy transitions for a directory

## Dimension Bars
The bars are a primary data feature — make them visible and beautiful.
- Height: 6px (not 3–4px — too thin to read)
- Background: `#EDE9E2` (warm surface)
- Fill: linear-gradient `#8B5E3C` → `#D4A853` (sienna to gold)
- Border-radius: full (pill shape)
- Value label: sienna, tabular-nums, bold

## Do Not
- Use purple/violet (#6c63ff) anywhere — this was the old primary color, now retired
- Use gradient boxes as church photo placeholders — use the left-border accent instead
- Center everything uniformly — vary alignment for visual interest
- Use Inter, Roboto, or Poppins as fonts
- Use drop shadows on cards unless on hover state
- Use generic stock-photo hero sections

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-23 | Fraunces serif for church names | Distinctive — no directory does this. Signals gravitas and tradition. |
| 2026-03-23 | Sienna + gold palette (retire purple) | Earthy, faith-community-coded, unclaimed in the discovery space |
| 2026-03-23 | Left-border accent, no photo placeholders | Data-first principle — HolyHub's advantage is richness of data, not photos |
| 2026-03-23 | Split-pane as primary layout (no toggle) | Google Maps pattern — list and map always co-visible, synced on hover |
| 2026-03-23 | Plus Jakarta Sans for body | Humanist, warm, readable — not overused |
| 2026-07-27 | Label machine-extracted website content at the section level | Keeps crawled claims distinct from community ratings without adding per-pill clutter |
| 2026-07-27 | Identify website-enriched churches on result cards | Users need to know which cards open into richer detail; a compact sourced row preserves that signal without implying community consensus |
