"""Synthetic regression for PR64 B handoff -> PR71 four-model bridge.

No actual BOATRACE data, provider collection, credentials, bets or real timing
receipts occur in this fixture. Dates/participants/permissions are fictional.
"""
from datetime import datetime
import hashlib
import hmac
import json
import unittest

from race_ai.comprehensive_four_sport_models import digest, RESEARCH
from race_ai.boat_b_program_bridge import (
    HANDOFF_SCHEMA, STAGE_SCHEMA, stage_official_b_handoff,
    link_b_stage_to_features,
)
from race_ai.permissioned_source_delivery import (
    SourceDeliveryError, PermissionPolicy, POLICY_SCHEMA, FEED_SCHEMA
)
from tests.test_permissioned_source_delivery import (
    KEY, SRC, AT, sample, policy_doc
)

DAY = "2030-01-15"
RACE = "20300115-01-01"
BURL = "https://www1.mbrace.or.jp/od2/B/203001/b300115.lzh"
B_RIGHTS = "fictional-b-hand-reviewed"
CUTOFF = "2030-01-15T10:00:00+09:00"
CAPTURE = "2030-01-15T08:05:00+09:00"


def b_row(i):
    return {
        "lane":i,
        "racer_registration_id":str(4000+i),
        "motor_no":10+i,
        "boat_no":20+i,
        "name":None,
        "average_st":None,
        "display_time":None,
        "preview_course":None,
        "grade":"A2",
        "national_win_rate":6.2,
        "local_win_rate":5.5,
        "national_top2_rate":47.0,
        "local_top2_rate":41.0,
        "motor_top2_rate":36.0,
        "boat_top2_rate":31.0,
    }


def b_handoff():
    data = {
        "date_jst":DAY, "source_url":BURL,
        "source_sha256":"a"*64, "extracted_text_sha256":"b"*64,
        "source_hash_scope":"downloaded_archive",
        "first_observed_at":CAPTURE,
        "venues":[{"venue":"01", "races":[
            {"race_id":f"20300115-01-{r:02d}",
             "boats":[b_row(i) for i in range(1,7)],
             "closed_at":CUTOFF if r==1 else f"2030-01-15T{10+r:02d}:00:00+09:00",
             "preview_available":False}
            for r in range(1,13)]}],
        "races":12, "complete_six_boat_races":12,
    }
    return {"schema":HANDOFF_SCHEMA, "rights_ref":B_RIGHTS,
            "parser_ref":"haji84/RACE-AI@27f3df12ddca3971833d4dbf03f6fbcc88df6b07:official_b_snapshot_adapter",
            "extract":data}


def approved_policy():
    signed = policy_doc()
    extra = {
        "source_ref":BURL,"rights_ref":B_RIGHTS,
        "transport_url":BURL,
        "purposes":["analysis","private_storage","private_derived"],
        "evidence_url":"https://example.org/fictional/b-terms",
        "reviewer":"fictional-reviewer",
        "checked_at":"2030-01-10T00:00:00+09:00",
        "expires_at":"2030-02-01T00:00:00+09:00",
        "max_bytes":2_000_000, "max_requests":1, "max_cost_jpy":0,
    }
    signed["policy"]["grants"].append(extra)
    signed["signature"] = hmac.new(
        KEY, digest(signed["policy"]).encode("ascii"), hashlib.sha256
    ).hexdigest()
    return PermissionPolicy(signed, KEY, at=AT)


def normalized_feed():
    obj=sample("boat", scope=RESEARCH)
    obj["race"]["race_id"]=RACE
    obj["race"]["venue"]="01"
    obj["race"]["event_date_jst"]=DAY
    obj["race"]["sales_cutoff_at"]=CUTOFF
    for row in obj["participants"]:
        row["identity"]=str(4000+row["number"])
        for feature in row["features"].values():
            feature["source_ref"]=SRC
            feature["source_rights_ref"]="fictional-permission-1"
    for item in obj["environment"].values():
        item["source_ref"]=SRC
        item["source_rights_ref"]="fictional-permission-1"
    return {"schema":FEED_SCHEMA, "snapshot":obj}


