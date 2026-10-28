"""Fictional B/K retained archives, with no model/source execution."""
import copy
from datetime import date, timedelta
import hashlib
import importlib
import itertools
import json
import unittest

from race_ai.boat_captured_history_bridge import build_program_history_snapshot


def raw(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value):
    return sha(raw(value)[:-1])


MODELS = [
    ('multisport-factor-interaction-v1','0.1.0-UNTRAINED'),
    ('multisport-scenario-ensemble-v1','0.1.0-UNTRAINED'),
    ('multisport-conditional-duel-v1','0.1.0-UNTRAINED'),
    ('multisport-race-trajectory-v1','0.1.0-UNTRAINED'),
    ('multisport-chronological-ranker-v1','0.1-research-trained + model_sha256'),
    ('boat-comprehensive-v1','0.1.0-UNTRAINED'),('boat-scenario-mixture-v1','0.1.0-UNTRAINED'),
    ('boat-observed-pairwise-factor-v1','0.1.0-UNTRAINED'),('boat-observed-pairwise-start-v1','0.1.0-UNTRAINED'),
    ('boat-b-lite-v1-untrained','0.1.0-UNTRAINED'),('boat-enriched-v1-untrained','0.1.0-UNTRAINED'),
    ('official-program-uniform-pl','1'),('official-program-rating-pl','1'),
    ('official-beforeinfo-display-pl','1'),('official-display-original-pl','1'),
    ('name-bound-display','2'),('name-bound-original','2'),('history-course-plackett-luce','1'),
    ('linear-plackett-luce-research','artifact_sha256 (implementation linear-pl-research-v1)')]
REASONS = [
    *['FULL_COMMON_SPORT_ENVIRONMENT_FEATURES_UNAVAILABLE']*4,
    'NO_ELIGIBLE_PRIOR_FITTED_ARTIFACT_AND_FULL_INPUT',
    *['SEVEN_RATINGS_AND_TRUE_WEATHER_CONDITIONS_UNAVAILABLE']*2,None,None,
    *['CORE_SAMPLE_COUNTS_PUBLICATION_AND_COURSE_SCORE_UNAVAILABLE']*2,None,None,
    'NO_OBSERVED_EXHIBITION_AT_P0','NO_OBSERVED_ORIGINAL_TIMINGS_AT_P0',
    *['NO_GENUINE_NAME_BINDING_AND_EXHIBITION_AT_P0']*2,
    'NO_VERIFIED_CURRENT_COURSE_OR_PUBLISHED_HISTORY_ADMISSION',
    'NO_ELIGIBLE_PRIOR_FITTED_ARTIFACT_AND_FEATURES']
MODEL_PATHS = [
    'legacy:web/evaluation_contract.py','legacy:web/exhibition_contract.py',
    'legacy:web/original_exhibition_contract.py','legacy:web/original_prediction_contract.py',
    'legacy:web/race_contract.py','legacy:web/research_contract.py',
    'pr71:race_ai/actions_contract.py','pr71:race_ai/boat_observed_pairwise_models.py',
    'pr71:race_ai/legacy_boat_rank.py']


