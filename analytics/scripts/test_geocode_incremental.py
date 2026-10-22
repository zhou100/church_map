"""A ledger result is reused only for the exact address it was made from."""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import geocode_incremental as gi
from geocode_incremental import cell, key


class LedgerTests(unittest.TestCase):
    def row(self, **overrides):
        return {"geo_id": "candidate:test", "street": "22 Waller Street", "city": "San Francisco",
                "state": "CA", "zip": "94102", **overrides}

    def test_same_address_reuses(self):
        self.assertEqual(key(self.row()), key(self.row(name="Renamed", profile_ready="t")))

    def test_any_address_part_change_needs_fresh_census_work(self):
        for part, value in (("street", "24 Waller Street"), ("city", "Daly City"), ("zip", ""), ("state", "NV")):
            with self.subTest(part=part):
                self.assertNotEqual(key(self.row()), key(self.row(**{part: value})))

    def test_other_subject_never_borrows_a_result(self):
        self.assertNotEqual(key(self.row()), key(self.row(geo_id="church:1")))

    def test_export_cells_match_psql_csv(self):
        self.assertEqual([cell(None), cell(True), cell(False), cell("x")], ["", "t", "f", "x"])


class PublishTests(unittest.TestCase):
    """Review of e734ff1: output and receipt are one publication; a torn one binds nothing."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name, path in (("EXPORTS", self.dir), ("OUTPUT", self.dir / "geocode_output.csv"),
                           ("RECEIPT", self.dir / "geocode_reconciliation.json")):
            patcher = mock.patch.object(gi, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.input = self.dir / "geocode_input_aaaa.csv"
        self.input.write_text("geo_id,street,city,state,zip\ncandidate:X-1,100 Main St,San Mateo,CA,94401\n")
        self.row = {k: "" for k in gi.FIELDS}

    def test_a_complete_publication_binds_its_input(self):
        gi.publish([{**self.row, "geo_id": "candidate:X-1"}], {"input_sha256": gi.sha256(self.input)})
        self.assertEqual(gi.bound_input(), self.input)
        self.assertFalse(list(self.dir.glob("*.tmp")))

    def test_an_interrupted_publication_binds_nothing(self):
        gi.publish([{**self.row, "geo_id": "candidate:X-1"}], {"input_sha256": gi.sha256(self.input)})
        meta = self.dir / "geocode_census_metadata.json"  # the old fallback must not rescue it
        meta.write_text(json.dumps({"input_sha256": gi.sha256(self.input)}))
        real, calls = os.replace, []

        def replace_then_die(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise KeyboardInterrupt
            real(src, dst)
        with mock.patch.object(gi.os, "replace", replace_then_die), self.assertRaises(KeyboardInterrupt):
            gi.publish([{**self.row, "geo_id": "candidate:X-1", "status": "ok", "latitude": "1"}],
                       {"input_sha256": gi.sha256(self.input)})
        self.assertIsNone(gi.bound_input())


class DirectionProofTests(unittest.TestCase):
    """Direction-only rows: accepted only when the county's complete ranges leave no
    competing directional segment for the house in the input ZIP."""

    ENTRY = {"street": "306 W Eaton Ave", "zip": "95376"}
    RAW = ["candidate:X-1", "306 W Eaton Ave, Tracy, CA, 95376", "Match", "Exact",
           "306 EATON AVE, TRACY, CA, 95376", "-121.43,37.73", "111", "L", "06", "077", "1", "1"]

    def tables(self, extra=()):
        names = {"111": ["Eaton Ave"], "222": ["E Eaton Ave"], "333": ["Grant Line Rd"]}
        ranges = [{"TLID": "111", "FROMHN": "300", "TOHN": "398", "ZIP": "95376"},
                  {"TLID": "333", "FROMHN": "300", "TOHN": "398", "ZIP": "95376"},  # other street
                  {"TLID": "111", "FROMHN": "301", "TOHN": "399", "ZIP": "95376"}]  # odd side
        return names, ranges + list(extra)

    def test_the_only_segment_covering_the_house_proves_it(self):
        proven, ev = gi.prove_direction(self.ENTRY, self.RAW, self.tables())
        self.assertTrue(proven)
        self.assertEqual(ev["segments_covering_house"], ["111"])

    def test_a_competing_directional_segment_blocks_it(self):
        extra = [{"TLID": "222", "FROMHN": "300", "TOHN": "350", "ZIP": "95376"}]
        proven, ev = gi.prove_direction(self.ENTRY, self.RAW, self.tables(extra))
        self.assertFalse(proven)
        self.assertEqual(ev["segments_covering_house"], ["111", "222"])

    def test_a_census_zip_other_than_the_input_zip_blocks_it(self):
        proven, _ = gi.prove_direction({**self.ENTRY, "zip": "95377"}, self.RAW, self.tables())
        self.assertFalse(proven)

    def test_a_segment_in_another_zip_does_not_compete(self):
        extra = [{"TLID": "222", "FROMHN": "300", "TOHN": "350", "ZIP": "95304"}]
        self.assertTrue(gi.prove_direction(self.ENTRY, self.RAW, self.tables(extra))[0])


    def test_a_post_direction_contradicting_a_prefix_stays_in_review(self):
        # Review of 59b5cad: "100 N Main St" against "100 MAIN ST S" read as N vs nothing.
        raw = list(self.RAW)
        raw[4] = "100 MAIN ST S, TRACY, CA, 95376"
        names = {"111": ["Main St S"]}
        ranges = [{"TLID": "111", "FROMHN": "100", "TOHN": "198", "ZIP": "95376"}]
        proven, ev = gi.prove_direction({"street": "100 N Main St", "zip": "95376"}, raw, (names, ranges))
        self.assertFalse(proven)
        self.assertEqual((ev["input_direction"], ev["census_direction"], ev["contradicts"]), (["N"], ["S"], True))

    def test_an_intercardinal_post_direction_contradicting_a_prefix_stays_in_review(self):
        # Review of 80a54e5: "MAIN ST SW" read as no direction, so N vs SW passed.
        raw = list(self.RAW)
        raw[4] = "100 MAIN ST SW, TRACY, CA, 95376"
        names = {"111": ["Main St SW"]}
        ranges = [{"TLID": "111", "FROMHN": "100", "TOHN": "198", "ZIP": "95376"}]
        proven, ev = gi.prove_direction({"street": "100 N Main St", "zip": "95376"}, raw, (names, ranges))
        self.assertFalse(proven)
        self.assertEqual((ev["input_direction"], ev["census_direction"], ev["contradicts"]), (["N"], ["SW"], True))

    def test_intercardinal_spellings_read_the_same(self):
        for street in ("100 Main St SW", "100 Main St Southwest", "100 S.W. Main St", "100 South West Main St"):
            with self.subTest(street=street):
                self.assertEqual(gi.stated_directions(street), {"SW"})
        self.assertEqual(gi.stated_directions("100 N Main St"), {"N"})
        self.assertEqual(gi.stated_directions("100 Main St Suite S"), set())

    def test_an_alphanumeric_house_number_stays_in_review_without_raising(self):
        # Review of 59b5cad: competing_ranges int()s the house number; "306A" aborted the run.
        raw = list(self.RAW)
        raw[4] = "306A EATON AVE, TRACY, CA, 95376"
        proven, ev = gi.prove_direction({"street": "306A W Eaton Ave", "zip": "95376"}, raw, self.tables())
        self.assertFalse(proven)
        self.assertEqual((ev["house_number"], ev["house_number_supported"]), ("306a", False))

    def test_two_stated_directions_that_disagree_stay_in_review(self):
        raw = list(self.RAW)
        raw[4] = "306 E EATON AVE, TRACY, CA, 95376"
        names, ranges = self.tables()
        names["111"] = ["E Eaton Ave"]
        proven, ev = gi.prove_direction(self.ENTRY, raw, (names, ranges))
        self.assertFalse(proven)
        self.assertTrue(ev["contradicts"])
        self.assertEqual((ev["input_direction"], ev["census_direction"]), (["W"], ["E"]))

    def test_a_direction_only_census_states_can_be_proven(self):
        raw = list(self.RAW)
        raw[4] = "3700 N PACIFIC AVE, STOCKTON, CA, 95204"
        names = {"111": ["N Pacific Ave"]}
        ranges = [{"TLID": "111", "FROMHN": "3700", "TOHN": "3798", "ZIP": "95204"}]
        proven, ev = gi.prove_direction({"street": "3700 Pacific Avenue", "zip": "95204"}, raw, (names, ranges))
        self.assertTrue(proven)
        self.assertFalse(ev["contradicts"])


class ReclassifyKeepsDirectionProofsTests(unittest.TestCase):
    """Review of 59b5cad: --reclassify reset a proven direction-only row to needs_review and
    the saved review then kept it there for good. The whole main() sequence, offline."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        history = self.dir / "geocode_history"
        history.mkdir()
        for name, path in (("EXPORTS", self.dir), ("OUTPUT", self.dir / "geocode_output.csv"),
                           ("RECEIPT", self.dir / "geocode_reconciliation.json"), ("HISTORY", history),
                           ("LEDGER", self.dir / "geocode_ledger.csv"),
                           ("DIRECTION_REVIEWS", self.dir / "geocode_direction_reviews.json")):
            patcher = mock.patch.object(gi, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        tables = ({"111": ["Eaton Ave"]}, [{"TLID": "111", "FROMHN": "300", "TOHN": "398", "ZIP": "95376"}],
                  {"tl_2026_06077_addr.zip": "a" * 64, "tl_2026_06077_featnames.zip": "b" * 64})
        patcher = mock.patch.object(gi, "county_tables", lambda county, fetch, cache: tables)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.row = {"geo_id": "candidate:X-1", "name": "Grace", "street": "306 W Eaton Ave", "city": "Tracy",
                    "state": "CA", "zip": "95376", "current_lat": "", "current_lon": "", "reason": "new_congregation",
                    "profile_ready": "t"}
        self.input = self.dir / "geocode_input_aaaa.csv"
        gi.write_csv(self.input, gi.INPUT_COLS, [self.row])
        raw = ["candidate:X-1", "306 W Eaton Ave, Tracy, CA, 95376", "Match", "Exact", "306 EATON AVE, TRACY, CA, 95376",
               "-121.430000,37.730000", "111", "L", "06", "077", "1", "1"]
        self.raw_name = "census_20261022T000000Z_raw.csv"
        raw_path = history / self.raw_name
        with raw_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f, quoting=csv.QUOTE_ALL).writerow(raw)
        (history / self.raw_name.replace("_raw.csv", "_meta.json")).write_text(json.dumps(
            {"raw_sha256": gi.sha256(raw_path), "geocoded_at": "2026-10-22T00:00:00+00:00"}))
        entry = gi.classify(self.row, raw, "2026-10-22T00:00:00+00:00")
        self.assertEqual(entry["status"], "needs_review")
        gi.write_csv(gi.LEDGER, gi.LEDGER_COLS, [{**{k: self.row[k] for k in gi.ADDRESS}, **entry, "source": self.raw_name}])

    def status(self, *argv):
        with mock.patch.object(sys, "argv", ["geocode_incremental.py", "--input", str(self.input), *argv]), \
                mock.patch("builtins.print"):
            self.assertEqual(gi.main(), 0)
        return next(csv.DictReader(gi.OUTPUT.open(encoding="utf-8")))["status"]

    def test_first_review_then_reclassify_then_an_ordinary_run_all_end_ok(self):
        self.assertEqual(self.status(), "ok")
        self.assertEqual(self.status("--reclassify", self.raw_name), "ok")
        self.assertEqual(self.status(), "ok")
        reviews = json.loads(gi.DIRECTION_REVIEWS.read_text())
        self.assertTrue(reviews and all(v["proven"] for v in reviews.values()))


if __name__ == "__main__":
    unittest.main()
