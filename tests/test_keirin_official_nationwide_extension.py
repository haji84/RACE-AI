"""Invented fixtures for a preparation adapter; not live coverage evidence."""
from copy import deepcopy
from hashlib import sha256
import re
from subprocess import TimeoutExpired
import unittest

from race_ai import keirin_official_nationwide_extension as ext
from tests.test_keirin_official_sp_receipt import AT, DAY, calendar_receipt, list_data, html, detail_data
from tests.test_keirin_official_canary_join import fixture


def line_fixture():
    data=detail_data()
    positions=[1,2,4,6,7,9,10]
    data['SJ0314']=dict(resultCd=0,narabiyoso=dict(lineKeitai='四分戦',lineKeitaiClass='yonbusen',
        errFlg='false',ryoikiFlg='true',kyoHyoji='false',maxAxixY=1,teikyo='架空紙',
        shaban=[dict(shaban=str(n),ichi=str(p)) for n,p in enumerate(positions,1)]))
    script='\n'.join(ext._LINE_VIEW_FRAGMENTS).encode()
    return data,dict(raw_bytes=script,expected_sha256=sha256(script).hexdigest(),observed_at=AT)


def parse_lines(data, script):
    raw=html(data).replace(b'</body>',('<script src="'+ext.LINE_VIEW_PATH+'"></script></body>').encode())
    return ext.parse_published_lines(raw,detail_sha256=sha256(raw).hexdigest(),
        starters=list(range(1,8)),competition='S',line_view_source=script)


