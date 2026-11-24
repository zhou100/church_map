"""Programs stage: children's, youth and childcare programs from archived pages.

Reads the pages fetch archived for a church (kids, youth, childcare and the
website_v3 pages that often carry the same links), asks the model which
programs they state, and keeps only what the archive itself supports
(docs/plans/crawler_visit_facts_plan.md, PR 4 and appendix A):

  * the site must be tied to this church record (site_is_this_church): not a
    denomination site shared by many records, and naming this church; if not,
    no model call is made and nothing is shown;
  * the excerpt must occur verbatim, exactly once, in the text of the page it
    names; offsets are computed here, never taken from the model;
  * name, ages and schedule must each occur inside that excerpt;
  * the program's own list item must carry a kids word or stated ages, and a
    type or age band survives only if the words carry it (nursery, "grades
    6-12", "during the service", preschool, ...); a program named only "Kids"
    keeps no age band;
  * young adults stay a separate band, so a college group is never a youth group;
  * programs tied to another campus, whose stated year has passed, that sit
    under a calendar date (one event, not a standing program) or that are
    stated as paused are dropped.

The rules come from the 2026-11-23 pilot, where 7 of 13 kept programs were
wrong; tests/scrapers_v2/test_programs.py keeps each failure as a case.

The stage never touches raw_crawl_artifacts.extract_status, so it cannot
enqueue or starve website_v3. Its own state is church_program_extractions: a
church is due when the set of archived pages it would read differs from the
set last read. An unchanged re-fetch keeps its artifact id, so it creates no
work; a changed page is a new artifact and does. Calls cost money, so the stage
runs only from scripts/extract_programs.py with --apply and a bounded limit.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

import httpx
from lxml import html as lxml_html

from backend.db.repository import ProgramRepository
from backend.scrapers_v2 import r2 as r2mod
from backend.scrapers_v2.extract import (
    HTTP_TIMEOUT_S,
    ExtractionError,
    TransientExtractionError,
    call_llm,
)
from backend.scrapers_v2.prompts.programs_v1 import (
    AGE_BANDS,
    MODEL,
    PROGRAM_TYPES,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)

# Recorded on every row: the prompt that proposed a program and the version of
# the checks below that kept it. Bump CHECKS_VERSION when a rule changes.
CHECKS_VERSION = "checks.v3"
EXTRACTOR_VERSION = f"{PROMPT_VERSION}+{CHECKS_VERSION}"

MAX_PAGE_CHARS = 8_000
MAX_INPUT_CHARS = 24_000
MIN_EXCERPT_CHARS = 20
MAX_EXCERPT_CHARS = 600
MAX_PROGRAMS = 25

# ----- page text --------------------------------------------------------------

_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "head", "iframe")
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "option", "p", "section", "table",
    "td", "th", "tr", "ul",
}
_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "​": None, "‌": None, "‍": None, "﻿": None, "­": None,
})
_SPACES = re.compile(r"[^\S\n]+")
# Characters XML forbids. lxml parses HTML containing them but refuses to set
# them as element text, so one such page (a stray form feed or NUL) would stop
# the whole batch. They carry no words; a space keeps the words apart.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def normalize_text(text: str) -> str:
    """NFKC, straight quotes and hyphens, one space between words, one line
    per block. The same rules apply to the page and to the model's excerpt."""
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def page_text(raw: bytes) -> str:
    """Every visible word of the archived HTML, footer and navigation included
    (an address or "Nursery available" often sits there), not trafilatura's
    article text. Program offsets refer to this string."""
    try:
        doc = lxml_html.document_fromstring(_NOT_XML.sub(" ", raw.decode("utf-8", errors="replace")))
    except Exception:
        return ""
    for el in [e for e in doc.iter(*_DROP_TAGS)]:
        el.drop_tree()
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in _BLOCK_TAGS:
            el.tail = "\n" + (el.tail or "")
            if el.tag.lower() != "br":
                el.text = "\n" + (el.text or "")
    return normalize_text(doc.text_content())


def locate(excerpt: str, text: str) -> tuple[int, int] | None | str:
    """(start, end) of the excerpt's only occurrence in `text`, matching across
    line breaks; 'ambiguous' when it occurs more than once; None when absent.
    Exact case first; then case-insensitive where lowering keeps offsets."""
    needle = normalize_text(excerpt).replace("\n", " ")
    if not needle:
        return None
    hay = text.replace("\n", " ")  # same length, so offsets carry over
    candidates = [(hay, needle)]
    lowered = hay.lower()
    if len(lowered) == len(hay):
        candidates.append((lowered, needle.lower()))
    for h, n in candidates:
        count = h.count(n)
        if count == 1:
            start = h.find(n)
            return start, start + len(n)
        if count > 1:
            return "ambiguous"
    return None


