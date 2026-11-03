"""Authored rights/receipt/HTTP only; real fixed producers, SQLite and processes.

These local contracts do not authenticate storage, source rights or real time.
No external writer, provider feed, cloud account or live forecast is used.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import base64
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_fixed_model_case_profiles import v2_fixture, v2_gates, NEW_PIN
from tests.test_offline_model_run import Clock, MODELS
from tests.test_permissioned_case_submission import RecordingTransport, gates, BRANCH, PIN
from race_ai import permissioned_model_case as case
from race_ai import private_wire_retention as retention

ROOT = Path(__file__).resolve().parents[1]
RESERVED = '2030-01-15T09:16:00+09:00'
COMMITTED = '2030-01-15T09:17:00+09:00'
OBSERVED = '2030-01-15T09:18:00+09:00'
ADMITTED = '2030-01-15T09:19:00+09:00'
DISPATCH = '2030-01-15T09:20:00+09:00'


def forbidden(*args, **kwargs):
    raise AssertionError('fictional cache must not renew inference, authority or clock')


def request_options(seal, at):
    return dict(expected_request_sha256=seal['request_sha256'],
                expected_branch=BRANCH, submission_source_sha40=PIN, clock=Clock(at))


def settings(request):
    # Revision1 is in the authored original snapshot, not the request ledger.
    # The production validator must compare it to that unchanged snapshot.
    # Neither this fiction nor these callbacks authenticate a provider revision.
    slot = dict(schema='RACE_AI_PROSPECTIVE_COMPARISON_SLOT_V1',
        scope_ref='fictional-declared-comparison-scope', race_id=request['race_id'],
        race_revision=1, as_of_utc=datetime.fromisoformat(request['as_of']).astimezone(timezone.utc).isoformat(),
        model_ids=list(MODELS))
    destination = dict(destination_ref='fictional-private-destination',
        owner_scope_ref='fictional-owner-scope', adapter_contract_sha256='a'*64,
        max_wire_bytes=4*1024*1024)
    policy = dict(policy_ref='fictional-retention-policy', retain_until='2030-02-15T10:00:00+09:00',
        protection_policy_sha256='b'*64, immutability_policy_sha256='c'*64)
    return slot, destination, policy


def reserve(attempt, original, request, seal, **overrides):
    module = importlib.import_module('race_ai.retained_case_submission')
    slot, destination, policy = settings(request)
    options = dict(**request_options(seal, RESERVED), slot=slot,
        assignment_ref='fictional-single-path-assignment', destination=destination,
        retention_policy=policy, private_path_verifier=gates()['private_path_verifier'],
        admit_store=gates()['admit_store'])
    options.update(overrides)
    return module.reserve_retained_case(attempt, original, **options)


def handoff(original, seal, reservation, request):
    _, destination, policy = settings(request)
    return retention.prepare_retention_handoff(original,
        expected_case_request_sha256=seal['request_sha256'], destination=destination,
        retention_policy=policy, coordinator_binding=reservation['base_binding'],
        clock=Clock(RESERVED), private_path_verifier=gates()['private_path_verifier'],
        admit_source_storage=lambda r, snapshot: r['case_request_sha256']==seal['request_sha256'],
        admit_owner_destination=lambda r: r['destination']==destination and r['retention_policy']==policy,
        admit_coordinator=lambda r, b: b==reservation['base_binding'])


def evidence(handoff):
    request = handoff['request']
    descriptor = dict(schema='RACE_AI_PRIVATE_WIRE_READBACK_V1',
        request_sha256=handoff['request_sha256'], destination_ref=request['destination']['destination_ref'],
        object_ref='fictional-whole-object', object_version='immutable-version-001',
        wire_sha256=request['wire_sha256'], wire_byte_count=request['wire_byte_count'],
        observed_at=OBSERVED, reader_attestation_ref='fictional-protected-readback')
    receipt = dict(schema='RACE_AI_PRIVATE_WIRE_RETENTION_RECEIPT_V1',
        **{k:descriptor[k] for k in ('request_sha256','destination_ref','object_ref','object_version','wire_sha256','wire_byte_count')},
        committed_at=COMMITTED, retained_until=request['retention_policy']['retain_until'],
        protection_policy_sha256=request['retention_policy']['protection_policy_sha256'],
        immutability_policy_sha256=request['retention_policy']['immutability_policy_sha256'],
        issuer_ref='fictional-independent-issuer')
    return descriptor, receipt, b'FICTIONAL_OPAQUE_PROOF_NO_REAL_ISSUER'


def admit(attempt, original, seal, reservation, material, **overrides):
    module = importlib.import_module('race_ai.retained_case_submission')
    descriptor, receipt, proof = evidence(material)
    options = dict(expected_request_sha256=seal['request_sha256'],
        expected_reservation_sha256=reservation['reservation_sha256'],
        readback_bytes=material['wire'], readback_descriptor=descriptor,
        receipt_claims=receipt, receipt_proof=proof, clock=Clock(ADMITTED),
        private_path_verifier=gates()['private_path_verifier'], admit_store=gates()['admit_store'],
        admit_source_storage=lambda r,snapshot: r==material['request'],
        admit_owner_destination=lambda r: r==material['request'],
        admit_coordinator=lambda r,b: r==material['request'] and b==reservation['base_binding'],
        admit_protected_readback=lambda r,d: r==material['request'] and d==descriptor,
        verify_independent_receipt=lambda r,c,p: r==material['request'] and c==receipt and p==proof)
    options.update(overrides)
    return module.admit_case_retention(attempt, original, **options)


def dispatch(attempt, original, seal, reservation, transport, **overrides):
    module = importlib.import_module('race_ai.retained_case_submission')
    options = dict(**request_options(seal, DISPATCH), **gates(), transport=transport,
        expected_reservation_sha256=reservation['reservation_sha256'],
        admit_retention_action=lambda claim, prerequisite: True)  # Explicit fiction.
    options.update(overrides)
    return module.dispatch_retained_case(attempt, original, **options)


def rows(path, table):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT count(*) FROM '+table).fetchone()[0]


def child(mode, root):
    data=json.loads((root/'state.json').read_text(encoding='utf-8'))
    original, attempt=root/'case.sqlite', root/'attempt.sqlite'
    if mode=='reserve':
        result=reserve(attempt,original,data['request'],data['seal'])
        print(json.dumps({'reservation_sha256':result['reservation_sha256']}))
    elif mode=='crash-put':
        def crash(url,method,body):
            if method!='PUT':raise AssertionError('GET before first PUT')
            os._exit(23)  # Consumed intent is durable before transport entry.
        dispatch(attempt,original,data['seal'],data['reservation'],crash)
        raise AssertionError('crash transport did not run')
    else:
        raise AssertionError('unknown child mode')


class RetainedSubmissionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared_dir=tempfile.TemporaryDirectory(prefix='race33-four-sport-fictional-')
        cls.cases={}
        for sport,n in (('boat',6),('keirin',7),('autorace',3),('horse',3)):
            request,raw,policy=v2_fixture(sport,n)
            path=Path(cls.prepared_dir.name)/(sport+'.sqlite')
            seal=case.prepare_case(path,request,raw,policy,clock=Clock(),**v2_gates(request))
            cls.cases[sport]=(path,request,seal)

    @classmethod
    def tearDownClass(cls):
        cls.prepared_dir.cleanup()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.retained_case_submission'),
            'durable retention prerequisite is missing')
        self.tmp=tempfile.TemporaryDirectory(prefix='race33-local-integration-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.original,self.attempt=self.root/'case.sqlite',self.root/'attempt.sqlite'
        self.select('autorace')
        sentinel=patch('socket.create_connection',side_effect=AssertionError('network forbidden'))
        sentinel.start();self.addCleanup(sentinel.stop)

    def select(self,sport):
        path,self.request,self.seal=self.cases[sport]
        shutil.copyfile(path,self.original)

    def prepared(self):
        reservation=reserve(self.attempt,self.original,self.request,self.seal)
        material=handoff(self.original,self.seal,reservation,self.request)
        self.assertEqual(material['status'],'NOT_SENT_NO_WRITE_AUTHORITY')
        admitted=admit(self.attempt,self.original,self.seal,reservation,material)
        self.assertEqual(admitted['reservation_sha256'],reservation['reservation_sha256'])
        self.assertEqual(admitted['retention_request_sha256'],material['request_sha256'])
        return reservation,material,admitted

    def test_four_sport_original_whole_wire_precedes_any_public_intent_and_replays(self):
        for sport in self.cases:
            with self.subTest(sport=sport):
                self.select(sport);self.attempt=self.root/(sport+'-attempt.sqlite')
                before=self.original.read_bytes()
                reservation,material,admitted=self.prepared()
                self.assertEqual(rows(self.attempt,'submission_retention'),1)
                self.assertEqual(rows(self.attempt,'submission_intents'),0)
                loaded=case.load_case(self.original,expected_request_sha256=self.seal['request_sha256'],
                    private_path_verifier=gates()['private_path_verifier'])
                self.assertEqual(loaded['request']['schema'],'RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2')
                self.assertEqual(loaded['request']['model_source_sha40'],NEW_PIN)
                self.assertEqual(material['wire'],loaded['wire'])
                transport=RecordingTransport()
                result=dispatch(self.attempt,self.original,self.seal,reservation,transport)
                self.assertFalse(result['dispatch_barrier'])
                self.assertEqual(tuple(m['model_id'] for m in result['models']),MODELS)
                self.assertTrue(all(m['normal_acknowledged'] for m in result['models']))
                self.assertEqual([m for _,m,_ in transport.calls],['PUT','GET']*4)
                put_bytes=[base64.b64decode(json.loads(data)['content'],validate=True)
                           for _,method,data in transport.calls if method=='PUT']
                self.assertEqual(put_bytes,[case._canonical(p['anchor']).encode()+b'\n' for p in loaded['plans']])
                persisted=self.attempt.read_bytes()
                again=dispatch(self.attempt,self.original,self.seal,reservation,None,
                    clock=forbidden,admit_retention_action=forbidden,
                    **{k:forbidden for k in gates() if k not in ('private_path_verifier','admit_store')})
                self.assertEqual(again,{**result,'github_reads':0})
                self.assertEqual(self.attempt.read_bytes(),persisted)
                self.assertEqual(self.original.read_bytes(),before)
                for flag in ('official_prediction','eligible_for_hit_at_8','full_private_payload_retention_verified',
                             'global_exactly_once_verified','cloned_store_protection_verified'):
                    self.assertIs(result[flag],False)

    def test_missing_admission_and_partial_wire_cannot_consume_or_send(self):
        reservation=reserve(self.attempt,self.original,self.request,self.seal)
        transport=RecordingTransport()
        try:dispatch(self.attempt,self.original,self.seal,reservation,transport)
        except ValueError:pass
        self.assertEqual(rows(self.attempt,'submission_intents'),0)
        material=handoff(self.original,self.seal,reservation,self.request)
        try:admit(self.attempt,self.original,self.seal,reservation,material,readback_bytes=material['wire'][:-1])
        except ValueError:pass
        self.assertEqual(rows(self.attempt,'submission_retention'),0)
        self.assertEqual(rows(self.attempt,'submission_intents'),0)
        self.assertEqual(transport.calls,[])

    def test_actual_process_exit_at_first_put_keeps_permanent_unknown_commit_barrier(self):
        reservation,_,_=self.prepared()
        (self.root/'state.json').write_text(json.dumps(dict(request=self.request,seal=self.seal,reservation=reservation)),encoding='utf-8')
        run=subprocess.run([sys.executable,'-B','-X','utf8','-m','tests.test_retained_case_submission_integration','crash-put',str(self.root)],
            cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,23,run.stdout+run.stderr)
        self.assertEqual(rows(self.attempt,'submission_intents'),1)
        self.assertEqual(rows(self.attempt,'submission_evidence'),0)
        transport=RecordingTransport()
        result=dispatch(self.attempt,self.original,self.seal,reservation,transport)
        self.assertTrue(result['dispatch_barrier']);self.assertEqual(transport.calls,[])
        from race_ai.permissioned_case_submission import recover_submission_attempts
        restored=recover_submission_attempts(self.attempt,self.original,
            **request_options(self.seal,DISPATCH),private_path_verifier=gates()['private_path_verifier'],
            admit_store=gates()['admit_store'],submission_contract='RETAINED_V2',
            expected_reservation_sha256=reservation['reservation_sha256'])
        self.assertTrue(restored['dispatch_barrier'])
        self.assertEqual(restored['github_reads'],0)
        self.assertEqual(rows(self.attempt,'submission_intents'),1)
        self.assertEqual(rows(self.attempt,'submission_evidence'),0)

    def test_two_real_processes_share_identical_one_row_reservation(self):
        (self.root/'state.json').write_text(json.dumps(dict(request=self.request,seal=self.seal)),encoding='utf-8')
        commands=[subprocess.Popen([sys.executable,'-B','-X','utf8','-m','tests.test_retained_case_submission_integration','reserve',str(self.root)],
            cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        results=[]
        try:
            for process in commands:
                stdout,stderr=process.communicate(timeout=30)
                self.assertEqual(process.returncode,0,stdout+stderr)
                results.append(json.loads(stdout))
        finally:
            for process in commands:
                if process.poll() is None:process.kill();process.communicate()
        self.assertEqual(results[0],results[1])
        self.assertEqual(rows(self.attempt,'submission_reservation'),1)
        self.assertEqual(rows(self.attempt,'submission_intents'),0)

    def test_retained_known_commit_recovery_reads_three_without_ack_or_resend(self):
        reservation,_,_=self.prepared()
        transport=RecordingTransport(fail='GET')
        failed=dispatch(self.attempt,self.original,self.seal,reservation,transport)
        self.assertTrue(failed['dispatch_barrier'])
        commit=failed['models'][0]['commit_sha']
        self.assertIsNotNone(commit)
        plan=self.seal['plans'][0]
        base='https://api.github.com/repos/haji84/RACE-AI'
        run=dict(id=42,head_sha=commit,event='push',head_branch=BRANCH,
            repository=dict(full_name='haji84/RACE-AI'),created_at='2030-01-15T09:21:00+09:00')
        responses={base+'/actions/runs?head_sha='+commit+'&event=push&per_page=100':
            dict(total_count=1,workflow_runs=[run]),base+'/actions/runs/42':run,
            base+'/contents/'+plan['path']+'?ref='+commit:
            dict(type='file',encoding='base64',content=base64.b64encode(case._canonical(plan['anchor']).encode()+b'\n').decode())}
        reads=[]
        def fetch(url):
            reads.append(url)
            return deepcopy(responses[url])
        from race_ai.permissioned_case_submission import recover_submission_attempts
        from race_ai.github_freeze_receipt import verify_github_freeze
        result=recover_submission_attempts(self.attempt,self.original,
            **request_options(self.seal,'2030-01-15T11:05:00+09:00'),
            private_path_verifier=gates()['private_path_verifier'],admit_store=gates()['admit_store'],
            submission_contract='RETAINED_V2',expected_reservation_sha256=reservation['reservation_sha256'],
            admit_reader=lambda *a:True,github_fetch=fetch,trusted_legacy_verifier=verify_github_freeze)
        self.assertEqual(len(reads),3)
        self.assertEqual(result['github_reads'],3)
        self.assertTrue(result['dispatch_barrier'])
        self.assertFalse(result['models'][0]['normal_acknowledged'])
        self.assertTrue(result['models'][0]['witness']['external_pre_cutoff_presence_verified'])
        self.assertEqual([m['status'] for m in result['models']][1:],['NOT_ATTEMPTED']*3)
        self.assertEqual([method for _,method,_ in transport.calls],['PUT','GET'])
        before=self.attempt.read_bytes()
        cached=dispatch(self.attempt,self.original,self.seal,reservation,transport,
            clock=forbidden,admit_retention_action=forbidden)
        self.assertTrue(cached['dispatch_barrier'])
        self.assertEqual(before,self.attempt.read_bytes())
        self.assertEqual([method for _,method,_ in transport.calls],['PUT','GET'])


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1] in ('reserve','crash-put'):
        child(sys.argv[1],Path(sys.argv[2]))
    else:unittest.main()
