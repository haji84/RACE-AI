"""Fictional full-cohort source archives; no real inputs or source requests."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import shutil
from unittest.mock import patch


def raw(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value):
    return sha(raw(value)[:-1])


NOW = '2030-01-06T12:00:00+00:00'


def fixture(day='2030-01-04'):
    compact = day.replace('-',''); captured = day+'T00:00:00+00:00'
    registry = [{'model_id':f'fictional-{i:02d}', 'model_version':'1', 'kind':'fixed_untrained'} for i in range(19)]
    registry[-2]['model_id'] = 'name-bound-display'; registry[-1]['model_id'] = 'name-bound-original'
    source = {'source_id':'fictional-frozen-input', 'source_url':f'https://www1.mbrace.or.jp/od2/B/{compact[:6]}/b{compact[2:]}.lzh',
              'source_sha256':'a'*64, 'captured_at':captured, 'published_at':None, 'evidence_basis':'CAPTURED_BY_CLAIM', 'source_rights_ref':'fictional-owner'}
    model_codes = {'fictional/model.py':'b'*64}
    registry_file = {'schema':'RACE38_SOURCE_ONLY_MODEL_INVENTORY_V1','models':registry}
    observation_id='fictional-frozen-input'
    manifest = {'schema':'RACE39_TODAY_CALLER_MANIFEST_V1','observation_id':observation_id,'day_jst':day,
                'source_url':source['source_url'],'caller_sha256':'7'*64,'registry_sha256':sha(raw(registry_file)),
                'model_source_sha256':model_codes,'source_code_sha256':{'pr72/fictional.py':'c'*64}}
    races = []; venues = []
    tickets = list(itertools.permutations(range(1,7),3))
    scores = [{'combination':list(t),'score':1/120} for t in tickets]
    for v in range(1,15):
        vr = []
        for n in range(1,13):
            index = (v-1)*12+n-1; closed = index < 37
            rid = f'{compact}-{v:02d}-{n:02d}'; cutoff = day+('T00:00:00+00:00' if closed else 'T03:00:00+00:00')
            boats = [{'lane':i,'racer_registration_id':str(1000+i),'motor_no':i,'boat_no':i,'national_win_rate':5.0} for i in range(1,7)]
            vr.append({'race_id':rid,'closed_at':cutoff,'preview_available':False,'boats':boats})
            asof = day+'T01:00:00+00:00'; generated = None if closed else day+'T01:00:01+00:00'
            inp = None if closed else {'case_id':rid,'stage':'P0','legacy':{'boats':[{'lane':i,'national_win_rate':5.0}for i in range(1,7)]},
                'source_manifest_sha256':sha(raw(source)), 'observed_pairwise_snapshot':{'race_id':f'boat:{day}:boatrace-jcd-{v:02d}:{n}',
                    'schema':'RACE_AI_BOAT_OBSERVED_PAIRWISE_V1','scope':'OPERATOR_SUPPLIED_RESEARCH',
                    'venue':f'boatrace-jcd-{v:02d}','event_date_jst':day,'as_of':asof,'stage':'P0','sales_cutoff_at':cutoff,
                    'race_revision':1,'race_source_id':source['source_id'],
                    'participants':[{'lane':i,'registration_no':str(1000+i),
                        'features':{'national_win_rate':{'value':5.0,'sample_n':None,'source_id':source['source_id'],'transform_id':'official_B_national_win_rate_points_v1'}},
                        'missing':{'recent_mean_finish':'NO_PRIOR_SAMPLES','recent_mean_st':'NO_PRIOR_SAMPLES','course_mean_finish':'NO_VERIFIED_COURSE',
                            'course_mean_st':'NO_VERIFIED_COURSE','exhibition_time_seconds':'MISSING','exhibition_start_seconds':'MISSING','motor_top2_rate':'MISSING'}}for i in range(1,7)],'sources':[source]}}
            models = []
            for j,m in enumerate(registry):
                predicted = not closed and j<4
                models.append({'model_id':m['model_id'],'model_version':m['model_version'],'stage':'P0',
                    'status':'FORECAST' if predicted else 'NO_FORECAST','reason':None if predicted else 'CLOSED_BEFORE_INFERENCE'if closed else'MISSING_INPUT',
                    'top8':[list(t)for t in tickets[:8]]if predicted else None,'scores120':copy.deepcopy(scores)if predicted else None,
                    **({'forecast_sha256':'d'*64,'method':'EXACT_PR71_PREDICT_PAIR'}if predicted else{})})
            races.append({'race_id':rid,'planned_cutoff_at':cutoff,'race_revision_claim':1,'stage':'P0','as_of':asof,'input':inp,
                'input_sha256':sha(raw(inp))if inp is not None else None,'generated_at':generated,
                'state':'CLOSED_BEFORE_INFERENCE'if closed else'COMPUTED_BEFORE_PLANNED_CUTOFF','models':models,
                'actual_cutoff_verified':False,'roster_withdrawals_verified':False,'formal_prospective_forecast':False})
        venues.append({'venue':f'{v:02d}','races':vr})
    normalized = {'date_jst':day,'source_url':source['source_url'],'source_sha256':'a'*64,'first_observed_at':captured,
        'venues':venues,'races':168,'complete_six_boat_races':168,'source_hash_scope':'downloaded_archive','extracted_text_sha256':'e'*64}
    facts = {'schema':'RACE39_TODAY_PRIVATE_NORMALIZED_FACTS_V1','observation_id':observation_id,'source':source,'normalized':normalized,
        'source_publication_at':None,'raw_lzh_or_text_retained':False,'independent_capture_timestamp':False}
    bundle = {'schema':'RACE39_TODAY_ALL19_PRIVATE_PREDICTION_BUNDLE_V1','observation_id':observation_id,'normalized_facts_sha256':sha(raw(facts)),
        'source':source,'manifest_sha256':sha(raw(manifest)),'model_registry':registry,'model_code_sha256':model_codes,
        'stage':'P0','races':races,'before_write_local_clock_claimed':day+'T01:00:02+00:00',
        'external_timestamp_verified':False,'formal_prospective_forecast':False,'no_outcome_or_odds_input':True}
    bundle_hash = sha(raw(bundle))
    seal = {'schema':'RACE39_TODAY_LOCAL_READBACK_SEAL_V1','observation_id':observation_id,'bundle_sha256':bundle_hash,'normalized_facts_sha256':sha(raw(facts)),
        'readback_at_local_clock_claimed':day+'T01:00:03+00:00','external_timestamp_verified':False,
        'formal_prospective_forecast':False,'local_storage_immutable':False,
        'races':[{'race_id':r['race_id'],'planned_cutoff_at':r['planned_cutoff_at'],'bundle_sha256':bundle_hash,
                  'local_pre_cutoff_readback':r['state']=='COMPUTED_BEFORE_PLANNED_CUTOFF'}for r in races]}
    proof = {'schema':'RACE39_TODAY_EXECUTION_PROOF_V1','observation_id':observation_id,'caller_sha256':'7'*64,
        'manifest_sha256':sha(raw(manifest)),'phase':'COMPLETE','bundle_sha256':sha(raw(bundle)),'seal_sha256':sha(raw(seal)),
        'normalized_facts_sha256':sha(raw(facts)),'source_archive_sha256':'a'*64,'total_races':168,'registry_models':19,'model_slots':3192,
        'actual_forecasts':524,'races_computed':131,'races_local_pre_cutoff_readback':131,'completed_at_local_clock_claimed':day+'T01:00:04+00:00'}
    values = dict(facts=facts,bundle=bundle,seal=seal,manifest=manifest,proof=proof,registry=registry_file)
    return {k:raw(v)for k,v in values.items()}


def altered(files, change):
    values={k:json.loads(v)for k,v in files.items()};change(values)
    f,b,s,m,p=[values[k]for k in('facts','bundle','seal','manifest','proof')]
    m['registry_sha256']=sha(raw(values['registry']))
    b['manifest_sha256']=sha(raw(m));b['normalized_facts_sha256']=sha(raw(f))
    for race in b['races']:
        if race['input']is not None:race['input_sha256']=sha(raw(race['input']))
    s['bundle_sha256']=sha(raw(b));s['normalized_facts_sha256']=sha(raw(f))
    for race in s['races']:race['bundle_sha256']=s['bundle_sha256']
    p.update(bundle_sha256=sha(raw(b)),seal_sha256=sha(raw(s)),normalized_facts_sha256=sha(raw(f)))
    return {k:raw(v)for k,v in values.items()}


def policy():
    return {'schema':'RACE_AI_RETAINED_AUDIT_POLICY_V1','mode':'RETAINED_PREDICTION_AUDIT',
        'declared_at':'2030-01-06T11:59:00+00:00','prior_result_exposure':'ALREADY_EXPOSED_RESEARCH',
        'result_source_id':'OFFICIAL_BOATRACE','authorization_ref':'fictional-private-owner-audit',
        'settlement_policy':'NORMAL_FINISH_ONLY'}


def label(files, index=37, revision=1, status='SCORABLE_NORMAL_FINISH', winning='1-2-3', prior=None):
    race = json.loads(files['bundle'])['races'][index]; rid = race['race_id']
    observed = status not in ('SOURCE_UNAVAILABLE_OR_INVALID','STOPPED_BEFORE_REQUEST')
    value = {'schema':'RACE39_TODAY_RESULT_LABEL_V1','observation_id':f'fictional-{rid}-{revision}',
        'result_observation_revision':revision,'supersedes_observation_id':None if revision==1 else f'fictional-{rid}-{revision-1}',
        'race_id':rid,'status':status,'source_url':f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}',
        'source_sha256':'f'*64 if observed else None,'captured_at':rid[:4]+'-01-05T00:00:00+00:00'if observed else None,
        'source_published_at':None,'planned_cutoff_at':race['planned_cutoff_at'],
        'source_page_cutoff_at':race['planned_cutoff_at']if status!='CUTOFF_REVISION_REQUIRES_REVIEW'else'2030-01-04T03:01:00+00:00',
        'winning_combination':winning if status=='SCORABLE_NORMAL_FINISH'else None,
        'bundle_sha256':sha(files['bundle']),'seal_sha256':sha(files['seal']),
        'formal_hit_at_8_all_eligible':False,'individual_model_receipt':False,'official_final_cutoff_authenticated':False,
        'raw_html_retained':False,'payout_amounts_retained':False,'correction_policy':'NEW_EXPLICIT_APPEND_ONLY_REVISION_REQUIRED'}
    if status=='SCORABLE_NORMAL_FINISH':
        value.update(body_identity_verified=True,frozen_registration_identity_joined=True,source_result_status='settled',
                     finish_status_counts={'FINISHED':6},refunded_boat_count=0,source_status='AVAILABLE',
                     entry_reconciliation='RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED')
    if revision>1:
        value.update(schema='RACE_AI_RETAINED_OFFICIAL_OBSERVATION_V1',status='FINAL',source_id='OFFICIAL_BOATRACE',
            source_sha256='e'*64,registration_ids={str(i):str(1000+i)for i in range(1,7)},
            official_cutoff_at=race['planned_cutoff_at'],winning_triples=[[int(n)for n in winning.split('-')]],
            supersedes_file_sha256=prior['expected_sha256'],provider_revision_reference='fictional-provider-correction-2')
        for key in ('source_page_cutoff_at','winning_combination','correction_policy','individual_model_receipt','source_status','entry_reconciliation'):
            value.pop(key,None)
    content = raw(value)
    return {'expected_sha256':sha(content),'raw':content}


def request(items):
    return {'schema':'RACE_AI_RETAINED_LABEL_REQUEST_V1','observations':[
        {'race_id':json.loads(x['raw'])['race_id'],'revision':json.loads(x['raw'])['result_observation_revision'],
         'source_id':'OFFICIAL_BOATRACE','file_sha256':x['expected_sha256'],'path':f'fictional-label-{i}.json'}for i,x in enumerate(items)]}


class RetainedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = fixture()
        cls.baseline = tempfile.TemporaryDirectory();cls.addClassCleanup(cls.baseline.cleanup)
        try:api=importlib.import_module('race_ai.retained_prediction_audit')
        except ModuleNotFoundError:return
        p=policy();j=api.RetainedAuditJournal(cls.baseline.name,'fictional',clock=lambda:datetime.fromisoformat(NOW))
        cls.baseline_import=j.import_bundle(cls.files,expected_sha256={k:sha(v)for k,v in cls.files.items()},
                                           policy=p,expected_policy_sha256=canonical_sha(p))

    def setUp(self):
        try: self.api = importlib.import_module('race_ai.retained_prediction_audit')
        except ModuleNotFoundError: self.fail('retained audit implementation is absent')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.time = datetime.fromisoformat(NOW)
        shutil.copytree(self.baseline.name,self.root,dirs_exist_ok=True)
        self.j = self.api.RetainedAuditJournal(self.root,'fictional',clock=lambda:self.time)

    def imported(self):
        return copy.deepcopy(self.baseline_import)

    def observe(self, imp, items, reader=None):
        req=request(items)
        return self.j.observe(reader or(lambda:items),expected_import_sha256=imp['import_sha256'],
                              label_request=req,expected_request_sha256=canonical_sha(req))

    def append(self, imp, report, items, reader=None):
        req=request(items)
        return self.j.append_results(reader or(lambda:items),batch_number=1,expected_import_sha256=imp['import_sha256'],
            expected_report_sha256=canonical_sha(report),label_request=req,expected_request_sha256=canonical_sha(req))

    def test_full_import_preserves_clocks_missing_aliases_and_old_bytes(self):
        result=self.imported(); origin=result['origin']
        self.assertEqual(len(origin['races']),168)
        self.assertEqual(sum(r['generated_at']is None for r in origin['races']),37)
        self.assertEqual(sum(m['status']=='FORECAST'for r in origin['races']for m in r['models']),524)
        self.assertEqual(result['imported_at'],NOW)
        self.assertFalse(result['final_test_eligible'])
        self.assertEqual(origin['models'][-1]['numerical_alias_of'],'official-display-original-pl')
        self.assertEqual((self.j.directory/'origin/bundle.json').read_bytes(),self.files['bundle'])

    def test_changed_origin_rejected_without_registry_writes(self):
        changed=dict(self.files);changed['bundle']+=b' '
        self.root=self.root/'fresh';self.j=self.api.RetainedAuditJournal(self.root,'fictional',clock=lambda:self.time)
        with self.assertRaises(self.api.RetainedAuditError):
            self.j.import_bundle(changed,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=policy(),expected_policy_sha256=canonical_sha(policy()))
        self.assertFalse((self.root/'exposed-races').exists())

    def test_all_exposures_are_durable_before_label_reader_and_full_rows_remain(self):
        imp=self.imported()
        items=[label(self.files,37),label(self.files,38,winning='6-5-4'),label(self.files,39),
               label(self.files,40,status='RESULT_PENDING'),*[label(self.files,i,status='SOURCE_UNAVAILABLE_OR_INVALID')for i in range(41,44)],
               *[label(self.files,i,status='CUTOFF_REVISION_REQUIRES_REVIEW')for i in range(44,46)]]
        def reader():
            self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),336)
            self.assertTrue((self.j.directory/'result-batches/000000/intent.json').exists())
            return items
        report=self.observe(imp,items,reader)
        self.assertEqual(len(report['rows']),3192)
        m=report['models'][0]
        self.assertEqual((m['cohort'],m['known_results'],m['unobserved_results'],m['observed_unscored_results'],m['unknown_results']),(168,3,159,6,165))
        self.assertEqual((m['predicted'],m['hit8'],m['missing_prediction_known']),(131,2,0))
        self.assertEqual(report['models'][4]['missing_prediction_known'],3)
        self.assertIsNone(report['formal_hit_at_8_all'])

    def test_interrupted_reader_cannot_retry_and_prior_report_is_explicit(self):
        imp=self.imported();report=self.observe(imp,[label(self.files)])
        def crash():raise RuntimeError('fictional interruption')
        with self.assertRaises(RuntimeError):
            self.append(imp,report,[label(self.files,38)],crash)
        with self.assertRaises((self.api.RetainedAuditError,FileNotFoundError)):
            self.j.read_report(expected_import_sha256=imp['import_sha256'])
        self.assertEqual(self.j.read_report(expected_import_sha256=imp['import_sha256'],through_batch=0),report)
        called=[]
        with self.assertRaises((self.api.RetainedAuditError,FileNotFoundError)):
            self.append(imp,report,[label(self.files,38)],lambda:called.append(1))
        self.assertEqual(called,[])

    def test_delayed_revision_changes_score_without_changing_import(self):
        imp=self.imported();before=(self.j.directory/'import.json').read_bytes()
        initial=label(self.files,winning='6-5-4');report=self.observe(imp,[initial])
        self.time=datetime(2030,1,7,tzinfo=timezone.utc)
        updated=self.append(imp,report,[label(self.files,revision=2,prior=initial)])
        self.assertEqual(updated['models'][0]['hit8'],1)
        self.assertEqual((self.j.directory/'import.json').read_bytes(),before)
        self.assertEqual(self.j.read_report(expected_import_sha256=imp['import_sha256'],through_batch=0),report)

    def test_shared_lock_prevents_import_and_does_not_remove_other_lock(self):
        lock=self.root/'final-reveal.lock';lock.write_text('other')
        p=policy()
        with self.assertRaises(FileExistsError):
            self.j.import_bundle(self.files,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=p,expected_policy_sha256=canonical_sha(p))
        self.assertEqual(lock.read_text(),'other')

    def test_outcome_fields_in_label_request_fail_before_reader(self):
        imp=self.imported();items=[label(self.files)];req=request(items);req['winning_triples']=[[1,2,3]];called=[]
        with self.assertRaises(self.api.RetainedAuditError):
            self.j.observe(lambda:called.append(1),expected_import_sha256=imp['import_sha256'],
                label_request=req,expected_request_sha256=canonical_sha(req))
        self.assertEqual(called,[])

    def test_unavailable_source_capture_remains_null_separate_from_read_time(self):
        imp=self.imported();self.observe(imp,[label(self.files,status='SOURCE_UNAVAILABLE_OR_INVALID')])
        obs=json.loads((self.j.directory/'result-batches/000000/observations.json').read_bytes())[0]
        self.assertIsNone(obs['observed_at']);self.assertIsNone(obs['source_sha256'])
        self.assertEqual(obs['read_at'],NOW)

    def test_import_intent_tampering_blocks_reader(self):
        imp=self.imported();path=self.j.directory/'import-intent.json';value=json.loads(path.read_bytes())
        value['reserved_at']='2030-01-01T00:00:00Z';path.write_bytes(raw(value));called=[]
        with self.assertRaises(self.api.RetainedAuditError):self.observe(imp,[label(self.files)],lambda:called.append(1))
        self.assertEqual(called,[])

    def test_existing_first_exposure_bytes_are_not_rewritten(self):
        self.imported();before={p.name:p.read_bytes()for p in(self.root/'exposed-races').iterdir()}
        other=self.api.RetainedAuditJournal(self.root,'another-audit',clock=lambda:self.time)
        p=policy();other.import_bundle(self.files,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=p,expected_policy_sha256=canonical_sha(p))
        self.assertEqual({p.name:p.read_bytes()for p in(self.root/'exposed-races').iterdir()},before)

    def test_partial_exposure_failure_consumes_import_without_reader(self):
        j=self.api.RetainedAuditJournal(self.root/'partial','partial',clock=lambda:self.time)
        create=self.api._create;seen=[]
        def fail(path,value):
            if path.parent.name=='exposed-races':
                seen.append(path)
                if len(seen)==3:raise OSError('fictional disk failure')
            return create(path,value)
        p=policy()
        with patch.object(self.api,'_create',side_effect=fail),self.assertRaises(OSError):
            j.import_bundle(self.files,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=p,expected_policy_sha256=canonical_sha(p))

        self.assertEqual(len(list((j.root/'exposed-races').glob('*.json'))),2)
        self.assertFalse((j.directory/'import-completed.json').exists())
        called=[];req=request([label(self.files)])
        with self.assertRaises(FileNotFoundError):
            j.observe(lambda:called.append(1),expected_import_sha256='0'*64,label_request=req,expected_request_sha256=canonical_sha(req))
        self.assertEqual(called,[])
        with self.assertRaises(FileExistsError):
            j.import_bundle(self.files,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=p,expected_policy_sha256=canonical_sha(p))

    def test_import_completion_clock_rollback_never_returns_success(self):
        clocks=iter([datetime.fromisoformat(NOW),datetime(2030,1,1,tzinfo=timezone.utc)])
        j=self.api.RetainedAuditJournal(self.root,'rollback',clock=lambda:next(clocks));p=policy()
        with self.assertRaises(self.api.RetainedAuditError):
            j.import_bundle(self.files,expected_sha256={k:sha(v)for k,v in self.files.items()},policy=p,expected_policy_sha256=canonical_sha(p))
        self.assertTrue((j.directory/'import-intent.json').exists())
        self.assertFalse((j.directory/'import-completed.json').exists())
        self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),336)

    def test_import_blocks_renamed_final_race_in_existing_journal(self):
        self.imported()
        from race_ai.evaluation_journal import EvaluationJournal
        from race_ai.evaluation_experiment import EvaluationError
        from test_evaluation_experiment import plan,payload
        for index,venue in enumerate(('boatrace-jcd-01','01')):
            p=plan();p['experiment_id']='renamed'+str(index);p['races']=[p['races'][2]]
            p['races'][0].update(race_id='renamed-race',venue=venue,race_no=1)
            p['eligibility']=[{'race_id':'renamed-race','stage':'P0','model_id':m['model_id'],'eligible':True,'reason':None}for m in p['models']]
            j=EvaluationJournal(self.root,p['experiment_id']);j.register(p);c,o=payload(p)
            s=j.seal(c,o,sealed_at='2030-01-06T00:00:01Z',expected_plan_sha256=canonical_sha(p));called=[]
            with self.assertRaises(EvaluationError):j.reveal(lambda:called.append(1),expected_seal_sha256=s['seal_sha256'],now=NOW)
            self.assertEqual(called,[])


class OriginAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.files=fixture()

    def rejected(self, change):
        from race_ai.retained_prediction_audit import adapt_race39,RetainedAuditError
        files=altered(self.files,change)
        with self.assertRaises(RetainedAuditError):adapt_race39(files,{k:sha(v)for k,v in files.items()})

    def test_rehashed_legacy_numeric_feature_cannot_disagree_with_frozen_B(self):
        self.rejected(lambda v:v['bundle']['races'][37]['input']['legacy']['boats'][0].update(national_win_rate=9.9))

    def test_rehashed_later_history_inside_snapshot_is_rejected(self):
        self.rejected(lambda v:v['bundle']['races'][37]['input']['observed_pairwise_snapshot']['participants'][0]['features'].update(recent_mean_finish={'value':1.0,'sample_n':20}))

    def test_wrong_execution_proof_type_is_rejected(self):
        self.rejected(lambda v:v['proof'].update(schema='RESULT_EXECUTION_PROOF'))

    def test_wrong_execution_manifest_or_caller_is_rejected(self):
        self.rejected(lambda v:v['proof'].update(manifest_sha256='0'*64))
        self.rejected(lambda v:v['proof'].update(caller_sha256='0'*64))

    def test_mismatched_original_observation_id_is_rejected(self):
        self.rejected(lambda v:v['seal'].update(observation_id='another-source'))

    def test_upgraded_capture_cutoff_or_roster_authority_is_rejected(self):
        self.rejected(lambda v:v['facts'].update(independent_capture_timestamp=True))
        self.rejected(lambda v:v['bundle']['races'][37].update(actual_cutoff_verified=True,roster_withdrawals_verified=True,formal_prospective_forecast=True))

    def test_huge_score_and_changed_top8_are_rejected(self):
        self.rejected(lambda v:v['bundle']['races'][37]['models'][0]['scores120'][0].update(score=10**1000))
        self.rejected(lambda v:v['bundle']['races'][37]['models'][0]['top8'].reverse())

    def test_missing_permutation_and_duplicate_model_slot_are_rejected(self):
        self.rejected(lambda v:v['bundle']['races'][37]['models'][0]['scores120'].pop())
        self.rejected(lambda v:v['bundle']['races'][37]['models'][1].update(model_id='fictional-00'))

    def test_outcome_bearing_expected_audit_cannot_be_origin_member(self):
        from race_ai.retained_prediction_audit import adapt_race39,RetainedAuditError
        files={**self.files,'expected_audit':raw({'winning_triples':[[1,2,3]]})}
        with self.assertRaises(RetainedAuditError):adapt_race39(files,{k:sha(v)for k,v in files.items()})


class LabelAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files=fixture();cls.api=importlib.import_module('race_ai.retained_prediction_audit')
        cls.imported={'origin':cls.api.adapt_race39(cls.files,{k:sha(v)for k,v in cls.files.items()}),
                      'policy':policy(),'original_file_sha256':{k:sha(v)for k,v in cls.files.items()}}

    def correction(self, change):
        initial=label(self.files);update=label(self.files,revision=2,prior=initial);value=json.loads(update['raw']);change(value)
        content=raw(value);evidence=[{'file_sha256':sha(content),'utf8':content.decode()}]
        with self.assertRaises(self.api.RetainedAuditError):self.api.adapt_labels(evidence,self.imported,NOW)

    def test_future_normal_schema_rejects_F_or_refund(self):
        self.correction(lambda x:x.update(finish_status_counts={'FINISHED':5,'F':1},refunded_boat_count=1))

    def test_future_schema_rejects_original_html_and_payout_fields(self):
        self.correction(lambda x:x.update(raw_html_retained=True,payout_amounts_retained=True,raw_html='<html>fictional</html>',payout_amount=12345))

    def test_legacy_schema_rejects_raw_retention_and_unknown_payload(self):
        for fields in ({'raw_html':'<html>fictional</html>'},{'payout_amount':12345},{'raw_html_retained':True},
                       {'payout_amounts_retained':True},{'unreviewed_payload':{'secret':123}}):
            with self.subTest(fields=fields):
                value=json.loads(label(self.files)['raw']);value.update(fields);content=raw(value)
                with self.assertRaises(self.api.RetainedAuditError):
                    self.api.adapt_labels([{'file_sha256':sha(content),'utf8':content.decode()}],self.imported,NOW)

    def test_revision_reusing_observation_id_is_rejected(self):
        initial=label(self.files);update=label(self.files,revision=2,prior=initial)
        previous=self.api.adapt_labels([{'file_sha256':initial['expected_sha256'],'utf8':initial['raw'].decode()}],self.imported,NOW)
        value=json.loads(update['raw']);value['observation_id']=previous[0]['observation_id'];content=raw(value)
        current=self.api.adapt_labels([{'file_sha256':sha(content),'utf8':content.decode()}],self.imported,NOW)
        with self.assertRaises(self.api.RetainedAuditError):self.api._validate_revisions(current,previous)

    def test_wrong_source_or_future_capture_are_rejected(self):
        self.correction(lambda x:x.update(source_url='https://invalid.example/result'))
        self.correction(lambda x:x.update(captured_at='2031-01-01T00:00:00Z'))

    def test_allowed_optional_metadata_cannot_hide_nested_source_payload(self):
        injected={'raw_html':'<html>fictional page</html>','payout_amount':12345}
        cases=[('SCORABLE_NORMAL_FINISH',field,injected)for field in('entry_reconciliation','batch_id','source_status')]
        cases += [('UNSUPPORTED_NONSTANDARD_RESULT','finish_status_counts',injected),
                  ('UNSUPPORTED_NONSTANDARD_RESULT','refunded_boat_count',injected),
                  ('UNSUPPORTED_NONSTANDARD_RESULT','source_result_status',injected)]
        for status,field,payload in cases:
            with self.subTest(status=status,field=field):
                value=json.loads(label(self.files,status=status)['raw']);value[field]=payload;content=raw(value)
                with self.assertRaises(self.api.RetainedAuditError):
                    self.api.adapt_labels([{'file_sha256':sha(content),'utf8':content.decode()}],self.imported,NOW)


class BoundedFileReadTests(unittest.TestCase):
    def test_small_registry_file_does_not_allocate_maximum_input_buffer(self):
        from race_ai.retained_prediction_audit import regular_bytes
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'small.json';path.write_bytes(b'{"small":true}\n');original=Path.open
            class SmallRead:
                def __init__(self,f):self.f=f
                def __enter__(self):return self
                def __exit__(self,*args):self.f.close()
                def fileno(self):return self.f.fileno()
                def read(self,n):
                    if n>1024:raise AssertionError('tiny registry file requested more than1KiB allocation')
                    return self.f.read(n)
            with patch.object(Path,'open',lambda p,*a,**kw:SmallRead(original(p,*a,**kw))):
                self.assertEqual(regular_bytes(path),b'{"small":true}\n')


if __name__=='__main__':unittest.main()