def _contains(part: str | None, excerpt: str) -> str | None:
    """The model's stated field, if it is really inside the excerpt."""
    if not isinstance(part, str):
        return None
    value = normalize_text(part).replace("\n", " ")
    if not value or value.lower() not in excerpt.lower():
        return None
    return value[:200]


# ----- what the words support ----------------------------------------------------

# Any word that makes a passage about babies, children, teens or young adults.
_KIDS_WORDS = re.compile(
    r"\b(kids?|kidz|child|children'?s?|childcare|youth|teens?|teenagers?|students?|nursery|"
    r"infants?|babies|baby|toddlers?|pre-?school(?:ers?)?|pre-?k|tk|kindergarten|elementary|"
    r"middle school|junior high|jr\.? high|high school|grades?|\d{1,2}(?:st|nd|rd|th) grade|"
    r"sunday school|vbs|vacation bible school|awana|young adults?|college|"
    r"mother'?s day out|parents'? day out|daycare|day care|early learning|confirmation|"
    r"religious education|faith formation|ccd)\b",
    re.I,
)

_RANGE = r"\s*(?:-|to|through|thru)\s*"
_ORD = r"(?:st|nd|rd|th)?"
_AGE_RANGE = re.compile(rf"\b(?:ages?|aged)\s*(\d{{1,2}}){_RANGE}(\d{{1,2}})\b", re.I)
_AGE_RANGE_YEARS = re.compile(rf"\b(\d{{1,2}}){_RANGE}(\d{{1,2}})\s*(?:years?|yrs?|y/?o)\b", re.I)
_AGE_UP = re.compile(r"\b(?:ages?)\s*(\d{1,2})\s*(?:\+|and up|and older)", re.I)
_BIRTH_TO = re.compile(rf"\b(?:birth|newborns?|infants?|babies){_RANGE}(?:age\s*)?(\d{{1,2}})\b", re.I)
_MONTHS = re.compile(rf"\b\d{{1,2}}(?:{_RANGE}\d{{1,2}})?\s*(?:months?|mos?\.?)\b", re.I)
_GRADE_LEVEL = r"(k|tk|pre-?k|kindergarten|\d{1,2})"
_GRADE_RANGE = re.compile(
    rf"\b(?:grades?\s*{_GRADE_LEVEL}{_ORD}{_RANGE}{_GRADE_LEVEL}{_ORD}"
    rf"|{_GRADE_LEVEL}{_ORD}{_RANGE}{_GRADE_LEVEL}{_ORD}\s*grades?)\b",
    re.I,
)
_ONE_GRADE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s*grade(?:rs?)?\b", re.I)

_BAND_WORDS = {
    "preschool": re.compile(
        r"\b(nursery|infants?|babies|baby|toddlers?|pre-?school(?:ers?)?|pre-?k|pre-?kindergarten|"
        r"tk|transitional kindergarten|early childhood|little ones|cradle roll)\b", re.I),
    "children": re.compile(
        r"\b(?<!pre-)(?<!pre)(?<!transitional )(kindergarten|elementary|grade school)\b", re.I),
    "youth": re.compile(
        r"\b(youth|teens?|teenagers?|middle school(?:ers?)?|junior high|jr\.? high|high school(?:ers?)?|"
        r"sr\.? high|senior high)\b|(?<!college )(?<!university )(?<!grad )(?<!campus )\bstudents?\b", re.I),
    "young_adult": re.compile(
        r"\b(young adults?|college|university|collegiate|twenty-?somethings|20s)\b", re.I),
}


def _grade(value: str) -> int:
    v = value.lower().replace("-", "")
    if v in ("tk", "prek"):
        return -1
    if v in ("k", "kindergarten"):
        return 0
    return int(v)


def _bands_for_ages(lo: int, hi: int) -> set[str]:
    lo, hi = min(lo, hi), max(lo, hi)
    out = set()
    # Appendix A: 0-5 before kindergarten is preschool. Ages are approximate
    # at the edges, so a range claims a band only well inside it: "ages 2-5"
    # is preschool, "ages 5-11" is K-5th, and youth (6th-12th) needs 12+.
    if lo <= 4:
        out.add("preschool")
    if lo <= 10 and hi >= 6:
        out.add("children")
    if lo <= 17 and hi >= 12:
        out.add("youth")
    if lo >= 17 and hi >= 18:
        out.add("young_adult")
    return out