def raw_feed():
    return json.dumps(normalized_feed()).encode("utf-8")


class BProgramBridgeTests(unittest.TestCase):
    def test_stage_has_real_schema_no_fabricated_features_or_verified_flags(self):
        s=stage_official_b_handoff(b_handoff(), approved_policy(), now=AT, race_id=RACE)
        self.assertEqual(s["schema"],STAGE_SCHEMA)
        self.assertEqual(s["status"],"AWAITING_VERIFIED_PRE_RACE_FEATURES")
        self.assertFalse(s["model_eligible"])
        self.assertFalse(s["official_schedule_completeness_verified"])
        self.assertFalse(s["official_bytes_independently_authenticated"])
        self.assertFalse(s["official_prediction"])
        self.assertIsNone(s["external_freeze_receipt"])
        self.assertEqual(len(s["participants"]),6)
        self.assertIn("start_timing",s["missing_model_required_features"])
        self.assertEqual(s["known_b_races"],12)

    def test_b_racer_identity_matches_provider_features_before_four_models(self):
        gate=approved_policy()
        s=stage_official_b_handoff(b_handoff(),gate,now=AT,race_id=RACE)
        result=link_b_stage_to_features(s,raw_feed(),gate,at=AT)
        self.assertTrue(result["b_program_reconciled"])
        self.assertEqual(result["b_program_stage_sha256"],s["stage_sha256"])
        self.assertEqual(result["research_suite"]["model_count"],4)
        for row in result["research_suite"]["models"].values():
            self.assertEqual(row["candidate_count"],120)
            self.assertEqual(len(row["ordered_top8"]),8)
            self.assertFalse(row["official_prediction"])
        self.assertFalse(result["can_count_in_hit_at_8"])
        self.assertFalse(result["official_b_bytes_independently_authenticated"])
        self.assertEqual(result["delivery_sha256"],digest({
            k:v for k,v in result.items() if k!="delivery_sha256"
        }))

    def test_wrong_racer_number_or_race_cutoff_is_rejected(self):
        gate=approved_policy()
        s=stage_official_b_handoff(b_handoff(),gate,now=AT,race_id=RACE)
        feed=normalized_feed()
        feed["snapshot"]["participants"][0]["identity"]="9999"
        with self.assertRaisesRegex(SourceDeliveryError,"racer/draw"):
            link_b_stage_to_features(s,json.dumps(feed).encode(),gate,at=AT)
        feed=normalized_feed()
        feed["snapshot"]["race"]["sales_cutoff_at"]="2030-01-15T10:01:00+09:00"
        with self.assertRaisesRegex(SourceDeliveryError,"race/program/feature"):
            link_b_stage_to_features(s,json.dumps(feed).encode(),gate,at=AT)

    def test_b_unapproved_source_is_not_accepted(self):
        doc=policy_doc()
        with self.assertRaisesRegex(SourceDeliveryError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            stage_official_b_handoff(
                b_handoff(),PermissionPolicy(doc,KEY,at=AT),
                now=AT,race_id=RACE
            )

    def test_same_day_after_cutoff_is_not_a_prior_forecast(self):
        after="2030-01-15T10:02:00+09:00"
        p=PermissionPolicy(approved_policy_document(),KEY,at=after)
        s=stage_official_b_handoff(b_handoff(),p,now=after,race_id=RACE)
        self.assertEqual(s["status"],"MISSED_DEADLINE")
        with self.assertRaisesRegex(SourceDeliveryError,"not prospective"):
            link_b_stage_to_features(s,raw_feed(),p,at=after)

    def test_missing_official_sales_cutoff_never_produces_forecast(self):
        handoff=b_handoff()
        handoff["extract"]["venues"][0]["races"][0]["closed_at"]=None
        s=stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)
        self.assertEqual(s["status"],"SALES_CUTOFF_MISSING")
        self.assertIsNone(s["cutoff_at"])
        self.assertFalse(s["model_eligible"])

    def test_b_source_cannot_claim_post_program_exhibition_values(self):
        handoff=b_handoff()
        handoff["extract"]["venues"][0]["races"][0]["boats"][0]["display_time"]=6.75
        with self.assertRaisesRegex(SourceDeliveryError,"cannot authenticate exhibition"):
            stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)

    def test_duplicate_motors_and_missing_lane_fail_closed(self):
        handoff=b_handoff()
        handoff["extract"]["venues"][0]["races"][0]["boats"][1]["motor_no"]=11
        with self.assertRaisesRegex(SourceDeliveryError,"equipment allocation"):
            stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)
        handoff=b_handoff()
        handoff["extract"]["venues"][0]["races"][0]["boats"][1]["lane"]=1
        with self.assertRaisesRegex(SourceDeliveryError,"identity mismatch"):
            stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)

    def test_incomplete_program_day_and_wrong_day_are_rejected(self):
        handoff=b_handoff()
        handoff["extract"]["races"]=13
        with self.assertRaisesRegex(SourceDeliveryError,"race coverage invalid"):
            stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)
        handoff=b_handoff()
        handoff["extract"]["date_jst"]="2030-01-16"
        with self.assertRaisesRegex(SourceDeliveryError,"does not match JST program day"):
            stage_official_b_handoff(handoff,approved_policy(),now=AT,race_id=RACE)

    def test_staged_source_must_still_be_permitted_when_linked(self):
        stage=stage_official_b_handoff(b_handoff(),approved_policy(),now=AT,race_id=RACE)
        # A later model run must not inherit a grant which is now absent.
        revoked=PermissionPolicy(policy_doc(),KEY,at=AT)
        with self.assertRaisesRegex(SourceDeliveryError,"SOURCE_PERMISSION_NOT_ADMITTED:B_SOURCE"):
            link_b_stage_to_features(stage,raw_feed(),revoked,at=AT)

    def test_cannot_self_claim_verified_receipt_by_rehashing_stage(self):
        stage=stage_official_b_handoff(b_handoff(),approved_policy(),now=AT,race_id=RACE)
        stage["external_freeze_receipt"]={"pretend":True}
        stage["stage_sha256"]=digest({k:v for k,v in stage.items() if k!="stage_sha256"})
        with self.assertRaisesRegex(SourceDeliveryError,"cannot claim official forecast"):
            link_b_stage_to_features(stage,raw_feed(),approved_policy(),at=AT)

    def test_tampered_staging_hash_is_rejected(self):
        p=approved_policy()
        s=stage_official_b_handoff(b_handoff(),p,now=AT,race_id=RACE)
        s["participants"][0]["racer_registration_id"]="9999"
        with self.assertRaisesRegex(SourceDeliveryError,"hash changed"):
            link_b_stage_to_features(s,raw_feed(),p,at=AT)


def approved_policy_document():
    """Reconstruct fictional source grants without exposing a real key."""
    base=policy_doc()
    base["policy"]["grants"].append({
        "source_ref":BURL,"rights_ref":B_RIGHTS,"transport_url":BURL,
        "purposes":["analysis","private_storage","private_derived"],
        "evidence_url":"https://example.org/fictional/b-terms",
        "reviewer":"fictional-reviewer",
        "checked_at":"2030-01-10T00:00:00+09:00",
        "expires_at":"2030-02-01T00:00:00+09:00",
        "max_bytes":2_000_000,"max_requests":1,"max_cost_jpy":0,
    })
    base["signature"]=hmac.new(KEY,digest(base["policy"]).encode("ascii"),hashlib.sha256).hexdigest()
    return base


if __name__=="__main__":
    unittest.main()
