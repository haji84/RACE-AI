"""Local intake persists actual private observations without replaying work."""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import tempfile
import unittest
from unittest.mock import patch
import fcntl
import errno
import subprocess
import sys
import threading


def intake(test):
    try:
        return importlib.import_module("race_ai.boat_video_intake")
    except ModuleNotFoundError:
        test.fail("private automatic local video intake is missing")


def specification(digest, *, cutoff="2030-04-01T12:00:00+09:00", number=1):
    return {"schema_version": "RACE_AI_BOAT_VIDEO_JOB_V1",
            "race_id": "20300401-01-%02d" % number, "cutoff_at": cutoff,
            "roster": [{"lane": n, "registration_number": str(4200 + n)} for n in range(1, 7)],
            "source": {"kind": "OWNER_LOCAL", "media_sha256": digest,
                "captured_at": "2030-04-01T00:00:00+09:00", "identity_status": "OWNER_DECLARED"}}


def tracking(digest):
    return {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1", "media_sha256": digest,
            "width": 320, "height": 240, "duration_seconds": 1.0,
            "timeline_source": "MEDIA_PTS", "coordinate_space": "REFERENCE_IMAGE_PX",
            "model_eligible": False, "validation_status": "UNVALIDATED",
            "tracks": [{"lane": n, "identity_status": "COLOR_CANDIDATE", "samples": [
                {"t": i / 10, "frame_index": i, "scene": 0, "valid": True,
                 "x": float(i * n), "y": 0.0, "position_error": 0.1}
                for i in range(6)]} for n in range(1, 7)],
            "quality": {"flags": ["CONTROLLED_EXTRACTOR_TEST"], "decoded_frame_count": 6}}


class BoatVideoIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.media = self.root / "authorized-local.mp4"
        self.media.write_bytes(b"controlled extractor fixture, not an official video")
        self.media.chmod(0o600)
        self.digest = sha256(self.media.read_bytes()).hexdigest()
        self.calls = []

    def job(self, **kwargs):
        result = specification(self.digest, **kwargs)
        # Captures genuinely precede the real processing clock; now is only a
        # scheduling input and must never backdate actual analysis timestamps.
        result["source"]["captured_at"] = "2030-04-01T00:00:00+09:00".replace("2030", "2020")
        result["race_id"] = result["race_id"].replace("2030", "2020")
        result["cutoff_at"] = result["cutoff_at"].replace("2030", "2020")
        return result

    def extractor(self, path, *, options=None):
        self.calls.append(Path(path))
        return tracking(self.digest)

    def process(self, **kwargs):
        return intake(self).process_ready(self.private,
            now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"),
            extractor=self.extractor, **kwargs)

    def invoke(self, extra=(), *, extractor=None):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            try:
                code = intake(self).main(["--private-root", str(self.private), *extra], extractor=extractor)
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_enqueue_is_content_addressed_private_and_preserves_original(self):
        module = intake(self)
        before = (self.media.read_bytes(), self.media.stat().st_mtime_ns)
        ident = module.enqueue(self.private, self.media, self.job())
        self.assertRegex(ident, r"^[a-f0-9]{64}$")
        manifest = self.private / "video-intake" / "jobs" / (ident + ".json")
        copied = self.private / "video-intake" / "media" / (self.digest + ".media")
        stamp = manifest.stat().st_mtime_ns
        self.assertEqual(module.enqueue(self.private, self.media, self.job()), ident)
        self.assertEqual(manifest.stat().st_mtime_ns, stamp)
        self.assertEqual(copied.read_bytes(), before[0])
        self.assertEqual((self.media.read_bytes(), self.media.stat().st_mtime_ns), before)
        serialized = manifest.read_text()
        self.assertNotIn(str(self.media), serialized)
        self.assertNotIn(str(self.private), serialized)
        self.assertEqual(json.loads(serialized)["media_reference"], "media/" + self.digest + ".media")
        for path in (manifest, copied):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_distinct_media_continue_past_former_lifetime_byte_limit(self):
        module = intake(self)
        another = self.root / "another-authorized.mp4"
        another.write_bytes(b"a second small controlled local clip")
        another.chmod(0o600)
        second_job = self.job(number=2)
        second_job["source"]["media_sha256"] = sha256(another.read_bytes()).hexdigest()
        with patch.object(module, "_MAX_MEDIA_TOTAL", self.media.stat().st_size + 1, create=True):
            module.enqueue(self.private, self.media, self.job())
            module.enqueue(self.private, another, second_job)
        self.assertEqual(module.read_status(self.private)["counts"]["PENDING"], 2)
        copies = list((self.private / "video-intake" / "media").glob("*.media"))
        self.assertEqual(len(copies), 2)
        self.assertEqual(sum(path.stat().st_size for path in copies),
                         self.media.stat().st_size + another.stat().st_size)
        self.assertEqual(another.read_bytes(), b"a second small controlled local clip")

    def test_jobs_and_terminal_states_continue_past_former_lifetime_file_limit(self):
        module = intake(self)
        with patch.object(module, "_MAX_FILES", 1, create=True):
            module.enqueue(self.private, self.media, self.job())
            module.enqueue(self.private, self.media, self.job(number=2))
            result = self.process()
            self.assertEqual(result["succeeded"], 2)
            self.assertEqual(module.read_status(self.private)["counts"]["SUCCEEDED"], 2)
            self.assertEqual(self.process()["processed"], 0)

    def test_saved_report_validation_has_no_inherited_bulk_archive_stop(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        self.assertEqual(self.process()["succeeded"], 1)
        from race_ai import boat_video_evaluation as evaluation
        with patch.object(evaluation, "_MAX_FILES", 0), patch.object(evaluation, "_MAX_TOTAL", 1):
            self.assertEqual(module.read_status(self.private)["counts"]["SUCCEEDED"], 1)
            self.assertEqual(self.process()["processed"], 0)

    def test_enqueue_disk_space_failure_is_explicit_and_preserves_original(self):
        module = intake(self)
        before = self.media.read_bytes()
        with patch.object(module, "_atomic", side_effect=OSError(errno.ENOSPC, "owner-secret path")):
            with self.assertRaisesRegex(ValueError, "^BOAT_VIDEO_INTAKE_STORAGE_UNAVAILABLE$"):
                module.enqueue(self.private, self.media, self.job())
        self.assertEqual(self.media.read_bytes(), before)
        self.assertEqual(sum(module.read_status(self.private)["counts"].values()), 0)

    def test_report_disk_space_failure_is_persisted_without_marking_success(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        with patch.object(module, "save_evaluation", side_effect=OSError(errno.ENOSPC, "owner-secret path")):
            result = self.process()
        self.assertEqual((result["succeeded"], result["failed"]), (0, 1))
        self.assertEqual(result["states"][0]["failure_code"], "STORAGE_UNAVAILABLE")
        self.assertNotIn("owner-secret", json.dumps(result))
        self.assertEqual(self.process()["processed"], 0)
        self.assertTrue(self.media.exists())

    def test_process_saves_real_measurements_once_across_restarts_and_keeps_actual_clock(self):
        module = intake(self)
        ident = module.enqueue(self.private, self.media, self.job())
        original = self.root / "forecasts.json"
        original.write_bytes(b"frozen original forecast")
        first = self.process()
        self.assertEqual((first["processed"], first["succeeded"], first["failed"]), (1, 1, 0))
        self.assertEqual(first["counts"]["SUCCEEDED"], 1)
        self.assertEqual(first["states"][0]["job_sha256"], ident)
        self.assertEqual(first["states"][0]["availability"], "LATE_HISTORICAL")
        from race_ai.boat_video_evaluation import read_evaluations
        report, = read_evaluations(self.private)
        self.assertEqual(report["validation_status"], "UNVALIDATED")
        self.assertFalse(report["model_eligible"])
        self.assertFalse(report["pre_cutoff_available"])
        self.assertGreater(datetime.fromisoformat(report["analysis_started_at"]).year, 2020)
        phases = report["measurements"]["lanes"][0]["phases"]
        self.assertEqual(next(m["value"] for m in phases["straight"]["metrics"]
                              if m["name"] == "mean_interval_speed"), 10.0)
        importlib.reload(module)
        second = self.process()
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["counts"]["SUCCEEDED"], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertNotEqual(self.calls[0], self.media)
        self.assertEqual(original.read_bytes(), b"frozen original forecast")
        self.assertEqual(len(read_evaluations(self.private)), 1)

    def test_empty_source_health_is_explicit_and_status_never_extracts(self):
        module = intake(self)
        status = module.read_status(self.private)
        self.assertEqual(status["status"], "WAITING_FOR_AUTHORIZED_SOURCE")
        self.assertEqual(sum(status["counts"].values()), 0)
        self.assertFalse(status["source_acquisition_complete"])
        self.assertEqual(self.process()["processed"], 0)
        self.assertFalse(self.calls)

        module.enqueue(self.private, self.media, self.job())
        status = module.read_status(self.private)
        self.assertEqual(status["counts"]["PENDING"], 1)
        self.assertNotIn(str(self.root), json.dumps(status))
        self.assertFalse(self.calls)

    def test_default_processing_does_not_create_model_connection_store(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        summary = self.process()
        self.assertNotIn('model_connections', summary)
        self.assertFalse((self.private / 'video-connections').exists())

    def test_connect_models_empty_queue_cli_has_no_private_path_or_new_predictions(self):
        code, output, error = self.invoke(('--connect-models',))
        self.assertEqual((code, error), (0, ''))
        summary = json.loads(output)
        self.assertEqual(summary['model_connections']['status'], 'WAITING_FOR_COMPLETED_REPORTS')
        self.assertEqual(summary['model_connections']['processed'], 0)
        self.assertNotIn(str(self.private), output)

    def test_new_completed_report_calls_actual_coordinator_and_poll_restart_deduplicates(self):
        module = intake(self)
        from race_ai import boat_video_connection as connection
        module.enqueue(self.private, self.media, self.job())
        with patch.object(connection, 'connect_report', wraps=connection.connect_report) as actual:
            first = self.process(connect_models=True)
            second = self.process(connect_models=True)
            importlib.reload(module)
            third = self.process(connect_models=True)
        self.assertEqual(actual.call_count, 1)
        self.assertEqual(first['counts']['SUCCEEDED'], 1)
        self.assertEqual(first['model_connections']['processed'], 1)
        self.assertEqual(second['model_connections']['processed'], 0)
        self.assertEqual(third['model_connections']['reused'], 1)
        saved = list((self.private / 'video-connections').glob('*.json'))
        self.assertEqual(len(saved), 1)
        bundle = json.loads(saved[0].read_text())
        self.assertEqual(saved[0].stem, bundle['connection_sha256'])
        self.assertEqual(bundle['status'], 'BLOCKED')
        self.assertIn('ACTUAL_INFERENCE_POST_CUTOFF', bundle['missing_reasons'])
        self.assertEqual(stat.S_IMODE(saved[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(saved[0].parent.stat().st_mode), 0o700)
        self.assertNotIn(str(self.private), json.dumps(first))

    def test_changed_identity_evidence_creates_new_immutable_attempt_using_actual_clock(self):
        module = intake(self)
        from race_ai.boat_video_evaluation import save_evaluation
        from tests.test_boat_video_model_context import fixture, seal_evidence
        from copy import deepcopy
        report, evidence = fixture()
        save_evaluation(self.private, report)
        first = module.process_connections(self.private)
        paths = list((self.private / 'video-connections').glob('*.json'))
        original = {path.name: path.read_bytes() for path in paths}
        second = module.process_connections(self.private, identity_evidence_provider=lambda _: deepcopy(evidence))
        again = module.process_connections(self.private, identity_evidence_provider=lambda _: deepcopy(evidence))
        changed = deepcopy(evidence)
        changed['identities'][0]['reviewer_id'] = 'another-fictional-reader'
        changed = seal_evidence(changed)
        third = module.process_connections(self.private, identity_evidence_provider=lambda _: changed)
        self.assertEqual((first['processed'], second['processed'], again['processed'], third['processed']), (1, 1, 0, 1))
        self.assertEqual(len(list((self.private / 'video-connections').glob('*.json'))), 3)
        for name, raw in original.items():
            self.assertEqual((self.private / 'video-connections' / name).read_bytes(), raw)
        for path in (self.private / 'video-connections').glob('*.json'):
            bundle = json.loads(path.read_text())
            self.assertNotEqual(bundle['started_at'], report['analysis_completed_at'])
            self.assertEqual(bundle['video_context']['as_of'], bundle['started_at'])

    def test_connection_failure_never_changes_succeeded_report_or_job_state(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        first = self.process()
        saved = {str(path): path.read_bytes() for directory in ('video-evaluations', 'video-intake/states')
                 for path in (self.private / directory).glob('*.json')}
        from race_ai import boat_video_connection as connection
        with patch.object(connection, 'connect_report', side_effect=RuntimeError('private path detail')):
            result = self.process(connect_models=True)
        self.assertEqual(result['counts']['SUCCEEDED'], 1)
        self.assertEqual(result['model_connections']['failed'], 1)
        self.assertNotIn('private path detail', json.dumps(result))
        for path, raw in saved.items():
            self.assertEqual(Path(path).read_bytes(), raw)

    def test_connection_report_scan_has_no_inherited_bulk_report_quota(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        self.assertEqual(self.process()['succeeded'], 1)
        from race_ai import boat_video_evaluation as evaluation
        with patch.object(evaluation, '_MAX_FILES', 0), patch.object(evaluation, '_MAX_TOTAL', 1):
            self.assertEqual(module.process_connections(self.private)['processed'], 1)

    def test_selected_connection_reads_only_requested_report(self):
        module = intake(self)
        from race_ai.boat_video_evaluation import save_evaluation
        from tests.test_boat_video_model_context import fixture
        from tests.test_boat_video_evaluation import reseal
        from copy import deepcopy
        report, _ = fixture()
        other = deepcopy(report); other['race_id'] = '20300401-01-02'; other = reseal(other)
        save_evaluation(self.private, report); save_evaluation(self.private, other)
        with patch.object(module, '_read_report', wraps=module._read_report) as reads:
            result = module.process_connections(self.private, report_sha256s=[report['report_sha256']])
        self.assertEqual(result['processed'], 1)
        self.assertEqual([call.args[1] for call in reads.call_args_list], [report['report_sha256']+'.json'])

    def test_connection_rescan_considers_upcoming_cutoffs_before_historical_reports(self):
        module = intake(self)
        from race_ai.boat_video_evaluation import save_evaluation
        from tests.test_boat_video_model_context import fixture
        from tests.test_boat_video_evaluation import reseal
        from copy import deepcopy
        report, _ = fixture()
        historical = deepcopy(report)
        for key in ('race_id', 'cutoff_at', 'analysis_started_at', 'analysis_completed_at'):
            historical[key] = historical[key].replace('2030', '2020')
        historical['source']['captured_at'] = historical['source']['captured_at'].replace('2030', '2020')
        historical = reseal(historical)
        save_evaluation(self.private, historical); save_evaluation(self.private, report)
        considered = []
        def provider(raw):
            considered.append(raw['race_id'])
        module.process_connections(self.private, identity_evidence_provider=provider)
        self.assertEqual(considered, [report['race_id'], historical['race_id']])

    def test_failed_immediate_connection_does_not_block_next_job_or_repeat_same_poll(self):
        module = intake(self)
        from race_ai import boat_video_connection as connection
        module.enqueue(self.private, self.media, self.job())
        module.enqueue(self.private, self.media, self.job(number=2))
        analyze, connect, events = module.analyze_video, connection.connect_report, []
        def observe_analysis(path, specification, **kwargs):
            events.append('analyze:'+specification['race_id'][-2:])
            return analyze(path, specification, **kwargs)
        def observe_connection(report, **kwargs):
            number = report['race_id'][-2:]
            events.append('connect:'+number)
            if number == '01':
                raise RuntimeError('private connection failure detail')
            return connect(report, **kwargs)
        with patch.object(module, 'analyze_video', side_effect=observe_analysis), \
             patch.object(connection, 'connect_report', side_effect=observe_connection):
            result = self.process(connect_models=True)
        self.assertEqual(events, ['analyze:01', 'connect:01', 'analyze:02', 'connect:02'])
        self.assertEqual(result['counts']['SUCCEEDED'], 2)
        self.assertEqual(result['model_connections']['failed'], 1)
        self.assertEqual(result['model_connections']['processed'], 1)
        self.assertEqual(result['model_connections']['reused'], 0)
        self.assertEqual(len(result['model_connections']['states']), 2)
        self.assertNotIn('private connection failure', json.dumps(result))

    def test_digest_mismatch_foreign_source_and_unsafe_inputs_are_rejected(self):
        module = intake(self)
        bad = self.job(); bad["source"]["media_sha256"] = "f" * 64
        with self.assertRaises(ValueError): module.enqueue(self.private, self.media, bad)
        bad = self.job(); bad["source"].update(kind="OFFICIAL_BROWSER_CAPTURE",
            public_page_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20200401&jcd=02&rno=1")
        with self.assertRaises(ValueError): module.enqueue(self.private, self.media, bad)
        link = self.root / "linked.mp4"; link.symlink_to(self.media)
        with self.assertRaises(ValueError): module.enqueue(self.private, link, self.job())
        link.unlink(); os.link(self.media, link)
        with self.assertRaises(ValueError): module.enqueue(self.private, self.media, self.job())
        link.unlink()
        self.media.chmod(0o644)
        with self.assertRaises(ValueError): module.enqueue(self.private, self.media, self.job())
        self.media.chmod(0o600)
        git = self.root / "repository"; git.mkdir(mode=0o700); (git / ".git").mkdir()
        with self.assertRaises(ValueError): module.enqueue(git, self.media, self.job())
        local = git / "raw.mp4"; local.write_bytes(self.media.read_bytes()); local.chmod(0o600)
        with self.assertRaises(ValueError): module.enqueue(self.private, local, self.job())

    def test_mutated_private_media_fails_once_without_saving_report(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        copied = self.private / "video-intake" / "media" / (self.digest + ".media")
        copied.write_bytes(b"changed after enqueue")
        first = self.process()
        self.assertEqual((first["succeeded"], first["failed"]), (0, 1))
        self.assertEqual(first["states"][0]["failure_code"], "MEDIA_INTEGRITY_REJECTED")
        self.assertEqual(self.process()["processed"], 0)
        self.assertFalse(self.calls)
        from race_ai.boat_video_evaluation import read_evaluations
        self.assertEqual(read_evaluations(self.private), [])

    def test_failed_decoder_is_terminal_and_newly_delivered_job_is_consumed(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        def broken(path, *, options=None):
            raise RuntimeError("private secret decoder detail")
        first = module.process_ready(self.private,
            now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=broken)
        self.assertEqual(first["counts"]["FAILED"], 1)
        self.assertNotIn("private secret", json.dumps(first))
        second_id = module.enqueue(self.private, self.media, self.job(number=2))
        second = self.process()
        self.assertEqual(second["processed"], 1)
        self.assertEqual(second["states"][0]["job_sha256"], second_id)
        self.assertEqual(second["counts"]["FAILED"], 1)
        self.assertEqual(second["counts"]["SUCCEEDED"], 1)

    def test_priority_window_precedes_late_history_then_chronological_cutoff(self):
        module = intake(self)
        later = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T12:05:00+09:00", number=5))
        history = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T11:00:00+09:00", number=1))
        early = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T12:00:00+09:00", number=4))
        urgent = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T11:59:00+09:00", number=3))
        waiting = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T12:20:00+09:00", number=6))
        result = self.process()
        self.assertEqual([row["job_sha256"] for row in result["states"]], [early, later, urgent, history])
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["counts"]["PENDING"], 1)
        self.assertNotIn(waiting, [row["job_sha256"] for row in result["states"]])

    def test_new_priority_delivery_runs_before_remaining_historical_jobs(self):
        module = intake(self)
        first = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T10:00:00+09:00", number=1))
        historical = module.enqueue(self.private, self.media,
            self.job(cutoff="2030-04-01T10:05:00+09:00", number=2))
        urgent = []
        def arriving(path, *, options=None):
            if not urgent:
                urgent.append(module.enqueue(self.private, self.media,
                    self.job(cutoff="2030-04-01T12:00:00+09:00", number=3)))
            return tracking(self.digest)
        result = module.process_ready(self.private,
            now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=arriving)
        self.assertEqual([state["job_sha256"] for state in result["states"]],
                         [first, urgent[0], historical])
        self.assertEqual(result["counts"]["SUCCEEDED"], 3)
        self.assertEqual(self.process()["processed"], 0)

    def test_interrupted_attempt_is_retained_without_automatic_reanalysis(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        def interrupted(path, *, options=None):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            module.process_ready(self.private,
                now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=interrupted)
        self.assertEqual(module.read_status(self.private)["counts"]["PROCESSING"], 1)
        restarted = self.process()
        self.assertEqual(restarted["counts"]["FAILED"], 1)
        self.assertEqual(restarted["states"][0]["failure_code"], "INTERRUPTED_PREVIOUS_ATTEMPT")
        self.assertEqual(self.process()["processed"], 0)
        self.assertFalse(self.calls)

    def test_nonstandard_decoder_failure_is_persisted_and_does_not_block_next_job(self):
        module = intake(self)
        first = module.enqueue(self.private, self.media, self.job())
        second = module.enqueue(self.private, self.media, self.job(number=2))
        attempts = []
        class DecoderError(Exception):
            pass
        def extractor(path, *, options=None):
            attempts.append(path)
            if len(attempts) == 1:
                raise DecoderError("sensitive implementation detail")
            return tracking(self.digest)
        result = module.process_ready(self.private,
            now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=extractor)
        self.assertEqual((result["failed"], result["succeeded"]), (1, 1))
        self.assertEqual(set(row["job_sha256"] for row in result["states"]), {first, second})
        self.assertNotIn("sensitive", json.dumps(result))

    def test_missing_listed_manifest_is_integrity_failure_not_empty_source_health(self):
        module = intake(self)
        ident = module.enqueue(self.private, self.media, self.job())
        manifest = self.private / "video-intake" / "jobs" / (ident + ".json")
        actual = module._read
        def vanished(parent, name):
            if name == manifest.name:
                raise FileNotFoundError()
            return actual(parent, name)
        with patch.object(module, "_read", side_effect=vanished), self.assertRaises(ValueError):
            module.read_status(self.private)

    def test_consumer_lock_is_nonblocking_and_prevents_parallel_analysis(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        lock = self.private / "video-intake" / "process.lock"
        with lock.open("a+b") as held:
            lock.chmod(0o600)
            fcntl.flock(held.fileno(), fcntl.LOCK_EX)
            result = self.process()
        self.assertEqual(result["status"], "BUSY")
        self.assertEqual(result["processed"], 0)
        self.assertFalse(self.calls)
        self.assertEqual(self.process()["succeeded"], 1)

    def test_status_sees_complete_publication_before_temporary_cleanup(self):
        module = intake(self)
        actual_unlink = module.os.unlink
        published, release = threading.Event(), threading.Event()
        def paused_unlink(name, *, dir_fd=None):
            if str(name).startswith(".tmp-") and dir_fd is not None and any(
                    entry.endswith(".json") for entry in os.listdir(dir_fd)):
                published.set()
                release.wait(2)
            return actual_unlink(name, dir_fd=dir_fd)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(module.os, "unlink", side_effect=paused_unlink):
                queued = pool.submit(module.enqueue, self.private, self.media, self.job())
                self.assertTrue(published.wait(2))
                try:
                    status = module.read_status(self.private)
                finally:
                    release.set()
                queued.result(timeout=2)
        self.assertEqual(status["counts"]["PENDING"], 1)

    def _kill_publication_child(self, root, stage):
        code = """
from datetime import datetime
import json, os, re, signal, sys
from race_ai import boat_video_intake as intake
from tests.test_boat_video_intake import tracking
root, media, stage = sys.argv[1:]
job = json.loads(sys.stdin.read())
unlink = os.unlink
def stop_before_cleanup(name, *, dir_fd=None):
    if str(name).startswith('.tmp-') and dir_fd is not None:
        names = os.listdir(dir_fd)
        selected = (stage == 'media' and any(n.endswith('.media') for n in names) or
                    stage == 'job' and any(re.fullmatch(r'[a-f0-9]{64}\\.json', n) for n in names) or
                    stage == 'started' and any(n.endswith('.started.json') for n in names) or
                    stage == 'finished' and any(n.endswith('.finished.json') for n in names))
        if selected:
            print('PUBLISHED', flush=True)
            signal.pause()
    return unlink(name, dir_fd=dir_fd)
intake.os.unlink = stop_before_cleanup
if stage == 'partial':
    atomic = intake._atomic
    def partial_write(parent, name, writer):
        if not name.endswith('.media'):
            return atomic(parent, name, writer)
        def interrupted_writer(target):
            target.write(b'private partial copy')
            target.flush()
            os.fsync(target.fileno())
            print('PARTIAL', flush=True)
            signal.pause()
        return atomic(parent, name, interrupted_writer)
    intake._atomic = partial_write
if stage in ('media', 'job', 'partial'):
    intake.enqueue(root, media, job)
else:
    intake.process_ready(root, now=datetime.fromisoformat('2020-04-01T11:50:00+09:00'),
        extractor=lambda path, *, options=None: tracking(job['source']['media_sha256']))
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(root), str(self.media), stage],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            child.stdin.write(json.dumps(self.job()))
            child.stdin.close()
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(timeout=10), "publication checkpoint was not reached")
                checkpoint = child.stdout.readline().strip()
            if checkpoint != ("PARTIAL" if stage == "partial" else "PUBLISHED"):
                self.fail("publication child exited before checkpoint: " + child.stderr.read())
            child.kill()
            self.assertEqual(child.wait(timeout=5), -signal.SIGKILL)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()

    def test_sigkill_after_each_publication_keeps_queue_readable_and_restartable(self):
        module = intake(self)
        original = self.media.read_bytes()
        for stage in ("media", "job", "started", "finished"):
            with self.subTest(stage=stage):
                root = self.private / stage
                root.mkdir(mode=0o700)
                if stage in ("started", "finished"):
                    module.enqueue(root, self.media, self.job())
                self._kill_publication_child(root, stage)
                published = [path for path in (root / "video-intake").rglob("*")
                             if path.is_file() and not path.name.startswith(".tmp-")
                             and path.name not in ("enqueue.lock", "process.lock")]
                self.assertTrue(published)
                self.assertTrue(all(path.stat().st_nlink == 1 for path in published))
                status = module.read_status(root)
                calls = []
                def extract(path, *, options=None):
                    calls.append(path)
                    return tracking(self.digest)
                if stage == "media":
                    self.assertEqual(sum(status["counts"].values()), 0)
                    module.enqueue(root, self.media, self.job())
                result = module.process_ready(root,
                    now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=extract)
                if stage in ("media", "job"):
                    self.assertEqual((result["succeeded"], len(calls)), (1, 1))
                elif stage == "started":
                    self.assertEqual((result["failed"], len(calls)), (1, 0))
                    self.assertEqual(result["states"][0]["failure_code"], "INTERRUPTED_PREVIOUS_ATTEMPT")
                else:
                    self.assertEqual((result["processed"], len(calls)), (0, 0))
                    self.assertEqual(status["counts"]["SUCCEEDED"], 1)
                module.enqueue(root, self.media, self.job(number=2))
                self.assertEqual(module.process_ready(root,
                    now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=extract)["succeeded"], 1)
                self.assertEqual(self.media.read_bytes(), original)

    def test_sigkill_during_copy_leaves_only_private_ignored_partial_temporary(self):
        module = intake(self)
        original = self.media.read_bytes()
        self._kill_publication_child(self.private, "partial")
        media_store = self.private / "video-intake" / "media"
        partial, = media_store.glob(".tmp-*")
        self.assertEqual(partial.read_bytes(), b"private partial copy")
        self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o600)
        self.assertEqual(partial.stat().st_nlink, 1)
        self.assertFalse(list(media_store.glob("*.media")))
        self.assertEqual(sum(module.read_status(self.private)["counts"].values()), 0)
        module.enqueue(self.private, self.media, self.job())
        self.assertEqual(self.process()["succeeded"], 1)
        self.assertEqual(self.media.read_bytes(), original)
        self.assertEqual(partial.read_bytes(), b"private partial copy")

    def test_atomic_publication_never_replaces_existing_file_or_symlink(self):
        module = intake(self)
        target = self.private / "immutable"
        target.write_bytes(b"existing immutable content")
        target.chmod(0o600)
        original = target.stat()
        alias = self.private / "existing-link"
        alias.symlink_to(self.media)
        descriptor = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for name in (target.name, alias.name):
                with self.subTest(name=name), self.assertRaises(FileExistsError):
                    module._atomic(descriptor, name, lambda stream: stream.write(b"attempted replacement"))
        finally:
            os.close(descriptor)
        self.assertEqual(target.read_bytes(), b"existing immutable content")
        self.assertEqual((target.stat().st_ino, target.stat().st_mtime_ns),
                         (original.st_ino, original.st_mtime_ns))
        self.assertTrue(alias.is_symlink())
        self.assertEqual(self.media.read_bytes(), b"controlled extractor fixture, not an official video")

    def test_foreign_hardlinks_to_published_media_jobs_and_states_remain_rejected(self):
        module = intake(self)
        ident = module.enqueue(self.private, self.media, self.job())
        media = self.private / "video-intake" / "media" / (self.digest + ".media")
        alias = self.root / "foreign-alias"
        os.link(media, alias)
        with self.assertRaises(ValueError): module.enqueue(self.private, self.media, self.job())
        alias.unlink()
        job = self.private / "video-intake" / "jobs" / (ident + ".json")
        os.link(job, alias)
        with self.assertRaises(ValueError): module.read_status(self.private)
        alias.unlink()
        self.assertEqual(self.process()["succeeded"], 1)
        state = self.private / "video-intake" / "states" / (ident + ".finished.json")
        os.link(state, alias)
        with self.assertRaises(ValueError): module.read_status(self.private)
        alias.unlink()
        self.assertEqual(module.read_status(self.private)["counts"]["SUCCEEDED"], 1)

    def test_original_media_can_change_after_enqueue_without_changing_bound_copy(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        self.media.write_bytes(b"owner independently replaced the original")
        result = self.process()
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(self.media.read_bytes(), b"owner independently replaced the original")

    def test_source_change_before_manifest_publication_cannot_leave_a_queued_job(self):
        module = intake(self)
        actual = module._atomic
        def changed(parent, name, writer):
            actual(parent, name, writer)
            if name.endswith(".media"):
                self.media.write_bytes(b"changed during enqueue")
        with patch.object(module, "_atomic", side_effect=changed), self.assertRaises(ValueError):
            module.enqueue(self.private, self.media, self.job())
        self.assertEqual(sum(module.read_status(self.private)["counts"].values()), 0)

    def test_growing_source_is_bounded_before_extra_bytes_are_written_to_copy(self):
        module = intake(self)
        actual = module._atomic
        written = []
        def growing(parent, name, writer):
            if not name.endswith(".media"):
                return actual(parent, name, writer)
            self.media.write_bytes(self.media.read_bytes() + b"x" * 1024)
            def bounded_writer(target):
                class CountingTarget:
                    def write(self, chunk):
                        written.append(len(chunk))
                        if sum(written) > 128:
                            raise AssertionError("consumer copied more than its media limit")
                        return target.write(chunk)
                writer(CountingTarget())
            return actual(parent, name, bounded_writer)
        with patch.object(module, "_MAX_MEDIA", 128), patch.object(module, "_atomic", side_effect=growing):
            with self.assertRaises(ValueError):
                module.enqueue(self.private, self.media, self.job())
        self.assertLessEqual(sum(written), 128)

    def test_tampering_during_extraction_never_saves_a_success_report(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        def tampering(path, *, options=None):
            Path(path).write_bytes(b"tampered during extraction")
            return tracking(self.digest)
        result = module.process_ready(self.private,
            now=datetime.fromisoformat("2020-04-01T11:50:00+09:00"), extractor=tampering)
        self.assertEqual((result["succeeded"], result["failed"]), (0, 1))
        from race_ai.boat_video_evaluation import read_evaluations
        self.assertEqual(read_evaluations(self.private), [])

    def test_status_cannot_claim_success_when_its_sealed_report_is_missing(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        result = self.process()
        report_sha = result["states"][0]["report_sha256"]
        (self.private / "video-evaluations" / (report_sha + ".json")).unlink()
        with self.assertRaises(ValueError): module.read_status(self.private)
        with self.assertRaises(ValueError): self.process()

    def test_follow_keeps_polling_after_empty_queue_and_accepts_new_delivery(self):
        module = intake(self)
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        sleeps = []
        def next_delivery(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                module.enqueue(self.private, self.media, self.job())
            elif len(sleeps) == 3:
                raise KeyboardInterrupt()
        with patch.object(module.time, "sleep", side_effect=next_delivery), redirect_stdout(output):
            self.assertEqual(module.main(["--private-root", str(self.private), "--follow", "--poll-seconds", "0.1"],
                                         extractor=self.extractor), 0)
        polls = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([poll["processed"] for poll in polls], [0, 1, 0])
        self.assertEqual(polls[-1]["counts"]["SUCCEEDED"], 1)
        self.assertEqual(len(self.calls), 1)

    def test_cli_defaults_to_one_empty_poll_and_rejects_secret_arguments_safely(self):
        intake(self)
        command = [sys.executable, "scripts/boat_video_intake.py", "--private-root", str(self.private)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)["status"], "WAITING_FOR_AUTHORIZED_SOURCE")
        bad = subprocess.run(command + ["--unknown=secret-token"], capture_output=True, text=True, timeout=10)
        self.assertEqual(bad.returncode, 2)
        self.assertNotIn("secret-token", bad.stderr)

    def test_identity_follow_uses_fresh_provider_for_each_delivery_and_keeps_assets_private(self):
        module = intake(self)
        model = self.root / "owner-secret-hull.onnx"
        ocr = self.root / "owner-secret-tesseract"
        data = self.root / "owner-secret-tessdata"
        model.write_bytes(b"controlled local factory boundary")
        ocr.write_bytes(b"controlled local factory boundary")
        data.mkdir()
        job = self.job(); job["options"] = {"sampling_fps": 5.0}
        module.enqueue(self.private, self.media, job)
        providers, configurations, sleeps = [], [], []
        class Provider:
            used = False
        def create_provider(**configuration):
            provider = Provider()
            providers.append(provider)
            configurations.append(configuration)
            return provider
        def extract_tracks(path, *, options=None, identity_provider=None):
            if identity_provider.used:
                raise ValueError("temporal identity state leaked between media")
            identity_provider.used = True
            report = tracking(self.digest)
            for lane in report["tracks"]:
                lane["identity_status"] = "NUMBER_TEMPORAL_CANDIDATE"
            return report
        def next_delivery(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                job = self.job(number=2); job["options"] = {"sampling_fps": 5.0}
                module.enqueue(self.private, self.media, job)
            elif len(sleeps) == 3:
                raise KeyboardInterrupt()
        flags = ["--follow", "--poll-seconds", "0.1", "--hull-model", str(model),
                 "--detector-kind", "nanodet", "--tesseract", str(ocr), "--tessdata", str(data)]
        with patch("race_ai.boat_video_identity.create_local_identity_provider", side_effect=create_provider), \
             patch("race_ai.boat_video_tracking.extract_tracks", side_effect=extract_tracks), \
             patch.object(module.time, "sleep", side_effect=next_delivery):
            code, output, error = self.invoke(flags)
        self.assertEqual((code, error), (0, ""))
        polls = [json.loads(line) for line in output.splitlines()]
        self.assertEqual([poll["succeeded"] for poll in polls], [1, 1, 0])
        self.assertEqual(polls[-1]["counts"]["SUCCEEDED"], 2)
        self.assertEqual(len(providers), 2)
        self.assertIsNot(providers[0], providers[1])
        self.assertTrue(all(provider.used for provider in providers))
        self.assertTrue(all(configuration["model_path"] == model and
                            configuration["tesseract_path"] == ocr and
                            configuration["tessdata_path"] == data and
                            configuration["detector_kind"] == "nanodet"
                            for configuration in configurations))
        from race_ai.boat_video_evaluation import read_evaluations
        reports = read_evaluations(self.private)
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertEqual(report["analysis_parameters"], {"options": {"sampling_fps": 5.0}})
            self.assertEqual([row["identity_status"] for row in report["measurements"]["lanes"]],
                             ["NUMBER_TEMPORAL_CANDIDATE"] * 6)
            self.assertFalse(report["model_eligible"])
            self.assertEqual(report["validation_status"], "UNVALIDATED")
        for private_path in (model, ocr, data):
            self.assertNotIn(str(private_path), output + error)
            for persisted in self.private.rglob("*.json"):
                self.assertNotIn(str(private_path), persisted.read_text())

    def test_identity_defaults_resolve_system_ocr_without_changing_job_options(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        model = self.root / "owner-secret-hull.onnx"
        standard = Path("/usr/share/tesseract-ocr/5/tessdata")
        is_file = Path.is_file
        with patch("race_ai.boat_video_identity.make_local_identity_extractor", return_value=self.extractor) as factory, \
             patch("shutil.which", return_value="/usr/bin/tesseract"), \
             patch("pathlib.Path.is_file", autospec=True,
                   side_effect=lambda path: path == standard / "eng.traineddata" or is_file(path)):
            code, output, error = self.invoke(["--hull-model", str(model)])
        self.assertEqual((code, error), (0, ""))
        factory.assert_called_once_with(model_path=model, detector_kind="yolox",
                                       tesseract_path=Path("/usr/bin/tesseract"), tessdata_path=standard)
        self.assertEqual(json.loads(output)["succeeded"], 1)

    def test_no_identity_flags_keep_default_hsv_boundary_and_do_not_load_assets(self):
        module = intake(self)
        module.enqueue(self.private, self.media, self.job())
        with patch("race_ai.boat_video_identity.make_local_identity_extractor", side_effect=AssertionError("loaded assets")), \
             patch("race_ai.boat_video_tracking.extract_tracks", side_effect=self.extractor):
            code, output, error = self.invoke()
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output)["succeeded"], 1)
        from race_ai.boat_video_evaluation import read_evaluations
        report, = read_evaluations(self.private)
        self.assertEqual(report["analysis_parameters"], {})
        self.assertEqual([row["identity_status"] for row in report["tracking"]["tracks"]],
                         ["COLOR_CANDIDATE"] * 6)

    def test_identity_companions_require_model_and_model_rejects_injected_extractor(self):
        for flags, extractor in ((["--detector-kind", "nanodet"], None),
                                 (["--tesseract", "/owner-secret/ocr"], None),
                                 (["--tessdata", "/owner-secret/data"], None),
                                 (["--hull-model", "/owner-secret/hull"], self.extractor)):
            with self.subTest(flags=flags):
                code, output, error = self.invoke(flags, extractor=extractor)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertNotIn("owner-secret", error)
                self.assertEqual(list(self.private.iterdir()), [])

    def test_missing_default_ocr_fails_before_poll_without_leaking_asset_paths(self):
        intake(self)
        with patch("shutil.which", return_value=None):
            code, output, error = self.invoke(["--hull-model", "/owner-secret/hull.onnx"])
        self.assertEqual((code, output, error), (2, "", "BOAT_VIDEO_INTAKE_REJECTED\n"))
        self.assertEqual(list(self.private.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