def _bands_for_grades(lo: int, hi: int) -> set[str]:
    lo, hi = min(lo, hi), max(lo, hi)
    out = set()
    if lo <= -1:
        out.add("preschool")
    if lo <= 5 and hi >= 0:
        out.add("children")
    if lo <= 12 and hi >= 6:
        out.add("youth")
    return out


def stated_age_bands(text: str) -> set[str]:
    """Bands that explicit ages, months or grades in `text` cover."""
    out: set[str] = set()
    for m in _AGE_RANGE.finditer(text):
        out |= _bands_for_ages(int(m.group(1)), int(m.group(2)))
    for m in _AGE_RANGE_YEARS.finditer(text):
        out |= _bands_for_ages(int(m.group(1)), int(m.group(2)))
    for m in _AGE_UP.finditer(text):
        out |= _bands_for_ages(int(m.group(1)), max(int(m.group(1)), 17))
    for m in _BIRTH_TO.finditer(text):
        out |= _bands_for_ages(0, int(m.group(1)))
    if _MONTHS.search(text):
        out.add("preschool")
    for m in _GRADE_RANGE.finditer(text):
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out |= _bands_for_grades(_grade(a), _grade(b))
    for m in _ONE_GRADE.finditer(text):
        out |= _bands_for_grades(int(m.group(1)), int(m.group(1)))
    return out


def supported_age_bands(text: str) -> set[str]:
    """Bands the words of `text` support: explicit ages or grades, or an age word."""
    out = stated_age_bands(text)
    for band, pattern in _BAND_WORDS.items():
        if pattern.search(text):
            out.add(band)
    return out


_TYPE_WORDS = {
    "during_service": re.compile(
        r"\bduring\b[^.;\n]{0,40}\b(services?|worship|mass|masses|liturgy|sermon|gatherings?)\b"
        r"|\bwhile\b[^.;\n]{0,30}\b(worship|attend|service)"
        r"|\b(?:at|for|in) (?:both|all|each|every|our|the) [^.;\n]{0,20}(services|masses)\b"
        r"|\bsunday school\b|\bchildren'?s church\b|\bkids'? church\b|\bchildren'?s (?:worship|chapel|liturgy)\b"
        r"|\bnursery\b(?! school)",
        re.I),
    "weekday_care": re.compile(
        r"\b(daycare|day care|child ?care cent(?:er|re)|child development cent(?:er|re)|"
        r"early learning|early education|mother'?s day out|mothers day out|parents'? day out|mdo|"
        r"after-? ?school|before and after school|nursery school|pre-?k program|"
        r"monday\s*(?:-|to|through|thru)\s*friday|weekdays|m-f|tuition|enroll(?:ment|ing)?|"
        r"(?:elementary|catholic|christian|lutheran|parish|parochial|day|montessori|episcopal) school|"
        r"academy)\b"
        r"|\bpre-?school\b(?!-?\s*(?:age|aged)\b)(?!ers?\b)",
        re.I),
    "other": re.compile(
        r"\b(awana|vbs|vacation bible school|camps?|retreats?|clubs?|confirmation|religious education|"
        r"ccd|faith formation|catechesis|catechism|special needs|youth group|youth night|bible study|"
        r"small groups?|fellowship|midweek|lock-?in|mission trips?|"
        r"(?:mon|tues|wednes|thurs|fri|satur)days?)\b",
        re.I),
}


def supports_type(program_type: str, text: str) -> bool:
    return bool(_TYPE_WORDS[program_type].search(text))


_YEAR = re.compile(r"\b(20\d\d)\b")
# A calendar date ("MAY 10", "Nov. 3", "10 June"): the excerpt is one dated
# occurrence, such as an "Upcoming Events" entry, not a standing program. A
# year is often missing, so the year check above cannot tell it is past
# (2026-11-23 pilot: a May 10 Mother's Day Sunday School, shown in November).
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DATE = re.compile(
    rf"\b{_MONTH}\.?\s+(?:[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?\b(?!\s*(?::|am\b|pm\b|\d))"
    rf"|\b(?:[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b",
    re.I)