def _anchors(values):
    b,s = values['bundle'],values['seal']; day=b['source']['captured_at'][:10]
    run = values['witness_source']['run']; files=[]; entries=[]; races=[]
    for r in b['races']:
        if r['state'] != 'COMPUTED_BEFORE_PLANNED_CUTOFF': continue
        rid=r['race_id']; seal_sha=sha(raw(s))
        path=f'audit/freezes/{day}/'+sha((rid+'\0RACE41_WHOLE_BUNDLE_SEAL\0'+seal_sha).encode())+'.json'
        content=raw({'schema':'RACE_AI_GITHUB_FREEZE_ANCHOR_V1','race_id':rid,'prediction_sha256':seal_sha,'cutoff_at':r['planned_cutoff_at']})
        blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        files.append({'path':path,'status':'added','sha':blob});entries.append({'path':path,'sha':blob,'type':'blob','size':len(content)})
        races.append({'race_id':rid,'planned_cutoff_at':r['planned_cutoff_at'],'anchor_path':path,
                      'hash_witness_before_planned_cutoff':run['created_at']<r['planned_cutoff_at']})
    ws=values['witness_source'];ws['commit']['files']=files;ws['tree']['entries']=entries
    values['witness']={'schema':'RACE41_TODAY_GITHUB_BUNDLE_WITNESS_V1','all_17_anchor_git_blobs_exact':True,
        'bundle_sha256':sha(raw(b)),'seal_sha256':sha(raw(s)),'source_proof_sha256':sha(raw(ws)),
        'formal_hit_at_8_all_eligible':False,'individual_model_receipt':False,'official_final_cutoff_authenticated':False,
        'source_publication_or_capture_authenticated':False,'proof_type':'WHOLE_BUNDLE_SHA_PRESENT_ON_GITHUB_BEFORE_PLANNED_CUTOFF',
        'pre_cutoff_count':16,'late_count':1,'run':copy.deepcopy(run),'races':races}


def rebind(values):
    """Rebind outer bytes only: deliberately do not repair semantic projections."""
    f,b,s,m,p,h,parent=[values[k]for k in('facts','bundle','seal','manifest','proof','history','parent')]
    history_sha=sha(raw(h));registry_sha=sha(raw(values['registry']))
    m['code_pins']['C:/fictional/pr72/artifacts/race38-model-inventory.json']=registry_sha
    m['history_packet_sha256']=history_sha
    f['history_packet_sha256']=history_sha
    b.update(manifest_sha256=sha(raw(m)),normalized_facts_sha256=sha(raw(f)),history_packet_sha256=history_sha)
    for r in b['races']:
        r['history_packet_sha256']=history_sha
        if r['input'] is not None:
            r['input']['source_manifest_sha256']=sha(raw({'program':b['source'],'history':b['history_source'],'history_packet_sha256':history_sha}))
            r['input_sha256']=sha(raw(r['input']))
    s.update(bundle_sha256=sha(raw(b)),normalized_facts_sha256=sha(raw(f)),history_packet_sha256=history_sha)
    for r in s['races']:r['bundle_sha256']=s['bundle_sha256']
    p.update(bundle_sha256=sha(raw(b)),seal_sha256=sha(raw(s)),manifest_sha256=sha(raw(m)),
             normalized_facts_sha256=sha(raw(f)),history_packet_sha256=history_sha)
    parent.update(proof_sha256=sha(raw(p)),manifest_sha256=sha(raw(m)))
    _anchors(values)
    return {key:raw(value)for key,value in values.items()}


