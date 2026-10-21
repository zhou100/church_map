"""Mechanical acceptance checks for Muse returns (plan section 6.5).

Usage:
    python3 muse_handoff/validate_returns.py A_calibration muse_handoff/returns/results_A.csv \
        muse_handoff/returns/new_candidates_A.csv [--received-at 2026-10-19T17:27:00Z]

For a redo file covering only some rows of a batch, pass `-` as the candidates
file and add --redo (IDs must belong to the batch; full coverage not required).
Use batch ALL for a file spanning batches (e.g. the Facebook pass).
Other manifests: --manifest muse_handoff/batch_C_manifest.csv. Candidates-only
check (e.g. task CN): pass `-` as the results file.

Prints ERROR lines (rule violations) and WARN lines (needs human review), then a
coverage summary. Exit code 1 if any ERROR. Stdlib only; reads local files only.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "peninsula_seed_v1.csv"

PACKAGE_TASK_RE = re.compile(r"^WP\d{4}$")  # work packages from the shared Drive queue

ENUMS = {
    "task": {"C", "CN", "D", "E", "F", "L", "H"},
    "candidate_status": {"active", "unresolved"},
    "entity_type": {"congregation", "religious_house", "non_christian", "business", "other", "unknown"},
    "status": {"active", "closed", "moved", "merged", "unresolved"},
    "source_type": {"own_site", "fb_page", "denomination", "other"},
    "url_evidence": {"address_matches", "phone_matches", "cross_linked", "name_only"},
    "fb_page_evidence": {"links_to_site", "site_links_to_page", "posts_as_church", "address_matches", "phone_matches"},
    "address_is_worship_location": {"yes", "no", "unknown"},
    "pin_check": {"matches", "off", "unknown"},
    "match_confidence": {"high", "medium", "low"},
    "found_via": {"fb_page_search", "fb_group_lead", "web_search", "denomination_directory", "host_church_site"},
}

# ZIPs -> USPS city names for San Mateo County and the South Bay (a ZIP may serve several).
ZIP_CITIES = {
    "94002": {"Belmont"}, "94005": {"Brisbane"}, "94010": {"Burlingame", "Hillsborough"},
    "94014": {"Daly City", "Colma"}, "94015": {"Daly City", "Broadmoor"}, "94019": {"Half Moon Bay"},
    "94025": {"Menlo Park", "Atherton"}, "94027": {"Atherton"}, "94030": {"Millbrae"},
    "94044": {"Pacifica"}, "94061": {"Redwood City"}, "94062": {"Redwood City", "Woodside"},
    "94063": {"Redwood City"}, "94065": {"Redwood City"}, "94066": {"San Bruno"},
    "94070": {"San Carlos"}, "94080": {"South San Francisco"},
    "94401": {"San Mateo"}, "94402": {"San Mateo", "Hillsborough"}, "94403": {"San Mateo"},
    "94404": {"San Mateo", "Foster City"},
    # Coast and south San Mateo County
    "94018": {"El Granada", "Half Moon Bay"}, "94020": {"La Honda"}, "94021": {"Loma Mar"},
    "94028": {"Portola Valley", "Ladera", "Menlo Park"}, "94037": {"Montara"}, "94038": {"Moss Beach"},
    "94060": {"Pescadero"}, "94074": {"San Gregorio"}, "94128": {"San Francisco"},
    # North Santa Clara County (batch C) and South Bay (task CN)
    "94022": {"Los Altos", "Los Altos Hills"}, "94024": {"Los Altos", "Los Altos Hills"},
    "94301": {"Palo Alto"}, "94303": {"Palo Alto", "East Palo Alto"}, "94304": {"Palo Alto"},
    "94305": {"Stanford", "Palo Alto"}, "94306": {"Palo Alto"},
    "94040": {"Mountain View"}, "94041": {"Mountain View"}, "94043": {"Mountain View"},
    "94085": {"Sunnyvale"}, "94086": {"Sunnyvale"}, "94087": {"Sunnyvale"}, "94089": {"Sunnyvale"},
    "95014": {"Cupertino"}, "95008": {"Campbell"}, "95030": {"Los Gatos", "Monte Sereno"}, "95032": {"Los Gatos"},
    "95035": {"Milpitas"}, "95050": {"Santa Clara"}, "95051": {"Santa Clara"}, "95054": {"Santa Clara"},
    "95070": {"Saratoga"},
    **{str(z): {"San Jose"} for z in list(range(95110, 95140)) + [95148]},
    "95002": {"San Jose", "Alviso"},
    # San Francisco and the Fremont area (batch D)
    **{str(z): {"San Francisco"} for z in list(range(94102, 94135)) + [94158]},
    "94536": {"Fremont"}, "94537": {"Fremont"}, "94538": {"Fremont"}, "94539": {"Fremont"},
    "94555": {"Fremont"}, "94560": {"Newark"}, "94587": {"Union City"}, "94586": {"Sunol"},
    # East Bay (batch F). Multi-city sets where one ZIP serves several USPS names.
    **{str(z): {"Oakland"} for z in range(94601, 94622)},
    "94610": {"Oakland", "Piedmont"}, "94611": {"Oakland", "Piedmont"}, "94618": {"Oakland", "Piedmont"},
    "94608": {"Oakland", "Emeryville"}, "94705": {"Berkeley", "Oakland"},
    **{str(z): {"Berkeley"} for z in (94702, 94703, 94704, 94709, 94710, 94720)},
    "94707": {"Berkeley", "Kensington", "Albany"}, "94708": {"Berkeley", "Kensington"},
    "94706": {"Albany", "Kensington", "Berkeley"},
    "94501": {"Alameda"}, "94502": {"Alameda"},
    "94577": {"San Leandro"}, "94578": {"San Leandro", "Ashland", "Cherryland"}, "94579": {"San Leandro"},
    "94580": {"San Lorenzo", "Ashland", "Cherryland", "Hayward"},
    "94541": {"Hayward", "Cherryland", "Ashland"}, "94542": {"Hayward"}, "94544": {"Hayward"}, "94545": {"Hayward"},
    "94546": {"Castro Valley"}, "94552": {"Castro Valley"},
    "94568": {"Dublin"}, "94566": {"Pleasanton"}, "94588": {"Pleasanton"},
    "94550": {"Livermore"}, "94551": {"Livermore"},
    "94582": {"San Ramon"}, "94583": {"San Ramon"}, "94506": {"Danville"}, "94526": {"Danville", "Diablo"},
    "94595": {"Walnut Creek"}, "94596": {"Walnut Creek"}, "94597": {"Walnut Creek"}, "94598": {"Walnut Creek"},
    "94518": {"Concord"}, "94519": {"Concord"}, "94520": {"Concord"}, "94521": {"Concord"},
    "94523": {"Pleasant Hill"}, "94553": {"Martinez"}, "94549": {"Lafayette"}, "94563": {"Orinda"},
    "94556": {"Moraga"}, "94517": {"Clayton"},
    "94801": {"Richmond", "North Richmond"}, "94804": {"Richmond"}, "94805": {"Richmond"},
    "94803": {"Richmond", "El Sobrante", "San Pablo", "Pinole"}, "94806": {"San Pablo", "Richmond", "Rollingwood"},
    "94530": {"El Cerrito", "Richmond", "East Richmond Heights"},
    "94564": {"Pinole"}, "94547": {"Hercules", "Rodeo"}, "94572": {"Rodeo"}, "94525": {"Crockett"},
    "94565": {"Pittsburg", "Bay Point"}, "94509": {"Antioch"}, "94531": {"Antioch"},
    "94513": {"Brentwood"}, "94561": {"Oakley"}, "94548": {"Knightsen"}, "94510": {"Benicia"},
}

# ---- Street addresses: one normalizer for the validator, repair tool and seeds ----
# "107 San Mateo Avenue" must never count as evidence for "107 San Pedro Road":
# compare the house number and every word of the street name, with suffixes and
# directions normalized; a unit/suite after the suffix is ignored.
STREET_SUFFIX = {"street": "st", "st": "st", "avenue": "ave", "ave": "ave", "av": "ave", "boulevard": "blvd",
                 "blvd": "blvd", "drive": "dr", "dr": "dr", "road": "rd", "rd": "rd", "lane": "ln", "ln": "ln",
                 "court": "ct", "ct": "ct", "way": "way", "place": "pl", "pl": "pl", "circle": "cir", "cir": "cir",
                 "highway": "hwy", "hwy": "hwy", "real": "real", "parkway": "pkwy", "pkwy": "pkwy",
                 "terrace": "ter", "ter": "ter", "plaza": "plz", "plz": "plz", "square": "sq", "sq": "sq",
                 "alley": "aly", "aly": "aly", "expressway": "expy", "expy": "expy", "center": "ctr", "ctr": "ctr"}
STREET_DIRECTION = {"north": "n", "n": "n", "south": "s", "s": "s", "east": "e", "e": "e", "west": "w", "w": "w"}
UNIT_WORDS = {"ste", "suite", "unit", "apt", "room", "rm", "fl", "floor", "bldg", "building", "#"}


NAME_ABBREV = {"saint": "st", "mount": "mt", "fort": "ft"}  # "St. Lawrence" = "Saint Lawrence"
NUMBER_WORDS = dict(enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                              "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()))


UNIT_NUMBER = {w: i for i, w in NUMBER_WORDS.items()}
TENS_NUMBER = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
               "ninety": 90}


def _merge_number_words(toks: list[str]) -> list[str]:
    """Read a run of number words as one number: "twenty one" / "twenty-one" -> "21",
    "one hundred five" -> "105", "one" -> "1". A single word is never matched on its
    own inside a longer phrase ("one" is not "twenty-one")."""
    out, i = [], 0
    while i < len(toks):
        if toks[i] not in UNIT_NUMBER and toks[i] not in TENS_NUMBER:
            out.append(toks[i])
            i += 1
            continue
        total, cur, j = 0, 0, i
        while j < len(toks):
            w = toks[j]
            if w in TENS_NUMBER and cur % 100 == 0:
                cur += TENS_NUMBER[w]
            elif w in UNIT_NUMBER and (cur % 10 == 0 or cur == 0) and not (cur % 100 >= 10 and cur % 100 < 20):
                cur += UNIT_NUMBER[w]
            elif w == "hundred" and 0 < cur < 10:
                cur *= 100
            elif w == "and" and cur >= 100:
                pass
            else:
                break
            j += 1
        total += cur
        out.append(str(total))
        i = j
    return out


def street_tokens(text: str) -> list[str]:
    t = (text or "").lower().replace(".", "")
    toks = _merge_number_words(re.findall(r"#|[^\W_]+", t))
    out = []
    for x in toks:
        x = re.sub(r"^(\d+)(st|nd|rd|th)$", r"\1", x)  # "39th" = "39"
        out.append(NAME_ABBREV.get(x, STREET_DIRECTION.get(x, STREET_SUFFIX.get(x, x))))
    return out


def street_key(street: str) -> tuple[str, tuple[str, ...]] | None:
    """(house number, normalized street-name tokens up to and including the suffix)."""
    toks = street_tokens(street)
    if not toks or not re.fullmatch(r"\d+[a-z]?", toks[0]) or len(toks) < 2:  # "592A Tennent Ave"
        return None
    name = []
    for tok in toks[1:]:
        if tok in UNIT_WORDS:
            break
        name.append(tok)
        if tok in STREET_SUFFIX.values() and len(name) > 1:
            break
    return (toks[0], tuple(name)) if name else None


def excerpt_supports_street(excerpt: str, street: str) -> bool:
    """True if the excerpt states this exact street address (number + full street name).
    A suffix may be left out in the excerpt ("107 San Pedro, Colma") as long as no
    other suffix stands in its place."""
    key = street_key(street)
    if not key:
        return False
    number, name = key
    toks = street_tokens(excerpt)
    seqs = [[number, *name]]  # number words were already read as whole numbers by street_tokens
    if len(name) > 1 and name[-1] in STREET_SUFFIX.values():
        seqs.append([number, *name[:-1]])
    for seq in seqs:
        n = len(seq)
        for i in range(len(toks) - n + 1):
            if toks[i:i + n] == seq:
                nxt = toks[i + n] if i + n < len(toks) else ""
                if len(seq) == len(name) + 1 or nxt not in STREET_SUFFIX.values():
                    return True
    return False


# ---- Service times: the excerpt must state the same times on the same days ----
SVC_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|[ap](?![a-z]))", re.I)
DAY_WORDS = {
    "sun": ("sunday", "sundays", "sun", "主日", "週日", "周日", "星期日", "禮拜日", "礼拜日", "주일", "일요일",
            "domingo", "domingos", "dom"),
    "mon": ("monday", "mondays", "mon", "週一", "周一", "星期一", "월요일", "lunes"),
    "tue": ("tuesday", "tuesdays", "tue", "tues", "週二", "周二", "星期二", "화요일", "martes"),
    "wed": ("wednesday", "wednesdays", "wed", "週三", "周三", "星期三", "수요일", "miércoles", "miercoles", "mié"),
    "thu": ("thursday", "thursdays", "thu", "thur", "thurs", "週四", "周四", "星期四", "목요일", "jueves", "jue"),
    "fri": ("friday", "fridays", "fri", "週五", "周五", "星期五", "금요일", "viernes", "vie"),
    "sat": ("saturday", "saturdays", "sat", "週六", "周六", "星期六", "토요일", "sábado", "sabado", "sábados", "sáb"),
}


CJK_NUM = {"一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
           "十": 10, "十一": 11, "十二": 12}
CJK_TIME_RE = re.compile(r"(上午|下午|早上|晚上|中午|午前|午後|오전|오후)?\s*(\d{1,2}|十[一二]?|[一二兩两三四五六七八九])"
                         r"\s*(?:[:：](\d{2})|[點点時时시])\s*(?:(\d{1,2})\s*[分분]|(半))?")
PM_WORDS = ("下午", "晚上", "午後", "오후")
ACTIVITY_WORDS = {
    "worship": ("worship", "service", "services", "mass", "masses", "liturgy", "eucharist", "celebration", "vigil",
                "崇拜", "聚會", "聚会", "彌撒", "弥撒", "禮拜", "礼拜", "예배", "misa", "culto", "servicio"),
    "study": ("bible study", "sunday school", "fellowship", "prayer", "youth", "class", "classes", "choir",
              "small group", "growth group", "主日學", "主日学", "團契", "团契", "查經", "查经", "禱告", "祷告",
              "성경공부", "escuela dominical", "estudio bíblico"),
}
LANGUAGE_WORDS = {
    "english": ("english", "英文", "英語", "英语", "영어", "inglés"), "spanish": ("spanish", "español", "espanol"),
    "mandarin": ("mandarin", "國語", "国语", "普通話", "普通话", "華語", "华语"), "cantonese": ("cantonese", "粵語", "粤语", "廣東話"),
    "korean": ("korean", "한국어", "韓語"), "vietnamese": ("vietnamese", "tiếng việt"), "taiwanese": ("taiwanese", "台語", "台语"),
}


def _has_word(t: str, w: str) -> bool:
    return bool(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t)) if w.isascii() else w in t


def _times_in(chunk: str) -> list[tuple[int, str]]:
    """(position, HH:MM) for each time in the chunk."""
    out = []
    for m in SVC_TIME_RE.finditer(chunk):
        h, mm, ap = m.groups()
        hour = int(h)
        if 1 <= hour <= 12:
            out.append((m.start(), f"{hour % 12 + (12 if ap.lower().startswith('p') else 0):02d}:{int(mm or 0):02d}"))
    for m in CJK_TIME_RE.finditer(chunk):
        ap, h, m1, m2, half = m.groups()
        hour = int(h) if h.isdigit() else CJK_NUM.get(h, 0)
        if not ap or not 1 <= hour <= 12:
            continue  # without 上午/下午/오전/오후 the half of day is unknown
        minute = int(m1 or m2 or (30 if half else 0))
        out.append((m.start(), f"{hour % 12 + (12 if ap in PM_WORDS else 0):02d}:{minute:02d}"))
    return out


def _day_positions(chunk: str) -> list[tuple[int, str]]:
    found = []
    for day, words in DAY_WORDS.items():
        for w in words:
            pat = rf"(?<![a-z]){re.escape(w)}(?![a-z])" if w.isascii() else re.escape(w)
            found += [(m.start(), day) for m in re.finditer(pat, chunk)]
    return sorted(found)


def _class_positions(chunk: str, table: dict) -> list[tuple[int, int, str]]:
    """(start, end, class) of every keyword; "sunday school" wins over its "sunday"."""
    found = []
    for cls, words in table.items():
        for w in words:
            pat = rf"(?<![a-z]){re.escape(w)}(?![a-z])" if w.isascii() else re.escape(w)
            found += [(m.start(), m.end(), cls) for m in re.finditer(pat, chunk)]
    return found


def _class_for_time(found: list[tuple[int, int, str]], times: list[int], i: int, labels_after: bool) -> str | None:
    """Class of the keyword belonging to the i-th time in a clause. Schedules are written
    either label-first ("主日崇拜：上午 9:00", "Sunday worship 10 AM") or time-first
    ("9:40am 成人主日學 11:00am 國語主日崇拜"); the clause's first element decides."""
    pos = times[i]
    nxt = times[i + 1] if i + 1 < len(times) else 10**9
    prv = times[i - 1] if i else -1
    if labels_after:
        cands = [f for f in found if pos < f[0] < nxt]
        return min(cands)[2] if cands else None
    cands = [f for f in found if prv < f[0] < pos]
    return max(cands)[2] if cands else None