# How far before the excerpt a date still heads it ("MAY\n10\nSUN\n" + entry).
_DATE_LOOKBACK = 40
# Under an events heading, every entry until the excerpt belongs to the date
# above it ("Upcoming Events / MAY 10 / ... / Youth Fellowship 1:00 PM").
_EVENTS_HEADING = re.compile(r"^(?:upcoming |coming |future )?(?:events|calendar|this week|happenings)\b",
                             re.I | re.M)
_EVENTS_LOOKBACK = 400
# An events list is short lines under each date. More lines than this, or a
# longer line, between the date and the excerpt means the list has ended
# (page text keeps no headings, so "Service Times" below it looks the same).
_EVENT_ENTRY_LINES = 8
_EVENT_ENTRY_CHARS = 60
# Stated as not running now.
_PAUSED = re.compile(
    r"\b(on (?:summer |winter )?break|on hiatus|suspended|cancell?ed|postponed|paused|"
    r"will resume|resumes? (?:in|on|this|next)|not meeting)\b", re.I)
# Separators between the items of a list ("Bible Study, Youth Group, Adventure Club").
_CLAUSE_BREAK = re.compile(r"[,;|•·\n]|\s(?:--|[-–—])\s")
# An aside that states ages right after a program's name: "Youth Group, grades 6-12".
_AGES_LEAD = re.compile(
    r"\(?\s*(?:for\s+)?(?:ages?\b|grades?\b|\d|birth\b|newborns?\b|infants?\b|toddlers?\b|"
    r"pre-?k\b|k\s*[-–]|kindergarten\b|elementary\b|middle\b|high school\b)", re.I)


def is_dated(text: str, start: int, end: int) -> bool:
    """A calendar date inside the excerpt, or just before it in the same block."""
    before = text[max(0, start - _DATE_LOOKBACK):start]
    before = re.split(r"[.!?]\s", before)[-1]
    if _DATE.search(before + "\n" + text[start:end]):
        return True
    window = text[max(0, start - _EVENTS_LOOKBACK):start]
    headings = list(_EVENTS_HEADING.finditer(window))
    if not headings:
        return False
    dates = list(_DATE.finditer(window, headings[-1].end()))
    if not dates:
        return False
    between = window[dates[-1].end():].split("\n")[1:-1]
    return len(between) <= _EVENT_ENTRY_LINES and all(len(line) <= _EVENT_ENTRY_CHARS for line in between)


def _clause_span(name: str | None, excerpt: str) -> tuple[int, int]:
    """Where the list item that names the program starts and ends in `excerpt`;
    the whole excerpt when there is no name or it is not found."""
    if not name:
        return 0, len(excerpt)
    at = excerpt.lower().find(name.lower())
    if at < 0:
        return 0, len(excerpt)
    cuts = [m.end() for m in _CLAUSE_BREAK.finditer(excerpt, 0, at)]
    nxt = _CLAUSE_BREAK.search(excerpt, at + len(name))
    return (cuts[-1] if cuts else 0), (nxt.start() if nxt else len(excerpt))


def own_clause(name: str | None, excerpt: str) -> str:
    """The list item of `excerpt` that names the program: a kids word elsewhere
    in the same list does not make "Adventure Club" a children's program."""
    a, b = _clause_span(name, excerpt)
    return excerpt[a:b]


def own_ages(name: str | None, ages: str | None, excerpt: str) -> str | None:
    """The stated ages, if they start in the program's own list item or in an
    aside that opens with ages right after it ("Youth Group, grades 6-12").
    2026-11-24 pilot: "... Young Adults, and College Campus Students -- lots to
    share for all ages" gave both groups "all ages", a phrase about the list."""
    if not ages:
        return None
    a, b = _clause_span(name, excerpt)
    end = b
    brk = _CLAUSE_BREAK.match(excerpt, b)
    if brk:
        after = _CLAUSE_BREAK.search(excerpt, brk.end())
        aside_end = after.start() if after else len(excerpt)
        if _AGES_LEAD.match(excerpt, brk.end()):
            end = aside_end
    flat, want = excerpt.replace("\n", " ").lower(), ages.lower()
    at = flat.find(want)
    while at >= 0:
        if a <= at < end:
            return ages
        at = flat.find(want, at + 1)
    return None


# Words that name no particular campus. Directions, "main", "downtown" and
# street names do tell campuses apart, so they are not in this list.
_CAMPUS_GENERIC = {"campus", "campuses", "church", "location", "site", "with", "from",
                   "kids", "children", "youth", "student", "students"}
