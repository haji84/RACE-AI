import unittest
from unittest.mock import patch

from scripts import keirin_generate_result_unread_analysis as ingest

from scripts import keirin_rider_context_study as study


def conditions():
    def model(ticket):
        return {arm:{'2t':{'candidates':[ticket[:2]],'selected':[ticket[:2]]},
                     '3t':{'candidates':[ticket],'selected':[ticket]}} for arm in ('A','B')}
    date = '2099-01-01'
    rows = [dict(race_id=f'20990101620{i}', cutoff_at=cutoff, baseline=model([1,2,3]), candidate=model([2,1,3]))
            for i, cutoff in ((1, date+'T11:00:00+09:00'), (2, date+'T10:02:00+09:00'))]
    study_data = dict(schema=study.FROZEN_SCHEMA, date=date, sealed_at=date+'T10:00:00+09:00',
                      windows={'2t':4,'3t':4}, pairs=rows)
    result = dict(winning_2t=[2,1], winning_3t=[2,1,3], observed_at=date+'T12:00:00+09:00',
                  authority='cross_source_reference', comparison_scope='POST_CUTOFF_REFERENCE')
    outcomes = dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=date, checked_at=date+'T12:01:00+09:00',
                    races=[dict(state='matched', race_id=row['race_id'],
                                comparison=dict(result,race_id=row['race_id'])) for row in rows])
    return study_data, outcomes


class RiderContextStudyTests(unittest.TestCase):
    def test_single_digit_hour_is_a_supported_published_cutoff(self):
        self.assertEqual(ingest.published_cutoff('2099-01-01','8:05').hour, 8)

    def test_limit_applies_equally_when_one_version_has_fewer_candidates(self):
        frame, outcomes = conditions()
        frame['pairs'][0]['candidate']['A']['3t']['candidates'] = [[3,2,1],[2,1,3]]
        report = study.score(frame, outcomes, witnessed_at='2099-01-01T10:03:00+09:00')
        run = report['metrics']['A']['3t']
        self.assertEqual(run['baseline']['fixed_window_points'], run['candidate']['fixed_window_points'])
        self.assertEqual(run['candidate']['fixed_window_hits'], 0)

    def test_witness_uses_github_ci_time_and_the_exact_published_commitment(self):
        frame, _ = conditions()
        frame.update(candidate_method='test', candidate_source_sha256='a'*64, baseline_source_sha256='b'*64)
        commit = 'c'*40
        run = dict(event='pull_request', path='.github/workflows/keirin-persistent-core-ci.yml',
                   repository={'full_name':'haji84/RACE-AI','id':1416489937},
                   head_sha=commit, created_at='2099-01-01T10:03:00+09:00')
        with patch.object(study, 'github_json', side_effect=[run,study.commitment(frame)]):
            self.assertEqual(study.github_witness(frame,commit,123), '2099-01-01T10:03:00+09:00')
        wrong = dict(study.commitment(frame), data_sha256='d'*64)
        with patch.object(study,'github_json',side_effect=[run,wrong]):
            with self.assertRaisesRegex(ValueError,'GITHUB_COMMITMENT_MISMATCH'):
                study.github_witness(frame,commit,123)

    def test_compares_same_races_where_github_readback_precedes_cutoff(self):
        frame, outcomes = conditions()
        result = study.score(frame, outcomes, witnessed_at='2099-01-01T10:03:00+09:00')
        self.assertEqual(result['eligible_pairs'], 1)
        self.assertEqual(result['compared_pairs'], 1)
        self.assertEqual(result['metrics']['A']['3t']['baseline']['fixed_window_hits'], 0)
        self.assertEqual(result['metrics']['A']['3t']['candidate']['fixed_window_hits'], 1)
        self.assertEqual(result['metrics']['B']['2t']['candidate']['selected_points'], 1)

    def test_before_frozen_and_special_results_cannot_score(self):
        frame, outcomes = conditions()
        outcomes['races'][0]['comparison']['observed_at'] = '2099-01-01T10:00:00+09:00'
        outcomes['races'][1] = dict(race_id='209901016202',state='held',reason='special_result')
        result = study.score(frame, outcomes, witnessed_at='2099-01-01T10:01:00+09:00')
        self.assertEqual(result['eligible_pairs'], 2)
        self.assertEqual(result['compared_pairs'], 0)
