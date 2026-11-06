"""Children's, youth and childcare program extraction prompt, v1.

Separate from website_v3 so its baseline, cache and PROMPT_VERSION are not
touched (docs/plans/crawler_visit_facts_plan.md, PR 4). Bump PROMPT_VERSION
whenever the prompt or schema changes. A bump does not re-queue anything:
church_program_extractions only goes due again when a church's archived page
set changes.

The model only proposes. backend/scrapers_v2/programs.py keeps a program only
if its excerpt is found verbatim, exactly once, in the page it names, and keeps
a type or age band only if that excerpt (or the stated name, ages and schedule)
carries words for it. So the prompt asks for long verbatim excerpts and blanks,
never guesses.
"""
from __future__ import annotations

PROMPT_VERSION = "2026-11-04.programs.v1"

# Same model as website_v3; it is recorded on every row and extraction.
MODEL = "google/gemini-2.5-flash-lite"

PROGRAM_TYPES = {"during_service", "weekday_care", "other"}
AGE_BANDS = {"preschool", "children", "youth", "young_adult"}

SYSTEM_PROMPT = """You read pages from one church's website and list the programs it offers
for babies, children, teenagers and young adults. Output one JSON object and nothing else.

Each page in the input starts with a line "=== PAGE <n> (<kind>) <url> ===".

Return:
{
  "programs": [
    {
      "page": <n of the page the excerpt is copied from>,
      "excerpt": "<copied exactly from that page: 40-300 characters that state this program>",
      "name": "<program name as written, or null>",
      "type": "during_service" | "weekday_care" | "other" | null,
      "age_bands": [zero or more of "preschool", "children", "youth", "young_adult"],
      "ages_stated": "<ages, grades or months exactly as written, or null>",
      "schedule_stated": "<day/time exactly as written, or null>",
      "campus_stated": "<campus or location name if the page ties the program to one, or null>"
    }
  ]
}

Rules:
- Only list what the page states. If you are unsure, leave the field null or the list empty.
- excerpt must be a contiguous copy of the page text: same words, same spelling, same order.
  Do not join text from separate places. Include the program name and its ages or schedule
  when they are next to each other.
- type:
  - "during_service": care or classes while adults worship, or Sunday school / children's church
    at the Sunday gathering (nursery during the service, kids church, Sunday school).
  - "weekday_care": childcare or education on weekdays: preschool, daycare, early learning center,
    Mother's Day Out, after-school care, a school the church runs.
  - "other": everything else for these ages: midweek clubs (e.g. AWANA), youth group meetings,
    VBS, camps, retreats, confirmation, religious education, special-needs ministry.
  - null if the page does not say when it meets or what kind of program it is.
- age_bands, only from words on the page:
  - "preschool": ages 0-5, months, nursery, infants, babies, toddlers, preschool, pre-K, TK.
  - "children": kindergarten to 5th grade, elementary, ages about 5-11.
  - "youth": grades 6-12, middle school, junior high, high school, teens, youth group.
  - "young_adult": college, university, young adults, 18-30s. Never put a college or
    young-adult group in "youth".
  - A program called only "Kids" or "Children's Ministry" with no ages or grades gets [].
- Do not guess ages from the program name alone unless the name itself is an age word
  (e.g. "Nursery", "Middle School Ministry", "Preschool").
- Skip adult-only groups, staff bios, donation appeals and job postings.
- Skip events whose dates have clearly passed.
- If there are no such programs, return {"programs": []}.
"""
