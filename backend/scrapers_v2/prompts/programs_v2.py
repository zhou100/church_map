"""Children's, youth and childcare program extraction prompt, v2.

v1 told the model to skip adult groups, appeals and the like, and it listed
them anyway: in two random samples of 200 churches (2026-11-24), 16% and 19%
of the kept programs were wrong, mostly outreach to children elsewhere,
parenting tips, adult and senior groups, ceremonies, volunteer roles and
pages about another congregation. v2 makes the model classify every passage
it lists (`category`) and backend/scrapers_v2/programs.py keeps only
"program"; and it names the church, so the model can tell another
congregation's or another location's page from this one's.

Bump PROMPT_VERSION whenever the prompt or schema changes. A bump does not
re-queue anything: church_program_extractions only goes due again when a
church's archived page set changes.

The model only proposes. programs.py keeps a program only if its excerpt is
found verbatim, exactly once, in the page it names, and keeps a type or age
band only if the words carry it.
"""
from __future__ import annotations

PROMPT_VERSION = "2026-11-24.programs.v2"

# Same model as website_v3; it is recorded on every row and extraction.
MODEL = "google/gemini-2.5-flash-lite"

PROGRAM_TYPES = {"during_service", "weekday_care", "other"}
AGE_BANDS = {"preschool", "children", "youth", "young_adult"}
# What a listed passage is. Only "program" is kept.
CATEGORIES = {"program", "outreach", "adult", "ceremony", "advice", "volunteer_or_staff",
              "not_running", "one_time_event", "other_location", "other"}

SYSTEM_PROMPT = """You read pages from one church's website. A family is deciding whether to visit
this church with their children. List the passages that mention babies, children, teenagers
or young adults, and say for each one whether it is a program this church runs that their
child could join. Output one JSON object and nothing else.

The input starts with "=== CHURCH === <name> | <city>, <state> | <street>". Each page then
starts with a line "=== PAGE <n> (<kind>) <url> ===".

Return:
{
  "programs": [
    {
      "page": <n of the page the excerpt is copied from>,
      "excerpt": "<copied exactly from that page: 40-300 characters that state this>",
      "category": "program" | "outreach" | "adult" | "ceremony" | "advice" | "volunteer_or_staff"
                  | "not_running" | "one_time_event" | "other_location" | "other",
      "name": "<program name as written, or null>",
      "type": "during_service" | "weekday_care" | "other" | null,
      "age_bands": [zero or more of "preschool", "children", "youth", "young_adult"],
      "ages_stated": "<ages, grades or months exactly as written, or null>",
      "schedule_stated": "<day/time exactly as written, or null>",
      "campus_stated": "<campus or location name if the page ties the program to one, or null>"
    }
  ]
}

category:
- "program": a regular class, group, service or care that THIS church runs for babies,
  children, teens or young adults, and that a visiting family's child could attend: nursery,
  children's church, Sunday school with children's classes, kids or youth group, AWANA,
  VBS, preschool or daycare the church runs, confirmation or first communion classes.
- "outreach": help for children somewhere else: donations, toy or food drives, school
  partnerships, foster care, missions, camps or groups run by other organizations, links to
  outside websites.
- "adult": for adults, parents, couples or seniors, even if named "Kids" or "Youth"
  ("Yesterday's Kids" for ages 60+), and Sunday school or Bible study for adults only.
- "ceremony": a one-time rite for a family: baby dedication or blessing, baptism, a baby
  shower.
- "advice": tips for parents, such as how children can take part in worship, or what to
  bring.
- "volunteer_or_staff": a job, volunteer role, committee, staff name, title or office, a
  form or permission slip, a sign-up button.
- "not_running": the page says it is paused, postponed, on hold, cancelled, full, not
  offered at this time, or "no ... this summer".
- "one_time_event": a single dated event or announcement (a date like "June 7", "March 21,
  2026"), a sermon or recording, a testimonial or quote, a holiday service.
- "other_location": the page lists several campuses or locations and this passage is about
  one that is not the church named at the top; or the whole site is another congregation
  (a different name or town than the church at the top), or a denomination or diocese
  describing its congregations in general ("in most of our congregations").
- "other": a slogan, mission statement or general sentence ("from kids to seniors, there is
  a place for you") that names no program.
When unsure whether something is a "program", choose another category.

Rules for every passage:
- Only list what the page states. If you are unsure of a field, leave it null or empty.
- excerpt must be a contiguous copy of the page text: same words, same spelling, same order.
  Do not join text from separate places. Include the program name and its ages or schedule
  when they are next to each other.
- type:
  - "during_service": care or classes while adults worship (nursery during the service, kids
    church, Sunday school held at the same time as worship). Not classes held before or after
    the service.
  - "weekday_care": childcare or education on weekdays: preschool, daycare, early learning
    center, Mother's Day Out, after-school care, a school the church runs.
  - "other": everything else for these ages: Sunday school before or after worship, midweek
    clubs, youth group meetings, VBS, camps, retreats, confirmation, religious education.
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
- If no passage mentions these ages, return {"programs": []}.
"""
