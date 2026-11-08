"""Invented owner-saved CSV racecards. Never network or real provider data."""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_saved_csv import (
    SCHEMA, FIELDS, OwnerRacecardError,
    import_owner_saved_csv, stage_owner_saved_csv
)
from race_ai.keirin_owner_manual import (
    PERSONAL_MARKER, PersonalOwnerObservations
)
from race_ai.keirin_allowed_delivery import assemble_permitted_pre_race

DAY="2030-01-15"
NOW="2030-01-15T09:15:00+09:00"
ASOF="2030-01-15T09:10:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"


def fictitious_csv(score=306.15, contradict=False):
    f=io.StringIO()
    writer=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n")
    writer.writeheader()
    for n in range(1,8):
        writer.writerow({
            "car_no":n,"rider_name":f"fiction-rider-{n}",
            "grade":"A3","style":("逃" if n<4 else "追"),
            "race_score":str(score if n==1 else 75+n),
            "starts":20,
            "wins":9 if n==1 else 2,
            "seconds":4 if n==1 else 4,
            "thirds":1 if n==1 else 3,
            "unplaced":6 if n==1 and not contradict else 11,
            "s_count":2,"h_count":3,"b_count":8,
            "escape_count":5,"makuri_count":4,"sashi_count":3,
            "mark_count":1,"gear":"3.92"
        })
    return f.getvalue().encode("utf-8")


def meta(raw, source_url="https://www.keirin.jp/pc/top"):
    return {
        "schema":SCHEMA,
        "source_url":source_url,
        "source_observed_at":ASOF,
        "source_sha256":sha256(raw).hexdigest(),
        "race":{
            "race_id":"203001153601","venue":"fiction-venue",
            "event_date_jst":DAY,"race_kind":"fictional qualifying",
            "race_revision":1,"distance_m":2000,
            "as_of":ASOF,"official_cutoff_at":CUTOFF,
            "starters":[{
                "number":n,"identity":f"fiction-rider-{n}",
                "style":"front" if n<4 else "stalker",
                "group_id":"L1" if n<4 else "L2",
            } for n in range(1,8)]
        },
        "observed_race_facts":{
            "race_id_date_venue_no":{
                "race_id":"203001153601",
                "event_date_jst":DAY,
                "venue":"fiction-venue"
            },
            "race_distance":2000,
            "official_sales_cutoff":CUTOFF,
            "late_scratches_substitutions_revisions":{
                "race_revision":1,"active_numbers":list(range(1,8))
            },
            "line_order_all_riders":{
                "lines":[{"group_id":"L1","order":[1,2,3]},
                         {"group_id":"L2","order":[4,5,6,7]}],
                "solos":[]
            },
            "event_grade_and_class":"A3",
            "race_stage":"challenge-qualifying",
        }
    }


