"""Source-free bounded continuation checks over invented official documents."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from tests.test_keirin_official_nationwide_extension import NationwideExtensionTests
from tests.test_keirin_official_canary_join import fixture


class Lease:
    def __init__(self): self.calls = []
    def before_request(self, **kwargs): self.calls.append(kwargs)


class NationwideSourceTests(unittest.TestCase):
    def api(self):
        return importlib.import_module('race_ai.keirin_official_nationwide_sources')

    def candidate(self):
        args = NationwideExtensionTests().baseline_arguments()
        from race_ai import keirin_official_nationwide_extension as ext
        baseline = ext.build_baseline_candidate(**args)
        return args, baseline['snapshot']

    def test_condition_join_reparses_real_source_shapes_without_changing_baseline(self):
        args, snapshot = self.candidate(); captured = fixture(); before = deepcopy(snapshot)
        out = self.api().build_condition_candidate(snapshot=snapshot,
            card_arguments=args['card_arguments'], prediction_source=args['prediction_source'],
            prediction_scripts=args['prediction_scripts'], history_manifest=captured['history_manifest'],
            source_bytes_by_sha=captured['source_bytes_by_sha'], now=args['now'])
        self.assertEqual(snapshot, before)
        self.assertEqual(out['supplement']['race_id'], snapshot['race_id'])
        self.assertEqual(len(out['supplement']['condition_evidence']['riders']), 7)
        self.assertEqual(out['identity_proof']['verified_rider_results'], 42)
        self.assertFalse(out['availability']['medical_recovery_inferred'])

    def test_condition_identity_or_missing_raw_bytes_cannot_be_admitted(self):
        args, snapshot = self.candidate()
        for mutate in ('identity', 'raw'):
            with self.subTest(mutate=mutate):
                captured = fixture()
                if mutate == 'identity': captured['history_manifest']['riders'][0]['registration_id'] = '999999'
                else: captured['source_bytes_by_sha'].pop(captured['history_manifest']['riders'][0]['profile']['source_sha256'])
                with self.assertRaises(ValueError):
                    self.api().build_condition_candidate(snapshot=snapshot,
                        card_arguments=args['card_arguments'], prediction_source=args['prediction_source'],
                        prediction_scripts=args['prediction_scripts'], history_manifest=captured['history_manifest'],
                        source_bytes_by_sha=captured['source_bytes_by_sha'], now=args['now'])

    def test_shared_session_checks_guard_before_transport_and_denial_stops_all_later_calls(self):
        at = fixture()['now']; lease = Lease(); events = []
        def transport(url, fields=None, referer=None):
            self.assertEqual(lease.calls[-1]['url'], url)
            events.append('request')
            return dict(url=url,status=403,raw=b'private refusal',observed_at=at)
        with tempfile.TemporaryDirectory() as folder, patch('race_ai.keirin_github_provider_stop.record_denial') as denial:
            session = self.api().OfficialSourceSession(repo='/synthetic',private_root=folder,
                lease=lease,clock=lambda:at,request=transport)
            with self.assertRaises(ValueError): session.fetch('https://keirin.jp/sp/raceschedule')
            with self.assertRaises(ValueError): session.fetch('https://keirin.jp/sp/static/js/SJ0201.js')
            self.assertEqual(events,['request']); denial.assert_called_once()
            self.assertTrue(session.provider_denied)
            self.assertEqual(session.safe_diagnostics[-1]['http_status'],403)
            self.assertNotIn('private refusal',str(session.safe_diagnostics))

    def test_http_failure_is_not_denial_and_success_cache_does_not_refetch(self):
        at = fixture()['now']; calls = []
        def request(url, fields=None, referer=None):
            calls.append(url)
            return dict(url=url,status=200 if len(calls)==1 else 503,raw=b'ordinary source',observed_at=at)
        with tempfile.TemporaryDirectory() as folder, patch('race_ai.keirin_github_provider_stop.record_denial') as denial:
            session = self.api().OfficialSourceSession(repo='/synthetic',private_root=folder,
                lease=Lease(),clock=lambda:at,request=request)
            first=session.fetch('https://keirin.jp/sp/raceschedule')
            self.assertEqual(session.fetch('https://keirin.jp/sp/raceschedule'),first)
            with self.assertRaises(ValueError): session.fetch('https://keirin.jp/sp/static/js/SJ0201.js')
            self.assertEqual(len(calls),2); self.assertFalse(session.provider_denied)
            self.assertTrue(session.halted); denial.assert_not_called()

    def test_future_card_requires_published_future_mapping_not_only_result_mapping(self):
        api=self.api();linked=''.join('<script src="'+path+'"></script>' for path in api.LIST_SCRIPTS)
        class Session:
            def fetch(self,url):
                parts=api.LIST_SCRIPTS[url.replace('https://keirin.jp','')]
                body=''.join(p for p in parts if 'dispDI==1' not in p).encode()
                return {'raw_bytes':body}
        with self.assertRaisesRegex(ValueError,'LIST_SCRIPT_CHANGED'):
            api.require_list_scripts(Session(),{'raw_bytes':('<html>'+linked+'</html>').encode()})

    def test_non_pair_form_container_cannot_collide_with_a_cached_request(self):
        at=fixture()['now'];lease=Lease()
        with tempfile.TemporaryDirectory() as folder:
            session=self.api().OfficialSourceSession(repo='/synthetic',private_root=folder,
                lease=lease,clock=lambda:at,request=lambda *args: self.fail('no provider'))
            with self.assertRaises(ValueError):
                session.fetch('https://keirin.jp/sp/race',{'encp':'A'*43,'disp':'SJ0315'})
            self.assertEqual(lease.calls,[])

    def test_earliest_archived_cutoff_reserve_stops_before_transport(self):
        at=fixture()['now'];lease=Lease()
        with tempfile.TemporaryDirectory() as folder:
            session=self.api().OfficialSourceSession(repo='/synthetic',private_root=folder,
                lease=lease,clock=lambda:at,request=lambda *args:self.fail('no provider'))
            session.capture_deadline=at
            with self.assertRaisesRegex(ValueError,'CAPTURE_FINALIZATION_RESERVE'):
                session.fetch('https://keirin.jp/sp/raceschedule')
            self.assertEqual(lease.calls,[])

    def final_fixture(self, folder, *, unit_status=200, result_kind='2'):
        from tests.test_keirin_result_collection import fixture as final_fixture
        from race_ai import keirin_official_nationwide_extension as extension
        pages, frozen=final_fixture()
        pages['/sp/static/js/SJ0301_c.js']+=b'if(dispDI==1){dispDI="SJ0315";}'
        if result_kind!='2':
            pages['/sp/racelist']=pages['/sp/racelist'].replace(b'"strRaceLnkKbn": "2"',
                ('"strRaceLnkKbn": "'+result_kind+'"').encode())
        calls=[];now=datetime.fromisoformat('2026-11-20T17:12:02+09:00')
        def request(url,fields=None,referer=None):
            path=urlsplit(url).path;calls.append(path)
            at=datetime.fromisoformat('2026-11-20T17:12:01+09:00' if path=='/ticket/' else
                                      '2026-11-20T17:12:00+09:00')
            return dict(url=url,status=unit_status if path=='/ticket/' else 200,
                        raw=pages[path],observed_at=at)
        session=self.api().OfficialSourceSession(repo='/synthetic',private_root=folder,
            lease=Lease(),clock=lambda:now,request=request,sleep=lambda delay:None,
            monotonic=lambda:1)
        inventory=extension.collect_day_inventory(request=session.request,clock=lambda:now,event_day='2026-11-20')
        original=dict(race_id=frozen['race_id'],day_jst='2026-11-20',
            baseline=dict(published_cutoff_at=frozen['official_cutoff_at']),
            snapshot=dict(riders=[dict(car=r['car'],athlete_id=r['registration_id']) for r in frozen['riders']]))
        final=self.api().collect_final(session=session,inventory=inventory,original=original,clock=lambda:now)
        return session,original,final,calls

    def test_real_shared_session_final_keeps_safe_schema_and_separate_unit_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            session,original,final,calls=self.final_fixture(folder)
            parsed=self.api().reparse_final(original,final)
        self.assertTrue(parsed['monetary_comparison_eligible'])
        self.assertEqual(calls[-2:],['/sp/race','/ticket/'])
        self.assertNotEqual(final['observed_at'],final['unit_evidence']['observed_at'])
        self.assertTrue(final['safe_diagnostics'])
        self.assertTrue(all(row.get('schema') for row in final['safe_diagnostics']))

    def test_unit_failure_retains_order_and_denial_prevents_every_subsequent_call(self):
        for status in (403,503):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder,\
                    patch('race_ai.keirin_github_provider_stop.record_denial') as denial:
                session,original,final,calls=self.final_fixture(folder,unit_status=status)
                parsed=self.api().reparse_final(original,final)
                self.assertEqual(parsed['winning_triples'],[[1,2,3]])
                self.assertFalse(parsed['monetary_comparison_eligible'])
                self.assertIsNone(final['unit_evidence'])
                before=list(calls)
                with self.assertRaises(ValueError):session.fetch('https://keirin.jp/sp/raceschedule')
                self.assertEqual(calls,before)
                self.assertEqual(session.provider_denied,status==403)
                self.assertEqual(denial.call_count,int(status==403))

    def test_future_card_link_never_becomes_a_result_request(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError,'RESULT_NOT_PUBLISHED'):
            self.final_fixture(folder,result_kind='1')


if __name__ == '__main__': unittest.main()
