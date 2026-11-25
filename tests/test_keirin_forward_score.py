from hashlib import sha256
import json
import unittest

from scripts.keirin_forward_score import score


def encode(doc):
    return json.dumps(doc, sort_keys=True).encode()


def fixtures():
    day = '2026-11-25'
    cutoff = day + 'T16:00:00+09:00'
    observed = day + 'T16:18:00+09:00'
    rows, entries, matches = [], [], []
    for number in range(1, 7):
        rid = '2026112562' + f'{number:02d}'
        source = f'https://keirin.kdreams.jp/hiroshima/racedetail/62202611250100{number:02d}/'
        rows.append(dict(race_id=rid, cutoff_at=cutoff, published=[[1, 2, 3], [2, 1, 3]],
                         trial=[[3, 1, 2], [2, 1, 3]], points=1))
        entries.append(dict(race_id=rid, date=day, venue='広島', race_no=number, published_cutoff_at=cutoff,
                            source_url=source, observed_riders=[{'number':n} for n in (1,2,3)]))
        if number <= 3:
            order = [[3,1,2], [1,2,3], [2,1,3]][number-1]
            comparison = dict(race_id=rid, observed_at=observed, authority='cross_source_reference',
                              comparison_scope='POST_CUTOFF_REFERENCE', winning_3t=order, winning_2t=order[:2],
                              payouts_100yen={'2t':100, '3t':250},
                              sources=[dict(source_id='kdreams', checked_at=observed, url=source+'?pageType=result'),
                                       dict(source_id='netkeirin', checked_at=observed,
                                            url='https://keirin.netkeiba.com/race/result/?race_id='+rid)])
            matches.append(dict(race_id=rid, state='matched', comparison=comparison))
        elif number < 6:
            state, reason = ('held','source_disagreement') if number == 4 else ('pending','result_unpublished')
            matches.append(dict(race_id=rid, state=state, reason=reason))
    rows[2]['points'] = 2
    return (dict(schema='KEIRIN_FORWARD_PREDICTIONS_V1', races=rows),
            dict(schema='KEIRIN_FORWARD_RECEIPT_V1', frozen_at=day+'T05:00:00Z'),
            dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', generated_at=day+'T01:00:00Z',
                 date=day, forecast_asset_sha256='a'*64, races=entries),
            dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=day, checked_at=observed, races=matches))


