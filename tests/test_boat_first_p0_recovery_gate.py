"""Admission of existing immutable artifacts, without source requests."""
import copy
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest
from scripts import boat_main_dispatch_gate as gate


def evidence():
    repo = {'id': 1416489937, 'full_name': 'haji84/RACE-AI'}
    run = {'id': 42995325741, 'workflow_id': 405276784,
           'head_branch': gate.RELEASE_REF, 'event': 'workflow_dispatch',
           'head_sha': 'e24f09f150e2318dd16a96bdc6db1d8c1317b9ae',
           'status': 'completed', 'conclusion': 'failure',
           'repository': repo, 'head_repository': dict(repo)}
    items = []
    for ident, prefix in ((13842474540, 'boat-p0-existing'),
                          (13842779131, 'race-cycle-continuity'),
                          (13842973909, 'race-source-control')):
        items.append({'id': ident, 'name': f'{prefix}-42995325741',
                      'created_at': '2026-11-11T09:29:52Z', 'expired': False,
                      'size_in_bytes': 100, 'digest': 'sha256:'+'a'*64,
                      'workflow_run': {'id': run['id'], 'head_sha': run['head_sha'],
                                       'repository_id': 1416489937,
                                       'head_repository_id': 1416489937}})
    return run, {'total_count': 3, 'artifacts': items}


class RecoveryAdmissionTests(unittest.TestCase):
    def test_recovery_failure_cannot_run_later_publication_but_normal_polling_can(self):
        # Evaluate the workflow's actual boolean guard with controlled GitHub
        # contexts; removing the dependency guard exposes the old-view publish.
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-racer-daily.yml').read_text()
        section=workflow.split('  daily:\n',1)[1].split('    runs-on:',1)[0]
        expression=' '.join(section.split('    if: >-\n',1)[1].split())
        expression=expression.replace('&&',' and ').replace('||',' or ')
        expression=re.sub(r'!(?!=)',' not ',expression).strip()
        for event, message, result, expected in (
            ('push','racer-intraday-refresh: stage-model-pdca | recover-first-p0-42995325741','failure',False),
            ('push','racer-intraday-refresh: stage-model-pdca | recover-first-p0-42995325741','skipped',False),
            ('push','racer-intraday-refresh: stage-model-pdca | recover-first-p0-42995325741','cancelled',False),
            ('push','racer-intraday-refresh: stage-model-pdca | recover-first-p0-42995325741','success',True),
            ('schedule','','skipped',True),
            ('push','racer-intraday-refresh: stage-model-pdca','skipped',True),
        ):
            context={'github':NS(event_name=event,repository='haji84/RACE-AI',ref='refs/heads/main',
                                 event=NS(head_commit=NS(message=message))),
                     'needs':NS(source_mirror=NS(result='skipped'),original_reconcile=NS(result=result)),
                     'cancelled':lambda:False,'contains':lambda a,b:b in a,
                     'startsWith':lambda a,b:a.startswith(b)}
            with self.subTest(event=event,result=result,message=message):
                self.assertEqual(eval(expression,{'__builtins__':{}},context),expected)

    def test_failed_run_original_is_recoverable_without_new_source_permission(self):
        run, artifacts = evidence()
        result = gate.recovery_selection(run=run, artifacts=artifacts)
        self.assertEqual(result['p0_artifact'], 13842474540)
        self.assertEqual(result['companion_artifacts'], [13842779131, 13842973909])
        self.assertEqual(result['day_jst'], '2026-11-11')
        self.assertFalse(result['source_dispatch_allowed'])

    def test_future_release_original_is_selected_by_exact_source_head(self):
        run, artifacts = evidence()
        run.update(id=987654321, head_sha=gate.RELEASE_SHA, conclusion='success')
        for row in artifacts['artifacts']:
            row['name'] = row['name'].replace('42995325741', '987654321')
            row['workflow_run'].update(id=run['id'], head_sha=gate.RELEASE_SHA)
        self.assertEqual(gate.recovery_selection(run=run, artifacts=artifacts)['source_run_id'], 987654321)

    def test_foreign_or_unapproved_execution_stays_rejected(self):
        for field, value in [('event', 'push'), ('event', 'pull_request'),
                             ('head_branch', 'main'), ('head_sha', 'b'*40),
                             ('workflow_id', 1), ('status', 'in_progress')]:
            run, artifacts = evidence()
            run[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                gate.recovery_selection(run=run, artifacts=artifacts)
        for field in ('repository', 'head_repository'):
            run, artifacts = evidence()
            run[field] = {'id': 1416489937, 'full_name': 'stranger/RACE-AI'}
            with self.assertRaises(ValueError):
                gate.recovery_selection(run=run, artifacts=artifacts)

    def test_missing_duplicate_partial_and_foreign_artifacts_stay_rejected(self):
        changes = [lambda a: a['artifacts'].pop(),
                   lambda a: a.update(total_count=4),
                   lambda a: a['artifacts'].__setitem__(1, copy.deepcopy(a['artifacts'][0])),
                   lambda a: a['artifacts'][0]['workflow_run'].update(id=1),
                   lambda a: a['artifacts'][0]['workflow_run'].update(head_sha='b'*40),
                   lambda a: a['artifacts'][0].update(expired=True),
                   lambda a: a['artifacts'][0].update(digest='sha256:broken')]
        for change in changes:
            run, artifacts = evidence()
            change(artifacts)
            with self.assertRaises(ValueError):
                gate.recovery_selection(run=run, artifacts=artifacts)


if __name__ == '__main__':
    unittest.main()
