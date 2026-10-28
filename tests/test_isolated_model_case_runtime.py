"""Authored inputs and real local children; no provider or cloud operations."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tracemalloc
import unittest
from unittest.mock import patch

from tests.test_permissioned_model_case import fixture
from tests.test_permissioned_source_delivery import snapshot, AT

ROOT = Path(__file__).resolve().parent.parent
PIN = "db075c203704d2b30df5742ce8458a43932696a4"
MANIFEST = "6116f1eb3e4746e496b041dce3161dab8421811ddd300b444302787325371c8c"
PROFILE = "MAX8_COMPLETE_UNIVERSE"
SCHEMA = "RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def authored(sport="autorace"):
    request, _, policy = fixture()
    supplied = snapshot(sport)
    supplied["participants"] = supplied["participants"][:3]
    from race_ai.permissioned_source_delivery import FEED_SCHEMA
    raw = canonical({"schema": FEED_SCHEMA, "snapshot": supplied}).encode()
    row = next(row for row in request["ledger"]["records"]
               if row["sport"] == ("horse_local" if sport == "horse" else sport))
    request.update(schema=SCHEMA, race_id=row["race_id"], source_payload_sha256=sha(raw),
        feature_snapshot_sha256=sha(canonical(supplied).encode()), as_of=supplied["race"]["as_of"],
        sales_cutoff_at=supplied["race"]["sales_cutoff_at"], model_source_sha40=PIN)
    decisions = {}
    entries = [value for participant in supplied["participants"] for value in participant["features"].values()]
    entries += list(supplied["environment"].values())
    for entry in entries:
        for purpose in ("analysis", "private_storage", "private_derived"):
            key = sha(canonical([entry["source_ref"], entry["source_rights_ref"], purpose]).encode())
            decisions[key] = policy.authorize(entry["source_ref"], entry["source_rights_ref"], purpose) is True
    return request, sha(SCHEMA.encode() + b"\0" + canonical(request).encode()), raw, decisions


READY = {"schema": "RACE_AI_ISOLATED_CASE_READY_V1", "profile": PROFILE, "pin": PIN, "manifest_sha256": MANIFEST}
FRAME_CODE = "import json,struct,sys,time,os\ndef emit(x):\n b=json.dumps(x,sort_keys=True,separators=(',',':')).encode();sys.stdout.buffer.write(struct.pack('!I',len(b))+b);sys.stdout.buffer.flush()\n"


class IsolatedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.isolated_model_case_runtime"),
                             "fixed isolated producer runtime is missing")
        self.runtime = importlib.import_module("race_ai.isolated_model_case_runtime")
        self.request, self.request_sha, self.raw, self.decisions = authored()
        self.children = []

    def produce(self, **overrides):
        options = {"started_at": AT, "admit_private_input": lambda: AT}
        options.update(overrides)
        return self.runtime.produce(self.request, self.request_sha, self.raw, self.decisions, **options)

    def fault(self, source):
        actual = subprocess.Popen
        def spawn(command, **kwargs):
            child = actual([sys.executable, "-I", "-S", "-B", "-u", "-c", source], **kwargs)
            self.children.append(child)
            return child
        return patch.object(self.runtime.subprocess, "Popen", side_effect=spawn)

    def assert_clean(self):
        self.assertTrue(all(child.poll() is not None for child in self.children))
        self.assertFalse([thread.name for thread in threading.enumerate() if thread.name.startswith("race32-")])

    def test_actual_n3_both_sports_original_wire_and_parent_modules_unchanged(self):
        from race_ai.private_delivery_codec import deserialize_private_delivery, serialize_private_delivery
        paths = tuple(sys.path)
        import race_ai
        package_path = tuple(race_ai.__path__)
        module = sys.modules["race_ai.four_sport_model_suite"]
        self.assertIs(self.runtime.preflight(), True)
        for sport in ("autorace", "horse", "autorace"):
            with self.subTest(sport=sport):
                self.request, self.request_sha, self.raw, self.decisions = authored(sport)
                before = deepcopy((self.request, self.decisions))
                wire, delivery_sha, actual = self.produce()
                delivery = deserialize_private_delivery(wire, expected_delivery_sha256=delivery_sha)
                self.assertEqual(wire, serialize_private_delivery(delivery))
                self.assertEqual(delivery["source_payload_sha256"], sha(self.raw))
                self.assertEqual(delivery["feature_snapshot_sha256"], self.request["feature_snapshot_sha256"])
                self.assertEqual(delivery["policy_record_sha256"], self.request["policy_record_sha256"])
                self.assertEqual(actual, "2030-01-15T00:15:00+00:00")
                self.assertEqual(delivery["ingested_at"], actual)
                self.assertEqual(len(delivery["research_suite"]["models"]), 4)
                for model in delivery["research_suite"]["models"].values():
                    self.assertEqual(model["candidate_count"], 6)
                    self.assertEqual(len({tuple(x) for x in model["ordered_top8"]}), 6)
                self.assertFalse(delivery["official_prediction"])
                self.assertFalse(delivery["can_count_in_hit_at_8"])
                self.assertEqual((self.request, self.decisions), before)
        self.assertEqual(tuple(sys.path), paths)
        self.assertEqual(tuple(race_ai.__path__), package_path)
        self.assertIs(sys.modules["race_ai.four_sport_model_suite"], module)
        self.assert_clean()

    def test_wrong_ready_never_invokes_private_admission(self):
        source = FRAME_CODE + "emit(" + repr({**READY, "pin": "f" * 40}) + ");time.sleep(10)"
        calls = []
        with self.fault(source), self.assertRaises(self.runtime.IsolatedModelError):
            self.produce(admit_private_input=lambda: calls.append(True) or AT)
        self.assertEqual(calls, [])
        self.assert_clean()

    def test_no_ready_hang_is_killed_and_all_threads_joined(self):
        start = time.monotonic()
        with self.fault("import time;time.sleep(10)"), patch.object(self.runtime, "TOTAL_SECONDS", .3):
            with self.assertRaises(self.runtime.IsolatedModelError):
                self.produce()
        self.assertLess(time.monotonic() - start, 2)
        self.assert_clean()

    def test_ready_does_not_reset_total_deadline_or_accept_late_private_admission(self):
        source = FRAME_CODE + "time.sleep(.15);emit(" + repr(READY) + ");time.sleep(10)"
        def slow():
            time.sleep(.3)
            return AT
        start = time.monotonic()
        with self.fault(source), patch.object(self.runtime, "TOTAL_SECONDS", .4):
            with self.assertRaises(self.runtime.IsolatedModelError):
                self.produce(admit_private_input=slow)
        self.assertLess(time.monotonic() - start, 2)
        self.assert_clean()

    def test_expired_rollback_naive_or_private_admission_exception_is_private(self):
        def secret():
            raise RuntimeError("FICTIONAL_PRIVATE_ADMISSION_KEY")
        for admission in (lambda: "2030-01-15T10:00:00+09:00", lambda: "2030-01-15T09:14:00+09:00",
                          lambda: "2030-01-15T09:15:00", secret, None):
            with self.subTest(admission=admission):
                try:
                    self.produce(admit_private_input=admission)
                except self.runtime.IsolatedModelError as error:
                    self.assertNotIn("FICTIONAL_PRIVATE_ADMISSION_KEY", "".join(traceback.format_exception(error)))
                else:
                    self.fail("unadmitted private send accepted")
        self.assert_clean()

    def test_oversized_result_truncation_and_stderr_flood_are_bounded(self):
        for tail in ("sys.stdout.buffer.write(struct.pack('!I',4097));sys.stdout.buffer.flush()",
                     "sys.stdout.buffer.write(struct.pack('!I',100)+b'x');sys.stdout.buffer.flush()",
                     "sys.stderr.write('FICTIONAL_PRIVATE_CHILD_KEY'*100000);sys.stderr.flush()"):
            with self.subTest(tail=tail):
                source = FRAME_CODE + "emit(" + repr(READY) + ");" + tail
                with self.fault(source), self.assertRaises(self.runtime.IsolatedModelError) as caught:
                    self.produce()
                self.assertNotIn("FICTIONAL_PRIVATE_CHILD_KEY", "".join(traceback.format_exception(caught.exception)))
                self.assert_clean()

    def test_minimal_child_environment_strips_secret_sentinels(self):
        worker_path = str(Path(self.runtime.worker.__file__).resolve())
        code = ("import os,runpy;assert 'FICTIONAL_PRIVATE_SOURCE_KEY' not in os.environ;"
                "assert 'PYTHONPATH' not in os.environ;runpy.run_path(" + repr(worker_path) + ",run_name='__main__')")
        with patch.dict(os.environ, {"FICTIONAL_PRIVATE_SOURCE_KEY": "NEVER_SEND", "PYTHONPATH": "fictional-hostile"}), self.fault(code):
            wire, _, _ = self.produce()
        self.assertIs(type(wire), bytes)
        self.assert_clean()

    def test_callback_mutation_or_invalid_original_inputs_never_send_private_frame(self):
        original = deepcopy(self.request)
        def mutate():
            self.request["case_id"] = "FICTIONAL_PRIVATE_MUTATION"
            return AT
        with self.assertRaises(self.runtime.IsolatedModelError):
            self.produce(admit_private_input=mutate)
        self.request = original
        for altered in ({**self.request, "model_source_sha40": "f" * 40},
                        {**self.request, "schema": SCHEMA.replace("V2", "V1")},
                        {**self.request, "padding": "x" * (8 * 1024 * 1024)}):
            with patch.object(self.runtime.subprocess, "Popen", side_effect=AssertionError("spawn before validation")):
                with self.assertRaises(self.runtime.IsolatedModelError):
                    self.runtime.produce(altered, self.request_sha, self.raw, self.decisions,
                                         started_at=AT, admit_private_input=lambda: AT)
        self.assert_clean()

    def test_missing_extra_or_nontrue_purpose_decisions_are_rejected(self):
        first = next(iter(self.decisions))
        for altered in ({}, {**self.decisions, "f" * 64: True}, {**self.decisions, first: 1},
                        {**self.decisions, first: False}):
            with self.subTest(altered=altered), self.assertRaises(self.runtime.IsolatedModelError):
                self.runtime.produce(self.request, self.request_sha, self.raw, altered,
                                     started_at=AT, admit_private_input=lambda: AT)
        self.assert_clean()

    def test_manifest_byte_mutation_and_reparse_bundle_reject_before_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "public-bundle"
            shutil.copytree(self.runtime.worker.BUNDLE, copied)
            target = copied / "race_ai" / "four_sport_model_suite.py"
            target.write_bytes(target.read_bytes() + b"\n# unexpected\n")
            with patch.object(self.runtime.worker, "BUNDLE", copied):
                with self.assertRaises(self.runtime.IsolatedModelError):
                    self.runtime.preflight()

    def test_blocked_private_writer_is_killed_and_reaped(self):
        source = FRAME_CODE + "emit(" + repr(READY) + ");time.sleep(10)"
        with self.fault(source), patch.object(self.runtime, "TOTAL_SECONDS", .4):
            with self.assertRaises(self.runtime.IsolatedModelError):
                self.produce()
        self.assert_clean()

    def test_fresh_after_ready_start_is_used_by_the_actual_original_delivery(self):
        wire, digest, actual = self.produce(admit_private_input=lambda: "2030-01-15T09:16:00+09:00")
        from race_ai.private_delivery_codec import deserialize_private_delivery
        restored = deserialize_private_delivery(wire, expected_delivery_sha256=digest)
        self.assertEqual(actual, "2030-01-15T00:16:00+00:00")
        self.assertEqual(restored["ingested_at"], actual)
        self.assert_clean()

    def test_verified_bytes_survive_same_path_bundle_mutation_after_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "public-bundle"
            shutil.copytree(self.runtime.worker.BUNDLE, copied)
            path = str(Path(self.runtime.worker.__file__).absolute())
            code = ("import runpy,pathlib;w=runpy.run_path(" + repr(path) + ");"
                    "w['_bundle'].__globals__['BUNDLE']=pathlib.Path(" + repr(str(copied)) + ");w['_run']()")
            def replace_after_ready():
                (copied / "race_ai" / "four_sport_model_suite.py").write_bytes(b"raise RuntimeError('FICTIONAL_PRIVATE_TAMPER')")
                return AT
            with self.fault(code):
                wire, _, _ = self.produce(admit_private_input=replace_after_ready)
            self.assertIs(type(wire), bytes)
            self.assert_clean()

    def test_closed_importer_rejects_unlisted_module_without_disk_fallback(self):
        path = str(Path(self.runtime.worker.__file__).absolute())
        code = ("import runpy,importlib;w=runpy.run_path(" + repr(path) + ");"
                "w['_install'](w['_bundle']());\n"
                "try:importlib.import_module('race_ai.fictional_unlisted')\n"
                "except ImportError:print('DENIED')\n"
                "else:raise AssertionError('unlisted module accepted')")
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-u", "-c", code],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, env={}, close_fds=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), [b"DENIED"])

    def test_preallocated_oversized_scalar_rejects_with_bounded_allocation(self):
        request = {**self.request, "case_id": "x" * (8 * 1024 * 1024)}
        tracemalloc.start()
        try:
            with self.assertRaises(self.runtime.IsolatedModelError):
                self.runtime.produce(request, self.request_sha, self.raw, self.decisions,
                                     started_at=AT, admit_private_input=lambda: AT)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 128 * 1024)

    def test_duplicate_noncanonical_and_wrong_phase_ready_are_not_admitted(self):
        canonical_ready = canonical(READY).encode()
        for raw in (canonical_ready.replace(b'{', b'{"schema":"duplicate",', 1),
                    json.dumps(READY).encode(), canonical_ready.replace(b'READY_V1', b'RESULT_V1'), b'\xff'):
            source = "import sys,struct;sys.stdout.buffer.write(struct.pack('!I',len(" + repr(raw) + "))+" + repr(raw) + ");sys.stdout.buffer.flush()"
            calls = []
            with self.fault(source), self.assertRaises(self.runtime.IsolatedModelError):
                self.produce(admit_private_input=lambda: calls.append(1) or AT)
            self.assertEqual(calls, [])
            self.assert_clean()

    def test_partial_session_start_failure_or_interrupt_reaps_child_and_reader(self):
        original_start = threading.Thread.start
        for target, failure in (("reader", RuntimeError), ("watchdog", RuntimeError), ("watchdog", KeyboardInterrupt)):
            with self.subTest(target=target, failure=failure):
                self.children = []
                def fail_start(thread):
                    if thread.name == "race32-" + target:
                        raise failure("FICTIONAL_PRIVATE_THREAD_DETAIL")
                    return original_start(thread)
                try:
                    with self.fault("import time;time.sleep(10)"), patch.object(threading.Thread, "start", fail_start):
                        with self.assertRaises((self.runtime.IsolatedModelError, KeyboardInterrupt)):
                            self.produce()
                    self.assert_clean()
                finally:
                    # The RED deliberately exposes an orphan; don't leave it alive.
                    for child in self.children:
                        if child.poll() is None:
                            child.kill()
                        child.wait(timeout=2)
                        for stream in (child.stdin, child.stdout):
                            stream.close()
                    for thread in threading.enumerate():
                        if thread.name.startswith("race32-"):
                            thread.join(timeout=2)

    def test_constructor_failure_cleans_up_started_child_without_private_traceback(self):
        with self.fault("import time;time.sleep(10)"), \
             patch.object(self.runtime, "_Session", side_effect=RuntimeError("FICTIONAL_PRIVATE_CONSTRUCTOR")):
            with self.assertRaises(self.runtime.IsolatedModelError) as caught:
                self.produce()
        self.assertNotIn("FICTIONAL_PRIVATE_CONSTRUCTOR", "".join(traceback.format_exception(caught.exception)))
        self.assert_clean()

    def test_post_ready_preallocated_eight_mib_mutation_is_bounded(self):
        oversized = "x" * (8 * 1024 * 1024)
        def mutation():
            tracemalloc.start()
            self.request["case_id"] = oversized
            return AT
        try:
            with self.assertRaises(self.runtime.IsolatedModelError):
                self.produce(admit_private_input=mutation)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 128 * 1024)
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
