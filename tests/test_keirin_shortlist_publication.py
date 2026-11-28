from collections import Counter
from copy import deepcopy
from datetime import datetime
from itertools import permutations
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from scripts import keirin_publish_shortlist_confidence as publication


DAY = '2026-11-25'
RACE = '202611257501'
FORECAST_AT = DAY + 'T16:00:00+09:00'
CUTOFF = DAY + 'T18:00:00+09:00'
RESULT_AT = DAY + 'T19:00:00+09:00'
END = '2026-11-26T00:00:00+09:00'
CARDS = list(range(1, 8))
KDREAMS = 'https://keirin.kdreams.jp/matsuyama/racedetail/7520261125010001/'
NETKEIRIN = 'https://keirin.netkeiba.com/race/result/?race_id=' + RACE


def _public_fixture():
    candidates = dict(schema=publication.public.REFERENCE_SCHEMA, day=DAY, published_at=FORECAST_AT,
                      races=[dict(race_id=RACE, cutoff_at=CUTOFF, saved_at=FORECAST_AT,
                                  a=[[1, 2, 3], [2, 3, 4]], b=[[3, 2, 1]])])
    roster = dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=DAY, generated_at=FORECAST_AT,
                  forecast_asset_sha256='c' * 64, races=[dict(
                      race_id=RACE, date=DAY, venue='松山', race_no=1, published_cutoff_at=CUTOFF,
                      source_url=KDREAMS, observed_riders=[dict(number=car) for car in CARDS])])
    comparison = dict(race_id=RACE, authority='cross_source_reference', comparison_scope='POST_CUTOFF_REFERENCE',
                      observed_at=RESULT_AT, winning_3t=[1, 2, 3], winning_2t=[1, 2],
                      payouts_100yen={'3t': 1000, '2t': 500},
                      sources=[dict(source_id='kdreams', url=KDREAMS + '?pageType=result', checked_at=RESULT_AT),
                               dict(source_id='netkeirin', url=NETKEIRIN, checked_at=RESULT_AT)])
    results = dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=DAY, checked_at=RESULT_AT,
                   races=[dict(race_id=RACE, state='matched', comparison=comparison)])
    return candidates, results, roster


