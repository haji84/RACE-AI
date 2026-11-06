"""Continuous app-owned rounds; services/sources below are entirely fictional."""
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
        self.wait = None
        self.deadline = None
        self.day_counts = {}
        self.done = threading.Event()

    def automatic_source_status(self, day_jst=None):
        current=self.now.astimezone(M.JST).date().isoformat()
        self.day_counts[current]=self.requests
        day=day_jst or current
        return {"day_jst": day,
                "requests_used": self.day_counts.get(day,0), "halted_reason": self.halted,
                "source_wait": self.wait, "next_deadline_at": self.deadline}

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

    def test_each_round_checks_missing_p0_and_p1_at_existing_180second_cadence(self):
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
        self.assertEqual(len(self.service.calls), 4)
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
        self.assertEqual(self.service.calls.count(("boat", "P0")), 2)

    @patch('race_ai.local_forecast_automation.SOURCE_LIMIT',None)
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
        self.assertEqual(self.service.calls.count(("boat", "P0")), 2)
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
        self.assertEqual(result["state"], "REVIEW_WAIT")
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
        self.assertEqual(restarted.tick()["state"], "REVIEW_WAIT")
        self.assertEqual(self.service.calls, [])

    def test_hard_review_wait_reschedules_without_busy_loop_or_source_work(self):
        self.service.halted="SOURCE_IDENTITY_OR_PARSE_STOP"
        self.controller.tick()
        self.service.now+=timedelta(days=1)
        out=self.controller.tick()
        self.assertEqual(out["state"],"REVIEW_WAIT")
        self.assertGreaterEqual(datetime.fromisoformat(out["next_run_at"]),self.service.now+timedelta(seconds=180))
        self.assertEqual(self.service.calls,[])

    def test_65minutes_and_24rounds_do_not_stop_or_reset_on_restart(self):
        self.assertTrue(self.controller.status()["continuous"])
        initial = self.controller.tick()
        for _ in range(26):
            self.service.now += timedelta(seconds=180)
            out=self.controller.tick()
        self.assertEqual(out["round_no"],27)
        self.assertTrue(out["continuous"])
        self.assertIsNone(out["halted_reason"])
        self.controller.stop()
        fresh = M.ForecastAutomation(self.service)
        self.addCleanup(fresh.stop)
        out = fresh.tick()
        self.assertEqual(out["stop_at"], initial["stop_at"])
        self.assertEqual(out["state"], "WAITING")
        self.assertEqual(out["round_no"],27)
        self.assertEqual(out["started_at"],initial["started_at"])
        self.assertIsNone(out["stop_at"])

    def test_day_change_archives_day_and_keeps_lifetime_counter(self):
        first=self.controller.tick()
        self.service.now += timedelta(days=1)
        self.service.requests=0
        out = self.controller.tick()
        self.assertIsNone(out["halted_reason"])
        self.assertEqual(out["day_jst"],"2030-01-16")
        self.assertEqual(out["round_no"],2)
        self.assertEqual(out["requests_total"],first["requests_used"])
        self.assertEqual(out["requests_used"],0)
        self.assertEqual(len(self.service.calls),4)
        archived=json.loads((self.service.root/"automatic-day-2030-01-15.json").read_text())
        self.assertEqual(archived["requests_used"],1)
        self.assertEqual(archived["round_no"],1)

    def test_transient_failure_waits_until_next_round_without_immediate_retry(self):
        self.service.fail = TimeoutError("fictional private source")
        first = self.controller.tick()
        self.assertFalse(first["p0_completed"])
        self.assertEqual(first["state"], "SOURCE_WAIT")
        self.assertEqual(first["waiting_state"],"TRANSIENT_SOURCE_WAIT")
        self.assertEqual(len(self.service.calls), 1)
        self.controller.tick()
        self.assertEqual(len(self.service.calls), 1)
        self.service.now += timedelta(seconds=180)
        self.controller.tick()
        self.assertEqual(self.service.calls, [("boat", "P0"), ("boat", "P0"), ("boat", "P1")])

    def test_source_retry_after_is_persistent_and_does_not_admit_round(self):
        from race_ai.source_retry_policy import plan_http_wait
        self.service.wait=plan_http_wait(429,{"Retry-After":"7200"},self.service.now)
        out=self.controller.tick()
        self.assertEqual(out["state"],"SOURCE_WAIT")
        self.assertEqual(out["round_no"],0)
        self.assertEqual(out["next_run_at"],self.service.wait["retry_at"])
        self.assertEqual(out["retry_at"],self.service.wait["retry_at"])
        self.assertEqual(out["waiting_state"],"RATE_LIMIT_WAIT")
        self.assertEqual(self.service.calls,[])
        self.controller.stop()
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        self.service.now+=timedelta(seconds=180)
        self.assertEqual(restarted.tick()["state"],"SOURCE_WAIT")
        self.assertEqual(self.service.calls,[])
        self.service.now+=timedelta(seconds=7020)
        self.service.wait=None
        self.assertEqual(restarted.tick()["round_no"],1)

    def test_authorization_wait_stays_alive_without_source_work(self):
        from race_ai.source_retry_policy import plan_http_wait
        self.service.wait=plan_http_wait(403,{},self.service.now)
        self.assertEqual(self.controller.tick()["state"],"SOURCE_WAIT")
        self.service.now+=timedelta(days=1)
        self.service.requests=0
        self.assertEqual(self.controller.tick()["state"],"SOURCE_WAIT")
        self.assertEqual(self.service.calls,[])

    def legacy_record(self, **changes):
        self.controller.tick();self.controller.stop()
        current=self.service.root/"automatic-continuous.json"
        value=json.loads(current.read_text());value.pop("local_session_sha256")
        start=datetime.fromisoformat(value["started_at"])
        midnight=start.astimezone(M.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        value.update(schema=M.LEGACY_SCHEMA,max_rounds=24,
                     stop_at=min(start+timedelta(minutes=65),midnight).isoformat(),**changes)
        value["local_session_sha256"]=hashlib.sha256(M._wire(value)).hexdigest()
        target=self.service.root/"automatic-2030-01-15.json"
        target.write_bytes(M._wire(value)+b"\n");target.chmod(0o600);current.unlink()
        (self.service.root/"automatic.lock").write_bytes(b"")  # The prior V1 writer had no marker.
        return target,target.read_bytes()

    def test_legacy_normal_limit_migration_preserves_bytes_and_continuity(self):
        target,original=self.legacy_record(round_no=24,state="STOPPED",halted_reason="MAX_ROUNDS_REACHED")
        self.service.now+=timedelta(minutes=70)
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["round_no"],25)
        self.assertEqual(out["requests_total"],1)
        self.assertIsNone(out["halted_reason"])
        self.assertEqual(target.read_bytes(),original)
        record=json.loads((self.service.root/"automatic-continuous.json").read_text())
        self.assertEqual(record["legacy_predecessors"][0]["sha256"],hashlib.sha256(original).hexdigest())

    def test_legacy_interrupted_record_is_preserved_and_requires_review(self):
        target,original=self.legacy_record(round_in_progress=True,state="RUNNING")
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["state"],"REVIEW_WAIT")
        self.assertEqual(out["halted_reason"],"INTERRUPTED_ROUND_REQUIRES_REVIEW")
        self.assertEqual(target.read_bytes(),original)
        self.assertEqual(len(self.service.calls),2)

    @patch('race_ai.local_forecast_automation.SOURCE_LIMIT',None)
    def test_legacy_numeric_cap_migration_retains_counter_and_original_record(self):
        target,original=self.legacy_record(state="STOPPED",halted_reason="SOURCE_BUDGET_EXHAUSTED",
                                           requests_used=240,requests_total=240)
        self.service.requests=241;self.service.now+=timedelta(seconds=180)
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["state"],"WAITING")
        self.assertEqual(out["requests_used"],241)
        self.assertEqual(out["requests_total"],241)
        self.assertEqual(target.read_bytes(),original)

    def test_legacy_clock_evidence_is_not_rebased_to_hide_reversal(self):
        self.legacy_record(last_observed_at=(self.service.now+timedelta(minutes=10)).isoformat())
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["halted_reason"],"CLOCK_REVERSED")
        self.assertEqual(len(self.service.calls),2)

    def test_missing_continuous_checkpoint_beside_day_archive_never_resets(self):
        self.controller.tick()
        self.service.now+=timedelta(days=1);self.service.requests=0
        self.controller.tick();self.controller.stop()
        (self.service.root/"automatic-continuous.json").unlink()
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["state"],"REVIEW_WAIT")
        self.assertFalse((self.service.root/"automatic-continuous.json").exists())
        self.assertEqual(len(self.service.calls),4)

    def test_missing_first_day_checkpoint_beside_existing_lock_never_resets(self):
        self.controller.tick();self.controller.stop()
        (self.service.root/"automatic-continuous.json").unlink()
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        out=restarted.tick()
        self.assertEqual(out["state"],"REVIEW_WAIT")
        self.assertFalse((self.service.root/"automatic-continuous.json").exists())
        self.assertEqual(len(self.service.calls),2)

    def test_missing_migrated_checkpoint_does_not_replay_retained_v1(self):
        self.legacy_record(round_no=24,state="STOPPED",halted_reason="MAX_ROUNDS_REACHED")
        self.service.now+=timedelta(seconds=180)
        migrated=M.ForecastAutomation(self.service);self.addCleanup(migrated.stop)
        self.assertEqual(migrated.tick()["round_no"],25);migrated.stop()
        (self.service.root/"automatic-continuous.json").unlink()
        restarted=M.ForecastAutomation(self.service);self.addCleanup(restarted.stop)
        self.assertEqual(restarted.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(len(self.service.calls),4)

    def test_deadline_hint_wakes_at_preferred_window_without_busy_loop(self):
        self.service.deadline=(self.service.now+timedelta(seconds=40)).isoformat()
        out=self.controller.tick()
        self.assertEqual(out["next_run_at"],self.service.deadline)
        self.service.now+=timedelta(seconds=40)
        self.controller.tick()
        self.assertEqual(self.controller.status()["round_no"],2)
        self.assertGreaterEqual(datetime.fromisoformat(self.controller.status()["next_run_at"])-self.service.now,timedelta(seconds=1))

    def test_midnight_inflight_aborts_old_day_then_continues_next_day(self):
        self.service.now=datetime(2030,1,15,14,59,59,tzinfo=timezone.utc)
        original=self.service.generate_auto
        def crossed(sport,stage):
            self.service.generate_auto=original
            self.service.day_counts["2030-01-15"]=2
            self.service.now+=timedelta(seconds=2);self.service.requests=0
            raise ValueError("SOURCE_DAY_BOUNDARY_PASSED")
        self.service.generate_auto=crossed
        out=self.controller.tick()
        self.assertIsNone(out["halted_reason"])
        self.assertEqual(out["day_jst"],"2030-01-16")
        self.assertEqual(out["requests_total"],2)
        self.assertEqual(self.service.calls,[])
        self.service.now=datetime.fromisoformat(out["next_run_at"])
        self.assertEqual(self.controller.tick()["state"],"WAITING")
        self.assertEqual(self.service.calls,[("boat","P0"),("boat","P1")])

    def test_unknown_error_is_fixed_and_contains_no_original_exception(self):
        self.service.fail = ValueError("SECRET /private/source/forecast.json")
        out = self.controller.tick()
        self.assertEqual(out["state"], "REVIEW_WAIT")
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
        target = self.service.root / "automatic-continuous.json"
        value = json.loads(target.read_text()); value.pop("local_session_sha256")
        value.update(changes)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        value["local_session_sha256"] = hashlib.sha256(raw).hexdigest()
        target.write_text(json.dumps(value)); target.chmod(0o600)

    def test_recovered_round23_runs_round24_and25(self):
        self.controller.tick()
        self.rewrite_session(round_no=23, next_run_at=self.service.now.isoformat())
        restarted = M.ForecastAutomation(self.service)
        self.addCleanup(restarted.stop)
        out = restarted.tick()
        self.assertEqual(len(self.service.calls), 4)
        self.assertEqual(out["round_no"], 24)
        self.assertIsNone(out["halted_reason"])
        self.service.now+=timedelta(seconds=180)
        self.assertEqual(restarted.tick()["round_no"],25)

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
        self.assertEqual(other.tick()["state"], "REVIEW_WAIT")
        self.assertEqual(len(self.service.calls), 2)

    def test_replaced_lock_inode_stops_before_another_source_call(self):
        self.controller.tick()
        lock = self.service.root / "automatic.lock"
        lock.unlink(); lock.write_bytes(b""); lock.chmod(0o600)
        self.service.now += timedelta(seconds=180)
        self.assertEqual(self.controller.tick()["state"], "REVIEW_WAIT")
        self.assertEqual(len(self.service.calls), 2)

    def test_failed_state_read_does_not_overwrite_corruption_from_cached_memory(self):
        self.controller.tick(); self.controller.stop()
        target = self.service.root / "automatic-continuous.json"
        value = json.loads(target.read_text()); value["round_no"] = 0
        target.write_text(json.dumps(value))
        corrupt = target.read_bytes()
        self.controller.start(); self.controller._thread.join(timeout=1)
        self.assertEqual(self.controller.status()["state"], "REVIEW_WAIT")
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
            document = json.loads((self.service.root / "automatic-continuous.json").read_text())
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
        target = self.service.root / "automatic-continuous.json"
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
