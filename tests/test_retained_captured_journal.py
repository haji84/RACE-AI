"""Synthetic lifecycle/score boundaries. No source, model or historical records."""
import copy
from datetime import datetime, timezone
import importlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.retained_prediction_audit import canonical, digest, byte_sha


ROLES = ('facts','bundle','seal','manifest','proof','registry','history','parent','witness','witness_source')
NOW = '2030-01-06T12:00:00+00:00'


def origin():
    models = [{'model_id':f'fictional-{i}', 'model_version':'1', 'numerical_alias_of':None} for i in range(19)]
    scores = [{'combination':list(t),'score':1/120} for t in itertools.permutations(range(1,7),3)]
    races = []
    for i,state in enumerate(('TIMELY_HASH_WITNESS','LATE_HASH_WITNESS','NO_ANCHOR'),1):
        races.append({'race_id':f'20300104-01-0{i}', 'identity':{'sport':'boat','venue':'boatrace-jcd-01','event_date_jst':'2030-01-04','race_no':i},
            'registration_ids':{str(n):str(1000+n)for n in range(1,7)}, 'planned_cutoff_at':'2030-01-04T03:00:00+00:00',
            'as_of':'2030-01-04T01:00:00+00:00','generated_at':'2030-01-04T01:00:01+00:00' if i<3 else None,
            'input_sha256':'a'*64 if i<3 else None,'state':'COMPUTED_BEFORE_PLANNED_CUTOFF'if i<3 else'CLOSED_BEFORE_INFERENCE',
            'local_pre_cutoff_readback':i<3,'witness_state':state,'hash_witness_before_planned_cutoff':True if i==1 else False if i==2 else None,
            'models':[{**m,'status':'FORECAST'if j==0 and i<3 else'NO_FORECAST',
                'reason':None if j==0 and i<3 else'MISSING_INPUT','top8':[x['combination']for x in scores[:8]]if j==0 and i<3 else None,
                'scores120':copy.deepcopy(scores)if j==0 and i<3 else None,'forecast_sha256':'b'*64 if j==0 and i<3 else None}for j,m in enumerate(models)]})
    return {'profile':'RACE41_CAPTURED_HISTORY_V1','models':models,'races':races,
        'history_race_ids':['20300103-01-01','20300103-01-02'],'original_completed_at':'2030-01-04T01:00:04+00:00'}


def inputs():
    files={r:canonical({'role':r})for r in ROLES}
    request={'schema':'RACE_AI_CAPTURED_ORIGIN_REQUEST_V1','profile':'RACE41_CAPTURED_HISTORY_V1',
        'target_race_ids':[r['race_id']for r in origin()['races']], 'history_race_ids':origin()['history_race_ids'],
        'files':{r:{'path':r+'.json','sha256':byte_sha(v)}for r,v in files.items()}}
    policy={'schema':'RACE_AI_RETAINED_AUDIT_POLICY_V1','mode':'RETAINED_PREDICTION_AUDIT',
        'declared_at':'2030-01-06T11:59:00+00:00','prior_result_exposure':'ALREADY_EXPOSED_RESEARCH',
        'result_source_id':'OFFICIAL_BOATRACE','authorization_ref':'fictional-private-owner-audit','settlement_policy':'NORMAL_FINISH_ONLY'}
    return files,request,policy


def observation(rid,status='FINAL'):
    return {'race_id':rid,'revision':1,'status':status,'winning_triples':[[1,2,3]]if status=='FINAL'else[],
        'unscored_reason':None if status=='FINAL'else'SOURCE_UNAVAILABLE_OR_INVALID','file_sha256':'d'*64}


