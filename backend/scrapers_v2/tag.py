"""Tag stage: deterministic rules over churches.name + denomination + extracted_tags.

Pure CPU/SQL, no LLM. Re-runnable: only updates rows where language OR
cultural_background is currently NULL. Force mode re-tags all rows.

Rule table is ported verbatim from backend/scrapers/name_tags.py — the IP
is the regex set, not the SQLite plumbing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from psycopg.rows import dict_row

from backend.db.repository import CrawlRepository

log = logging.getLogger(__name__)


@dataclass
class Rule:
    pattern: str
    language: str | None
    cultural_background: str | None


RULES: list[Rule] = [
    Rule(r"iglesia|primera\b|segundo\b|nueva\b|cristo\b|dios\b|señor\b|"
         r"espiritu\b|sagrada\b|virgen\b|nuestra\b|evangelio\b|parroquia\b|"
         r"templo\b|catedral\b|hispana|hispanica|latina|latino|española|español",
         "Spanish", "Hispanic/Latino"),
    Rule(r"korean|한국|코리안", "Korean", "Korean"),
    Rule(r"chinese|mandarin|cantonese|中文|华人|taiwanese|台灣|台湾",
         "Chinese", "Chinese"),
    Rule(r"vietnamese|viet\b|việt", "Vietnamese", "Vietnamese"),
    Rule(r"filipino|pilipino|tagalog|philippine", "Filipino", "Filipino"),
    Rule(r"portuguesa|brasileira|brasil\b|lusitano|lusitana|portuguese",
         "Portuguese", "Brazilian/Portuguese"),
    Rule(r"haitian|haïtien|haitien|francophone|française|creole",
         "Haitian Creole", "Haitian"),
    Rule(r"\barabic\b|\barab\b", "Arabic", "Arab"),
    Rule(r"ethiopian|eritrean|amharic|oromo", "Amharic", "East African"),
    Rule(r"\bhmong\b", "Hmong", "Hmong"),
    Rule(r"\bhindi\b|\bpunjabi\b|\btelugu\b|\btamil\b|\bmalayalam\b|\bsouth asian\b",
         "Hindi", "South Asian"),
    Rule(r"\bjapanese\b", "Japanese", "Japanese"),
    Rule(r"\bame\b(?!\s*zion\s+lutheran|\s*zion\s+methodist)|"
         r"african methodist episcopal|"
         r"national baptist|progressive national|"
         r"national missionary baptist|"
         r"colored methodist|c\.m\.e\.|"
         r"mount zion\b|"
         r"\bame zion\b",
         "English", "African American"),
    Rule(r"\bswahili\b|\bafrican\b(?!\s+methodist)", "Swahili", "African"),
]

_COMPILED: list[tuple[re.Pattern[str], str | None, str | None]] = [
    (re.compile(r.pattern, re.IGNORECASE), r.language, r.cultural_background)
    for r in RULES
]


def detect(name: str, denomination: str | None) -> tuple[str | None, str | None]:
    text = f"{name} {denomination or ''}"
    for pattern, lang, culture in _COMPILED:
        if pattern.search(text):
            return lang, culture
    return None, None


async def run_tag_batch(repo: CrawlRepository, *, batch_size: int, force: bool = False) -> dict:
    # name_tagged_at is the watermark. Incremental runs select rows where it
    # is NULL; once we touch a row (match or no-match), we stamp the column
    # so the next batch advances to fresh churches. Without this, batches
    # keep re-selecting the same unmatched rows until they fill the limit.
    if force:
        sql = "SELECT church_id, name, denomination FROM churches LIMIT %s"
    else:
        sql = """
            SELECT church_id, name, denomination FROM churches
             WHERE name_tagged_at IS NULL
             ORDER BY church_id
             LIMIT %s
        """

    async with repo.con.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (batch_size,))
        rows = await cur.fetchall()

    rows_processed = 0
    rows_ok = 0

    for row in rows:
        rows_processed += 1
        lang, culture = detect(row["name"], row["denomination"])
        if not lang and not culture:
            # Stamp the watermark even on no-match so we don't reselect.
            # In force mode we additionally clear stale tags from prior runs.
            if force:
                async with repo.con.cursor() as cur:
                    await cur.execute(
                        "UPDATE churches SET language=NULL, cultural_background=NULL, "
                        "name_tagged_at=NOW() WHERE church_id=%s",
                        (row["church_id"],),
                    )
            else:
                async with repo.con.cursor() as cur:
                    await cur.execute(
                        "UPDATE churches SET name_tagged_at=NOW() WHERE church_id=%s",
                        (row["church_id"],),
                    )
            continue
        # Drop English-only language tags — default, not useful as a filter.
        write_lang = None if lang == "English" else lang
        async with repo.con.cursor() as cur:
            await cur.execute(
                "UPDATE churches SET language=%s, cultural_background=%s, "
                "name_tagged_at=NOW() WHERE church_id=%s",
                (write_lang, culture, row["church_id"]),
            )
        rows_ok += 1

    return {"rows_processed": rows_processed, "rows_ok": rows_ok, "rows_error": 0}
