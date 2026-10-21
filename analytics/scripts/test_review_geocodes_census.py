"""Offline safeguards for the bounded Census review."""
import copy
import unittest

from review_geocodes_census import IDS, review_row, competing_ranges


def example(county=False):
    row = dict(geo_id="candidate:C-015", street="900 Cabrillo Highway North",
               city="Half Moon Bay", state="CA", zip="94019", current_lat="", current_lon="")
    address="900 N CABRILLO HWY, HALF MOON BAY, CA, 94019"
    comp=dict(fromAddress="998", toAddress="800", city="HALF MOON BAY", state="CA",
              zip="94019", streetName="CABRILLO", suffixType="HWY")
    geo={"Counties":[{"STATE":"06", "COUNTY":"081", "GEOID":"06081"}],
         "Incorporated Places":[{"NAME":"Half Moon Bay city"}]}
    if county:
        row.update(geo_id="candidate:D-145", street="25100 Skyland Road", city="Los Gatos", zip="95033")
        address="25100 SKYLAND RD, LOS GATOS, CA, 95033"
        comp.update(fromAddress="24964", toAddress="25198", city="LOS GATOS", zip="95033", streetName="SKYLAND", suffixType="RD")
        geo={"Counties":[{"STATE":"06", "COUNTY":"087", "GEOID":"06087"}],
             "County Subdivisions":[{"NAME":"Summit Road CCD"}]}
    raw=[row["geo_id"], "", "Match", "Exact" if county else "Non_Exact", address,
         "-122.43,37.47", "1234", "L", "06", "087" if county else "081", "123456", "1000"]
    match={"matchedAddress":address, "tigerLine":{"tigerLineId":"1234", "side":"L"},
           "coordinates":{"x":-122.43, "y":37.47}, "addressComponents":comp, "geographies":geo}
    data={"result":{"input":{"address":{k:row[k] for k in ("street","city","state","zip")}},
                    "addressMatches":[match]}}
    return row, raw, data


class CensusReviewTests(unittest.TestCase):
    def test_range_proof_retains_a_competing_directional_segment(self):
        names={"selected":["Winchester Blvd"],"competitor":["N Winchester Blvd"]}
        ranges=[dict(TLID=id,ZIP="95008",FROMHN="1800",TOHN="1900",SIDE="L") for id in names]
        found=competing_ranges("1870 S Winchester Blvd","95008",names,ranges)
        self.assertEqual({r["range"]["TLID"] for r in found},{"selected","competitor"})

    def test_range_check_respects_zip_suffix_and_parity(self):
        names={"right":["Winchester Blvd"],"other_zip":["N Winchester Blvd"],
               "other_suffix":["S Winchester Ave"],"odd":["N Winchester Blvd"]}
        ranges=[dict(TLID=id,ZIP="95008",FROMHN="1800",TOHN="1900",SIDE="L") for id in names]
        ranges[1]["ZIP"]="95128"
        ranges[3].update(FROMHN="1801",TOHN="1899")
        found=competing_ranges("1870 S Winchester Blvd","95008",names,ranges)
        self.assertEqual([r["range"]["TLID"] for r in found],["right"])

    def test_direction_relocation_with_same_direction_is_accepted(self):
        row,raw,data=example()
        self.assertEqual(review_row(row,raw,data)["status"],"ok")

    def test_north_is_not_equated_to_south(self):
        row,raw,data=example()
        row["street"]="900 Cabrillo Highway South"
        data["result"]["input"]["address"]["street"]=row["street"]
        self.assertEqual(review_row(row,raw,data)["status"],"needs_review")

    def test_missing_direction_is_not_ignored(self):
        row,raw,data=example()
        row["street"]="900 Cabrillo Highway"
        data["result"]["input"]["address"]["street"]=row["street"]
        self.assertEqual(review_row(row,raw,data)["status"],"needs_review")

    def test_county_exception_is_specific_to_verified_unincorporated_point(self):
        row,raw,data=example(county=True)
        self.assertEqual(review_row(row,raw,data)["status"],"ok")
        data["result"]["addressMatches"][0]["geographies"]["Incorporated Places"]=[{"NAME":"Other city"}]
        self.assertEqual(review_row(row,raw,data)["status"],"needs_review")

    def test_county_rule_does_not_accept_arbitrary_ids(self):
        row,raw,data=example(county=True)
        row["geo_id"]="candidate:unreviewed"
        self.assertEqual(review_row(row,raw,data)["status"],"needs_review")

    def test_wrong_house_number_fails_closed(self):
        row,raw,data=example()
        row["street"]="1900 Cabrillo Highway North"
        data["result"]["input"]["address"]["street"]=row["street"]
        with self.assertRaises(AssertionError):
            review_row(row,raw,data)

    def test_query_must_preserve_input_address(self):
        row,raw,data=example()
        data["result"]["input"]["address"]["street"]="900 Other Street"
        with self.assertRaises(AssertionError):
            review_row(row,raw,data)

    def test_two_candidates_never_selects_a_pin(self):
        row,raw,data=example()
        data["result"]["addressMatches"].append(copy.deepcopy(data["result"]["addressMatches"][0]))
        out=review_row(row,raw,data)
        self.assertEqual((out["status"],out["latitude"],out["longitude"]),("needs_review","",""))

    def test_segment_mismatch_fails_closed(self):
        row,raw,data=example()
        data["result"]["addressMatches"][0]["tigerLine"]["tigerLineId"]="9999"
        with self.assertRaises(AssertionError):
            review_row(row,raw,data)

    def test_removed_rows_are_out_of_scope(self):
        self.assertEqual(len(IDS),9)
        self.assertTrue({"candidate:C-054","candidate:D-059"}.isdisjoint(IDS))


if __name__=="__main__":
    unittest.main()
