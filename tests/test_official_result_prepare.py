"""Authored plan-preparation context; never key, GitHub or provider access."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import unittest

from race_ai.actions_contract import digest
from tests.test_all_existing_model_official_recovery import fixture, NOW
from tests.test_official_result_issue import actual_run, BRANCH, REPO, ISSUER
from tests.test_official_recovery_preflight import jobs

try:
    from race_ai import all_existing_model_official_prepare as prepare
except ImportError:
    prepare = None

PATH = 'audit/state/official-result-recovery-prepare-request.json'
SINGLE = 'KEIRIN_SINGLE_SIXTEEN_PROBE'
EIGHT = 'KEIRIN_FIRST_EIGHT_AFTER_VERIFIED_SIXTEEN'
DAY = NOW + timedelta(days=1)


def context():
    data, _, _ = fixture()
    pin = lambda n: dict(id=n, digest='sha256:'+'d'*64, run_id=66, head_sha='c'*40)
    source = deepcopy(data['request'])
    source.update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3',
        mode='FIXED_ATTEMPT_TWO_HISTORICAL_AFTER_VERIFIED_SAME_HOST_PROBE',
        probe_journal_artifact_id=90001, probe_result_artifact_id=90002,
        probe_request_sha256='e'*64)
    source['manifest'].update(schema='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V3',
        execution_day='2026-11-08', target_event_day='2026-11-07')
    source['manifest']['prior_journal_artifacts'].append(pin(90001))
    source['manifest']['checkpoint_artifacts'].append(pin(90002))
    raw = json.dumps(source, sort_keys=True).encode()
    parent = actual_run(dict(data['first_attempt'], updated_at=(DAY-timedelta(minutes=5)).isoformat()))
    first = actual_run(dict(parent, id=66, head_sha='c'*40, updated_at=(DAY-timedelta(hours=2)).isoformat()))
    current = dict(first, run_attempt=2, updated_at=(DAY-timedelta(hours=1)).isoformat())
    prior = dict(head_sha='c'*40, run_id=66, run_attempt=2, first_viewer_job_id=2001,
        recovery_request_sha256=digest(source), recovery_request_blob_sha256=sha256(raw).hexdigest(),
        journal_artifact=pin(90003), result_artifact=pin(90004))
    request = dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V1', repository_id=1416489937,
        workflow_id=392270247, pull_request=71, kind=SINGLE, target_event_day='2026-11-07',
        verified_parent=dict(head_sha=parent['head_sha'], run_id=parent['id'], run_attempt=1, first_viewer_job_id=1001),
        previous_source=prior)
    latest = dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1', repository_id=1416489937,
        workflow_id=392270247, pull_request=71, target={k:prior[k] for k in ('head_sha','run_id','run_attempt')},
        target_first_viewer_job_id=2001, recovery_request_sha256=digest(source),
        recovery_request_blob_sha256=sha256(raw).hexdigest())
    issuer = actual_run(dict(parent, id=99, head_sha=ISSUER, status='in_progress', conclusion=None))
    pr = dict(number=71, state='open', user=dict(id=173585154, login='haji84'),
        head=dict(sha=ISSUER, ref=BRANCH, repo=dict(id=1416489937, full_name=REPO)),
        base=dict(ref='codex/actions-four-sport-e2e', repo=dict(id=1416489937, full_name=REPO)))
    source_jobs = jobs(first); source_jobs['jobs'][0]['id'] = 2001
    snapshot = dict(head_sha=ISSUER, parents=[parent['head_sha']], changed_files=[PATH],
        subject='official-results-prepare: exact', source_is_ancestor=True,
        recovery_raw=raw, current_recovery_raw=raw, latest_issue_raw=json.dumps(latest).encode())
    return request, dict(prepare_run=issuer, current_pr=pr, snapshot=snapshot,
        parent_current=deepcopy(parent), parent_first=deepcopy(parent), parent_jobs=jobs(parent),
        source_current=current, source_first=first, source_jobs=source_jobs, now=DAY), source


def plans():
    cases = [dict(sport='keirin', race_id=f'keirin:2026-11-07:keirin-jyo-48:{n}',
        route=dict(kind='NORMAL_UI', ui_entry_url='https://keirin.jp/pc/top', ui_venue_name='Fixture')) for n in range(1,12)]
    original = dict(schema='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1', execution_day='2026-11-07',
        cases=cases, terms_manifest=dict(terms=['unchanged authored terms']), maximum_requests=32,
        result_wait_seconds=120, static_cache=[dict(raw_base64='AQ==', metadata=dict(source_url=url))
            for url in ('https://autorace.jp/fixture.js','https://keirin.jp/fixture.js')])
    journal = dict(cases=[dict(sport='keirin', race_id=c['race_id'], state='DUE') for c in cases])
    return original, journal


class PreparationContextTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(prepare, 'source-free preparation core must exist')
        return prepare

    def test_fully_tested_code_parent_and_actual_previous_source_are_separate(self):
        api = self.api(); request, ctx, _ = context(); before = deepcopy(ctx)
        proof = api.admit_context(request, **ctx)
        self.assertEqual(proof['verified_parent']['run_id'], 77)
        self.assertEqual(proof['previous_source']['run_id'], 66)
        self.assertEqual(ctx, before)

    def test_parent_current_attempt_two_is_only_its_exact_authenticated_source(self):
        api = self.api(); request, ctx, _ = context()
        request['verified_parent'] = dict(head_sha='c'*40, run_id=66, run_attempt=1, first_viewer_job_id=2001)
        ctx.update(parent_current=ctx['source_current'], parent_first=ctx['source_first'], parent_jobs=ctx['source_jobs'])
        ctx['snapshot']['parents'] = ['c'*40]
        api.admit_context(request, **ctx)
        ctx['parent_current'] = dict(ctx['parent_current'], run_attempt=3)
        with self.assertRaises(ValueError): api.admit_context(request, **ctx)

    def test_unverified_parent_newer_issue_or_source_uncertainty_is_hold(self):
        api = self.api()
        for change in ('parent_running','parent_two_other','python_skipped','parent_job','extra_file','prefix',
                       'fork','source_running','source_attempt','source_hash','newer_issue','ancestry'):
            request, ctx, _ = context()
            if change=='parent_running': ctx['parent_current']=dict(ctx['parent_current'],status='in_progress')
            elif change=='parent_two_other': ctx['parent_current']=dict(ctx['parent_current'],run_attempt=2)
            elif change=='python_skipped': ctx['parent_jobs']['jobs'][0]['steps'][0]['conclusion']='skipped'
            elif change=='parent_job': request['verified_parent']['first_viewer_job_id']=55
            elif change=='extra_file': ctx['snapshot']['changed_files'].append('race_ai/unsafe.py')
            elif change=='prefix': ctx['snapshot']['subject']='official-results-issue: other'
            elif change=='fork': ctx['current_pr']['head']['repo']['id']=1
            elif change=='source_running': ctx['source_current']['status']='in_progress'
            elif change=='source_attempt': ctx['source_current']['run_attempt']=1
            elif change=='source_hash': request['previous_source']['recovery_request_blob_sha256']='0'*64
            elif change=='newer_issue':
                issue=json.loads(ctx['snapshot']['latest_issue_raw']);issue['target']['run_id']=88
                ctx['snapshot']['latest_issue_raw']=json.dumps(issue).encode()
            else: ctx['snapshot']['source_is_ancestor']=False
            with self.subTest(change=change), self.assertRaises(ValueError): api.admit_context(request, **ctx)

    def test_literal_schema_and_typed_pins_only(self):
        api=self.api()
        for change in ('extra','kind','boolean','pin','attempt'):
            request, _, _ = context()
            if change=='extra': request['key_path']='/not-read'
            elif change=='kind': request['kind']='AUTO_REPEAT'
            elif change=='boolean': request['verified_parent']['run_id']=True
            elif change=='pin': request['previous_source']['journal_artifact']['run_id']=1
            else: request['previous_source']['run_attempt']=3
            with self.subTest(change=change), self.assertRaises(ValueError): api.validate_prepare_request(request)


class DeterministicPlanTests(unittest.TestCase):
    def test_preparation_returns_existing_sixteen_or_continuation_request_only(self):
        self.assertIsNotNone(prepare);value,_,source=context()
        result=prepare.build_recovery_request(value,source,plan_sha256='f'*64,now=DAY)
        self.assertEqual(result['schema'],'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4')
        self.assertEqual(result['probe_sport'],'keirin');self.assertNotIn('probe_result_artifact_id',result)
        self.assertEqual(result['manifest']['native_artifacts'],source['manifest']['native_artifacts'])
        value['kind']=EIGHT
        source={k:v for k,v in source.items() if k not in ('probe_journal_artifact_id','probe_result_artifact_id','probe_request_sha256')}
        source.update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4',
            mode='FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE_16',probe_sport='keirin')
        value['previous_source']['recovery_request_sha256']=digest(source)
        result=prepare.build_recovery_request(value,source,plan_sha256='e'*64,now=DAY)
        self.assertEqual(result['schema'],'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3')
        self.assertEqual(result['probe_request_sha256'],digest(source))
        self.assertEqual(result['probe_journal_artifact_id'],90003)
    def test_unchanged_original_order_terms_day_and_sport_static_only(self):
        self.assertIsNotNone(prepare); old, journal=plans(); before=deepcopy(old)
        plan=prepare.derive_plan(SINGLE,old,journal)
        self.assertEqual(plan['cases'],[old['cases'][0]])
        self.assertEqual(plan['static_cache'],old['static_cache'][1:])
        self.assertEqual(plan['execution_day'],old['execution_day']);self.assertEqual(plan['maximum_requests'],16)
        self.assertEqual(plan['terms_manifest'],old['terms_manifest']);self.assertEqual(old,before)

    def test_eight_races_preserve_original_case_objects_and_probe(self):
        self.assertIsNotNone(prepare);old,journal=plans()
        plan=prepare.derive_plan(EIGHT,old,journal,probe_case=old['cases'][0])
        self.assertEqual(plan['cases'],old['cases'][:8]);self.assertEqual(plan['maximum_requests'],32)
        old['cases']=old['cases'][:7]
        with self.assertRaises(ValueError):prepare.derive_plan(EIGHT,old,journal,probe_case=old['cases'][0])

    def test_no_eligible_case_wrong_route_or_missing_original_probe_is_hold(self):
        self.assertIsNotNone(prepare)
        for change in ('not_entrusted','wrong_route','missing_probe'):
            old,journal=plans()
            if change=='not_entrusted':journal['cases']=[]
            elif change=='wrong_route':old['cases'][0]['route']['kind']='DIRECT_API'
            with self.subTest(change=change),self.assertRaises(ValueError):
                prepare.derive_plan(EIGHT if change=='missing_probe' else SINGLE,old,journal,
                    probe_case=old['cases'][-1] if change=='missing_probe' else None)


class RealPreparationEvidenceTests(unittest.TestCase):
    def test_own_keirin_sixteen_normal_nine_rider_result_prepares_eight_races(self):
        from tests.official_result_prepare_fixtures import eight_fixture,KEY
        from race_ai.boat_all_model_store import open_forecasts
        value,data,ctx,now=eight_fixture()
        result=prepare.prepare_from_evidence(value,data,context=ctx,run_id=601,head_sha='7'*40,now=now,key=KEY)
        self.assertEqual((result['counts']['case_count'],result['counts']['maximum_new_requests']),(8,32))
        self.assertEqual(result['request']['schema'],'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3')
        self.assertEqual(result['request']['probe_request_sha256'],digest(data['source_request']))
        plan=open_forecasts(result['plan_cipher'],key=KEY);self.assertEqual(len(plan['cases']),8)
        self.assertTrue(all(c['sport']=='keirin' for c in plan['cases']))
        self.assertEqual(result['counts']['previous_normal_observation_count'],1)
        selector=result['counts']['future_selector']
        self.assertEqual(selector['state'],'selector_absent')
        self.assertTrue(selector['selector_only']);self.assertFalse(selector['fresh_future_input'])
        self.assertNotIn('case',selector)

    def test_copied_earlier_normal_result_cannot_stand_in_for_current_source_capture(self):
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        from tests.test_all_existing_model_official_continuation import zipped,pin
        from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
        from race_ai import all_existing_model_official_results as official
        value,data,ctx,now=single_fixture();source=data['source_request']
        previous=next(a for a in data['groups']['checkpoint_artifacts'] if a['metadata']['id']==source['probe_result_artifact_id'])
        current=next(a for a in data['groups']['checkpoint_artifacts'] if a['metadata']['id']==value['previous_source']['result_artifact']['id'])
        copied=open_forecasts(official._cipher(previous['raw']),key=KEY)
        actual=open_forecasts(official._cipher(current['raw']),key=KEY)
        copied.update(run_id=actual['run_id'],code_sha=actual['code_sha'],generated_at=actual['generated_at'])
        raw=zipped(seal_forecasts(copied,run_id=str(actual['run_id']),round_no=900005,key=KEY),'results.enc')
        current['raw']=raw;current['metadata'].update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
        value['previous_source']['result_artifact']=pin(current['metadata'])
        with self.assertRaisesRegex(ValueError,'CURRENT_SOURCE_RESULT_CAPTURE_JOIN'):
            prepare.prepare_from_evidence(value,data,context=ctx,run_id=501,head_sha='8'*40,now=now,key=KEY)

    def test_real_fixture_native_result_owner_mac_replay_produces_only_plan_authority(self):
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        from race_ai.boat_all_model_store import open_forecasts,forecast_header
        value,data,ctx,now=single_fixture();before=deepcopy(data)
        result=prepare.prepare_from_evidence(value,data,context=ctx,run_id=501,head_sha='8'*40,now=now,key=KEY)
        self.assertEqual(set(result),{'plan_cipher','request','counts'})
        self.assertEqual((result['counts']['case_count'],result['counts']['maximum_new_requests']),(1,16))
        self.assertEqual(result['counts']['source_requests'],0);self.assertEqual(result['counts']['grants_issued'],0)
        self.assertEqual(result['request']['schema'],'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4')
        old=open_forecasts(data['old_plan_raw'],key=KEY);plan=open_forecasts(result['plan_cipher'],key=KEY)
        self.assertIn(plan['cases'][0],old['cases']);self.assertEqual(plan['execution_day'],old['execution_day'])
        self.assertEqual(plan['terms_manifest'],old['terms_manifest'])
        self.assertEqual(forecast_header(result['plan_cipher'])['round_no'],900033)
        self.assertEqual(data,before)

    def test_wrong_owner_capsule_plan_bytes_or_result_metadata_cannot_prepare(self):
        from tests.official_result_prepare_fixtures import single_fixture,KEY
        for change in ('capsule','plan','result_digest'):
            value,data,ctx,now=single_fixture()
            if change=='capsule':data['source_capsule_raw']=data['source_capsule_raw'][:-1]+bytes([data['source_capsule_raw'][-1]^1])
            elif change=='plan':data['old_plan_raw']+=b'corrupt'
            else:
                ident=value['previous_source']['result_artifact']['id']
                next(a for a in data['groups']['checkpoint_artifacts'] if a['metadata']['id']==ident)['metadata']['digest']='sha256:'+'0'*64
            with self.subTest(change=change),self.assertRaises(ValueError):
                prepare.prepare_from_evidence(value,data,context=ctx,run_id=501,head_sha='8'*40,now=now,key=KEY)


if __name__=='__main__':unittest.main()
