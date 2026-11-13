"""Real GitHub workflow_run completion should restart only authenticated BOAT owner.

Synthetic GitHub event/API fixtures, no provider GET, AES keys or dispatch.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import base64
import io
import json
import os
import tempfile
import unittest

from scripts import boat_recovery_dispatch_gate as launcher
from scripts import boat_main_dispatch_gate as base

NOW = datetime(2030, 4, 1, 2, 35, tzinfo=timezone.utc)
DAY = "2030-04-01"


def source_control():
    run = dict(id=9901, name=base.WORKFLOW, event="workflow_dispatch",
               head_branch=base.RELEASE_REF, head_sha=base.RELEASE_SHA,
               status="completed", conclusion="success",
               created_at="2030-04-01T01:50:00Z")
    control = dict(previous_run_id=9901,day_jst=DAY,
                   prepared_round=None,source_wait=None,
                   previous_halted_reason=None,previous_stop_reason="WORKER_HANDOFF",
                   previous_session_requests=310,completed_round=24,
                   lifetime_requests=310,day_start_lifetime_requests=0,
                   receipt=dict(id=7101,digest="sha256:"+"a"*64,
                                created_at="2030-04-01T02:20:00Z"),
                   source_control_receipt=dict(id=7102,digest="sha256:"+"b"*64,
                                               created_at="2030-04-01T02:20:01Z"))
    return run, control


def event(run):
    return dict(action="completed", workflow_run=dict(run,
        repository=dict(full_name=base.REPO),
        head_repository=dict(full_name=base.REPO)))


class OwnerCompletionTriggerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.run,self.control=source_control()
        self.history=dict(total_count=1,workflow_runs=[deepcopy(self.run)])
        self.eventpath=self.folder/"event.json"
        self.eventpath.write_text(json.dumps(event(self.run)))
        self.env=dict(GITHUB_ACTIONS="true",GITHUB_EVENT_NAME="workflow_run",
                      GITHUB_REPOSITORY=base.REPO,GITHUB_REF="refs/heads/main",
                      GITHUB_EVENT_PATH=str(self.eventpath))

    def trusted(self, doc=None, hist=None, env=None):
        if doc is not None:self.eventpath.write_text(json.dumps(doc))
        return launcher.trusted_owner_completion(
            self.history if hist is None else hist, NOW,
            env=self.env if env is None else env)

    def test_authentic_owner_completion_is_recognized(self):
        self.assertTrue(self.trusted())

    def test_untrusted_pr_foreign_head_and_denials_remain_closed(self):
        for field,invalid in (
            ("head_sha","0"*40),("head_branch","main"),
            ("event","pull_request"),("conclusion","cancelled"),
            ("status","in_progress"),("id",1)):
            bad=event(self.run)
            bad["workflow_run"][field]=invalid
            with self.subTest(field=field):
                self.assertFalse(self.trusted(bad))
        for bad in (dict(event(self.run),action="requested"),
                    dict(event(self.run),workflow_run=dict(event(self.run)["workflow_run"],
                          head_repository=dict(full_name="other/repo"))),
                    dict(event(self.run),workflow_run=dict(event(self.run)["workflow_run"],
                          repository=dict(full_name="other/repo")))):
            self.assertFalse(self.trusted(bad))
        self.assertFalse(self.trusted(event(self.run),env=dict(self.env,GITHUB_EVENT_NAME="pull_request")))
        self.assertFalse(self.trusted(event(self.run),env=dict(self.env,GITHUB_ACTIONS="false")))

    def test_live_api_run_must_match_event_exactly_and_be_latest_today(self):
        bad=deepcopy(self.history);bad["workflow_runs"][0]["head_sha"]="0"*40
        self.assertFalse(self.trusted(hist=bad))
        bad=deepcopy(self.history);bad["workflow_runs"][0]["conclusion"]="failure"
        self.assertFalse(self.trusted(hist=bad))
        bad=deepcopy(self.history);bad["workflow_runs"]=[]
        self.assertFalse(self.trusted(hist=bad))
        newer=dict(self.run,id=9902,created_at="2030-04-01T02:22:00Z")
        bad=dict(total_count=2,workflow_runs=[newer,self.run])
        self.assertFalse(self.trusted(hist=bad))

    def test_bad_event_bytes_symlink_and_prior_day_hold(self):
        self.eventpath.write_text("{not json")
        self.assertFalse(self.trusted())
        self.eventpath.write_text("x"*1048577)
        self.assertFalse(self.trusted())
        self.eventpath.unlink()
        self.eventpath.symlink_to(self.folder/"safe.json")
        self.assertFalse(self.trusted())
        self.eventpath.unlink()
        old=dict(self.run,created_at="2030-03-31T14:50:00Z")
        self.assertFalse(self.trusted(event(old)))

    def test_authenticated_workflow_completion_uses_pinned_reader_then_admits_successor(self):
        output=self.folder/"github-output"
        output.write_text("")
        release=self.folder/"release.json"
        release.write_text(json.dumps(dict(ref="refs/heads/"+base.RELEASE_REF,
                                           object=dict(sha=base.RELEASE_SHA))))
        policy=self.folder/"owner.json"
        policy.write_text(json.dumps(dict(encoding="base64",content=base64.b64encode(
            base.RELEASE_TOKEN.encode()).decode())))
        listing=self.folder/"history.json"
        listing.write_text(json.dumps(self.history))
        with patch.dict(os.environ,self.env,clear=True),patch.object(
             launcher,"read_pinned_control",return_value=self.control) as read,redirect_stdout(io.StringIO()) as out:
            code=launcher.main(["--release",str(release),"--owner-doc",str(policy),
                                "--history",str(listing),"--verify-source-handoff",
                                "--github-output",str(output)],now=NOW)
        self.assertEqual(code,0)
        read.assert_called_once()
        self.assertIn("ready=true",output.read_text())
        result=json.loads(out.getvalue())
        self.assertEqual(result["status"],"READY_VERIFIED_SAME_DAY_CONTINUATION")
        self.assertEqual(result["official_source_requests"],0)

    def test_failed_real_owner_event_requests_aes_repair_not_blind_relaunch(self):
        failed=dict(self.run,conclusion="failure")
        recorded=dict(total_count=1,workflow_runs=[failed])
        self.assertTrue(self.trusted(event(failed),hist=recorded))
        decision=launcher.decide(
            now=NOW,release=dict(ref="refs/heads/"+base.RELEASE_REF,
                                 object=dict(sha=base.RELEASE_SHA)),
            owner_doc=dict(encoding="base64",content=base64.b64encode(
                base.RELEASE_TOKEN.encode()).decode()),
            history=recorded,continuation_proof=None)
        self.assertFalse(decision["dispatch_allowed"])
        self.assertTrue(decision["recovery_required"])

    def test_duplicate_api_ids_and_untrusted_main_ref_hold(self):
        duplicate=dict(total_count=2,workflow_runs=[dict(self.run),dict(self.run)])
        self.assertFalse(self.trusted(hist=duplicate))
        self.assertFalse(self.trusted(env=dict(self.env,GITHUB_REF="refs/heads/other")))

    def test_trigger_does_not_admit_successor_without_physical_control(self):
        self.assertTrue(self.trusted())
        # This is the same gate used by the CLI after the trusted event.
        result=launcher.decide(now=NOW,release=dict(ref="refs/heads/"+base.RELEASE_REF,
                                object=dict(sha=base.RELEASE_SHA)),
                               owner_doc=dict(encoding="base64",content=base64.b64encode(
                                   base.RELEASE_TOKEN.encode()).decode()),
                               history=self.history,continuation_proof=None)
        self.assertFalse(result["dispatch_allowed"])

    def test_main_owner_job_listens_to_completed_authentic_producer_only(self):
        source=(Path(__file__).resolve().parents[1]/".github/workflows/boat-racer-daily.yml").read_text()
        job=source.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event_name == 'workflow_run'",job)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'",job)
        self.assertIn("github.event.workflow_run.head_sha == '"+base.RELEASE_SHA+"'",job)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository",job)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'",job)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",job)
        self.assertIn("--verify-source-handoff",job)
        self.assertIn("group: boat-main-launcher-source-free",job)


if __name__=="__main__":
    unittest.main()