def fixture(day='2030-01-04'):
    """Ten independently fictional role bytes; first115closed, next17computed."""
    prior=(date.fromisoformat(day)-timedelta(days=2)).isoformat();compact=day.replace('-','');kd=prior.replace('-','')
    source={'source_id':'fictional-b','source_url':f'https://www1.mbrace.or.jp/od2/B/{compact[:6]}/b{compact[2:]}.lzh',
        'source_sha256':'a'*64,'source_rights_ref':'fictional-owner','published_at':None,'captured_at':day+'T01:00:00+00:00','evidence_basis':'CAPTURED_BY_CLAIM'}
    hs={'source_id':'race39-retained-k'+kd,'source_url':f'https://www1.mbrace.or.jp/od2/K/{kd[:6]}/k{kd[2:]}.lzh',
        'source_sha256':'b'*64,'source_rights_ref':'fictional-owner','published_at':None,'captured_at':prior+'T12:00:00+00:00','evidence_basis':'CAPTURED_BY_CLAIM'}
    rows=[{'race_id':f'{kd}-{v:02d}-{n:02d}','lane':i,'racer_id':str(1000+10*v+i),'course':i,'st':i/100,
           'st_status':'OK','finish':i,'race_at':prior+'T00:00:00+00:00','source_sha256':hs['source_sha256']}
          for v in range(1,13)for n in range(1,13)for i in range(1,7)]
    h={'status':'PRIVATE_NORMALIZED_HISTORY_ONLY','day':prior,'source_get_attempts':1,'raw_source_persisted':False,
       'models_executed':False,'current_race_prediction_input':False,'odds_or_payouts_extracted':False,
       'source':{k:v for k,v in hs.items()if k!='source_id'},'history':{'rows':rows,'complete_races':144,
       'whole_day_completeness_proven':False,'provider_finality_verified':False,
       'race_at_semantics':'PARSER_DATE_SENTINEL_UTC_MIDNIGHT_NOT_ACTUAL_START','race_time_precision':'DATE_ONLY'}}
    h['source'].update(event_date_jst=prior,kind='K',purpose='post_race_results_private_audit',source_rights_basis='OWNER_ATTESTATION_NOT_INDEPENDENT_AUDIT')
    registry=[{'model_id':mid,'model_version':ver,'kind':'fixed_untrained'}for mid,ver in MODELS]
    inventory={'schema':'RACE38_SOURCE_ONLY_MODEL_INVENTORY_V1','models':registry}
    codes={key:sha(key.encode())for key in MODEL_PATHS}
    pins={f'C:/fictional/{key.replace(":","/")}':value for key,value in codes.items()}
    pins.update({'C:/fictional/pr72/artifacts/race41-today-caller.py':'c'*64,
        'C:/fictional/pr72/artifacts/race41-today-parent.py':'d'*64,'C:/fictional/pr72/race_ai/boat_captured_history_bridge.py':'e'*64,
        'C:/fictional/pr72/artifacts/race38-model-inventory.json':sha(raw(inventory)),'C:/fictional/runtime.pyd':'9'*64})
    m={'schema':'RACE41_TODAY_CALLER_MANIFEST_V1','observation_id':source['source_id'],'day_jst':day,'source_url':source['source_url'],
       'code_pins':pins,'history_packet_sha256':sha(raw(h)),'history_archive_sha256':hs['source_sha256'],
       'pr72_head':'1'*40,'pr71_head':'2'*40,'prepared_at':day+'T00:59:00+00:00'}
    scores=[{'combination':list(t),'score':1/120}for t in itertools.permutations(range(1,7),3)]
    races=[];venues=[]
    for v in range(1,12):
        vr=[]
        for n in range(1,13):
            index=(v-1)*12+n-1;closed=index<115;rid=f'{compact}-{v:02d}-{n:02d}'
            cutoff=day+('T00:00:00+00:00'if closed else'T01:02:00+00:00'if index==115 else'T03:00:00+00:00')
            boats=[{'lane':i,'racer_registration_id':str(1000+10*v+i),'motor_no':i,'boat_no':i,'national_win_rate':5.0}for i in range(1,7)]
            fact={'race_id':rid,'closed_at':cutoff,'preview_available':False,'boats':boats};vr.append(fact)
            asof=day+f'T01:01:{max(0,index-115):02d}+00:00';enriched=None;case=None
            if not closed:
                enriched=build_program_history_snapshot(fact,source,rows,hs,event_date_jst=day,as_of=asof,race_revision=1)
                case={'case_id':rid,'stage':'P0','legacy':{'boats':[{'lane':i,'national_win_rate':5.0}for i in range(1,7)]},
                    'source_manifest_sha256':sha(raw({'program':source,'history':hs,'history_packet_sha256':sha(raw(h))})),
                    'observed_pairwise_snapshot':enriched['snapshot']}
            models=[]
            for j,registered in enumerate(registry):
                model={'model_id':registered['model_id'],'model_version':registered['model_version'],'stage':'P0',
                       'status':'NO_FORECAST','reason':'CLOSED_BEFORE_INFERENCE'if closed else REASONS[j],'top8':None,'scores120':None}
                if not closed and j in(7,8,11,12):
                    model.pop('reason');model.update(status='FORECAST',top8=[r['combination']for r in scores[:8]],scores120=copy.deepcopy(scores),numerical_alias_of=None,
                        method='EXACT_PR71_PREDICT_PAIR'if j in(7,8)else'PINNED_LEGACY_NUMERIC_FORMULA_AND_PL_KERNEL')
                    if j in(7,8):model.update(source_model_status='OBSERVED_CONTRASTS',forecast_sha256='f'*64)
                    else:
                        model['baseline_model_id']=None;model['forecast_sha256']=canonical_sha(model)
                models.append(model)
            races.append({'race_id':rid,'planned_cutoff_at':cutoff,'race_revision_claim':1,'stage':'P0','as_of':asof,
                'input':case,'input_sha256':sha(raw(case))if case else None,'history_audit':enriched['history_audit']if enriched else None,
                'history_packet_sha256':sha(raw(h)),'generated_at':None if closed else day+f'T01:01:{index-114:02d}+00:00',
                'state':'CLOSED_BEFORE_INFERENCE'if closed else'COMPUTED_BEFORE_PLANNED_CUTOFF','models':models,
                'actual_cutoff_verified':False,'roster_withdrawals_verified':False,'formal_prospective_forecast':False})
        venues.append({'venue':f'{v:02d}','races':vr})
    f={'schema':'RACE41_TODAY_PRIVATE_NORMALIZED_FACTS_V1','observation_id':source['source_id'],'source':source,
       'normalized':{'date_jst':day,'source_url':source['source_url'],'source_sha256':source['source_sha256'],'first_observed_at':source['captured_at'],
         'venues':venues,'races':132,'complete_six_boat_races':132},'source_publication_at':None,'raw_lzh_or_text_retained':False,'independent_capture_timestamp':False,'history_packet_sha256':sha(raw(h))}
    b={'schema':'RACE41_TODAY_ALL19_PRIVATE_PREDICTION_BUNDLE_V1','observation_id':source['source_id'],'source':source,'history_source':hs,
       'model_registry':registry,'model_code_sha256':codes,'adapter_sha256':'e'*64,'decompressor_runtime_sha256':{'C:/fictional/runtime.pyd':'9'*64},
       'stage':'P0','races':races,'before_write_local_clock_claimed':day+'T01:01:20+00:00',
       'external_timestamp_verified':False,'formal_prospective_forecast':False,'no_target_outcome_or_odds_input':True}
    s={'schema':'RACE41_TODAY_LOCAL_READBACK_SEAL_V1','observation_id':source['source_id'],'readback_at_local_clock_claimed':day+'T01:01:21+00:00',
       'external_timestamp_verified':False,'formal_prospective_forecast':False,'local_storage_immutable':False,
       'races':[{'race_id':r['race_id'],'planned_cutoff_at':r['planned_cutoff_at'],'local_pre_cutoff_readback':r['input']is not None,
                 'required_external_witness':'EXACT_BUNDLE_AND_SEAL_DIGEST_BEFORE_THIS_CUTOFF'}for r in races]}
    p={'schema':'RACE41_TODAY_EXECUTION_PROOF_V1','observation_id':source['source_id'],'caller_sha256':'c'*64,'phase':'COMPLETE',
       'source_archive_sha256':source['source_sha256'],'total_races':132,'registry_models':19,'model_slots':2508,'actual_forecasts':68,
       'races_computed':17,'races_local_pre_cutoff_readback':17,'source_GETs':1,'automatic_retry_allowed':False,'raw_source_saved':False,
       'external_timestamp_verified':False,'formal_prospective_forecast':False,'local_storage_immutable':False,
       'status':'PRIVATE_INPUT_AND_PREDICTIONS_RETAINED_EXTERNAL_WITNESS_PENDING',
       'started_at_local_clock_claimed':day+'T00:59:59+00:00','completed_at_local_clock_claimed':day+'T01:01:22+00:00'}
    parent={'accepted_complete':True,'caller_sha256':'c'*64,'child_reaped':True,'exit_code':0,'source_GETs':1,'retries':0,
        'timed_out':False,'interrupted':False,'reap_failed':False,'kill_failed':False,'cleanup_failed':False,
        'status':p['status'],'completed_at':day+'T01:01:23+00:00'}
    run={'id':123,'created_at':day+'T01:03:00+00:00','head_sha':'3'*40,'head_branch':'audit/freeze-race41-'+compact,
         'path':'.github/workflows/p0-freeze-witness.yml','workflow_id':456,'run_attempt':1,'event':'push','status':'completed','conclusion':'success',
         'html_url':'https://github.com/fictional/repository/actions/runs/123'}
    ws={'schema':'RACE41_GITHUB_HASH_WITNESS_SOURCE_V1','observed_at':day+'T01:04:00+00:00',
        'private_payload_public':False,'run':run,'commit':{'sha':'3'*40,'tree_sha':'4'*40,'parents':['1'*40],'files':[]},
        'tree':{'sha':'4'*40,'truncated':False,'entries':[]}}
    return rebind(dict(facts=f,bundle=b,seal=s,manifest=m,proof=p,registry=inventory,history=h,parent=parent,witness_source=ws))


