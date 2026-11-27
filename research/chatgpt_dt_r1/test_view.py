"""Dashboard privacy, injection and evidence-label checks using synthetic aggregates."""
from copy import deepcopy
from html.parser import HTMLParser
import importlib
import json
from pathlib import Path
import re
import tempfile
import unittest

try:
    view = importlib.import_module('research.chatgpt_dt_r1.view')
except ModuleNotFoundError:
    view = None


def metrics(n=100, predicted=90, hits=20):
    return {
        'registered': n + 5, 'evaluable': n, 'predicted_evaluable': predicted,
        'prediction_coverage': predicted / n if n else None,
        'not_evaluable': {'MISSING': 3, 'DEAD_HEAT': 2}, 'holds': {'MISSING_PREDICTION': n - predicted},
        'trifecta': {str(k): {'hits': min(n, hits + k), 'all_target_rate': min(n, hits + k) / n if n else None,
                              'predicted_rate': min(n, hits + k) / predicted if predicted else None} for k in (1, 2, 4, 9, 12)},
        'exacta': {str(k): {'hits': hits + k, 'all_target_rate': (hits + k) / n if n else None} for k in (1, 2)},
        'proper_scores': {'n': predicted, 'joint_top3_log_loss': 4.1, 'exacta_log_loss': 2.8, 'multiclass_brier': .95},
    }