def service_slots(text: str) -> set[tuple]:
    """(day, activity, language, HH:MM) for every time in the text. A time takes the
    nearest day named before it (carrying over from earlier clauses), and the activity
    and language keywords that belong to it within its clause (split on ; , | / sentence
    ends, lines), label-first or time-first as the clause is written."""
    slots, day = set(), None
    for chunk in re.split(r"[;,|/\n；，、。]+|\.\s", (text or "").lower()):
        days = _day_positions(chunk)
        acts, langs = _class_positions(chunk, ACTIVITY_WORDS), _class_positions(chunk, LANGUAGE_WORDS)
        found_times = sorted(_times_in(chunk))
        positions = [p for p, _ in found_times]

        def time_first(labels: list) -> bool:
            # Decided separately for activity and for language: in "Sunday Mass 10 AM
            # (Spanish)" the activity precedes the time while the language follows it.
            return bool(positions) and (not labels or positions[0] < min(f[0] for f in labels))

        acts_after, langs_after = time_first(acts), time_first(langs)
        for i, (pos, t) in enumerate(found_times):
            before = [d for p, d in days if p < pos]
            slots.add((before[-1] if before else day, _class_for_time(acts, positions, i, acts_after),
                       _class_for_time(langs, positions, i, langs_after), t))
        if days:
            day = days[-1][1]
    return slots


