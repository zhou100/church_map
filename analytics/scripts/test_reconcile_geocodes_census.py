"""Prevent reusing a stale pin after a sourced address-part correction."""
import unittest

from reconcile_geocodes_census import changed_rows


class ReconciliationTests(unittest.TestCase):
    def test_zip_correction_requires_fresh_census_work(self):
        row=dict(geo_id="candidate:test",street="22 Waller Street",city="San Francisco",state="CA",zip="94102")
        raw={row["geo_id"]:[row["geo_id"],"22 Waller Street, San Francisco, CA, ","Tie"]}
        self.assertEqual(changed_rows([row],raw),[row])

    def test_new_row_is_not_silently_missing(self):
        row=dict(geo_id="candidate:new",street="10 Test St",city="Test",state="CA",zip="90000")
        self.assertEqual(changed_rows([row],{}),[row])

    def test_unchanged_rows_are_not_resubmitted(self):
        row=dict(geo_id="candidate:same",street="10 Test St",city="Test",state="CA",zip="90000")
        raw={row["geo_id"]:[row["geo_id"],"10 Test St, Test, CA, 90000","Match"]}
        self.assertEqual(changed_rows([row],raw),[])


if __name__=="__main__":
    unittest.main()
