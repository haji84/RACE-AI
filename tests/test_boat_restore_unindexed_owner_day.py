"""Only attested physical BOAT originals may be recovered to a previously missing day."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from boat_restore_unindexed_owner_day import coverage,SOURCE_SHA,PARENT_SHA,SOURCE_CIPHER,DAY,RUN,main


def cohort():
    a=[]
    for index in range(136):
        rid=f"20261113-{(index//12)+1:02d}-{(index%12)+1:02d}"
        p=dict(stage="P0",model_id="origin",eligible_pre_cutoff=True,
               persisted_at="2026-11-13T09:00:00+09:00")
        additional=[dict(stage="P0",model_id=f"factor-{i}")
                    for i in range(5)]
        if index<9:
            additional.append(dict(stage="P1",model_id="pre-exhibition-original"))
        a.append(dict(sport="boat",event_date_jst=DAY,race_id=rid,
                      prediction=p,comparison_predictions=additional))
    return dict(schema="RACE_AI_PRIVATE_CYCLE_VIEW_V1",records=a)


class SealedNewDayRecoveryTests(unittest.TestCase):
    def test_fixed_run_and_prior_aes_router_must_be_pinned(self):
        self.assertEqual(RUN,43348227701)
        self.assertEqual(SOURCE_SHA,"0da3f00b0f5c5115f956658d306ddcb9833ec7af")
        self.assertEqual(PARENT_SHA,"6383db3fad783dd40ad40be3b828c0b783b3aad9")
        self.assertEqual(SOURCE_CIPHER,"52e194c99217b5dfdbd5db7d35c203cc762d91ce577a936e93ea53f642a10bee")

    def test_physical_136_scope_is_not_all_p1(self):
        value=coverage(cohort())
        self.assertEqual(value["races"],136)
        self.assertEqual(value["stage_races"],{"P0":136,"P1":9})
        self.assertEqual(value["forecasts"]["P0"],816)
        self.assertEqual(value["forecasts"]["P1"],9)
        self.assertEqual(value["eligible_pre_cutoff_counts"]["P0"],136)

    def test_duplicate_race_is_rejected(self):
        view=cohort()
        view["records"][1]["race_id"]=view["records"][0]["race_id"]
        with self.assertRaisesRegex(ValueError,"BOAT_NEW_DAY_RACE_DUPLICATE"):
            coverage(view)

    def test_foreign_day_never_appears_in_requested_day(self):
        view=cohort()
        view["records"][0]["event_date_jst"]="2026-11-12"
        self.assertEqual(coverage(view)["races"],135)

    def test_plain_source_invocation_rejects_before_race_or_remote_calls(self):
        with patch("subprocess.check_output",return_value=b"untrusted-source\n"):
            self.assertEqual(main(),2)

    def test_writer_contains_original_guard_and_exact_future_no_get(self):
        s=(ROOT/"scripts/boat_restore_unindexed_owner_day.py").read_text()
        for field in ("intake_saved_models(previous,hydrate=True,day=DAY",
                      "recover_runs=[RUN]","F.ensure_append_only(previous,from_view)",
                      "protect_new_forecast_originals(previous,from_view,root)",
                      "git.head()==parent","F.publish_view(git,bootstrap,from_view",
                      "F.current_view(git,bootstrap,day=DAY)",
                      "NEW_DAY_READBACK_INVENTORY_MISMATCH",
                      "p1_all_races_complete_proven=False",
                      "source_provider_gets=0"):
            self.assertIn(field,s)
        for forbidden in ("www.boatrace.jp","requests.get","httpx.get",
                          "collect(already_frozen_models=",
                          "first_p0_bootstrap.py","gh workflow run",
                          "official_source_requests += 1"):
            self.assertNotIn(forbidden,s)


if __name__=="__main__":
    unittest.main()