def service_times_of(text: str) -> set[str]:
    return {s[3] for s in service_slots(text)}


def service_days_of(text: str) -> set[str]:
    return {s[0] for s in service_slots(text) if s[0]}


def _slot_supported(want: tuple, have: set[tuple]) -> bool:
    day, act, lang, t = want
    for d, a, l, tt in have:
        if tt != t:
            continue
        if day and d != day:          # a day the record states must be stated, and the same
            continue
        if act and a and a != act:    # worship vs Bible study, if both say
            continue
        if lang and l and l != lang:  # language, if both say
            continue
        return True
    return False


def excerpt_supports_service(excerpt: str, verbatim: str) -> bool:
    """Each time in the recorded schedule must appear in the excerpt on the same day, for
    the same kind of gathering and in the same language where either text says so.
    "Sunday worship 10 AM" is not supported by "Saturday Bible study 10 AM; Sunday
    worship 11 AM". A schedule with no parseable time is not judged here."""
    want = service_slots(verbatim)
    if not want:
        return True
    have = service_slots(excerpt)
    return all(_slot_supported(w, have) for w in want)


FACT_GROUPS = {
    # group -> predicate: is the group "filled" on this row? (kids exists from v3)
    "status": lambda r: r["status"] not in ("", "unresolved"),
    "address": lambda r: bool(r["street_address"]),
    "phone": lambda r: bool(r["phone"]),
    "service": lambda r: bool(r["service_times_verbatim"] or r["service_languages"]),
    "kids": lambda r: bool(r.get("kids_program_verbatim")),
}