# "Grace Church South Campus", "our North Campus": a campus the excerpt itself
# names, checked even when the model left campus_stated empty.
_CAMPUS_IN_TEXT = re.compile(r"\b(?:[A-Z][\w'’.-]*\s+){1,4}[Cc]ampus\b")


def _tokens(*values: str | None) -> set[str]:
    words: set[str] = set()
    for v in values:
        for w in re.findall(r"[a-z]{4,}", (v or "").lower()):
            if w not in _CAMPUS_GENERIC:
                words.add(w)
    return words


# ----- is this website this church's? ---------------------------------------------

# A website listed by this many church records or more is a denomination's or a
# directory's (jw.org, lds.org: 2026-11-23 pilot), not one congregation's.
SHARED_SITE_LIMIT = 10
# Name words that do not tell one congregation from another: church types,
# denominations (often abbreviated on the site: AME, SDA, UMC) and fillers.
_NAME_GENERIC = frozenset("""
    church churches the and saint saints iglesia parish parroquia congregation ministries
    ministry inc community fellowship chapel center centre temple assembly assemblies mission
    capilla baptist lutheran methodist episcopal african presbyterian pentecostal adventist
    seventh catholic roman christian apostolic evangelical orthodox greek congregational united
    reformed nazarene gospel full bible holy christ jesus lord lords first second third kingdom
    hall jehovah jehovahs witnesses latter missionary independent memorial evangelistic
    interdenominational nondenominational international worship family house street avenue
    road drive boulevard lane highway our his her new san los las del des god sts
    ame sda umc cogic pca lcms elca ucc coc upc fwb freewill brethren mennonite wesleyan
""".split())
# The 80 most frequent distinctive name words (as _identity_words returns
# them), each in at least 0.25% of the 134,377 church records on 2026-11-23.
# A name made only of these ("Mount Zion", "Grace") is shared by many
# congregations, so finding it on a site does not say which one the site is.
_COMMON_NAME_WORDS = frozenset("""
    mount grove hill zion pleasant creek bethel faith day hope john grace calvary trinity union
    paul spring life valley oak tabernacle mary free olive greater salem holiness rock ridge west
    antioch pine park bethlehem peter liberty jame north friendship view lake central little east
    primitive good old city bethany joseph shiloh lady macedonia south mark star pilgrim luke
    branch living emmanuel mountain river cedar covenant victory height ebenezer immanuel carmel
    heart home white light fairview providence andrew point prayer shepherd
""".split())
_DIRECTIONS = frozenset("north south east west calle court place parkway way suite".split())
# A word on the site may be the short form: "Mt. Zion", "St. John's", "Ft. Myers".
_SHORT_FORM = {"mount": "mt", "saint": "st", "fort": "ft"}


_SPELLING = re.compile(r"(savi|neighb)our")


