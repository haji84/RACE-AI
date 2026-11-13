"""Source-free acceptance for the canonical BOAT main launcher."""
import base64
from datetime import datetime, timezone
import unittest

from scripts.boat_main_dispatch_gate import (
    decide, RELEASE_REF, RELEASE_SHA, RELEASE_TOKEN, WORKFLOW,
    FIRST_FAILED_ID, FIRST_FAILED_SHA
)

NOW = datetime(2026, 11, 11, 0, 10, tzinfo=timezone.utc)


def release(sha=RELEASE_SHA):
    return {"ref": "refs/heads/" + RELEASE_REF, "object": {"sha": sha}}


def source_doc(text):
    return {"encoding": "base64", "content": base64.b64encode(
        text.encode("utf8")).decode("ascii")}


def history(*runs, total=None):
    return {"workflow_runs": list(runs), "total_count": len(runs) if total is None else total}


class BoatOwnerLauncherGateTests(unittest.TestCase):
    def decide(self, *, sha=RELEASE_SHA, src=RELEASE_TOKEN, runs=None):
        return decide(now=NOW, release=release(sha),
                      owner_doc=source_doc(src),
                      history=history(*(runs or [])))

    def test_no_source_owner_release_keeps_existing_fixed_boundary(self):
        for doc in (
            RELEASE_TOKEN + " ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY",
            "CODE_ONLY_NO_SOURCE",
        ):
            value=self.decide(src=doc)
            self.assertFalse(value["dispatch_allowed"])
            self.assertEqual(value["status"], "HOLD_SOURCE_OWNER_FIXED_BOUNDARY_NOT_RELEASED")
            self.assertFalse(value["future_real_forecast_proven"])
            self.assertFalse(value["official_results_reconciled"])

    def test_newer_formal_release_does_not_delete_historical_holds(self):
        result=self.decide(src="ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY\\n"
                               + RELEASE_TOKEN)
        self.assertTrue(result["dispatch_allowed"])
        self.assertEqual(result["status"], "READY_EXISTING_OWNER_WORKFLOW_ONLY")

    def test_release_sha_must_be_exact_not_mutable_branch_alias(self):
        value=self.decide(sha="0"*40)
        self.assertEqual(value["status"], "HOLD_RELEASE_SHA_MISMATCH")
        self.assertFalse(value["dispatch_allowed"])

    def test_positive_owner_release_and_new_day_allows_existing_workflow(self):
        value=self.decide()
        self.assertEqual(value["status"], "READY_EXISTING_OWNER_WORKFLOW_ONLY")
        self.assertTrue(value["dispatch_allowed"])
        self.assertEqual(value["official_source_requests"], 0)

    def test_duplicate_same_day_owner_run_never_issued_twice(self):
        existing={"name": WORKFLOW, "head_branch": RELEASE_REF,
                  "event":"workflow_dispatch",
                  "created_at": "2026-11-11T00:01:00Z", "status": "completed"}
        result=self.decide(runs=[existing])
        self.assertEqual(result["status"], "HOLD_ALREADY_DISPATCHED_FOR_JST_DAY")

    def test_yesterday_does_not_block_new_day(self):
        existing={"name": WORKFLOW,"head_branch":RELEASE_REF,
                  "created_at":"2026-11-10T05:00:00Z"}
        self.assertTrue(self.decide(runs=[existing])["dispatch_allowed"])

    def test_existing_boat_result_polling_times_are_unchanged(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/
                ".github/workflows/boat-racer-daily.yml").read_text()
        self.assertIn("cron: '2-59/5 0-14 * * *'", source)
        self.assertIn("cron: '2-59/5 22-23 * * *'", source)
        self.assertIn("cron: '20 21 * * *'", source)
        self.assertNotIn("cron: '2-59/5 0-14,22-23 * * *'", source)
        # 15 hours + 2 hours. Identical minute values in each hour:
        minute_set=set(range(2,60,5))
        self.assertEqual(len(minute_set),12)
        self.assertEqual(len(minute_set)*(15+2),204)
        launcher=source.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event.schedule == '2-59/5 22-23 * * *'", launcher)
        self.assertIn("github.event.schedule == '2-59/5 0-14 * * *'", launcher)
        self.assertIn("group: boat-main-launcher-source-free", launcher)
        self.assertIn("actions: write", launcher)
        self.assertNotIn("racer_intraday_refresh",launcher)

    def _safe_same_day_successor(self):
        run=dict(id=101,name=WORKFLOW,head_branch=RELEASE_REF,
                 head_sha=RELEASE_SHA,event='workflow_dispatch',
                 created_at='2026-11-11T00:01:00Z',
                 status='completed',conclusion='success')
        control=dict(previous_run_id=101,day_jst='2026-11-11',
                     prepared_round=None,source_wait=None,
                     previous_halted_reason=None,
                     previous_stop_reason='BOUNDED_SESSION_END',
                     previous_session_requests=30,completed_round=8,
                     lifetime_requests=130,day_start_lifetime_requests=100,
                     receipt=dict(id=701,digest='sha256:'+'a'*64,
                                  created_at='2026-11-11T00:04:00Z'),
                     source_control_receipt=dict(id=702,digest='sha256:'+'b'*64,
                                  created_at='2026-11-11T00:04:01Z'))
        return run,control

    def test_delayed_previous_evening_schedule_cannot_claim_new_jst_day(self):
        early=datetime.fromisoformat('2026-11-12T00:02:00+09:00')
        result=decide(now=early,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history())
        self.assertFalse(result['dispatch_allowed'])
        self.assertEqual(result['status'],'HOLD_OUTSIDE_OWNER_DAYTIME_WINDOW')
        first=datetime.fromisoformat('2026-11-12T06:20:00+09:00')
        result=decide(now=first,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history())
        self.assertTrue(result['dispatch_allowed'])

    def test_authenticated_same_day_handoff_admits_exactly_one_safe_successor(self):
        run,control=self._safe_same_day_successor()
        first=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                     history=history(run))
        self.assertEqual(first['status'],'HOLD_ALREADY_DISPATCHED_FOR_JST_DAY')
        self.assertFalse(first['dispatch_allowed'])
        approved=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                        history=history(run),continuation_proof=control)
        self.assertTrue(approved['dispatch_allowed'])
        self.assertEqual(approved['status'],'READY_VERIFIED_SAME_DAY_CONTINUATION')
        self.assertEqual(approved['official_source_requests'],0)
        self.assertFalse(approved['future_real_forecast_proven'])

    def test_handoff_requires_complete_round_and_authentic_counters(self):
        from copy import deepcopy
        run,control=self._safe_same_day_successor()
        def verdict(c,rows=None):
            return decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                          history=history(*(rows if rows is not None else [run])),
                          continuation_proof=c)
        for edit in (
            lambda c:c.update(prepared_round=9),
            lambda c:c.update(previous_stop_reason='SOURCE_HTTP_403_NO_RETRY'),
            lambda c:c.update(source_wait=dict(state='SOURCE_REVIEW_WAIT',reason='SOURCE_VERIFICATION_REQUIRED')),
            lambda c:c.update(previous_halted_reason='SOURCE_VERIFICATION_REQUIRED'),
            lambda c:c.pop('day_start_lifetime_requests'),
            lambda c:c.update(day_start_lifetime_requests=-1),
            lambda c:c.update(day_start_lifetime_requests=131,lifetime_requests=130),
            lambda c:c.update(previous_run_id=102),
            lambda c:c['receipt'].update(created_at='2026-11-11T00:11:00Z'),
            lambda c:c['receipt'].update(digest='sha256:'+'x'*64),
            lambda c:c['source_control_receipt'].update(id=-1),
        ):
            record=deepcopy(control);edit(record)
            with self.subTest(record=record):
                self.assertFalse(verdict(record)['dispatch_allowed'])
        changed=dict(run,head_sha='0'*40)
        self.assertFalse(verdict(control,[changed])['dispatch_allowed'])
        self.assertFalse(verdict(control,[run,run])['dispatch_allowed'])
        self.assertFalse(verdict(control,[dict(run,status='in_progress')])['dispatch_allowed'])

    def test_authenticated_400_get_successor_is_not_rejected_by_240_quota(self):
        run,control=self._safe_same_day_successor()
        control.update(previous_stop_reason='WORKER_HANDOFF',
                       lifetime_requests=500,day_start_lifetime_requests=100,
                       previous_session_requests=400)
        out=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                   history=history(run),continuation_proof=control)
        self.assertEqual(out['status'],'READY_VERIFIED_SAME_DAY_CONTINUATION')
        self.assertTrue(out['dispatch_allowed'])
        self.assertEqual(out['official_source_requests'],0)

    def test_overnight_active_owner_run_blocks_another_writer(self):
        previous={"name": WORKFLOW, "head_branch": RELEASE_REF,
                  "event":"workflow_dispatch",
                  "created_at": "2026-11-10T23:01:00Z",
                  "status": "in_progress"}
        # Previous in JST? 23:01 UTC is already next JST date.
        previous["created_at"] = "2026-11-10T14:55:00Z"
        value=self.decide(runs=[previous])
        self.assertEqual(value["status"], "HOLD_ACTIVE_OWNER_WORKFLOW")
        self.assertFalse(value["dispatch_allowed"])

    def test_ordered_hundred_old_runs_cover_current_day_despite_pagination(self):
        from datetime import timedelta
        from scripts.boat_main_dispatch_gate import decide
        last=datetime(2026,11,10,14,0,tzinfo=timezone.utc)
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":(last-timedelta(days=i)).isoformat(),
               "status":"completed"} for i in range(100)]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows,total=101))
        self.assertEqual(result["status"],"READY_EXISTING_OWNER_WORKFLOW_ONLY")
        self.assertTrue(result["dispatch_allowed"])

    def test_pagination_with_recent_unseen_run_stays_hold(self):
        from datetime import timedelta
        from scripts.boat_main_dispatch_gate import decide
        newest=NOW-timedelta(minutes=3)
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":(newest-timedelta(seconds=5*i)).isoformat(),
               "status":"completed"} for i in range(100)]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows,total=101))
        self.assertEqual(result["status"],"HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(result["dispatch_allowed"])

    def test_out_of_order_run_metadata_never_proves_history_complete(self):
        from scripts.boat_main_dispatch_gate import decide
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":at,"status":"completed"} for at in (
                 "2026-11-10T02:00:00Z","2026-11-10T03:00:00Z")]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows))
        self.assertEqual(result["status"],"HOLD_INCOMPLETE_RUN_HISTORY")

    def test_one_shot_owner_push_reuses_existing_main_workflow(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/boat-racer-daily.yml").read_text()
        self.assertIn("docs/evidence/owner-pdca-main-trigger.txt", workflow)
        launcher=workflow.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event_name == 'push'", launcher)
        self.assertIn("boat-owner-release: single-real-session-20261111", launcher)
        self.assertIn("github.ref == 'refs/heads/main'", launcher)
        self.assertIn("steps.owner_gate.outputs.ready == 'true'", launcher)
        self.assertIn("--ref production/boat-p0-p1-20261111", launcher)
        self.assertIn("production_scope=existing-owner-p0-p1", launcher)
        self.assertIn("group: boat-main-launcher-source-free", launcher)
        self.assertIn("cancel-in-progress: false", launcher)
        self.assertIn("actions: write", launcher)
        self.assertNotIn("racer_intraday_refresh", launcher)
        self.assertNotIn("scripts.boat_pdca_github", launcher)
        # Existing collector and main result scorer remain separate jobs.
        self.assertEqual(workflow.splitlines().count("  daily:"),1)
        self.assertEqual(workflow.splitlines().count("  source_mirror:"),1)

    def _previous_pre_source_run_and_proof(self):
        at="2026-11-11T09:13:07Z"
        row=dict(id=FIRST_FAILED_ID,name=WORKFLOW,
                 head_branch=RELEASE_REF,event="workflow_dispatch",
                 status="completed",conclusion="failure",created_at=at)
        skipped=(
            "Check all earlier same-day receipts before first P0",
            "Authenticate the requested grid before any bootstrap source GET",
            "Obtain first P0 from verified official B only if truly absent",
            "Save first P0 separately before reading results",
            "Execute new-day P0 families from the authenticated first receipt",
            "Freeze additional new-day P0 as owner ciphertext",
            "Wait without source requests for the authenticated exhibition window",
            "Initialize continuous source session and account for initial B GET",
            "Deadline-ordered five-model round 01",
        )
        steps=[{"name":f"Placeholder source-free prep {i}", "conclusion":"success"}
               for i in range(61)]
        steps.append({"name":"Test originals, pending results, tampering and unchanged models",
                      "conclusion":"failure"})
        steps.extend({"name":name,"conclusion":"skipped"} for name in skipped)
        proof=dict(run={**row,"head_sha":FIRST_FAILED_SHA},
            jobs={"total_count":1,"jobs":[{
                "name":"Existing frozen P0, exhibition P1, separate official results and PDCA",
                "conclusion":"failure","steps":steps}]},
            artifacts={"total_count":1,"artifacts":[{
                "name":"existing-cycle-source-42993305843"}]})
        return row,proof

    def test_old_11_12_p0_is_readable_only_by_exact_run_sha_and_artifact_digests(self):
        from copy import deepcopy
        from scripts.boat_main_dispatch_gate import recovery_selection
        r=dict(id=43131905826,head_sha='cf7b6f6a926396c6873e78fe1ad1d3d6840088a8',
               head_branch=RELEASE_REF,event='workflow_dispatch',workflow_id=405276784,
               status='completed',conclusion='failure',
               repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
               head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))
        rows=[
            ('boat-p0-existing',13905925953,
             '5a3287ac9cb45be6907be6c7d370c04addf3216d6e70184bda20e05502c80c6d','2026-11-12T01:07:04Z'),
            ('race-cycle-continuity',13905208588,
             'f11be8ff9b65d46c9f03a43ca496fa77c19bd26c01b081ae8253840e737e1644','2026-11-12T01:08:07Z'),
            ('race-source-control',13906460172,
             'b6b17372f57caa642aa9e249df42bfeddd512181371892a5eef988347d4a55f7','2026-11-12T01:08:09Z')]
        artifacts=[dict(name=f'{name}-{r["id"]}',id=ident,digest='sha256:'+digest,
                        expired=False,size_in_bytes=100000,created_at=at,
                        workflow_run=dict(id=r['id'],head_sha=r['head_sha'],
                                          repository_id=1416489937,
                                          head_repository_id=1416489937))
                   for name,ident,digest,at in rows]
        bundle=dict(total_count=3,artifacts=artifacts)
        selected=recovery_selection(run=r,artifacts=bundle)
        self.assertFalse(selected['source_dispatch_allowed'])
        self.assertEqual(selected['p0_artifact'],13905925953)
        self.assertEqual(selected['day_jst'],'2026-11-12')
        self.assertEqual(selected['companion_artifacts'],[13905208588,13906460172])
        for case in ('run_id','head_sha','artifact_sha','artifact_id','source_day',
                     'foreign_repository','not_complete','reused_source'):
            with self.subTest(case=case):
                changed_run=deepcopy(r);changed=deepcopy(bundle)
                if case=='run_id':
                    changed_run['id']=43131905827
                elif case=='head_sha':
                    changed_run['head_sha']=RELEASE_SHA
                    for a in changed['artifacts']:a['workflow_run']['head_sha']=RELEASE_SHA
                    # The same historical artifact identifiers must never
                    # become a newly generated current-release provenance.
                elif case=='artifact_sha':changed['artifacts'][0]['digest']='sha256:'+'f'*64
                elif case=='artifact_id':changed['artifacts'][0]['id']=13905925954
                elif case=='source_day':changed['artifacts'][0]['created_at']='2026-11-11T01:07:04Z'
                elif case=='foreign_repository':changed_run['repository']['id']=7
                elif case=='not_complete':changed_run['status']='in_progress'
                elif case=='reused_source':changed_run['event']='push'
                with self.assertRaises(ValueError):
                    recovery_selection(run=changed_run,artifacts=changed)

    def test_failed_producer_saved_p0_recovery_is_source_free_and_one_exact_run(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-racer-daily.yml').read_text()
        retention=workflow.split('  original_retention:',1)[1].split('  original_readback:',1)[0]
        owner=workflow.split('  owner_p0_p1_dispatch:',1)[1]
        token='boat-owner-readback: recover-saved-p0-43131905826'
        self.assertIn(token,retention)
        self.assertIn("'43131905826'",retention)
        self.assertIn('github.event_name == \'push\'',retention)
        self.assertIn('steps.select.outputs.p0',workflow)
        self.assertIn('--verify-retained-p1',workflow)
        self.assertNotIn(token,owner)
        self.assertNotIn('gh workflow run',retention)
        self.assertIn("github.event.head_commit.message, 'racer-intraday-refresh: stage-model-pdca'",workflow)
        self.assertIn('docs/evidence/owner-pdca-main-trigger.txt',workflow.split('jobs:',1)[0])
        self.assertEqual(workflow.splitlines().count('  original_retention:'),1)
        self.assertEqual(workflow.splitlines().count('  original_readback:'),1)
        self.assertEqual(workflow.splitlines().count('  original_reconcile:'),1)

    def test_verified_result_only_push_uses_pinned_collector_not_forecast_owner(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1] /
                  '.github/workflows/boat-racer-daily.yml').read_text()
        token='boat-result-refresh: owner-p0-43131905826-20261112'
        daily=workflow.split('\n  daily:\n    needs: [source_mirror, original_reconcile]',1)[1].split('\n  owner_p0_p1_dispatch:',1)[0]
        owner=workflow.split('  owner_p0_p1_dispatch:',1)[1]
        self.assertIn(token,daily)
        self.assertNotIn(token,owner)
        self.assertIn('!cancelled()',daily)
        self.assertIn("github.ref == 'refs/heads/main'",daily)
        self.assertIn("docs/evidence/owner-pdca-main-trigger.txt",workflow.split('jobs:',1)[0])
        self.assertEqual(workflow.count('name: Reflect confirmed races and retain encrypted incremental source packets'),1)
        self.assertIn("'6327bc5675aee2da94ac13397f1f86f39b27d8fd'",daily)
        self.assertIn('Authenticate the saved 11/12 P0 receipt before results or read-only view',daily)
        self.assertLess(daily.index('Use pinned collector for official results and stage-aware P0 reader'),
                        daily.index('path: pr64-reference'))
        self.assertLess(daily.index('path: pr64-reference'),
                        daily.index('Authenticate the saved 11/12 P0 receipt'))
        self.assertIn('zip_sha256=\'5a3287ac9cb45be6907be6c7d370c04addf3216d6e70184bda20e05502c80c6d\'',daily)
        self.assertIn('artifact_id=13905925953,race_count=142,model_forecast_count=284',daily)
        result_only=daily.split("if [[ \"$RESULT_ONLY\" == 'true' ]]; then",1)[1].split('else',1)[0]
        self.assertIn('python -m scripts.racer_intraday_refresh',result_only)
        self.assertIn('--verify-public --sync-results',result_only)
        # The website checker validates the existing P0 forecast and its
        # official results even though no genuine P1 has yet been generated.
        self.assertIn('VERIFY_SAVED_P0:',daily)
        self.assertIn("if [[ \"$VERIFY_SAVED_P0\" == 'true' ]]; then site_context_args+=(--stage P0); fi",daily)
        self.assertNotIn('--sync-beforeinfo',result_only)
        self.assertNotIn('gh workflow run',daily)
        self.assertNotIn('first_p0_bootstrap',daily)
        self.assertIn('  daily:\n    needs: [source_mirror, original_reconcile]',workflow)

    def test_result_refresh_restores_stage_aware_reader_only_after_provider_step(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1] /
                  '.github/workflows/boat-racer-daily.yml').read_text()
        daily=workflow.split('\n  daily:\n    needs: [source_mirror, original_reconcile]',1)[1].split('\n  owner_p0_p1_dispatch:',1)[0]
        result='      - name: Reflect confirmed races and retain encrypted incremental source packets'
        reader='      - name: Restore P0-aware read-only site verifier after result collection'
        browser='      - name: Verify private result display without publishing owner data'
        self.assertLess(daily.index(result),daily.index(reader))
        self.assertLess(daily.index(reader),daily.index(browser))
        self.assertEqual(daily.count(reader),1)
        reader_steps=daily.split(reader,1)[1].split('      - name: Install browser check only for an explicit verification run',1)[0]
        self.assertEqual(reader_steps.count('uses: actions/checkout@'),3)
        self.assertIn('ref: 0796b52c2804177976e4c2e5ab9b65f32589720b',reader_steps)
        self.assertIn('ref: 761247bee0209e37b1af6b8885e92cad3e9260a5',reader_steps)
        self.assertIn('ref: 7a432e5acc4d3495a0e82bd79726929e2f8085fe',reader_steps)
        self.assertIn('path: pr64-reference',reader_steps)
        self.assertIn('path: pr72-reference',reader_steps)
        self.assertEqual(reader_steps.count('boat-result-refresh: owner-p0-43131905826-20261112'),3)
        self.assertNotIn('gh workflow run',reader_steps)
        self.assertNotIn('racer_intraday_refresh',reader_steps)
        self.assertIn("'6327bc5675aee2da94ac13397f1f86f39b27d8fd'",daily)
        self.assertIn('VERIFY_SAVED_P0:',daily)
        self.assertNotIn(reader,daily.split(result,1)[0])

    def test_verified_p0_result_view_has_no_source_get_or_p1_requirement(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1] /
                  '.github/workflows/boat-racer-daily.yml').read_text()
        viewer='boat-result-view: saved-p0-43131905826-20261112'
        daily=workflow.split('\n  daily:\n    needs: [source_mirror, original_reconcile]',1)[1].split('\n  owner_p0_p1_dispatch:',1)[0]
        owner=workflow.split('\n  owner_p0_p1_dispatch:',1)[1]
        self.assertIn(viewer,daily)
        self.assertNotIn(viewer,owner)
        self.assertIn('site_context_args=(--day 2026-11-12 --stage P0)',daily)
        self.assertIn("context['stage']=='P0'",daily)
        self.assertIn("context['minimum_results']>=11",daily)
        self.assertIn('RESULT_VIEW_ONLY:',daily)
        self.assertIn("'0796b52c2804177976e4c2e5ab9b65f32589720b'",daily)
        self.assertIn("'6327bc5675aee2da94ac13397f1f86f39b27d8fd'",daily)
        self.assertIn("startsWith(github.event.head_commit.message, 'boat-result-view')",daily)
        self.assertIn('VERIFY_SAVED_P0:',daily)
        self.assertIn('--compact-results',daily)
        self.assertIn('--check-current-day',daily)
        source_step=daily.split('      - name: Reflect confirmed races and retain encrypted incremental source packets',1)[1].split('      - name: Install browser check',1)[0]
        self.assertNotIn(viewer,source_step)
        self.assertNotIn('gh workflow run',daily)
        self.assertNotIn('first_p0_bootstrap',daily)
        self.assertIn('P0_GIT_BLOB_MISMATCH',daily)
        self.assertIn('originals_changed=False',daily)

    def test_one_attested_pre_source_failure_can_retry_without_any_original(self):
        row,proof=self._previous_pre_source_run_and_proof()
        ci=dict(name=WORKFLOW,head_branch=RELEASE_REF,event="pull_request",
                created_at="2026-11-11T09:17:51Z",status="completed",
                conclusion="success")
        value=decide(now=datetime(2026,11,11,9,30,tzinfo=timezone.utc),
                     release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                     history=history(ci,row),retry_proof=proof)
        self.assertEqual(value["status"],"READY_RETRY_AFTER_VERIFIED_PRE_SOURCE_FAILURE")
        self.assertTrue(value["dispatch_allowed"])
        self.assertEqual(value["official_source_requests"],0)
        self.assertFalse(value["future_real_forecast_proven"])

    def test_preplace_failure_proof_cannot_be_faked_or_reused(self):
        from copy import deepcopy
        row,proof=self._previous_pre_source_run_and_proof()
        now=datetime(2026,11,11,9,30,tzinfo=timezone.utc)
        def verdict(evidence,records=None):
            return decide(now=now,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                          history=history(*(records or [row])),retry_proof=evidence)
        for corrupt in (
            lambda p:p["artifacts"]["artifacts"].append({"name":"boat-p0-existing-fake"}),
            lambda p:p["artifacts"].update(total_count=5),
            lambda p:p["run"].update(head_sha="0"*40),
            lambda p:p["run"].update(conclusion="success"),
            lambda p:p["jobs"]["jobs"][0]["steps"][-1].update(conclusion="success"),
            lambda p:p["jobs"].update(total_count=10),
        ):
            tmp=deepcopy(proof)
            corrupt(tmp)
            self.assertFalse(verdict(tmp)["dispatch_allowed"])
        second={**row,"id":42994444444,"created_at":"2026-11-11T09:25:00Z",
                "conclusion":"failure"}
        self.assertEqual(verdict(proof,[second,row])["status"],
                         "HOLD_ALREADY_DISPATCHED_FOR_JST_DAY")
        self.assertFalse(verdict(None)["dispatch_allowed"])

    def test_cli_main_respects_supplied_argv_not_process_argv(self):
        # The schedule invokes the CLI, while callers also use main(argv).
        # A bad global argv must not silently replace the explicit test args.
        import io
        import json
        import sys
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        from unittest.mock import patch
        from scripts.boat_main_dispatch_gate import main

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = {
                'release': release(),
                'owner': source_doc(RELEASE_TOKEN),
                'history': history(),
            }
            for name, value in inputs.items():
                (root / (name + '.json')).write_text(
                    json.dumps(value), encoding='utf8')
            args = [
                '--release', str(root / 'release.json'),
                '--owner-doc', str(root / 'owner.json'),
                '--history', str(root / 'history.json'),
            ]
            output = io.StringIO()
            with patch.object(sys, 'argv', ['gate', '--invalid-process-argument']), redirect_stdout(output):
                self.assertEqual(main(args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['release_sha'], RELEASE_SHA)
            self.assertEqual(result['official_source_requests'], 0)
            self.assertFalse(result['future_real_forecast_proven'])

    def test_unreturned_pagination_is_not_no_forecast(self):
        output=decide(now=NOW, release=release(),
            owner_doc=source_doc(RELEASE_TOKEN), history=history(total=101))
        self.assertEqual(output["status"], "HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(output["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
