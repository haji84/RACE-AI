"""Fake LZH archive, fake parsed B records. No network and no raw publication."""
import unittest
from scripts.p0_one_shot_real_b_parse import probe,TARGET
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":"refs/heads/p0-b-parse-smoke-20261024",
     "RACE_AI_B_PARSE_ALLOWED":"20261022-B-PARSER","GITHUB_SHA":"a"*40}
class R:
 def __init__(self):
    self.status=200
    self.headers={"Content-Type":"application/x-lzh-compressed","Date":"Thu, 22 Oct 2026 00:00:00 GMT"}
 def __enter__(self):return self
 def __exit__(self,*x):return False
 def geturl(self):return TARGET
 def read(self,n):return b"\x16\x00-lh5-"+b"Z"*120
class O:
 def __init__(self):self.calls=0
 def open(self,req,timeout):
    assert req.full_url==TARGET and timeout==10
    self.calls+=1
    return R()
def parsed(_bytes):
    rid="20261022-11-01"
    return ([{"race_id":rid,"lane":x} for x in range(1,7)],
            {(rid,x):{"national_win_rate":5.2} for x in range(1,7)},
            {rid:"2026-10-22T10:24:00+09:00"})
class OneShotParserTests(unittest.TestCase):
 def test_gated_before_any_http(self):
    client=O();data=dict(ENV,GITHUB_REF="refs/heads/main")
    with self.assertRaises(RuntimeError):probe(env=data,opener=client,extract=lambda *_:b"x",parser=parsed)
    self.assertEqual(client.calls,0)
 def test_parser_evidence_only(self):
    client=O()
    result=probe(env=ENV,opener=client,extract=lambda *_:b"synthetic expanded",parser=parsed)
    self.assertEqual(client.calls,1)
    self.assertEqual(result["status"],"REAL_OFFICIAL_B_FORMAT_ACCEPTED_AUDIT_ONLY")
    self.assertEqual(result["race_count"],1)
    self.assertEqual(result["detailed_stat_rows"],6)
    self.assertFalse(result["model_feature_ready"])
    self.assertFalse(result["raw_archive_retained"])
 def test_missing_stats_rejected(self):
    client=O()
    report=probe(env=ENV,opener=client,extract=lambda *_:b"fake",
                 parser=lambda *_:([{"race_id":"r","lane":1}],{},{"r":"10:24"}))
    self.assertEqual(report["status"],"REAL_B_TRANSPORT_OR_PARSE_UNVERIFIED")
if __name__=="__main__":unittest.main()
