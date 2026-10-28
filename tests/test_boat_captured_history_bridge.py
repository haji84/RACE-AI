"""Authored fictional K/B rows; no source access or historical predictions."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest

from tests.test_boat_observed_program_bridge import fixture as program_fixture, DAY, ASOF


def fixture():
    program, bsource = program_fixture()
    source = dict(source_id='k-history',
        source_url='https://www1.mbrace.or.jp/od2/K/203003/k300316.lzh',
        source_sha256='b' * 64, source_rights_ref='fictional-history-rights',
        captured_at='2030-03-17T07:00:00+09:00', published_at=None,
        evidence_basis='CAPTURED_BY_CLAIM')
    rows = []
    for number in (1, 2):
        for lane in range(1, 7):
            rows.append(dict(race_id=f'20300316-18-{number:02d}', lane=lane,
                racer_id=str(4000 + lane), course=lane,
                st=0.0 if number == 1 else .2, st_status='OK',
                finish=lane if number == 1 else 7-lane,
                race_at='2030-03-16T00:00:00+00:00', source_sha256='b' * 64))
    return program, bsource, rows, source


class CapturedHistoryBridgeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.boat_captured_history_bridge'),
                             'captured single-day history API missing')
        self.api = importlib.import_module('race_ai.boat_captured_history_bridge')

    def build(self, args=None, **kwargs):
        options = dict(event_date_jst=DAY, as_of=ASOF, race_revision=1)
        options.update(kwargs)
        return self.api.build_program_history_snapshot(*(fixture() if args is None else args), **options)

    def test_measured_means_counts_sources_and_unknown_publication(self):
        result = self.build()
        snapshot, audit = result['snapshot'], result['history_audit']
        self.assertEqual(len(snapshot['participants']), 6)
        self.assertEqual(len(snapshot['sources']), 2)
        self.assertIsNone(snapshot['sources'][1]['published_at'])
        self.assertEqual(snapshot['sources'][1]['evidence_basis'], 'CAPTURED_BY_CLAIM')
        self.assertEqual(audit['selection_policy'], 'ALL_SUPPLIED_STARTS_IN_SINGLE_SOURCE_DAY')
        self.assertEqual((audit['input_row_count'], audit['deduplicated_row_count']), (12, 12))
        for person in snapshot['participants']:
            finish, st = (person['features'][k] for k in ('recent_mean_finish', 'recent_mean_st'))
            self.assertEqual((finish['value'], st['value']), (3.5, .1))
            self.assertEqual((finish['sample_n'], st['sample_n']), (2, 2))
            for feature in (finish, st):
                self.assertEqual(feature['source_id'], 'k-history')
                self.assertEqual(feature['history']['total_n'], 2)
                self.assertEqual(feature['history']['ok_n'], 2)
                self.assertEqual(feature['history']['unresolved_n'], 0)
            self.assertIsNone(person['features']['national_win_rate']['sample_n'])
            self.assertEqual(person['missing']['course_mean_finish'], 'NO_VERIFIED_COURSE')
            self.assertEqual(person['missing']['exhibition_time_seconds'], 'MISSING')
        self.assertFalse(audit['source_bytes_authenticated'])
        self.assertFalse(audit['independent_availability_verified'])
        self.assertFalse(audit['whole_day_completeness_verified'])
        self.assertFalse(audit['official_prediction'])

    def test_finish_and_st_dispositions_have_independent_denominators(self):
        args = fixture()
        args[2][0].update(finish=None)  # OK/ST still observed.
        args[2][1].update(st=None, st_status='MISSING')  # Numeric finish still observed.
        out = self.build(args)['snapshot']['participants']
        self.assertEqual(out[0]['missing']['recent_mean_finish'], 'UNRESOLVED_DISPOSITION')
        self.assertEqual(out[0]['features']['recent_mean_st']['value'], .1)
        self.assertEqual(out[1]['features']['recent_mean_finish']['value'], 3.5)
        st = out[1]['features']['recent_mean_st']
        self.assertEqual((st['value'], st['sample_n'], st['history']['total_n'],
                          st['history']['missing_n']), (.2, 1, 2, 1))

    def test_f_l_not_numeric_st_and_absent_excluded(self):
        args = fixture()
        args[2][0].update(finish=None, st=None, st_status='F')
        args[2][1].update(finish=None, st=None, st_status='L')
        args[2][2].update(finish=None, st=None, st_status='ABSENT', course=None)
        out = self.build(args)
        people = out['snapshot']['participants']
        for ix, status in ((0, 'f_n'), (1, 'l_n')):
            self.assertEqual(people[ix]['missing']['recent_mean_finish'], 'UNRESOLVED_DISPOSITION')
            f = people[ix]['features']['recent_mean_st']
            self.assertEqual((f['sample_n'], f['history'][status], f['history']['total_n']), (1, 1, 2))
        self.assertEqual(people[2]['features']['recent_mean_finish']['sample_n'], 1)
        self.assertEqual(people[2]['features']['recent_mean_st']['history']['total_n'], 1)
        self.assertEqual(out['history_audit']['participants'][2]['absent_n'], 1)

    def test_all_non_ok_or_all_absent_stays_missing_not_zero(self):
        for status in ('F', 'L', 'MISSING', 'ABSENT'):
            args = fixture()
            for row in (args[2][0], args[2][6]):
                row.update(st=None, st_status=status, finish=None)
                if status == 'ABSENT':
                    row['course'] = None
            person = self.build(args)['snapshot']['participants'][0]
            self.assertNotIn('recent_mean_st', person['features'])
            self.assertNotIn('recent_mean_finish', person['features'])
            self.assertEqual(person['missing']['recent_mean_st'],
                             'NO_PRIOR_SAMPLES' if status == 'ABSENT' else 'UNRESOLVED_DISPOSITION')

    def test_empty_history_and_missing_racer_do_not_change_six_person_roster(self):
        args = fixture(); args[2].clear()
        result = self.build(args)
        self.assertEqual(len(result['snapshot']['participants']), 6)
        for row in result['snapshot']['participants']:
            self.assertEqual(row['missing']['recent_mean_finish'], 'NO_PRIOR_SAMPLES')
        args = fixture()
        for row in args[2]:
            if row['racer_id'] == '4001':
                row['racer_id'] = '9999'
        self.assertEqual(self.build(args)['snapshot']['participants'][0]['missing']['recent_mean_st'],
                         'NO_PRIOR_SAMPLES')

    def test_membership_identity_changes_when_a_whole_race_is_omitted(self):
        full = self.build()
        args = fixture(); args[2][:] = args[2][:6]
        subset = self.build(args)
        self.assertNotEqual(full['history_audit']['membership_sha256'], subset['history_audit']['membership_sha256'])
        self.assertNotEqual(full['snapshot']['participants'][0]['features']['recent_mean_finish']['history']['window_id'],
                            subset['snapshot']['participants'][0]['features']['recent_mean_finish']['history']['window_id'])
        self.assertFalse(subset['history_audit']['whole_day_completeness_verified'])

    def test_reordering_and_exact_duplicate_do_not_change_measurements_or_membership(self):
        full = self.build()
        args = fixture(); args[2].append(deepcopy(args[2][0])); args[2].reverse()
        out = self.build(args)
        self.assertEqual(out['snapshot'], full['snapshot'])
        self.assertEqual(out['history_audit']['membership_sha256'], full['history_audit']['membership_sha256'])
        self.assertEqual(out['history_audit']['input_row_count'], 13)
        self.assertEqual(out['history_audit']['deduplicated_row_count'], 12)

    def test_conflicts_partial_races_same_racer_two_venues_and_invalid_finishes_rejected(self):
        for mode in ('partial', 'conflict', 'racer', 'course', 'finish', 'two-venues'):
            args = fixture(); rows = args[2]
            if mode == 'partial': rows.pop()
            if mode == 'conflict':
                rows.append(dict(rows[0], st=.1))
            if mode == 'racer': rows[1]['racer_id'] = rows[0]['racer_id']
            if mode == 'course': rows[1]['course'] = 1
            if mode == 'finish': rows[1]['finish'] = 1
            if mode == 'two-venues':
                for row in rows[6:]: row['race_id'] = '20300316-19-02'
            with self.subTest(mode=mode), self.assertRaises(self.api.CapturedHistoryError):
                self.build(args)

    def test_target_future_wrong_source_sentinel_and_unsupported_columns_rejected(self):
        for mode in ('target', 'future', 'hash', 'sentinel', 'odds', 'result', 'bool', 'nan', 'large'):
            args = fixture()
            if mode in ('target', 'future'):
                digit = '17' if mode == 'target' else '18'
                args[3]['source_url'] = f'https://www1.mbrace.or.jp/od2/K/203003/k3003{digit}.lzh'
                for row in args[2]:
                    row['race_id'] = row['race_id'].replace('20300316', '203003'+digit)
                    row['race_at'] = f'2030-03-{digit}T00:00:00+00:00'
            if mode == 'hash': args[2][0]['source_sha256'] = 'c'*64
            if mode == 'sentinel': args[2][0]['race_at'] = '2030-03-16T01:00:00+00:00'
            if mode in ('odds', 'result'): args[2][0][mode] = 1
            if mode == 'bool': args[2][0]['finish'] = True
            if mode == 'nan': args[2][0]['st'] = float('nan')
            if mode == 'large': args[2][:] = args[2]*145
            with self.subTest(mode=mode), self.assertRaises(self.api.CapturedHistoryError):
                self.build(args)

    def test_capture_at_asof_equal_offsets_is_allowed_but_after_is_rejected(self):
        args = fixture(); args[3]['captured_at'] = '2030-03-16T23:00:00Z'
        self.assertEqual(self.build(args)['snapshot']['as_of'], ASOF)
        for value in ('2030-03-16T23:00:00.000001Z', '2030-03-15T14:59:59Z', 'not-time'):
            args[3]['captured_at'] = value
            with self.subTest(value=value), self.assertRaises(self.api.CapturedHistoryError):
                self.build(args)

    def test_known_publication_kept_but_impossible_or_contradictory_claim_rejected(self):
        args = fixture()
        args[3].update(published_at='2030-03-16T23:00:00+09:00', evidence_basis='SOURCE_PUBLISHED_AT_CLAIM')
        self.assertEqual(self.build(args)['snapshot']['sources'][1]['published_at'], args[3]['published_at'])
        for value in ('2030-03-17T07:00:01+09:00', '2030-03-15T23:59:59+09:00', None):
            args[3]['published_at'] = value
            with self.subTest(value=value), self.assertRaises(self.api.CapturedHistoryError): self.build(args)
        args = fixture(); args[3]['published_at'] = '2030-03-16T23:00:00+09:00'
        with self.assertRaises(self.api.CapturedHistoryError): self.build(args)

    def test_exact_source_identity_and_no_collision_with_b(self):
        for key, value in (('source_id', 'b-program'), ('source_sha256', 'a'*64),
            ('source_url', 'https://www1.mbrace.or.jp/od2/K/203003/k300316.lzh?m=1'),
            ('source_url', 'https://www1.mbrace.or.jp/od2/K/203002/k300316.lzh'),
            ('source_rights_ref', ''), ('evidence_basis', 'VERIFIED')):
            args = fixture(); args[3][key] = value
            with self.subTest(key=key), self.assertRaises(self.api.CapturedHistoryError): self.build(args)

    def test_outputs_detached_and_no_source_rows_as_model_fields(self):
        args = fixture(); before = deepcopy(args)
        out = self.build(args)
        out['snapshot']['sources'][1]['source_id'] = 'changed'
        out['history_audit']['participants'][0]['row_refs'][0]['lane'] = 99
        self.assertEqual(args, before)
        self.assertEqual(set(out['snapshot']['participants'][0]), {'lane', 'registration_no', 'features', 'missing'})

    def test_non_ascii_registration_rejected_in_b_and_k_before_model_output(self):
        for scope in ('b', 'k', 'both'):
            args = fixture()
            if scope in ('b', 'both'):
                args[0]['boats'][0]['racer_registration_id'] = '４００１'
            if scope in ('k', 'both'):
                for row in args[2]:
                    if row['racer_id'] == '4001': row['racer_id'] = '４００１'
            with self.subTest(scope=scope), self.assertRaises(self.api.CapturedHistoryError): self.build(args)

    def test_canonically_different_zero_duplicates_reject_in_both_orders(self):
        for reverse in (False, True):
            args = fixture()
            args[2].append(dict(args[2][0], st=-0.0))
            if reverse: args[2].reverse()
            with self.subTest(reverse=reverse), self.assertRaises(self.api.CapturedHistoryError): self.build(args)

    def test_actual_pinned_pairwise_model_consumes_both_sources_with_analysis_gate(self):
        from scripts.verify_observed_pairs_synthetic import PINS, ROOT
        ref = ROOT/'pr71-observed-pair-reference'
        for path, sha in PINS.items():
            self.assertEqual(hashlib.sha256((ref/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest(), sha)
        spec = importlib.util.spec_from_file_location('race_ai._r41_observed', ref/'race_ai/boat_observed_pairwise_models.py')
        model = importlib.util.module_from_spec(spec); spec.loader.exec_module(model)
        out = self.build()['snapshot']
        allowed = {(s['source_url'], s['source_rights_ref'], 'analysis') for s in out['sources']}
        suite = model.predict_pair(out, allow_source=lambda *args: args in allowed)
        self.assertEqual(len(suite['models']), 2)
        for row in suite['models'].values():
            self.assertEqual(len(row['ordered_top8']), 8)
            self.assertEqual(len(row['candidates']), 120)
        with self.assertRaises(model.ObservedPairwiseError):
            model.predict_pair(out, allow_source=lambda url, right, purpose: '/B/' in url)


if __name__ == '__main__':
    unittest.main()