def _fold(text: str | None) -> str:
    """ASCII, lower case, one spelling ("Saviour's" on a "Savior's" record)."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return _SPELLING.sub(r"\1or", text)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def _identity_words(text: str | None) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{3,}", _fold(text))
            if w not in _NAME_GENERIC and _stem(w) not in _NAME_GENERIC}


def site_is_this_church(church: dict, texts: list[str]) -> bool:
    """Whether the archived site can be tied to this church record, from the
    record's own name and address. Every distinctive word of the name must be
    on the site (or in its address), or at least one of them together with the
    street. A name made only of common words ("Grace", "Mount Zion") belongs to
    many congregations, so it needs the city or street as well; one made only
    of generic words
    ("First Baptist Church") needs the city. A shared street alone is not
    enough: another congregation may meet in the same building. Unconfirmed is not "wrong": it means no program from this
    site is shown for this record."""
    if (church.get("site_shared_by") or 0) >= SHARED_SITE_LIMIT:
        return False
    words = {_stem(w) for t in texts for w in re.findall(r"[a-z]{2,}", _fold(t))}
    site = re.sub(r"[^a-z0-9]", "", re.sub(r"^[a-z]+://(www\.)?", "", _fold(church.get("website")).strip()))

    def on_site(word: str) -> bool:
        short = _SHORT_FORM.get(word)
        # A short word inside a domain is a match only at its start
        # ("ivymemorialbaptistchurch.com"), not anywhere ("ann" in "annunciation").
        return (word in words or (len(word) >= 4 and word in site) or site.startswith(word)
                or (short is not None and (short in words or short in site)))

    # A domain often joins words: "gracewayaustin.org", "leroyum.org".
    raw_name = re.findall(r"[a-z0-9]+", _fold(church.get("name")))
    joined = {a + b for a, b in zip(raw_name, raw_name[1:]) if len(a + b) >= 6 and a + b in site}

    def named(word: str) -> bool:
        return on_site(word) or any(word in j for j in joined)

    name = _identity_words(church.get("name"))
    street = _identity_words(church.get("address")) - _DIRECTIONS
    city = _identity_words(church.get("city"))
    city_joined = "".join(re.findall(r"[a-z0-9]+", _fold(church.get("city"))))
    street_ok = bool(street) and all(map(on_site, street))
    city_ok = (bool(city) and all(map(on_site, city))) or (len(city_joined) >= 5 and city_joined in site)
    if name:
        found = [w for w in name if named(w)]
        if len(found) == len(name):
            return not name <= _COMMON_NAME_WORDS or city_ok or street_ok
        return bool(found) and street_ok
    return city_ok


def campus_is_this_church(campus: str, church_words: set[str]) -> bool:
    """A stated campus is this church's only if every word that identifies it
    is in this church's name, city or address. Sharing the church name is not
    enough: "Grace Church South Campus" is not "Grace Church North Campus". A
    campus we cannot confirm is treated as someone else's and the program is
    not kept."""
    return _tokens(campus) <= church_words


# "College Campus Students", "University Campus Ministry", "Campus Crusade": a
# ministry to students on a school campus, not a campus of this church
# (2026-11-23 pilot: it dropped every program listed beside it).
_SCHOOL_CAMPUS = re.compile(r"\b(college|university|school|seminary)\b", re.I)
_CAMPUS_MINISTRY = re.compile(
    r"\s+(ministry|ministries|students?|outreach|fellowship|crusade|life|groups?)\b", re.I)


def is_church_campus(phrase: str, after: str = "") -> bool:
    return not (_SCHOOL_CAMPUS.search(phrase) or _CAMPUS_MINISTRY.match(after))


def campuses_named(campus: str | None, excerpt: str) -> list[str]:
    if campus:
        return [campus] if is_church_campus(campus) else []
    return [m.group(0) for m in _CAMPUS_IN_TEXT.finditer(excerpt)
            if is_church_campus(m.group(0), excerpt[m.end():])]


# ----- the model's answer, checked against the archive -----------------------------

@dataclass
class Page:
    artifact_id: int
    kind: str
    url: str
    r2_key: str
    content_hash: str | None
    fetched_at: datetime
    raw_sha256: str
    text: str

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass
class Checked:
    programs: list[dict] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


def well_formed(obj: Any) -> bool:
    """Only an answer of the asked shape may replace a church's programs; an
    empty list is then a real "none found". Anything else ({}, a string, a
    programs value that is not a list) is a failed answer."""
    return isinstance(obj, dict) and isinstance(obj.get("programs"), list)


def check_programs(obj: Any, pages: list[Page], church: dict) -> Checked:
    """Keep only programs the archived pages support; count what was dropped and why."""
    out = Checked()
    items = obj.get("programs") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        if obj not in (None, {}):
            out.drop("bad_shape")
        return out
    seen: set[tuple] = set()
    church_words = _tokens(church.get("name"), church.get("city"), church.get("address"))
    for item in items[:MAX_PROGRAMS * 2]:
        if not isinstance(item, dict):
            out.drop("bad_shape")
            continue
        try:
            n = int(item.get("page"))
        except (TypeError, ValueError):
            n = 0
        if not 1 <= n <= len(pages):
            out.drop("bad_page")
            continue
        page = pages[n - 1]
        raw_excerpt = item.get("excerpt")
        if not isinstance(raw_excerpt, str) or len(normalize_text(raw_excerpt)) < MIN_EXCERPT_CHARS:
            out.drop("too_short")
            continue
        found = locate(raw_excerpt[:MAX_EXCERPT_CHARS], page.text)
        if found is None:
            out.drop("not_found")
            continue
        if found == "ambiguous":
            out.drop("ambiguous")
            continue
        start, end = found
        excerpt = page.text[start:end].replace("\n", " ")
        if not _KIDS_WORDS.search(excerpt):
            out.drop("not_kids")
            continue

        name = _contains(item.get("name"), excerpt)
        ages = own_ages(name, _contains(item.get("ages_stated"), excerpt), page.text[start:end])
        schedule = _contains(item.get("schedule_stated"), excerpt)
        campus = _contains(item.get("campus_stated"), excerpt)
        if campus and not is_church_campus(campus):
            campus = None

        # The program's own words must make it a kids/youth program; with no
        # stated name, the whole excerpt is its own words.
        clause = own_clause(name, page.text[start:end])
        if not (_KIDS_WORDS.search(clause) or (ages and stated_age_bands(ages))):
            out.drop("not_kids")
            continue

        years = [int(y) for y in _YEAR.findall(" ".join(filter(None, [schedule, excerpt])))]
        if years and max(years) < page.fetched_at.year:
            out.drop("stale")
            continue
        if is_dated(page.text, start, end):
            out.drop("dated_event")
            continue
        if _PAUSED.search(clause):
            out.drop("paused")
            continue
        if not all(campus_is_this_church(c, church_words) for c in campuses_named(campus, excerpt)):
            out.drop("other_campus")
            continue

        own_words = " ".join(filter(None, [name, ages])) or excerpt
        proposed = {b for b in item.get("age_bands") or [] if isinstance(b, str) and b in AGE_BANDS} \
            if isinstance(item.get("age_bands"), list) else set()
        bands = (proposed & supported_age_bands(own_words)) | stated_age_bands(ages or "")
        program_type = item.get("type") if item.get("type") in PROGRAM_TYPES else None
        if program_type and not supports_type(program_type, excerpt):
            program_type = None

        key = (page.artifact_id, start) if not name else (name.lower(), program_type, tuple(sorted(bands)))
        if key in seen:
            out.drop("duplicate")
            continue
        seen.add(key)
        if len(out.programs) >= MAX_PROGRAMS:
            out.drop("over_limit")
            continue
        out.programs.append({
            "program_type": program_type,
            "age_bands": sorted(bands, key=["preschool", "children", "youth", "young_adult"].index),
            "name_stated": name,
            "ages_stated": ages,
            "schedule_stated": schedule,
            "campus_stated": campus,
            "excerpt": excerpt,
            "excerpt_start": start,
            "excerpt_end": end,
            "source_url": page.url,
            "artifact_id": page.artifact_id,
            "r2_key": page.r2_key,
            "content_hash": page.content_hash,
            "raw_sha256": page.raw_sha256,
            "text_sha256": page.text_sha256,
            "page_fetched_at": page.fetched_at,
        })
    return out


# ----- one church ------------------------------------------------------------------

LLMCall = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class Gathered:
    pages: list[Page]
    unreadable: int = 0
    missing: int = 0
    # Text of every page read, with or without program words: the homepage
    # footer or contact page is where a site names its church and street.
    texts: list[str] = field(default_factory=list)


def _read_pages(r2: r2mod.R2Client, target: dict) -> Gathered:
    """Archived pages with any program word, in the SQL's priority order."""
    out = Gathered(pages=[])
    for artifact_id, kind, url, key, chash, fetched_at in zip(
        target["artifact_ids"], target["kinds"], target["urls"], target["r2_keys"],
        target["content_hashes"], target["fetched_ats"],
    ):
        try:
            raw = r2.get_html(key)
        except r2mod.R2NotFound:
            out.missing += 1
            continue
        except r2mod.R2Error as e:
            log.warning("programs: R2 get failed for %s: %s", key, e)
            out.unreadable += 1
            continue
        text = page_text(raw)
        out.texts.append(text)
        if text and _KIDS_WORDS.search(text):
            out.pages.append(Page(artifact_id, kind, url, key, chash, fetched_at,
                                  hashlib.sha256(raw).hexdigest(), text))
    return out