THIRD_PARTY_HOSTS = ("businessyab.", "yelp.", "google.", "christianity.com", "pwi.org", "mapquest.", "chamberofcommerce.")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Phrases produced by search/places tools rather than by the cited page.
TOOL_OUTPUT_RE = re.compile(r"away from query location|do not trust other web sources|operating status:|account type:|stats: \d", re.I)
LANG_ALIASES = {
    "spanish": ("spanish", "español", "espanol", "espanõl"),
    "mandarin": ("mandarin", "普通話", "普通话", "國語", "国语"),
    "cantonese": ("cantonese", "粵語", "粤语", "廣東話", "广东话"),
    "vietnamese": ("vietnamese", "tiếng việt", "tieng viet"),
    "japanese": ("japanese", "日本語", "日語", "日语"),
}
NEGATED_PERSONAL_RE = re.compile(r"\bnot (identified as |labell?ed as |a )?personal\b", re.I)
PERSONAL_PHONE_RE = re.compile(r"\b(cell|mobile|personal|rector's|pastor's|priest's|father's)\b", re.I)
# Accepts CJK numerals too ("下午一時半"): a verbatim excerpt must never need rewriting
# to satisfy this check (CN round: Muse edited 4 excerpts to add Arabic time tokens).
TIME_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?|am|pm|點|点|時|时|시)|noon|\d{1,2}:\d{2}"
                     r"|[一二三四五六七八九十]{1,3}\s*(時|时|點|点)"
                     r"|\b\d{1,2}(:\d{2})?\s?[ap]\b", re.I)  # Korean 오전 8시; "10A" shorthand
