"""Synthetic per-minute odds polling plan tests; no actual network calls."""
from datetime import datetime, timedelta
import hashlib
import hmac
import unittest

from race_ai.comprehensive_four_sport_models import digest
from race_ai.odds_refresh_plan import plan_one_minute
from race_ai.permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError
)
from tests.test_permissioned_source_delivery import KEY, policy_doc, AT


def signed(day="20300115",n=4):
    doc=policy_doc()
    for i in range(1,n+1):
        url=f"https://www.boatrace.jp/owpc/pc/race/odds3t?hd={day}&jcd=01&rno={i}"
        doc["policy"]["grants"].append({
            "source_ref":url,"rights_ref":"synthetic-odds-only","transport_url":url,
            "purposes":["collection","analysis","private_storage","private_derived","odds_display"],
            "evidence_url":"https://example.org/fictional/policy",
            "reviewer":"SYNTHETIC_CONTRACT_TEST",
            "checked_at":"2030-01-10T00:00:00+09:00",
            "expires_at":"2030-02-01T00:00:00+09:00",
            "max_bytes":2_000_000,"max_requests":1,"max_cost_jpy":0,
        })
    doc["signature"]=hmac.new(KEY,digest(doc["policy"]).encode("ascii"),hashlib.sha256).hexdigest()
    return PermissionPolicy(doc,KEY,at=AT)


def event(no,remaining=10):
    cutoff=(datetime.fromisoformat(AT)+timedelta(minutes=remaining)).isoformat()
    return {"race_id":f"20300115-01-{no:02d}",
            "source_url":f"https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20300115&jcd=01&rno={no}",
            "source_rights_ref":"synthetic-odds-only","cutoff_at":cutoff,
            "cutoff_verified":True,"last_attempt_at":None,"blocked_until":None}


class OddsRefreshPlanTests(unittest.TestCase):
    def test_low_traffic_plans_at_most_budget_by_earliest_cutoff(self):
        races=[event(1,15),event(2,12),event(3,5)]
        result=plan_one_minute(races,now=AT,policy=signed(),
                               prior_daily_calls=98,minute_limit=2,daily_limit=100)
        self.assertEqual(result["requests_selected"],2)
        self.assertEqual([r["race_id"] for r in result["races"] if r["request_selected"]],
                         ["20300115-01-03","20300115-01-02"])
        self.assertEqual(result["races"][-1]["status"],"CAPACITY_OR_DAILY_QUOTA_UNAVAILABLE")
        self.assertTrue(result["official_quote_provider_access_not_executed"])

    def test_source_policy_must_admit_every_purpose(self):
        x=plan_one_minute([event(1)],now=AT,policy=None,
                          prior_daily_calls=0,minute_limit=2,daily_limit=100)
        self.assertEqual(x["races"][0]["status"],"PROVIDER_RIGHTS_UNVERIFIED")
        y=plan_one_minute([event(1)],now=AT,policy=signed(),
                          prior_daily_calls=0,minute_limit=0,daily_limit=100)
        self.assertEqual(y["races"][0]["status"],"CAPACITY_OR_DAILY_QUOTA_UNAVAILABLE")
        self.assertEqual(y["requests_selected"],0)

    def test_provider_backoff_and_clock_cooldown(self):
        row=event(1)
        row["blocked_until"]="2030-01-15T09:22:00+09:00"
        p=plan_one_minute([row],now=AT,policy=signed(),prior_daily_calls=0,
                          minute_limit=2,daily_limit=100)
        self.assertEqual(p["races"][0]["status"],"PROVIDER_BLOCKED_OR_BACKOFF")
        row["blocked_until"]=None
        row["last_attempt_at"]="2030-01-15T09:14:30+09:00"
        p=plan_one_minute([row],now=AT,policy=signed(),prior_daily_calls=0,
                          minute_limit=2,daily_limit=100)
        self.assertEqual(p["races"][0]["status"],"COOLDOWN_NOT_DUE")

    def test_closed_unverified_cutoff_and_long_horizon(self):
        rows=[event(1,-2),event(2,62),event(3,10)]
        rows[2]["cutoff_verified"]=False
        p=plan_one_minute(rows,now=AT,policy=signed(),
                          prior_daily_calls=0,minute_limit=2,daily_limit=100)
        self.assertEqual([x["status"] for x in p["races"]],[
            "CLOSED","OFFICIAL_CUTOFF_UNVERIFIED","OUTSIDE_REFRESH_WINDOW"
        ])

    def test_durable_count_required_and_quota_exhaustion(self):
        with self.assertRaisesRegex(SourceDeliveryError,"durable daily"):
            plan_one_minute([event(1)],now=AT,policy=signed(),prior_daily_calls=None)
        p=plan_one_minute([event(1)],now=AT,policy=signed(),
                          prior_daily_calls=100,minute_limit=10,daily_limit=100)
        self.assertEqual(p["requests_selected"],0)

    def test_mismatched_source_race_number_and_duplicates_rejected(self):
        rows=[event(1),event(1)]
        with self.assertRaisesRegex(SourceDeliveryError,"duplicate"):
            plan_one_minute(rows,now=AT,policy=signed(),
                            prior_daily_calls=0,minute_limit=2,daily_limit=100)
        row=event(1);row["source_url"]=event(2)["source_url"]
        with self.assertRaisesRegex(SourceDeliveryError,"inconsistent odds race"):
            plan_one_minute([row],now=AT,policy=signed(),
                            prior_daily_calls=0,minute_limit=2,daily_limit=100)

    def test_no_claim_every_race_receives_minute_updates_when_over_capacity(self):
        rows=[event(i,5+i) for i in range(1,5)]
        p=plan_one_minute(rows,now=AT,policy=signed(),prior_daily_calls=0,
                          minute_limit=1,daily_limit=100)
        self.assertEqual(p["requests_selected"],1)
        self.assertEqual(sum(r["status"]=="CAPACITY_OR_DAILY_QUOTA_UNAVAILABLE"
                             for r in p["races"]),3)


if __name__=="__main__":
    unittest.main()
