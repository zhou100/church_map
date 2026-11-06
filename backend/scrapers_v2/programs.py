"""Programs stage: children's, youth and childcare programs from archived pages.

Reads the pages fetch archived for a church (kids, youth, childcare and the
website_v3 pages that often carry the same links), asks the model which
programs they state, and keeps only what the archive itself supports
(docs/plans/crawler_visit_facts_plan.md, PR 4 and appendix A):

  * the excerpt must occur verbatim, exactly once, in the text of the page it
    names; offsets are computed here, never taken from the model;
  * name, ages and schedule must each occur inside that excerpt;
  * a type or age band survives only if the program's own words carry it
    (nursery, "grades 6-12", "during the service", preschool, ...); a
    program named only "Kids" keeps no age band;
  * young adults stay a separate band, so a college group is never a youth group;
  * programs tied to another campus, or whose stated year has passed, are dropped.

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
        doc = lxml_html.document_fromstring(raw.decode("utf-8", errors="replace"))
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
        r"sr\.? high|senior high)\b|(?<!college )(?<!university )(?<!grad )\bstudents?\b", re.I),
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


def campus_is_this_church(campus: str, church_words: set[str]) -> bool:
    """A stated campus is this church's only if every word that identifies it
    is in this church's name, city or address. Sharing the church name is not
    enough: "Grace Church South Campus" is not "Grace Church North Campus". A
    campus we cannot confirm is treated as someone else's and the program is
    not kept."""
    return _tokens(campus) <= church_words


def campuses_named(campus: str | None, excerpt: str) -> list[str]:
    return [campus] if campus else [m.group(0) for m in _CAMPUS_IN_TEXT.finditer(excerpt)]


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
        ages = _contains(item.get("ages_stated"), excerpt)
        schedule = _contains(item.get("schedule_stated"), excerpt)
        campus = _contains(item.get("campus_stated"), excerpt)

        years = [int(y) for y in _YEAR.findall(" ".join(filter(None, [schedule, excerpt])))]
        if years and max(years) < page.fetched_at.year:
            out.drop("stale")
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
    """Returns the outcome: ok, no_program_text, error, missing_archive or
    transient. Only ok and no_program_text replace earlier programs; every
    other outcome keeps them. Transient writes nothing, so the church stays due
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
            pages_read=0, dropped={}, extractor_version=PROMPT_VERSION, model=None)
        return "missing_archive"
    if not got.pages:
        # Nothing on these pages is about children or youth: no call, no cost.
        # Earlier programs are cleared: the pages that stated them have changed.
        await repo.record_program_extraction(
            church_id, input_ids, status="no_program_text", programs=[],
            pages_read=len(input_ids), dropped={},
            extractor_version=PROMPT_VERSION, model=None)
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
            pages_read=len(got.pages), dropped={}, extractor_version=PROMPT_VERSION, model=MODEL)
        return "error"
    checked = check_programs(raw, got.pages, target)
    await repo.record_program_extraction(
        church_id, input_ids, status="ok", programs=checked.programs,
        pages_read=len(got.pages), dropped=checked.dropped,
        extractor_version=PROMPT_VERSION, model=MODEL)
    return "ok"


async def run_program_batch(
    repo: ProgramRepository,
    r2: r2mod.R2Client,
    *,
    limit: int,
    apply: bool,
    call: LLMCall = call_llm,
) -> dict:
    """Dry run (default): how many due churches would cost a model call, read
    from R2 only. Apply: extract each, one transaction per church. Counts only;
    nothing here prints page text, so the output is safe for a public log."""
    targets = await repo.due_for_program_extraction(limit=limit)
    counts = {"due": len(targets), "ok": 0, "no_program_text": 0, "error": 0,
              "missing_archive": 0, "transient": 0,
              "programs_kept": 0, "would_call_model": 0, "input_chars": 0}
    if not apply:
        for t in targets:
            got = await asyncio.to_thread(_read_pages, r2, t)
            if got.unreadable:
                counts["transient"] += 1
            elif got.missing:
                counts["missing_archive"] += 1
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
