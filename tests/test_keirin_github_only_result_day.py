"""No network, keys or false official outcomes in these tests."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from scripts import keirin_github_only_result_day as results

DAY="2026-11-19"
RID="202611192601"
CLOCK=lambda: datetime.fromisoformat("2026-11-19T08:00:00+00:00")


class GitHubOnlyResultStudy(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.root.chmod(0o700)
        self.raw=self.root/"raw"
        self.raw.mkdir(mode=0o700)

    def test_current_wall_day_stop_blocks_previous_day_result_registration(self):
        today_path = f"{results.provider_stop.ROOT}/{DAY}.json"
        marker = {"schema": results.provider_stop.SCHEMA, "day_jst": DAY,
                  "code": "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                  "observed_at": "2026-11-19T07:00:00+00:00"}

        def read(repo, head, path):
            return (0, json.dumps(marker)) if path == today_path else None

        with patch.object(results.archive, "_remote", return_value=self.root), \
             patch.object(results.archive, "_refresh", return_value="f" * 40), \
             patch.object(results.archive, "_show", side_effect=read), \
             patch.object(results.archive, "_cmd", return_value=(0, "")), \
             patch.object(results.registration, "register_day") as registration:
            with self.assertRaisesRegex(
                    results.live.GitHubOnlyDayError, "DENIAL_NO_RETRY"):
                results.run_day(day="2026-11-18", repo=self.root,
                                private_raw_dir=self.raw, clock=CLOCK)
        registration.assert_not_called()

    def test_previous_race_day_denial_is_saved_against_observed_wall_day(self):
        stored = []

        def save(**kwargs):
            stored.append(kwargs)
            return "PROVIDER_DAY_STOP_RECORDED"

        with patch.object(results.archive, "_remote", return_value=self.root), \
             patch.object(results.live, "archived_day",
                          return_value={"202611182601": "a" * 64}), \
             patch.object(results.capture, "fetch_once", side_effect=
                          results.capture.SourceCaptureError(
                              "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")), \
             patch.object(results.provider_stop, "append_once", side_effect=save):
            with self.assertRaises(results.capture.SourceCaptureError):
                results.run_day(day="2026-11-18", repo=self.root,
                                private_raw_dir=self.raw, clock=CLOCK)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["day"], "2026-11-19")
        self.assertEqual(stored[0]["observed_at"], "2026-11-19T08:00:00+00:00")

    def test_result_denial_persistence_failure_aborts_without_second_get(self):
        ids = [RID, "202611192602"]
        manifest = {
            "schema": results.capture.SCHEMA, "day_jst": DAY,
            "source_use_scope": "OWNER_PERSONAL_RESEARCH_ONLY",
            "races": [{"race_id": rid,
                       "netkeirin_url": "https://keirin.netkeiba.com/race/entry/"
                                         "?race_id=" + rid,
                       "kdreams_url": "https://keirin.kdreams.jp/seibuen/"
                                      "racedetail/26202611190100" + rid[-2:] + "/",
                       "cutoff_hint": None} for rid in ids],
        }
        calls = []

        def denied(url):
            calls.append(url)
            raise results.capture.SourceCaptureError(
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")

        with patch.object(results.archive, "_remote", return_value=self.root), \
             patch.object(results.live, "archived_day",
                          return_value={rid: "a" * 64 for rid in ids}), \
             patch.object(results.registration, "register_day",
                          return_value=({"races": manifest["races"]}, manifest, {})), \
             patch.object(results.archive, "_refresh", return_value="f" * 40), \
             patch.object(results, "_published_cutoff", return_value=
                          datetime.fromisoformat("2026-11-19T06:00:00+00:00")), \
             patch.object(results, "_prior_research", return_value=[]), \
             patch.object(results.capture, "fetch_once", side_effect=denied), \
             patch.object(results.provider_stop, "append_once", side_effect=
                          results.provider_stop.ProviderStopError(
                              "PROVIDER_STOP_CONCURRENT_GIT_RETRY_EXHAUSTED")):
            with self.assertRaisesRegex(RuntimeError, "STOP_PERSISTENCE_FAILED"):
                results.run_day(day=DAY, repo=self.root,
                                private_raw_dir=self.raw, clock=CLOCK)
        self.assertEqual(len(calls), 1)

    def test_unavailable_early_results_do_not_starve_later_frozen_races(self):
        ids = [f"2026111926{n:02d}" for n in range(1, 11)]
        manifest = {"races": [{"race_id": rid} for rid in ids]}
        attempted = []

        def unavailable(**kwargs):
            attempted.append(kwargs["race_id"])
            raise ValueError("RESULT_NOT_PUBLISHED")

        with patch.object(results.archive, "_remote", return_value=self.root), \
             patch.object(results.live, "archived_day",
                          return_value={rid: "a" * 64 for rid in ids}), \
             patch.object(results.registration, "register_day",
                          return_value=({"races": manifest["races"]}, manifest, {})), \
             patch.object(results.archive, "_refresh", return_value="f" * 40), \
             patch.object(results, "_published_cutoff", return_value=
                          datetime.fromisoformat("2026-11-19T06:00:00+00:00")), \
             patch.object(results, "_prior_research", return_value=[]), \
             patch.object(results.result_poll, "poll", side_effect=unavailable):
            for minute in ("00", "10"):
                report = results.run_day(
                    day=DAY, repo=self.root, private_raw_dir=self.raw,
                    clock=lambda: datetime.fromisoformat(
                        "2026-11-19T08:" + minute + ":00+00:00"))
                self.assertLessEqual(report["result_candidates"], 8)
                self.assertEqual(report["research_matches_persisted"], 0)
                self.assertEqual(report["officially_scored"], 0)
        self.assertEqual(set(attempted), set(ids))

    def test_requires_existing_frozen_prediction_before_result_GET(self):
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",return_value={}),\
             patch.object(results.registration,"register_day") as get:
            report=results.run_day(
                day=DAY,repo=self.root,private_raw_dir=self.raw,clock=CLOCK)
        get.assert_not_called()
        self.assertEqual(report["result_candidates"],0)
        self.assertEqual(report["officially_scored"],0)

    def test_result_does_not_go_backward_beyond_previous_day(self):
        with patch.object(results.archive,"_remote") as repo:
            with self.assertRaisesRegex(
                    results.live.GitHubOnlyDayError, "CURRENT_OR_PREVIOUS"):
                results.run_day(
                    day="2026-11-17",repo=self.root,
                    private_raw_dir=self.raw,clock=CLOCK)
            repo.assert_not_called()

    def test_real_link_registration_accepts_current_and_previous_result_days(self):
        for requested_day in ("2026-11-19", "2026-11-18"):
            with self.subTest(day=requested_day):
                compact = requested_day.replace("-", "")
                rid = compact + "2601"
                calendar_url = ("https://keirin.kdreams.jp/kaisai/2026/11/" +
                                requested_day[-2:] + "/")
                meeting = "/seibuen/racecard/26" + compact + "0100/"
                detail = "/seibuen/racedetail/26" + compact + "010001/"
                meeting_url = "https://keirin.kdreams.jp" + meeting
                pages = {
                    calendar_url: ('<a href="' + meeting + '">venue</a>').encode(),
                    meeting_url: ('<a href="' + detail + '">1R</a>').encode(),
                }
                calls = []

                def fetch(url):
                    calls.append(url)
                    return pages[url]

                observed = {
                    "race_id": rid,
                    "state": "SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL",
                    "qualifies_for_formal_settlement": False,
                    "winning_triple": [7, 3, 4], "payout_per_100yen": 5590,
                }
                with patch.object(results.archive, "_remote", return_value=self.root), \
                     patch.object(results.live, "archived_day",
                                  return_value={rid: "a" * 64}), \
                     patch.object(results.archive, "_refresh", return_value="f" * 40), \
                     patch.object(results, "_published_cutoff", return_value=
                                  datetime.fromisoformat(requested_day + "T06:00:00+00:00")), \
                     patch.object(results, "_prior_research", return_value=[]), \
                     patch.object(results.capture, "fetch_once", side_effect=fetch), \
                     patch.object(results.result_poll, "poll", return_value=observed), \
                     patch.object(results, "_archive_result",
                                  return_value="RESEARCH_REVISION_GIT_CREATE_ONCE_READBACK"), \
                     patch.object(results.live.generator, "run_cycle") as forecast:
                    report = results.run_day(day=requested_day, repo=self.root,
                                             private_raw_dir=self.raw, clock=CLOCK)
                self.assertEqual(calls, [calendar_url, meeting_url])
                self.assertEqual(report["registered_linked_races"], 1)
                self.assertEqual(report["research_matches_persisted"], 1)
                self.assertEqual(report["officially_scored"], 0)
                forecast.assert_not_called()

    def test_not_yet_post_cutoff_is_not_polled(self):
        registry={"races":[{"race_id":RID}]}
        manifest={"races":[{"race_id":RID}]}
        cutoff=datetime.fromisoformat("2026-11-19T08:01:00+00:00")
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",
                          return_value={RID:"a"*64}),\
             patch.object(results.registration,"register_day",
                          return_value=(registry,manifest,{})),\
             patch.object(results.archive,"_refresh",
                          return_value="f"*40),\
             patch.object(results,"_published_cutoff",return_value=cutoff),\
             patch.object(results.result_poll,"poll") as poll:
            out=results.run_day(
                day=DAY,repo=self.root,
                private_raw_dir=self.raw,clock=CLOCK)
        poll.assert_not_called()
        self.assertEqual(out["result_candidates"],0)
        self.assertEqual(out["officially_scored"],0)

    def test_observed_provisional_result_can_be_archived_not_scored(self):
        registry={"races":[{"race_id":RID}]}
        manifest={"races":[{"race_id":RID}]}
        cutoff=datetime.fromisoformat("2026-11-19T06:00:00+00:00")
        observed={
            "race_id":RID,
            "state":"SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL",
            "qualifies_for_formal_settlement":False,
            "winning_triple":[7,3,4],
            "payout_per_100yen":5590}
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",
                          return_value={RID:"a"*64}),\
             patch.object(results.registration,"register_day",
                          return_value=(registry,manifest,{})),\
             patch.object(results.archive,"_refresh",
                          return_value="f"*40),\
             patch.object(results,"_published_cutoff",return_value=cutoff),\
             patch.object(results,"_prior_research",return_value=[]),\
             patch.object(results.result_poll,"poll",return_value=observed),\
             patch.object(results,"_archive_result",
                          return_value="RESEARCH_REVISION_GIT_CREATE_ONCE_READBACK"):
            out=results.run_day(
                day=DAY,repo=self.root,private_raw_dir=self.raw,clock=CLOCK)
        self.assertEqual(out["result_candidates"],1)
        self.assertEqual(out["research_matches_persisted"],1)
        self.assertEqual(out["officially_scored"],0)
        self.assertFalse(out["official_primary_result_authenticated"])

    def test_provisional_receipt_refuses_false_official_flags(self):
        with self.assertRaisesRegex(
                results.live.GitHubOnlyDayError, "CANNOT_BE_ARCHIVED_AS_MATCHED"):
            results._archive_result(self.root,{
                "race_id":RID,"state":"SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL",
                "qualifies_for_formal_settlement":True,
                "winning_triple":[7,3,4],
                "payout_per_100yen":5590})


if __name__=="__main__":
    unittest.main()
