"""Invented AUTO result captures, separate from fictional frozen inputs."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import json
import unittest

from race_ai.actions_contract import digest
from race_ai.autorace_official_sparse_adapter import build_requests
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.manual_official_capture import official_rights_ref
from tests.test_autorace_official_sparse_adapter import fixture as input_fixture, wire, NOW as INPUT_AT


JST = timezone(timedelta(hours=9))
NOW = datetime(2030, 1, 15, 12, 5, tzinfo=JST)
RIGHTS = official_rights_ref('autorace')
BASE = 'https://autorace.jp/race_info/'


def encoded(raw):return base64.b64encode(raw).decode()


def fixture():
    source = input_fixture()
    prepared = build_requests(wire(source['program']), wire(source['race']), source['dom'],
        source['metadata'], now=INPUT_AT, source_rights_ref=RIGHTS, request_bodies=source['request_bodies'])
    frozen = next(r['native_payload'] for r in prepared['requests'] if r['cell_key']=='autorace/'+ALL_MODELS[0])
    cars = [3, 4, 6, 5, 7, 2, 8, 1]
    result = dict(result='Success', errors=[], body=dict(
        raceResult=[dict(order=i+1, carNo=car, playerCode=1000+car, playerName=f'Invented Driver {car}',
                         accidentCode=None, accidentName=None, retireFlag=0, foulCode=None)
                    for i,car in enumerate(cars)],
        refundInfo=dict(rt3=dict(typeCode=0, typeName='通常', list=[{
            '1thCarNo':3, '2thCarNo':4, '3thCarNo':6, 'refund':21710, 'pop':97, 'refundVotes':'224'}]), absent=[])))
    request = wire(dict(placeCode=3, raceDate='2030-01-15', raceNo='1'))
    info = deepcopy(source['race']); info['body']['raceNo'] = '1'
    def metadata(raw, endpoint, at):
        return dict(source_url=BASE+endpoint, final_url=BASE+endpoint, status=200, byte_count=len(raw),
            source_sha256=sha256(raw).hexdigest(), fetched_at=(at-timedelta(seconds=1)).isoformat(),
            response_received_at=at.isoformat(), headers={'content-type':'application/json'},
            http_method='POST', ui_capture_kind='NORMAL_BROWSER_UI', request_body_sha256=sha256(request).hexdigest(),
            request_content_type='application/json;charset=UTF-8')
    dom = ('<html><body><h1>伊勢崎 レース結果 2030年 開催 第2日目</h1>'
           '<table class="race-infoTable"><tr><td>1月15日(火)</td><td>予選1R</td><td>3100m</td></tr></table>'
           '<p>投票締切10:58 発走予定11:00</p><h2>レース結果</h2>'
           + ''.join('<p>'+r['playerName']+'</p>' for r in result['body']['raceResult'])
           + '<h2>払戻金</h2><table><tr><th>3連単</th><td>3-4-6</td><td>21,710円</td></tr></table></body></html>').encode()
    raw = wire(result); main = metadata(raw, 'RaceResult', NOW-timedelta(minutes=5))
    context = dict(schema='RACE_AI_AUTORACE_OFFICIAL_RESULT_CONTEXT_V1', request_body_base64=encoded(request),
        race_info_capture=dict(raw_base64=encoded(wire(info)), metadata=metadata(wire(info), 'OtherRaceInfo', NOW-timedelta(minutes=6)),
                               request_body_base64=encoded(request)),
        rendered_dom_capture=dict(raw_base64=encoded(dom), metadata=dict(source_url=BASE+'Live/isesaki',
            final_url=BASE+'Live/isesaki/RaceResult/2030-01-15_1',
            captured_at=(NOW-timedelta(minutes=4)).isoformat(), byte_count=len(dom), source_sha256=sha256(dom).hexdigest())))
    main['auto_result_context'] = context
    unit_raw = '<html><body><p>払戻金は100円に対する金額です。</p></body></html>'.encode()
    main['auto_result_archive_context'] = dict(schema='RACE_AI_AUTORACE_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1',
        payout_unit_capture=dict(raw_base64=encoded(unit_raw), metadata=dict(
            source_url='https://autorace.jp/guide/fixture-payout-unit',
            final_url='https://autorace.jp/guide/fixture-payout-unit', status=200,
            byte_count=len(unit_raw), source_sha256=sha256(unit_raw).hexdigest(),
            fetched_at=(NOW-timedelta(minutes=9)).isoformat(),
            response_received_at=(NOW-timedelta(minutes=8)).isoformat(), headers={'content-type':'text/html;charset=UTF-8'})))
    return dict(result=result, metadata=main, frozen=frozen)


def reseal_result(data):
    raw = wire(data['result'])
    data['metadata'].update(byte_count=len(raw), source_sha256=sha256(raw).hexdigest())


class AutoraceOfficialResultTests(unittest.TestCase):
    def module(self):return importlib.import_module('race_ai.autorace_official_result_adapter')

    def parse(self, data=None):
        data = fixture() if data is None else data
        return self.module().parse_result(wire(data['result']), data['metadata'],
            frozen_native_payload=data['frozen'], now=NOW, source_rights_ref=RIGHTS)

    def test_normal_result_binds_literal_request_frozen_roster_actual_cutoff_and_single_payout(self):
        data = fixture(); before = deepcopy(data); observation = self.parse(data)
        from race_ai.all_existing_model_official_results import OBSERVATION_FIELDS
        self.assertEqual(set(observation), OBSERVATION_FIELDS)
        self.assertEqual((observation['status'], observation['ordered_top3'], observation['payout_per_100_yen']),
                         ('settled', [3,4,6], 21710))
        self.assertEqual(observation['roster'], {str(n):str(1000+n) for n in range(1,9)})
        self.assertTrue(observation['identity_verified'])
        self.assertEqual(observation['captured_at'], data['metadata']['response_received_at'])
        self.assertEqual(observation['closed_at'], '2030-01-15T10:58:00+09:00')
        self.assertEqual(observation['source_sha256'], sha256(wire(data['result'])).hexdigest())
        self.assertIsNone(observation['published_at'])
        self.assertEqual(data, before)

    def test_original_packet_convenience_uses_identical_http_body_and_metadata(self):
        data = fixture()
        result = self.module().parse_result(dict(raw=wire(data['result']), metadata=data['metadata']),
            frozen_native_payload=data['frozen'], now=NOW, source_rights_ref=RIGHTS)
        self.assertEqual(result, self.parse(data))

    def test_ordinary_label_does_not_multiply_popularity_or_winning_ticket_counts(self):
        data = fixture(); row=data['result']['body']['refundInfo']['rt3']['list'][0]
        row.update(pop=999999, refundVotes='999999999');reseal_result(data)
        self.assertEqual(self.parse(data)['payout_per_100_yen'],21710)

    def test_unit_proof_must_explicitly_describe_published_payout_per_100_yen(self):
        for kind in ('missing','minimum_bet_only','fee_only','script_only','wrong_unit','hash','future',
                     'reverse1100','reverse_grouped1100','template_only','head_only','hidden_only',
                     'style_hidden','negated','question','self_closed_template','self_closed_hidden'):
            data=fixture()
            if kind=='missing':data['metadata'].pop('auto_result_archive_context')
            else:
                proof=data['metadata']['auto_result_archive_context']['payout_unit_capture']
                if kind=='minimum_bet_only':raw='<p>車券は100円単位で購入できます。</p>'.encode()
                elif kind=='fee_only':raw='<p>払戻金の手数料は100円あたりの定額です。</p>'.encode()
                elif kind=='script_only':raw='<script>払戻金は100円に対する金額です。</script><p>車券は100円から。</p>'.encode()
                elif kind=='wrong_unit':raw='<p>払戻金は1000円に対する金額です。</p>'.encode()
                elif kind=='reverse1100':raw='<p>1100円あたりの払戻金を表示します。</p>'.encode()
                elif kind=='reverse_grouped1100':raw='<p>1,100円あたりの払戻金を表示します。</p>'.encode()
                elif kind=='template_only':raw='<template>払戻金は100円に対する金額です。</template><p>車券は100円から。</p>'.encode()
                elif kind=='head_only':raw='<html><head><title>払戻金は100円に対する金額です。</title></head><body>車券は100円から。</body></html>'.encode()
                elif kind=='hidden_only':raw='<p hidden>払戻金は100円に対する金額です。</p>'.encode()
                elif kind=='style_hidden':raw='<p style="display: none">払戻金は100円に対する金額です。</p>'.encode()
                elif kind=='negated':raw='<p>払戻金は100円に対する金額ではありません。</p>'.encode()
                elif kind=='question':raw='<p>払戻金は100円に対する金額ですか？</p>'.encode()
                elif kind=='self_closed_template':raw='<template/>払戻金は100円に対する金額です。'.encode()
                elif kind=='self_closed_hidden':raw='<div hidden/>払戻金は100円に対する金額です。'.encode()
                else:raw=base64.b64decode(proof['raw_base64'])
                proof['raw_base64']=encoded(raw);proof['metadata'].update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
                if kind=='hash':proof['metadata']['source_sha256']='f'*64
                if kind=='future':proof['metadata']['response_received_at']=(NOW+timedelta(seconds=1)).isoformat()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.parse(data)

    def test_complete_positive_unit_declarations_accept_direct_reverse_and_fullwidth_text(self):
        for text in ('払戻金は100円に対する金額です。','100円あたりの払戻金を表示します。',
                     '払戻金は１００円に対する金額です。'):
            data=fixture();proof=data['metadata']['auto_result_archive_context']['payout_unit_capture']
            raw=('<p>'+text+'</p>').encode();proof['raw_base64']=encoded(raw)
            proof['metadata'].update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
            with self.subTest(text=text):self.assertEqual(self.parse(data)['status'],'settled')

    def test_unscored_pending_and_special_sources_do_not_require_a_unit_claim(self):
        for kind in ('pending','special'):
            data=fixture();data['metadata'].pop('auto_result_archive_context')
            if kind=='pending':data['result']['body']['raceResult']=[]
            else:data['result']['body']['refundInfo']['absent']=[8]
            reseal_result(data)
            with self.subTest(kind=kind):self.assertIn(self.parse(data)['status'],('pending','special'))

    def test_result_before_cutoff_future_capture_hash_and_wrong_roster_reject(self):
        for kind in ('before_cutoff','future','hash','id','duplicate'):
            data=fixture()
            if kind=='before_cutoff':
                data['metadata']['fetched_at']='2030-01-15T10:56:00+09:00';data['metadata']['response_received_at']='2030-01-15T10:57:00+09:00'
            elif kind=='future':data['metadata']['response_received_at']=(NOW+timedelta(seconds=1)).isoformat()
            elif kind=='hash':data['metadata']['source_sha256']='f'*64
            elif kind=='id':data['result']['body']['raceResult'][0]['playerCode']=9999;reseal_result(data)
            else:data['result']['body']['raceResult'][1]['carNo']=3;reseal_result(data)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.parse(data)

    def test_missing_or_rehashed_wrong_request_date_venue_and_race_reject(self):
        for kind in ('missing','day','venue','race'):
            data=fixture();context=data['metadata']['auto_result_context']
            if kind=='missing':context.pop('request_body_base64')
            else:
                request=dict(placeCode=3,raceDate='2030-01-15',raceNo='1')
                if kind=='day':request['raceDate']='2030-01-14'
                elif kind=='venue':request['placeCode']=2
                else:request['raceNo']='2'
                raw=wire(request);context['request_body_base64']=encoded(raw)
                data['metadata']['request_body_sha256']=sha256(raw).hexdigest()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.parse(data)

    def test_companion_clock_cutoff_or_rendered_race_cannot_be_substituted(self):
        for kind in ('companion_clock','cutoff','dom'):
            data=fixture();context=data['metadata']['auto_result_context']
            if kind=='companion_clock':context['race_info_capture']['metadata']['response_received_at']=NOW.isoformat()
            elif kind=='cutoff':
                capture=context['race_info_capture'];info=json.loads(base64.b64decode(capture['raw_base64']));info['body']['telvoteTime']='10:59'
                raw=wire(info);capture['raw_base64']=encoded(raw);capture['metadata'].update(source_sha256=sha256(raw).hexdigest(),byte_count=len(raw))
            else:
                capture=context['rendered_dom_capture'];raw=base64.b64decode(capture['raw_base64']).replace(b'1R',b'2R')
                capture['raw_base64']=encoded(raw);capture['metadata'].update(source_sha256=sha256(raw).hexdigest(),byte_count=len(raw))
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.parse(data)

    def test_pending_result_never_becomes_a_normal_label(self):
        data=fixture();body=data['result']['body'];body['raceResult']=[];body['refundInfo']['rt3']['list']=[];reseal_result(data)
        observation=self.parse(data)
        self.assertEqual(observation['status'],'pending')
        self.assertEqual(observation['ordered_top3'],[])
        self.assertIsNone(observation['payout_per_100_yen'])
        self.assertFalse(observation['identity_verified'])

    def test_refund_dead_heat_nonfinish_cancellation_and_special_payout_stay_distinct(self):
        reasons=set()
        for kind in ('refund','dead_heat','nonfinish','cancelled','special','no_vote'):
            data=fixture();body=data['result']['body'];trifecta=body['refundInfo']['rt3']
            if kind=='refund':body['refundInfo']['absent']=[8]
            elif kind=='dead_heat':body['raceResult'][1]['order']=1
            elif kind=='nonfinish':body['raceResult'][-1].update(order=None,accidentCode=1,accidentName='落')
            elif kind=='cancelled':body['raceResult']=[];trifecta.update(typeCode=2,typeName='競走中止',list=[])
            elif kind=='special':trifecta.update(typeCode=1,typeName='特払い')
            else:trifecta.update(typeCode=5,typeName='無投票')
            reseal_result(data);observation=self.parse(data);reasons.add(observation['reason'])
            with self.subTest(kind=kind):
                self.assertEqual(observation['status'],'special')
                self.assertEqual(observation['ordered_top3'],[])
                self.assertIsNone(observation['payout_per_100_yen'])
            if kind=='refund':self.assertEqual(observation['refund_numbers'],[8])
        self.assertEqual(len(reasons),6)

    def test_payout_must_be_single_positive_normal_record_matching_actual_finishes(self):
        for kind in ('multiple','wrong_combo','negative','boolean'):
            data=fixture();rows=data['result']['body']['refundInfo']['rt3']['list']
            if kind=='multiple':rows.append(deepcopy(rows[0]))
            elif kind=='wrong_combo':rows[0]['1thCarNo']=2
            elif kind=='negative':rows[0]['refund']=-100
            else:rows[0]['refund']=True
            reseal_result(data)
            with self.subTest(kind=kind):
                if kind=='multiple':self.assertEqual(self.parse(data)['status'],'special')
                else:
                    with self.assertRaises(ValueError):self.parse(data)


if __name__=='__main__':unittest.main()
