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
from scripts import keirin_mac_shadow_result as shadow
from scripts.keirin_official_day_pipeline import private_snapshot_json
from tests.test_keirin_official_public_source import DAY, RACE, fixtures, transport


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
                official_venue_source_sha256=cuts['source_sha256'], input=dict(race_id=RACE, riders=roster)),
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
        source_url = 'https://keirin.kdreams.jp/synthetic/racedetail/2620261002010001/'
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
        return {'git/ref/heads/state/keirin-public-results': {'object': {'sha': ref}},
                f'contents/rosters/{DAY}.json?ref={ref}': roster,
                f'contents/results/{DAY}.json?ref={ref}': results}

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
