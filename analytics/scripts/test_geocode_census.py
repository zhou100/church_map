"""Offline safety tests: python -m unittest discover -s analytics/scripts -p test_geocode_census.py."""
import unittest

from geocode_census import classify, distance_m, street_key, validate_clusters, assess_street


def source(**overrides):
    return dict(geo_id="candidate:test", street="137 Dempsey Road", city="Milpitas",
                state="CA", zip="95035", current_lat="", current_lon="", **overrides)


def response(match="Exact", address="137 DEMPSEY RD, MILPITAS, CA, 95035", county="085", line="1234", side="L"):
    return ["candidate:test", "unchanged address", "Match", match, address,
            "-121.885959,37.432342", line, side, "06", county, "123456", "1001"]


class CensusSafetyTests(unittest.TestCase):
    def test_wrong_street_and_suffix_always_fail(self):
        for matched in ("101 Del Monte Ave, Los Altos, CA, 94022", "101 El Monte Ct, Los Altos, CA, 94022"):
            self.assertEqual(assess_street(matched,"101 N El Monte Ave",direction_proven=True)[0],"failed")

    def test_direction_only_requires_explicit_range_proof(self):
        matched="1870 WINCHESTER BLVD, CAMPBELL, CA, 95008"
        self.assertEqual(assess_street(matched,"1870 S Winchester Blvd")[0],"needs_review")
        self.assertEqual(assess_street(matched,"1870 S Winchester Blvd",direction_proven=True)[0],"ok")

    def test_shared_validator_handles_name_abbreviations(self):
        self.assertEqual(assess_street("10 ST LAWRENCE AVE, TEST CITY, CA", "10 Saint Lawrence Avenue")[0],"ok")

    def test_tie_does_not_choose_coordinates(self):
        out = classify(source(), ["candidate:test", "address", "Tie"], "now")
        self.assertEqual((out["status"], out["match_type"], out["latitude"]), ("needs_review", "Tie", ""))

    def test_no_match_is_failed(self):
        out = classify(source(), ["candidate:test", "address", "No_Match"], "now")
        self.assertEqual((out["status"], out["match_type"], out["longitude"]), ("failed", "No_Match", ""))

    def test_exact_with_wrong_house_number_is_withheld(self):
        out = classify(source(), response(address="138 DEMPSEY RD, MILPITAS, CA, 95035"), "now")
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["latitude"], "")

    def test_non_exact_same_street_is_accepted(self):
        out = classify(source(), response(match="Non_Exact"), "now")
        self.assertEqual(out["status"], "ok")

    def test_wrong_county_is_withheld(self):
        out = classify(source(), response(county="081"), "now")
        self.assertEqual(out["status"], "needs_review")

    def test_unknown_city_without_zip_or_city_proof_fails_closed(self):
        row = source()
        row["city"] = "Unknown City"
        row["zip"] = ""
        self.assertEqual(classify(row, response(), "now")["status"], "needs_review")
        row["zip"] = "95036"
        self.assertEqual(classify(row, response(), "now")["status"], "needs_review")

    def test_unknown_county_city_without_zip_accepted_on_same_city(self):
        row = source()
        row["city"] = "Petaluma"
        row["zip"] = ""
        out = classify(row, response(address="137 DEMPSEY RD, PETALUMA, CA, 94954", county="097"), "now")
        self.assertEqual(out["status"], "ok")
        self.assertIn("Census city PETALUMA equals input city", out["notes"])

    def test_unknown_city_needs_california(self):
        row = source()
        row["city"] = "Unknown City"
        bad = response()
        bad[8] = "32"
        self.assertEqual(classify(row, bad, "now")["status"], "needs_review")

    def test_unknown_city_accepted_on_matching_zip(self):
        row = source()
        row["city"] = "Unknown City"
        out = classify(row, response(), "now")
        self.assertEqual(out["status"], "ok")
        self.assertIn("Census ZIP 95035 equals input ZIP", out["notes"])

    def test_outside_california_is_withheld(self):
        bad = response()
        bad[5] = "-104.990000,39.740000"
        self.assertEqual(classify(source(), bad, "now")["status"], "needs_review")

    def test_missing_segment_evidence_is_withheld(self):
        for kwargs in ({"line": ""}, {"side": ""}):
            with self.subTest(kwargs=kwargs):
                out = classify(source(), response(**kwargs), "now")
                self.assertEqual(out["status"], "needs_review")
                self.assertEqual(out["longitude"], "")

    def test_different_address_collision_withheld_for_both(self):
        rows = {"a": source(), "b": source()}
        rows["b"]["street"] = "139 Dempsey Road"
        output = [{"geo_id": key, "status": "ok", "latitude": "37.432342", "longitude": "-121.885959"} for key in rows]
        self.assertEqual(validate_clusters(output, rows), [])
        self.assertTrue(all(o["status"] == "needs_review" and o["latitude"] == "" for o in output))

    def test_allowed_dempsey_normalization(self):
        self.assertEqual(street_key("137 Dempsey Road"), street_key("137 Dempsey Rd"))
        rows = {"candidate:D-107": source(), "candidate:CN-014": source()}
        rows["candidate:D-107"]["street"] = "137 Dempsey Rd"
        output = [{"geo_id": key, "status": "ok", "latitude": "37.432342", "longitude": "-121.885959"} for key in rows]
        self.assertEqual(len(validate_clusters(output, rows)), 1)
        self.assertTrue(all(o["status"] == "ok" for o in output))

    def test_direction_not_discarded(self):
        self.assertNotEqual(street_key("137 N Dempsey Rd"), street_key("137 Dempsey Rd"))
        self.assertEqual(street_key("137 North Dempsey Road"), street_key("137 N Dempsey Rd"))

    def test_distance_is_meters(self):
        self.assertEqual(distance_m(37, -122, 37, -122), 0)
        self.assertAlmostEqual(distance_m(0, 0, 0, 1), 111195.08, places=1)


if __name__ == "__main__":
    unittest.main()
