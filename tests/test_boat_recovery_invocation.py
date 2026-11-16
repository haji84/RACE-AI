"""Only existing trusted main events may enter private failed-owner recovery."""
from contextlib import redirect_stdout
from copy import deepcopy
import io,json,os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import boat_recover_failed_owner as cli

SOURCE='b'*40
MAIN='c'*40
REPO=dict(id=1416489937,full_name='haji84/RACE-AI')
WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main'


def callback():
    return dict(repository=deepcopy(REPO),workflow_run=dict(id=99,workflow_id=405276784,
        name='BOAT nationwide cutoff-ordered A/B research (no Vercel)',
        head_repository=deepcopy(REPO),head_branch='production/boat-p0-p1-20261111',
        head_sha=SOURCE,event='workflow_dispatch',status='completed',conclusion='failure',run_attempt=1))


class TrustedRecoveryInvocationTests(unittest.TestCase):
    def check(self,event,document,**changes):
        args=dict(workflow_ref=WORKFLOW_REF,ref='refs/heads/main',sha=MAIN,expected_source_head=SOURCE)
        args.update(changes)
        return cli.trusted_main_invocation(event,document,**args)

    def test_genuine_completed_owner_callback_is_allowed_without_event_spoofing(self):
        self.assertTrue(self.check('workflow_run',callback()))

    def test_existing_schedule_and_explicit_release_push_remain_supported(self):
        self.assertTrue(self.check('schedule',dict(repository=REPO,schedule='2-59/5 0-14 * * *')))
        push=dict(repository=REPO,ref='refs/heads/main',after=MAIN,
                  head_commit=dict(id=MAIN,message='boat-owner-release: single-real-session-20261111 fixture'))
        self.assertTrue(self.check('push',push))
        push['head_commit']['message']='ordinary unrelated push'
        with self.assertRaises(ValueError):self.check('push',push)

    def test_pr_manual_wrong_workflow_or_branch_never_reaches_private_recovery(self):
        for event in ('pull_request','workflow_dispatch','repository_dispatch'):
            with self.subTest(event=event),self.assertRaises(ValueError):self.check(event,callback())
        for changed in (dict(workflow_ref=WORKFLOW_REF.replace('boat-racer-daily','other')),
                        dict(ref='refs/heads/unreviewed')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.check('workflow_run',callback(),**changed)

    def test_foreign_or_active_rerun_or_unreviewed_source_callback_rejected(self):
        for change in (dict(id=True),dict(workflow_id=1),dict(head_sha='f'*40),
                       dict(head_branch='unreviewed'),dict(event='pull_request'),
                       dict(status='in_progress'),dict(conclusion='cancelled'),dict(run_attempt=2),
                       dict(head_repository=dict(id=1,full_name=REPO['full_name']))):
            data=callback();data['workflow_run'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.check('workflow_run',data)

    def test_explicitly_reviewed_old_origin_is_not_an_arbitrary_ancestor(self):
        data=callback();data['workflow_run']['head_sha']='84128e0ec8bd9fe3da64ad49f74b8511b07e72be'
        self.assertTrue(self.check('workflow_run',data))
        data['repository']=dict(id=1,full_name=REPO['full_name'])
        with self.assertRaises(ValueError):self.check('workflow_run',data)

    def test_release_push_must_bind_the_actual_main_sha(self):
        data=dict(repository=REPO,ref='refs/heads/main',after='d'*40,
                  head_commit=dict(id=MAIN,message='boat-owner-release: single-real-session-20261111 fixture'))
        with self.assertRaises(ValueError):self.check('push',data)

    def test_actual_callback_cli_passes_context_guard_before_touching_private_vault(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);event=root/'event.json';event.write_text(json.dumps(callback()))
            env=dict(GITHUB_EVENT_NAME='workflow_run',GITHUB_EVENT_PATH=str(event),
                     GITHUB_WORKFLOW_REF=WORKFLOW_REF,GITHUB_REF='refs/heads/main',GITHUB_SHA=MAIN)
            with patch.dict(os.environ,env),patch.object(cli,'_packages'), \
                 patch('scripts.boat_private_original_vault._environment',
                       side_effect=ValueError('ROUND_RECOVERY_FIXTURE_REACHED_VAULT')) as vault, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--history',str(root/'history.json'),
                    '--expected-head',SOURCE,'--output',str(root/'proof.json')]),2)
            self.assertEqual(vault.call_count,1)
            self.assertFalse((root/'proof.json').exists())
