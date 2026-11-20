"""Invented public-form result responses, no live provider calls."""
from datetime import datetime
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts import keirin_official_form_canary as api
from tests.test_keirin_official_schedule import page, venue, meeting
from tests.test_keirin_official_sp_receipt import header, html


def fixture():
    def link(raw, paths):
        return raw.replace(b'</body>', ''.join('<script src="' + p + '"></script>'
            for p in paths).encode() + b'</body>')
    calendar = link(page([venue(81, [meeting('2026-11-18', '2026-11-23')])],
        year='2026', month='11'), ['/sp/static/js/SJ0201.js', '/sp/static/js/commonSubmit.js'])
    refs = [dict(strRaceNo=str(n), strSyumokuName='架空区分', strArrow='', strArrowName='',
        strRaceLnk='/sp/race', strRaceLnkPrm=chr(64 + n) * 43, strRaceLnkKbn='2',
        strColorClass='') for n in range(1, 6)]
    listing = dict(SC0201=dict(resultCd=0, C0201data=header('2026/11/20')),
        SJ0301=dict(resultCd=0, kaisaiDayList=[dict(strKaisaiNitijName='3日目(11/20)',
                                                raceProgramList=refs)]))
    riders = [dict(car=n, registration_id=f'{15000+n:06d}') for n in range(1, 7)]
    head = dict(txtEventDate='2026/11/20', selRaceNo=5, aftBetDate='202611201707',
                flgRaceCancel=False, flgKekkaRefund=False)
    result = dict(resultCd=0, tyakujyunDispFlg=True, haraiGakuDispFlg=True, bikouDispFlg=False,
        lastUpdateTime='2026/11/20 17:11&nbsp;更新',
        digestUrl='https://wm.st.keirin.jp/wm-keirin81/20261120-81-02-05-01-00.mp4',
        tyakujyunItemSubData=[dict(syaban=str(r['car']), sensyuRegistNo=r['registration_id'],
            tyaku=str(r['car']), kojinStateItemSubData=[]) for r in riders],
        haraiGakuSubData=dict(APartReturnDispFlg=False, RT3HaraiGakuDispItemSubData=[
            dict(kumiBan='1-2-3', haraiGaku='1,230', kumiDispFlg=True)]))
    raw = ('<html><body><script>var jsonData = {};jsonData["SC0201"] = ' +
        json.dumps(dict(resultCd=0, C0201data=head)) + ';jsonData["SJ0326"] = ' +
        json.dumps(result) + ';</script></body></html>').encode()
    responses = {
        '/sp/raceschedule': calendar,
        '/sp/static/js/SJ0201.js': b'params["encp"]=encp;params["disp"]="SJ0301";commonSubmit.formPost(next,params,null);',
        '/sp/static/js/commonSubmit.js': b'$form.attr("method","post");',
        '/sp/racelist': link(html(listing), ['/sp/static/js/SJ0301_v.js', '/sp/static/js/SJ0301_c.js']),
        '/sp/static/js/SJ0301_v.js': b'raceProgram.strRaceLnk;raceProgram.strRaceLnkPrm;raceProgram.strRaceLnkKbn;',
        '/sp/static/js/SJ0301_c.js': b'var action=$(children[1]).attr("value");params["encp"]=$(children[2]).attr("value");if(dispDI==2){dispDI="SJ0326";}commonSubmit.formPost(action,params);',
        '/sp/race': raw,
        '/ticket/': ('<html><body><p>' + api.payout_unit.UNIT_URLS['https://www.hofukeirin.jp/ticket/'] +
                    '</p></body></html>').encode(),
    }
    return responses, dict(race_id=api.RACE, official_cutoff_at=api.CUTOFF, riders=riders)