STRICT_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")

problems: list[tuple[str, str, str]] = []


def err(where: str, msg: str) -> None:
    problems.append(("ERROR", where, msg))


def warn(where: str, msg: str) -> None:
    problems.append(("WARN", where, msg))


def is_url(u: str) -> bool:
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)


def is_fb(u: str) -> bool:
    return "facebook.com" in urlparse(u).netloc


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_multi(where: str, col: str, value: str, enum: str) -> None:
    for part in filter(None, value.split(";")):
        if part not in ENUMS[enum]:
            err(where, f"{col}={part!r} not allowed")


def check_zip_city(where: str, r: dict) -> None:
    z, city = r.get("zip", ""), r.get("city", "")
    if not z:
        if r.get("street_address"):
            warn(where, "street_address without zip")
        return
    if not re.fullmatch(r"\d{5}", z):
        err(where, f"zip {z!r} is not 5 digits")
    elif z not in ZIP_CITIES:
        warn(where, f"zip {z} not in the ZIP table; check manually")
    elif city and city not in ZIP_CITIES[z]:
        err(where, f"zip {z} belongs to {sorted(ZIP_CITIES[z])}, not {city!r}")


def check_common(where: str, r: dict, received_at: datetime | None) -> None:
    for col, val in r.items():
        if val and (col.endswith("_url") or col == "official_url") and not is_url(val):
            err(where, f"{col} is not an http(s) URL")
        if val and col.endswith("excerpt") and len(val) > 200:
            err(where, f"{col} is {len(val)} chars (>200)")
        if val and EMAIL_RE.search(val):
            err(where, f"{col} contains an email address")
        if val and col.endswith("excerpt") and TOOL_OUTPUT_RE.search(val):
            err(where, f"{col} reads like search/places-tool output, not text from the cited page")
        if val and col.endswith("source_url") and any(h in val for h in THIRD_PARTY_HOSTS):
            warn(where, f"{col} is a third-party listing ({urlparse(val).netloc})")
    if r.get("official_url") and is_fb(r["official_url"]):
        err(where, "official_url is a facebook.com URL")
    if r.get("facebook_page_url"):
        if not is_fb(r["facebook_page_url"]):
            err(where, "facebook_page_url is not facebook.com")
        if not r.get("fb_page_evidence"):
            err(where, "facebook_page_url without fb_page_evidence (S2 requires at least one)")
        check_multi(where, "fb_page_evidence", r.get("fb_page_evidence", ""), "fb_page_evidence")
    if r.get("fb_last_post_date"):
        try:
            if date.fromisoformat(r["fb_last_post_date"]) > date.today():
                err(where, "fb_last_post_date is in the future")
        except ValueError:
            err(where, "fb_last_post_date is not YYYY-MM-DD")
    if r.get("street_address") and not re.match(r"\s*\d", r["street_address"]):
        err(where, "street_address has no leading house number")
    if r.get("state") and r["state"] != "CA":
        err(where, f"state={r['state']!r}")
    check_zip_city(where, r)
    ts = parse_ts(r.get("checked_at", ""))
    if r.get("checked_at") and not STRICT_TS_RE.match(r["checked_at"]):
        err(where, f"checked_at {r['checked_at']!r} is not YYYY-MM-DDTHH:MM[:SS]Z")
    if ts is None:
        err(where, "checked_at missing or not ISO 8601")
    elif received_at and ts > received_at:
        err(where, f"checked_at {r['checked_at']} is after the file was received ({received_at:%H:%M}Z)")


