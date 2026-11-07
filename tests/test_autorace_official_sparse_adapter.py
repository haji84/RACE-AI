"""Invented normal-browser responses; no real providers, keys or accuracy claim."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import json
import math
import unittest

from race_ai import all_existing_model_registry as registry
from race_ai.autorace_personal_baseline import MODEL_ID as PERSONAL
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.manual_official_capture import official_rights_ref


JST = timezone(timedelta(hours=9))
NOW = datetime(2030, 1, 15, 9, 15, tzinfo=JST)
RIGHTS = official_rights_ref('autorace')
BASE = 'https://autorace.jp/race_info/'


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def fixture():
    players = [dict(carNo=n, playerCode=1000+n, playerName=f'Invented Driver {n}',
                    handicap=(n-1)*10, trialRunTime='', retireFlag=0, absent=None,
                    rate2='not used', rate3='not used') for n in range(1, 9)]
    histories = {}
    for p in players:
        histories[str(p['playerCode'])] = [dict(
            raceDate=f'2030-01-{14-i:02d}', placeCode=3, placeKey='isesaki', raceNo=i+1,
            order=1+(p['carNo']+i)%8, accidentName=None, materializedName=None)
            for i in range(10)]
    program = dict(result='Success', errors=[], body=dict(playerList=players,
        latest3List={key: deepcopy(rows[:3]) for key, rows in histories.items()},
        latest10List=histories, unusedMarketStatistics={'not copied': True}))
    race = dict(result='Success', errors=[], body=dict(placeCode=3, placeKey='isesaki',
        placeName='伊勢崎', raceNo=1, periodStartDate='2030-01-14', periodEndDate='2030-01-17',
        paragraphday=2, distance=3100, raceStartTime='11:00', telvoteTime='10:58', classCode=1))
    dom = ('<html><body><h2>伊勢崎 開催期間:2030年1月14日～17日 開催 第2日目</h2>'
           '<table class="race-infoTable"><tr><td>1月15日(火)</td><td>予選1R</td>'
           '<td>3100m</td></tr></table><div>投票締切10:58 発走予定11:00</div>'
           + ''.join('<a>'+p['playerName']+'</a>' for p in players) + '</body></html>').encode()
    request = wire(dict(placeCode=3, raceDate='2030-01-15', raceNo=1))
    body_hash = sha256(request).hexdigest()
    raw = [wire(program), wire(race)]
    ledger = [dict(sequence=i+1, url=BASE+path, method='POST', resource_type='xhr', status=200,
        request_started_at=(NOW-timedelta(seconds=40-i*10)).isoformat(),
        response_received_at=(NOW-timedelta(seconds=35-i*10)).isoformat(),
        body_captured_at=(NOW-timedelta(seconds=30-i*10)).isoformat(),
        source_sha256=sha256(raw[i]).hexdigest(), byte_count=len(raw[i]),
        content_type='application/json',
        request_body_sha256=body_hash, request_content_type='application/json;charset=UTF-8')
        for i, path in enumerate(('Program', 'OtherRaceInfo'))]
    metadata = dict(schema='RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1', scope='SYNTHETIC_ONLY',
        ui_capture_kind='NORMAL_BROWSER_UI', source_url=BASE+'Live/isesaki',
        final_url=BASE+'Live/isesaki', started_at=(NOW-timedelta(seconds=45)).isoformat(),
        captured_at=(NOW-timedelta(seconds=10)).isoformat(), stopped_host=False,
        rendered_dom=dict(byte_count=len(dom), source_sha256=sha256(dom).hexdigest()), ledger=ledger)
    return dict(program=program, race=race, dom=dom, metadata=metadata,
                request_bodies={body_hash: request})


def reseal_source(data, field):
    index = ('program', 'race').index(field)
    encoded = wire(data[field])
    data['metadata']['ledger'][index].update(source_sha256=sha256(encoded).hexdigest(), byte_count=len(encoded))


class AutoraceOfficialSparseAdapterTests(unittest.TestCase):
    def build(self, data=None, *, now=NOW, **kwargs):
        module = importlib.import_module('race_ai.autorace_official_sparse_adapter')
        data = fixture() if data is None else data
        return module.build_requests(wire(data['program']), wire(data['race']), data['dom'],
            data['metadata'], now=now, source_rights_ref=RIGHTS,
            request_bodies=data['request_bodies'], **kwargs)

    def test_six_native_input_requests_preserve_actual_facts_without_fabricated_ratings(self):
        data = fixture(); before = deepcopy(data)
        converted = self.build(data)
        self.assertEqual(converted['state'], 'READY')
        requests = {r['cell_key']: r['native_payload'] for r in converted['requests']}
        self.assertEqual(set(requests), {'autorace/'+mid for mid in (*ALL_MODELS, LEARNED_ID, PERSONAL)})
        self.assertEqual(data, before)
        self.assertFalse(converted['independent_pre_cutoff_receipt_verified'])
        self.assertFalse(converted['provider_model_training_permission_confirmed'])
        self.assertEqual(converted['phase_states']['B_POST_TRIAL']['state'], 'HOLD')
        personal = requests['autorace/'+PERSONAL]
        self.assertEqual(personal['snapshot']['race']['phase'], 'A_PRE_TRIAL')
        self.assertEqual(personal['snapshot']['race']['as_of_at'], NOW.isoformat())
        self.assertEqual(personal['snapshot']['race']['sales_cutoff_at'], '2030-01-15T10:58:00+09:00')
        self.assertEqual(personal['registered_roster']['roster'], {str(n):str(1000+n) for n in range(1, 9)})
        for driver in personal['snapshot']['drivers']:
            self.assertEqual(driver['handicap_m'], (driver['car_no']-1)*10)
            self.assertEqual(len(driver['recent_finishes']), 10)
            self.assertIsNone(driver['trial_seconds'])
        prediction = registry.predict(PERSONAL, 'autorace', personal, at=NOW, allow_source=lambda *_:True)
        self.assertEqual(prediction['candidate_count'], math.perm(8, 3))

    def test_shared_optional_top3_event_fractions_are_source_bound_observations(self):
        data = fixture(); converted = self.build(data)
        self.assertEqual(converted['state'], 'READY')
        for request in converted['requests']:
            if request['cell_key'] == 'autorace/'+PERSONAL:
                continue
            payload = request['native_payload']; snapshot = payload['snapshot']
            self.assertEqual(payload['stage'], 'P0')
            self.assertEqual(snapshot['race']['as_of'], NOW.isoformat())
            self.assertEqual(snapshot['race']['distance_m'], 3100)
            self.assertEqual(snapshot['environment'], {})
            for participant in snapshot['participants']:
                self.assertEqual(set(participant['features']), {'recent_form_3race', 'recent_form_10race'})
                self.assertIn('ability', participant['missing'])
                self.assertIn('recent_form', participant['missing'])
                self.assertIn('handicap_advantage', participant['missing'])
                for length in (3, 10):
                    name = f'recent_form_{length}race'; observed = participant['features'][name]
                    rows = data['program']['body'][f'latest{length}List'][participant['identity']]
                    self.assertEqual(observed['value'], sum(r['order']<=3 for r in rows)/length)
                    self.assertEqual(observed['sample_n'], length)
                    self.assertEqual(observed['transform_id'],
                                     f'official-prior-normal-top3-finish-fraction-last{length}-v1')
                    self.assertEqual(observed['source_sha256'], data['metadata']['ledger'][0]['source_sha256'])
                    self.assertIsNone(observed['published_at'])
            if request['cell_key'] != 'autorace/'+LEARNED_ID:
                prediction = registry.predict(request['cell_key'].split('/', 1)[1], 'autorace', payload,
                                              at=NOW, allow_source=lambda *_:True)
                self.assertEqual(prediction['candidate_count'], math.perm(8, 3))
            else:
                self.assertNotIn('learned_model', payload)

    def test_missing_exact_request_bytes_holds_every_cell(self):
        data = fixture(); data['request_bodies'] = {}
        self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_normal_ui_history_url_binds_the_same_date_and_race(self):
        data = fixture()
        data['metadata']['final_url'] += '/Program/2030-01-15_1/program'
        self.assertEqual(self.build(data)['state'], 'READY')
        data['metadata']['final_url'] = BASE+'Live/isesaki/Program/2030-01-15_2/program'
        self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_response_mime_boolean_race_number_and_wrong_month_do_not_bind_a_case(self):
        for kind in ('mime', 'boolean', 'month'):
            data = fixture()
            if kind == 'mime':data['metadata']['ledger'][0]['content_type'] = 'text/html'
            elif kind == 'boolean':data['race']['body']['raceNo'] = True;reseal_source(data, 'race')
            else:
                data['dom'] = data['dom'].replace('1月15日'.encode(), '11月15日'.encode())
                data['metadata']['rendered_dom'].update(byte_count=len(data['dom']), source_sha256=sha256(data['dom']).hexdigest())
            with self.subTest(kind=kind):self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_matching_request_hash_cannot_substitute_wrong_race_day_or_venue(self):
        for field, value in (('raceNo', 2), ('raceDate', '2030-01-14'), ('placeCode', 4)):
            data = fixture(); body = dict(placeCode=3, raceDate='2030-01-15', raceNo=1); body[field] = value
            encoded = wire(body); identity = sha256(encoded).hexdigest()
            data['request_bodies'] = {identity: encoded}
            for item in data['metadata']['ledger']:item['request_body_sha256'] = identity
            with self.subTest(field=field):
                self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_source_hash_clocks_permission_and_rendered_identity_fail_closed(self):
        mutations = (
            lambda d: d['metadata']['ledger'][0].update(source_sha256='f'*64),
            lambda d: d['metadata'].update(captured_at=(NOW+timedelta(seconds=1)).isoformat()),
            lambda d: d['metadata']['ledger'][0].update(status=403),
            lambda d: d['metadata'].update(ui_capture_kind='DIRECT_API'),
            lambda d: d['metadata'].update(final_url='https://example.test/race'),
            lambda d: d['metadata']['ledger'][0].update(url='https://api.autorace.jp/race_info/Program'),
        )
        for mutate in mutations:
            data = fixture(); mutate(data)
            self.assertEqual(self.build(data)['state'], 'HOLD')
        data = fixture(); data['dom'] = data['dom'].replace(b'1R', b'2R')
        data['metadata']['rendered_dom'].update(byte_count=len(data['dom']), source_sha256=sha256(data['dom']).hexdigest())
        self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_duplicate_car_or_stable_driver_id_and_unconfirmed_roster_hold(self):
        for field in ('carNo', 'playerCode'):
            data = fixture(); players = data['program']['body']['playerList']; players[1][field] = players[0][field]
            reseal_source(data, 'program')
            with self.subTest(field=field):self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_future_same_day_and_invalid_history_dates_never_enter_features(self):
        for event in ('2030-01-15', '2030-01-16', 'invalid'):
            data = fixture()
            for length in (3, 10):data['program']['body'][f'latest{length}List']['1001'][0]['raceDate'] = event
            reseal_source(data, 'program')
            with self.subTest(event=event):self.assertEqual(self.build(data)['state'], 'HOLD')

    def test_special_history_is_excluded_with_actual_denominators_and_audit(self):
        data = fixture()
        for length in (3, 10):
            row = data['program']['body'][f'latest{length}List']['1001'][0]
            row.update(order='F', accidentName='反則')
        reseal_source(data, 'program'); converted = self.build(data)
        shared = next(r['native_payload'] for r in converted['requests'] if r['cell_key']=='autorace/'+ALL_MODELS[0])
        participant = shared['snapshot']['participants'][0]
        self.assertEqual(participant['features']['recent_form_3race']['sample_n'], 2)
        self.assertEqual(participant['features']['recent_form_10race']['sample_n'], 9)
        line = shared['adapter_lineage']['participants'][0]['windows']['10']
        self.assertEqual((line['source_rows'], line['normal_rows'], line['excluded_rows']), (10, 9, 1))
        personal = next(r['native_payload'] for r in converted['requests'] if r['cell_key']=='autorace/'+PERSONAL)
        self.assertEqual(len(personal['snapshot']['drivers'][0]['recent_finishes']), 9)

    def test_no_normal_history_is_missing_and_does_not_become_an_observed_zero(self):
        data = fixture()
        for length in (3, 10):
            for row in data['program']['body'][f'latest{length}List']['1001']:
                row.update(order='F', accidentName='反則')
        reseal_source(data, 'program'); converted = self.build(data)
        self.assertEqual(converted['requests'], [])
        self.assertTrue(all(v['state']=='HOLD' for v in converted['model_states'].values()))

    def test_observed_zero_event_fraction_keeps_its_nonzero_sample_support(self):
        data = fixture()
        for length in (3, 10):
            for row in data['program']['body'][f'latest{length}List']['1001']:row['order'] = 8
        reseal_source(data, 'program'); converted = self.build(data)
        shared = next(r['native_payload'] for r in converted['requests'] if r['cell_key']=='autorace/'+ALL_MODELS[0])
        observed = shared['snapshot']['participants'][0]['features']['recent_form_10race']
        self.assertEqual((observed['value'], observed['sample_n']), (0, 10))

    def test_six_requests_pass_existing_native_capsule_and_direct_source_contracts(self):
        from race_ai.all_existing_model_inputs import _additional_source_pairs
        from race_ai.all_existing_model_pairs import _native_input
        converted = self.build(); known = {cell['cell_key']:cell for cell in registry.cells()}
        expected_refs = set(map(tuple, converted['source_refs']))
        self.assertEqual(len(converted['requests']), 6)
        for request in converted['requests']:
            payload = request['native_payload']
            with self.subTest(cell=request['cell_key']):
                self.assertEqual(_additional_source_pairs(payload, as_of=NOW.isoformat()), expected_refs)
                capsule, info, sport = _native_input(request['cell_key'], payload, known, now=NOW,
                    allow_source=lambda ref,right,purpose:purpose=='analysis' and (ref,right) in expected_refs)
                self.assertEqual(sport, 'autorace')
                self.assertEqual(info['roster'], {str(n):str(1000+n) for n in range(1, 9)})
                self.assertEqual(capsule['captured_as_of'], NOW.isoformat())

    def test_existing_baseline_ranker_is_optional_but_wrong_clock_and_tampering_hold(self):
        from race_ai.four_sport_learning import fit_training_only
        from race_ai.observed_weight_learning import seal
        from tests.test_nonboat_sparse_contracts import training_rows
        baseline = fit_training_only(training_rows('autorace'), sport='autorace', epochs=2,
            train_end_at='2030-01-06T12:00:00+09:00',
            now=lambda:datetime.fromisoformat('2030-01-07T12:00:00+09:00'))
        converted = self.build(baseline_ranker=baseline)
        self.assertEqual(converted['state'], 'READY')
        payload = next(r['native_payload'] for r in converted['requests'] if r['cell_key']=='autorace/'+LEARNED_ID)
        self.assertEqual(payload['learned_model'], baseline)
        for kind in ('future', 'tamper', 'other_sport'):
            bad = deepcopy(baseline)
            if kind == 'future':bad['created_at'] = (NOW+timedelta(seconds=1)).isoformat();seal(bad, 'model_sha256')
            elif kind == 'tamper':bad['weights'][0] += 1
            else:bad['sport'] = 'keirin';seal(bad, 'model_sha256')
            with self.subTest(kind=kind):self.assertEqual(self.build(baseline_ranker=bad)['state'], 'HOLD')

    def test_actual_trial_prevents_new_pre_trial_a_and_late_clock_holds_all_inputs(self):
        data = fixture(); data['program']['body']['playerList'][0]['trialRunTime'] = '3.42'
        reseal_source(data, 'program'); converted = self.build(data)
        self.assertEqual(converted['model_states']['autorace/'+PERSONAL]['state'], 'HOLD')
        self.assertNotIn('autorace/'+PERSONAL, {r['cell_key'] for r in converted['requests']})
        self.assertEqual(self.build(now=NOW.replace(hour=10, minute=56))['state'], 'HOLD')


if __name__ == '__main__':
    unittest.main()