class ResultCollectionTests(unittest.TestCase):
    def collect(self, folder, *, failure_path=None, status=200, extra_guide=b'', blocked=False):
        responses, frozen = fixture()
        responses['/ticket/'] = responses['/ticket/'].replace(b'</body>', extra_guide+b'</body>')
        calls = []
        now = datetime.fromisoformat('2026-11-20T17:12:02+09:00')
        def request(url, fields=None, referer=None):
            path = urlsplit(url).path
            calls.append(path)
            if failure_path == path and status is None:
                raise OSError('Do not publish Cookie=fixture-secret or encp=private-token')
            at = '2026-11-20T17:12:01+09:00' if path == '/ticket/' else '2026-11-20T17:12:00+09:00'
            return dict(url=url, status=status if failure_path == path else 200,
                        raw=responses[path], observed_at=datetime.fromisoformat(at))
        with patch.object(api, '_provider_preflight', side_effect=api.CanaryError('CANARY_PERSISTENT_PROVIDER_STOP') if blocked else None):
            result = api.collect_final_result(repo='/synthetic', private_root=folder,
                frozen_card=frozen, clock=lambda: now, request=request)
        return result, calls

    def test_result_is_fetched_before_unit_and_capture_clock_is_not_backdated(self):
        with tempfile.TemporaryDirectory() as folder:
            result, calls = self.collect(folder)
        self.assertEqual(calls[-2:], ['/sp/race', '/ticket/'])
        self.assertEqual(result['observed_at'], '2026-11-20T08:12:00+00:00')
        self.assertEqual(result['unit_evidence']['observed_at'], '2026-11-20T08:12:01+00:00')
        parsed = api.form.parse_final_result(result['raw_result'], expected_race_id=api.RACE,
            observed_at=result['observed_at'], expected_reference=result['expected_reference'],
            verified_unit_evidence=result['unit_evidence'],
            source_bytes_by_sha=result['source_bytes_by_sha'], unit_verified_at=result['unit_verified_at'])
        self.assertTrue(parsed['monetary_comparison_eligible'])

    def test_unit_transport_failure_keeps_official_order_and_does_not_latch_denial(self):
        for code in (None, 503):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder, patch.object(api.provider_stop, 'record_denial') as latch:
                result, calls = self.collect(folder, failure_path='/ticket/', status=code)
                self.assertIsNone(result['unit_evidence'])
                self.assertEqual(result['payout_unit_state'], 'UNAVAILABLE')
                self.assertEqual(result['official_order']['winning_triples'], [[1, 2, 3]])
                self.assertFalse(result['official_order']['monetary_comparison_eligible'])
                self.assertEqual(calls[-2:], ['/sp/race', '/ticket/'])
                self.assertNotIn('fixture-secret', json.dumps(result['safe_diagnostics']))
                latch.assert_not_called()

    def test_unit_denial_is_recorded_before_latch_and_keeps_already_verified_order(self):
        for code in (403, 429):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                def latch(**kwargs):
                    saved = [json.loads(p.read_text()) for p in (Path(folder)/'safe').glob('*.json')]
                    self.assertTrue(any(r['http_status'] == code and r['purpose'] == 'OFFICIAL_PAYOUT_UNIT' for r in saved))
                with patch.object(api.provider_stop, 'record_denial', side_effect=latch) as stopped:
                    result, calls = self.collect(folder, failure_path='/ticket/', status=code)
                    self.assertEqual(result['payout_unit_state'], 'PROVIDER_STOPPED')
                    self.assertEqual(result['official_order']['winning_triples'], [[1, 2, 3]])
                    self.assertIsNone(result['unit_evidence'])
                    self.assertEqual(calls[-1], '/ticket/')
                    stopped.assert_called_once()

    def test_passive_guide_asset_does_not_latch_but_interstitial_does(self):
        passive = b'<script id="google-recaptcha-js" src="https://www.google.com/recaptcha/api.js?render=fixture"></script>'
        with tempfile.TemporaryDirectory() as folder, patch.object(api.provider_stop, 'record_denial') as latch:
            result, _ = self.collect(folder, extra_guide=passive)
            self.assertEqual(result['payout_unit_state'], 'VERIFIED')
            latch.assert_not_called()
        with tempfile.TemporaryDirectory() as folder, patch.object(api.provider_stop, 'record_denial') as latch:
            result, calls = self.collect(folder, extra_guide=b'<h1>Verify you are human</h1>')
            self.assertEqual(result['payout_unit_state'], 'PROVIDER_STOPPED')
            self.assertEqual(calls[-1], '/ticket/')
            latch.assert_called_once()

    def test_result_denial_exposes_only_safe_receipt_and_never_requests_unit(self):
        responses, frozen = fixture()
        calls = []
        now = datetime.fromisoformat('2026-11-20T17:12:02+09:00')
        def request(url, fields=None, referer=None):
            path = urlsplit(url).path; calls.append(path)
            return dict(url=url, status=403 if path == '/sp/race' else 200,
                        raw=responses[path], observed_at=now)
        with tempfile.TemporaryDirectory() as folder, patch.object(api, '_provider_preflight'), patch.object(api.provider_stop, 'record_denial'):
            with self.assertRaises(api.CanaryError) as error:
                api.collect_final_result(repo='/synthetic', private_root=folder,
                    frozen_card=frozen, clock=lambda:now, request=request)
            self.assertEqual(calls[-1], '/sp/race')
            self.assertNotIn('/ticket/', calls)
            self.assertEqual(error.exception.safe_diagnostics[-1]['purpose'], 'OFFICIAL_FINAL_RESULT')
            self.assertEqual(error.exception.safe_diagnostics[-1]['http_status'], 403)
            self.assertNotIn('encp', json.dumps(error.exception.safe_diagnostics))

    def test_main_keeps_allowlisted_failure_details_in_summary(self):
        from race_ai import keirin_result_diagnostics as diagnostics
        row = diagnostics.make_diagnostic(purpose='OFFICIAL_FINAL_RESULT', stage='HTTP_RESPONSE',
            reason='HTTP_DENIED', http_status=403, observed_at='2026-11-20T18:24:45+09:00')
        error = api.CanaryError('CANARY_PROVIDER_DENIED_PERSISTED_NO_RETRY', safe_diagnostics=[row])
        with tempfile.TemporaryDirectory() as folder, patch.object(api, 'run_settle', side_effect=error), redirect_stdout(StringIO()):
            report = Path(folder)/'safe'/'summary.json'
            code = api.main(['settle', '--repo', '/synthetic', '--private-root', folder,
                '--owner-public-pem', '/synthetic/public.pem', '--report', str(report)])
            self.assertEqual(code, 2)
            saved = json.loads(report.read_text())
            self.assertEqual(saved.get('safe_diagnostics'), [row])

    def test_unknown_exception_text_is_never_treated_as_public_error_code(self):
        output = StringIO()
        with tempfile.TemporaryDirectory() as folder, patch.object(api, 'run_settle',
                side_effect=OSError('PRIVATE_TOKEN_DO_NOT_LOG')), redirect_stdout(output):
            report = Path(folder)/'safe'/'summary.json'
            api.main(['settle', '--repo', '/synthetic', '--private-root', folder,
                '--owner-public-pem', '/synthetic/public.pem', '--report', str(report)])
            self.assertNotIn('PRIVATE_TOKEN_DO_NOT_LOG', report.read_text())
            self.assertNotIn('PRIVATE_TOKEN_DO_NOT_LOG', output.getvalue())

    def test_existing_stop_prevents_every_provider_request(self):
        _, frozen = fixture()
        with tempfile.TemporaryDirectory() as folder, patch.object(api.provider_stop,
                'read_for_observed_day', return_value={'code': 'DENIED'}), \
                patch.object(api.card_source, '_CurlPublicSession') as transport:
            with self.assertRaisesRegex(api.CanaryError, 'PERSISTENT_PROVIDER_STOP'):
                api.collect_final_result(repo='/synthetic', private_root=folder,
                    frozen_card=frozen, clock=lambda:datetime.fromisoformat('2026-11-20T18:00:00+09:00'))
            transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