def altered(files, change):
    values={k:json.loads(v)for k,v in files.items()};change(values);return rebind(values)


def policy():
    return {'schema':'RACE_AI_RETAINED_AUDIT_POLICY_V1','mode':'RETAINED_PREDICTION_AUDIT','declared_at':'2030-01-06T11:59:00+00:00',
            'prior_result_exposure':'ALREADY_EXPOSED_RESEARCH','result_source_id':'OFFICIAL_BOATRACE',
            'authorization_ref':'fictional-private-owner-audit','settlement_policy':'NORMAL_FINISH_ONLY'}


def label(files, index=115, *, status='SCORABLE_NORMAL_FINISH', winning='1-2-3'):
    race=json.loads(files['bundle'])['races'][index];rid=race['race_id'];day=rid[:4]+'-'+rid[4:6]+'-'+rid[6:8]
    observed=status not in('SOURCE_UNAVAILABLE_OR_INVALID','STOPPED_BEFORE_REQUEST');timely=index!=115
    value={'schema':'RACE41_TODAY_RESULT_LABEL_V1','observation_id':f'fictional-{rid}-v1','result_observation_revision':1,
        'supersedes_observation_id':None,'race_id':rid,'status':status,
        'source_url':f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}',
        'source_sha256':'9'*64 if observed else None,'captured_at':day+'T04:00:00+00:00'if observed else None,'source_published_at':None,
        'planned_cutoff_at':race['planned_cutoff_at'],'source_page_cutoff_at':race['planned_cutoff_at']if observed else None,
        'winning_combination':winning if status=='SCORABLE_NORMAL_FINISH'else None,'hash_witness_before_planned_cutoff':timely,
        'comparison_subset':'TIMELY_HASH_WITNESSED_PLANNED_CUTOFF'if timely else'LATE_HASH_WITNESS_RESEARCH_ONLY',
        'bundle_sha256':sha(files['bundle']),'seal_sha256':sha(files['seal']),'formal_hit_at_8_all_eligible':False,
        'individual_model_receipt':False,'official_final_cutoff_authenticated':False,'raw_html_retained':False,'payout_amounts_retained':False,
        'correction_policy':'NEW_EXPLICIT_APPEND_ONLY_REVISION_REQUIRED'}
    if observed:value.update(source_status='AVAILABLE',body_identity_verified=True,source_result_status='settled',finish_status_counts={'FINISHED':6},
        refunded_boat_count=0,entry_reconciliation='RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED',frozen_registration_identity_joined=True)
    content=raw(value);return {'expected_sha256':sha(content),'raw':content}