def check_fact_groups(w: str, r: dict) -> None:
    for g, filled in FACT_GROUPS.items():
        if f"{g}_source_url" not in r or not filled(r):
            continue
        missing = [c for c in (f"{g}_source_url", f"{g}_source_type", f"{g}_excerpt") if not r[c]]
        if missing:
            err(w, f"{g} fact without {', '.join(missing)}")
        if r[f"{g}_source_type"] and r[f"{g}_source_type"] not in ENUMS["source_type"]:
            err(w, f"{g}_source_type={r[f'{g}_source_type']!r} not allowed")
        if r[f"{g}_source_url"] and urlparse(r[f"{g}_source_url"]).path in ("", "/") \
                and r[f"{g}_source_type"] == "denomination":
            warn(w, f"{g}_source_url is a bare homepage; cannot locate the cited listing")
    ex = r.get("address_excerpt", "")
    if r.get("street_address") and ex and not excerpt_supports_street(ex, r["street_address"]):
        err(w, "address_excerpt does not state this full street address (number + street name)")
    if r.get("phone") and r.get("phone_excerpt") and digits(r["phone"])[-4:] not in digits(r["phone_excerpt"]):
        err(w, "phone_excerpt does not contain the phone's last 4 digits")
    if r.get("service_times_verbatim") and r.get("service_excerpt") and not TIME_RE.search(r["service_excerpt"]):
        err(w, "service_excerpt has no time token")
    elif r.get("service_times_verbatim") and r.get("service_excerpt") and \
            not excerpt_supports_service(r["service_excerpt"], r["service_times_verbatim"]):
        err(w, "service_excerpt does not state the same times on the same days as service_times_verbatim")
    phone_ctx = NEGATED_PERSONAL_RE.sub("", r.get("notes", "") + " " + r.get("phone_excerpt", ""))
    if r.get("phone") and PERSONAL_PHONE_RE.search(phone_ctx):
        err(w, "phone looks like a personal number (D-2): leave blank, note 'personal number withheld'")
    if r.get("match_confidence") == "high" and r.get("url_evidence") == "name_only":
        err(w, "match_confidence=high but url_evidence=name_only (high needs >=2 independent signals)")


