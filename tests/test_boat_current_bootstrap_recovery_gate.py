"""The saved r0 incident grants recovery inspection, never a source retry."""
import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import boat_main_dispatch_gate as base
from scripts import boat_recovery_dispatch_gate as gate
from scripts import boat_bootstrap_recovery_adapter as adapter
from scripts import boat_failed_recovery_contract as frozen

CURRENT = 'e' * 40  # Public fixture; replaced at runtime only by the exact release pin.
ORIGIN = 'fbc743be548bfd123e46cdbfe290515a59e5e0d3'
NOW = datetime(2026, 11, 18, 23, 10, tzinfo=timezone.utc)


def incident():
    repo = dict(id=1416489937, full_name=base.REPO)
    return dict(id=44409798061, head_sha=ORIGIN, head_branch=base.RELEASE_REF,
                name=base.WORKFLOW, event='workflow_dispatch', status='completed',
                conclusion='failure', created_at='2026-11-18T22:15:26Z', run_attempt=1,
                workflow_id=405276784, repository=repo, head_repository=deepcopy(repo))


def inputs(run=None):
    return dict(now=NOW,
                release=dict(ref='refs/heads/' + base.RELEASE_REF, object=dict(sha=CURRENT)),
                owner_doc=dict(encoding='base64', content=base64.b64encode(
                    base.RELEASE_TOKEN.encode()).decode()),
                history=dict(total_count=1, workflow_runs=[run or incident()]))


def saved_proof(successor=False):
    """Invented counters and inventory, delivered only through the internal step boundary."""
    run=incident()
    p0=dict(id=1, digest='sha256:'+'a'*64, created_at='2026-11-18T22:18:29Z')
    original=dict(previous_run_id=run['id'], day_jst='2026-11-19',
        previous_session_requests=1, lifetime_requests=15530, day_start_lifetime_requests=15529,
        completed_round=0, prepared_round=None, lifetime_completed_rounds=700,
        source_wait=None, previous_halted_reason=None, previous_stop_reason=None,
        receipt=dict(id=2,digest='sha256:'+'b'*64,created_at='2026-11-18T22:19:58Z'),
        source_control_receipt=dict(id=3,digest='sha256:'+'c'*64,created_at='2026-11-18T22:19:59Z'))
    fixed=deepcopy(original)
    fixed['recovery']=dict(schema=frozen.BOOTSTRAP_SCHEMA, previous_run_id=run['id'],
        round_no=None, verified_at=NOW.isoformat(), original_control_receipt=original['receipt'],
        source_attempts=1, no_p1_or_result_artifacts_verified=True,
        no_future_forecast_generated=True, originals_rewritten=False,
        checkpoint_AES_authenticated=True, public_control_matches_AES=True,
        first_receipt_union_verified=True, p0_receipt=p0,
        continuity_receipt=original['receipt'], source_control_receipt=original['source_control_receipt'])
    models=dict(head_sha=CURRENT, run_id=run['id'], source_head_sha=ORIGIN, day_jst='2026-11-19',
        new_forecasts=0,forecasts=5,baseline_forecasts=2,verified_at=NOW.isoformat(),
        forecast_inventory_sha256='a'*64,restored_inventory_sha256='a'*64,
        baseline_inventory_sha256='b'*64,restored_baseline_inventory_sha256='b'*64,
        issued_models_sha256='c'*64,included_issued_models_sha256='c'*64,
        vault_commit='d'*40, view_commit='e'*40,
        artifact_receipt=dict(id=14475644448,digest='sha256:'+'f'*64,
                              created_at='2026-11-18T22:19:54Z'))
    repair=dict(run_id=run['id'],original_head_sha=ORIGIN, original_control=original,
        control=fixed,vault_commit='f'*40, original_artifact_ids=[1,2,3],bootstrap_models=models)
    runs=[run];controls={run['id']:original}
    if successor:
        current=deepcopy(run);current.update(id=44420000000,head_sha=CURRENT,
            created_at='2026-11-18T22:30:00Z',conclusion='success')
        control=deepcopy(original);control.update(previous_run_id=current['id'],
            previous_session_requests=3,lifetime_requests=15533,completed_round=1,
            lifetime_completed_rounds=701,previous_stop_reason='WORKER_HANDOFF',
            receipt=dict(id=4,digest='sha256:'+'d'*64,created_at='2026-11-18T22:55:00Z'),
            source_control_receipt=dict(id=5,digest='sha256:'+'e'*64,created_at='2026-11-18T22:55:01Z'))
        runs=[current,run];controls[current['id']]=control
    proof=adapter.build_current_recovery_proof(runs,[repair],controls,now=NOW,expected_head=CURRENT)
    args=inputs();args['history']=dict(total_count=len(runs),workflow_runs=runs)
    latest=max(runs,key=lambda row:row['created_at'])
    args['continuation_proof']=controls[latest['id']]
    return args,proof


