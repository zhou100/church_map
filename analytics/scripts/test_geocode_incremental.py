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


if __name__ == "__main__":
    unittest.main()