class ForwardScoreTests(unittest.TestCase):
    def setUp(self):
        self.frame, self.receipt, self.roster, self.results = fixtures()

    def run_score(self):
        predictions = encode(self.frame)
        receipt = dict(prediction_sha256=sha256(predictions).hexdigest(), **self.receipt)
        return score(predictions, encode(receipt), encode(self.roster), encode(self.results))

    def test_current_public_schema_matched_only_at_declared_budget(self):
        self.receipt.update(comparators={'published':'existing', 'trial':'candidate'},
                            normalized_at='2026-11-25T20:00:00Z', timestamp_semantics='original_ticket_forecast_freeze')
        report = self.run_score()
        self.assertEqual(report['comparators'], self.receipt['comparators'])
        self.assertEqual(report['receipt_normalized_at'], self.receipt['normalized_at'])
        self.assertEqual(report['result_states'], {'matched':3, 'held':1, 'pending':1, 'missing':1})
        self.assertEqual((report['registered'], report['matched'], report['tickets_per_arm']), (6, 3, 4))
        self.assertEqual((report['published_hits'], report['trial_hits']), (2, 2))
        self.assertEqual(report['gained'], ['202611256201'])
        self.assertEqual(report['lost'], ['202611256202'])
        # An additional order after the 1-point cutoff does not score.
        self.frame['races'][2]['points'] = 1
        report = self.run_score()
        self.assertEqual((report['published_hits'], report['trial_hits'], report['tickets_per_arm']), (1, 1, 3))

    def test_optional_flow_is_bound_to_frozen_original_and_does_not_change_finish_scores(self):
        for row in self.frame['races']:
            row['flow'] = {side: {'INITIAL':[1,2,3], 'INITIATIVE':1}
                           for side in ('published', 'trial')}
        raw = encode(self.frame)
        receipt = encode(dict(prediction_sha256=sha256(raw).hexdigest(), **self.receipt))
        facts = dict(schema='KEIRIN_FLOW_OBSERVATIONS_V1', forecast_sha256=sha256(raw).hexdigest(),
                     recorded_at='2026-11-25T20:00:00+09:00', races=[dict(
                         race_id=self.frame['races'][0]['race_id'], observations=[dict(
                             race_id=self.frame['races'][0]['race_id'], aspect='INITIATIVE', observed=2, complete=True,
                             source='user', receipt=dict(reference='synthetic:report',
                                         recorded_at='2026-11-25T19:00:00+09:00', sha256=None))])])
        args = (raw, receipt, encode(self.roster), encode(self.results))
        legacy = score(*args)
        report = score(*args, flow_observations_raw=encode(facts))
        self.assertEqual({k:v for k,v in report.items() if k != 'flow_evaluation'}, legacy)
        evaluation = report['flow_evaluation']
        self.assertEqual(evaluation['published']['categories']['E'], 3)
        self.assertEqual(evaluation['published']['provisional_categories']['D'], 1)
        self.assertEqual(evaluation['trial']['provisional_categories']['B'], 1)
        self.assertEqual(evaluation['registered'], 6)
        self.assertEqual(evaluation['result_unavailable'], 3)
        self.assertNotIn('phase_orders', json.dumps(evaluation))
        facts['forecast_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'FLOW_FORECAST_SHA'):
            score(*args, flow_observations_raw=encode(facts))

    def test_flow_not_saved_before_cutoff_cannot_be_added_by_observations(self):
        raw = encode(self.frame)
        receipt = encode(dict(prediction_sha256=sha256(raw).hexdigest(), **self.receipt))
        facts = dict(schema='KEIRIN_FLOW_OBSERVATIONS_V1', forecast_sha256=sha256(raw).hexdigest(),
                     recorded_at='2026-11-25T20:00:00+09:00', races=[dict(
                         race_id=self.frame['races'][0]['race_id'], observations=[dict(
                             race_id=self.frame['races'][0]['race_id'], aspect='INITIATIVE', observed=2, complete=True,
                             source='video', receipt=dict(reference='synthetic:frame',
                                         recorded_at='2026-11-25T19:00:00+09:00', sha256='a'*64))])])
        report = score(raw, receipt, encode(self.roster), encode(self.results), flow_observations_raw=encode(facts))
        for side in ('published', 'trial'):
            self.assertEqual(report['flow_evaluation'][side]['categories'], {'A':0, 'B':0, 'C':0, 'D':0, 'E':3})

    def test_postcutoff_normalized_flow_is_excluded_while_original_finish_scoring_continues(self):
        for row in self.frame['races']:
            row['flow']={side:{'INITIATIVE':1} for side in ('published','trial')}
        raw=encode(self.frame)
        receipt=encode(dict(prediction_sha256=sha256(raw).hexdigest(), **self.receipt,
                            normalized_at='2026-11-25T20:00:00Z',
                            timestamp_semantics='original_ticket_forecast_freeze'))
        facts=dict(schema='KEIRIN_FLOW_OBSERVATIONS_V1',forecast_sha256=sha256(raw).hexdigest(),
                   recorded_at='2026-11-26T00:00:00Z',races=[])
        args=(raw,receipt,encode(self.roster),encode(self.results))
        legacy=score(*args)
        report=score(*args,flow_observations_raw=encode(facts))
        self.assertEqual(legacy,{k:v for k,v in report.items() if k!='flow_evaluation'})
        self.assertEqual(report['matched'],3)
        for side in ('published','trial'):
            self.assertEqual(report['flow_evaluation'][side]['categories'],dict.fromkeys('ABCDE',0))
            self.assertEqual(report['flow_evaluation'][side]['origin_not_admitted'],6)

    def test_wrong_forecast_bytes_or_unbound_cutoff_cannot_score(self):
        receipt = dict(prediction_sha256='f'*64, **self.receipt)
        with self.assertRaisesRegex(ValueError, 'DIGEST_MISMATCH'):
            score(encode(self.frame), encode(receipt), encode(self.roster), encode(self.results))
        self.frame['races'][0]['cutoff_at'] = '2026-11-25T21:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'CUTOFF_MISMATCH'):
            self.run_score()
        self.frame['races'][0]['cutoff_at'] = self.roster['races'][0]['published_cutoff_at']
        self.receipt['frozen_at'] = self.frame['races'][0]['cutoff_at']
        with self.assertRaisesRegex(ValueError, 'AT_OR_AFTER'):
            self.run_score()

    def test_duplicate_rows_or_duplicate_orders_cannot_inflate_hits(self):
        for document in (self.frame, self.results, self.roster):
            with self.subTest(schema=document['schema']):
                document['races'].append(document['races'][0])
                with self.assertRaises(ValueError):
                    self.run_score()
                document['races'].pop()
        self.frame['races'][0]['trial'] *= 2
        with self.assertRaisesRegex(ValueError, 'INVALID_ANALYSIS_TICKETS'):
            self.run_score()

    def test_no_silent_budget_reduction(self):
        self.frame['races'][2]['trial'] = [[2,1,3]]
        with self.assertRaisesRegex(ValueError, 'FEWER_TICKETS'):
            self.run_score()

    def test_conflicting_or_early_matched_evidence_cannot_score(self):
        row = self.results['races'][0]['comparison']
        for field, invalid in [('winning_2t',[2,1]), ('observed_at','2026-11-24T12:00:00Z'),
                               ('sources',[row['sources'][0],row['sources'][0]])]:
            with self.subTest(field=field):
                original = row[field]
                row[field] = invalid
                with self.assertRaises(ValueError):
                    self.run_score()
                row[field] = original
        row['sources'][0]['checked_at'] = '2026-11-25T01:00:00Z'
        with self.assertRaisesRegex(ValueError, 'INVALID_SOURCE_TIME'):
            self.run_score()
