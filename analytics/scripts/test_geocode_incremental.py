"""A ledger result is reused only for the exact address it was made from."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
