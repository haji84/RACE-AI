"""The Mac shadow settlement uses a frozen input and an offline official source."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from race_ai import keirin_official_public_source as official
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_mac_shadow_result as shadow
from scripts.keirin_official_day_pipeline import private_snapshot_json
from tests.test_keirin_official_public_source import DAY, RACE, fixtures, transport
from tests.test_keirin_public_site_results import kd_result, net_result


KDREAMS = 'https://keirin.kdreams.jp/synthetic/racedetail/2620261002010001/'
NETKEIRIN = 'https://keirin.netkeiba.com/race/result/?race_id=' + RACE


def at(hour, minute):
    return datetime(2026, 10, 2, hour, minute, tzinfo=timezone.utc)


class MacShadowResultTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = fixtures()
        self.calls = []
        self.get = transport(self.data, self.calls)
        schedule = official.fetch_day_schedule(DAY, fetcher=self.get, clock=lambda: at(1, 30))
        self.calls.clear()
        cuts = [r for r in schedule['races'] if r['race_id'] == RACE][0]
        roster = [dict(car=r['car'], athlete_id=r['registration_id']) for r in cuts['starters']]
        self.schedule_path = self.write('official-schedule.json', private_snapshot_json(schedule))
        self.schedule_sha = sha256(self.schedule_path.read_bytes()).hexdigest()
        self.original = dict(
            schema='KEIRIN_MAC_PROSPECTIVE_SHADOW_V1', scope='PROSPECTIVE_RESEARCH',
            race_id=RACE, generated_at=at(1, 40).isoformat(), score_cutoff_at=at(1, 46).isoformat(),
            official_cutoff_at=cuts['official_cutoff_at'], production_model_switched=False,
            selected_arm='all_96', input=dict(official_schedule_sha256=self.schedule_sha,
                official_venue_source_sha256=cuts['source_sha256'], input=dict(race_id=RACE, riders=roster),
                source_url=KDREAMS, source_sha256='c' * 64, source_captured_at=at(1, 35).isoformat(),
                provider_cutoff_at=at(1, 46).isoformat()),
            forecasts=self.forecasts())
        self.request = self.write_request()
        self.now = at(1, 43)
        self.assertEqual(self.run_shadow()['state'], 'WAITING_FOR_OFFICIAL_START')
        self.now = at(3, 12)

    def write(self, name, content):
        path = self.root / name
        path.write_text(json.dumps(content), encoding='utf-8')
        path.chmod(0o600)
        return path

    def write_request(self):
        path = self.write('original.json', self.original)
        request = dict(original_path=str(path), original_sha256=sha256(path.read_bytes()).hexdigest(),
                       schedule_path=str(self.schedule_path), schedule_sha256=self.schedule_sha)
        return self.write('request.json', request)

    def forecasts(self):
        orders = list(permutations(range(1, 8), 3))

        def book(tops):
            back = (1 - sum(tops.values())) / (len(orders) - len(tops))
            return dict(trifecta=[[list(k), tops.get(k, back)] for k in orders])

        return {'saved': book({(7, 6, 5): .5, (7, 5, 6): .2, (6, 7, 5): .15, (6, 5, 7): .1}),
                'all_96': book({(1, 2, 3): .8})}

    def run_shadow(self, fetcher=..., **options):
        return shadow.run(self.root, self.request, clock=lambda: self.now,
                          fetcher=self.get if fetcher is ... else fetcher, **options)

    def public_fixture(self):
        ref = 'a' * 40
        cutoff = self.original['score_cutoff_at']
        published = at(3, 5).isoformat()
        source_url = KDREAMS
        roster = dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=DAY,
                      generated_at=at(1, 42).isoformat(), forecast_asset_sha256='b' * 64,
                      races=[dict(race_id=RACE, date=DAY, venue='架空場', race_no=1,
                                  published_cutoff_at=cutoff, source_url=source_url,
                                  observed_riders=[{'number': car} for car in range(1, 8)])])
        outcome = dict(race_id=RACE, observed_at=published, authority='cross_source_reference',
                       comparison_scope='POST_CUTOFF_REFERENCE', winning_3t=[1, 2, 3], winning_2t=[1, 2],
                       payouts_100yen={'2t': 300, '3t': 1230},
                       sources=[dict(source_id='kdreams', checked_at=published,
                                     url=source_url + '?pageType=result'),
                                dict(source_id='netkeirin', checked_at=published,
                                     url='https://keirin.netkeiba.com/race/result/?race_id=' + RACE)])
        results = dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=DAY, checked_at=published,
                       races=[dict(race_id=RACE, state='matched', comparison=outcome)])
        return {'git/ref/heads/state/keirin-public-results': {
                    'ref': 'refs/heads/state/keirin-public-results', 'object': {'sha': ref, 'type': 'commit'}},
                f'contents/rosters/{DAY}.json?ref={ref}': roster,
                f'contents/results/{DAY}.json?ref={ref}': results}

    def approve_secondary(self, **overrides):
        request = json.loads(self.request.read_bytes())
        approval = dict(schema='KEIRIN_MAC_SHADOW_SECONDARY_RESULT_APPROVAL_V1',
                        scope='OWNER_PERSONAL_RESEARCH_ONLY', race_id=RACE, kdreams_url=KDREAMS,
                        original_sha256=request['original_sha256'], schedule_sha256=request['schedule_sha256'])
        approval.update(overrides)
        return self.write('secondary-result-approval.json', approval)

    def run_secondary(self, fetch, *, status=404, unexpected_url=False, wrong_ref=False, absent='rosters'):
        public = self.public_fixture()
        if wrong_ref:
            public[shadow.GITHUB_REF]['ref'] = 'refs/heads/unrelated'
        missing = shadow.GITHUB_REF if absent == 'ref' else f'contents/{absent}/{DAY}.json?ref={"a" * 40}'

        def public_get(path, **_):
            self.result_calls.append(path)
            if path == missing:
                url = shadow.GITHUB_API + (path if not unexpected_url else 'unexpected-not-found')
                raise HTTPError(url, status, 'fixture', {}, None)
            return public[path]

        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}):
            with patch.object(capture, 'fetch_once', side_effect=fetch):
                return self.run_shadow(fetcher=None, public_fetcher=public_get)

    def site_page(self, url, *, podium='1-2-3'):
        self.result_calls.append(url)
        if url == KDREAMS + '?pageType=result':
            page = kd_result().decode().replace('1-2-4', '1-2-3')
        elif url == NETKEIRIN:
            page = net_result(podium=podium).decode()
        else:
            self.fail(f'unexpected source request: {url}')
        return page.replace('広島競輪 2026年11月23日', '架空場競輪 2026年10月2日').encode()

    def test_exact_missing_roster_allows_the_approved_pair_and_reuses_the_saved_outcome(self):
        self.approve_secondary()
        self.result_calls = []
        before = (self.root / 'original.json').read_bytes()
        report = self.run_secondary(self.site_page)
        self.assertEqual(report['state'], 'SHADOW_SECONDARY_PODIUM_SCORED')
        self.assertEqual(report['scope'], 'TWO_SOURCE_MATCHED_PODIUM_ONLY')
        self.assertEqual(report['official_state'], 'HOLD_OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED')
        self.assertFalse(report['full_finish_verified'])
        self.assertEqual(report['scores'], {'saved': {'top4_3t': 0, 'top2_2t': 0},
                                           'challenger': {'top4_3t': 1, 'top2_2t': 1}})
        self.assertEqual(self.run_secondary(self.site_page), report)
        self.assertEqual(self.result_calls, [shadow.GITHUB_REF,
                         f'contents/rosters/{DAY}.json?ref={"a" * 40}', KDREAMS + '?pageType=result', NETKEIRIN])
        self.assertEqual((self.root / 'original.json').read_bytes(), before)
        self.assertEqual(list(self.root.rglob('official-result.json')), [])

    def test_site_projection_rechecks_saved_secondary_evidence_without_sources(self):
        from scripts import keirin_mac_shadow_publication as site

        self.approve_secondary()
        self.result_calls = []
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'SHADOW_SECONDARY_PODIUM_SCORED')
        result_path = self.root / 'keirin-mac-shadow-results' / RACE / 'site-two-source/result.json'
        with (patch.object(capture, 'fetch_once', side_effect=AssertionError('unexpected provider request')),
              patch.object(shadow, '_public_github_json', side_effect=AssertionError('unexpected GitHub request'))):
            report = site.prepare_record(self.root, self.request, 'a' * 64, clock=lambda: self.now)
            self.assertEqual(report['result']['evidence_sha256'], sha256(result_path.read_bytes()).hexdigest())
            self.assertEqual(report['result']['scope'], 'TWO_SOURCE_MATCHED_PODIUM_ONLY')
            self.assertEqual(report['scores']['trifecta'], dict(points=4, saved_hit=False, challenger_hit=True))
            self.assertEqual(report['scores']['exacta'], dict(points=2, saved_hit=False, challenger_hit=True))
            self.assertEqual(report['tracking_learning'], 'HELD')
            self.assertFalse(report['production_weights_promoted'])
            raw = next(result_path.parent.glob('raw/*.html'))
            raw.write_bytes(b'new body with an invalid digest')
            with self.assertRaises(ValueError):
                site.prepare_record(self.root, self.request, 'a' * 64, clock=lambda: self.now)

    def test_site_projection_stays_empty_until_an_exact_saved_result_exists(self):
        from scripts import keirin_mac_shadow_publication as site

        with (patch.object(shadow, 'run', side_effect=AssertionError('unexpected live settlement')),
              patch.object(capture, 'fetch_once', side_effect=AssertionError('unexpected provider request'))):
            for moment in (at(1, 43), at(3, 12)):
                self.assertIsNone(site.prepare_record(self.root, self.request, 'a' * 64, clock=lambda: moment))

    def test_an_approved_pair_still_waits_for_the_stored_start(self):
        self.approve_secondary()
        self.result_calls = []
        self.now = at(1, 49)
        report = self.run_secondary(self.site_page)
        self.assertEqual(report['state'], 'WAITING_FOR_OFFICIAL_START')
        self.assertEqual(self.result_calls, [])

    def test_existing_archived_race_is_preferred_even_with_approval(self):
        self.approve_secondary()
        documents = self.public_fixture()
        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}):
            with patch.object(capture, 'fetch_once', side_effect=AssertionError('fallback was requested')):
                report = self.run_shadow(fetcher=None, public_fetcher=lambda path, **_: documents[path])
        self.assertEqual(report['state'], 'SHADOW_PUBLIC_PODIUM_SCORED')

    def test_missing_approval_keeps_the_github_wait(self):
        self.result_calls = []
        report = self.run_secondary(self.site_page)
        self.assertEqual(report['state'], 'WAITING_FOR_GITHUB_PUBLIC_RESULT')
        self.assertEqual(len(self.result_calls), 2)

    def test_approval_cannot_substitute_a_different_race_source(self):
        self.approve_secondary(kdreams_url=KDREAMS.replace('/synthetic/', '/unbound/'))
        self.result_calls = []
        report = self.run_secondary(self.site_page)
        self.assertEqual(report['state'], 'HOLD_SECONDARY_RESULT_APPROVAL_INVALID')
        self.assertNotIn('scores', report)
        self.assertEqual(len(self.result_calls), 2)

    def test_a_denied_or_unbound_github_response_cannot_trigger_secondary_requests(self):
        self.approve_secondary()
        cases = [
            ({'status': 403}, 'HOLD_GITHUB_PUBLIC_RESULT_REFUSAL'),
            ({'status': 503}, 'HOLD_GITHUB_PUBLIC_RESULT_UNAVAILABLE'),
            ({'unexpected_url': True}, 'WAITING_FOR_GITHUB_PUBLIC_RESULT'),
            ({'absent': 'ref'}, 'WAITING_FOR_GITHUB_PUBLIC_RESULT'),
            ({'wrong_ref': True}, 'WAITING_FOR_GITHUB_PUBLIC_RESULT'),
        ]
        for options, expected in cases:
            with self.subTest(options=options), TemporaryDirectory(dir=self.root) as folder:
                # A fresh state namespace keeps the refusal and poll receipts isolated.
                real_root, self.root = self.root, Path(folder)
                try:
                    self.result_calls = []
                    after, self.now = self.now, at(1, 43)
                    self.assertEqual(self.run_secondary(self.site_page)['state'], 'WAITING_FOR_OFFICIAL_START')
                    self.now = after
                    report = self.run_secondary(self.site_page, **options)
                    self.assertEqual(report['state'], expected)
                    self.assertTrue(all(path.startswith(('git/ref/', 'contents/')) for path in self.result_calls))
                finally:
                    self.root = real_root

    def test_secondary_denial_is_persisted_before_touching_the_other_provider(self):
        self.approve_secondary()
        self.result_calls = []

        def denied(url):
            self.result_calls.append(url)
            raise capture.SourceCaptureError('PUBLIC_PROVIDER_HTTP_ERROR_STOP', http_status=407)

        report = self.run_secondary(denied, absent='results')
        self.assertEqual(report['state'], 'HOLD_SECONDARY_RESULT_PROVIDER_REFUSAL')
        self.now += timedelta(minutes=30)
        self.assertEqual(self.run_secondary(self.site_page, absent='results'), report)
        self.assertEqual(self.result_calls.count(KDREAMS + '?pageType=result'), 1)
        self.assertNotIn(NETKEIRIN, self.result_calls)

    def test_disagreement_cannot_score_the_shadow(self):
        self.approve_secondary()
        self.result_calls = []
        report = self.run_secondary(lambda url: self.site_page(url, podium='1-2-4'))
        self.assertEqual(report['state'], 'HOLD_SECONDARY_RESULT_DISAGREEMENT')
        self.assertNotIn('scores', report)

    def test_changed_raw_bytes_do_not_replay_a_matched_shadow(self):
        self.approve_secondary()
        self.result_calls = []
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'SHADOW_SECONDARY_PODIUM_SCORED')
        saved_raw = next(self.root.rglob('*.html'))
        saved_raw.write_bytes(b'changed')
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'HOLD_SECONDARY_RESULT_EVIDENCE_INVALID')
        self.assertEqual(len(self.result_calls), 4)

    def test_missing_actor_pin_does_not_recreate_a_previously_scored_result(self):
        self.approve_secondary()
        self.result_calls = []
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'SHADOW_SECONDARY_PODIUM_SCORED')
        pin_path = next(self.root.rglob('actor-pin.json'))
        pin_path.unlink()
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'HOLD_SECONDARY_RESULT_EVIDENCE_INVALID')
        self.assertFalse(pin_path.exists())
        self.assertEqual(len(self.result_calls), 4)

    def test_secondary_capture_can_resume_later_in_the_existing_public_result_window(self):
        self.approve_secondary()
        self.result_calls = []
        self.now = at(5, 20)
        self.assertEqual(self.run_secondary(self.site_page)['state'], 'SHADOW_SECONDARY_PODIUM_SCORED')

    def test_a_missing_parser_dependency_returns_a_hold_without_contacting_either_provider(self):
        self.approve_secondary()
        self.result_calls = []
        with patch.object(shadow, 'observe', side_effect=ModuleNotFoundError('fixture parser dependency')):
            try:
                report = self.run_secondary(self.site_page)
            except ImportError:
                self.fail('missing parser escaped the fallback instead of returning a hold')
        self.assertEqual(report['state'], 'HOLD_SECONDARY_RESULT_PARSER_UNAVAILABLE')
        self.assertEqual(len(self.result_calls), 2)

    def test_waits_for_official_start_even_after_the_scoring_cutoff(self):
        self.now = at(1, 49)
        self.assertEqual(self.run_shadow()['state'], 'WAITING_FOR_OFFICIAL_START')
        self.assertEqual(self.calls, [])

    def test_default_transport_requires_existing_opt_in(self):
        def unpublished(path, **_):
            raise HTTPError(path, 404, 'not published', {}, None)

        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}):
            with patch.object(official, '_http_get', side_effect=AssertionError('unapproved transport')):
                result = self.run_shadow(fetcher=None, public_fetcher=unpublished)
        self.assertEqual(result['state'], 'WAITING_FOR_GITHUB_PUBLIC_RESULT')
        self.assertEqual(result['official_state'], 'HOLD_OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED')

    def test_public_github_receipt_scores_only_the_two_source_podium(self):
        documents = self.public_fixture()
        calls = []

        def public_get(path, **_):
            calls.append(path)
            return documents[path]

        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}):
            with patch.object(official, '_http_get', side_effect=AssertionError('unapproved transport')):
                report = self.run_shadow(fetcher=None, public_fetcher=public_get)
                self.assertEqual(self.run_shadow(fetcher=None, public_fetcher=public_get), report)
        self.assertEqual(report['state'], 'SHADOW_PUBLIC_PODIUM_SCORED')
        self.assertEqual(report['scope'], 'TWO_SOURCE_MATCHED_PODIUM_ONLY')
        self.assertFalse(report['full_finish_verified'])
        self.assertEqual(report['scores'], {'saved': {'top4_3t': 0, 'top2_2t': 0},
                                           'challenger': {'top4_3t': 1, 'top2_2t': 1}})
        self.assertEqual(len(calls), 3)
        self.assertEqual(list(self.root.rglob('official-result.json')), [])

    def test_public_podium_holds_when_the_published_starting_field_changes(self):
        documents = self.public_fixture()
        roster = next(doc for doc in documents.values() if doc.get('schema') == 'KEIRIN_PUBLIC_RESULT_ROSTER_V1')
        roster['races'][0]['observed_riders'].pop()
        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}):
            report = self.run_shadow(fetcher=None, public_fetcher=lambda path, **_: documents[path])
        self.assertEqual(report['state'], 'HOLD_GITHUB_PUBLIC_RESULT_INVALID')
        self.assertNotIn('scores', report)

    def test_verifies_then_scores_both_books_and_reuses_the_immutable_receipt(self):
        before = (self.root / 'original.json').read_bytes()
        report = self.run_shadow()
        self.assertEqual(report['state'], 'SHADOW_RESULT_SCORED')
        self.assertEqual(report['scope'], 'OFFICIAL_COMPLETE_FINISH_RESEARCH')
        self.assertEqual(report['scores'], {'saved': {'top4_3t': 0, 'top2_2t': 0},
                                           'challenger': {'top4_3t': 1, 'top2_2t': 1}})
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(list(self.root.rglob('official-result.json'))), 1)
        self.assertEqual(self.run_shadow(), report)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual((self.root / 'original.json').read_bytes(), before)
        self.assertNotIn('999001', json.dumps(report))

    def test_hash_mismatch_and_same_car_different_registration_hold_without_fetching(self):
        path = self.root / 'original.json'
        path.write_bytes(path.read_bytes() + b' ')
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_INPUT_INVALID')
        self.original['input']['input']['riders'][0]['athlete_id'] = '910001'
        self.request = self.write_request()
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_INPUT_INVALID')
        self.assertEqual(self.calls, [])

    def test_replacing_the_original_and_its_request_after_cutoff_holds_before_fetch(self):
        self.original['forecasts']['all_96'] = self.original['forecasts']['saved']
        self.request = self.write_request()
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_INPUT_CHANGED_AFTER_PIN')
        self.assertEqual(self.calls, [])

    def test_starting_without_a_pre_cutoff_tick_holds_before_fetch(self):
        (self.root/'keirin-mac-shadow-results'/RACE/'request-pins.json').unlink()
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_PRE_CUTOFF_PIN_MISSING')
        self.assertEqual(self.calls, [])

    def test_expired_or_exhausted_shadow_stops_polls(self):
        self.data['JSJ018'].update(resultList=[], raceCount=0)
        self.now = at(2, 0)
        self.assertEqual(self.run_shadow()['state'], 'WAITING_FOR_OFFICIAL_FINAL')
        self.assertEqual(self.run_shadow()['state'], 'WAITING_FOR_OFFICIAL_POLL_INTERVAL')
        for _ in range(3):
            self.now += timedelta(minutes=15)
            self.assertEqual(self.run_shadow()['state'], 'WAITING_FOR_OFFICIAL_FINAL')
        self.now += timedelta(minutes=15)
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_POLL_LIMIT')
        self.assertEqual(len(self.calls), 4)
        self.now = at(4, 0)
        self.assertEqual(self.run_shadow()['state'], 'HOLD_SHADOW_POLL_EXPIRED')
        self.assertEqual(len(self.calls), 4)

    def test_refusal_never_retries_even_after_the_next_poll_interval(self):
        tried = []

        def denied(url):
            tried.append(url)
            raise HTTPError(url, 429, 'denied', {}, None)

        self.assertEqual(self.run_shadow(denied)['state'], 'HOLD_OFFICIAL_PROVIDER_REFUSAL')
        self.now += timedelta(minutes=15)
        self.assertEqual(self.run_shadow()['state'], 'HOLD_OFFICIAL_PROVIDER_REFUSAL')
        self.assertEqual(len(tried), 1)
        self.assertEqual(self.calls, [])

    def test_ordinary_payout_does_not_make_a_finish_with_withdrawal_scorable(self):
        self.data['JSJ012']['tyakujyunItemSubData'][-1]['tyaku'] = '落'
        report = self.run_shadow()
        self.assertEqual(report['state'], 'HOLD_SHADOW_FINISH_NOT_SCORABLE')
        self.assertNotIn('scores', report)
        self.assertEqual(len(list(self.root.rglob('official-result.json'))), 1)


if __name__ == '__main__':
    unittest.main()