class OwnerCsvTests(unittest.TestCase):
    def grants(self):
        return PersonalOwnerObservations(
            source_hosts=["www.keirin.jp"],now=NOW)

    def test_347_statuses_are_constructed_from_partial_owner_csv(self):
        raw=fictitious_csv()
        out=import_owner_saved_csv(raw,meta(raw))
        self.assertEqual(out["roster_count"],7)
        self.assertFalse(out["independently_attested_published_at"])
        self.assertFalse(out["provider_automated_access_authorized"])
        self.assertEqual(out["race_count_conflict_riders"],[])
        decoded=assemble_permitted_pre_race(
            out["delivery"],grant_check=self.grants().allowed,
            checked_at=NOW)
        self.assertEqual(decoded["status"]["checked_count"],347)
        self.assertGreater(decoded["status"]["verified_items"],0)
        self.assertGreater(decoded["status"]["unavailable_items"],0)
        self.assertIsNone(decoded["private_snapshot"])
        self.assertIn("rider/1/last_3_races_rank_and_rivals",
                      decoded["status"]["unverified_critical_keys"])
        observed={r["key"]:r["value"] for r in out["delivery"]["observations"]}
        self.assertAlmostEqual(observed["rider/1/race_score"],306.15)
        self.assertAlmostEqual(observed["rider/1/win_rate"],9/20)
        self.assertAlmostEqual(observed["rider/1/top_three_rate"],14/20)
        self.assertEqual(observed["rider/1/back_B_count"],8)
        self.assertEqual(
            observed["rider/1/line_leader_or_follow_role"]["role"],"leader")
        self.assertEqual(
            observed["rider/2/line_leader_or_follow_role"]["role"],"second")
        self.assertTrue(
            observed["race/line_roles_and_solo_riders"][
                "is_expected_lineup_not_official_result"])
        self.assertNotIn(
            "rider/1/line_leader_or_follow_role",
            decoded["status"]["unverified_critical_keys"])


    def test_conflicting_win_counts_do_not_get_promoted(self):
        raw=fictitious_csv(contradict=True)
        out=import_owner_saved_csv(raw,meta(raw))
        self.assertEqual(out["race_count_conflict_riders"],[1])
        keys={o["key"] for o in out["delivery"]["observations"]}
        self.assertNotIn("rider/1/top_three_rate",keys)
        self.assertNotIn("rider/1/win_rate",keys)
        self.assertIn("rider/1/race_score",keys)

    def test_no_finite_200_point_ceiling(self):
        for x in (100.5,201,500.05,25000.5,10**20):
            with self.subTest(score=x):
                raw=fictitious_csv(score=x)
                out=import_owner_saved_csv(raw,meta(raw))
                seen=next(o["value"] for o in out["delivery"]["observations"]
                          if o["key"]=="rider/1/race_score")
                self.assertEqual(seen,float(x))

    def test_rakuten_and_hash_mismatch_rejected(self):
        raw=fictitious_csv()
        with self.assertRaisesRegex(OwnerRacecardError,"NON_RAKUTEN"):
            import_owner_saved_csv(raw,meta(raw,"https://keirin.kdreams.jp/a"))
        wrong=meta(raw)
        wrong["source_sha256"]="0"*64
        with self.assertRaisesRegex(OwnerRacecardError,"SOURCE_CSV_SHA_MISMATCH"):
            import_owner_saved_csv(raw,wrong)

    def test_owner_csv_after_deadline_does_not_create_forecast(self):
        raw=fictitious_csv()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/"csv").mkdir()
            (p/"csv"/"a.csv").write_bytes(raw)
            (p/"csv"/"a.meta.json").write_text(
                json.dumps(meta(raw)),encoding="utf-8")
            past=stage_owner_saved_csv(p,now="2030-01-15T10:00:01+09:00")
            self.assertEqual(past["blocked_csv"],1)
            self.assertEqual(list((p/"raw").glob("*.json")),[])
            first=stage_owner_saved_csv(p,now=NOW)
            self.assertEqual(first["staged_csv"],1)
            self.assertEqual(first["provider_http_requests"],0)
            second=stage_owner_saved_csv(p,now=NOW)
            self.assertEqual(second["unchanged_csv"],1)
            self.assertEqual(len(list((p/"raw").glob("*.json"))),1)

    def test_missing_or_modified_metadata_rejected(self):
        raw=fictitious_csv()
        info=meta(raw)
        info["race"]["starters"][0]["identity"]="forged"
        with self.assertRaisesRegex(OwnerRacecardError,
                                    "RIDER_CSV_IDENTITY_OR_STYLE_MISMATCH"):
            import_owner_saved_csv(raw,info)

    def test_unsupported_extra_betting_columns_rejected(self):
        raw=fictitious_csv().replace(
            b"car_no,",b"odds,car_no,",1)
        m=meta(raw)
        with self.assertRaisesRegex(OwnerRacecardError,"CSV_FIELDS_NOT_EXACT"):
            import_owner_saved_csv(raw,m)


if __name__=="__main__":
    unittest.main()
