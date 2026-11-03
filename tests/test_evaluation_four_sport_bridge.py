"""Fictional five-provider coverage, research seal and retained audit join only."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.actions_contract import digest
from race_ai.discovery_reconcile import CoverageError
from race_ai.evaluation_experiment import seal_predictions
from race_ai.four_sport_ledger_bridge import link_day
from race_ai.four_sport_ledger_bridge_cli import main

DAY = '2030-01-05'
VENUES = [('boat', 'boatrace-jcd-01', 'r-boat', 6),
          ('keirin', 'test-keirin', 'r-keirin', 7),
          ('autorace', 'test-autorace', 'r-autorace', 8),
          ('horse_jra', 'test-horse-jra', 'r-hj', 10),
          ('horse_local', 'test-horse-local', 'r-hl', 9)]
HORSES = {'r-hj': 'horse_jra', 'r-hl': 'horse_local'}


def inputs():
    refs = [{'sport': sport, 'venue': venue, 'race_numbers': [1, 2] if sport == 'boat' else [1]}
            for sport, venue, _, _ in VENUES]
    reference = {'scope': 'MANUAL_REFERENCE_ONLY', 'event_date_jst': DAY, 'venues': refs}
    records = [{'sport': sport, 'venue': venue, 'race_no': 1,
                'race_id': f'{sport}:{DAY}:{venue}:1', 'cutoff_verified': False,
                'prediction': None, 'no_forecast_reason': 'SOURCE_PERMISSION_NOT_VERIFIED'}
               for sport, venue, _, _ in VENUES]
    ledger = {'schema': 'RACE_AI_FORECAST_AUDIT_V1', 'dataset_status': 'AUDIT_ONLY',
              'event_date_jst': DAY, 'records': records}
    return reference, ledger


def sealed_fixture():
    plan = {'schema': 'RACE_AI_EVALUATION_PLAN_V1', 'experiment_id': 'fixture-v1',
            'declared_at': '2030-01-01T00:00:00Z', 'mode': 'RETROSPECTIVE_RESEARCH',
            'cohort_rule': 'all fictional provider races', 'discovery_sha256': 'd'*64,
            'windows': {'train_end': '2030-01-02', 'validation_end': '2030-01-03',
                        'test_end': DAY},
            'seen_race_ids': [], 'stages': ['P0'], 'result_source_ids': ['X'],
            'models': [{'model_id': 'm', 'version': '1', 'code_sha256': 'a'*64,
                        'artifact_sha256': None, 'trained_until': None, 'created_at': None}],
            'comparison_groups': [],
            'feature_policy': {'schema_id': 'fixture', 'transform_sha256': '9'*64,
                               'allowed_fields': ['rating']},
            'races': [{'race_id': rid, 'sport': 'horse' if sport.startswith('horse') else sport,
                       'venue': venue, 'race_no': 1, 'event_date_jst': DAY,
                       'cutoff_at': '2030-01-05T03:00:00Z', 'participants': list(range(1, n+1))}
                      for sport, venue, rid, n in VENUES]}
    plan['eligibility'] = [{'race_id': x['race_id'], 'stage': 'P0', 'model_id': 'm',
                            'eligible': True, 'reason': None} for x in plan['races']]
    contexts, outputs = [], []
    for race in plan['races']:
        ctx = {'race_id': race['race_id'], 'stage': 'P0',
               'as_of': '2030-01-05T01:00:00Z', 'features': {'rating': [1,2,3]},
               'sources': [{'source_id': 'X', 'sha256': 'e'*64,
                            'captured_at': '2030-01-05T00:00:00Z', 'published_at': None}]}
        contexts.append(ctx)
        is_missing = race['sport'] == 'keirin'
        outputs.append({'race_id': race['race_id'], 'stage': 'P0', 'model_id': 'm',
                        'context_sha256': digest(ctx), 'code_sha256': 'a'*64,
                        'artifact_sha256': None, 'generated_at': '2030-01-06T00:00:00Z',
                        'status': 'NO_FORECAST' if is_missing else 'PREDICTED',
                        'top8': [] if is_missing else [[1,2,3]],
                        'reason': 'INPUT_MISSING' if is_missing else None})
    return seal_predictions(plan, contexts, outputs, sealed_at='2030-01-06T00:00:01Z')


class FourSportBridgeTests(unittest.TestCase):
    def test_five_providers_and_missing_manual_race_are_not_discarded(self):
        ref, ledger = inputs()
        report = link_day(ref, ledger, sealed_bundles=[sealed_fixture()],
                          horse_authorities=HORSES)
        self.assertEqual(report['explicit_manual_reference_races'], 6)
        self.assertEqual(report['reported_race_identities'], 6)
        self.assertEqual(report['local_archived_slot_counts'],
                         {'NO_FORECAST': 1, 'PREDICTED': 4})
        self.assertEqual({row['sport'] for row in report['records']},
                         {'boat', 'keirin', 'autorace', 'horse_jra', 'horse_local'})
        missing = next(row for row in report['records'] if row['sport'] == 'boat' and row['race_no'] == 2)
        self.assertIn('MISSING_AUDIT_LEDGER_RECORD', missing['unresolved'])
        self.assertIsNone(report['formal_hit_at_8_all'])
        self.assertIsNone(report['formal_pre_cutoff_prediction_count'])
        self.assertFalse(report['official_completeness_verified'])
        self.assertTrue(all(not slot['formal_prediction_admitted'] for row in report['records']
                            for slot in row['archive_slots']))

    def test_missing_authority_and_tamper_fail_closed(self):
        ref, ledger = inputs()
        with self.assertRaisesRegex(CoverageError, 'HORSE_AUTHORITY_REQUIRED'):
            link_day(ref, ledger, sealed_bundles=[sealed_fixture()])
        tampered = sealed_fixture()
        tampered['outputs'][0]['top8'] = [[3,2,1]]
        with self.assertRaises(ValueError):
            link_day(ref, ledger, sealed_bundles=[tampered], horse_authorities=HORSES)

    def test_duplicate_archive_slot_rejected_instead_of_counted_twice(self):
        ref, ledger = inputs()
        seal = sealed_fixture()
        with self.assertRaisesRegex(CoverageError, 'DUPLICATE_MODEL_STAGE'):
            link_day(ref, ledger, sealed_bundles=[seal, seal], horse_authorities=HORSES)

    def test_manual_prediction_claim_stays_unverified(self):
        ref, ledger = inputs()
        ledger['records'][0]['prediction'] = {'ordered_top8': [[1,2,3]]}
        result = link_day(ref, ledger)
        item = next(row for row in result['records'] if row['sport'] == 'boat' and row['race_no'] == 1)
        self.assertIn('LEDGER_PREDICTION_CLAIM_NOT_INDEPENDENTLY_VERIFIED', item['unresolved'])
        self.assertFalse(result['external_pre_cutoff_receipts_verified'])

    def test_unknown_race_count_stays_unknown(self):
        ref, ledger = inputs()
        ref['venues'].append({'sport': 'keirin', 'venue': 'undisclosed', 'race_numbers': None})
        result = link_day(ref, ledger)
        self.assertEqual(result['unknown_reference_race_counts'], [['keirin', 'undisclosed']])
        self.assertIsNone(result['official_complete_denominator'])

    def test_retained_research_rows_link_by_explicit_boat_code_not_model_alias(self):
        ref, ledger = inputs()
        retained = {'schema': 'RACE_AI_RETAINED_AUDIT_REPORT_V1',
                    'mode': 'RETAINED_PREDICTION_AUDIT', 'final_test_eligible': False,
                    'import_sha256': 'b'*64,
                    'rows': [{'race_id': '20300105-01-01', 'stage': 'P0',
                              'model_id': 'm', 'model_version': '1',
                              'prediction_status': 'FORECAST', 'missing_reason': None}]}
        result = link_day(ref, ledger, retained_reports=[retained])
        boat = next(row for row in result['records'] if row['sport'] == 'boat' and row['race_no'] == 1)
        self.assertEqual(boat['archive_slots'][0]['archive_race_id'], '20300105-01-01')
        self.assertFalse(boat['archive_slots'][0]['formal_prediction_admitted'])
        retained['rows'][0]['race_id'] = '20300106-01-01'
        with self.assertRaisesRegex(CoverageError, 'DIFFERENT_EVENT_DATE'):
            link_day(ref, ledger, retained_reports=[retained])

    def test_offline_cli_create_only_and_never_official_pass(self):
        ref, ledger = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            src, audit, output = (Path(tmp)/n for n in ('source.json', 'ledger.json', 'report.json'))
            src.write_text(json.dumps(ref), encoding='utf-8')
            audit.write_text(json.dumps(ledger), encoding='utf-8')
            args = ['--reference',str(src),'--ledger',str(audit),'--output',str(output)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
                self.assertEqual(main(args), 3)
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['schema'], 'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1')
            self.assertFalse(saved['source_rights_verified'])

if __name__ == '__main__':
    unittest.main()