class KeirinShortlistPublicationTests(unittest.TestCase):
    def test_official_annotations_score_exactly_the_public_displayed_points(self):
        # A hit at position nine must not count in the eight-point projection.
        a = list(permutations(CARDS, 3))[:12]
        winner = a[8]
        b = [winner, *a[:3]]
        original = dict(baseline_sealed_at=FORECAST_AT, baseline={
            arm: {'model': name} for arm, name in [('A', publication.model.MODEL_A),
                                                  ('B', publication.model.MODEL_B)]})
        scored = dict(official_result=dict(observed_at=RESULT_AT))
        prior = dict(observed_at=RESULT_AT)
        future = dict(observed_at=END)
        store = SimpleNamespace(index={'originals': {RACE: {'fixture': 'original'}},
                                      'results': {RACE: [prior, future]}})
        coverage = Counter()
        extracted = (datetime.fromisoformat(CUTOFF), True, {winner: 1000}, {'A': a, 'B': b}, {})
        with (patch.object(publication.records, '_replay_saved_result', return_value=(original, scored, None)) as replay,
              patch.object(publication.measured, '_result_measurements', return_value=extracted)):
            rows = list(publication._official_observations(store, b'', datetime.fromisoformat(END), coverage))
        replay.assert_called_once_with(store, store.index['originals'][RACE], prior, b'')
        self.assertEqual([(r.lane, r.arm, r.points, r.hit) for r in rows],
                         [('official', 'A', 8, False), ('official', 'B', 4, True)])
        self.assertEqual(coverage, {'prior_results': 1, 'scored_races': 1})

    def test_only_prior_revisions_and_pre_cutoff_originals_are_admitted(self):
        late = dict(observed_at=END)
        prior = dict(observed_at=RESULT_AT)
        store = SimpleNamespace(index={'originals': {RACE: {}}, 'results': {RACE: [late]}})
        coverage = Counter()
        with patch.object(publication.records, '_replay_saved_result') as replay:
            self.assertEqual(list(publication._official_observations(store, b'', datetime.fromisoformat(END), coverage)), [])
            replay.assert_not_called()
        self.assertEqual(coverage['result_not_available_before_target'], 1)

        store.index['results'][RACE] = [prior]
        original = dict(baseline_sealed_at=CUTOFF)
        extracted = (datetime.fromisoformat(CUTOFF), True, {(1, 2, 3): 1000}, {}, {})
        with (patch.object(publication.records, '_replay_saved_result',
                           return_value=(original, {'official_result': {'observed_at': RESULT_AT}}, None)),
              patch.object(publication.measured, '_result_measurements', return_value=extracted)):
            self.assertEqual(list(publication._official_observations(store, b'', datetime.fromisoformat(END), coverage)), [])
        self.assertEqual(coverage['held'], 1)

    def test_public_reference_scorer_uses_separately_pinned_result_and_roster(self):
        reference, results, roster = _public_fixture()
        registry = dict(schema=publication.public.SCHEMA, day=DAY, published_at=FORECAST_AT,
                        races=[dict(race_id=RACE, cutoff_at=CUTOFF, status='pending',
                                    saved_at=None, a=[], b=[])])
        forecast_store = Mock()
        forecast_store.read_previous.side_effect = (
            json.dumps(registry).encode(), json.dumps(reference).encode(), None,
        )
        result_store = Mock()
        repo = object()
        with patch.object(publication.archive, 'read_blob_bytes',
                          side_effect=(json.dumps(results).encode(), json.dumps(roster).encode())) as read:
            actual = list(publication._published_observations(
                repo, forecast_store, 'a' * 40, result_store, 'b' * 40, [DAY]))
        forecast_store.fetch.assert_called_once_with('a' * 40)
        result_store.fetch.assert_called_once_with('b' * 40)
        self.assertEqual([call.args for call in forecast_store.read_previous.call_args_list],
                         [('a' * 40, f'{folder}/{DAY}.json')
                          for folder in ('forecasts', 'references', 'research')])
        self.assertEqual([(call.args[1], call.args[2]) for call in read.call_args_list],
                         [('b' * 40, f'results/{DAY}.json'), ('b' * 40, f'rosters/{DAY}.json')])
        self.assertEqual([(r.lane, r.arm, r.race_id, r.points, r.hit) for r in actual],
                         [('reference', 'A', RACE, 2, True), ('reference', 'B', RACE, 1, False)])

    def test_public_scorer_holds_cutoff_conflict_late_forecast_and_changed_roster(self):
        reference, results, roster = _public_fixture()
        research = dict(schema=publication.public.RESEARCH_SCHEMA, day=DAY, published_at=FORECAST_AT,
                        races=[dict(race_id=RACE, cutoff_at=CUTOFF, generated_at=FORECAST_AT,
                                    starter_cars=CARDS[:6], a=[[1, 2, 3]], b=[])])
        self.assertEqual(list(publication._public_observations(DAY, {'racecard': research}, results, roster)), [])
        research['races'][0]['starter_cars'] = CARDS
        research['published_at'] = CUTOFF
        self.assertEqual(list(publication._public_observations(DAY, {'racecard': research}, results, roster)), [])
        research['published_at'] = FORECAST_AT
        actual = list(publication._public_observations(DAY, {'racecard': research}, results, roster))
        self.assertEqual([(r.lane, r.arm, r.points, r.hit) for r in actual], [('racecard', 'A', 1, True)])
        for field, time in (('cutoff_at', DAY + 'T17:00:00+09:00'), ('saved_at', CUTOFF)):
            altered = deepcopy(reference)
            altered['races'][0][field] = time
            self.assertEqual(list(publication._public_observations(DAY, {'reference': altered}, results, roster)), [])
        premature = deepcopy(results)
        premature['races'][0]['comparison']['observed_at'] = FORECAST_AT
        self.assertEqual(list(publication._public_observations(DAY, {'reference': reference}, premature, roster)), [])
