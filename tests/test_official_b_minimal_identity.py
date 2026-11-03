"""Synthetic raw parser outputs, no protected archive in the repository."""
import copy,unittest
from race_ai.official_b_minimal_identity import to_audit,MinimalOfficialBError
URL="https://www1.mbrace.or.jp/od2/B/202610/b261022.lzh"
def rows():
    return [{"race_id":f"20261022-11-{r:02d}","lane":n,"racer_id":str(4000+n+r*10)}
            for r in (1,2) for n in range(1,7)]
def output(data):
    return to_audit(data,event_date_jst="2026-10-22",source_url=URL,
        archive_sha256="a"*64,observed_at_claimed="2026-10-24T08:00:00+09:00",
        rights_ref="REVIEW_PENDING")
class AdapterTests(unittest.TestCase):
 def test_six_real_layout_members_per_race_as_audit_only(self):
    result=output(rows())
    self.assertEqual(len(result["records"]),2)
    self.assertEqual(result["records"][0]["race_id"],"boat:2026-10-22:boatrace-jcd-11:1")
    self.assertEqual(result["minimal_b_real_source_audit"]["entrant_rows_count"],12)
    self.assertEqual(result["minimal_b_real_source_audit"]["venue_count"],1)
    self.assertTrue(all(x["sales_cutoff_at"] is None and x["prediction"] is None for x in result["records"]))
    self.assertFalse(result["minimal_b_real_source_audit"]["model_feature_ready"])
 def test_missing_lane_and_duplicate_roster_block(self):
    with self.assertRaises(MinimalOfficialBError):output(rows()[:-1])
    r=rows();r[1]["lane"]=1
    with self.assertRaisesRegex(MinimalOfficialBError,"duplicate lane"):output(r)
 def test_wrong_date_or_alias_block(self):
    wrong=rows();wrong[0]["race_id"]="20261023-11-01"
    with self.assertRaisesRegex(MinimalOfficialBError,"day mismatch"):output(wrong)
    with self.assertRaisesRegex(MinimalOfficialBError,"source URL mismatch"):
      to_audit(rows(),event_date_jst="2026-10-22",source_url="https://fake.invalid",
               archive_sha256="a"*64,observed_at_claimed="2026-10-24T08:00:00+09:00",
               rights_ref="REVIEW_PENDING")
if __name__=="__main__":unittest.main()
