"""NAR official manual-positioned CSV adapter: fictional layout fixtures only.

The format is documented by NAR, but the sample participants and source grant
are invented and DO NOT authorize real NAR data collection or model training.
"""
import csv
from io import StringIO
import unittest

from race_ai.nar_official_csv_adapter import (
    stage_nar_csv, NarFormatError, RACELIST_COLUMNS,
    HORSELIST_COLUMNS, STAGE_SCHEMA
)
from tests.test_permissioned_source_delivery import SRC, AT, gate, policy_doc

DAY = "2030-01-15"
OBS = "2030-01-15T08:05:00+09:00"
VENUE = "架空の競馬場"


def csv_bytes(rows, *, encoding="utf-8-sig"):
    text=StringIO(newline="")
    writer=csv.writer(text)
    writer.writerows(rows)
    return text.getvalue().encode(encoding)


def race_row(*, race=7, n=3):
    r=[""]*RACELIST_COLUMNS
    r[:5]=[VENUE,"20300115",str(race),"1000","架空競走"]
    r[21:24]=["ダート","右","1800"]
    r[26]=str(n)
    return r


def horse_row(number, *, race=7):
    r=[""]*HORSELIST_COLUMNS
    r[0:3]=[VENUE,"20300115",str(race)]
    r[3]=str((number-1)//2+1)
    r[5]=str(number)
    r[6]="架空馬"+str(number)
    r[7]="牡"
    r[8]="5"
    r[14]="架空騎手"+str(number)
    r[16]="56"
    r[18]="架空調教師"+str(number)
    r[24]="2-1-0-6"
    r[27]="0-1-0-2"
    r[28]="0-1-0-1"
    return r


def stage(rr=None,hr=None, *, obs=OBS, now=AT, policy=None, header=False, encoding="utf-8-sig"):
    races=rr if rr is not None else [race_row()]
    horses=hr if hr is not None else [horse_row(i) for i in range(1,4)]
    if header:
        races=[["競馬場","競走年月日","レース番号"]+["未使用"]*(RACELIST_COLUMNS-3)]+races
        horses=[["競馬場","競走年月日","レース番号"]+["未使用"]*(HORSELIST_COLUMNS-3)]+horses
    return stage_nar_csv(csv_bytes(races,encoding=encoding),
                         csv_bytes(horses,encoding=encoding),
                         policy or gate(),at=now,observed_at=obs,
                         source_ref=SRC,rights_ref="fictional-permission-1",
                         event_date_jst=DAY,venue=VENUE,race_no=7,
                         encoding=encoding,has_header=header)


class NarAdapterTests(unittest.TestCase):
    def test_documented_columns_to_private_pre_model_stage(self):
        got=stage()
        self.assertEqual(got["schema"],STAGE_SCHEMA)
        self.assertEqual(got["scheduled_start_at"],"2030-01-15T10:00:00+09:00")
        self.assertIsNone(got["sales_cutoff_at"])
        self.assertFalse(got["model_ready"])
        self.assertFalse(got["forecast_frozen"])
        self.assertEqual(got["declared_entries"],3)
        self.assertEqual(len(got["participants"]),3)
        self.assertEqual(got["participants"][1]["horse_number"],2)
        self.assertEqual(got["participants"][0]["career_record"],"2-1-0-6")
        self.assertEqual(got["participants"][0]["horse_identity_status"],"NO_UNIQUE_ID_IN_NAR_CSV")
        self.assertEqual(len(got["original_csv_sha256"]["racelist"]),64)
        self.assertNotIn("popularity",str(got).lower())
        self.assertNotIn("race_result",str(got))
        self.assertFalse(got["eligible_hit_at_8"])

    def test_doc_header_and_explicit_cp932_supported(self):
        got=stage(header=True,encoding="cp932")
        self.assertEqual(got["observed_entries"],3)
        with self.assertRaisesRegex(NarFormatError,"unannounced header"):
            r=[["競馬場","競走年月日","レース番号"]+[""]*(RACELIST_COLUMNS-3),race_row()]
            stage(rr=r,header=False)
        with self.assertRaisesRegex(NarFormatError,"header differs"):
            stage(rr=[race_row()],hr=[horse_row(i) for i in range(1,4)],header=True,
                  encoding="ascii")

    def test_never_ingest_current_race_results_popularity_or_sectionals(self):
        h=[horse_row(i) for i in range(1,4)]
        h[0][31]="1"             # current race finish / post-race
        with self.assertRaisesRegex(NarFormatError,"POST_RACE_HORSELIST"):
            stage(hr=h)
        h=[horse_row(i) for i in range(1,4)]
        h[0][35]="2"             # popularity, may appear before finish
        with self.assertRaisesRegex(NarFormatError,"POST_RACE_HORSELIST"):
            stage(hr=h)
        r=race_row()
        r[58]="1,2,3"            # corner pass order after race
        with self.assertRaisesRegex(NarFormatError,"POST_RACE_RACELIST"):
            stage(rr=[r])
        r=race_row()
        r[33]="38.2"             # current race last 4F
        with self.assertRaisesRegex(NarFormatError,"POST_RACE_RACELIST"):
            stage(rr=[r])

    def test_other_settled_race_does_not_leak_into_selected_race(self):
        other=race_row(race=6)
        other[33]="37.7"
        old=horse_row(1,race=6)
        old[31]="1"
        st=stage(rr=[other,race_row()],hr=[old]+[horse_row(i) for i in range(1,4)])
        self.assertEqual(st["race_no"],7)
        self.assertNotIn("37.7",str(st))

    def test_declared_entrants_mismatch_is_visible_not_filled(self):
        got=stage(hr=[horse_row(1),horse_row(2)])
        self.assertEqual(got["status"],"HORSE_COUNT_MISMATCH_OR_SCRATCH_UNVERIFIED")
        self.assertFalse(got["model_ready"])

    def test_unknown_permissions_fail_closed(self):
        restricted=gate(policy_doc(["collection","private_storage","private_derived"]))
        with self.assertRaisesRegex(NarFormatError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            stage(policy=restricted)

    def test_time_identity_and_duplicates(self):
        with self.assertRaisesRegex(NarFormatError,"source observation lies in the future"):
            stage(obs="2030-01-15T09:50:00+09:00")
        with self.assertRaisesRegex(NarFormatError,"MISSED_START"):
            stage(now="2030-01-15T10:01:00+09:00")
        with self.assertRaisesRegex(NarFormatError,"duplicate horse number"):
            stage(hr=[horse_row(1),horse_row(1),horse_row(3)])
        with self.assertRaisesRegex(NarFormatError,"once"):
            stage(rr=[race_row(),race_row()])

    def test_invalid_format_and_ambiguity_do_not_guess(self):
        r=race_row()
        with self.assertRaisesRegex(NarFormatError,"column layout"):
            stage(rr=[r[:-1]])
        r=race_row()
        r[3]="2461"
        with self.assertRaisesRegex(NarFormatError,"HHMM"):
            stage(rr=[r])
        h=horse_row(1)
        h[24]="unknown"
        with self.assertRaisesRegex(NarFormatError,"career statistics"):
            stage(hr=[h,horse_row(2),horse_row(3)])
        with self.assertRaisesRegex(NarFormatError,"encoding"):
            stage(encoding="shift-jis")


if __name__=="__main__":
    unittest.main()