def check_results(batch: str, path: Path, received_at: datetime | None, redo: bool = False,
                  manifest: Path = MANIFEST) -> list[dict]:
    expected = {r["church_id"] for r in csv.DictReader(manifest.open(encoding="utf-8"))
                if batch == "ALL" or r["batch"] == batch}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    ids = Counter(r["church_id"] for r in rows)
    for cid, n in ids.items():
        if n > 1:
            err(cid, f"appears {n} times")
    for cid in (set() if redo else expected - set(ids)):
        err(cid, "missing from results")
    for cid in set(ids) - expected:
        err(cid, "not in this batch of the manifest")

    for r in rows:
        w = r["church_id"]
        for col in ("entity_type", "status", "pin_check", "match_confidence"):
            if r[col] not in ENUMS[col]:
                err(w, f"{col}={r[col]!r} not allowed")
        if r["address_is_worship_location"] and r["address_is_worship_location"] not in ENUMS["address_is_worship_location"]:
            err(w, "address_is_worship_location not allowed")
        check_multi(w, "url_evidence", r["url_evidence"], "url_evidence")
        if r["official_url"] and not r["url_evidence"]:
            err(w, "official_url without url_evidence")
        if r["minutes_spent"] and not r["minutes_spent"].isdigit():
            err(w, "minutes_spent is not an integer")

        for g, filled in FACT_GROUPS.items():
            if not filled(r):
                continue
            missing = [c for c in (f"{g}_source_url", f"{g}_source_type", f"{g}_excerpt") if not r[c]]
            if missing:
                err(w, f"{g} fact without {', '.join(missing)}")
            if r[f"{g}_source_type"] and r[f"{g}_source_type"] not in ENUMS["source_type"]:
                err(w, f"{g}_source_type={r[f'{g}_source_type']!r} not allowed")
            if r[f"{g}_source_url"] and urlparse(r[f"{g}_source_url"]).path in ("", "/") \
                    and r[f"{g}_source_type"] == "denomination":
                warn(w, f"{g}_source_url is a bare homepage; cannot locate the cited listing")

        ex = r["address_excerpt"]
        if r["street_address"] and ex and not excerpt_supports_street(ex, r["street_address"]):
            err(w, "address_excerpt does not state this full street address (number + street name)")
        if r["zip"] and ex and r["zip"] not in ex:
            warn(w, f"address_excerpt does not contain zip {r['zip']}")
        if r["phone"] and r["phone_excerpt"] and digits(r["phone"])[-4:] not in digits(r["phone_excerpt"]):
            err(w, "phone_excerpt does not contain the phone's last 4 digits")
        if r["service_times_verbatim"] and r["service_excerpt"] and not TIME_RE.search(r["service_excerpt"]):
            err(w, "service_excerpt has no time token")
        seen = (r["service_excerpt"] + " " + r["service_times_verbatim"]).lower()
        for lang in filter(None, r["service_languages"].split(";")):
            aliases = LANG_ALIASES.get(lang.lower(), (lang.lower(),))
            if lang != "English" and not any(a in seen for a in aliases):
                warn(w, f"service language {lang} not visible in excerpt or verbatim times")

        # D-2: personal numbers are never kept, even if the church published them.
        phone_ctx = NEGATED_PERSONAL_RE.sub("", r["notes"] + " " + r["phone_excerpt"])
        if r["phone"] and PERSONAL_PHONE_RE.search(phone_ctx):
            err(w, "phone looks like a personal number (D-2): leave blank, note 'personal number withheld'")

        # Consistency between verdicts.
        if r["match_confidence"] == "high" and r["url_evidence"] == "name_only":
            err(w, "match_confidence=high but url_evidence=name_only (high needs >=2 independent signals)")
        if r["match_confidence"] == "high" and r["status"] == "unresolved":
            warn(w, "match_confidence=high on an unresolved row")
        if r["status"] == "closed" and "temporarily" in r["status_excerpt"].lower():
            warn(w, "status=closed but the excerpt says temporarily closed")
        if r["entity_type"] != "congregation" and r["status"] == "closed":
            warn(w, "entity_type should describe the named (closed) entity, not the building's current occupant")
        if r["status_source_type"] == "own_site" and r["status_source_url"] and \
                r["official_url"] and urlparse(r["official_url"]).netloc.split("www.")[-1] not in r["status_source_url"]:
            warn(w, "status source typed own_site but not on the official domain")
    return rows


def check_candidates_v3(rows: list[dict], received_at: datetime | None) -> None:
    refs = Counter(r["candidate_ref"] for r in rows)
    for ref, n in refs.items():
        if not ref or n > 1:
            err(f"cand:{ref or '(blank)'}", f"candidate_ref blank or repeated ({n}x)")
    for r in rows:
        w = f"{r['candidate_ref']}:{r['candidate_name'][:28]}"
        for col in ("candidate_name", "city", "status", "found_via", "match_confidence", "task"):
            if not r[col]:
                err(w, f"missing required {col}")
        if r["task"] and r["task"] not in ENUMS["task"] and not PACKAGE_TASK_RE.match(r["task"]):
            err(w, f"task={r['task']!r} not allowed")
        if r["status"] and r["status"] not in ENUMS["candidate_status"]:
            err(w, f"status={r['status']!r} not allowed (candidates: active or unresolved)")
        if r["found_via"] and r["found_via"] not in ENUMS["found_via"]:
            err(w, f"found_via={r['found_via']!r} not allowed")
        if r["match_confidence"] and r["match_confidence"] not in ENUMS["match_confidence"]:
            err(w, f"match_confidence={r['match_confidence']!r} not allowed")
        check_multi(w, "url_evidence", r["url_evidence"], "url_evidence")
        if r.get("address_is_worship_location") and \
                r["address_is_worship_location"] not in ENUMS["address_is_worship_location"]:
            err(w, f"address_is_worship_location={r['address_is_worship_location']!r} not allowed (yes/no/unknown)")
        if r["status"] == "active" and not r["status_source_url"]:
            err(w, "status=active without status_source_url")
        if not r["street_address"]:
            warn(w, "no street address (cannot be pinned)")
        check_fact_groups(w, r)
        check_common(w, r, received_at)


