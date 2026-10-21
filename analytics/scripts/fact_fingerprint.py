"""Fingerprint of one Muse fact as it was re-checked (stdlib only).

recheck_sources.py records it next to each verdict; build_seeds.py recomputes it
from the row it is about to publish. A verdict only counts when the two agree, so
a later correction to the value, the source URL or the excerpt can never inherit
an earlier "verified" (review of PR #41, issue 2).

Computed on the raw returned row, before any sanitizing.
"""
from __future__ import annotations

import hashlib
import json

FACT_FIELDS = {
    "status": ("status",),
    "address": ("street_address", "city", "zip"),
    "phone": ("phone",),
    "service": ("service_times_verbatim", "service_languages"),
    "kids": ("kids_program_verbatim",),
    "candidate": ("street_address", "city", "zip"),  # v2 candidates: one source for the row
    # Task W answers: is this the worship location, and (if not as recorded) where is it
    "worship": ("address_is_worship_location", "worship_street_address", "worship_city", "worship_zip"),
}


def source_of(row: dict, group: str) -> tuple[str, str]:
    """(source_url, excerpt) for a fact group, in either return format."""
    if group in ("candidate", "worship"):
        return row.get("source_url", ""), row.get("excerpt", "")
    return row.get(f"{group}_source_url", ""), row.get(f"{group}_excerpt", "")


def fact_fingerprint(row: dict, group: str) -> str:
    url, excerpt = source_of(row, group)
    values = [(row.get(f) or "").strip() for f in FACT_FIELDS[group]]
    payload = json.dumps([group, values, url.strip(), excerpt], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
