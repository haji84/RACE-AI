"""Bounded app-owned rounds; services/sources below are entirely fictional."""
from datetime import datetime, timedelta, timezone
import importlib
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    M = importlib.import_module("race_ai.local_forecast_automation")
except ModuleNotFoundError:
    M = None


class Service:
    def __init__(self, root):
        self.root = root
        self.now = datetime(2030, 1, 15, 0, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.calls = []
        self.requests = 1  # A prior manual source GET must not be reset.
        self.halted = None
        self.fail = None
        self.done = threading.Event()

    def automatic_source_status(self):
        return {"day_jst": self.now.astimezone(M.JST).date().isoformat(),
                "requests_used": self.requests, "halted_reason": self.halted}

    def generate_auto(self, sport, stage):
        self.calls.append((sport, stage))
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error
        if stage == "P1": self.done.set()
        return {"summary": {"generated": 2 if stage == "P0" else 5,
                            "reused": 0, "missing": 10}}


class AutomaticForecastTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M, "bounded automatic forecast controller is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service(Path(self.temp.name))
        self.controller = M.ForecastAutomation(self.service)
        self.addCleanup(self.controller.stop)

    def test_first_round_p0_p1_then_only_p1_at_existing_180second_cadence(self):
        out = self.controller.tick()
        self.assertEqual(self.service.calls, [("boat", "P0"), ("boat", "P1")])
        self.assertTrue(out["p0_completed"])
        self.assertEqual(out["round_no"], 1)
        self.assertEqual(out["requests_used"], 1)
        self.service.now += timedelta(seconds=179)
        self.controller.tick()
        self.assertEqual(len(self.service.calls), 2)
        self.service.now += timedelta(seconds=1)
        out = self.controller.tick()
        self.assertEqual(self.service.calls[-1], ("boat", "P1"))
        self.assertEqual(len(self.service.calls), 3)
        self.assertEqual(out["round_no"], 2)

    def test_restart_keeps_original_stop_time_round_and_p0_ack(self):
        first = self.controller.tick()
        self.controller.stop()
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        self.service.now += timedelta(seconds=60)
        same = restarted.tick()
        self.assertEqual(same["stop_at"], first["stop_at"])
        self.assertEqual(same["started_at"], first["started_at"])
        self.assertEqual(same["round_no"], 1)
        self.assertEqual(len(self.service.calls), 2)
        self.service.now += timedelta(seconds=120)
        self.assertEqual(restarted.tick()["round_no"], 2)
        self.assertEqual(self.service.calls.count(("boat", "P0")), 1)

    def test_source_count_beyond_old_limit_continues_and_survives_restart(self):
        self.service.requests = 241
        first = self.controller.tick()
        self.assertEqual(first["state"], "WAITING")
        self.assertEqual(first["requests_used"], 241)
        self.assertIsNone(first["source_limit"])
        self.assertEqual(self.service.calls, [("boat", "P0"), ("boat", "P1")])
        self.controller.stop()
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        self.service.requests = 365
        self.service.now += timedelta(seconds=180)
        later = restarted.tick()
        self.assertEqual(later["state"], "WAITING")
        self.assertEqual(later["requests_used"], 365)
        self.assertEqual(later["stop_at"], first["stop_at"])
        self.assertEqual(later["round_no"], 2)
        self.assertEqual(self.service.calls.count(("boat", "P0")), 1)
        self.service.requests = 364
        self.service.now += timedelta(seconds=180)
        self.assertEqual(restarted.tick()["halted_reason"], "AUTOMATIC_SOURCE_STATUS_REJECTED")

    def test_legacy_count_only_halt_is_preserved_without_resuming_or_reset(self):
        self.controller.tick()
        self.controller._halt("SOURCE_BUDGET_EXHAUSTED", self.service.now)
        self.controller.stop()
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        self.service.requests = 241
        result = restarted.tick()
        self.assertEqual(result["state"], "STOPPED")
        self.assertEqual(result["halted_reason"], "SOURCE_BUDGET_EXHAUSTED")
        self.assertEqual(result["requests_used"], 1)
        self.assertEqual(len(self.service.calls), 2)

    def test_http_latch_cannot_be_cleared_by_restart(self):
        self.service.halted = "SOURCE_HTTP_4XX_STOP"
        out = self.controller.tick()
        self.assertEqual(out["halted_reason"], "SOURCE_HTTP_4XX_STOP")
        self.controller.stop()
        self.service.halted = None
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        self.assertEqual(restarted.tick()["state"], "STOPPED")
        self.assertEqual(self.service.calls, [])

    def test_65minute_stop_is_persistent_not_a_new_session_on_restart(self):
        initial = self.controller.tick()
        self.service.now += timedelta(minutes=65)
        self.assertEqual(self.controller.tick()["halted_reason"], "BOUNDED_SESSION_END")
        self.controller.stop()
        fresh = M.ForecastAutomation(self.service)
        self.addCleanup(fresh.stop)
        out = fresh.tick()
        self.assertEqual(out["stop_at"], initial["stop_at"])
        self.assertEqual(out["state"], "STOPPED")
        self.assertEqual(len(self.service.calls), 2)

    def test_day_change_does_not_start_tomorrow_implicitly(self):
        self.controller.tick()
        self.service.now += timedelta(days=1)
        out = self.controller.tick()
        self.assertEqual(out["halted_reason"], "DAY_CHANGED")
        self.assertEqual(len(self.service.calls), 2)

    def test_transient_failure_waits_until_next_round_without_immediate_retry(self):
        self.service.fail = TimeoutError("fictional private source")
        first = self.controller.tick()
        self.assertFalse(first["p0_completed"])
        self.assertEqual(first["state"], "WAITING")
        self.assertEqual(len(self.service.calls), 1)
        self.controller.tick()
        self.assertEqual(len(self.service.calls), 1)
        self.service.now += timedelta(seconds=180)
        self.controller.tick()
        self.assertEqual(self.service.calls, [("boat", "P0"), ("boat", "P0"), ("boat", "P1")])

    def test_unknown_error_is_fixed_and_contains_no_original_exception(self):
        self.service.fail = ValueError("SECRET /private/source/forecast.json")
        out = self.controller.tick()
        self.assertEqual(out["state"], "STOPPED")
        self.assertNotIn("SECRET", json.dumps(out))
        self.assertNotIn("/private/source", json.dumps(out))

    def test_source_halt_after_p0_prevents_p1(self):
        original = self.service.generate_auto
        def halted(sport, stage):
            value = original(sport, stage)
            self.service.halted = "SOURCE_HTTP_4XX_STOP"
            return value
        self.service.generate_auto = halted
        out = self.controller.tick()
        self.assertEqual(self.service.calls, [("boat", "P0")])
        self.assertTrue(out["p0_completed"])
        self.assertEqual(out["halted_reason"], "SOURCE_HTTP_4XX_STOP")

    def test_another_instance_cannot_become_second_automatic_writer(self):
        self.controller.tick()
        other = M.ForecastAutomation(self.service)
        self.addCleanup(other.stop)
        out = other.tick()
        self.assertEqual(out["state"], "ALREADY_RUNNING")
        self.assertEqual(len(self.service.calls), 2)

    def test_start_runs_without_click_and_stop_wakes_existing_wait(self):
        self.assertTrue(self.controller.start())
        self.assertTrue(self.service.done.wait(2), "app startup did not generate automatically")
        self.assertTrue(self.controller.start())
        self.controller.stop()
        self.assertEqual(self.service.calls, [("boat", "P0"), ("boat", "P1")])
        self.assertEqual(self.controller.status()["state"], "PAUSED")

    def test_status_is_cached_and_never_calls_the_service(self):
        self.controller.tick()
        def forbidden(): raise AssertionError("status polled the provider")
        self.service.automatic_source_status = forbidden
        self.assertEqual(self.controller.status()["round_no"], 1)

    def test_reversed_clock_halts_before_generating(self):
        self.controller.tick()
        self.service.now -= timedelta(seconds=1)
        self.assertEqual(self.controller.tick()["halted_reason"], "CLOCK_REVERSED")
        self.assertEqual(len(self.service.calls), 2)

    def rewrite_session(self, **changes):
        self.controller.stop()
        target = next(self.service.root.glob("automatic-2030-01-15.json"))
        value = json.loads(target.read_text()); value.pop("local_session_sha256")
        value.update(changes)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        value["local_session_sha256"] = hashlib.sha256(raw).hexdigest()
        target.write_text(json.dumps(value)); target.chmod(0o600)

    def test_recovered_round23_runs_last_admitted_round24_then_stops(self):
        self.controller.tick()
        self.rewrite_session(round_no=23, next_run_at=self.service.now.isoformat())
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        out = restarted.tick()
        self.assertEqual(len(self.service.calls), 3)
        self.assertEqual(out["round_no"], 24)
        self.assertEqual(out["halted_reason"], "MAX_ROUNDS_REACHED")

    def test_recovered_unknown_inprogress_round_does_not_blindly_replay(self):
        self.controller.tick()
        self.rewrite_session(round_in_progress=True)
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        self.assertEqual(restarted.tick()["halted_reason"], "INTERRUPTED_ROUND_REQUIRES_REVIEW")
        self.assertEqual(len(self.service.calls), 2)

    def test_unknown_source_status_never_silently_becomes_zero_budget(self):
        self.service.automatic_source_status = lambda: {"day_jst":"2030-01-15", "requests_used":True, "halted_reason":None}
        out = self.controller.tick()
        self.assertEqual(out["halted_reason"], "AUTOMATIC_SOURCE_STATUS_REJECTED")
        self.assertEqual(self.service.calls, [])

    def test_clock_and_state_files_keep_private_modes_and_links_fail_closed(self):
        self.controller.tick()
        for p in self.service.root.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.controller.stop()
        lock = self.service.root / "automatic.lock"
        lock.unlink(); lock.symlink_to(self.service.root / "foreign")
        other = M.ForecastAutomation(self.service)
        self.addCleanup(other.stop)
        self.assertEqual(other.tick()["state"], "STOPPED")
        self.assertEqual(len(self.service.calls), 2)

    def test_replaced_lock_inode_stops_before_another_source_call(self):
        self.controller.tick()
        lock = self.service.root / "automatic.lock"
        lock.unlink(); lock.write_bytes(b""); lock.chmod(0o600)
        self.service.now += timedelta(seconds=180)
        self.assertEqual(self.controller.tick()["state"], "STOPPED")
        self.assertEqual(len(self.service.calls), 2)

    def test_failed_state_read_does_not_overwrite_corruption_from_cached_memory(self):
        self.controller.tick(); self.controller.stop()
        target = self.service.root / "automatic-2030-01-15.json"
        value = json.loads(target.read_text()); value["round_no"] = 0
        target.write_text(json.dumps(value))
        corrupt = target.read_bytes()
        self.controller.start(); self.controller._thread.join(timeout=1)
        self.assertEqual(self.controller.status()["state"], "STOPPED")
        self.assertEqual(target.read_bytes(), corrupt)
        self.assertEqual(len(self.service.calls), 2)

    def test_shutdown_waits_for_inflight_source_and_durable_paused_checkpoint(self):
        entered, release, finished, returned = (threading.Event() for _ in range(4))
        original = self.service.generate_auto
        def blocked(sport, stage):
            entered.set()
            if not release.wait(5): raise TimeoutError("fictional source timeout")
            answer = original(sport, stage)
            finished.set()
            return answer
        self.service.generate_auto = blocked
        self.controller.start()
        self.assertTrue(entered.wait(1))
        def shutdown():
            self.controller.stop()
            returned.set()
        shutdown_thread = threading.Thread(target=shutdown)
        shutdown_thread.start()
        try:
            self.assertFalse(returned.wait(1.1), "shutdown returned while source was still running")
            self.assertFalse(finished.is_set())
            release.set(); shutdown_thread.join(timeout=3)
            self.assertTrue(returned.is_set())
            self.assertTrue(finished.is_set())
            self.assertEqual(self.controller.status()["state"], "PAUSED")
            document = json.loads(next(self.service.root.glob("automatic-2030-01-15.json")).read_text())
            self.assertFalse(document["round_in_progress"])
            self.assertEqual(document["state"], "PAUSED")
            self.assertEqual(self.service.calls, [("boat", "P0")])
        finally:
            release.set(); shutdown_thread.join(timeout=3)

    def test_repeated_stop_does_not_overwrite_another_active_writers_state(self):
        self.controller.tick(); self.controller.stop()
        next_writer = M.ForecastAutomation(self.service)
        self.addCleanup(next_writer.stop)
        self.service.now += timedelta(seconds=180)
        next_writer.tick()
        target = next(self.service.root.glob("automatic-2030-01-15.json"))
        current = target.read_bytes()
        self.controller.stop()
        self.assertEqual(target.read_bytes(), current)

    def test_shutdown_policy_abort_is_a_clean_pause_not_generation_failure(self):
        entered, release = threading.Event(), threading.Event()
        def interrupted(sport, stage):
            entered.set(); release.wait(5)
            raise ValueError("AUTOMATIC_SESSION_END")
        self.service.generate_auto = interrupted
        self.controller.start(); self.assertTrue(entered.wait(1))
        errors = []
        def shutdown():
            try: self.controller.stop()
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=shutdown); worker.start()
        try:
            # The provider's trusted guard observes STOPPING and finishes its
            # policy abort instead of starting another source/native action.
            release.set(); worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(self.controller.status()["state"], "PAUSED")
            self.assertIsNone(self.controller.status()["halted_reason"])
        finally:
            release.set(); worker.join(timeout=3)

    def test_shutdown_timeout_raises_and_does_not_claim_a_clean_checkpoint(self):
        entered, release = threading.Event(), threading.Event()
        original = self.service.generate_auto
        def blocked(sport, stage):
            entered.set(); release.wait(5)
            return original(sport, stage)
        self.service.generate_auto = blocked
        self.controller.start(); self.assertTrue(entered.wait(1))
        try:
            with patch.object(M, "SHUTDOWN_GRACE_SECONDS", 0.02):
                with self.assertRaisesRegex(ValueError, "AUTOMATIC_SHUTDOWN_INCOMPLETE"):
                    self.controller.stop()
            self.assertEqual(self.controller.status()["state"], "STOPPING")
            self.assertTrue(self.controller._thread.is_alive())
        finally:
            release.set(); self.controller.stop()
