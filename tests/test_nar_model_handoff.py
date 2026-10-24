"""Synthetic NAR pre-model evidence handoff tests. NO real data or licenses."""
import copy
import json
import unittest

from race_ai.comprehensive_four_sport_models import RESEARCH, digest
from race_ai.nar_model_handoff import (
    link_nar_stage_to_features, IDENTITY_SCHEMA, CUTOFF_SCHEMA
)
from race_ai.nar_official_csv_adapter import NarFormatError
from tests.test_nar_official_csv_adapter import stage, race_row, horse_row
from tests.test_permissioned_source_delivery import SRC, AT, gate, snapshot, FEED_SCHEMA

CUTOFF = "2030-01-15T09:45:00+09:00"
PUB = "2030-01-15T08:00:00+09:00"
CAPTURED = "2030-01-15T08:05:00+09:00"
RIGHTS = "fictional-permission-1"


def source():
    return {"source_ref":SRC, "source_rights_ref":RIGHTS,
            "published_at":PUB,"captured_at":CAPTURED}


def build():
    st = stage(rr=[race_row(n=8)], hr=[horse_row(i) for i in range(1,9)])
    model = snapshot("horse")
    model["participants"] = model["participants"][:8]
    model["race"].update({"race_id":st["race_id"],"venue":st["venue"],
                          "surface":"dirt","race_kind":"fictional sample",
                          "sales_cutoff_at":CUTOFF,"distance_m":1800})
    for i, participant in enumerate(model["participants"],1):
        participant["number"] = i
        participant["identity"] = f"external-fictional-stable-horse-id-{i}"
        participant["draw"] = i
    feed={"schema":FEED_SCHEMA,"snapshot":model}
    horses=[
        {"horse_number":v["horse_number"],"frame_number":v["frame_number"],
         "horse_name":v["horse_name"],
         "stable_horse_id":f"external-fictional-stable-horse-id-{v['horse_number']}"}
        for v in st["participants"]
    ]
    identity={"schema":IDENTITY_SCHEMA,"race_id":st["race_id"],
              "horses":horses, **source()}
    cutoff={"schema":CUTOFF_SCHEMA,"race_id":st["race_id"],
            "sales_cutoff_at":CUTOFF,**source()}
    return st,feed,identity,cutoff


def run(st, feed, identity, cutoff, **options):
    return link_nar_stage_to_features(
        st,json.dumps(feed).encode(),identity,cutoff,gate(),at=AT,
        verify_identity=options.get("verify_identity",lambda _:True),
        verify_cutoff=options.get("verify_cutoff",lambda _:True))


class NarModelHandoffTests(unittest.TestCase):
    def test_synthetic_stage_with_separate_full_features_and_witnesses(self):
        st,feed,identity,cutoff=build()
        result=run(st,feed,identity,cutoff)
        self.assertEqual(result["handoff_schema"],"RACE_AI_NAR_MODEL_HANDOFF_V1")
        self.assertEqual(result["nar_stage_sha256"],st["stage_sha256"])
        self.assertEqual(result["identity_witness_sha256"],digest(identity))
        self.assertEqual(result["cutoff_witness_sha256"],digest(cutoff))
        self.assertEqual(result["research_suite"]["model_count"],4)
        for model in result["research_suite"]["models"].values():
            self.assertEqual(model["candidate_count"],8*7*6)
            self.assertEqual(len(model["ordered_top8"]),8)
            self.assertFalse(model["official_prediction"])
        self.assertIsNone(result["external_freeze_receipt"])
        self.assertFalse(result["official_prediction"])
        self.assertFalse(result["can_count_in_hit_at_8"])

    def test_missing_independent_attestation_cannot_pass(self):
        st,feed,identity,cutoff=build()
        with self.assertRaisesRegex(NarFormatError,"UNVERIFIED_IDENTITY"):
            run(st,feed,identity,cutoff,verify_identity=lambda _:False)
        with self.assertRaisesRegex(NarFormatError,"UNVERIFIED_CUTOFF"):
            run(st,feed,identity,cutoff,verify_cutoff=lambda _:False)

    def test_identity_change_and_missing_stable_ids_rejected(self):
        st,feed,identity,cutoff=build()
        feed["snapshot"]["participants"][0]["identity"]="forged"
        with self.assertRaisesRegex(NarFormatError,"stable identity mismatch"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        identity["horses"][1]["stable_horse_id"]=identity["horses"][0]["stable_horse_id"]
        with self.assertRaisesRegex(NarFormatError,"duplicate or unreliable"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        identity["horses"][0]["horse_name"]="renamed-other-horse"
        with self.assertRaisesRegex(NarFormatError,"number/frame/name mismatch"):
            run(st,feed,identity,cutoff)

    def test_unverified_cutoff_cannot_be_inferred_from_start_time(self):
        st,feed,identity,cutoff=build()
        feed["snapshot"]["race"]["sales_cutoff_at"]=st["scheduled_start_at"]
        with self.assertRaisesRegex(NarFormatError,"cutoff differs"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        cutoff["sales_cutoff_at"]=st["scheduled_start_at"]
        feed["snapshot"]["race"]["sales_cutoff_at"]=st["scheduled_start_at"]
        with self.assertRaisesRegex(NarFormatError,"BAD_CUTOFF"):
            run(st,feed,identity,cutoff)

    def test_late_witness_future_and_permissions(self):
        st,feed,identity,cutoff=build()
        cutoff["captured_at"]="2030-01-15T09:20:00+09:00"
        with self.assertRaisesRegex(NarFormatError,"witness timestamp"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        cutoff["source_ref"]="https://unreviewed.invalid/source"
        with self.assertRaisesRegex(NarFormatError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            run(st,feed,identity,cutoff)

    def test_stage_mutation_and_missing_entries_block(self):
        st,feed,identity,cutoff=build()
        st["participants"][0]["horse_name"]="changed-post-stage"
        with self.assertRaisesRegex(NarFormatError,"altered"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        st["status"]="HORSE_COUNT_MISMATCH_OR_SCRATCH_UNVERIFIED"
        st["stage_sha256"]=digest({k:v for k,v in st.items() if k!="stage_sha256"})
        with self.assertRaisesRegex(NarFormatError,"incomplete"):
            run(st,feed,identity,cutoff)

    def test_market_in_cutoff_witness_and_race_feature_block(self):
        st,feed,identity,cutoff=build()
        cutoff["payout_yen"]=9999
        with self.assertRaisesRegex(Exception,"market or result"):
            run(st,feed,identity,cutoff)
        st,feed,identity,cutoff=build()
        feed["snapshot"]["participants"][0]["features"]["odds"]=9
        with self.assertRaisesRegex(Exception,"market or result"):
            run(st,feed,identity,cutoff)

    def test_model_input_missing_feature_fails_no_imputation(self):
        st,feed,identity,cutoff=build()
        del feed["snapshot"]["participants"][0]["features"]["speed_figure"]
        with self.assertRaisesRegex(Exception,"required features missing"):
            run(st,feed,identity,cutoff)


if __name__=="__main__":
    unittest.main()
