"""Source-free pipeline tests: do not mistake mocks for live coverage."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import json
import unittest

from race_ai import keirin_official_nationwide_records as official_archive
from scripts import keirin_github_only_ab_day as live
from scripts import keirin_github_only_ab_readback as readback


RID1 = "202611192601"
RID2 = "202611192602"
DAY = "2026-11-19"
CLOCK = lambda: datetime.fromisoformat("2026-11-18T16:00:00+00:00")


def example_manifest():
    return {"day_jst": DAY, "races": [
        {"race_id": RID1}, {"race_id": RID2}]}


def linked_manifest(count=2):
    return {
        "schema": live.collector.SCHEMA, "day_jst": DAY,
        "source_use_scope": "OWNER_PERSONAL_RESEARCH_ONLY",
        "races": [{
            "race_id": f"2026111926{n:02d}",
            "netkeirin_url": "https://keirin.netkeiba.com/race/entry/"
                              f"?race_id=2026111926{n:02d}",
            "kdreams_url": "https://keirin.kdreams.jp/seibuen/racedetail/"
                           f"26202611190100{n:02d}/",
            "cutoff_hint": None,
        } for n in range(1, count + 1)],
    }


def prepared_registration():
    registry = live.registration.dynamic.create_day(
        day_jst=DAY, registered_at=CLOCK().isoformat(),
        venue_snapshots=[{
            "venue": "synthetic venue", "venue_code": "26", "grade": "UNKNOWN",
            "source_url": "https://example.org/synthetic-calendar",
            "source_bytes_sha256": "a" * 64,
            "source_available_at": CLOCK().isoformat(),
            "race_numbers": [1, 2], "source_race_day": DAY,
        }],
        independently_verify_venue_snapshot=lambda block: True)
    return registry, linked_manifest(), {
        "day_jst": DAY, "stopped_after_provider_error": False}


class GithubOnlyABDay(unittest.TestCase):
    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.root.chmod(0o700)
        self.pub = self.root / "owner-public.pem"
        self.pub.write_bytes(b"public-test-placeholder")
        # Source-free orchestration tests keep the new metadata transport mocked;
        # its separate tests use real bare Git and independent runner clones.
        self.selection_read = patch.object(live.selection_history, "read_day", return_value={})
        self.selection_write = patch.object(live.selection_history, "append_selected", return_value={})
        self.addCleanup(self.selection_read.stop)
        self.addCleanup(self.selection_write.stop)
        self.selection_read.start()
        self.selection_write.start()
        env = patch.dict(os.environ, {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"})
        self.addCleanup(env.stop)
        env.start()

    def selected_by_run(self, manifest, clock, max_races=8):
        selected = []

        def capture(**kwargs):
            selected.extend(r["race_id"] for r in kwargs["day_manifest"]["races"])
            return {"GET_pair_attempts": len(selected),
                    "normalized_private_cards": 0, "states": {}}

        with patch.object(live, "archived_day", return_value={}), \
             patch.object(live.registration, "register_day",
                          return_value=({"races": manifest["races"]}, manifest, {})), \
             patch.object(live.collector, "capture_cycle", side_effect=capture), \
             patch.object(live.generator, "registered_race_ids",
                          return_value=[r["race_id"] for r in manifest["races"]]), \
             patch.object(live.generator, "run_cycle", return_value={
                 "registered_races": len(manifest["races"]), "same_job_sealed": 0,
                 "statuses": {}, "records": []}):
            report = live.run_day(
                day=DAY, workspace=self.root, private_dir_path=self.root,
                owner_public_pem=self.pub, clock=clock, max_races=max_races)
        return selected, report

    def test_expired_prefix_cannot_starve_future_race_before_fetch_budget(self):
        manifest = linked_manifest(10)
        for row in manifest["races"][:9]:
            row["cutoff_hint"] = "2026-11-19T10:00:00+09:00"
        manifest["races"][9]["cutoff_hint"] = "2026-11-19T16:00:00+09:00"
        selected, report = self.selected_by_run(
            manifest, lambda: datetime.fromisoformat("2026-11-19T15:00:00+09:00"))
        self.assertEqual(selected, ["202611192610"])
        self.assertEqual(report["unfrozen_linked_races_before_budget"], 10)
        self.assertFalse(report["national_universe_verified"])

    def test_nearest_future_hint_is_selected_before_lexicographic_race_id(self):
        manifest = linked_manifest(3)
        manifest["races"][0]["cutoff_hint"] = "2026-11-19T16:00:00+09:00"
        manifest["races"][2]["cutoff_hint"] = "2026-11-19T15:05:00+09:00"
        selected, _ = self.selected_by_run(
            manifest, lambda: datetime.fromisoformat("2026-11-19T15:00:00+09:00"),
            max_races=1)
        self.assertEqual(selected, ["202611192603"])

    def test_unknown_cutoffs_get_a_turn_when_earlier_races_never_freeze(self):
        manifest = linked_manifest(10)
        first, _ = self.selected_by_run(
            manifest, lambda: datetime.fromisoformat("2026-11-19T00:00:00+09:00"))
        second, report = self.selected_by_run(
            manifest, lambda: datetime.fromisoformat("2026-11-19T00:10:00+09:00"))
        self.assertLessEqual(len(first), 8)
        self.assertLessEqual(len(second), 8)
        self.assertEqual(set(first + second),
                         {f"2026111926{n:02d}" for n in range(1, 11)})
        self.assertEqual(report["new_A_B_git_archived"], 0)
        self.assertFalse(report["national_universe_verified"])

    def test_failed_timed_prefix_yields_to_unselected_same_deadline_races(self):
        manifest = linked_manifest(16)
        for row in manifest["races"]:
            row["cutoff_hint"] = "2026-11-19T10:00:00+09:00"
        counts = {}
        seen = []
        for minute in (0, 10, 20, 30, 40, 50):
            eligible, remaining = live.select_unfrozen(
                manifest, {}, now=datetime.fromisoformat(
                    f"2026-11-19T09:{minute:02d}:00+09:00"),
                selection_counts=counts)
            ids = [row["race_id"] for row in eligible["races"]]
            seen.append(ids)
            # A selection is not evidence of a successful GET or normalization.
            # No originals freeze, so every row stays in the next manifest.
            for rid in ids:
                counts[rid] = counts.get(rid, 0) + 1
            self.assertEqual(remaining, 16)
        self.assertEqual(seen[0], [r["race_id"] for r in manifest["races"][:8]])
        self.assertEqual(seen[1], [r["race_id"] for r in manifest["races"][8:]])
        self.assertEqual(set(counts.values()), {3})

    def test_nearby_unequal_cutoffs_are_fair_but_distant_races_do_not_jump_ahead(self):
        manifest = linked_manifest(17)
        for index, row in enumerate(manifest["races"]):
            row["cutoff_hint"] = (
                "2026-11-19T10:00:00+09:00" if index < 8 else
                "2026-11-19T10:10:00+09:00" if index < 16 else
                "2026-11-19T18:00:00+09:00")
        counts = {row["race_id"]: 1 for row in manifest["races"][:8]}
        eligible, _ = live.select_unfrozen(
            manifest, {}, now=datetime.fromisoformat("2026-11-19T09:10:00+09:00"),
            selection_counts=counts)
        self.assertEqual([r["race_id"] for r in eligible["races"]],
                         [r["race_id"] for r in manifest["races"][8:16]])
        for row in manifest["races"][8:16]:
            counts[row["race_id"]] = 1
        eligible, _ = live.select_unfrozen(
            manifest, {}, now=datetime.fromisoformat("2026-11-19T09:20:00+09:00"),
            selection_counts=counts)
        self.assertEqual([r["race_id"] for r in eligible["races"]],
                         [r["race_id"] for r in manifest["races"][:8]])

    def test_expired_rows_cannot_anchor_the_imminent_selection_cohort(self):
        manifest = linked_manifest(3)
        for row, hint in zip(manifest["races"], (
                "2026-11-19T09:00:00+09:00", "2026-11-19T10:00:00+09:00",
                "2026-11-19T10:05:00+09:00")):
            row["cutoff_hint"] = hint
        eligible, _ = live.select_unfrozen(
            manifest, {}, max_races=1,
            now=datetime.fromisoformat("2026-11-19T09:10:00+09:00"),
            selection_counts={manifest["races"][1]["race_id"]: 2})
        self.assertEqual([r["race_id"] for r in eligible["races"]],
                         [manifest["races"][2]["race_id"]])

    def test_selection_persistence_failure_stops_before_any_racecard_get(self):
        with patch.object(live, "archived_day", return_value={}), \
             patch.object(live.selection_history, "append_selected",
                          side_effect=ValueError("CAPTURE_SELECTION_EXACT_READBACK_FAILED")), \
             patch.object(live.collector, "capture_cycle") as capture, \
             patch.object(live.collector, "fetch_once") as get:
            with self.assertRaisesRegex(ValueError, "EXACT_READBACK_FAILED"):
                live.run_day(day=DAY, workspace=self.root, private_dir_path=self.root,
                             owner_public_pem=self.pub, clock=CLOCK,
                             registration_data=prepared_registration())
        capture.assert_not_called()
        get.assert_not_called()

    def test_existing_denial_precedes_history_selection_and_provider_gets(self):
        with patch.object(live, "archived_day", side_effect=live.GitHubOnlyDayError(
                "HOLD_PROVIDER_PREVIOUS_DAY_DENIAL_NO_RETRY")), \
             patch.object(live.selection_history, "read_day") as history, \
             patch.object(live.registration, "register_day") as register, \
             patch.object(live.collector, "fetch_once") as get:
            with self.assertRaisesRegex(ValueError, "DENIAL_NO_RETRY"):
                live.run_day(day=DAY, workspace=self.root, private_dir_path=self.root,
                             owner_public_pem=self.pub, clock=CLOCK)
        history.assert_not_called()
        register.assert_not_called()
        get.assert_not_called()

    def test_capture_denial_persistence_failure_aborts_without_second_get(self):
        manifest = linked_manifest()
        calls = []

        def denied(url):
            calls.append(url)
            raise live.collector.SourceCaptureError(
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")

        with patch.object(live, "archived_day", return_value={}), \
             patch.object(live.registration, "register_day",
                          return_value=({"races": manifest["races"]}, manifest, {})), \
             patch.object(live.generator, "registered_race_ids",
                          return_value=[RID1, RID2]), \
             patch.object(live.collector, "fetch_once", side_effect=denied), \
             patch.object(live.provider_stop, "append_once",
                          side_effect=OSError("private failure detail")), \
             patch.object(live.generator, "run_cycle", return_value={
                 "registered_races": 2, "same_job_sealed": 0,
                 "statuses": {}, "records": []}):
            with self.assertRaisesRegex(RuntimeError, "STOP_PERSISTENCE_FAILED"):
                live.run_day(day=DAY, workspace=self.root,
                             private_dir_path=self.root, owner_public_pem=self.pub,
                             clock=CLOCK)
        self.assertEqual(len(calls), 1)

    def test_prepared_registration_reuses_source_stop_latch_without_another_get(self):
        calls = []
        public_key = (Path(live.__file__).resolve().parents[1] /
                      "docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem")
        self.pub.write_bytes(public_key.read_bytes())

        def denied(url):
            calls.append(url)
            raise live.collector.SourceCaptureError(
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")

        with patch.object(live, "archived_day", return_value={}), \
             patch.object(live.registration, "register_day") as registration, \
             patch.object(live.collector, "fetch_once", side_effect=denied), \
             patch.object(live.provider_stop, "append_once",
                          return_value="PROVIDER_DAY_STOP_RECORDED"):
            shared_fetch = live.guarded_provider_fetch(self.root, CLOCK)
            with self.assertRaises(live.collector.SourceCaptureError):
                shared_fetch("https://example.org/synthetic-refusal")
            report = live.run_day(
                day=DAY, workspace=self.root, private_dir_path=self.root,
                owner_public_pem=self.pub, clock=CLOCK,
                registration_data=prepared_registration(), fetch=shared_fetch)
        registration.assert_not_called()
        self.assertEqual(calls, ["https://example.org/synthetic-refusal"])
        self.assertEqual(report["new_A_B_git_archived"], 0)
        self.assertEqual(report["observed_races"], 2)

    def test_prepared_registration_still_checks_day_and_registry_integrity(self):
        original = prepared_registration()
        wrong_manifest_day = deepcopy(original)
        wrong_manifest_day[1]["day_jst"] = "2026-11-18"
        changed_registry = deepcopy(original)
        changed_registry[0]["races"][0]["grade"] = "CHANGED_AFTER_REGISTRATION"
        for bad in (wrong_manifest_day, changed_registry):
            with self.subTest(data=bad[1]["day_jst"]), \
                 patch.object(live, "archived_day", return_value={}), \
                 patch.object(live.collector, "fetch_once") as source:
                with self.assertRaises(ValueError):
                    live.run_day(
                        day=DAY, workspace=self.root, private_dir_path=self.root,
                        owner_public_pem=self.pub, clock=CLOCK,
                        registration_data=bad)
            source.assert_not_called()

    def test_selection_skips_already_frozen_without_changing_population(self):
        prior = {RID1: "a" * 64}
        eligible, remaining = live.select_unfrozen(example_manifest(), prior)
        self.assertEqual(remaining, 1)
        self.assertEqual([x["race_id"] for x in eligible["races"]], [RID2])
        self.assertEqual(len(example_manifest()["races"]), 2)

    def test_budget_limits_gets_but_no_national_coverage_claim(self):
        ids = [f"2026111926{r:02d}" for r in range(1, 11)]
        manifest = {"day_jst":DAY, "races":[{"race_id":x} for x in ids]}
        eligible, count = live.select_unfrozen(manifest, {}, max_races=8)
        self.assertEqual((len(eligible["races"]), count), (8,10))
        self.assertEqual(manifest["races"][9]["race_id"], ids[9])

    def test_yesterday_and_tomorrow_refuse_before_any_http_or_git(self):
        with patch.object(live, "archived_day") as history, \
             patch.object(live.registration, "register_day") as source:
            for wrong in ("2026-11-18", "2026-11-20"):
                with self.assertRaisesRegex(
                        live.GitHubOnlyDayError, "NO_RETROSPECTIVE"):
                    live.run_day(
                        day=wrong, workspace=self.root,
                        private_dir_path=self.root,
                        owner_public_pem=self.pub, clock=CLOCK)
            history.assert_not_called()
            source.assert_not_called()

    def test_mocked_one_race_archived_not_misreported_as_full_day(self):
        source = example_manifest()
        raw_cipher = b"synthetic-private-cipher-placeholder\n"
        sha = sha256(raw_cipher).hexdigest()
        registry = {"day_jst": DAY}

        def fake_generate(**kwargs):
            dest = kwargs["private_cipher_dir"] / (RID2 + ".sealed.json")
            dest.write_bytes(raw_cipher)
            return {"registered_races":2,"same_job_sealed":1,
                    "statuses":{"NO_FORECAST_INPUT_MISSING":1,
                                "A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH":1},
                    "records":[{"race_id":RID1,"ciphertext_local_created":False},
                               {"race_id":RID2,"ciphertext_local_created":True,
                                "cipher_file_sha256":sha}]}
        with patch.object(live, "archived_day", return_value={RID1:"a"*64}), \
             patch.object(live.registration, "register_day",
                          return_value=(registry,source,{})), \
             patch.object(live.collector, "capture_cycle",
                          return_value={"GET_pair_attempts":1,
                                        "normalized_private_cards":1,
                                        "states":{"PRIVATE_CARD_NORMALIZED":1}}) as get, \
             patch.object(live.generator, "registered_race_ids",
                          return_value=[RID1,RID2]), \
             patch.object(live.generator, "run_cycle",
                          side_effect=fake_generate), \
             patch.object(live.archive, "append_once",
                          return_value={"state":"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED"}) as write, \
             patch.dict(os.environ,
                        {"GITHUB_RUN_ID":"12345","GITHUB_SHA":"a"*40}):
            result = live.run_day(
                day=DAY, workspace=self.root,
                private_dir_path=self.root,
                owner_public_pem=self.pub, clock=CLOCK)
        self.assertEqual(get.call_args.kwargs["day_manifest"]["races"],
                         [{"race_id":RID2}])
        self.assertEqual(result["new_A_B_git_archived"],1)
        self.assertFalse(result["national_universe_verified"])
        self.assertEqual(result["official_results_scored"],0)
        self.assertEqual(result["already_frozen_prior"],1)
        self.assertEqual(write.call_args.kwargs["expected_cipher_sha256"],sha)
        self.assertNotIn("ranked_tickets", str(result))

    def test_readback_rejects_missing_verified_git_original(self):
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":1,
                  "new_encrypted_originals":[
                      {"race_id":RID2,"cipher_sha256":"a"*64}]}
        with patch.object(readback.archive,"read_original",
                          return_value={"state":"HOLD"}):
            with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                        "READBACK_NOT_VERIFIED"):
                readback.verify(report=report,repo=self.root)

    def test_readback_reports_nothing_official(self):
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":1,
                  "new_encrypted_originals":[
                      {"race_id":RID2,"cipher_sha256":"a"*64}]}
        with patch.object(readback.archive,"read_original",
                          return_value={
                              "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}):
            result = readback.verify(report=report,repo=self.root)
        self.assertEqual(result["independently_verified"], 1)
        self.assertFalse(result["RSA_private_decryption_verified"])
        self.assertFalse(result["organizer_result_verified"])

    def test_readback_cli_pins_one_independent_partial_archive_for_all_ciphertexts(self):
        checkout = self.root / 'existing-checkout'
        checkout.mkdir()
        command = readback.archive._cmd
        command(checkout, 'init', '--quiet', '--template=')
        remote = 'https://github.com/haji84/RACE-AI.git'
        command(checkout, 'remote', 'add', 'origin', remote)
        report = self.root / 'producer-receipt.json'
        target = self.root / 'reader-receipt.json'
        report.write_text(json.dumps(dict(schema=live.SCHEMA, day_jst=DAY, new_A_B_git_archived=2,
            new_encrypted_originals=[dict(race_id=RID1, cipher_sha256='1'*64,
                conditioned_state='GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED',
                conditioned_cipher_sha256='2'*64, baseline_prediction_sha256='3'*64, cohort_sha256='4'*64),
                dict(race_id=RID2, cipher_sha256='5'*64)])))
        head = 'a'*40

        def fetch(reader, *, with_ancestry):
            self.assertNotEqual(reader, checkout)
            self.assertTrue(with_ancestry)
            self.assertEqual(command(reader, 'remote', 'get-url', 'origin')[1], remote)
            self.assertEqual(command(reader, 'config', '--local', 'remote.origin.promisor')[1], 'true')
            self.assertEqual(command(reader, 'config', '--local', 'remote.origin.partialclonefilter')[1], 'blob:none')
            return head

        env = dict(RUNNER_TEMP=str(self.root), RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true')
        with patch.dict(os.environ, env), redirect_stdout(StringIO()), \
                patch.object(official_archive, 'fetch_partial_head', side_effect=fetch) as partial, \
                patch.object(readback.archive, '_read_at', return_value={}) as baseline, \
                patch.object(readback.archive, '_read_conditioned_at', return_value={}) as conditioned, \
                patch.object(readback.archive, '_refresh', side_effect=AssertionError('full archive fetch')):
            status = readback.main(['--repo',str(checkout),'--report',str(report),'--out',str(target)])

        self.assertEqual(status, 0)
        partial.assert_called_once()
        reader = partial.call_args.args[0]
        self.assertFalse(reader.exists())
        self.assertEqual([call.args for call in baseline.call_args_list],
                         [(reader,head,RID1,'1'*64), (reader,head,RID2,'5'*64)])
        conditioned.assert_called_once_with(reader,head,RID1,'2'*64,'1'*64,'3'*64,'4'*64)
        receipt = json.loads(target.read_text())
        self.assertEqual(receipt['independently_verified'], 2)
        self.assertEqual(receipt['paired_cipher_originals_verified'], 1)
        self.assertFalse(receipt['RSA_private_decryption_verified'])

    def test_readback_without_new_originals_does_not_contact_archive(self):
        report = dict(schema=live.SCHEMA, day_jst=DAY, new_A_B_git_archived=0,
                      new_encrypted_originals=[])
        with patch.object(official_archive, 'fetch_partial_head') as fetch:
            receipt = readback._verify_independently(report, self.root, self.root)
        fetch.assert_not_called()
        self.assertEqual(receipt['independently_verified'], 0)

    def test_readback_rejects_duplicate_races(self):
        row = {"race_id":RID2,"cipher_sha256":"a"*64}
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":2,
                  "new_encrypted_originals":[row,row]}
        with patch.object(readback.archive,"read_original",
                          return_value={
                              "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}):
            with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                        "DUPLICATE"):
                readback.verify(report=report,repo=self.root)

    def test_conditioned_readback_failure_keeps_verified_baseline(self):
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":1, "new_conditioned_A_B_git_archived":1,
                  "new_encrypted_originals":[{
                      "race_id":RID2, "cipher_sha256":"a"*64,
                      "conditioned_state":"GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED",
                      "conditioned_cipher_sha256":"b"*64,
                      "baseline_prediction_sha256":"c"*64,
                      "cohort_sha256":"d"*64}]}
        with patch.object(readback.archive, "read_original", return_value={
                "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}), \
             patch.object(readback.archive, "read_conditioned_original", create=True,
                          side_effect=ValueError("CONDITIONED_SHA_MISMATCH")):
            result = readback.verify(report=report, repo=self.root)
        self.assertEqual(result["independently_verified"], 1)
        self.assertEqual(result.get("independently_verified_conditioned"), 0)
        self.assertEqual(result.get("paired_cipher_originals_verified"), 0)
        self.assertEqual(result["records"][0].get("conditioned_state"),
                         "HOLD_CONDITIONED_SECOND_RUNNER_READBACK")

    def test_producer_cannot_preclaim_successful_conditioned_readback(self):
        report = {"schema":live.SCHEMA, "day_jst":DAY,
                  "new_A_B_git_archived":1, "new_encrypted_originals":[{
                      "race_id":RID2, "cipher_sha256":"a"*64,
                      "conditioned_state":"SECOND_RUNNER_CONDITIONED_GITHUB_SHA_CONFIRMED"}]}
        with patch.object(readback.archive, "read_original", return_value={
                "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}):
            result = readback.verify(report=report, repo=self.root)
        self.assertEqual(result["independently_verified"], 1)
        self.assertEqual(result["paired_cipher_originals_verified"], 0)

    def run_with_conditioned_archive(self, *, fail=False):
        baseline = b"synthetic sealed baseline"
        conditioned = b"synthetic sealed conditioned"
        baseline_sha = sha256(baseline).hexdigest()
        conditioned_sha = sha256(conditioned).hexdigest()

        def generate(**kwargs):
            folder = kwargs["private_cipher_dir"]
            (folder/(RID2+".sealed.json")).write_bytes(baseline)
            (folder/(RID2+".form.sealed.json")).write_bytes(conditioned)
            return {"registered_races":2, "same_job_sealed":1, "statuses":{},
                    "records":[{
                        "race_id":RID2, "ciphertext_local_created":True,
                        "cipher_file_sha256":baseline_sha,
                        "form_fall_shadow_state":"PRIVATE_CONDITIONED_SHADOW_SEALED",
                        "form_fall_shadow_file_sha256":conditioned_sha,
                        "form_fall_baseline_sha256":"c"*64}]}

        with patch.object(live, "archived_day", return_value={}), \
             patch.object(live.registration, "register_day", return_value=(
                 {"day_jst":DAY}, example_manifest(), {})), \
             patch.object(live.collector, "capture_cycle", return_value={
                 "GET_pair_attempts":1, "normalized_private_cards":1, "states":{}}), \
             patch.object(live.generator, "registered_race_ids", return_value=[RID1,RID2]), \
             patch.object(live.generator, "run_cycle", side_effect=generate), \
             patch.object(live.archive, "append_once", return_value={
                 "state":"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED"}), \
             patch.object(live.archive, "append_conditioned_once", create=True,
                          side_effect=OSError("synthetic write failure") if fail else None,
                          return_value={"state":"GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED"}), \
             patch.dict(os.environ, {"GITHUB_RUN_ID":"12345", "GITHUB_SHA":"a"*40}):
            return live.run_day(day=DAY, workspace=self.root,
                private_dir_path=self.root, owner_public_pem=self.pub, clock=CLOCK)

    def test_day_persists_conditioned_original_alongside_baseline(self):
        report = self.run_with_conditioned_archive()
        self.assertEqual(report["new_A_B_git_archived"], 1)
        self.assertEqual(report.get("new_conditioned_A_B_git_archived"), 1)
        row = report["new_encrypted_originals"][0]
        self.assertEqual(row.get("conditioned_state"),
                         "GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED")
        self.assertEqual(row.get("conditioned_cipher_sha256"),
                         sha256(b"synthetic sealed conditioned").hexdigest())
        self.assertEqual(row.get("baseline_prediction_sha256"), "c"*64)

    def test_conditioned_git_failure_is_hold_without_losing_baseline(self):
        report = self.run_with_conditioned_archive(fail=True)
        self.assertEqual(report["new_A_B_git_archived"], 1)
        self.assertEqual(report.get("new_conditioned_A_B_git_archived"), 0)
        self.assertEqual(report["new_encrypted_originals"][0].get("conditioned_state"),
                         "HOLD_CONDITIONED_GIT_ARCHIVE")


if __name__ == "__main__":
    unittest.main()
