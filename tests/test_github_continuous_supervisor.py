"""One existing workflow, no official source calls or real GitHub writes."""
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
import json
import base64
import subprocess
import zipfile
import hashlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
try:
    from race_ai.github_continuous_supervisor import GitHubSupervisor, GitHubCLI, WorkflowAPIWait
except ImportError:
    GitHubSupervisor = None


class GitHub:
    def __init__(self):
        self.active = []
        self.latest = {"id": 11, "status": "completed", "conclusion": "success", "head_sha": "a"*40}
        self.control = {"run_id": 11, "day_jst": "2030-01-15", "requests_used": 400,
                        "completed_round": 25, "halted_reason": None, "source_wait": None}
        self.trigger = {"head": "a"*40, "content": "existing owner instruction\n"}
        self.commits = []
        self.fail_after_commit = False
    def active_runs(self): return list(self.active)
    def raw(self, endpoint): raise AssertionError("unexpected fictional API read: " + endpoint)
    def latest_run(self): return self.latest.copy()
    def final_control(self, run): return self.control.copy()
    def read_trigger(self): return self.trigger.copy()
    def append_trigger(self, previous, line):
        assert previous["head"] == self.trigger["head"]
        self.commits.append(line)
        self.trigger = {"head": "b"*40, "content": previous["content"]+line}
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise OSError("fictional response lost")
        return self.trigger["head"]


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(GitHubSupervisor, "continuous existing-workflow supervisor is missing")
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=datetime(2030,1,15,0,tzinfo=timezone.utc)
        self.api=GitHub()
        self.supervisor=GitHubSupervisor(Path(self.temp.name),client=self.api,clock=lambda:self.now)
        self.addCleanup(self.supervisor.stop)
    def test_active_or_pending_writer_never_gets_a_second_successor(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        self.assertEqual(self.supervisor.tick()["state"],"RUNNING")
        self.api.active=[dict(id=12,status="pending",head_sha="b"*40)]
        self.assertEqual(self.supervisor.tick()["state"],"WAITING")
        self.assertEqual(self.api.commits,[])
    def test_normal_completion_creates_one_durable_trigger_and_restart_does_not_duplicate(self):
        first=self.supervisor.tick()
        self.assertEqual(first["state"],"HANDOFF_WAIT")
        self.assertEqual(len(self.api.commits),1)
        self.supervisor.stop()
        reopened=GitHubSupervisor(Path(self.temp.name),client=self.api,clock=lambda:self.now)
        self.addCleanup(reopened.stop)
        self.assertEqual(reopened.tick()["state"],"HANDOFF_WAIT")
        self.assertEqual(len(self.api.commits),1)
    def test_committed_trigger_with_lost_response_is_not_committed_twice(self):
        self.api.fail_after_commit=True
        self.supervisor.tick()
        self.now+=timedelta(seconds=180)
        self.supervisor.tick()
        self.assertEqual(len(self.api.commits),1)
    def test_server_wait_survives_restart_and_day_change_without_a_trigger(self):
        retry=(self.now+timedelta(hours=24)).isoformat()
        self.api.control["source_wait"]={"state":"RATE_LIMIT_WAIT","reason":"HTTP_RATE_LIMIT",
                                         "retry_at":retry,"http_status":429,"attempts":1}
        self.assertEqual(self.supervisor.tick()["state"],"SOURCE_WAIT")
        self.now+=timedelta(hours=16)
        self.assertEqual(self.supervisor.tick()["state"],"SOURCE_WAIT")
        self.assertEqual(self.api.commits,[])
        self.now+=timedelta(hours=8)
        self.assertEqual(self.supervisor.tick()["state"],"HANDOFF_WAIT")
    def test_authorization_wait_and_manual_cancel_are_not_retried(self):
        self.api.control["source_wait"]={"state":"AUTHORIZATION_WAIT","reason":"SOURCE_AUTHORIZATION_REQUIRED",
                                         "retry_at":None,"http_status":403,"attempts":1}
        self.assertEqual(self.supervisor.tick()["state"],"SOURCE_WAIT")
        self.api.control["source_wait"]=None;self.api.latest["conclusion"]="cancelled"
        self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(self.api.commits,[])
    def test_more_than_one_writer_is_review_wait_and_continuous_caps_are_null(self):
        self.api.active=[dict(id=11,status="in_progress"),dict(id=12,status="in_progress")]
        out=self.supervisor.tick()
        self.assertEqual(out["state"],"REVIEW_WAIT")
        self.assertTrue(out["continuous"])
        self.assertIsNone(out["max_rounds"])
        self.assertIsNone(out["stop_at"])
        self.assertEqual(self.api.commits,[])

    def test_failed_or_unfinished_predecessor_does_not_trigger(self):
        for conclusion in ("failure","timed_out","action_required"):
            self.api.latest["conclusion"]=conclusion
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.api.latest["conclusion"]="success";self.api.control["prepared_round"]=2
        self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(self.api.commits,[])

    def test_missing_checkpoint_beside_lock_cannot_reset_trigger_intent(self):
        self.supervisor.tick();self.supervisor.stop()
        (Path(self.temp.name)/"supervisor.json").unlink()
        reopened=GitHubSupervisor(Path(self.temp.name),client=self.api,clock=lambda:self.now)
        self.addCleanup(reopened.stop)
        self.assertEqual(reopened.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(len(self.api.commits),1)

    def test_observed_successor_cannot_be_forgotten_by_a_stale_run_listing(self):
        self.supervisor.tick()
        self.api.active=[dict(id=12,status="pending",head_sha="b"*40)]
        self.supervisor.tick();self.api.active=[]
        self.assertEqual(self.supervisor.tick()["state"],"WAITING")
        self.assertEqual(len(self.api.commits),1)
        self.api.latest.update(id=12,head_sha="c"*40)
        self.api.control.update(run_id=12)
        self.supervisor.tick()
        self.assertEqual(len(self.api.commits),2)

    def test_api_retry_is_honored_by_direct_ticks_and_bad_checkpoint_does_not_kill_control(self):
        with patch.object(self.api,"active_runs",side_effect=OSError("fictional transport")) as get:
            self.supervisor.tick();self.supervisor.tick()
            self.assertEqual(get.call_count,1)
        self.now+=timedelta(seconds=180)
        with patch.object(self.api,"final_control",side_effect=zipfile.BadZipFile("fictional corruption")):
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(self.api.commits,[])

    def test_cli_transport_timeout_becomes_fixed_retry_error(self):
        from race_ai.github_continuous_supervisor import GitHubCLI
        with patch("race_ai.github_continuous_supervisor.subprocess.run",side_effect=subprocess.TimeoutExpired("gh",50)):
            with self.assertRaises(OSError):GitHubCLI().raw("actions/runs/1")

    def test_lock_replaced_during_api_read_cannot_publish_any_checkpoint(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        self.supervisor.tick()
        root=Path(self.temp.name);before=(root/"supervisor.json").read_bytes()
        self.now+=timedelta(seconds=30)
        def changed():
            lock=root/"supervisor.lock";lock.unlink();lock.write_bytes(b"successor-owned lock")
            lock.chmod(0o600)
            return list(self.api.active)
        with patch.object(self.api,"active_runs",side_effect=changed):
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual((root/"supervisor.json").read_bytes(),before)
        self.assertEqual(list(root.glob("supervisor-tmp-*")),[])

    def test_checkpoint_changed_during_api_read_is_never_overwritten(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        self.supervisor.tick();root=Path(self.temp.name)
        changed=b"independently retained conflicting checkpoint"
        def corrupt():
            (root/"supervisor.json").write_bytes(changed)
            return list(self.api.active)
        with patch.object(self.api,"active_runs",side_effect=corrupt):
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual((root/"supervisor.json").read_bytes(),changed)
        self.assertEqual(list(root.glob("supervisor-tmp-*")),[])

    def test_api_error_after_lost_lock_is_review_wait_without_stale_write(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        self.supervisor.tick();root=Path(self.temp.name)
        before=(root/"supervisor.json").read_bytes()
        def failed():
            lock=root/"supervisor.lock";lock.unlink();lock.write_bytes(b"new lock");lock.chmod(0o600)
            raise OSError("fictional request failure")
        with patch.object(self.api,"active_runs",side_effect=failed):
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual((root/"supervisor.json").read_bytes(),before)

    def test_quota_403_waits_until_reset_without_changing_actual_http_status(self):
        response=subprocess.CompletedProcess([],1,
            b'HTTP/2.0 403 Forbidden\r\nX-RateLimit-Remaining: 0\r\nX-RateLimit-Reset: 4102444800\r\n\r\n{"message":"quota"}',b"private diagnostics")
        with patch("race_ai.github_continuous_supervisor.subprocess.run",return_value=response):
            with self.assertRaises(WorkflowAPIWait) as caught:GitHubCLI().raw("actions/runs/1")
        wait=caught.exception.wait
        self.assertEqual(wait["http_status"],403)
        self.assertEqual(wait["state"],"RATE_LIMIT_WAIT")
        self.assertGreaterEqual(datetime.fromisoformat(wait["retry_at"]),datetime(2100,1,1,tzinfo=timezone.utc))

    def test_lf_headers_do_not_consume_binary_body_containing_crlf_separator(self):
        body=b"PK\x03\x04preserved archive bytes\r\n\r\n\x00\xfftail"
        response=subprocess.CompletedProcess([],0,b"HTTP/2.0 200 OK\nContent-Type: application/zip\n\n"+body,b"")
        with patch("race_ai.github_continuous_supervisor.subprocess.run",return_value=response):
            self.assertEqual(GitHubCLI().raw("actions/artifacts/1/zip"),body)

    def test_projection_api_wait_is_persisted_and_honored_before_more_reads(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        retry=(self.now+timedelta(hours=24)).isoformat()
        wait=dict(state="RATE_LIMIT_WAIT",reason="HTTP_RATE_LIMIT",retry_at=retry,http_status=429,attempts=1)
        self.supervisor.projection_refresh=lambda *args: (_ for _ in ()).throw(WorkflowAPIWait(wait))
        self.assertEqual(self.supervisor.tick()["state"],"SOURCE_WAIT")
        self.now+=timedelta(minutes=5)
        with patch.object(self.api,"active_runs",side_effect=AssertionError("cooldown must prevent API reads")):
            self.assertEqual(self.supervisor.tick()["retry_at"],retry)

    def test_completed_source_wait_refreshes_saved_view_without_a_trigger(self):
        refreshed=[]
        def refresh(get,root,run):
            refreshed.append(run);return {"counts":{"forecasts":533}}
        self.supervisor.projection_refresh=refresh
        self.api.control["source_wait"]=dict(state="AUTHORIZATION_WAIT",reason="SOURCE_AUTHORIZATION_REQUIRED",
            retry_at=None,http_status=403,attempts=1)
        out=self.supervisor.tick()
        self.assertEqual(out["state"],"SOURCE_WAIT")
        self.assertEqual(refreshed,[11])
        self.assertEqual(out["projection_status"]["counts"]["forecasts"],533)
        self.assertEqual(self.api.commits,[])

    def test_verified_completed_counters_are_published_and_active_unknown_is_null(self):
        self.assertIsNone(self.supervisor.status()["requests_used"])
        self.api.control.update(previous_run_id=11,previous_session_requests=400,
            lifetime_requests=900,lifetime_completed_rounds=125,completed_round=25)
        result=self.supervisor.tick()
        self.assertEqual(result["requests_used"],400)
        self.assertEqual(result["round_no"],25)
        self.assertEqual(result["lifetime_requests"],900)
        self.assertEqual(result["lifetime_completed_rounds"],125)
        self.api.active=[dict(id=12,status="in_progress",head_sha="b"*40)]
        active=self.supervisor.tick()
        self.assertIsNone(active["requests_used"])
        self.assertIsNone(active["round_no"])
        self.assertEqual(active["counter_run_id"],12)

    def test_recovered_api_wait_does_not_leave_stale_wait_fields_or_projection_error(self):
        wait=dict(state="RATE_LIMIT_WAIT",reason="HTTP_RATE_LIMIT",
            retry_at=(self.now+timedelta(seconds=180)).isoformat(),http_status=429,attempts=1)
        with patch.object(self.api,"active_runs",side_effect=WorkflowAPIWait(wait)):
            self.supervisor.tick()
        self.now+=timedelta(seconds=180)
        self.api.active=[dict(id=12,status="in_progress",head_sha="b"*40)]
        self.supervisor.projection_refresh=lambda *args: {"counts":{"forecasts":1}}
        result=self.supervisor.tick()
        self.assertIsNone(result.get("retry_at"))
        self.assertIsNone(result.get("waiting_reason"))
        self.assertFalse(result.get("projection_waiting",False))

    def test_retry_intent_cannot_commit_after_lock_replacement_during_trigger_read(self):
        with patch.object(self.api,"append_trigger",side_effect=OSError("fictional precommit failure")):
            self.supervisor.tick()
        self.now+=timedelta(seconds=180)
        def replaced():
            lock=Path(self.temp.name)/"supervisor.lock"
            lock.unlink();lock.write_bytes(b"other writer");lock.chmod(0o600)
            return self.api.trigger.copy()
        with patch.object(self.api,"read_trigger",side_effect=replaced):
            self.assertEqual(self.supervisor.tick()["state"],"REVIEW_WAIT")
        self.assertEqual(self.api.commits,[],"lost ownership must prevent an external commit too")

    def test_projection_validation_wait_clears_after_verified_refresh(self):
        self.api.active=[dict(id=11,status="in_progress",head_sha="a"*40)]
        self.supervisor.projection_refresh=lambda *args: (_ for _ in ()).throw(ValueError("fictional rejected view"))
        self.assertTrue(self.supervisor.tick()["projection_waiting"])
        self.supervisor.projection_refresh=lambda *args: {"counts":{"forecasts":1}}
        self.assertFalse(self.supervisor.tick()["projection_waiting"])

    def test_cli_interim_headers_preserve_zip_bytes_and_nonquota_403_stays_authorization_wait(self):
        body=b"PK\x03\x04\x00binary\r\n\r\nretained"
        response=subprocess.CompletedProcess([],0,b"HTTP/1.1 100 Continue\r\n\r\nHTTP/2 200 OK\r\nContent-Type: application/zip\r\n\r\n"+body,b"")
        with patch("race_ai.github_continuous_supervisor.subprocess.run",return_value=response):
            self.assertEqual(GitHubCLI().raw("actions/artifacts/1/zip"),body)
        denied=subprocess.CompletedProcess([],1,b"HTTP/2 403 Forbidden\nX-RateLimit-Remaining: 17\nX-RateLimit-Reset: 4102444800\n\n{}",b"")
        with patch("race_ai.github_continuous_supervisor.subprocess.run",return_value=denied):
            with self.assertRaises(WorkflowAPIWait) as caught:GitHubCLI().raw("pulls/71")
        self.assertEqual(caught.exception.wait["http_status"],403)
        self.assertEqual(caught.exception.wait["state"],"AUTHORIZATION_WAIT")
        self.assertIsNone(caught.exception.wait["retry_at"])

    def test_trigger_gate_rejects_unapplied_physical_workflow_and_omitted_file_content(self):
        from race_ai.github_continuous_supervisor import BRANCH, TRIGGER
        workflow=(Path(__file__).resolve().parents[1]/".github/workflows/boat-nationwide-ab-one-shot.yml").read_bytes()
        policy=b"MAX_ROUNDS = None\nMAX_SECONDS = None\n"
        def document(body):return {"type":"file","encoding":"base64","content":base64.b64encode(body).decode()}
        responses={"pulls/71":{"state":"open","head":{"ref":BRANCH,"sha":"a"*40}},
            "git/commits/"+"a"*40:{"tree":{"sha":"b"*40}},
            "contents/race_ai/repeated_cycle.py?ref="+"a"*40:document(policy),
            "contents/.github/workflows/boat-nationwide-ab-one-shot.yml?ref="+"a"*40:document(workflow),
            "contents/"+TRIGGER+"?ref="+"a"*40:document(b"owner instructions\n")}
        client=GitHubCLI()
        with patch.object(client,"api",side_effect=lambda path,**kwargs:responses[path]):
            self.assertEqual(client.read_trigger()["content"],"owner instructions\n")
            responses["contents/.github/workflows/boat-nationwide-ab-one-shot.yml?ref="+"a"*40]=document(workflow.replace(b"timeout-minutes: 360",b"timeout-minutes: 75"))
            with self.assertRaisesRegex(ValueError,"WORKFLOW"):client.read_trigger()
            responses["contents/.github/workflows/boat-nationwide-ab-one-shot.yml?ref="+"a"*40]=document(workflow)
            responses["contents/"+TRIGGER+"?ref="+"a"*40]={"type":"file","encoding":"none","content":""}
            with self.assertRaises(ValueError):client.read_trigger()

    def test_trigger_compaction_retains_owner_lines_and_recent_machine_history(self):
        from race_ai.github_continuous_supervisor import TRIGGER
        def line(number):
            return ("2030-01-15T00:00:00+00:00 RACE_AI_CONTINUOUS_"+format(number,"032x")+
                ": owner-authorized continuous successor after authenticated run 11; "
                "same workflow/single writer, unlimited logical rounds/time, preferred T-15..T-10, "
                "preserve originals and upstream waits; no new service, model, bet or promotion.\n")
        owner="Owner instruction: keep all existing originals.\nRACE_AI_CONTINUOUS_user_supplied_line\n"
        original=owner+"".join(line(n) for n in range(2500))+"Owner closing instruction.\n"
        bodies=[]
        def api(path,*,method,data):
            if path=="git/blobs":bodies.append(base64.b64decode(data["content"]).decode())
            if path=="git/trees":self.assertEqual(data["tree"][0]["path"],TRIGGER)
            return {"sha":"c"*40}
        client=GitHubCLI()
        with patch.object(client,"api",side_effect=api):
            client.append_trigger({"head":"a"*40,"tree":"b"*40,"content":original},"\n"+line(3000))
        compact=bodies[0]
        self.assertLess(len(compact.encode()),512*1024)
        self.assertTrue(compact.startswith(owner))
        self.assertIn("Owner closing instruction.\n",compact)
        self.assertNotIn(line(0),compact)
        self.assertNotIn(line(2371),compact)
        self.assertIn(line(2372),compact)
        self.assertIn(line(2499),compact)
        self.assertTrue(compact.endswith(line(3000)))

    def _authorization_checkpoint(self):
        wait = dict(state="AUTHORIZATION_WAIT", reason="SOURCE_AUTHORIZATION_REQUIRED",
                    retry_at=None, http_status=401, attempts=1)
        with patch.object(self.api, "active_runs", side_effect=WorkflowAPIWait(wait)):
            self.assertEqual(self.supervisor.tick()["state"], "SOURCE_WAIT")
        path = Path(self.temp.name) / "supervisor.json"
        body = path.read_bytes()
        return path, body, hashlib.sha256(body).hexdigest(), wait

    def _authorization_verification(self):
        return dict(repo="haji84/RACE-AI", workflow_id=405276784, run_id=11,
                    active_run_ids=[], source_control_sha256="a" * 64,
                    verification="GH_AUTH_STATUS_AND_AUTHENTICATED_WORKFLOW_READS")

    def test_explicit_401_reconnection_preserves_originals_and_never_dispatches(self):
        path, before, digest, wait = self._authorization_checkpoint()
        self.supervisor._state.update(intent={"marker": "retained", "predecessor": 9},
            source_control={"source_wait": {"http_status": 403}, "lifetime_requests": 3120},
            active_run_id=11, last_adopted_run_id=11)
        self.supervisor._save()
        before = path.read_bytes(); digest = hashlib.sha256(before).hexdigest()
        state_before = deepcopy(self.supervisor._state)
        with patch.object(self.api, "verify_authorization", create=True,
                          return_value=self._authorization_verification()) as verify:
            result = self.supervisor.reconnect_authorization(digest)
        verify.assert_called_once_with()
        self.assertEqual(result["state"], "AUTHORIZATION_RECONNECTED")
        saved = json.loads(path.read_bytes())
        self.assertIsNone(saved["api_wait"])
        receipt = saved["authorization_recoveries"][-1]
        self.assertEqual(receipt["previous_checkpoint_sha256"], digest)
        self.assertEqual(receipt["previous_api_wait"], wait)
        self.assertEqual(receipt["verification"], self._authorization_verification())
        self.assertEqual(receipt["checked_at"], self.now.isoformat())
        for key, value in state_before.items():
            if key != "api_wait": self.assertEqual(saved[key], value)
        self.assertEqual(self.api.commits, [])
        self.supervisor.stop()
        reopened = GitHubSupervisor(Path(self.temp.name), client=self.api, clock=lambda: self.now)
        self.addCleanup(reopened.stop)
        self.assertTrue(reopened._acquire())
        self.assertIsNone(reopened._state["api_wait"])
        self.assertEqual(reopened._state["intent"], state_before["intent"])

    def test_reconnection_requires_exact_checkpoint_and_only_the_401_api_latch(self):
        path, before, digest, wait = self._authorization_checkpoint()
        with patch.object(self.api, "verify_authorization", create=True) as verify:
            for value in (None, True, "a" * 63, "b" * 64):
                with self.assertRaises(ValueError): self.supervisor.reconnect_authorization(value)
            verify.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        variants = [dict(wait, http_status=403), dict(wait, http_status=429),
                    dict(wait, state="RATE_LIMIT_WAIT"), dict(wait, retry_at=self.now.isoformat()),
                    dict(wait, reason="SOURCE_REVIEW_REQUIRED"), None]
        for variant in variants:
            self.supervisor._state["api_wait"] = variant; self.supervisor._save()
            current = path.read_bytes()
            with patch.object(self.api, "verify_authorization", create=True) as verify:
                with self.assertRaises(ValueError):
                    self.supervisor.reconnect_authorization(hashlib.sha256(current).hexdigest())
                verify.assert_not_called()
            self.assertEqual(path.read_bytes(), current)

    def test_reconnection_provider_failure_keeps_original_checkpoint_and_latch(self):
        path, before, digest, wait = self._authorization_checkpoint()
        for error in (ValueError("GITHUB_AUTHORIZATION_NOT_CONFIRMED"),
                      WorkflowAPIWait(dict(wait, http_status=403)), OSError("fictional outage")):
            with patch.object(self.api, "verify_authorization", create=True, side_effect=error):
                with self.assertRaises((ValueError, OSError)):
                    self.supervisor.reconnect_authorization(digest)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.supervisor._state["api_wait"], wait)
        self.assertEqual(self.api.commits, [])

    def test_reconnection_rejects_clock_reversal_without_provider_read(self):
        path, before, digest, _ = self._authorization_checkpoint()
        self.now -= timedelta(seconds=1)
        with patch.object(self.api, "verify_authorization", create=True) as verify:
            with self.assertRaisesRegex(ValueError, "CLOCK_REVERSED"):
                self.supervisor.reconnect_authorization(digest)
            verify.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_reconnection_rejects_clock_reversal_during_provider_read(self):
        path, before, digest, _ = self._authorization_checkpoint()
        def backwards():
            self.now -= timedelta(seconds=1)
            return self._authorization_verification()
        with patch.object(self.api, "verify_authorization", create=True, side_effect=backwards):
            with self.assertRaisesRegex(ValueError, "CLOCK_REVERSED"):
                self.supervisor.reconnect_authorization(digest)
        self.assertEqual(path.read_bytes(), before)

    def test_reconnection_save_failure_keeps_in_memory_denial_and_never_dispatches(self):
        path, before, digest, wait = self._authorization_checkpoint()
        with patch.object(self.api, "verify_authorization", create=True,
                          return_value=self._authorization_verification()):
            with patch.object(self.supervisor, "_save", side_effect=OSError("fictional disk failure")):
                with self.assertRaises(OSError): self.supervisor.reconnect_authorization(digest)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.supervisor._state["api_wait"], wait)
        self.assertNotIn("authorization_recoveries", self.supervisor._state)
        with patch.object(self.api, "active_runs", side_effect=AssertionError("denial retained")):
            self.assertEqual(self.supervisor.tick()["state"], "SOURCE_WAIT")
        self.assertEqual(self.api.commits, [])

    def test_reconnection_refuses_stale_provider_run_and_preserves_source_denial(self):
        path, _, _, _ = self._authorization_checkpoint()
        self.supervisor._state["last_adopted_run_id"] = 12; self.supervisor._save()
        before = path.read_bytes(); digest = hashlib.sha256(before).hexdigest()
        with patch.object(self.api, "verify_authorization", create=True,
                          return_value=self._authorization_verification()):
            with self.assertRaisesRegex(ValueError, "WORKFLOW_METADATA_PENDING"):
                self.supervisor.reconnect_authorization(digest)
        self.assertEqual(path.read_bytes(), before)
        self.supervisor._state["last_adopted_run_id"] = 11; self.supervisor._save()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.api.control["source_wait"] = dict(state="AUTHORIZATION_WAIT", reason="SOURCE_AUTHORIZATION_REQUIRED",
                                              retry_at=None, http_status=403, attempts=1)
        with patch.object(self.api, "verify_authorization", create=True,
                          return_value=self._authorization_verification()):
            self.supervisor.reconnect_authorization(digest)
        result = self.supervisor.tick()
        self.assertEqual(result["state"], "SOURCE_WAIT")
        self.assertEqual(result["waiting_state"], "AUTHORIZATION_WAIT")
        self.assertEqual(self.supervisor._state["source_control"]["source_wait"], self.api.control["source_wait"])
        self.assertEqual(self.api.commits, [])

    def test_reconnection_does_not_overwrite_changed_checkpoint_or_lock(self):
        for replace in ("checkpoint", "lock"):
            with self.subTest(replace=replace):
                if replace == "lock":
                    self.supervisor.stop()
                    self.supervisor = GitHubSupervisor(Path(self.temp.name), client=self.api, clock=lambda: self.now)
                    self.addCleanup(self.supervisor.stop)
                path, before, digest, _ = self._authorization_checkpoint()
                conflicting = b"retained independent checkpoint"
                def changed():
                    if replace == "checkpoint": path.write_bytes(conflicting)
                    else:
                        lock = path.with_name("supervisor.lock"); lock.unlink()
                        lock.write_bytes(b"new owner"); lock.chmod(0o600)
                    return self._authorization_verification()
                with patch.object(self.api, "verify_authorization", create=True, side_effect=changed):
                    with self.assertRaises(ValueError): self.supervisor.reconnect_authorization(digest)
                self.assertEqual(path.read_bytes(), conflicting if replace == "checkpoint" else before)
                self.assertEqual(self.api.commits, [])
                if replace == "checkpoint":
                    # Restore this fictional fixture only, before the independent lock case.
                    path.write_bytes(before)

    def test_401_wait_remains_latched_on_ordinary_ticks_without_reconnection(self):
        path, before, _, _ = self._authorization_checkpoint()
        self.now += timedelta(days=30)
        with patch.object(self.api, "verify_authorization", create=True) as verify:
            with patch.object(self.api, "active_runs", side_effect=AssertionError("no automatic retry")):
                result = self.supervisor.tick()
                self.assertEqual(result["state"], "SOURCE_WAIT")
                self.assertEqual(result["waiting_state"], "AUTHORIZATION_WAIT")
            verify.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_provider_verification_uses_official_auth_and_same_workflow_reads_only(self):
        from race_ai.github_continuous_supervisor import WORKFLOW, WORKFLOW_FILE
        client = GitHubCLI()
        workflow = dict(id=WORKFLOW, path=WORKFLOW_FILE, state="active")
        latest = dict(id=11, workflow_id=WORKFLOW, head_branch="feat/four-sport-forecast-audit-view-20261022",
                      head_sha="a" * 40, status="completed", conclusion="success",
                      repository=dict(id=1416489937, full_name="haji84/RACE-AI"),
                      head_repository=dict(id=1416489937, full_name="haji84/RACE-AI"))
        control = dict(run_id=11, source_wait=dict(http_status=403), lifetime_requests=3120)
        response = subprocess.CompletedProcess([], 0, b"private account metadata", b"private diagnostics")
        with patch("race_ai.github_continuous_supervisor.subprocess.run", return_value=response) as run:
            with patch.object(client, "api", return_value=workflow) as api:
                with patch.object(client, "active_runs", return_value=[]):
                    with patch.object(client, "latest_run", return_value=latest):
                        with patch.object(client, "final_control", return_value=control) as final:
                            result = client.verify_authorization()
        self.assertEqual(run.call_args.args[0], ["gh", "auth", "status", "--hostname", "github.com"])
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)
        self.assertNotIn("env", run.call_args.kwargs)
        api.assert_called_once_with(f"actions/workflows/{WORKFLOW}")
        final.assert_called_once_with(latest)
        self.assertEqual(result["run_id"], 11)
        self.assertEqual(result["workflow_id"], WORKFLOW)
        self.assertEqual(result["source_control_sha256"], hashlib.sha256(
            json.dumps(control, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest())
        self.assertNotIn("private", json.dumps(result))

    def test_provider_verification_failure_never_changes_credentials_or_exposes_output(self):
        client = GitHubCLI()
        failures = [subprocess.CompletedProcess([], 1, b"private output", b"private error"),
                    subprocess.TimeoutExpired("gh", 50), OSError("private credential path")]
        for failure in failures:
            with patch("race_ai.github_continuous_supervisor.subprocess.run",
                       **({"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure})) as run:
                with patch.object(client, "api") as api:
                    with self.assertRaisesRegex(ValueError, "GITHUB_AUTHORIZATION_NOT_CONFIRMED") as caught:
                        client.verify_authorization()
                    api.assert_not_called()
                self.assertNotIn("private", str(caught.exception))
                self.assertEqual(run.call_count, 1)

    def test_provider_verification_rejects_wrong_workflow_run_or_checkpoint(self):
        from race_ai.github_continuous_supervisor import WORKFLOW, WORKFLOW_FILE
        workflow = dict(id=WORKFLOW, path=WORKFLOW_FILE, state="active")
        latest = dict(id=11, workflow_id=WORKFLOW, head_branch="feat/four-sport-forecast-audit-view-20261022",
                      head_sha="a" * 40, status="completed", conclusion="success",
                      repository=dict(id=1416489937, full_name="haji84/RACE-AI"),
                      head_repository=dict(id=1416489937, full_name="haji84/RACE-AI"))
        cases = [(dict(workflow, id=1), latest, {"run_id": 11}, []),
                 (dict(workflow, path="other.yml"), latest, {"run_id": 11}, []),
                 (dict(workflow, state="disabled_manually"), latest, {"run_id": 11}, []),
                 (workflow, dict(latest, workflow_id=1), {"run_id": 11}, []),
                 (workflow, dict(latest, head_branch="main"), {"run_id": 11}, []),
                 (workflow, dict(latest, repository={"full_name": "another/repo"}), {"run_id": 11}, []),
                 (workflow, dict(latest, head_repository={"full_name": "another/repo"}), {"run_id": 11}, []),
                 (workflow, dict(latest, repository=dict(id=1, full_name="haji84/RACE-AI")), {"run_id": 11}, []),
                 (workflow, dict(latest, head_repository=None), {"run_id": 11}, []),
                 (workflow, dict(latest, conclusion="failure"), {"run_id": 11}, []),
                 (workflow, latest, {"run_id": 10}, []),
                 (workflow, latest, {"run_id": 11}, [dict(latest, head_branch="main")])]
        for wf, run, control, active in cases:
            client = GitHubCLI()
            with patch("race_ai.github_continuous_supervisor.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")):
                with patch.object(client, "api", return_value=wf):
                    with patch.object(client, "active_runs", return_value=active):
                        with patch.object(client, "latest_run", return_value=run):
                            with patch.object(client, "final_control", return_value=control):
                                with self.assertRaises(ValueError): client.verify_authorization()
