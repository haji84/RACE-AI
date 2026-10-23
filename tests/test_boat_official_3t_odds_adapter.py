"""Offline synthetic HTML fixtures for the official-style 3T odds grid.

Real BOATRACE HTML bytes and live publisher approval are NOT supplied.
"""
import hashlib
import hmac
import unittest

from race_ai.boat_official_3t_odds_adapter import normalize_html
from race_ai.comprehensive_four_sport_models import digest
from race_ai.permissioned_source_delivery import SourceDeliveryError, PermissionPolicy
from tests.test_permissioned_source_delivery import policy_doc, KEY, AT

SOURCE="https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20300115&jcd=01&rno=1"
RACE="20300115-01-01"
CUTOFF="2030-01-15T10:00:00+09:00"


def licensed(extra=("odds_display",), *, at=AT):
    doc=policy_doc()
    item={
      "source_ref":SOURCE,"rights_ref":"synthetic-fictional-odds-approval",
      "transport_url":SOURCE,
      "purposes":["analysis","private_storage","private_derived",*extra],
      "evidence_url":"https://example.org/fictional/odds-policy",
      "reviewer":"FICTIONAL_ONLY",
      "checked_at":"2030-01-10T00:00:00+09:00",
      "expires_at":"2030-02-01T00:00:00+09:00",
      "max_bytes":2000000,"max_requests":1,"max_cost_jpy":0
    }
    doc["policy"]["grants"].append(item)
    doc["signature"]=hmac.new(KEY,digest(doc["policy"]).encode("ascii"),hashlib.sha256).hexdigest()
    return PermissionPolicy(doc,KEY,at=at)


def html(odds_count=120, *, value_at=None, duplicate=False):
    values=[str(i+10) for i in range(odds_count)]
    if value_at:
        values[value_at[0]]=value_at[1]
    markup="<html><body><div class='table1'><p>other summary</p></div>"
    markup+="<div class='table1'><table><tbody>"
    for i in range(0,len(values),6):
        markup+="<tr>"+ "".join(f"<td class='oddsPoint'><span>{x}</span></td>"
                                  for x in values[i:i+6])+"</tr>"
    markup+="</tbody></table></div>"
    if duplicate:
        markup+=("<div class='table1'>"+
                 "".join(f"<td class='oddsPoint'>{x}</td>" for x in values)+
                 "</div>")
    return (markup+"</body></html>").encode("utf-8")


def go(data=None, **overrides):
    opts={
        "source_url":SOURCE,"race_id":RACE,"venue_name":"架空場",
        "cutoff_at":CUTOFF,"ingested_at":AT,
        "policy":licensed(),"rights_ref":"synthetic-fictional-odds-approval"
    }
    opts.update(overrides)
    return normalize_html(data or html(), **opts)


class RealOddsAdapterContractTests(unittest.TestCase):
    def test_full_120_pairs_and_selected_known_layout(self):
        payload=go()
        self.assertEqual(len(payload["odds"]),120)
        self.assertEqual(payload["odds"][0]["ticket"],[1,2,3])
        self.assertEqual(payload["odds"][1]["ticket"],[2,1,3])
        self.assertEqual(payload["odds"][2]["ticket"],[3,1,2])
        self.assertEqual(payload["odds"][3]["ticket"],[4,1,2])
        self.assertEqual(payload["odds"][6]["ticket"],[1,2,4])
        self.assertEqual(payload["odds"][119]["ticket"],[6,5,4])
        self.assertEqual(len({tuple(x["ticket"]) for x in payload["odds"]}),120)
        self.assertEqual(payload["odds"][0]["decimal_odds"],10.)
        self.assertIsNone(payload["source_published_at"])
        self.assertEqual(payload["source_status"],"PROVIDER_REPORTED_UNVERIFIED")
        self.assertEqual(payload["sales_status"],"UNKNOWN")

    def test_missing_quote_is_null_not_made_up(self):
        got=go(html(value_at=(3,"--")))
        self.assertEqual(got["odds"][3]["status"],"UNAVAILABLE")
        self.assertIsNone(got["odds"][3]["decimal_odds"])
        self.assertEqual(got["odds"][4]["status"],"QUOTED")

    def test_malformed_grid_or_duplicate_grid_fails(self):
        for data in (html(119), html(121), html(120,duplicate=True), b"<html><body>not odds</body></html>"):
            with self.subTest(n=len(data)):
                with self.assertRaises(SourceDeliveryError):
                    go(data)

    def test_unsupported_text_cannot_be_coerced_to_odds(self):
        for token in ("<script>", "???", "0", "0.3", "Infinity", "NaN"):
            with self.subTest(token=token):
                with self.assertRaises(SourceDeliveryError):
                    go(html(value_at=(2,token)))

    def test_reject_pseudo_official_urls_and_wrong_race(self):
        with self.assertRaisesRegex(SourceDeliveryError,"official odds URL"):
            go(source_url="https://evil.example.com/owpc/pc/race/odds3t?hd=20300115&jcd=01&rno=1")
        with self.assertRaisesRegex(SourceDeliveryError,"race identity"):
            go(race_id="20300115-02-01")
        with self.assertRaisesRegex(SourceDeliveryError,"URL query"):
            go(source_url=SOURCE+"&odds=123")

    def test_unreviewed_display_rights_blocked(self):
        with self.assertRaisesRegex(SourceDeliveryError,"odds_display"):
            go(policy=licensed(extra=()))
        with self.assertRaisesRegex(SourceDeliveryError,"independent reviewed"):
            go(policy=None)

    def test_quoted_publish_time_must_not_come_from_future(self):
        with self.assertRaisesRegex(SourceDeliveryError,"after local receipt"):
            go(source_published_at="2030-01-15T09:45:00+09:00")
        got=go(source_published_at="2030-01-15T09:03:00+09:00")
        self.assertEqual(got["source_published_at"],"2030-01-15T09:03:00+09:00")

    def test_closed_status_not_final_payout(self):
        out=go(ingested_at="2030-01-15T10:01:00+09:00")
        self.assertEqual(out["sales_status"],"CLOSED_REPORTED")
        self.assertNotIn("winning_combinations",out)
        self.assertNotIn("prediction",out)


if __name__=="__main__":
    unittest.main()