class CapturedOriginTests(unittest.TestCase):
    def test_optional_metadata_cannot_embed_raw_or_upgrade_authority(self):
        changes=[lambda v:v['facts'].update(transport_receipt={'raw_html':'<html>target outcome</html>'}),
            lambda v:v['facts'].update(transport_receipt={'allowed_in_predictive_snapshot':True}),
            lambda v:v['bundle'].update(selection={'raw_html':'<html>target outcome</html>'}),
            lambda v:v['manifest'].update(caps={'raw_html':'<html>target outcome</html>'}),
            lambda v:v['manifest'].update(public_payload_allowed=True),
            lambda v:v['manifest'].update(raw_source_persisted=True),
            lambda v:v['history'].update(historical_event_day_only=False),
            lambda v:v['bundle']['races'][115]['models'][7].update(source_model_status='OFFICIAL_INDEPENDENTLY_AUTHENTICATED')]
        for change in changes:
            with self.subTest(change=changes.index(change)):self.reject_change(change)
    @classmethod
    def setUpClass(cls):cls.files=fixture()

    def adapter(self):
        try:module=importlib.import_module('race_ai.retained_captured_origin')
        except ImportError:self.fail('explicit captured-history origin adapter is absent')
        return module

    def test_full_origin_retains_arrays_missing_slots_and_witness_partition(self):
        out=self.adapter().adapt_race41(self.files,{k:sha(v)for k,v in self.files.items()})
        self.assertEqual(len(out['races']),132);self.assertEqual(len(out['history_race_ids']),144)
        self.assertEqual(len(out['models']),19);self.assertEqual(sum(len(r['models'])for r in out['races']),2508)
        self.assertEqual(sum(r['witness_state']=='TIMELY_HASH_WITNESS'for r in out['races']),16)
        self.assertEqual(out['races'][115]['witness_state'],'LATE_HASH_WITNESS')
        self.assertIsNone(out['races'][0]['hash_witness_before_planned_cutoff'])
        forecasts=[m for r in out['races']for m in r['models']if m['status']=='FORECAST']
        self.assertEqual(len(forecasts),68);self.assertTrue(all(len(m['scores120'])==120 for m in forecasts))
        self.assertEqual(sum(m['inner_digest_verification']=='LEGACY_PREIMAGE_VERIFIED'for m in forecasts),34)
        self.assertEqual(sum(m['inner_digest_verification']=='FULL_SOURCE_MODEL_PREIMAGE_NOT_RETAINED'for m in forecasts),34)

    def reject_change(self, change, *, rehash=True):
        module=self.adapter();values={k:json.loads(v)for k,v in self.files.items()};change(values)
        files=rebind(values)if rehash else{k:raw(v)for k,v in values.items()}
        with self.assertRaises(ValueError):module.adapt_race41(files,{k:sha(v)for k,v in files.items()})

    def test_exact_role_and_byte_closure(self):
        module=self.adapter();pins={k:sha(v)for k,v in self.files.items()}
        for missing in('history','parent','witness_source'):
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                module.adapt_race41({k:v for k,v in self.files.items()if k!=missing},pins)
        with self.assertRaises(ValueError):module.adapt_race41(self.files,{**pins,'history':'0'*64})

    def test_rehashed_history_window_member_change_is_rejected(self):
        self.reject_change(lambda v:v['history']['history']['rows'][0].update(st=0.99))

    def test_parser_date_sentinel_cannot_be_renamed_actual_race_time(self):
        self.reject_change(lambda v:v['history']['history'].update(race_at_semantics='ACTUAL_START'))

    def test_rehashed_whole_race_drop_cannot_hide_behind_same_means(self):
        self.reject_change(lambda v:v['history']['history'].update(rows=v['history']['history']['rows'][6:]))

    def test_future_capture_and_publication_upgrade_rejected(self):
        self.reject_change(lambda v:v['history']['source'].update(captured_at='2030-01-05T00:00:00+00:00'))
        self.reject_change(lambda v:v['bundle']['history_source'].update(published_at='2030-01-02T10:00:00+00:00'))

    def test_rehashed_history_feature_and_audit_drift_rejected(self):
        self.reject_change(lambda v:v['bundle']['races'][115]['input']['observed_pairwise_snapshot']['participants'][0]['features']['recent_mean_st'].update(value=0.99))
        self.reject_change(lambda v:v['bundle']['races'][115]['history_audit']['participants'][0].update(start_n=999))

    def test_new_course_or_target_outcome_payload_rejected(self):
        self.reject_change(lambda v:v['bundle']['races'][115]['input'].update(results=[1,2,3]))
        self.reject_change(lambda v:v['bundle']['races'][115]['input']['observed_pairwise_snapshot']['participants'][0]['features'].update(course_mean_st={'value':0.1}))

    def test_closed_slot_or_generation_cannot_be_upgraded(self):
        self.reject_change(lambda v:v['bundle']['races'][0].update(generated_at='2030-01-04T01:01:00+00:00'))
        self.reject_change(lambda v:v['bundle']['races'][0]['models'][0].update(reason='MISSING_INPUT'))

    def test_six_boat_allocation_or_registration_changed(self):
        self.reject_change(lambda v:v['facts']['normalized']['venues'][0]['races'][0]['boats'][0].update(motor_no=2))

    def test_closed_boat_lane_boolean_is_not_lane_one(self):
        self.reject_change(lambda v:v['facts']['normalized']['venues'][0]['races'][0]['boats'][0].update(lane=True))

    def test_unknown_role_payload_fields_are_rejected(self):
        for role in('facts','bundle','manifest','proof','parent','seal'):
            with self.subTest(role=role):self.reject_change(lambda v:v[role].update(raw_html='not admitted'))

    def test_decompressor_digest_must_match_execution_pins(self):
        self.reject_change(lambda v:v['bundle']['decompressor_runtime_sha256'].update({'C:/fictional/runtime.pyd':'0'*64}))

    def test_model_matrix_and_probability_mass_are_checked(self):
        self.reject_change(lambda v:v['bundle']['races'][115]['models'][7]['scores120'][0].update(score=0.5))
        self.reject_change(lambda v:v['bundle']['races'][115]['models'][7].update(model_version='changed'))

    def test_top8_must_match_complete_sorted_score_prefix(self):
        self.reject_change(lambda v:v['bundle']['races'][115]['models'][7]['top8'].reverse())

    def test_legacy_inner_digest_must_recompute(self):
        self.reject_change(lambda v:v['bundle']['races'][115]['models'][11].update(forecast_sha256='1'*64))

    def test_parent_completion_and_runtime_lineage_cannot_be_forged(self):
        self.reject_change(lambda v:v['parent'].update(child_reaped=False))
        self.reject_change(lambda v:v['parent'].update(cleanup_failed=True))
        self.reject_change(lambda v:v['manifest']['code_pins'].update({'C:/fictional/pr71/race_ai/boat_observed_pairwise_models.py':'0'*64}))

    def test_duplicate_code_role_match_is_rejected(self):
        self.reject_change(lambda v:v['manifest']['code_pins'].update({'C:/other/artifacts/race41-today-caller.py':'c'*64}))

    def test_local_readback_clock_and_flag_cannot_be_upgraded(self):
        self.reject_change(lambda v:v['seal'].update(readback_at_local_clock_claimed='2030-01-04T01:00:59+00:00'))
        self.reject_change(lambda v:v['seal']['races'][0].update(local_pre_cutoff_readback=True))

    def test_witness_blob_and_late_flag_are_not_trusted(self):
        self.reject_change(lambda v:v['witness']['races'][0].update(hash_witness_before_planned_cutoff=True),rehash=False)
        self.reject_change(lambda v:v['witness_source']['tree']['entries'][0].update(size=999),rehash=False)

    def test_witness_run_must_bind_original_commit_and_tree(self):
        self.reject_change(lambda v:v['witness_source']['commit'].update(tree_sha='5'*40))
        self.reject_change(lambda v:v['witness_source']['run'].update(event='workflow_dispatch'))

    def test_inputs_are_not_mutated_and_no_result_or_model_reads_occur(self):
        from unittest.mock import patch
        module=self.adapter();before=copy.deepcopy(self.files)
        with patch('builtins.open',side_effect=AssertionError('adapter must not open files')):
            out=module.adapt_race41(self.files,{k:sha(v)for k,v in self.files.items()})
        self.assertEqual(self.files,before)
        out['races'][115]['models'][7]['scores120'][0]['score']=0.5
        self.assertEqual(self.files,before)


if __name__=='__main__':unittest.main()