def model_input(pages: list[Page]) -> str:
    parts, used = [], 0
    for n, page in enumerate(pages, 1):
        if used >= MAX_INPUT_CHARS:
            break
        body = page.text[: min(MAX_PAGE_CHARS, MAX_INPUT_CHARS - used)]
        used += len(body)
        parts.append(f"=== PAGE {n} ({page.kind}) {page.url} ===\n{body}")
    return "\n\n".join(parts)


async def extract_programs_for_church(
    repo: ProgramRepository,
    r2: r2mod.R2Client,
    target: dict,
    *,
    call: LLMCall = call_llm,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Returns the outcome: ok, no_program_text, unconfirmed_site, error,
    missing_archive or transient. Only ok, no_program_text and unconfirmed_site
    replace earlier programs; every other outcome keeps them. Transient writes nothing, so the church stays due
    for the next run."""
    church_id = target["church_id"]
    input_ids = sorted(target["artifact_ids"])
    got = await asyncio.to_thread(_read_pages, r2, target)
    if got.unreadable:
        return "transient"
    if got.missing:
        # An archived page we cannot read is incomplete input, not a page
        # without programs: keep what was shown and make no call. The empty
        # input set never equals the due set, so the church stays due and is
        # retried once the object is back, but after churches never tried, so a
        # lost object cannot hold the front of every bounded batch.
        await repo.record_program_extraction(
            church_id, [], status="error", programs=None,
            error_detail=f"archived page missing from R2: {got.missing} of {len(input_ids)}",
            pages_read=0, dropped={}, extractor_version=EXTRACTOR_VERSION, model=None)
        return "missing_archive"
    if not site_is_this_church(target, got.texts):
        # Not tied to this record (a denomination-wide site, another parish's
        # site): no call, and nothing from it is shown for this church.
        await repo.record_program_extraction(
            church_id, input_ids, status="unconfirmed_site", programs=[],
            pages_read=len(input_ids), dropped={},
            extractor_version=EXTRACTOR_VERSION, model=None)
        return "unconfirmed_site"
    if not got.pages:
        # Nothing on these pages is about children or youth: no call, no cost.
        # Earlier programs are cleared: the pages that stated them have changed.
        await repo.record_program_extraction(
            church_id, input_ids, status="no_program_text", programs=[],
            pages_read=len(input_ids), dropped={},
            extractor_version=EXTRACTOR_VERSION, model=None)
        return "no_program_text"
    try:
        raw = await call(model_input(got.pages), api_key=api_key, client=client,
                         model=MODEL, system_prompt=SYSTEM_PROMPT)
    except TransientExtractionError as e:
        log.warning("programs transient failure church=%s: %s", church_id, e)
        return "transient"
    except ExtractionError as e:
        error = str(e)
    else:
        error = None if well_formed(raw) else "answer is not {\"programs\": [...]}"
    if error is not None:
        # Keep whatever was shown before; a bad answer is not evidence of absence.
        # Same input, same model: not re-called until the pages change.
        await repo.record_program_extraction(
            church_id, input_ids, status="error", programs=None, error_detail=error[:500],
            pages_read=len(got.pages), dropped={}, extractor_version=EXTRACTOR_VERSION, model=MODEL)
        return "error"
    checked = check_programs(raw, got.pages, target)
    await repo.record_program_extraction(
        church_id, input_ids, status="ok", programs=checked.programs,
        pages_read=len(got.pages), dropped=checked.dropped,
        extractor_version=EXTRACTOR_VERSION, model=MODEL)
    return "ok"


async def run_program_batch(
    repo: ProgramRepository,
    r2: r2mod.R2Client,
    *,
    limit: int,
    apply: bool,
    call: LLMCall = call_llm,
    church_ids: list[int] | None = None,
    sample_seed: str | None = None,
) -> dict:
    """Dry run (default): how many due churches would cost a model call, read
    from R2 only. Apply: extract each, one transaction per church. Counts only;
    nothing here prints page text, so the output is safe for a public log.

    `church_ids` re-reads exactly those churches, due or not (a rule fix for
    rows already written); `sample_seed` picks the due churches in a seeded
    random order instead of oldest first (an evaluation sample)."""
    targets = await repo.due_for_program_extraction(limit=limit, church_ids=church_ids,
                                                    sample_seed=sample_seed)
    counts = {"due": len(targets), "ok": 0, "no_program_text": 0, "unconfirmed_site": 0, "error": 0,
              "missing_archive": 0, "transient": 0,
              "programs_kept": 0, "would_call_model": 0, "input_chars": 0}
    if not apply:
        for t in targets:
            got = await asyncio.to_thread(_read_pages, r2, t)
            if got.unreadable:
                counts["transient"] += 1
            elif got.missing:
                counts["missing_archive"] += 1
            elif not site_is_this_church(t, got.texts):
                counts["unconfirmed_site"] += 1
            elif got.pages:
                counts["would_call_model"] += 1
                counts["input_chars"] += len(model_input(got.pages))
            else:
                counts["no_program_text"] += 1
        return counts
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        for t in targets:
            async with repo.con.transaction():
                outcome = await extract_programs_for_church(repo, r2, t, call=call, client=client)
            counts[outcome] += 1
    counts["programs_kept"] = await repo.count_programs([t["church_id"] for t in targets])
    return counts
