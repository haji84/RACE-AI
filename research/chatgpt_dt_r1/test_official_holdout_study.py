"""Synthetic contracts for saved official holdout replay."""
from datetime import datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1 import official_holdout_study as study


class OfficialHoldoutTests(unittest.TestCase):
    def test_cutoff_is_historical_evidence_clock_not_forecast_creation(self):
        day = study.DAYS[0]
        rid = day.replace('-', '') + '2401'
        cutoff = day + 'T03:15:00+00:00'
        store = SimpleNamespace(day=day, read=lambda *_: {'race_id': rid})
        meta = dict(cutoff_at=cutoff)
        before = datetime.fromisoformat(cutoff) - timedelta(minutes=15)
        clock = before.isoformat()
        official = dict(snapshot={'published_cutoff_at': cutoff},
                        origin_receipts={'baseline_origin': {'latest_server_evidence_at': clock}})
        history = object()
        rows = []

        def candidate(**opts):
            self.assertEqual(opts['clock'](), before)
            self.assertEqual(opts['venues'].records, ())
            rows.append(opts['official_history'])
            return {'race_id': rid, 'input_sha256': 'same-private-input',
                    'feature_status': 'READY',
                    'history_evidence': {'official_support': {'history_races': int(bool(rows[-1]))}}}, clock, {}

        joint = {ticket: 1/6 for ticket in permutations((1, 2, 3))}
        with (
            patch.object(study.records, 'admit_original', return_value=(official, {})),
            patch.object(study.shadow, '_candidate', side_effect=candidate),
            patch.object(study, '_joint', return_value=joint),
        ):
            pair = study._replay_pair(store, rid, meta, b'', None, object(), {}, history)
            self.assertEqual(tuple(pair['laws']), study.ARMS)
            self.assertEqual(pair['history_races'], 1)
            self.assertTrue(all(law is joint for law in pair['laws'].values()))
            self.assertEqual(rows, [history, None])
            rows.clear()
            with patch.object(study, '_adjust_residual', return_value=joint) as adjust:
                pair = study._replay_pair(store, rid, meta, b'', None, object(), {}, history,
                                          residual_context='fixture')
            self.assertEqual(tuple(pair['laws']), study.RESIDUAL_ARMS)
            self.assertEqual(rows, [history])
            self.assertEqual(adjust.call_args.args[0], 'fixture')
            official['origin_receipts']['baseline_origin']['latest_server_evidence_at'] = (
                before + timedelta(microseconds=1)).isoformat()
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_ORIGIN_AFTER_T15'):
                study._replay_pair(store, rid, meta, b'', None, object(), {}, history)
            self.assertEqual(len(rows), 1)

    def test_all_target_forecasts_precede_results_and_small_proper_scores_are_hidden(self):
        events = []
        stores = {}
        for day in study.DAYS:
            ids = [day.replace('-', '') + suffix for suffix in ('2401', '2402')]
            stores[day] = SimpleNamespace(repo='partial-reader', day=day, head=study.ARCHIVE_COMMIT, ids=ids,
                index={'originals': {ids[0]: {'evidence_sha256': 'original'}},
                       'results': {ids[0]: [{'evidence_sha256': 'result'}]}})

        def forecast(store, rid, *_):
            events.append(('forecast', rid))
            joint = {ticket: 1/6 for ticket in permutations((1, 2, 3))}
            return dict(history_races=1, laws={name: joint for name in study.ARMS})

        def outcome(store, rid, *_):
            events.append(('result', rid))
            if rid.endswith('2402') and store.day == study.DAYS[-1]:
                return {'race_id': rid, 'day': store.day, 'result_status': 'MISSING_SAVED_RESULT'}
            return {'race_id': rid, 'day': store.day, 'result_status': 'VERIFIED_NORMAL', 'top3': [1, 2, 3]}

        def prefetch(repo, head, paths, _):
            self.assertEqual((repo, head), ('partial-reader', study.ARCHIVE_COMMIT))
            stage = 'prefetch-result' if any(path.endswith('/result.sealed.json') for path in paths) else 'prefetch-original'
            events.append((stage, None))

        frozen = SimpleNamespace(to_dict=lambda: {'model_sha256': study.shadow.MODEL_SHA},
                                 fit_meta={'parameter_information_end_day': '2026-07-31'})
        with (
            patch.object(study.records, 'RecordStore', side_effect=lambda _, day, *, index_commit: stores[day]) as get,
            patch.object(study.settlement, '_load_registry', side_effect=lambda store, _: {
                'registered_race_ids': store.ids, 'day_inventory_complete': False, 'missing_venues': ['05']}),
            patch.object(study.settlement, '_result_row', side_effect=outcome),
            patch.object(study, 'OfficialHistory'),
            patch.object(study, '_replay_pair', side_effect=forecast),
            patch('race_ai.keirin_nationwide_cipher_history.prefetch_pinned_blobs', side_effect=prefetch),
        ):
            report = study.run_holdout(None, owner_private_pem=b'', trained=frozen, client=None,
                                      now=lambda: datetime(2026, 11, 28, tzinfo=timezone.utc))
            first_events = events.copy()
            events.clear()
            get.reset_mock()
            restricted = study.run_holdout(None, owner_private_pem=b'', trained=frozen, client=None,
                now=lambda: datetime(2026, 11, 28, tzinfo=timezone.utc), day=study.DAYS[-1])
            get.assert_called_once_with(None, study.DAYS[-1], index_commit=study.ARCHIVE_COMMIT)
            self.assertEqual([event for event, _ in events],
                             ['prefetch-original', 'forecast', 'prefetch-result', 'result', 'result'])
            events.clear()
            get.reset_mock()
            earlier = study.run_holdout(None, owner_private_pem=b'', trained=frozen, client=None,
                now=lambda: datetime(2026, 11, 28, tzinfo=timezone.utc), earlier_batch=True)
            self.assertEqual(tuple(earlier['evaluated_days']), study.DAYS[:-1])
            self.assertEqual(tuple(call.args[1] for call in get.call_args_list), study.DAYS[:-1])
            self.assertEqual([event for event, _ in events],
                             ['prefetch-original', 'forecast'] * 4 + ['prefetch-result', 'result', 'result'] * 4)
            with self.assertRaisesRegex(ValueError, 'HOLDOUT_BATCH_AND_DAY_CONFLICT'):
                study.run_holdout(None, owner_private_pem=b'', trained=frozen, client=None,
                    now=lambda: None, day=study.DAYS[-1], earlier_batch=True)
        self.assertEqual([event for event, _ in first_events],
                         ['prefetch-original', 'forecast'] * 5 + ['prefetch-result', 'result', 'result'] * 5)
        self.assertEqual((restricted['registered_races'], restricted['common_scorable_races']), (2, 1))
        self.assertEqual(restricted['state'], 'OFFICIAL_HOLDOUT_SCORED')
        self.assertNotIn('proper_scores', restricted)
        self.assertEqual(report['registered_races'], 10)
        self.assertEqual(report['source_holds']['SAVED_ORIGINAL_MISSING'], 5)
        self.assertEqual(report['official_scorable_races'], 9)
        self.assertEqual(report['common_scorable_races'], 5)
        self.assertEqual(report['metrics']['warm']['hits']['tri1'], 5)
        self.assertNotIn('proper_scores', report)
        self.assertFalse(report['prospectively_sealed'])
        self.assertEqual(report['venue_geometry'], 'OMITTED_POSTDATED_SIDECAR')

    def test_proper_scores_are_period_level_and_require_both_thresholds(self):
        def day(n):
            return {name: dict(n=n, **{metric: 0 for metric in study.RANK_METRICS + study.PROPER_METRICS})
                    for name in study.ARMS}
        for scores in ({'first': day(80)}, {'a': day(9), 'b': day(10), 'c': day(10)}):
            with self.subTest(scores=len(scores)):
                self.assertEqual(study._paired_metrics(scores)[1], {})
        scores = {name: day(10) for name in 'abc'}
        report = study._paired_metrics(scores)[1]
        self.assertIn('proper_scores', report)
        self.assertNotIn('a', report['proper_scores'])

    def test_residual_uses_fixed_unused_archive_and_only_two_matched_arms(self):
        events = []
        frozen = SimpleNamespace(to_dict=lambda: {'model_sha256': study.shadow.MODEL_SHA},
                                 fit_meta={'parameter_information_end_day': '2026-07-31'})
        law = {ticket: 1/6 for ticket in permutations((1, 2, 3))}

        def store(_, day, *, index_commit):
            self.assertEqual(index_commit, study.RESIDUAL_ARCHIVE)
            rid = day.replace('-', '') + '2401'
            return SimpleNamespace(day=day, head=index_commit, rid=rid, index={'originals': {rid: {}}, 'results': {}})

        def replay(source, rid, *_, residual_context):
            self.assertEqual(residual_context, 'frozen-candidate')
            events.append(('forecast', source.day))
            return dict(history_races=0, laws=dict.fromkeys(study.RESIDUAL_ARMS, law))

        def outcome(source, rid, *_):
            events.append(('result', source.day))
            return dict(race_id=rid, day=source.day, result_status='VERIFIED_NORMAL', top3=[1, 2, 3])

        with (
            patch.object(study.records, 'RecordStore', side_effect=store),
            patch.object(study.settlement, '_load_registry', side_effect=lambda source, _: {
                'registered_race_ids': [source.rid], 'day_inventory_complete': True, 'missing_venues': []}),
            patch.object(study.settlement, '_result_row', side_effect=outcome),
            patch.object(study, 'OfficialHistory'),
            patch.object(study, '_replay_pair', side_effect=replay),
            patch.object(study, '_prefetch_targets'),
        ):
            report = study.run_holdout(None, owner_private_pem=b'', trained=frozen, client=None,
                now=lambda: datetime(2026, 11, 29, tzinfo=timezone.utc), residual_context='frozen-candidate')
        self.assertEqual([kind for kind, _ in events], ['forecast', 'forecast', 'result', 'result'])
        self.assertEqual(report['fixed_period'], list(study.RESIDUAL_DAYS))
        self.assertEqual(report['archive_commit'], study.RESIDUAL_ARCHIVE)
        self.assertEqual(report['common_scorable_races'], 2)
        self.assertEqual(set(report['metrics']), set(study.RESIDUAL_ARMS))
        self.assertEqual(report['metrics']['winner_residual']['hits']['tri1'], 2)
        self.assertEqual(report['winner_residual_file_sha256'], study.RESIDUAL_FILE_SHA)
        self.assertNotIn('proper_scores', report)
        self.assertFalse(report['prospectively_sealed'])
