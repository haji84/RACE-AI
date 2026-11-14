"""Invented browser originals, pure packing and native contracts; no source/key I/O."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib.util
import json
import unittest

from race_ai import all_existing_model_registry as registry
from tests import test_all_existing_model_source_packet_freeze as fixtures
from tests.test_autorace_official_sparse_adapter import NOW


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def capture_fixture():
    original_cases = [fixtures.auto_case(), fixtures.keirin_case()]
    files = {}; rows = []; captured = []; plans = []
    for number, case in enumerate(original_cases):
        sport = case['sport']; auto = sport == 'autorace'
        metadata = deepcopy(case['capture_metadata'] if auto else case['racelive_metadata'])
        start = NOW-timedelta(seconds=60-number*30)
        dom_at = start+timedelta(seconds=25 if auto else 20)
        metadata.update(started_at=start.isoformat(), captured_at=dom_at.isoformat(),
                        ui_capture_kind='NORMAL_BROWSER_UI', scope='OPERATOR_SUPPLIED_RESEARCH', stopped_host=False)
        path = f'case-{number+1:02d}'
        dom = base64.b64decode(case['rendered_dom_b64'])
        metadata['rendered_dom'] = dict(file=path+'/rendered-dom.html',
            source_url=metadata['source_url'], final_url=metadata['final_url'],
            captured_at=dom_at.isoformat(), byte_count=len(dom), source_sha256=sha256(dom).hexdigest())
        files[path+'/rendered-dom.html'] = dom
        browser_rows = []
        roles = ('program', 'identity') if auto else ('racelist', 'racelive')
        for offset, role in enumerate(roles):
            entry = deepcopy(metadata['ledger'][offset]); sequence = len(rows)+1
            source_field = ('program_raw_b64' if role == 'program' else 'race_info_raw_b64') if auto else role+'_raw_b64'
            raw = base64.b64decode(case[source_field]); fetched = start+timedelta(seconds=5+offset*6)
            completed = fetched+timedelta(seconds=2)
            entry.update(sequence=sequence, request_started_at=fetched.isoformat(),
                response_received_at=completed.isoformat(), body_captured_at=completed.isoformat(),
                body_file=f'response-{sequence:03d}.body', metadata_file=f'response-{sequence:03d}.metadata.json')
            http = dict(source_url=entry['url'], final_url=entry['url'], status=200,
                byte_count=len(raw), source_sha256=sha256(raw).hexdigest(), fetched_at=fetched.isoformat(),
                response_received_at=completed.isoformat(), headers={'content-type':entry['content_type']},
                method='POST', http_method='POST', resource_type=entry['resource_type'], ui_capture_kind='NORMAL_BROWSER_UI')
            request = (base64.b64decode(case['request_bodies_b64'][entry['request_body_sha256']]) if auto else
                       b'disp='+ (b'PJ0305' if role == 'racelist' else b'PJ0315')+b'&encp=normal-ui-fixture')
            entry.update(request_body_file=f'request-{sequence:03d}.body',request_body_sha256=sha256(request).hexdigest(),
                         request_content_type='application/json;charset=UTF-8' if auto else 'application/x-www-form-urlencoded')
            files[entry['request_body_file']] = request
            http.update({key:entry[key] for key in ('request_body_file','request_body_sha256','request_content_type')})
            if auto:
                entry['request_identity'] = json.loads(request)
            files[entry['body_file']] = raw; files[entry['metadata_file']] = wire(http)
            rows.append(entry); browser_rows.append(deepcopy(entry))
        if not auto:
            for event in metadata['ledger'][2:]:
                event['at'] = (start+timedelta(seconds=9 if '一覧' in event['label'] else 18)).isoformat()
                browser_rows.append(event)
        metadata['ledger'] = sorted(browser_rows, key=lambda entry: entry.get('request_started_at',entry.get('at')))
        race = 'autorace:2030-01-15:isesaki:1' if auto else 'keirin:2030-01-15:keirin-jyo-48:2'
        captured.append(dict(sport=sport, race_id=race, state='CAPTURED',
            responses=[dict(role=role, sequence=len(rows)-1+i) for i, role in enumerate(roles)],
            rendered_dom=deepcopy(metadata['rendered_dom']), browser_metadata=metadata))
        plans.append(dict(sport=sport, race_id=race, ui_entry_url=metadata['source_url'],
            expected_date='2030-01-15', venue='isesaki' if auto else 'keirin-jyo-48',
            race_no=1 if auto else 2, cutoff_at='2030-01-15T10:58:00+09:00' if auto else '2030-01-15T11:50:00+09:00',
            **({} if auto else {'ui_venue_name':'創作競輪場'})))
    plan = dict(schema='RACE_AI_OFFICIAL_FUTURE_BROWSER_PLAN_V1', intent='CAPTURE_FRESH_NATIVE_FUTURE_CARDS',
                available_after=(NOW-timedelta(seconds=70)).isoformat(), cases=plans)
    index = dict(schema='RACE_AI_OFFICIAL_FUTURE_BROWSER_CAPTURE_V1', intent=plan['intent'],
        available_after=plan['available_after'], started_at=(NOW-timedelta(seconds=60)).isoformat(),
        completed_at=NOW.isoformat(), actual_request_count=4, maximum_requests=32,
        minimum_spacing_ms=825, maximum_elapsed_ms=85000, request_timeout_ms=12000,
        stop_reason='FINISHED', stopped_host=False, normal_ui_only=True, manual_api_requests=0,
        formal_learning_or_pdca_claim=False, native_contracts_verified=False,
        independent_pre_cutoff_receipt_verified=False, cases=captured, responses=rows,
        ledger=sorted([deepcopy(entry) for case in captured for entry in case['browser_metadata']['ledger']],
                      key=lambda entry: entry.get('request_started_at',entry.get('at'))))
    return plan, index, files, fixtures.packet(original_cases)['terms_manifest']


class FutureSourcePacketTests(unittest.TestCase):
    def build(self, plan, index, files, terms, **options):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.official_future_source_packet'),
                             'pure future packet builder is missing')
        from race_ai.official_future_source_packet import build_source_packet
        return build_source_packet(plan, index, files, terms_manifest=terms, as_of=options.get('as_of', NOW))

    def test_exact_raw_packing_proves_all_eleven_cells_at_one_fixed_asof_without_inventing_a_baseline(self):
        data = capture_fixture(); before = deepcopy(data); out = self.build(*data)
        self.assertEqual(out['state'], 'READY_INPUTS_ONLY'); self.assertEqual(data, before)
        self.assertEqual(out['fixed_as_of'], NOW.isoformat()); self.assertEqual(len(out['requests']), 11)
        self.assertEqual(out['packet']['schema'], 'RACE_AI_OFFICIAL_SOURCE_PACKET_V1')
        self.assertEqual(len(out['packet']['cases']), 2)
        self.assertEqual(base64.b64decode(out['packet']['cases'][0]['program_raw_b64']), data[2]['response-001.body'])
        self.assertEqual(base64.b64decode(out['packet']['cases'][1]['racelive_raw_b64']), data[2]['response-004.body'])
        for request in out['requests']:
            sport, mid = request['cell_key'].split('/', 1)
            identity = registry.identity(mid, sport, request['native_payload'])
            self.assertEqual(identity['as_of'], NOW.isoformat())
            self.assertNotIn('learned_model', request['native_payload'])
            self.assertNotIn('baseline_attachment', request['native_payload'])
        self.assertFalse(out['baseline_authenticated']); self.assertFalse(out['independent_pre_cutoff_receipt_verified'])
        self.assertFalse(out['forecast_created']); self.assertEqual(out['source_requests'], 0)

    def test_missing_tampered_stale_or_replayed_sources_never_make_a_ready_packet(self):
        for mutation in ('missing', 'body', 'metadata', 'request', 'dom', 'baseline', 'dynamic_replay', 'denial', 'wrong_day', 'case', 'roles'):
            plan, index, files, terms = capture_fixture()
            if mutation == 'missing': files.pop('response-001.body')
            elif mutation == 'body': files['response-001.body'] += b'changed'
            elif mutation == 'metadata':
                meta=json.loads(files['response-001.metadata.json']);meta['fetched_at']=plan['available_after'];files['response-001.metadata.json']=wire(meta)
            elif mutation == 'request': files['request-001.body'] += b'changed'
            elif mutation == 'dom': files['case-01/rendered-dom.html'] += b'changed'
            elif mutation == 'baseline': plan['available_after']=(NOW-timedelta(seconds=20)).isoformat();index['available_after']=plan['available_after']
            elif mutation == 'dynamic_replay': index['ledger'].append(dict(event='DYNAMIC_CACHE_REPLAY', url='https://autorace.jp/race_info/Program'))
            elif mutation == 'denial': index['responses'][0]['status']=403
            elif mutation == 'wrong_day': plan['cases'][0]['expected_date']='2030-01-16'
            elif mutation == 'case': plan['cases'][0]['race_no']=2
            elif mutation == 'roles': index['cases'][0]['responses'][0]['role']='result'
            out = self.build(plan,index,files,terms)
            with self.subTest(mutation=mutation):
                self.assertEqual(out['state'],'HOLD'); self.assertEqual(out['requests'],[]);self.assertIsNone(out['packet'])

    def test_cutoff_margin_and_original_native_contract_are_both_required(self):
        plan,index,files,terms=capture_fixture()
        plan['cases'][0]['cutoff_at']=(NOW+timedelta(minutes=10)).isoformat()
        self.assertEqual(self.build(plan,index,files,terms)['state'],'HOLD')
        plan,index,files,terms=capture_fixture()
        raw=files['response-001.body'].replace(b'Invented Driver 1',b'Unknown Driver 1')
        row=index['responses'][0];row.update(source_sha256=sha256(raw).hexdigest(),byte_count=len(raw))
        files['response-001.body']=raw
        meta=json.loads(files['response-001.metadata.json']);meta.update(source_sha256=row['source_sha256'],byte_count=len(raw));files['response-001.metadata.json']=wire(meta)
        index['ledger'][0]=deepcopy(row);index['cases'][0]['browser_metadata']['ledger'][0]=deepcopy(row)
        self.assertEqual(self.build(plan,index,files,terms)['state'],'HOLD')

    def test_conversion_clock_cannot_precede_capture_or_move_to_the_next_day(self):
        data=capture_fixture()
        for clock in (NOW-timedelta(minutes=1), NOW+timedelta(seconds=1), NOW+timedelta(days=1), NOW.replace(tzinfo=None)):
            with self.subTest(clock=clock):self.assertEqual(self.build(*data,as_of=clock)['state'],'HOLD')

    def test_capture_cannot_expand_the_plan_budget(self):
        plan,index,files,terms=capture_fixture();plan['request_budget']=3
        self.assertEqual(self.build(plan,index,files,terms)['state'],'HOLD')

    def test_optional_expiry_checks_actual_starts_without_retiming_later_body_completion(self):
        data=capture_fixture();original=self.build(*data)
        plan,index,files,terms=data
        plan['not_after']=(NOW-timedelta(seconds=18)).isoformat()
        before=deepcopy(data);out=self.build(*data)
        self.assertEqual(out['state'],'READY_INPUTS_ONLY');self.assertEqual(data,before)
        self.assertEqual(out['packet'],original['packet']);self.assertEqual(out['requests'],original['requests'])
        self.assertEqual(out['fixed_as_of'],NOW.isoformat())
        # The final response completes after expiry. Only its recorded actual
        # request start is authorized; no source or conversion clock is moved.
        self.assertGreater(index['responses'][-1]['body_captured_at'],plan['not_after'])

    def test_expiry_rejects_each_at_or_after_boundary_and_malformed_authorization(self):
        data=capture_fixture()
        expiries=[row['request_started_at'] for row in data[1]['responses']]
        expiries.extend([None,0,'2030-01-15T00:00:00',data[0]['available_after']])
        for expiry in expiries:
            plan,index,files,terms=deepcopy(data);plan['not_after']=expiry
            out=self.build(plan,index,files,terms)
            with self.subTest(expiry=expiry):
                self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[]);self.assertIsNone(out['packet'])

    def test_response_completion_order_does_not_change_request_identity_or_native_input(self):
        data=capture_fixture();first=self.build(*data)
        data[1]['responses'].reverse()
        out=self.build(*data)
        self.assertEqual(out['state'],'READY_INPUTS_ONLY')
        self.assertEqual(out['packet'],first['packet']);self.assertEqual(out['requests'],first['requests'])

    def test_stale_browser_program_identity_cannot_override_the_retained_actual_post(self):
        plan,index,files,terms=capture_fixture()
        actual=index['responses'][0]
        request=wire(dict(placeCode=3,raceDate='2030-01-15',raceNo=2))
        files[actual['request_body_file']]=request
        actual.update(request_body_sha256=sha256(request).hexdigest(),request_identity=json.loads(request))
        metadata=json.loads(files[actual['metadata_file']]);metadata['request_body_sha256']=actual['request_body_sha256']
        files[actual['metadata_file']]=wire(metadata)
        index['ledger'][0]=deepcopy(actual)
        # The stale race-one row has the same response hash/body clock and its
        # request SHA is still present for OtherRaceInfo. It must never win a
        # tie against the retained actual Program race-two request.
        index['cases'][0]['browser_metadata']['ledger'].append(deepcopy(actual))
        out=self.build(plan,index,files,terms)
        self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[]);self.assertIsNone(out['packet'])

    def test_every_browser_numbered_row_must_uniquely_match_a_global_original(self):
        for mutation in ('extra','duplicate','replacement','response_mismatch'):
            plan,index,files,terms=capture_fixture();browser=index['cases'][0]['browser_metadata']['ledger']
            changed=deepcopy(browser[0])
            if mutation=='extra':changed['sequence']=99
            elif mutation=='replacement':changed['request_identity']['raceNo']=2
            elif mutation=='response_mismatch':changed['source_sha256']='f'*64
            browser.append(changed)
            out=self.build(plan,index,files,terms)
            with self.subTest(mutation=mutation):self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[])

    def test_browser_ui_evidence_must_be_an_ordered_projection_of_the_global_ledger(self):
        for mutation in ('missing_global','fabricated','duplicate','reordered'):
            plan,index,files,terms=capture_fixture();browser=index['cases'][1]['browser_metadata']['ledger']
            event=next(entry for entry in browser if entry.get('event')=='NORMAL_SEMANTIC_UI_CLICK')
            if mutation=='missing_global':index['ledger'].remove(event)
            elif mutation=='fabricated':
                invented=deepcopy(event);invented['at']=(NOW-timedelta(seconds=15)).isoformat();browser.append(invented)
            elif mutation=='duplicate':browser.append(deepcopy(event))
            elif mutation=='reordered':browser.reverse()
            out=self.build(plan,index,files,terms)
            with self.subTest(mutation=mutation):self.assertEqual(out['state'],'HOLD');self.assertIsNone(out['packet'])

    def test_adapter_cannot_borrow_another_actual_program_row_outside_selected_roles(self):
        plan,index,files,terms=capture_fixture()
        plan['cases']=plan['cases'][:1];index['cases']=index['cases'][:1]
        index['responses']=index['responses'][:2];index['ledger']=deepcopy(index['responses'])
        browser=index['cases'][0]['browser_metadata']['ledger']
        # Both real Program bodies finish at the same recorded instant. The
        # chosen role points to race two; a valid but unselected race-one row
        # must not be borrowed just because OtherRaceInfo retains its POST SHA.
        completed=(NOW-timedelta(seconds=40)).isoformat()
        first=index['responses'][0];first.update(request_started_at=(NOW-timedelta(seconds=52)).isoformat(),response_received_at=completed,body_captured_at=completed)
        first_meta=json.loads(files[first['metadata_file']]);first_meta.update(fetched_at=first['request_started_at'],response_received_at=completed)
        files[first['metadata_file']]=wire(first_meta)
        index['ledger'][0]=deepcopy(first);browser[0]=deepcopy(first)
        other=deepcopy(first);other.update(sequence=3,request_started_at=(NOW-timedelta(seconds=42)).isoformat(),
            body_file='response-other.body',metadata_file='response-other.metadata.json',request_body_file='request-other.body')
        request=wire(dict(placeCode=3,raceDate='2030-01-15',raceNo=2));other.update(request_body_sha256=sha256(request).hexdigest(),request_identity=json.loads(request))
        files[other['body_file']]=files[first['body_file']];files[other['request_body_file']]=request
        other_meta=deepcopy(first_meta);other_meta.update(fetched_at=other['request_started_at'],request_body_file=other['request_body_file'],request_body_sha256=other['request_body_sha256'])
        files[other['metadata_file']]=wire(other_meta)
        index['responses'].append(other);index['ledger'].append(deepcopy(other));browser.append(deepcopy(other))
        index['actual_request_count']=3;index['cases'][0]['responses'][0]['sequence']=3
        out=self.build(plan,index,files,terms)
        self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[])

    def test_dynamic_data_cannot_be_relabelled_as_static(self):
        plan,index,files,terms=capture_fixture();url='https://keirin.jp/pc/racelist'
        raw=b'<html>old dynamic bootstrap</html>';captured=(NOW-timedelta(days=1)).isoformat()
        plan['static_cache']=[dict(raw_base64=base64.b64encode(raw).decode(),metadata=dict(
            source_url=url,final_url=url,status=200,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
            fetched_at=captured,response_received_at=captured,headers={'content-type':'text/html'},
            http_method='GET',resource_type='script'))]
        index['ledger'].append(dict(event='STATIC_CACHE_REPLAY',url=url,method='GET',resource_type='script',
            source_sha256=sha256(raw).hexdigest(),original_captured_at=captured))
        self.assertEqual(self.build(plan,index,files,terms)['state'],'HOLD')

    def test_fresh_static_asset_may_be_replayed_in_a_later_popup_with_its_original_receipt(self):
        plan,index,files,terms=capture_fixture();raw=b'/* same-run static helper */';url='https://keirin.jp/pc/static/app.js'
        fetched=(NOW-timedelta(seconds=4)).isoformat();completed=(NOW-timedelta(seconds=3)).isoformat()
        row=dict(sequence=5,url=url,method='GET',resource_type='script',status=200,content_type='application/javascript',
                 request_started_at=fetched,response_received_at=completed,body_captured_at=completed,
                 body_file='response-005.body',metadata_file='response-005.metadata.json',byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
        meta=dict(source_url=url,final_url=url,status=200,byte_count=len(raw),source_sha256=row['source_sha256'],
                  fetched_at=fetched,response_received_at=completed,headers={'content-type':'application/javascript'},
                  method='GET',http_method='GET',resource_type='script',ui_capture_kind='NORMAL_BROWSER_UI')
        files[row['body_file']]=raw;files[row['metadata_file']]=wire(meta)
        index['responses'].append(row);index['ledger'].append(deepcopy(row));index['actual_request_count']=5
        index['ledger'].append(dict(event='STATIC_CACHE_REPLAY',url=url,method='GET',resource_type='script',
            source_sha256=row['source_sha256'],original_captured_at=completed,at=(NOW-timedelta(seconds=2)).isoformat()))
        out=self.build(plan,index,files,terms)
        self.assertEqual(out['state'],'READY_INPUTS_ONLY')
        self.assertEqual(out['packet']['cases'][1]['racelive_metadata']['captured_at'],(NOW-timedelta(seconds=10)).isoformat())
        for at in (None, fetched, (NOW+timedelta(seconds=1)).isoformat()):
            changed=deepcopy(index)
            if at is None:changed['ledger'][-1].pop('at')
            else:changed['ledger'][-1]['at']=at
            with self.subTest(replay_at=at):self.assertEqual(self.build(plan,changed,files,terms)['state'],'HOLD')


if __name__ == '__main__': unittest.main()
