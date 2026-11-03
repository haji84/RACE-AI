"""Authored inputs/authority/HTTP only; actual fixed producers and typed wire."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import sys

from tests.test_permissioned_model_case import fixture, authorities, corrupt
from tests.test_offline_model_run import Clock, AT, LATE, canonical, sha, MODELS, VERSIONS
from tests.test_permissioned_case_submission import gates, RecordingTransport, BRANCH, PIN
from race_ai import permissioned_model_case as case
from race_ai.pr71_delivery_binding import bind_audit_to_delivery, BindingError
from race_ai.model_suite_settlement import audit_model_settlements, ModelSettlementError

NEW_PIN = 'db075c203704d2b30df5742ce8458a43932696a4'
V2 = 'RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2'
PROFILE = 'MAX8_COMPLETE_UNIVERSE'


def v2_fixture(sport='autorace', n=3):
    from tests.test_permissioned_source_delivery import snapshot, FEED_SCHEMA
    request, _, policy = fixture()
    snap = snapshot(sport)
    snap['participants'] = snap['participants'][:n]
    row = deepcopy(request['ledger']['records'][0])
    row['sport'] = 'horse_jra' if sport == 'horse' else sport
    row['race_id'] = f"{row['sport']}:2030-01-15:fictional-venue:1"
    raw = canonical({'schema': FEED_SCHEMA, 'snapshot': snap}).encode()
    request.update(schema=V2, model_source_sha40=NEW_PIN,
        case_id='fictional-v2-'+sport, race_id=row['race_id'],
        source_payload_sha256=sha(raw), feature_snapshot_sha256=sha(canonical(snap).encode()))
    request['ledger']['records'] = [row, {**row, 'race_no':2,
        'race_id':row['race_id'][:-1]+'2'}]
    return request, raw, policy


def v2_gates(request, seen=None):
    result = authorities(request)
    def verify(claim, snapshot, policy_sha, *, analysis_window):
        if seen is not None: seen.append(deepcopy(analysis_window))
        return (claim == request and policy_sha == request['policy_record_sha256']
            and analysis_window['through_at'] == request['sales_cutoff_at']
            and analysis_window['purposes'] == list(case.PURPOSES))
    result['verify_input'] = verify
    result['admit_model_roster'] = lambda value: value == tuple((name,VERSIONS[name],NEW_PIN) for name in MODELS)
    return result


class FixedModelCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='race32-fictional-case-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'case.sqlite'

    def prepare(self, request, raw, policy, **overrides):
        options = v2_gates(request)
        options.update(overrides)
        return case.prepare_case(self.path,request,raw,policy,clock=Clock(),**options)

    def load(self, prepared):
        return case.load_case(self.path,expected_request_sha256=prepared['request_sha256'],
            private_path_verifier=lambda *a,**kw:True)

    def test_explicit_v2_both_minimum_fields_run_original_all_six_models_and_replay(self):
        from race_ai import permissioned_source_delivery as old_source
        for sport in ('autorace','horse'):
            with self.subTest(sport=sport):
                self.path=Path(self.tmp.name)/(sport+'.sqlite')
                request,raw,policy=v2_fixture(sport)
                seen=[]
                # Fresh V2 must not use old parent inference at any stage.
                with patch.object(old_source,'deliver',side_effect=AssertionError('old producer used')):
                    result=self.prepare(request,raw,policy,**v2_gates(request,seen))
                self.assertEqual(result['status'],'PREPARED_NOT_EXTERNAL_FROZEN')
                self.assertEqual(result['schema'],'RACE_AI_PERMISSIONED_MODEL_CASE_RESULT_V2')
                loaded=self.load(result)
                self.assertEqual(len(seen),1)
                self.assertEqual(loaded['analysis_window'],seen[0])
                self.assertIs(loaded['analysis_window_admitted_by_callback'],True)
                self.assertEqual(loaded['request']['model_source_sha40'],NEW_PIN)
                self.assertTrue(all(len(m['ordered_top8'])==6 and m['candidate_count']==6
                    for m in loaded['delivery']['research_suite']['models'].values()))
                self.assertEqual(len(loaded['plans']),4)
                self.assertFalse(result['official_prediction'])
                original=self.path.read_bytes()
                from race_ai import isolated_model_case_runtime as runtime
                def forbidden(*a,**kw):raise AssertionError('cached case renewed')
                with patch.object(runtime,'produce',forbidden),patch.object(runtime,'preflight',forbidden):
                    replay=case.prepare_case(self.path,request,raw,None,clock=forbidden,
                        private_path_verifier=lambda *a,**kw:True,verify_input=forbidden,
                        verify_cutoff=forbidden,admit_model_roster=forbidden)
                self.assertEqual(result,replay)
                self.assertEqual(self.path.read_bytes(),original)

    def test_crossed_unknown_profiles_fail_before_callback_clock_or_path(self):
        request,raw,policy=v2_fixture()
        for schema,pin in ((V2,case.MODEL_PIN),(case.SCHEMA,NEW_PIN),('UNKNOWN',NEW_PIN),(V2,'f'*40)):
            r={**request,'schema':schema,'model_source_sha40':pin}
            with self.subTest(schema=schema,pin=pin),self.assertRaises(case.PermissionedCaseError):
                case.prepare_case(self.path,r,raw,policy,clock=lambda: self.fail('clock'),
                    private_path_verifier=lambda *a,**kw:self.fail('private path'))
            self.assertFalse(self.path.exists())

    def test_unaware_nontrue_mutating_window_admission_denies_before_creation(self):
        request,raw,policy=v2_fixture()
        callbacks=[lambda a,b,c: True,lambda *a,**kw:1,lambda *a,**kw:False]
        def changed(*a,analysis_window):
            analysis_window['through_at']=LATE
            return True
        callbacks.append(changed)
        for callback in callbacks:
            with self.subTest(callback=callback):
                result=self.prepare(request,raw,policy,verify_input=callback)
                self.assertEqual(result['status'],'NO_FORECAST')
                self.assertIn('INPUT_NOT_ADMITTED',result['reasons'])
                self.assertFalse(self.path.exists())

    def test_mutable_grant_dates_do_not_replace_explicit_window_capability(self):
        request,raw,policy=v2_fixture()
        for grant in policy.grants.values():grant['expires_at']='2099-01-01T00:00:00+09:00'
        result=self.prepare(request,raw,policy,verify_input=lambda *a,**kw:False)
        self.assertEqual(result['status'],'NO_FORECAST')
        self.assertFalse(self.path.exists())

    def test_changed_cutoff_or_exceptional_roster_denies_without_private_diagnostics(self):
        request,raw,policy=v2_fixture()
        def changed(row):
            row['sales_cutoff_at']=LATE
            return True
        def broken(*a):raise RuntimeError('FICTIONAL_PRIVATE_DIAGNOSTIC')
        for option in ({'verify_cutoff':changed},{'verify_cutoff':broken},{'admit_model_roster':broken}):
            result=self.prepare(request,raw,policy,**option)
            self.assertEqual(result['status'],'NO_FORECAST')
            self.assertNotIn('FICTIONAL_PRIVATE_DIAGNOSTIC',canonical(result))
            self.assertFalse(self.path.exists())

    def test_legacy_minimum_field_still_denies_without_child(self):
        request,raw,policy=v2_fixture()
        request.update(schema=case.SCHEMA,model_source_sha40=case.MODEL_PIN)
        result=case.prepare_case(self.path,request,raw,policy,clock=Clock(),**authorities(request))
        self.assertEqual(result['reasons'],['PINNED_MODEL_CARDINALITY_UNSUPPORTED'])
        self.assertFalse(self.path.exists())

    def test_header_profile_mismatch_is_not_migrated(self):
        request,raw,policy=v2_fixture()
        result=self.prepare(request,raw,policy)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA user_version=1')
            db.commit()
        original=self.path.read_bytes()
        with self.assertRaises(case.PermissionedCaseError):self.load(result)
        self.assertEqual(original,self.path.read_bytes())

    def test_window_policy_digest_and_complete_verdicts_are_bound_on_reload(self):
        request,raw,policy=v2_fixture()
        result=self.prepare(request,raw,policy)
        with closing(sqlite3.connect(self.path)) as db:
            trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
            db.execute('DROP TRIGGER permissioned_case_no_update')
            request_sha,text,wire=db.execute('SELECT request_sha256,metadata,wire FROM permissioned_case').fetchone()
            metadata=json.loads(text)
            metadata['analysis_window']['source_verdicts_sha256']='a'*64
            digest=sha(b'RACE_AI_PERMISSIONED_MODEL_CASE_CHECKPOINT_V2\0'+canonical([request_sha,metadata,sha(wire)]).encode())
            db.execute('UPDATE permissioned_case SET metadata=?,content_sha256=?',(canonical(metadata),digest))
            db.execute(trigger)
            db.commit()
        with self.assertRaises(case.PermissionedCaseError):self.load(result)

    def test_explicit_binding_and_settlement_no_implicit_max8_or_wrong_pin(self):
        request,raw,policy=v2_fixture()
        loaded=self.load(self.prepare(request,raw,policy))
        delivery=loaded['delivery']; ledger=request['ledger']
        with self.assertRaises(BindingError):bind_audit_to_delivery(ledger,delivery,race_id=request['race_id'])
        accepted=bind_audit_to_delivery(ledger,delivery,race_id=request['race_id'],model_contract=PROFILE)
        self.assertEqual(len(accepted['models']),4)
        for pin in (None,case.MODEL_PIN):
            with self.assertRaises(ModelSettlementError):
                audit_model_settlements(ledger,[],[{'race_id':request['race_id'],'delivery':delivery}],[],
                    expected_model_ids=MODELS,expected_model_versions=VERSIONS,
                    expected_model_source_sha40=pin,model_contract=PROFILE)

    def test_v2_submission_passes_new_pin_and_preserves_original_ack_barriers(self):
        from race_ai.permissioned_case_submission import dispatch_prepared_case, recover_submission_attempts
        request,raw,policy=v2_fixture('horse')
        prepared=self.prepare(request,raw,policy)
        attempt=Path(self.tmp.name)/'attempt.sqlite'; seen=[]; options=gates()
        options['admit_model_roster']=lambda claim,decl: seen.append(decl) is None and all(x[2]==NEW_PIN for x in decl)
        http=RecordingTransport()
        result=dispatch_prepared_case(attempt,self.path,expected_request_sha256=prepared['request_sha256'],
            expected_branch=BRANCH,submission_source_sha40=PIN,clock=Clock(),transport=http,**options)
        self.assertEqual(result['status'],'NORMAL_READBACKS_COMPLETE_RECEIPTS_PENDING')
        self.assertTrue(all(x['normal_acknowledged'] for x in result['models']))
        self.assertTrue(seen)
        self.assertEqual(len(http.calls),8)
        before=attempt.read_bytes()
        recovered=recover_submission_attempts(attempt,self.path,expected_request_sha256=prepared['request_sha256'],
            expected_branch=BRANCH,submission_source_sha40=PIN,clock=Clock(LATE),
            private_path_verifier=options['private_path_verifier'],admit_store=options['admit_store'])
        self.assertEqual(attempt.read_bytes(),before)
        self.assertEqual(len(http.calls),8)

    def test_rehashed_partial_duplicate_padded_and_reordered_six_are_rejected(self):
        request,raw,policy=v2_fixture()
        loaded=self.load(self.prepare(request,raw,policy))
        delivery=loaded['delivery']
        for kind in ('partial','duplicate','padded','reordered'):
            bad=deepcopy(delivery)
            model=next(iter(bad['research_suite']['models'].values()))
            picks=model['ordered_top8']
            model['ordered_top8']=({'partial':picks[:5],'duplicate':picks[:5]+picks[:1],
                'padded':picks+picks[:2],'reordered':list(reversed(picks))})[kind]
            model['prediction_sha256']=sha(canonical({k:v for k,v in model.items() if k!='prediction_sha256'}).encode())
            suite=bad['research_suite']
            suite['suite_sha256']=sha(canonical({k:v for k,v in suite.items() if k!='suite_sha256'}).encode())
            bad['delivery_sha256']=sha(canonical({k:v for k,v in bad.items() if k!='delivery_sha256'}).encode())
            with self.subTest(kind=kind),self.assertRaises(BindingError):
                bind_audit_to_delivery(request['ledger'],bad,race_id=request['race_id'],model_contract=PROFILE)

    def test_new_retention_retains_whole_wire_and_unpromoted_evidence(self):
        from tests.test_private_wire_retention import PrivateWireRetentionTests
        from race_ai import private_wire_retention as retention
        request,raw,policy=v2_fixture('horse')
        prepared=self.prepare(request,raw,policy)
        probe=PrivateWireRetentionTests()
        probe.module=retention; probe.path=self.path; probe.clock=Clock()
        probe.seal=prepared; probe.loaded=self.load(prepared)
        probe.destination={'destination_ref':'fictional-private-destination','owner_scope_ref':'fictional-owner-scope',
            'adapter_contract_sha256':'a'*64,'max_wire_bytes':4*1024*1024}
        probe.policy={'policy_ref':'fictional-retention-policy','retain_until':'2030-02-15T10:00:00+09:00',
            'protection_policy_sha256':'b'*64,'immutability_policy_sha256':'c'*64}
        probe.binding=probe.base()
        original=self.path.read_bytes()
        handoff=probe.prepare()
        self.assertEqual(handoff['status'],'NOT_SENT_NO_WRITE_AUTHORITY')
        self.assertEqual(handoff['wire'],probe.loaded['wire'])
        self.assertEqual(handoff['request']['model_source_sha40'],NEW_PIN)
        checked=probe.verify(handoff)
        self.assertEqual(checked['status'],'ADMITTED_BY_CALLBACK')
        probe.assert_unpromoted(checked)
        self.assertEqual(self.path.read_bytes(),original)

    def test_actual_profiles_interleave_without_parent_import_switch(self):
        case._dependencies()
        names=('permissioned_source_delivery','private_delivery_codec','comprehensive_four_sport_models','four_sport_model_suite')
        original={name:(id(sys.modules['race_ai.'+name]),sys.modules['race_ai.'+name].__file__) for name in names}
        original_path=list(sys.path)
        request1,raw1,policy1=fixture()
        first=Path(self.tmp.name)/'legacy.sqlite'
        old=case.prepare_case(first,request1,raw1,policy1,clock=Clock(),**authorities(request1))
        for sport in ('horse','autorace'):
            self.path=Path(self.tmp.name)/(sport+'.sqlite')
            request,raw,policy=v2_fixture(sport)
            self.assertEqual(self.prepare(request,raw,policy)['status'],'PREPARED_NOT_EXTERNAL_FROZEN')
            self.assertEqual(case.load_case(first,expected_request_sha256=old['request_sha256'],
                private_path_verifier=lambda *a,**kw:True)['request']['model_source_sha40'],case.MODEL_PIN)
        self.assertEqual(original_path,sys.path)
        self.assertEqual(original,{name:(id(sys.modules['race_ai.'+name]),sys.modules['race_ai.'+name].__file__) for name in names})

    def test_concurrent_same_case_has_one_producer_and_identical_commit(self):
        from race_ai import isolated_model_case_runtime as runtime
        request,raw,policy=v2_fixture()
        actual=runtime.produce; calls=[]
        def counted(*a,**kw):
            calls.append(1)
            return actual(*a,**kw)
        with patch.object(runtime,'produce',counted),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.prepare,request,raw,policy) for _ in range(2)]
            results=[f.result(timeout=40) for f in futures]
        self.assertEqual(results[0],results[1])
        self.assertEqual(calls,[1])

    def test_v2_revision_comparison_preserves_all_races_and_original_cases(self):
        from race_ai.comprehensive_four_sport_models import validate
        request,raw,policy=v2_fixture()
        prepared=self.prepare(request,raw,policy); loaded=self.load(prepared)
        original=self.path.read_bytes()
        results=[{'race_id':row['race_id'],'status':'FINAL','trifecta_offered':True,
            'payouts':[{'combination':[1,2,3],'yen_per_100':1000}],
            'refund_status':'NONE','revision_no':1,'confirmed_at':'2030-01-15T11:00:00+09:00',
            'source_ref':'https://example.org/fictional-result'} for row in request['ledger']['records']]
        freezes=[{'race_id':request['race_id'],'model_id':name,'prediction_sha256':model['prediction_sha256'],
            'generated_at':loaded['generated_at'],'persisted_at':loaded['persisted_at'],
            'cutoff_at':request['sales_cutoff_at'],'receipt':{'run_id':1000+i,'path':loaded['plans'][i]['path']}}
            for i,(name,model) in enumerate(loaded['delivery']['research_suite']['models'].items())]
        options={'expected_model_ids':MODELS,'expected_model_versions':VERSIONS,
            'expected_model_source_sha40':NEW_PIN,'model_contract':PROFILE,
            'validate_snapshot':validate,'allow_source':policy.authorize}
        deliveries=[{'race_id':request['race_id'],'delivery':loaded['delivery']}]
        denied=audit_model_settlements(request['ledger'],results,deliveries,freezes,**options)
        self.assertTrue(all(m['formal_hit_at_8_all'] is None for m in denied['models'].values()))
        options.update(admit_model_roster=lambda *a:True,verify_result=lambda *a:True,
            verify_cutoff=lambda *a:True,verify_model_freeze=lambda *a,**kw:True,verify_coverage=lambda *a:True)
        first=audit_model_settlements(request['ledger'],results,deliveries,freezes,**options)
        revision=deepcopy(results[0]);revision.update(revision_no=2,confirmed_at='2030-01-15T12:00:00+09:00',
            payouts=[{'combination':[3,2,1],'yen_per_100':500}])
        second=audit_model_settlements(request['ledger'],results+[revision],deliveries,freezes,**options)
        self.assertNotEqual(first['evaluation_sha256'],second['evaluation_sha256'])
        for model in second['models'].values():
            self.assertEqual(model['eligible_verified_subset'],2)
            self.assertEqual(model['freeze_verified_subset'],1)
            self.assertEqual(model['formal_hit_at_8_all'],0.5) # Fictional callback decisions only.
            self.assertEqual(model['rows'][0]['result_revisions_seen'],2)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse(second['producer_execution_authenticated_by_library'])


if __name__=='__main__':unittest.main()