class CapturedJournalTests(unittest.TestCase):
    def setUp(self):
        try:self.api=importlib.import_module('race_ai.retained_captured_journal')
        except ModuleNotFoundError:self.fail('captured journal API absent')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.files,self.req,self.policy=inputs()
        self.j=self.api.CapturedHistoryAuditJournal(self.root,'fictional',clock=lambda:datetime.fromisoformat(NOW))

    def test_legacy_import_and_report_match_prechange_golden_bytes(self):
        from race_ai.retained_prediction_audit import RetainedAuditJournal
        from test_retained_prediction_audit import fixture,policy,label,request,sha,canonical_sha
        files=fixture();p=policy();j=RetainedAuditJournal(self.root/'old','golden',clock=lambda:datetime.fromisoformat(NOW))
        imp=j.import_bundle(files,expected_sha256={k:sha(v)for k,v in files.items()},policy=p,expected_policy_sha256=canonical_sha(p))
        items=[label(files),label(files,38,status='SOURCE_UNAVAILABLE_OR_INVALID')];req=request(items)
        report=j.observe(lambda:items,expected_import_sha256=imp['import_sha256'],label_request=req,expected_request_sha256=canonical_sha(req))
        # Derived once from exact prechange2c949 source, same fictional fixture/time.
        self.assertEqual(digest(imp),'99aeda6fbe747770b2e447962f57a1234d4e7ea2821df2e76dd49bb9fad8912a')
        self.assertEqual(digest(report),'6d8863982c95e6b9f726d1c2fdbadc2da51bb7193539dc2f2bea0ce8ecfb1133')

    def imported(self,reader=None):
        with patch.object(self.api,'adapt_race41',return_value=origin()):
            return self.j.import_captured(reader or(lambda:self.files),request=self.req,expected_request_sha256=digest(self.req),
                policy=self.policy,expected_policy_sha256=digest(self.policy))

    def test_lazy_read_after_shared_lock_and_all_target_history_aliases(self):
        def read():
            self.assertTrue((self.root/'final-reveal.lock').is_file())
            self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),10)
            self.assertTrue((self.j.directory/'import-intent.json').is_file())
            return self.files
        imp=self.imported(read)
        self.assertEqual((imp['potentially_exposed_physical_races'],imp['potentially_exposed_registry_keys']),(5,10))
        self.assertEqual(imp['exposure_protection'],'DECLARED_IDENTITIES_ONLY_NOT_PAYLOAD_AUTHENTICATION')
        self.assertFalse((self.root/'final-reveal.lock').exists())
        with patch.object(self.api,'adapt_race41',return_value=origin()):
            self.assertEqual(self.j._verified(imp['import_sha256']),imp)

    def test_descriptor_policy_errors_never_call_reader(self):
        for change in ('hash','overlap','unsorted','duplicate','unicode','unknown-policy','settlement'):
            with self.subTest(change=change):
                req=copy.deepcopy(self.req);p=copy.deepcopy(self.policy)
                if change=='overlap':req['history_race_ids'][0]=req['target_race_ids'][0]
                if change=='unsorted':req['target_race_ids'].reverse()
                if change=='duplicate':req['target_race_ids'].append(req['target_race_ids'][0])
                if change=='unicode':req['target_race_ids']=[x.replace('2030','２０３０')for x in req['target_race_ids']]
                if change=='unknown-policy':p['prior_result_exposure']='UNKNOWN'
                if change=='settlement':p['settlement_policy']='OFFICIAL_REVISIONS_WITH_CANCELLATION_AND_DEAD_HEAT'
                calls=[]
                with self.assertRaises(ValueError):self.j.import_captured(lambda:calls.append(1),request=req,
                    expected_request_sha256='0'*64 if change=='hash'else digest(req),policy=p,expected_policy_sha256=digest(p))
                self.assertEqual(calls,[])
                self.assertFalse(self.j.directory.exists())

    def test_failed_reader_leaves_exposure_and_pending_no_retry(self):
        def read():raise OSError('synthetic interrupted read')
        with self.assertRaises(OSError):self.imported(read)
        self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),10)
        self.assertFalse((self.j.directory/'import-completed.json').exists())
        self.assertFalse((self.root/'final-reveal.lock').exists())
        calls=[]
        with self.assertRaises(FileExistsError):self.imported(lambda:calls.append(1))
        self.assertEqual(calls,[])

    def test_scope_mismatch_stays_pending(self):
        wrong=origin();wrong['history_race_ids'].pop()
        with patch.object(self.api,'adapt_race41',return_value=wrong),self.assertRaises(ValueError):
            self.j.import_captured(lambda:self.files,request=self.req,expected_request_sha256=digest(self.req),policy=self.policy,expected_policy_sha256=digest(self.policy))
        self.assertFalse((self.j.directory/'import-completed.json').exists())
        self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),10)

    def test_changed_exposure_rejected_before_origin_read(self):
        imp=self.imported();path=next((self.root/'exposed-races').glob('*.json'));path.write_text('{}\n')
        with patch.object(self.api,'adapt_race41')as adapter,self.assertRaises(ValueError):self.j._verified(imp['import_sha256'])
        adapter.assert_not_called()

    def test_changed_original_role_rejected(self):
        imp=self.imported();(self.j.directory/'origin/history.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):self.j._verified(imp['import_sha256'])

    def test_reversed_completion_clock_stays_pending(self):
        clocks=iter([datetime.fromisoformat(NOW),datetime(2029,1,1,tzinfo=timezone.utc)])
        self.j.clock=lambda:next(clocks)
        with self.assertRaises(ValueError):self.imported()
        self.assertFalse((self.j.directory/'import-completed.json').exists())

    def test_first_observe_must_be_after_import_completion_not_reservation(self):
        clocks=iter([datetime.fromisoformat(NOW),datetime.fromisoformat('2030-01-06T12:10:00+00:00')])
        self.j.clock=lambda:next(clocks);imp=self.imported()
        self.j.clock=lambda:datetime.fromisoformat('2030-01-06T12:05:00+00:00')
        calls=[];req={'schema':'RACE_AI_RETAINED_LABEL_REQUEST_V1','observations':[]}
        with patch.object(self.api,'adapt_race41',return_value=origin()),self.assertRaises(ValueError):
            self.j.observe(lambda:calls.append(1)or[],expected_import_sha256=imp['import_sha256'],
                label_request=req,expected_request_sha256=digest(req))
        self.assertEqual(calls,[])

    def test_readback_rejects_batch_moved_before_import_completion(self):
        clocks=iter([datetime.fromisoformat(NOW),datetime.fromisoformat('2030-01-06T12:10:00+00:00')])
        self.j.clock=lambda:next(clocks);imp=self.imported()
        self.j.clock=lambda:datetime.fromisoformat('2030-01-06T12:11:00+00:00')
        req={'schema':'RACE_AI_RETAINED_LABEL_REQUEST_V1','observations':[]}
        with patch.object(self.api,'adapt_race41',return_value=origin()):
            self.j.observe(lambda:[],expected_import_sha256=imp['import_sha256'],label_request=req,expected_request_sha256=digest(req))
            batch=self.j.directory/'result-batches/000000'
            for name,key in (('intent.json','reserved_at'),('completed.json','read_completed_at')):
                path=batch/name;v=json.loads(path.read_bytes());v[key]='2030-01-06T12:05:00+00:00';path.write_bytes(canonical(v)+b'\n')
            with self.assertRaises(ValueError):self.j.read_report(expected_import_sha256=imp['import_sha256'])

    def test_v2_full_denominator_and_descriptive_groups_proper_scores(self):
        imp=self.imported();labels=[observation('20300104-01-01'),observation('20300104-01-02','UNRESOLVED')]
        report=self.api.captured_report(imp,labels,batch_number=0)
        self.assertEqual(report['schema'],'RACE_AI_RETAINED_AUDIT_REPORT_V2')
        self.assertEqual((report['cohort_races'],report['model_slots']),(3,57))
        model=report['models'][0]
        self.assertEqual((model['known_results'],model['unknown_results'],model['hit8']),(1,2,1))
        self.assertAlmostEqual(model['proper_scores']['mean_brier'],119/120)
        self.assertAlmostEqual(model['proper_scores']['mean_log_loss'],4.787491742782046)
        self.assertEqual(report['models'][1]['proper_scores']['scored_predictions'],0)
        for key in ('TIMELY_HASH_WITNESS','LATE_HASH_WITNESS','NO_ANCHOR'):
            self.assertEqual(len(report['hash_witness_cohorts'][key]['race_ids']),1)
        self.assertIsNone(report['formal_hit_at_8_all'])

    def test_zero_probability_has_explicit_infinite_logloss_without_json_infinity(self):
        imp=self.imported();rows=imp['origin']['races'][0]['models'][0]['scores120']
        rows[0]['score']=0;rows[1]['score']+=1/120
        report=self.api.captured_report(imp,[observation('20300104-01-01')],batch_number=0)
        scores=report['models'][0]['proper_scores']
        self.assertIsNone(scores['mean_log_loss']);self.assertEqual(scores['zero_true_probability'],1)
        canonical(report)

    def test_original_race41_labels_are_explicit_and_byte_bound(self):
        from test_retained_captured_origin import fixture, label
        files=fixture(); bundle=json.loads(files['bundle']);race=bundle['races'][115]
        small=origin()['races'][1];small.update(race_id=race['race_id'],planned_cutoff_at=race['planned_cutoff_at'],
            identity={'sport':'boat','venue':'boatrace-jcd-'+race['race_id'][9:11],'event_date_jst':'2030-01-04','race_no':int(race['race_id'][-2:])})
        imported={'origin':{'races':[small]},'original_file_sha256':{k:byte_sha(v)for k,v in files.items()},'policy':self.policy}
        item=label(files);value=json.loads(item['raw'])
        evidence=[{'file_sha256':item['expected_sha256'],'utf8':item['raw'].decode()}]
        result=self.j._adapt_labels(evidence,imported,NOW)
        self.assertEqual(result[0]['status'],'FINAL');self.assertEqual(result[0]['file_sha256'],item['expected_sha256'])
        for mutation in ('witness','schema','extra','cutoff','authority','too-early'):
            bad=copy.deepcopy(value)
            if mutation=='witness':bad['hash_witness_before_planned_cutoff']=True
            elif mutation=='schema':bad['schema']='RACE39_TODAY_RESULT_LABEL_V1'
            elif mutation=='extra':bad['odds']={'1-2-3':999}
            elif mutation=='cutoff':bad['source_page_cutoff_at']='2030-01-04T00:00:00+00:00'
            elif mutation=='too-early':
                from datetime import timedelta
                bad['captured_at']=(datetime.fromisoformat(bad['planned_cutoff_at'])+timedelta(seconds=1)).isoformat()
            else:bad['formal_hit_at_8_all_eligible']=True
            raw=canonical(bad)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.j._adapt_labels([{'file_sha256':byte_sha(raw),'utf8':raw.decode()}],imported,NOW)


if __name__=='__main__':unittest.main()
