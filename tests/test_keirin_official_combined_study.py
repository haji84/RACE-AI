from datetime import timedelta
from itertools import permutations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_official_combined_study as study


class CombinedStudyTests(unittest.TestCase):
    def setUp(self):
        self.start = model.when('2026-11-27T05:06:00Z')
        self.ids = [f'20261127730{n}' for n in range(1, 6)]
        self.events = []
        self.rows = {}
        self.store = SimpleNamespace(day='2026-11-27', head='f' * 40, index={
            'originals': {}, 'results': {},
        })
        for n, (race_id, offset) in enumerate(zip(self.ids, (-90, -60, -40, 0, 30), strict=True)):
            cutoff = self.start + timedelta(minutes=offset)
            self.store.index['originals'][race_id] = dict(cutoff_at=cutoff.isoformat(),
                                                         evidence_sha256='b' * 64)
            self.store.index['results'][race_id] = [dict(
                observed_at=(cutoff + timedelta(minutes=30)).isoformat(),
                evidence_sha256=f'{n:064x}', race_id=race_id,
            )]
            self.rows[race_id] = tuple(self.forecast(weight) for weight in study.WEIGHTS)

    def forecast(self, weight):
        def market(size, count):
            orders = list(permutations(range(1, 6), size))
            first = 0.1 + weight / 2
            return [dict(order=order, probability=first if n == 0 else (1 - first) / (count - 1))
                    for n, order in enumerate(orders)]

        return dict(cars=[1, 2, 3, 4, 5], trifectas=market(3, 60), exactas=market(2, 20),
                    component_weights={'component': weight})

    def run_study(self, *, freeze=None):
        def prepare(store, race_id, original, private, **kwargs):
            self.events.append(('prepare', race_id))
            return self.rows[race_id]

        def load(store, original, revision, private):
            race_id = revision['race_id']
            self.events.append(('result', race_id))
            cutoff = model.when(original['cutoff_at'])
            official = dict(race_id=race_id, official_cutoff_at=cutoff.isoformat(),
                            observed_at=(cutoff + timedelta(minutes=10)).isoformat(),
                            status='FINAL_NORMAL', refund_status='NONE', winning_triples=[[1, 2, 3]],
                            finishes=[dict(car=car, place=car, status='FINISHED') for car in range(1, 6)])
            return {}, dict(official_result=official), {}

        def save(stage, payload):
            self.events.append(('freeze', stage))
            return {'sealed_sha256': model.digest(payload)}

        with patch.object(study, '_prepare', side_effect=prepare), \
                patch.object(study.records, '_replay_saved_result', side_effect=load):
            return study.run(self.store, b'fixture-key', self.ids, holdout_from=self.start,
                             clock=lambda: self.start + timedelta(days=1), freeze=freeze or save)

    def test_forecasts_and_fitted_model_frozen_before_corresponding_results(self):
        report = self.run_study()
        self.assertEqual(self.events, [('prepare', race_id) for race_id in self.ids] + [
            ('freeze', 'candidates'), ('result', self.ids[0]), ('result', self.ids[1]),
            ('freeze', 'model'), ('result', self.ids[3]), ('result', self.ids[4]),
        ])
        self.assertEqual(report['model']['current_weight'], 0.75)
        self.assertEqual(report['coverage']['training_results'], 2)
        self.assertEqual(report['coverage']['holdout_results'], 2)
        self.assertLess(report['holdout']['trifecta_distribution']['fitted']['log_loss'],
                        report['holdout']['trifecta_distribution']['fixed']['log_loss'])

    def test_failed_freeze_leaves_every_result_unread(self):
        def fail(stage, payload):
            raise OSError('fixture refuses write')

        with self.assertRaises(OSError):
            self.run_study(freeze=fail)
        self.assertEqual(self.events, [('prepare', race_id) for race_id in self.ids])

    def test_failed_model_freeze_never_opens_later_outcomes(self):
        def fail_model(stage, payload):
            if stage == 'model':
                raise OSError('fixture refuses write')
            return {'sealed_sha256': model.digest(payload)}

        with self.assertRaises(OSError):
            self.run_study(freeze=fail_model)
        self.assertEqual(self.events[-2:], [('result', self.ids[0]), ('result', self.ids[1])])
