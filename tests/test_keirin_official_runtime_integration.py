"""Fictional sources, real RSA/AES and local encrypted Git history.

Only the trusted acquisition and local-remote boundary are injected. No live
provider requests, external repositories, real owners or forecasts are used.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zipfile import ZipFile
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_github_provider_stop as stop
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_public_source as official
from race_ai import keirin_official_run_history as history
from race_ai import keirin_official_poll_progress as progress
from scripts import keirin_official_day_pipeline as pipeline
from tests.test_keirin_official_public_source import DAY, RACE, fixtures, transport
from tests.test_keirin_official_run_history import git


class NoExternalGitHub:
    stopped_reason = None

    def read_run_bundle(self, run):
        raise AssertionError("No originals in this fixture; no GitHub call is expected")


class OfficialEncryptedRuntimeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin = self.root / "origin.git"
        self.repo = self.root / "runner"
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        git(self.root, "clone", str(self.origin), str(self.repo))
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "README.md").write_text("SYNTHETIC ONLY\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "synthetic existing history")
        git(self.repo, "push", "origin", archive.BRANCH)
        self.public_path = self.root / "owner-public.pem"
        self.public_path.write_bytes(self.public)
        self.now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
        self.data = fixtures()
        self.runner_number = 0

        read_revisions = history.read_revisions
        append_revision = history.append_revision
        read_progress = progress.read_day
        advance_progress = progress.advance_day
        patches = [
            patch.object(storage, "PINNED_OWNER_SPKI_SHA256", self.pin),
            patch.object(history, "read_revisions", side_effect=lambda **kwargs:
                         read_revisions(**dict(kwargs, synthetic_local=True))),
            patch.object(history, "append_revision", side_effect=lambda **kwargs:
                         append_revision(**dict(kwargs, synthetic_local=True))),
            patch.object(progress, "read_day", side_effect=lambda **kwargs:
                         read_progress(**dict(kwargs, synthetic_local=True))),
            patch.object(progress, "advance_day", side_effect=lambda **kwargs:
                         advance_progress(**dict(kwargs, synthetic_local=True))),
            patch.object(pipeline, "read_originals", return_value={}),
            patch.object(stop, "read_for_observed_day", return_value=None),
            patch.object(official, "_http_get",
                         side_effect=AssertionError("Live source calls are forbidden in this test")),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def clock(self):
        return self.now

    def poll(self, *, saved_only=False, github_client=None):
        self.runner_number += 1
        private_root = self.root / f"private-run-{self.runner_number}"
        private_root.mkdir(mode=0o700)
        with patch.object(pipeline, "official_fetcher",
                          return_value=transport(self.data)) as acquire:
            report = pipeline.run_settlement(
                day=DAY, repo=self.repo, private_root=private_root,
                owner_public_path=self.public_path, owner_private_pem=self.private,
                max_races=8, clock=self.clock, collect_official=not saved_only,
                github_client=github_client or NoExternalGitHub())
            if saved_only:
                acquire.assert_not_called()
        self.now += timedelta(minutes=10)
        return report

    def loaded(self):
        return pipeline.load_day_evidence(self.repo, DAY, self.private)

    def archived(self):
        return history.read_revisions(repo=self.repo, day=DAY)

    def correct_payout(self, amount="2,340", update="2026/10/02 12:06&nbsp;更新"):
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = amount + "円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = amount
        self.data["JSJ012"]["lastUpdateTime"] = update

    def make_record(self, previous=None):
        get = transport(self.data)
        schedule = official.fetch_day_schedule(DAY, fetcher=get, clock=self.clock)
        return official.fetch_race_result(
            RACE, schedule=schedule, fetcher=get, clock=self.clock,
            previous_result=previous)

    def append_record(self, record):
        pipeline.persist_delta(
            repo=self.repo, day=DAY,
            payload={"schema": "RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1",
                     "kind": "OFFICIAL_SETTLEMENT", "day_jst": DAY,
                     "safe_report": {"day_jst": DAY},
                     "official_records": {RACE: record}},
            owner_public_pem=self.public, clock=self.clock)

    def test_correction_survives_encrypted_replay_without_changing_original_cipher(self):
        first = self.poll()
        self.assertEqual(first["official_result_states"][RACE], "OFFICIAL_FINAL")
        initial_cipher = self.archived()[0]["raw_cipher"]
        original = deepcopy(self.loaded()["official_records"][RACE])
        self.correct_payout()
        updated = self.poll()
        self.assertEqual(updated["official_result_states"][RACE], "OFFICIAL_FINAL")
        restored = self.loaded()
        current = restored["official_records"][RACE]
        self.assertEqual(current["result"]["payouts_100yen"],
                         [{"triple": [1, 2, 3], "yen": 2340}])
        self.assertEqual(current["provenance"]["previous_result"], original["result"])
        self.assertEqual(current["provenance"]["revision_relationship"]["previous_source_sha256"],
                         original["result"]["source_sha256"])
        self.assertIn(initial_cipher, [row["raw_cipher"] for row in self.archived()])
        revisions_before = [row["raw_cipher"] for row in self.archived()]
        replay = self.poll(saved_only=True)
        self.assertEqual(replay["official_result_states"], updated["official_result_states"])
        self.assertEqual([row["raw_cipher"] for row in self.archived()], revisions_before)
        self.assertTrue(official.reparse_race_result(original))

    def test_unchanged_polling_advances_progress_without_new_source_revisions(self):
        first=self.poll()
        initial=[row['raw_cipher'] for row in self.archived()]
        for _ in range(4):
            report=self.poll()
            self.assertEqual(report,first)
        self.assertEqual([row['raw_cipher'] for row in self.archived()],initial)
        current=progress.read_day(repo=self.repo,day=DAY)
        self.assertEqual(current['result_poll_cursor'],5)
        self.assertEqual(current['origin_poll_cursor'],0)

    def test_older_day_visits_reach_all_unavailable_origin_runs_without_clock_aliasing(self):
        from tests.test_keirin_official_cohort import schedule
        from race_ai.keirin_github_evidence_client import GitHubEvidenceError
        actual=schedule([(str(code),2) for code in range(26,34)])
        pipeline.persist_delta(repo=self.repo,day=DAY,payload={
            'schema':'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1','kind':'OFFICIAL_SCHEDULE',
            'day_jst':DAY,'schedule':actual,'safe_report':{'day_jst':DAY}},
            owner_public_pem=self.public,clock=self.clock)
        originals={row['race_id']:{'raw_cipher':b'unverified synthetic original',
            'cipher_sha256':'0'*64,'producer_run_id':str(100000+index),
            'producer_commit':'a'*40} for index,row in enumerate(actual['races'])}
        client=Mock(stopped_reason=None)
        client.read_run_bundle.side_effect=GitHubEvidenceError('GITHUB_EVIDENCE_HTTP_404')
        with patch.object(pipeline,'read_originals',return_value=originals):
            self.poll(saved_only=True,github_client=client)
            self.now += timedelta(minutes=10)  # Same parity of the global ten-minute slot.
            self.poll(saved_only=True,github_client=client)
        requested={call.args[0] for call in client.read_run_bundle.call_args_list}
        self.assertEqual(requested,{value['producer_run_id'] for value in originals.values()})
        self.assertEqual(len(requested),16)
        self.assertEqual(progress.read_day(repo=self.repo,day=DAY)['origin_poll_cursor'],2)

    def test_same_frozen_A_B_original_is_rescored_after_appended_official_correction(self):
        from race_ai import keirin_nationwide_auto_generator as model
        from tests.test_keirin_nationwide_auto_generator import fixture
        from tests.test_keirin_github_origin_evidence import evidence_fixture, archive_bytes, report_bytes

        source = json.loads(json.dumps(fixture()).replace("2026-11-18", DAY)
                            .replace("20261118", DAY.replace("-", "")))
        source["published_cutoff_at"] = DAY + "T10:45:00+09:00"
        forecast = model.generate_A_B(source, generated_at=DAY + "T09:01:00+09:00")
        path = self.root / "frozen-original.sealed.json"
        receipt = storage.seal_once(
            snapshot=source, prediction=forecast, public_key_pem=self.public,
            path=path, sealed_at=DAY + "T09:01:05+09:00")
        original = {"raw_cipher": path.read_bytes(), "cipher_sha256": receipt["cipher_sha256"],
                    "producer_run_id": "123456", "producer_commit": "a" * 40}
        original_before = deepcopy(original)
        winner = forecast["A"]["ranked_tickets"][0]
        order = winner + [car for car in range(1, 8) if car not in winner]
        summary = self.data["JSJ018"]["resultList"][0]
        detail = self.data["JSJ012"]
        for rank, car in enumerate(winner, 1):
            summary[f"tyakui{rank}List"][0]["rclblSyaban"] = car
        triple = "-".join(map(str, winner))
        summary["harai3renList"][0]["kumi"] = triple
        detail["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["kumiBan"] = triple
        for entry in self.data["JSJ017"]["rInfo"][0]["sInfo"]:
            entry["senNo"] = source["riders"][entry["syaban"] - 1]["athlete_id"]
        for entry in detail["tyakujyunItemSubData"]:
            car = int(entry["syaban"])
            entry["tyaku"] = str(order.index(car) + 1)
            entry["sensyuRegistNo"] = source["riders"][car - 1]["athlete_id"]

        packets = []
        for packet in evidence_fixture():
            with ZipFile(BytesIO(packet["archive_bytes"])) as zipped:
                member = zipped.namelist()[0]
                document = json.loads(zipped.read(member))
            document = json.loads(json.dumps(document).replace("2026-11-18", DAY)
                                  .replace("20261118", DAY.replace("-", "")))
            entries = document.get("new_encrypted_originals", document.get("records"))
            entries[0]["cipher_sha256"] = original["cipher_sha256"]
            metadata = {key: value for key, value in packet.items() if key != "archive_bytes"}
            packet = json.loads(json.dumps(metadata).replace("2026-11-18", DAY))
            packet["archive_bytes"] = archive_bytes(member, report_bytes(document))
            packet["artifact"]["digest"] = "sha256:" + sha256(packet["archive_bytes"]).hexdigest()
            packet["artifact"]["size_in_bytes"] = len(packet["archive_bytes"])
            packets.append(packet)
        client = Mock(stopped_reason=None)
        client.read_run_bundle.return_value = {"producer": packets[0], "readback": packets[1]}
        with patch.object(pipeline, "read_originals", return_value={RACE: original}):
            first = self.poll(github_client=client)
            self.assertEqual(first["paired_A_B_scored"], 1)
            self.assertEqual(first["scorecard"]["A_existing"]["payout_yen"], 1230)
            self.correct_payout()
            corrected = self.poll(github_client=client)
        self.assertEqual(corrected["paired_A_B_scored"], 1)
        self.assertEqual(corrected["scorecard"]["A_existing"]["payout_yen"], 2340)
        self.assertNotEqual(first["result_receipts"][0]["result_revision_sha256"],
                            corrected["result_receipts"][0]["result_revision_sha256"])
        self.assertEqual(first["result_receipts"][0]["cipher_file_sha256"],
                         corrected["result_receipts"][0]["cipher_file_sha256"])
        self.assertEqual(original, original_before)
        self.assertEqual(path.read_bytes(), original_before["raw_cipher"])
        client.read_run_bundle.assert_called_once_with("123456")

    def test_stale_retry_after_hold_cannot_erase_the_last_accepted_revision(self):
        self.poll()
        self.correct_payout()
        self.poll()
        accepted = deepcopy(self.loaded()["official_records"][RACE]["result"])
        self.data = fixtures()
        for _ in range(2):
            report = self.poll()
            self.assertEqual(report["official_result_states"][RACE],
                             "HOLD_RESULT_REVISION_REVIEW")
            restored = self.loaded()
            self.assertEqual(restored["accepted_results"][RACE], accepted)
            self.assertEqual(restored["official_records"][RACE]["provenance"]["previous_result"],
                             accepted)
        self.assertEqual(len(self.archived()) >= 3, True)

    def test_replay_rejects_a_correction_linked_to_an_unrecorded_previous_branch(self):
        self.poll()
        self.correct_payout("1,150", "2026/10/02 12:04&nbsp;更新")
        never_accepted = self.make_record()["result"]
        self.correct_payout()
        wrong_branch = self.make_record(previous=never_accepted)
        self.assertTrue(official.reparse_race_result(wrong_branch))
        self.append_record(wrong_branch)
        with self.assertRaises(ValueError):
            self.loaded()

    def test_replay_rejects_a_parentless_replacement_of_an_accepted_result(self):
        self.poll()
        self.correct_payout()
        parentless = self.make_record()
        self.assertTrue(official.reparse_race_result(parentless))
        self.append_record(parentless)
        with self.assertRaises(ValueError):
            self.loaded()

    def test_a_shrinking_source_schedule_keeps_the_previous_registered_cohort(self):
        self.poll()
        previous_schedule = self.loaded()["schedule"]
        self.data["JSJ017"]["rInfo"] = self.data["JSJ017"]["rInfo"][:1]
        self.data["JSJ001"]["C0201data"]["C0201race"] = self.data["JSJ001"]["C0201data"]["C0201race"][:1]
        report = self.poll()
        self.assertEqual(report["registered_races"], 2)
        self.assertEqual(report["provider_state"], "HOLD_OFFICIAL_COHORT_SHRINK_REVIEW")
        restored = self.loaded()
        self.assertEqual(restored["schedule_versions"][0], previous_schedule)
        self.assertEqual(len(restored["cohort"]["registry"]["races"]), 2)
        self.assertEqual(len(restored["schedule"]["races"]), 1)
        self.assertEqual(report["official_result_states"]["202610022602"],
                         "HOLD_RACE_REMOVED_FROM_LATEST_OFFICIAL_SCHEDULE")

    def test_expanded_official_schedule_retains_unforecast_races_in_the_denominator(self):
        self.poll()
        extra = deepcopy(self.data["JSJ017"]["rInfo"][1])
        extra.update(raceNo=3, denTime="12:47", stTime="12:50")
        self.data["JSJ017"]["rInfo"].append(extra)
        self.data["JSJ001"]["C0201data"]["C0201race"].append({
            "encParaR": "synthetic-race-token-0003", "flgRaceEnd": False})
        report = self.poll()
        self.assertEqual(report["registered_races"], 3)
        self.assertEqual(report["missing_originals"], 3)
        self.assertEqual(report["paired_A_B_scored"], 0)
        restored = self.loaded()
        self.assertEqual(len(restored["schedule"]["races"]), 3)

    def test_public_key_capture_of_empty_candidate_cannot_poison_prior_nonempty_history(self):
        from scripts import keirin_github_only_ab_day as live
        self.poll()
        previous_schedule = self.loaded()["schedule"]
        self.data["JSJ057"]["kInfo"] = []
        private_root = self.root / "private-empty-capture"
        private_root.mkdir(mode=0o700)
        with patch.object(live, "archived_day", return_value={}), \
                patch.object(pipeline, "official_fetcher", return_value=transport(self.data)):
            pipeline.run_capture(
                day=DAY, repo=self.repo, private_root=private_root,
                owner_public_path=self.public_path, max_races=8, clock=self.clock)
        restored = self.loaded()
        self.assertEqual(restored["schedule_versions"][0], previous_schedule)
        self.assertEqual(restored["schedule"]["races"], [])
        replay = self.poll(saved_only=True)
        self.assertEqual(replay["registered_races"], 2)
        self.assertEqual(replay["provider_state"], "HOLD_OFFICIAL_COHORT_SHRINK_REVIEW")

    def test_replacing_one_venue_preserves_old_ids_and_registers_new_ids(self):
        from tests.test_keirin_official_cohort import schedule
        old = schedule([('26', 2)])
        new = schedule([('27', 2)], minutes=10)
        for version in (old, new):
            pipeline.persist_delta(repo=self.repo, day=DAY, payload={
                'schema':'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1',
                'kind':'OFFICIAL_SCHEDULE','day_jst':DAY,'schedule':version,
                'safe_report':{'day_jst':DAY}}, owner_public_pem=self.public,clock=self.clock)
            self.now += timedelta(minutes=10)
        loaded=self.loaded()
        self.assertEqual(len(loaded['cohort']['registry']['races']),4)
        report=self.poll(saved_only=True)
        self.assertEqual(report['registered_races'],4)
        self.assertEqual(report['active_official_races'],2)
        self.assertEqual(report['removed_official_races_held'],2)
        self.assertEqual(report['paired_A_B_scored'],0)
        self.assertEqual(set(report['official_result_states']),{
            '202610022601','202610022602','202610022701','202610022702'})


class OfficialRuntimeContentAndFairness(unittest.TestCase):
    def test_identical_official_schedule_bytes_have_one_content_fingerprint(self):
        get = transport(fixtures())
        start = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
        first = official.fetch_day_schedule(DAY, fetcher=get, clock=lambda: start)
        reread = official.fetch_day_schedule(
            DAY, fetcher=get, clock=lambda: start + timedelta(minutes=10))
        self.assertNotEqual(first["snapshots"][0]["observed_at"],
                            reread["snapshots"][0]["observed_at"])
        self.assertEqual(pipeline.evidence_fingerprint(first),
                         pipeline.evidence_fingerprint(reread))

    def test_mixed_pending_and_final_queue_revisits_every_completed_race(self):
        now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
        final_ids = [f"2026100226{n:02d}" for n in range(1, 9)]
        pending_ids = [f"2026100224{n:02d}" for n in range(1, 9)]
        all_ids = final_ids + pending_ids
        schedule = {"races": [{"race_id": rid,
                               "official_cutoff_at": "2026-10-02T10:00:00+09:00"}
                              for rid in all_ids]}
        records = {rid: {"state": "OFFICIAL_FINAL"} for rid in final_ids}
        selected = set()
        for slot in range(16):
            batch = pipeline.select_result_races(
                schedule, records, {}, now + timedelta(minutes=10 * slot), max_races=8)
            self.assertLessEqual(len(batch), 8)
            self.assertEqual(len(batch), len(set(batch)))
            selected.update(batch)
        self.assertEqual(selected, set(all_ids))
        self.assertEqual(len(schedule["races"]), 16)

    def test_one_race_budget_does_not_starve_completed_corrections_forever(self):
        now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
        final_ids = [f"2026100226{n:02d}" for n in range(1, 5)]
        pending_ids = [f"2026100224{n:02d}" for n in range(1, 5)]
        schedule = {"races": [{"race_id": rid,
                               "official_cutoff_at": "2026-10-02T10:00:00+09:00"}
                              for rid in final_ids + pending_ids]}
        records = {rid: {"state": "OFFICIAL_FINAL"} for rid in final_ids}
        selected = set()
        for slot in range(24):
            batch = pipeline.select_result_races(
                schedule, records, {}, now + timedelta(minutes=10 * slot), max_races=1)
            self.assertLessEqual(len(batch), 1)
            selected.update(batch)
        self.assertEqual(selected, set(final_ids + pending_ids))


if __name__ == "__main__":
    unittest.main()