class CurrentBootstrapIncidentGateTests(unittest.TestCase):
    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_current_proof_preserves_original_identity_and_one_source_request(self):
        args,proof=saved_proof();before=deepcopy((args,proof))
        result=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(result['dispatch_allowed'])
        self.assertFalse(result['recovery_required'])
        self.assertEqual(result['status'],'READY_VERIFIED_RECOVERED_OWNER_CONTINUATION')
        self.assertEqual(proof['latest_control']['lifetime_requests'],15530)
        self.assertEqual(proof['latest_control']['day_start_lifetime_requests'],15529)
        self.assertEqual((args,proof),before)
        self.assertFalse(gate.decide(**args,recovery_proof=proof['historical_proof'])['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_later_success_still_authenticates_failed_history_and_its_counters(self):
        args,proof=saved_proof(successor=True)
        result=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(result['dispatch_allowed'])
        self.assertEqual(proof['history_sha256'],frozen.history_digest(args['history']['workflow_runs']))
        self.assertEqual(proof['latest_control']['lifetime_requests'],15533)
        self.assertEqual(args['history']['workflow_runs'][1]['conclusion'],'failure')
        changed=deepcopy(proof);changed['latest_control']['day_start_lifetime_requests']=15530
        self.assertFalse(gate.decide(**args,recovery_proof=changed)['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_counter_decrease_between_two_successors_never_authorizes_another(self):
        args,proof=saved_proof(successor=True)
        first=args['history']['workflow_runs'][0]
        latest=deepcopy(first);latest.update(id=44420000001,created_at='2026-11-18T23:00:00Z')
        control=deepcopy(args['continuation_proof'])
        control.update(previous_run_id=latest['id'],previous_session_requests=2,lifetime_requests=15532,
            receipt=dict(id=6,digest='sha256:'+'a'*64,created_at='2026-11-18T23:05:00Z'),
            source_control_receipt=dict(id=7,digest='sha256:'+'b'*64,created_at='2026-11-18T23:05:01Z'))
        runs=[latest,*args['history']['workflow_runs']]
        controls={incident()['id']:proof['repairs'][0]['original_control'],
                  first['id']:args['continuation_proof'],latest['id']:control}
        proof=adapter.build_current_recovery_proof(runs,proof['repairs'],controls,
            now=NOW,expected_head=CURRENT)
        args.update(history=dict(total_count=3,workflow_runs=runs),continuation_proof=control)
        self.assertFalse(gate.decide(**args,recovery_proof=proof)['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_incomplete_original_retention_projection_or_issued_inventory_stays_hold(self):
        args,proof=saved_proof()
        for field,value in [('vault_commit',None),('view_commit',None),
                            ('restored_inventory_sha256','0'*64),
                            ('included_issued_models_sha256','0'*64),
                            ('new_forecasts',1),('head_sha',ORIGIN)]:
            with self.subTest(field=field):
                changed=deepcopy(proof)
                changed['repairs'][0]['bootstrap_models'][field]=value
                # Keep both copies consistent: rejection must be the actual model guard.
                changed['historical_proof']['repairs']=deepcopy(changed['repairs'])
                self.assertFalse(gate.decide(**args,recovery_proof=changed)['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_stale_foreign_proof_unknown_history_and_fresh_control_changes_stay_hold(self):
        for successor in (False,True):
            args,proof=saved_proof(successor)
            for field,value in [('head_sha',ORIGIN),('verified_at','2026-11-18T22:55:00Z'),
                                ('history_sha256','0'*64)]:
                changed=deepcopy(proof);changed[field]=value
                self.assertFalse(gate.decide(**args,recovery_proof=changed)['dispatch_allowed'])
            altered=deepcopy(args);altered['continuation_proof']['lifetime_requests']+=1
            self.assertFalse(gate.decide(**altered,recovery_proof=proof)['dispatch_allowed'])
            altered=deepcopy(args)
            unknown=deepcopy(incident());unknown.update(id=44419999999,head_sha='d'*40,
                created_at='2026-11-18T22:25:00Z',conclusion='success')
            altered['history']['workflow_runs'].append(unknown);altered['history']['total_count']+=1
            changed=deepcopy(proof);changed['history_sha256']=frozen.history_digest(altered['history']['workflow_runs'])
            self.assertFalse(gate.decide(**altered,recovery_proof=changed)['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_exact_failed_bootstrap_requests_authenticated_recovery_only(self):
        args = inputs()
        before = deepcopy(args)
        result = gate.decide(**args)
        self.assertTrue(result['recovery_required'])
        self.assertFalse(result['dispatch_allowed'])
        self.assertEqual(result['official_source_requests'], 0)
        self.assertEqual(args, before)

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_other_run_head_attempt_day_workflow_or_repo_gains_no_admission(self):
        changes = [dict(id=44409798062), dict(head_sha='d' * 40), dict(run_attempt=2),
                   dict(workflow_id=405276785),
                   dict(repository=dict(id=1416489938, full_name=base.REPO)),
                   dict(head_repository=dict(id=1416489938, full_name=base.REPO)),
                   dict(conclusion='success')]
        for change in changes:
            with self.subTest(change=change):
                run = incident(); run.update(change)
                result = gate.decide(**inputs(run))
                self.assertFalse(result['recovery_required'])
                self.assertFalse(result['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_release_policy_active_writer_and_history_guards_remain_mandatory(self):
        for change in [dict(release=dict(ref='refs/heads/' + base.RELEASE_REF,
                                        object=dict(sha=ORIGIN))),
                       dict(owner_doc={}),
                       dict(history=dict(total_count=2, workflow_runs=[incident()])),
                       dict(now=NOW.replace(hour=19))]:
            with self.subTest(change=change):
                args=inputs(); args.update(change)
                try:
                    result=gate.decide(**args)
                except ValueError:
                    continue  # Existing invalid-clock guard rejects before recovery.
                self.assertFalse(result['recovery_required'])
                self.assertFalse(result['dispatch_allowed'])
        run=incident(); run['status']='in_progress'
        result=gate.decide(**inputs(run))
        self.assertFalse(result['recovery_required'])
        self.assertFalse(result['dispatch_allowed'])

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_exact_owner_completion_is_authenticated_against_live_history(self):
        run=incident(); history=inputs()['history']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'event.json'
            path.write_text(json.dumps(dict(action='completed', workflow_run=run)))
            env=dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_run',
                     GITHUB_REPOSITORY=base.REPO, GITHUB_REF='refs/heads/main',
                     GITHUB_EVENT_PATH=str(path))
            self.assertTrue(gate.trusted_owner_completion(history, NOW, env=env))
            for change in [dict(run_attempt=2), dict(id=44409798062),
                           dict(head_sha='d'*40), dict(status='in_progress')]:
                altered=deepcopy(run); altered.update(change)
                path.write_text(json.dumps(dict(action='completed', workflow_run=altered)))
                self.assertFalse(gate.trusted_owner_completion(history, NOW, env=env))

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_original_artifact_selection_is_read_only_and_exact(self):
        run=incident(); artifacts=[]
        for number, prefix in enumerate(('boat-p0-existing', 'race-cycle-continuity',
                                         'race-source-control'), start=1):
            artifacts.append(dict(id=number, name=f'{prefix}-{run["id"]}', expired=False,
                size_in_bytes=100, digest='sha256:'+str(number)*64,
                created_at='2026-11-18T22:19:59Z',
                workflow_run=dict(id=run['id'], head_sha=ORIGIN,
                    repository_id=1416489937, head_repository_id=1416489937)))
        inventory=dict(total_count=len(artifacts), artifacts=artifacts)
        try:
            selected=base.recovery_selection(run=run, artifacts=inventory)
        except ValueError:
            self.fail('The exact authenticated incident must remain readable after release advancement')
        self.assertFalse(selected['source_dispatch_allowed'])
        self.assertEqual(selected['source_sha'], ORIGIN)
        wrong=deepcopy(run); wrong['id']+=1
        with self.assertRaises(ValueError):
            base.recovery_selection(run=wrong, artifacts=inventory)

    @patch.object(base, 'RELEASE_SHA', CURRENT)
    def test_next_day_and_non_owner_events_keep_existing_new_day_behavior(self):
        args=inputs(); args['now']=NOW+timedelta(days=1)
        result=gate.decide(**args)
        self.assertFalse(result['recovery_required'])
        self.assertTrue(result['dispatch_allowed'])
        run=incident(); run['event']='pull_request'
        result=gate.decide(**inputs(run))
        self.assertFalse(result['recovery_required'])
        self.assertTrue(result['dispatch_allowed'])


if __name__ == '__main__':
    unittest.main()
