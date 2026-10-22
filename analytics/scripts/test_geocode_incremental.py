"""A ledger result is reused only for the exact address it was made from."""
import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
