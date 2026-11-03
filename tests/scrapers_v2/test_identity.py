"""Synthetic independent counterexamples; no private Muse returns or live calls."""
import copy
import json

import pytest

from backend.scrapers_v2.identity import check_identity

REFERENCE = {
    "name": "Example Church", "website": "https://example.org",
    "phone": "+1 (650) 555-0100",
    "address": {"streetAddress": "23 Main Street", "addressLocality": "Example City", "addressRegion": "CA"},
}
NODE = {"@type": "Church", "name": "Example Church", "url": "https://example.org/",
        "telephone": "650-555-0100", "address": REFERENCE["address"]}


def check(node=NODE, reference=REFERENCE, **kwargs):
    raw = ('<html><script type="application/ld+json">' + json.dumps(node) + '</script></html>').encode()
    return check_identity(raw, reference, source_url=kwargs.get("source_url", "https://example.org/contact"),
                          fetched_at="2026-11-03T23:00:00Z")


def test_match_is_evidence_not_worship_or_activity_verification():
    result = check()
    assert result.verdict == "match"
    assert result.address_matches is True and result.phone_matches is True
    assert result.allow_extraction
    assert "verified" not in result.report()


def test_missing_reference_fields_never_block():
    result = check(reference={"name": REFERENCE["name"], "website": REFERENCE["website"]})
    assert result.verdict == "no_comparable"
    assert result.address_matches is None and result.phone_matches is None
    assert result.allow_extraction


def test_explicit_two_channel_conflict_blocks():
    node = copy.deepcopy(NODE)
    node["address"]["streetAddress"] = "123 Main Street"
    node["telephone"] = "650-555-0199"
    result = check(node)
    assert result.verdict == "conflict"
    assert result.address_matches is False and result.phone_matches is False
    assert not result.allow_extraction


@pytest.mark.parametrize("field,value", [("telephone", "650-555-0199"),
    ("address", {"streetAddress": "123 Main Street", "addressLocality": "Example City", "addressRegion": "CA"})])
def test_office_address_or_alternate_phone_alone_does_not_block(field, value):
    result = check({**NODE, field: value})
    assert result.verdict == "no_comparable"
    assert result.allow_extraction


@pytest.mark.parametrize("node", [[], {"@type": "Organization", **{k: v for k, v in NODE.items() if k != "@type"}},
    [NODE, {**NODE, "name": "South Campus"}], {**NODE, "name": "Other Congregation"},
    {**NODE, "url": "https://vendor.example"}, {**NODE, "telephone": ["6505550100", "6505550199"], "address": []}])
def test_vendor_shared_building_multicampus_or_ambiguous_data_abstain(node):
    result = check(node)
    assert result.verdict == "no_comparable"
    assert result.allow_extraction


@pytest.mark.parametrize("street", ["Main Street", "", "PO Box 23"])
def test_incomplete_reference_address_is_unknown(street):
    reference = copy.deepcopy(REFERENCE)
    reference["address"]["streetAddress"] = street
    reference["phone"] = ""
    result = check(reference=reference)
    assert result.verdict == "no_comparable" and result.address_matches is None


def test_address_abbreviations_and_phone_country_prefix():
    node = copy.deepcopy(NODE)
    node["address"]["streetAddress"] = "23 Main St."
    node["address"]["addressRegion"] = "California"
    assert check(node).verdict == "match"


def test_malformed_or_unstructured_page_is_unknown():
    for raw in [b'<script type="application/ld+json">{broken}</script>', b'<p>23 Main Street</p>', b'\xff']:
        result = check_identity(raw, REFERENCE, source_url="https://example.org", fetched_at="2026-11-03")
        assert result.verdict == "no_comparable" and result.allow_extraction


def test_redirect_to_another_host_is_not_bound():
    assert check(source_url="https://different.example/contact").verdict == "no_comparable"


def test_changed_input_or_archive_invalidates_provenance():
    original = check()
    changed = check(reference={**REFERENCE, "phone": "6505550199"})
    assert original.reference_sha256 != changed.reference_sha256
    assert original.raw_sha256 == changed.raw_sha256
    assert check({**NODE, "telephone": "6505550199"}).raw_sha256 != original.raw_sha256


def test_report_omits_raw_private_fields():
    report = json.dumps(check().report())
    for private in [REFERENCE["name"], REFERENCE["phone"], "Main Street", "650-555-0100"]:
        assert private not in report


def test_private_manifest_reports_only_counts_and_does_not_overwrite(tmp_path, capsys):
    from scripts.check_website_identity import main
    raw = '<script type="application/ld+json">' + json.dumps(NODE) + '</script>'
    (tmp_path / "page.html").write_text(raw)
    manifest = tmp_path / "input.jsonl"
    manifest.write_text(json.dumps({"subject_id": "candidate-1", "html_path": "page.html",
        "source_url": "https://example.org", "fetched_at": "2026-11-03T23:00:00Z", "reference": REFERENCE}))
    output = tmp_path / "report.jsonl"
    args = ["--input", str(manifest), "--output", str(output)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"subjects": 1, "match": 1, "conflict": 0, "no_comparable": 0}
    report = output.read_bytes()
    assert json.loads(report)["allow_extraction"] is True
    assert main(args) == 1
    assert output.read_bytes() == report
    error = capsys.readouterr()
    assert str(output) not in error.err and REFERENCE["phone"] not in error.err


def test_duplicate_subjects_fail_without_partial_report(tmp_path, capsys):
    from scripts.check_website_identity import main
    (tmp_path / "page.html").write_text("<html></html>")
    row = json.dumps({"subject_id": "candidate-1", "html_path": "page.html", "reference": REFERENCE,
                      "source_url": "https://example.org", "fetched_at": "2026-11-03"})
    manifest, output = tmp_path / "input.jsonl", tmp_path / "report.jsonl"
    manifest.write_text(row + "\n" + row)
    assert main(["--input", str(manifest), "--output", str(output)]) == 1
    assert not output.exists()
    assert "candidate-1" not in capsys.readouterr().err
