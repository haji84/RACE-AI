"""Synthetic source bindings only; no live data or network in regressions."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_keirin_official_sp_receipt import (
    AT, DAY, calendar_receipt, detail_data, html, list_data,
)


class CanaryCardTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_official_canary_card'),
                             'CANARY_CARD_MODULE_REQUIRED')
        return importlib.import_module('race_ai.keirin_official_canary_card')

    def args(self):
        listing = list_data()
        listing['SJ0301']['kaisaiDayList'][1]['raceProgramList'][0]['strSyumokuName'] = 'Ｌ級ガールズ予選'
        detail = detail_data()
        for rider in detail['SJ0315']['sensyuTypeInfo']:
            rider['kyuhan'] = 'Ｌ級１班'
            rider['heikinTokuten'] = '51.25'
        lr, dr = html(listing), html(detail)
        return dict(list_raw=lr, detail_raw=dr, expected_day=DAY,
                    venue_code=98, race_number=1, calendar_receipt=calendar_receipt(),
                    list_observed_at=AT+timedelta(seconds=1),
                    detail_observed_at=AT+timedelta(seconds=2),
                    list_sha256=sha256(lr).hexdigest(), detail_sha256=sha256(dr).hexdigest(),
                    now=AT+timedelta(seconds=3), minimum_margin_seconds=390)

    def prediction_fixture(self):
        args = self.args()
        data = detail_data()
        for row in data['SJ0315']['sensyuTypeInfo']:
            row['kyuhan'] = 'L1'
        data['SC0201']['C0201data']['encSelParaR'] = 'C'*64
        data['SJ0314'] = dict(resultCd=0, narabiyoso=dict(
            lineKeitai='ライン無し', lineKeitaiClass='noline', ryoikiFlg='true',
            errFlg='false', teikyo='架空紙',
            shaban=[dict(shaban=str(n), ichi=str(n)) for n in range(1, 8)]))
        scripts = {
            '/sp/static/js/FSJ0315.js': b'''wk0201Data=jsonData["SC0201"].C0201data;
gPrmParaR=wk0201Data.encSelParaR; para=gPrmParaR; update(dispId,para,sKbn);
wkObj["encp"]=para; wkSyoriKbn=displayingSyoriKbn; wkObj["skbn"]=wkSyoriKbn;
gReqPrmsObject[dispId]=wkObj; case 'SJ0321': return ryController.JSON_REQ_ID;
var reqID=getReqID(key); Com.getRequestGet(reqID,gReqPrmsObject[key]);''',
            '/sp/static/js/SJ0321_c.js': b'''var ryController={JSON_REQ_ID:"JSJ041",
ryCreateList:function(params){Com.getRequestGet(ryController.JSON_REQ_ID,params);}};''',
            '/sp/static/js/commonJSON.js': b'''url:location.protocol+'//'+location.host+'/'+$($('script[src$="commonJSON.js"]')[0]).attr('src').split('/')[1]+'/json',
ajaxCfgG:{type:'get'},getRequestGet:function(reqType,para){return com.getRequestMain(reqType,para,true);},
if(flgType){$.ajaxSetup(cfg.ajaxCfgG);}params=para;params.type=reqType;$.ajax({data:params,dataType:'json'});''',
            '/sp/static/js/SJ0321_v.js': b'''ryDataChecker(sensyuTypeInfo.yosoin);ryDataChecker(sensyuTypeInfo.sensyuComment);
function ryDataChecker(str){var ret;if(str == undefined || str == null){ret="";}else{ret=str;}return ret;}''',
        }
        dr = html(data).replace(b'var jsonData', b'var displayingSyoriKbn = 1; var jsonData')
        extra = '<button onclick="btnClickOfFrame(\'SJ0321\')">予想情報</button>'
        extra += ''.join('<script src="'+path+'"></script>' for path in scripts)
        dr = dr.replace(b'</body>', extra.encode()+b'</body>')
        args['detail_raw'], args['detail_sha256'] = dr, sha256(dr).hexdigest()
        payload = dict(resultCd=0, syusouInfoExistFlg='1', bKeirinjyoCd='98',
            yosoinMei='架空紙', senComMei='架空紙',
            lastUpdateTime='2030/01/15 10:00&nbsp;更新', sensyuTypeInfo=[])
        for n, rider in enumerate(data['SJ0315']['sensyuTypeInfo'], 1):
            row = {key: rider[key] for key in ('syaban', 'sensyuRegistNo', 'sensyuName')}
            row['sensyuComment'] = '架空コメント'
            if n < 5:
                row['yosoin'] = ['◎', '○', '▲', '×'][n-1]
            payload['sensyuTypeInfo'].append(row)
        raw = json.dumps(payload, ensure_ascii=False).encode()
        return args, scripts, raw

    def parse_prediction_fixture(self, args=None, scripts=None, raw=None, **changes):
        default_args, default_scripts, default_raw = self.prediction_fixture()
        args = args or default_args
        scripts = default_scripts if scripts is None else scripts
        raw = default_raw if raw is None else raw
        api = self.api()
        self.assertTrue(hasattr(api, 'derive_prediction_tab_request'), 'PUBLIC_TAB_DERIVATION_REQUIRED')
        request = api.derive_prediction_tab_request(args['detail_raw'], scripts)
        parameters = dict(raw_bytes=raw, expected_sha256=sha256(raw).hexdigest(),
            observed_at=AT+timedelta(seconds=4), now=AT+timedelta(seconds=5),
            card=api.parse_canary_card(**args), detail_raw=args['detail_raw'],
            scripts=scripts, request_url=request['url'])
        parameters.update(changes)
        return api.parse_prediction_tab(**parameters)

    def test_public_marks_comments_bind_registration_and_actual_blank_cells(self):
        result = self.parse_prediction_fixture()
        self.assertEqual([r['mark_rank'] for r in result['riders']],
                         [1, 2, 3, 4, 'UNMARKED', 'UNMARKED', 'UNMARKED'])
        self.assertEqual(result['riders'][4]['mark_field_presence'], 'ABSENT_RENDERED_BLANK')
        self.assertEqual(result['riders'][0]['comment_raw'], '架空コメント')
        self.assertEqual(result['publisher_updated_at'], '2030-01-15T10:00:00+09:00')
        self.assertTrue(result['marks_source_verified'])
        self.assertFalse(result['independent_origin_attested'])

    def test_public_marks_wrong_registration_rejected(self):
        args, scripts, raw = self.prediction_fixture()
        payload = json.loads(raw)
        payload['sensyuTypeInfo'][0]['sensyuRegistNo'] = '998888'
        with self.assertRaisesRegex(ValueError, 'PREDICTION_ROSTER_MISMATCH'):
            self.parse_prediction_fixture(args, scripts, json.dumps(payload).encode())

    def test_public_marks_missing_view_proof_cannot_manufacture_unmarked(self):
        args, scripts, raw = self.prediction_fixture()
        scripts['/sp/static/js/SJ0321_v.js'] = b'ryDataChecker(sensyuTypeInfo.yosoin);'
        with self.assertRaisesRegex(ValueError, 'PUBLIC_TAB_SCRIPT_CHANGED'):
            self.parse_prediction_fixture(args, scripts, raw)

    def test_public_marks_unrelated_request_is_not_same_race(self):
        with self.assertRaisesRegex(ValueError, 'PUBLIC_TAB_REQUEST_MISMATCH'):
            self.parse_prediction_fixture(request_url='https://keirin.jp/sp/json?type=OTHER')

    def test_public_marks_late_capture_not_admitted(self):
        with self.assertRaisesRegex(ValueError, 'FUTURE_CUTOFF_MARGIN_REQUIRED'):
            self.parse_prediction_fixture(observed_at=AT+timedelta(hours=2),
                                          now=AT+timedelta(hours=2))

    def test_public_marks_unknown_glyph_rejected(self):
        args, scripts, raw = self.prediction_fixture()
        payload = json.loads(raw)
        payload['sensyuTypeInfo'][0]['yosoin'] = '謎'
        with self.assertRaises(ValueError):
            self.parse_prediction_fixture(args, scripts, json.dumps(payload).encode())

    def test_observed_no_fixed_line_preserves_six_or_seven_individuals(self):
        args, _, _ = self.prediction_fixture()
        card = self.api().parse_canary_card(**args)
        self.assertEqual(card['line_prediction']['groups'], [[n] for n in range(1, 8)])
        self.assertEqual(card['line_prediction']['kind'], 'NO_FIXED_LINE')

    def test_binds_official_registration_and_cutoff_without_fabricating_marks(self):
        card = self.api().parse_canary_card(**self.args())
        self.assertEqual(card['race_id'], '203001159801')
        self.assertEqual(card['official_cutoff_at'], '2030-01-15T12:47:00+09:00')
        self.assertEqual([r['registration_id'] for r in card['riders']],
                         [f'99{n:04d}' for n in range(1, 8)])
        self.assertEqual(card['competition'], 'GIRLS')
        self.assertFalse(card['prediction_input_complete'])
        self.assertIn('MARKS_SOURCE_UNCONFIRMED', card['missing_inputs'])
        self.assertIn('FOUR_MONTH_WIN_RATE_UNCONFIRMED', card['missing_inputs'])
        self.assertIn('HOME_COUNT_UNCONFIRMED', card['missing_inputs'])
        self.assertNotIn('mark_rank', card['riders'][0])
        self.assertNotIn('UNMARKED', str(card))
        self.assertEqual(card['source_sha256'], self.args()['detail_sha256'])

    def test_other_day_girls_label_does_not_relabel_current_mens_race(self):
        args = self.args()
        listing = list_data()
        listing['SJ0301']['kaisaiDayList'][0]['raceProgramList'][0]['strSyumokuName'] = 'Ｌ級ガールズ予選'
        args['list_raw'] = html(listing)
        args['list_sha256'] = sha256(args['list_raw']).hexdigest()
        with self.assertRaisesRegex(ValueError, 'GIRLS_CLASS_NOT_OBSERVED'):
            self.api().parse_canary_card(**args)

    def test_current_girls_label_cannot_override_mens_roster(self):
        args = self.args()
        detail = detail_data()
        for rider in detail['SJ0315']['sensyuTypeInfo']:
            rider['kyuhan'] = 'Ｓ級１班'
        args['detail_raw'] = html(detail)
        args['detail_sha256'] = sha256(args['detail_raw']).hexdigest()
        with self.assertRaisesRegex(ValueError, 'GIRLS_ROSTER_NOT_OBSERVED'):
            self.api().parse_canary_card(**args)

    def test_published_short_l1_class_with_six_riders_is_supported(self):
        args = self.args()
        detail = detail_data(6)
        for rider in detail['SJ0315']['sensyuTypeInfo']:
            rider['kyuhan'] = 'L1'
        args['detail_raw'] = html(detail)
        args['detail_sha256'] = sha256(args['detail_raw']).hexdigest()
        card = self.api().parse_canary_card(**args)
        self.assertEqual(len(card['riders']), 6)
        self.assertEqual(card['competition'], 'GIRLS')

    def test_late_clock_is_not_a_future_race(self):
        args = self.args()
        args['now'] = AT+timedelta(hours=2)
        with self.assertRaisesRegex(ValueError, 'FUTURE_CUTOFF_MARGIN_REQUIRED'):
            self.api().parse_canary_card(**args)

    def test_withdrawn_rider_is_not_silently_dropped(self):
        args = self.args()
        data = detail_data()
        for rider in data['SJ0315']['sensyuTypeInfo']:
            rider['kyuhan'] = 'Ｌ級１班'
        data['SJ0315']['sensyuTypeInfo'][0]['ketujyouTuikaHojyu'] = '欠場'
        args['detail_raw'] = html(data)
        args['detail_sha256'] = sha256(args['detail_raw']).hexdigest()
        with self.assertRaisesRegex(ValueError, 'ROSTER_EXCLUSION_UNRESOLVED'):
            self.api().parse_canary_card(**args)

    def test_changed_bytes_without_new_sha_are_rejected(self):
        args = self.args()
        args['detail_raw'] += b' '
        with self.assertRaises(ValueError):
            self.api().parse_canary_card(**args)

    def test_only_current_girls_numbers_are_selected(self):
        api = self.api()
        args = self.args()
        rows = api.girls_candidates(args['list_raw'], expected_day=DAY,
            expected_venue_code=98, observed_at=args['list_observed_at'],
            expected_sha256=args['list_sha256'], calendar_receipt=args['calendar_receipt'])
        self.assertEqual([r['race_no'] for r in rows], [1])

    def test_public_form_capture_saves_source_bound_card_with_missing_marks(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'collect_canary_card_http'), 'PUBLIC_FORM_CAPTURE_REQUIRED')
        args = self.args()
        from tests.test_keirin_official_sp_browser import calendar_html
        responses = {
            '/sp/raceschedule': calendar_html(venues=(98,)).replace(b'</body>',
                b'<script src="/sp/static/js/SJ0201.js"></script><script src="/sp/static/js/commonSubmit.js"></script></body>'),
            '/sp/static/js/SJ0201.js': b'params["encp"]=encp; params["disp"]="SJ0301"; commonSubmit.formPost(next,params,null);',
            '/sp/static/js/commonSubmit.js': b'$form.attr("action",actn).attr("method","post");',
            '/sp/racelist': args['list_raw'].replace(b'</body>',
                b'<script src="/sp/static/js/SJ0301_c.js"></script><script src="/sp/static/js/SJ0301_v.js"></script></body>'),
            '/sp/static/js/SJ0301_c.js': b'var action=$(children[1]).attr("value");params["encp"]=$(children[2]).attr("value");if(dispDI==1){dispDI="SJ0315";}params["disp"]=dispDI;commonSubmit.formPost(action,params);',
            '/sp/static/js/SJ0301_v.js': b'raceProgram.strRaceLnk;raceProgram.strRaceLnkPrm;raceProgram.strRaceLnkKbn;',
            '/sp/race': args['detail_raw'],
        }
        from urllib.parse import urlsplit
        calls = []
        def request(url, fields=None, referer=None):
            calls.append((url, fields))
            return dict(status=200, url=url, raw=responses[urlsplit(url).path], observed_at=AT)
        with tempfile.TemporaryDirectory() as folder:
            report = api.collect_canary_card_http(folder, venue_code=98, race_number=1,
                                                  request=request, clock=lambda: AT,
                                                  include_prediction_tab=False)
            cards = []
            for path in Path(folder).glob('*.json'):
                data = json.loads(path.read_text())
                if data.get('schema') == api.SCHEMA:
                    cards.append(data)
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]['race_id'], '203001159801')
            self.assertFalse(cards[0]['prediction_input_complete'])
            self.assertTrue(report['canary_card_saved'])
            self.assertEqual([x[1] for x in calls if x[1]],
                             [[('encp', 'A'*43), ('disp', 'SJ0301')],
                              [('encp', 'B'*43), ('disp', 'SJ0315')]])

    def test_public_form_denial_stops_without_retry(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'collect_canary_card_http'), 'PUBLIC_FORM_CAPTURE_REQUIRED')
        calls = []
        def request(url, fields=None, referer=None):
            calls.append(url)
            return dict(status=403, url=url, raw=b'Denied', observed_at=AT)
        with tempfile.TemporaryDirectory() as folder:
            report = api.collect_canary_card_http(folder, venue_code=98, race_number=1,
                                                  request=request, clock=lambda: AT)
        self.assertEqual(report['state'], 'HOLD_PROVIDER_HTTP_403')
        self.assertEqual(len(calls), 1)
        self.assertFalse(report['canary_card_saved'])

    def test_public_tab_capture_uses_observed_cookie_session_request_and_preserves_card(self):
        from tests.test_keirin_official_sp_browser import calendar_html
        from urllib.parse import parse_qs, urlsplit
        api = self.api()
        args, tab_scripts, tab_raw = self.prediction_fixture()
        linked = lambda raw, paths: raw.replace(b'</body>', ''.join(
            '<script src="'+path+'"></script>' for path in paths).encode()+b'</body>')
        responses = dict(tab_scripts)
        responses.update({
            '/sp/raceschedule': linked(calendar_html(venues=(98,)),
                ['/sp/static/js/SJ0201.js', '/sp/static/js/commonSubmit.js']),
            '/sp/static/js/SJ0201.js': b'params["encp"]=encp;params["disp"]="SJ0301";commonSubmit.formPost(next,params,null);',
            '/sp/static/js/commonSubmit.js': b'$form.attr("method","post");',
            '/sp/racelist': linked(args['list_raw'],
                ['/sp/static/js/SJ0301_c.js', '/sp/static/js/SJ0301_v.js']),
            '/sp/static/js/SJ0301_c.js': b'var action=$(children[1]).attr("value");params["encp"]=$(children[2]).attr("value");if(dispDI==1){dispDI="SJ0315";}commonSubmit.formPost(action,params);',
            '/sp/static/js/SJ0301_v.js': b'raceProgram.strRaceLnk;raceProgram.strRaceLnkPrm;raceProgram.strRaceLnkKbn;',
            '/sp/race': args['detail_raw'], '/sp/json': tab_raw,
        })
        for tab_status in (200, 403):
            with self.subTest(tab_status=tab_status), tempfile.TemporaryDirectory() as folder:
                calls = []
                def request(url, fields=None, referer=None):
                    calls.append((url, fields, referer))
                    path = urlsplit(url).path
                    return dict(status=tab_status if path == '/sp/json' else 200,
                                url=url, raw=responses[path], observed_at=AT+timedelta(seconds=5))
                report = api.collect_canary_card_http(folder, venue_code=98, race_number=1,
                    request=request, clock=lambda: AT+timedelta(seconds=5))
                self.assertTrue(report['canary_card_saved'])
                self.assertEqual(len(calls), 12)
                self.assertEqual(urlsplit(calls[-1][0]).path, '/sp/json')
                self.assertEqual(parse_qs(urlsplit(calls[-1][0]).query),
                    dict(encp=['C'*64], skbn=['1'], type=['JSJ041']))
                self.assertIsNone(calls[-1][1])
                self.assertEqual(calls[-1][2], 'https://keirin.jp/sp/race')
                card = json.loads((Path(folder)/(report['card_sha256']+'.json')).read_text())
                if tab_status == 200:
                    self.assertTrue(report['marks_source_verified'])
                    self.assertEqual(len(card['navigation_script_receipts']), 8)
                    self.assertEqual(card['riders'][4]['mark_rank'], 'UNMARKED')
                    self.assertNotIn('MARKS_SOURCE_UNCONFIRMED', card['missing_inputs'])
                    self.assertNotIn('LINE_PREDICTION_UNCONFIRMED', card['missing_inputs'])
                    self.assertFalse(card['prediction_input_complete'])
                else:
                    self.assertEqual(report['state'], 'HOLD_PROVIDER_HTTP_403')
                    self.assertFalse(report['marks_source_verified'])
                    self.assertIn('MARKS_SOURCE_UNCONFIRMED', card['missing_inputs'])


if __name__ == '__main__':
    unittest.main()
