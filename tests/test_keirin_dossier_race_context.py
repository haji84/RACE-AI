"""Source-free synthetic replay and public manifest checks."""
from copy import deepcopy
from datetime import timedelta
from tempfile import TemporaryDirectory
import json
import unittest

from race_ai import keirin_dossier_race_context as context
from race_ai import keirin_official_nationwide_records as records
from tests import test_keirin_official_nationwide_records as records_fixture


class DossierRaceContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records_fixture.NationwideRecordTests.setUpClass()

    def setUp(self):
        fixture = records_fixture.NationwideRecordTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with TemporaryDirectory() as folder:
            admitted, payload, raw, adjusted, packets, _ = fixture.comparison_fixture(folder)
        baseline_proof, condition_proof = records.verify_origins(admitted, raw, adjusted, packets)
        admitted['origin_receipts'] = {'baseline_origin': baseline_proof, 'condition_origin': condition_proof}
        admitted['condition_state'] = 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF'
        self.admitted = admitted
        self.payload = payload
        self.at = context._aware(admitted['baseline']['published_cutoff_at']) + timedelta(minutes=30)
        starters = [dict(number=row['car'], registration=row['athlete_id'])
                    for row in admitted['snapshot']['riders']]
        day, race = admitted['day_jst'], admitted['race_id']
        self.starters = dict(schema=context.STARTERS_SCHEMA, day=day, published_at=self.at.isoformat(),
            races=[dict(race_id=race, riders=starters), dict(race_id=race[:-2]+'02', riders=starters)])

    def test_official_replay_projects_numeric_facts_and_only_verified_past_history(self):
        row = context.project_sp_context(self.payload,self.admitted)
        self.assertEqual(len(row['riders']),7)
        source = self.payload['baseline_arguments']['prediction_source']
        self.assertEqual(row['comments_sha256'],source['expected_sha256'])
        self.assertEqual(context._aware(row['comments_at']),context._aware(source['observed_at']))
        self.assertGreater(len(row['riders'][0]['recent_results']),0)
        for rider in row['riders']:
            self.assertEqual(rider['comment'],{'state':'UNINTERPRETED'})
            self.assertIn('makuri_count',rider['stats'])
            self.assertTrue(all(result['day']<self.starters['day'] for result in rider['recent_results']))
        encoded = json.dumps(row,ensure_ascii=False)
        self.assertNotIn('架空コメント',encoded)
        self.assertNotIn('encp',encoded)
        self.assertNotIn('raw_bytes',encoded)
        self.assertNotIn('家族',encoded)

    def test_day_preserves_appearance_denominators_and_rejects_changed_public_state(self):
        row = context.project_sp_context(self.payload,self.admitted)
        packet = context.build_day(self.starters,[row],published_at=self.at)
        self.assertEqual(packet['coverage'],dict(registered_races=2,verified_races=1,
            registered_riders=14,verified_riders=7,comments_confirmed=0,comments_held=7,comments_missing=7))
        self.assertEqual(context.checked_day(json.loads(json.dumps(packet))),packet)
        broken = deepcopy(packet)
        broken['coverage']['comments_confirmed'] = 1
        with self.assertRaises(context.ContextHold):
            context.checked_day(broken)
        changed = deepcopy(row)
        changed['riders'][0]['comment'] = dict(state='SUMMARIZED',code='SOLO',summary='非公開内容')
        with self.assertRaises(context.ContextHold):
            context.build_day(self.starters,[changed],published_at=self.at)
        changed = deepcopy(row)
        changed['riders'][0]['registration'] = '999999'
        with self.assertRaises(context.ContextHold):
            context.build_day(self.starters,[changed],published_at=self.at)
        with self.assertRaises(context.ContextHold):
            context.build_day(self.starters,[row,row],published_at=self.at)

    def test_tampered_raw_body_and_unadmitted_condition_records_do_not_supply_data(self):
        changed=deepcopy(self.payload)
        changed['baseline_arguments']['prediction_source']['raw_bytes'] += b' '
        with self.assertRaisesRegex(ValueError,'BYTES_SHA_MISMATCH'):
            context.project_sp_context(changed,self.admitted)
        changed=deepcopy(self.admitted)
        changed['origin_receipts']['baseline_origin']['state']='STUB'
        with self.assertRaisesRegex(context.ContextHold,'ORIGINAL_BINDING'):
            context.project_sp_context(self.payload,changed)
        row=context.project_sp_context(self.payload,dict(self.admitted,condition_state='CONDITIONED_ORIGIN_PROOF_PENDING'))
        self.assertTrue(all(not rider['recent_results'] for rider in row['riders']))

    def test_comment_only_releases_paraphrase_and_unique_public_roster_reference(self):
        roster=[dict(car=1,name='試験　太郎'),dict(car=2,name='練習　次郎')]
        self.assertEqual(context._public_comment('自力で。余分な非公開内容',1,roster),
                         dict(state='SUMMARIZED',code='SELF_POWER',summary='自分で仕掛ける方針。'))
        self.assertEqual(context._public_comment('練習君に任せる。',1,roster),
                         dict(state='SUMMARIZED',code='FOLLOW',
                              summary='指定した選手の後ろで走る方針。',target_car=2))
        for raw in ('自力ではなく後ろ。','練習君と競る。','試験君。','相談中'):
            self.assertEqual(context._public_comment(raw,1,roster),{'state':'UNINTERPRETED'})
        self.assertEqual(context._public_comment('―',1,roster),{'state':'NOT_PUBLISHED'})