def check_candidates(path: Path, received_at: datetime | None) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if rows and "candidate_ref" in rows[0]:
        check_candidates_v3(rows, received_at)
        return rows
    for i, r in enumerate(rows, 1):
        w = f"cand{i}:{r['candidate_name'][:30]}"
        for col in ("candidate_name", "city", "source_url", "excerpt"):
            if not r[col]:
                err(w, f"missing required {col}")
        if r["source_type"] not in ENUMS["source_type"]:
            err(w, f"source_type={r['source_type']!r} not allowed")
        if r["found_via"] not in ENUMS["found_via"]:
            err(w, f"found_via={r['found_via']!r} not allowed")
        if r["street_address"] and not excerpt_supports_street(r["excerpt"], r["street_address"]):
            warn(w, "street_address not supported by the excerpt (number + full street name)")
        if not r["street_address"]:
            warn(w, "no street address (cannot be pinned)")
        if r["source_type"] == "other":
            warn(w, "only a non-official source")
        check_common(w, r, received_at)
    stamps = Counter(r["checked_at"] for r in rows)
    if len(rows) > 3 and len(stamps) == 1:
        warn("candidates", f"all {len(rows)} rows share checked_at {next(iter(stamps))}; likely reconstructed")
    return rows


def summarize(rows: list[dict]) -> None:
    n = len(rows)
    c = lambda pred: sum(1 for r in rows if pred(r))
    print(f"\nResults: {n} rows")
    print("  status:", dict(Counter(r["status"] for r in rows)))
    print("  entity_type:", dict(Counter(r["entity_type"] for r in rows)))
    print(f"  official_url: {c(lambda r: r['official_url'])} "
          f"(name_only: {c(lambda r: r['url_evidence'] == 'name_only')})")
    print(f"  facebook_page_url: {c(lambda r: r['facebook_page_url'])}; fb_last_post_date: {c(lambda r: r['fb_last_post_date'])}")
    print(f"  street_address: {c(lambda r: r['street_address'])} "
          f"(own_site source: {c(lambda r: r['street_address'] and r['address_source_type'] == 'own_site')})")
    print(f"  phone: {c(lambda r: r['phone'])}; service times: {c(lambda r: r['service_times_verbatim'])}; "
          f"languages stated: {c(lambda r: r['service_languages'])}")
    visit_ready = c(lambda r: r["status"] == "active" and r["street_address"]
                    and r["address_source_type"] in ("own_site", "denomination")
                    and r["url_evidence"] not in ("", "name_only")
                    and r["match_confidence"] == "high")
    print(f"  candidate visit-ready (active + own/denomination address + verified URL + high), pending audit: {visit_ready}")
    print("  checked_at values:", dict(Counter(r["checked_at"] for r in rows)))
    print(f"  minutes_spent total: {sum(int(r['minutes_spent'] or 0) for r in rows)}")


def main(argv: list[str]) -> int:
    received_at = None
    manifest = MANIFEST
    if "--manifest" in argv:
        i = argv.index("--manifest")
        manifest = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    redo = "--redo" in argv
    argv = [a for a in argv if a != "--redo"]
    if "--received-at" in argv:
        i = argv.index("--received-at")
        received_at = parse_ts(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    batch, results_path, candidates_path = argv[1], Path(argv[2]), Path(argv[3])
    rows = [] if str(results_path) == "-" else check_results(batch, results_path, received_at, redo, manifest)
    for r in rows:
        check_common(r["church_id"], r, received_at)
    cands = [] if str(candidates_path) == "-" else check_candidates(candidates_path, received_at)
    for level, where, msg in sorted(problems, key=lambda p: (p[0], p[1])):
        print(f"{level:5} {where:38} {msg}")
    print(f"\n{sum(p[0] == 'ERROR' for p in problems)} errors, {sum(p[0] == 'WARN' for p in problems)} warnings")
    if rows:
        summarize(rows)
    print(f"\nNew candidates: {len(cands)}; with street address: {sum(1 for r in cands if r['street_address'])}; "
          f"found_via: {dict(Counter(r['found_via'] for r in cands))}")
    return 1 if any(p[0] == "ERROR" for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
