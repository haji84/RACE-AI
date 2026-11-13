"""Never drop original BOAT forecasts because trusted result name labels are newer.

Synthetic sources only. There is no provider access, no result backfill and no
change to immutable P0 inputs; names are for display/race registration joins.
"""
from copy import deepcopy
import unittest
from race_ai import boat_saved_model_view as M
from tests.test_boat_saved_model_view import view


DAY="2030-04-01"
RID="20300401-01-01"
STAMP="2030-04-01T11:03:00+09:00"
BASE=dict(kind="SAME_RACE_RESULT",registration_no="4201",race_id=RID,
          source_sha256="f"*64,captured_at=STAMP,
          source_url="https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300401&jcd=01&rno=1")


def joined(source):
    saved=view()
    row=saved["records"][0]
    row["participants"][0].update(name="架空確認済み選手",name_source=source)
    return saved


class StrictSourceDisplayNameTests(unittest.TestCase):
    def test_same_race_official_result_name_is_display_only_and_forecast_unchanged(self):
        candidate=joined(deepcopy(BASE))
        before=deepcopy(candidate)
        out=M.merge_saved_views(candidate)
        self.assertEqual(candidate,before)
        self.assertEqual(out["records"][0]["participants"][0]["name_source"]["kind"],"SAME_RACE_RESULT")
        self.assertEqual(out["records"][0]["prediction"],candidate["records"][0]["prediction"])

    def test_other_same_day_official_result_requires_its_own_race_url(self):
        fact=dict(BASE,kind="SAME_DAY_OFFICIAL_RESULT",
            source_race_id="20300401-01-02",
            source_url="https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300401&jcd=01&rno=2")
        self.assertEqual(M.merge_saved_views(joined(fact))["records"][0]["prediction"],
                         view()["records"][0]["prediction"])
        for change in (dict(source_race_id=RID),
                       dict(source_race_id="20300402-01-02"),
                       dict(source_url=BASE["source_url"])):
            bad=joined(dict(fact,**change))
            with self.subTest(change=change),self.assertRaises(M.SavedModelViewError):
                M.merge_saved_views(bad)

    def test_current_official_profile_must_be_current_verified_and_registration_bound(self):
        fact=dict(kind="VERIFIED_OFFICIAL_PROFILE",registration_no="4201",
            verified_current=True,source_sha256="e"*64,captured_at=STAMP,
            source_url="https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=4201")
        doc=joined(fact)
        self.assertEqual(M.merge_saved_views(doc)["records"][0]["prediction"],
                         doc["records"][0]["prediction"])
        for change in (dict(verified_current=False),
                       dict(captured_at="2030-03-31T23:50:00+09:00"),
                       dict(source_url=fact["source_url"].replace("4201","4202")),
                       dict(source_sha256="bad")):
            with self.subTest(change=change),self.assertRaises(M.SavedModelViewError):
                M.merge_saved_views(joined(dict(fact,**change)))

    def test_forged_official_result_identity_never_hides_under_name_metadata(self):
        for change in (dict(registration_no="4202"),dict(race_id="20300401-02-01"),
                       dict(source_sha256="bad"),
                       dict(source_url=BASE["source_url"].replace("jcd=01","jcd=02")),
                       dict(source_url=BASE["source_url"].replace("rno=1","rno=2")),
                       dict(source_url=BASE["source_url"].replace("https://","http://")),
                       dict(captured_at="2030-03-31T23:59:59+09:00"),
                       dict(kind="OWNER_DECLARED")):
            with self.subTest(change=change),self.assertRaises(M.SavedModelViewError):
                M.merge_saved_views(joined(dict(BASE,**change)))


if __name__=="__main__":
    unittest.main()
