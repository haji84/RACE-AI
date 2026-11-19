"""Admission of existing immutable artifacts, without source requests."""
import copy
import base64
import hashlib
import json
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
    def continued_day(self):
        original, artifacts=evidence()
        original.update(id=99,head_sha=gate.RELEASE_SHA,created_at='2026-11-11T08:00:00Z')
        for item in artifacts['artifacts']:
            item['name']=item['name'].replace('42995325741','99')
            item['workflow_run'].update(id=99,head_sha=gate.RELEASE_SHA)
        current=dict(original,id=100,created_at='2026-11-11T10:00:00Z')
        remaining=copy.deepcopy(artifacts['artifacts'][1:])
        for item in remaining:
            item.update(id=item['id']+100, name=item['name'].replace('-99','-100'))
            item['workflow_run']['id']=100
        p0=artifacts['artifacts'][0]
        receipt=dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1',day_jst='2026-11-11',
            artifact_id=p0['id'],run_id=99,server_created_at=p0['created_at'],
            zip_sha256=p0['digest'][7:],json_sha256='b'*64,race_count=2,model_forecast_count=10,
            no_regeneration=True,retention_days=7,permanent_private_storage_proven=False)
        raw=(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
        path='docs/evidence/2026-11-11/p0-first-receipt.json'
        file=dict(type='file',path=path,size=len(raw),encoding='base64',
            sha=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest(),
            content=base64.b64encode(raw).decode())
        replies={f'contents/{path}?ref='+('d'*40):file,'actions/runs/99':original,
                 'actions/runs/99/artifacts?per_page=100':artifacts}
        return current,dict(total_count=2,artifacts=remaining),replies

    def test_continuation_uses_exact_canonical_first_receipt_and_original_companions(self):
        current,artifacts,replies=self.continued_day()
        before=copy.deepcopy((current,artifacts,replies))
        selected=gate.resolve_recovery_selection(run=current,artifacts=artifacts,
            get=lambda endpoint:replies[endpoint],receipt_commit='d'*40)
        self.assertEqual(selected['source_run_id'],99)
        self.assertEqual(selected['requested_run_id'],100)
        self.assertEqual(selected['p0_artifact'],13842474540)
        self.assertEqual(selected['companion_artifacts'],[13842779131,13842973909])
        self.assertFalse(selected['source_dispatch_allowed'])
        self.assertEqual((current,artifacts,replies),before)

    def test_continuation_rejects_wrong_receipt_blob_digest_day_and_original_origin(self):
        def change_digest(replies):
            replies['actions/runs/99/artifacts?per_page=100']['artifacts'][0]['digest']='sha256:'+'c'*64
        def change_origin(replies):
            replies['actions/runs/99']['head_sha']='c'*40
        def change_blob(replies):
            next(v for k,v in replies.items() if k.startswith('contents/'))['sha']='c'*40
        for mutate in (change_digest,change_origin,change_blob):
            current,artifacts,replies=self.continued_day();mutate(replies)
            with self.subTest(mutate=mutate.__name__),self.assertRaises(ValueError):
                gate.resolve_recovery_selection(run=current,artifacts=artifacts,
                    get=lambda endpoint:replies[endpoint],receipt_commit='d'*40)

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
                                 event=NS(head_commit=NS(message=message),
                                          schedule=('20 21 * * *' if event=='schedule' else None))),
                     'needs':NS(source_mirror=NS(result='skipped'),original_reconcile=NS(result=result)),
                     'cancelled':lambda:False,'contains':lambda a,b:b in a,
                     'startsWith':lambda a,b:a.startswith(b)}
            with self.subTest(event=event,result=result,message=message):
                self.assertEqual(eval(expression,{'__builtins__':{}},context),expected)
                if event == 'schedule':
                    # 05:30 JST is owner-only; it cannot also run the result collector.
                    context['github'].event.schedule = '30 20 * * *'
                    self.assertFalse(eval(expression,{'__builtins__':{}},context))

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
