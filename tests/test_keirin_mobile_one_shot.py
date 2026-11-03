"""Isolated no-network tests. The provider's content is always untrusted."""
import unittest
from datetime import datetime,timezone
from urllib.error import HTTPError
from race_ai.keirin_mobile_one_shot import (
    ACK, MobileProbeError, page_url, probe_one, MAX_BODY
)

class _Response:
    def __init__(self,url,body,status=200,mime="text/html; charset=utf-8"):
        self.url=url;self.body=body;self.status=status;self.headers={"Content-Type":mime}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.body[:n]

class _Client:
    def __init__(self,body,status=200,redirect=False,mime="text/html; charset=utf-8"):
        self.body=body;self.status=status;self.redirect=redirect;self.mime=mime;self.calls=0
    def open(self,request,timeout):
        self.calls+=1
        url=request.full_url+("/redirected" if self.redirect else "")
        return _Response(url,self.body,self.status,self.mime)

GOOD="2026年10月22日 小田原 2R 結果 3連単 1-6-7 2,670円 払戻".encode("utf-8")

class FormatTests(unittest.TestCase):
    def test_canonical_path(self):
        self.assertEqual(page_url("20261022",36,2),
          "https://www.keirin-mobile.jp/New/races/20261022/36/02/")
    def test_legacy_source_path_and_research_only(self):
        from race_ai.keirin_mobile_one_shot import legacy_page_url
        self.assertEqual(legacy_page_url("20261103",36,1),
            "https://www.keirin-mobile.jp/top/result.php?date=20261103&jcode=36&race=01")
        client=_Client(GOOD)
        report=probe_one("20261022",36,2,acknowledgement=ACK,
                         opener=client,route="legacy")
        self.assertIn("/top/result.php?",report["source_url"])
        self.assertFalse(report["result_officially_authenticated"])

    def test_unknown_route_rejected_without_network(self):
        client=_Client(GOOD)
        with self.assertRaisesRegex(MobileProbeError,"UNKNOWN_SOURCE_ROUTE"):
            probe_one("20261022",36,2,acknowledgement=ACK,
                      opener=client,route="unsafe")
        self.assertEqual(client.calls,0)

    def test_invalid_path_input_never_networks(self):
        for args in [("20260230",36,2),("20261022",0,2),
                     ("20261022",36,13),("20261022",True,2)]:
            with self.assertRaises(MobileProbeError):page_url(*args)
    def test_no_ack_is_zero_network(self):
        client=_Client(GOOD)
        with self.assertRaisesRegex(MobileProbeError,"EXPLICIT_ONE_SHOT"):
            probe_one("20261022",36,2,acknowledgement="",opener=client)
        self.assertEqual(client.calls,0)
    def test_marker_only_not_verified_official(self):
        client=_Client(GOOD)
        report=probe_one("20261022",36,2,acknowledgement=ACK,opener=client,
                          observed_at=datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertEqual(client.calls,1)
        self.assertTrue(report["page_date_marker"])
        self.assertTrue(report["page_race_marker"])
        self.assertTrue(report["trifecta_label_present"])
        self.assertFalse(report["result_officially_authenticated"])
        self.assertFalse(report["model_training_rights_verified"])
        self.assertFalse(report["race_results_parsed"])
        self.assertFalse(report["forecast_generated"])
        self.assertFalse(report["raw_page_stored"])
    def test_candidate_triplet_and_payout(self):
        from race_ai.keirin_mobile_one_shot import extract_trifecta_candidate
        got=extract_trifecta_candidate("払戻 3連単 1-6-7 (5) 2,670円")
        self.assertEqual(got["triple"],[1,6,7])
        self.assertEqual(got["payout_100yen"],2670)
        self.assertEqual(got["state"],"ONE_UNVERIFIED_PROVIDER_CANDIDATE")
        self.assertFalse(probe_one("20261022",36,2,acknowledgement=ACK,
                                   opener=_Client(GOOD))["result_officially_authenticated"])

    def test_conflicting_payout_refused(self):
        from race_ai.keirin_mobile_one_shot import extract_trifecta_candidate
        got=extract_trifecta_candidate("3連単 1-6-7 2670円 3連単 2-5-1 9010円")
        self.assertIsNone(got["triple"])

    def test_no_payout_does_not_infer_loss(self):
        from race_ai.keirin_mobile_one_shot import extract_trifecta_candidate
        got=extract_trifecta_candidate("払戻待ち 3連単")
        self.assertEqual(got["state"],"NO_UNAMBIGUOUS_TRIFECTA")
        self.assertIsNone(got["payout_100yen"])

    def test_no_result_is_not_final(self):
        p=probe_one("20261022",36,2,acknowledgement=ACK,
          opener=_Client(b"<p>not published yet</p>"))
        self.assertFalse(p["trifecta_label_present"])
        self.assertFalse(p["result_officially_authenticated"])
    def test_http_error_preserved_only_status(self):
        class _Refusing:
            def open(self,request,timeout):
                raise HTTPError(request.full_url,403,"sensitive details",None,None)
        with self.assertRaisesRegex(MobileProbeError,"PROVIDER_HTTP_403") as ctx:
            probe_one("20261022",36,2,acknowledgement=ACK,opener=_Refusing())
        self.assertNotIn("sensitive",str(ctx.exception))
    def test_wrong_mime_and_redirect_blocked(self):
        for cl in (_Client(GOOD,redirect=True),_Client(GOOD,mime="application/json")):
            with self.assertRaises(MobileProbeError):
                probe_one("20261022",36,2,acknowledgement=ACK,opener=cl)
    def test_body_size_limit(self):
        with self.assertRaisesRegex(MobileProbeError,"PROVIDER_BODY_SIZE_REJECTED"):
            probe_one("20261022",36,2,acknowledgement=ACK,
                      opener=_Client(b"X"*(MAX_BODY+1)))
    def test_cp932(self):
        raw='<html><meta charset="Shift_JIS">2026年10月22日 2R 結果</html>'.encode("cp932")
        p=probe_one("20261022",36,2,acknowledgement=ACK,
                    opener=_Client(raw,mime="text/html"))
        self.assertTrue(p["page_date_marker"])
        self.assertTrue(p["page_race_marker"])

if __name__=="__main__":unittest.main()