def report():
    return {
        'schema': 'dt-r1-real-archive-study-v1', 'model_sha256': 'a' * 64,
        'selected_candidate': 'full_with_pairs', 'final_period': metrics(),
        'evaluation_contract': {'splits': {
            'fit': {'start': '2025-10-01', 'end': '2026-06-30'},
            'tune': {'start': '2026-07-01', 'end': '2026-07-31'},
            'calibration': {'start': '2026-08-01', 'end': '2026-08-31'},
            'audit': {'start': '2026-09-01', 'end': '2026-09-30'},
            'test': {'start': '2026-10-01', 'end': '2026-11-22'}}, 'contract_sha256': 'b' * 64},
        'split_counts': {'fit': 1000, 'tune': 100, 'calibration': 100, 'audit': 100, 'test': 105},
        'source_audit': {'unique_races': 1405, 'dataset_sha256': 'c' * 64, 'sources': [
            {'file': 'keirin.db', 'sha256': 'd' * 64, 'bytes': 1024, 'rows': {'races': 1405}}]},
        'subgroups': {'field_size': {'7': metrics(20, 18, 4)}, 'class': {'L1': metrics(10, 8, 2)},
                     'venue': {'01': metrics(15, 12, 3)}},
        'fixed_policy_confidence_test': {'trifecta_4': {'HOT': {'n': 2, 'hits': 2, 'observed_rate': 1.0},
                                                      'HOLD': {'n': 98, 'hits': 22, 'observed_rate': 22 / 98}}},
        'fixed_policy_calibration': {'trifecta_4': {'calibration_rows': 100, 'audit_rows': 100}},
        'ablations_frozen_before_test': {'full_without_pairs': metrics(), 'full_with_pairs': metrics(),
                                        'without_history_with_pairs': metrics()},
        'three_way_contest': {'all_target': {'models': {
            'existing-integrated': {'forecast_n': 0, 'trifecta': {'hit_at': {'4': {'rate': .99}}}},
            'codex-new': {'forecast_n': 0},
            'chatgpt-dt-r1': {'forecast_n': 90, 'eligible_n': 100,
                'trifecta': {'hit_at': {'1': {'hits': 21, 'n': 100, 'rate': .21}, '4': {'hits': 24, 'n': 100, 'rate': .24}}},
                'exacta': {'hit_at': {'2': {'hits': 22, 'n': 100, 'rate': .22}}}}
            }}, 'common_cohort': {'eligible_n': 0}, 'verdict': {'winner': None}},
        'runtime': {'seconds': 12.5}, 'feature_count': 106, 'production_promoted': False,
    }


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements, self.dataset = [], ''
        self.in_dataset = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag == 'script' and attrs.get('id') == 'report-data':
            self.in_dataset = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_dataset = False

    def handle_data(self, data):
        if self.in_dataset:
            self.dataset += data


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(view, 'research dashboard is not implemented')

    def test_selected_without_context_candidate_is_visible_with_all_four_ablations(self):
        source = report()
        source['selected_candidate'] = 'without_context_with_pairs'
        source['ablations_frozen_before_test']['without_context_with_pairs'] = metrics()
        html = view.render_report(source)
        projected = json.loads(Document(html).dataset)
        self.assertEqual(projected['selected_candidate_id'], 'without_context_with_pairs')
        self.assertNotEqual(projected['selected_candidate'], '未確定')
        self.assertEqual(len(projected['ablations']), 4)
        self.assertIn('温度校正前', html)
        self.assertIn('主結果は校正後', html)

    def test_owner_report_cannot_be_written_under_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.git').mkdir()
            with self.assertRaisesRegex(ValueError, 'PRIVATE_STATE_MUST_BE_OUTSIDE_GIT'):
                view.write_owner_report(report(), [], root / 'private.html')
            # The aggregate projection is deliberately publishable.
            view.write_report(report(), root / 'aggregate.html')
            self.assertTrue((root / 'aggregate.html').is_file())

    def test_default_dashboard_omits_all_private_rows_and_unused_report_text(self):
        source = report()
        source.update(private_forecasts=[{'race_id': 'PRIVATE_RACE_SECRET', 'trifectas': [{'cars': [9, 8, 7]}]}],
                      riders=[{'name': 'PRIVATE_RIDER_SECRET'}], features=['PRIVATE_FEATURE_SECRET'],
                      api_key='PRIVATE_KEY_SECRET')
        source['three_way_contest']['common_cohort']['exclusions'] = [{'race_id': 'PRIVATE_EXCLUSION_SECRET'}]
        source['candidate_selection'] = {'private': {'raw_original': 'PRIVATE_ORIGINAL_SECRET'}}
        html = view.render_report(source)
        for secret in ('PRIVATE_RACE_SECRET', 'PRIVATE_RIDER_SECRET', 'PRIVATE_FEATURE_SECRET',
                       'PRIVATE_KEY_SECRET', 'PRIVATE_EXCLUSION_SECRET', 'PRIVATE_ORIGINAL_SECRET'):
            self.assertNotIn(secret, html)
        data = json.loads(Document(html).dataset)
        self.assertEqual(data['mode'], 'aggregate')
        self.assertNotIn('forecasts', data)

    def test_missing_rivals_show_no_fabricated_zero_or_supplied_fake_rate(self):
        data = json.loads(Document(view.render_report(report())).dataset)
        entrants = {row['id']: row for row in data['entrants']}
        self.assertEqual(entrants['existing-integrated']['status'], '未受領')
        self.assertEqual(entrants['codex-new']['status'], '未受領')
        self.assertIsNone(entrants['existing-integrated']['metrics'])
        self.assertIsNone(entrants['codex-new']['metrics'])
        self.assertEqual(data['verdict'], '勝敗未判定')

    def test_required_metric_counts_thresholds_and_retrospective_caveat(self):
        html = view.render_report(report())
        data = json.loads(Document(html).dataset)
        self.assertEqual(set(data['main']['trifecta']), {'1', '2', '4', '9', '12'})
        self.assertEqual(set(data['main']['exacta']), {'1', '2'})
        self.assertEqual(data['main']['evaluable'], 100)
        self.assertEqual(data['main']['not_evaluable']['DEAD_HEAT'], 2)
        self.assertEqual(data['confidence'][0]['ticket_limit'], 4)
        self.assertEqual(data['confidence'][0]['labels']['HOT']['n'], 2)
        for text in ('90%', '80%', '60%', '判定保留', '過去データの再検証', '未来の精度', 'オッズ連動', '最終1周'):
            self.assertIn(text, html)

    def test_subgroup_data_is_aggregate_only_and_missing_rates_are_not_zero(self):
        source = report()
        source['subgroups']['venue']['02'] = {'registered': 10, 'evaluable': 0, 'predicted_evaluable': 0}
        data = json.loads(Document(view.render_report(source)).dataset)
        self.assertEqual(set(data['subgroups']), {'field_size', 'class', 'venue'})
        self.assertEqual(data['subgroups']['field_size']['7']['evaluable'], 20)
        self.assertIsNone(data['subgroups']['venue']['02']['trifecta']['1']['all_target_rate'])

    def test_missing_coverage_breakdown_is_unknown_not_a_fabricated_zero(self):
        data = json.loads(Document(view.render_report({})).dataset)
        self.assertFalse(data['main'].get('holds_available', True))
        self.assertFalse(data['main'].get('exclusions_available', True))
        self.assertIsNone(data['main']['prediction_coverage'])

    def test_injection_does_not_create_executable_tags_or_network_sources(self):
        source = report()
        attack = '</script><script>alert("x")</script><img src="https://evil.invalid/x" onerror="alert(1)">\u2028\u2029'
        source['selected_candidate'] = attack
        source['subgroups']['venue'][attack] = metrics()
        source['source_audit']['sources'][0]['file'] = attack
        html = view.render_report(source)
        parsed = Document(html)
        self.assertEqual(sum(tag == 'script' for tag, _ in parsed.elements), 2)
        self.assertFalse(any(tag in ('img', 'iframe', 'object', 'embed', 'link') for tag, _ in parsed.elements))
        for tag, attrs in parsed.elements:
            self.assertFalse(any(key.lower().startswith('on') for key in attrs))
            self.assertFalse(any(str(v).startswith(('http:', 'https:', 'javascript:')) for v in attrs.values()))
        self.assertNotIn(attack, html)
        self.assertNotIn('\u2028', parsed.dataset)
        self.assertNotIn('\u2029', parsed.dataset)
        self.assertIsInstance(json.loads(parsed.dataset), dict)
        csp = next(attrs['content'] for tag, attrs in parsed.elements if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy')
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'none'", csp)

    def test_json_island_roundtrips_script_end_and_unicode_separators_safely(self):
        attack = '</script><script>alert(1)</script>&\u2028\u2029'
        payload = view._json_for_script({'value': attack})
        parsed = Document('<script id="report-data" type="application/json">' + payload + '</script>')
        self.assertEqual(sum(tag == 'script' for tag, _ in parsed.elements), 1)
        self.assertEqual(json.loads(parsed.dataset)['value'], attack)
        self.assertNotIn('</script>', payload)
        self.assertNotIn('\u2028', payload)
        self.assertNotIn('\u2029', payload)

    def test_owner_details_require_separate_explicit_entry_point(self):
        forecasts = [{'race_id': 'owner-race-synthetic', 'day': '2026-11-01', 'status': 'READY',
                      'trifectas': [{'cars': [1, 2, 3], 'probability': .2}],
                      'exactas': [{'cars': [1, 2], 'probability': .3}]}]
        public = view.render_report({**report(), 'forecasts': forecasts})
        private = view.render_owner_report(report(), forecasts)
        self.assertNotIn('owner-race-synthetic', public)
        self.assertIn('owner-race-synthetic', private)
        self.assertIn('所有者用', private)
        self.assertEqual(json.loads(Document(private).dataset)['mode'], 'owner_private')

    def test_writes_are_create_only_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.html'
            returned = view.write_report(report(), path)
            self.assertEqual(Path(returned), path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                view.write_report(report(), path)
            self.assertIn('DT-R1', path.read_text())


if __name__ == '__main__':
    unittest.main()