class NationwideExtensionTests(unittest.TestCase):
    def test_one_row_gaps_define_lines_and_preserve_single_rider_group(self):
        data,script=line_fixture()
        self.assertEqual(parse_lines(data,script)['groups'],[[1,2],[3],[4,5],[6,7]])

    def test_contest_multilevel_parenthesis_and_duplicate_position_hold(self):
        for mutate in (
            lambda l:l.update(kyoHyoji='true'),
            lambda l:l.update(maxAxixY=2),
            lambda l:l['shaban'][0].update(shaban='(1)'),
            lambda l:l['shaban'][0].update(ichi='2'),
            lambda l:l.update(lineKeitai='未知表示'),
        ):
            data,script=line_fixture();mutate(data['SJ0314']['narabiyoso'])
            with self.assertRaises(ext.OfficialExtensionError):parse_lines(data,script)

    def test_line_view_must_be_actual_matching_source(self):
        data,script=line_fixture();script['raw_bytes']+=b'changed'
        with self.assertRaisesRegex(ValueError,'SHA'):parse_lines(data,script)

    def registry(self, include=True, prior=()):
        raw=html(list_data())
        sources=[dict(venue_code=98,raw_bytes=raw,expected_sha256=sha256(raw).hexdigest(),
                      observed_at=AT,http_status=200)] if include else []
        return ext.register_day(calendar_receipt=calendar_receipt(),list_sources=sources,
                                event_day=DAY,now=AT,prior_race_ids=prior)

    def test_missing_venue_is_not_complete_coverage(self):
        out=self.registry(False)
        self.assertEqual(out['missing_venues'],[98]);self.assertFalse(out['day_inventory_complete'])

    def test_disappeared_race_kept_in_denominator_and_blocks_completeness(self):
        out=self.registry(True,('203001159804',))
        self.assertEqual(out['disappeared_race_ids'],['203001159804'])
        self.assertEqual(len(out['registered_race_ids']),4)
        self.assertFalse(out['day_inventory_complete'])

    def test_registry_completion_never_claims_prediction_coverage(self):
        out=self.registry()
        self.assertTrue(out['day_inventory_complete'])
        self.assertFalse(out['all_prediction_coverage_complete'])
        pending=ext.deadline_candidates(out,[],now=AT)
        self.assertEqual(len(pending['unresolved_race_ids']),3)
        self.assertEqual(pending['candidates'],[])

    def test_day_collector_stops_on_denial_without_alternate_request(self):
        for status in (401,403,407,429):
            calls=[]
            def request(url,fields,referer):
                calls.append(url)
                return dict(status=status,url=url,raw=b'Denied',observed_at=AT)
            out=ext.collect_day_inventory(request=request,clock=lambda:AT,event_day=DAY)
            self.assertEqual(len(calls),1)
            self.assertIsNone(out['registry'])
            self.assertEqual(out['state'],'OFFICIAL_EXTENSION_PROVIDER_HTTP_DENIED_'+str(status))
            self.assertTrue(out['provider_denied'])
            self.assertEqual(out['last_failed_http_status'],status)
            self.assertEqual(out['source_receipts'][-1]['http_status'],status)
            self.assertEqual(out['last_failed_request']['failure_code'],out['failure_code'])
            self.assertEqual(out['model_generation'],0)

    def test_server_failure_stops_but_is_not_a_provider_denial(self):
        for status in (500,502,503,504):
            calls=[]
            def request(url,fields,referer):
                calls.append(url)
                return dict(status=status,url=url,raw=b'Service unavailable',observed_at=AT)
            out=ext.collect_day_inventory(request=request,clock=lambda:AT,event_day=DAY)
            self.assertEqual(len(calls),1)
            self.assertFalse(out['provider_denied'])
            self.assertEqual(out['last_failed_http_status'],status)
            self.assertEqual(out['source_receipts'][-1]['http_status'],status)
            self.assertEqual(out['failure_code'],'OFFICIAL_EXTENSION_PROVIDER_HTTP_UNAVAILABLE_'+str(status))

    def test_challenge_is_a_persistent_denial_even_with_http_200(self):
        calls=[]
        def request(url,fields,referer):
            calls.append(url)
            return dict(status=200,url=url,raw=b'<html>captcha</html>',observed_at=AT)
        out=ext.collect_day_inventory(request=request,clock=lambda:AT,event_day=DAY)
        self.assertEqual(len(calls),1)
        self.assertTrue(out['provider_denied'])
        self.assertEqual(out['last_failed_http_status'],200)
        self.assertEqual(out['failure_code'],'OFFICIAL_EXTENSION_PROVIDER_CHALLENGE_REFUSED')
        self.assertTrue(out['source_receipts'][-1]['provider_denied'])

    def test_timeout_has_no_invented_http_status_and_is_not_denial(self):
        for error in (TimeoutError(),TimeoutExpired('fixture-command',20)):
            calls=[]
            def request(url,fields,referer):
                calls.append(url)
                raise error
            out=ext.collect_day_inventory(request=request,clock=lambda:AT,event_day=DAY)
            self.assertEqual(len(calls),1)
            self.assertFalse(out['provider_denied'])
            self.assertIsNone(out['last_failed_http_status'])
            self.assertIsNone(out['source_receipts'][-1]['http_status'])
            self.assertEqual(out['failure_code'],'OFFICIAL_EXTENSION_PROVIDER_TIMEOUT')

    def test_day_collector_follows_observed_form_and_keeps_result_identity(self):
        from urllib.parse import urlsplit
        cal=calendar_receipt()['raw_bytes'].replace(b'</body>',
            b'<script src="/sp/static/js/SJ0201.js"></script><script src="/sp/static/js/commonSubmit.js"></script></body>')
        responses={'/sp/raceschedule':cal,
            '/sp/static/js/SJ0201.js':b'params["encp"]=encp;params["disp"]="SJ0301";commonSubmit.formPost(next,params,null);',
            '/sp/static/js/commonSubmit.js':b'$form.attr("method","post");',
            '/sp/racelist':html(list_data())}
        calls=[]
        def request(url,fields,referer):
            calls.append((url,fields))
            return dict(status=200,url=url,raw=responses[urlsplit(url).path],observed_at=AT)
        out=ext.collect_day_inventory(request=request,clock=lambda:AT,event_day=DAY)
        self.assertEqual(out['state'],'DAY_SOURCES_CAPTURED')
        self.assertTrue(out['registry']['day_inventory_complete'])
        self.assertEqual(len(out['registry']['registered_race_ids']),3)
        self.assertEqual(calls[-1][1],[('encp','A'*43),('disp','SJ0301')])

    def baseline_arguments(self):
        d=fixture();m=d['card_manifest'];raw=d['source_bytes_by_sha']
        roles={s['kind']:s for s in m['sources']}
        cal,listed,detail,tab=(roles[k] for k in ('CALENDAR','RACE_LIST','RACECARD','PREDICTION_TAB'))
        listing=raw[listed['bytes_sha256']].replace('ガールズ予選'.encode(),'ガールズ選抜'.encode())
        args=dict(list_raw=listing,detail_raw=raw[detail['bytes_sha256']],expected_day=DAY,
            venue_code=98,race_number=1,
            calendar_receipt=dict(raw_bytes=raw[cal['bytes_sha256']],expected_sha256=cal['bytes_sha256'],
                                  observed_at=cal['captured_at']),
            list_observed_at=listed['captured_at'],detail_observed_at=detail['captured_at'],
            list_sha256=sha256(listing).hexdigest(),detail_sha256=detail['bytes_sha256'])
        scripts={s['url'].replace('https://keirin.jp',''):raw[s['bytes_sha256']]
                 for s in m['navigation_script_receipts']}
        profiles=[]
        for row in d['history_manifest']['riders']:
            digest=row['profile']['source_sha256']
            source=next(s for s in d['history_manifest']['source_receipts'] if s['bytes_sha256']==digest)
            profiles.append(dict(registration_id=row['registration_id'],raw_bytes=raw[digest],
                expected_sha256=digest,observed_at=source['captured_at'],http_status=200,
                source_url=source['source_url']))
        return dict(card_arguments=args,prediction_source=dict(raw_bytes=raw[tab['bytes_sha256']],
            expected_sha256=tab['bytes_sha256'],observed_at=tab['captured_at'],request_url=tab['url']),
            prediction_scripts=scripts,profile_sources=profiles,now=d['now'])

    def test_baseline_ready_without_any_history_or_condition_payload(self):
        out=ext.build_baseline_candidate(**self.baseline_arguments())
        self.assertEqual(out['baseline_state'],'BASELINE_INPUT_READY')
        self.assertEqual(out['condition_state'],'HOLD_CONDITION_HISTORY_NOT_JOINED')
        self.assertEqual(len(out['snapshot']['riders']),7)
        self.assertEqual(out['model_generation'],0)
        self.assertTrue(out['execution_requires_verified_canary_pass'])

    def test_profile_without_published_history_does_not_block_complete_baseline_statistics(self):
        args=self.baseline_arguments()
        for profile in args['profile_sources']:
            body=re.sub(rb'onclick="btnResultClick\([^\"]*\)"',b'',profile['raw_bytes'])
            self.assertNotEqual(body,profile['raw_bytes'])
            profile['raw_bytes']=body;profile['expected_sha256']=sha256(body).hexdigest()
        out=ext.build_baseline_candidate(**args)
        self.assertEqual(out['baseline_state'],'BASELINE_INPUT_READY')
        self.assertEqual(out['condition_state'],'HOLD_CONDITION_HISTORY_NOT_JOINED')

    def test_unknown_class_round_is_not_coerced_into_supported_class(self):
        args=self.baseline_arguments();card=args['card_arguments']
        card['list_raw']=card['list_raw'].replace('ガールズ選抜'.encode(),'未知決勝'.encode())
        card['list_sha256']=sha256(card['list_raw']).hexdigest()
        with self.assertRaisesRegex(ValueError,'CLASS_OR_ROUND_NOT_YET_OBSERVED'):
            ext.build_baseline_candidate(**args)


if __name__=='__main__':unittest.main()
