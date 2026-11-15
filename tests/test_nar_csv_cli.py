"""Offline ZIP wrapper tests with fictional NAR-shaped CSV bytes only."""
import io
import json
import zipfile
import unittest

from race_ai.nar_csv_cli import unpack_nar_race_zip
from race_ai.nar_official_csv_adapter import stage_nar_csv, NarFormatError
from tests.test_nar_official_csv_adapter import (
    DAY, OBS, AT, VENUE, SRC, race_row, horse_row, csv_bytes
)
from tests.test_permissioned_source_delivery import gate


def zipped(members):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name,value in members:
            z.writestr(name,value)
    return stream.getvalue()


def valid_members():
    return [
        ("20300115_racelist.csv",csv_bytes([race_row()])),
        ("20300115_horselist.csv",csv_bytes([horse_row(i) for i in range(1,4)])),
        ("20300115_payback.csv",b"fictional post-result only; must NOT read"),
    ]


class NarZipTests(unittest.TestCase):
    def test_offline_official_filenames_and_ignore_payback(self):
        archive=zipped(valid_members())
        race,horses=unpack_nar_race_zip(archive,event_date_jst=DAY)
        self.assertEqual(race,csv_bytes([race_row()]))
        self.assertNotIn(b"post-result",race+horses)
        stage=stage_nar_csv(race,horses,gate(),at=AT,observed_at=OBS,
                            source_ref=SRC,rights_ref="fictional-permission-1",
                            event_date_jst=DAY,venue=VENUE,race_no=7,
                            encoding="utf-8-sig",has_header=False)
        self.assertEqual(stage["status"],"MISSING_STABLE_HORSE_IDS_AND_FEATURES_AND_CUTOFF")
        self.assertFalse(stage["model_ready"])

    def test_archive_odds_directory_and_duplicate_rejected(self):
        extra=[
            ("20300115_odds.csv",b"bad"),
            ("../20300115_racelist.csv",b"bad"),
            ("X/20300115_racelist.csv",b"bad"),
        ]
        for name,data in extra:
            with self.subTest(name=name):
                with self.assertRaisesRegex(NarFormatError,"unsafe/unknown"):
                    unpack_nar_race_zip(zipped(valid_members()[:2]+[(name,data)]),
                                       event_date_jst=DAY)
        d=valid_members()[:2]+[valid_members()[0]]
        with self.assertRaisesRegex(NarFormatError,"duplicate"):
            unpack_nar_race_zip(zipped(d),event_date_jst=DAY)

    def test_corrupt_missing_and_inflated_member_rejected(self):
        with self.assertRaisesRegex(NarFormatError,"corrupt"):
            unpack_nar_race_zip(b"not-a-zip",event_date_jst=DAY)
        with self.assertRaisesRegex(NarFormatError,"required"):
            unpack_nar_race_zip(zipped([valid_members()[0],valid_members()[2]]),
                               event_date_jst=DAY)
        oversized=zipped([
            ("20300115_racelist.csv",b"x"*(4_000_001)),
            valid_members()[1]
        ])
        with self.assertRaisesRegex(NarFormatError,"unsafe/unknown"):
            unpack_nar_race_zip(oversized,event_date_jst=DAY)

    def test_wrong_jst_date_rejected(self):
        with self.assertRaisesRegex(NarFormatError,"unsafe/unknown"):
            unpack_nar_race_zip(zipped(valid_members()),event_date_jst="2030-01-16")


if __name__ == "__main__":
    unittest.main()
