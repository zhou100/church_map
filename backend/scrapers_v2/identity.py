"""Offline identity evidence, not independent confirmation of a congregation.

Only a single, same-site Church JSON-LD entity bound by its stated name is
comparable. Generic Organization nodes (vendors), multiple campuses, absent
fields and malformed metadata abstain. Both address AND phone must contradict
before blocking: a different office address or second phone alone is not enough.
No network, database writes, or model calls. Consumers must use allow_extraction
and must not relabel a match as verified activity or a verified worship location.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

VERSION = "identity.v1"


def _words(value: object) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold())) if isinstance(value, str) else ""


def _host(url: object) -> str:
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return ""
        host = (parsed.hostname or "").lower().removeprefix("www.")
        return host if "." in host else ""
    except ValueError:
        return ""


def _phone(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.removeprefix("tel:").strip()
    if not re.fullmatch(r"\+?[\d ().-]+", value):
        return ""  # extensions / multiple numbers need an explicit interpretation
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _address(value: object) -> tuple[str, str, str] | None:
    if not isinstance(value, dict):
        return None
    street = _words(value.get("streetAddress"))
    city = _words(value.get("addressLocality"))
    state = _words(value.get("addressRegion"))
    if state == "california":
        state = "ca"
    # Keep units and directions; never equate 23 with 123 or E with W.
    if not re.match(r"^\d+[a-z]?\s+\S", street) or not city or not state:
        return None
    aliases = {"street": "st", "road": "rd", "avenue": "ave", "boulevard": "blvd",
               "drive": "dr", "lane": "ln", "court": "ct"}
    street = " ".join(aliases.get(word, word) for word in street.split())
    return street, city, state


class _JSONLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.blocks.append("".join(self.current))
            self.current = None


def _nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _nodes(item)
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from _nodes(item)


@dataclass(frozen=True)
class IdentityResult:
    verdict: str
    address_matches: bool | None
    phone_matches: bool | None
    reason: str
    raw_sha256: str
    reference_sha256: str
    source_url: str
    fetched_at: str
    checker_version: str = VERSION

    @property
    def allow_extraction(self) -> bool:
        return self.verdict != "conflict"

    def report(self) -> dict:
        return {**asdict(self), "allow_extraction": self.allow_extraction}


def check_identity(raw_html: bytes, reference: dict, *, source_url: str,
                   fetched_at: str) -> IdentityResult:
    """Compare one archived page with one input reference, retaining identity hashes.

    reference: name, website, address (schema.org PostalAddress), phone. The
    caller must supply the intended congregation/campus, not a merged household
    or denomination. Missing comparable evidence is explicitly nonblocking.
    """
    provenance = dict(raw_sha256=hashlib.sha256(raw_html).hexdigest(),
                      reference_sha256=hashlib.sha256(json.dumps(
                          reference, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")).encode()).hexdigest(),
                      source_url=source_url, fetched_at=fetched_at)

    def result(verdict, reason, address=None, phone=None):
        return IdentityResult(verdict, address, phone, reason, **provenance)

    expected_host = _host(reference.get("website"))
    if not expected_host or _host(source_url) != expected_host:
        return result("no_comparable", "source_not_bound_to_reference")
    parser = _JSONLD()
    try:
        parser.feed(raw_html.decode("utf-8"))
    except (UnicodeError, ValueError):
        return result("no_comparable", "unreadable_html")
    churches = []
    for block in parser.blocks:
        try:
            nodes = list(_nodes(json.loads(block)))
        except (ValueError, RecursionError):
            return result("no_comparable", "malformed_jsonld")
        for node in nodes:
            kinds = node.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if not isinstance(kinds, list):
                continue
            if any(k in {"Church", "https://schema.org/Church", "http://schema.org/Church"} for k in kinds if isinstance(k, str)):
                churches.append(node)
    # Do not choose one campus just because it happens to match first.
    if len(churches) != 1:
        return result("no_comparable", "missing_or_multiple_church_entities")
    church = churches[0]
    name = _words(reference.get("name"))
    if not name or _words(church.get("name")) != name or _host(church.get("url")) != expected_host:
        return result("no_comparable", "entity_not_bound_to_reference")
    expected_address, observed_address = _address(reference.get("address")), _address(church.get("address"))
    expected_phone, observed_phone = _phone(reference.get("phone")), _phone(church.get("telephone"))
    address = expected_address == observed_address if expected_address and observed_address else None
    phone = expected_phone == observed_phone if expected_phone and observed_phone else None
    if address is False and phone is False:
        return result("conflict", "address_and_phone_contradict", address, phone)
    # Conflicting channels must not be advertised as a resolved identity.
    if address is False or phone is False:
        return result("no_comparable", "mixed_or_incomplete_evidence", address, phone)
    if address is True or phone is True:
        return result("match", "comparable_evidence_matches", address, phone)
    return result("no_comparable", "missing_comparable_fields", address, phone)
