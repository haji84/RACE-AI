"""Eight fictional P1 cases, actual AES admission and twelve native fits."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.all_existing_model_learning import fit,verify_training
from race_ai import all_existing_model_pairs as pairs
from race_ai.all_existing_model_intake import records_from_private_artifact
from race_ai.boat_observed_pairwise_models import FEATURE_TRANSFORMS,MODEL_IDS as OBSERVED
from race_ai.boat_observed_pairwise_models import JST
from scripts import all_existing_model_learning as cli
from tests import test_all_existing_model_pairs as fixtures
from tests.test_all_existing_model_learning import observed_records
from tests.test_boat_venue_research import personal_data,SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER


class NativeCommonCohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training=fit(observed_records(),now=fixtures.NOW)

    def setUp(self):
        fixture=fixtures.AllExistingModelPrivatePairsTests(methodName='runTest')
        fixture.records=observed_records();fixture.training=self.training
        fixture.cell=next(iter(self.training['models']));fixture.setUp()
        self.addCleanup(fixture.doCleanups);self.fixture=fixture;self.root=fixture.root
        requests=[];self.results=[]
        for number in range(1,10):
            native=fixture.native(number);snapshot=native['snapshot'];snapshot['stage']='P1'
            cutoff=fixtures.FORECAST_NOW+timedelta(minutes=20+number)
            snapshot['sales_cutoff_at']=cutoff.isoformat();source=snapshot['sources'][0]['source_id']
            for entrant in snapshot['participants']:
                for name,value in (('exhibition_time_seconds',6.71+entrant['lane']*.01),
                                   ('exhibition_start_seconds',.10+entrant['lane']*.01)):
                    entrant['missing'].pop(name,None)
                    entrant['features'][name]=dict(value=value,sample_n=None,source_id=source,
                        transform_id=FEATURE_TRANSFORMS[name])
            extra=fixture.extra_native_requests(number)
            for request in extra:
                base=request['native_payload'].get('source',request['native_payload'].get('base_source'))
                base['cutoff_at']=cutoff.astimezone(JST).isoformat()
            requests.extend(extra)
            requests.extend(dict(cell_key='boat/'+mid,native_payload=deepcopy(native)) for mid in OBSERVED)
            if number<=8:
                self.results.append(dict(race_id=f'20300401-24-{number:02d}',sport='boat',status='settled',
                    ordered_top3=[1,2,3] if number%2 else [6,5,4],
                    captured_at=(cutoff+timedelta(minutes=1)).isoformat(),published_at=None,
                    source_ref='https://www.boatrace.jp/fictional/result/'+str(number),
                    source_rights_ref='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106',source_sha256=f'{number:064x}',
                    identity_verified=True,roster={str(p['lane']):p['registration_no'] for p in snapshot['participants']},
                    payout_per_100_yen=1230,refund_numbers=[]))
        pairs.make_private_pairs(fixture.context,requests,self.root/'pairs',now=fixtures.FORECAST_NOW,
                                 allow_source=lambda *_:True)
        self.raw,_=fixture.archive();self.metadata=fixture.metadata(self.raw)
        self.now=fixtures.FORECAST_NOW+timedelta(hours=1)
        self.native_records=records_from_private_artifact(self.raw,self.metadata,self.results,now=self.now,
            expected_run_id=99,expected_head_sha=fixtures.HEAD)['records']
        self.rows,self.old_observations=personal_data(8)
        self.dataset=self.root/'dataset.json';self.dataset.write_text(json.dumps(POINTER))
        self.archive=self.root/'archive';self.archive.mkdir(mode=0o700)
        for name,raw in (('archive.zip',self.raw),('metadata.json',json.dumps(self.metadata).encode())):
            path=self.archive/name;path.write_bytes(raw);path.chmod(0o600)

    def load(self,**options):
        # External JSON transports return invented data; ciphertext, native
        # capsule reader, result join and derivation remain the real code.
        with patch.object(cli,'load_verified_intake',return_value=deepcopy(
                (self.rows,self.old_observations+self.results,SOURCE,CONTENT))), \
                patch.object(cli,'_github_json',return_value=deepcopy(self.metadata)):
            return cli.load_intake(self.root/'restored','source',self.dataset,now=self.now,
                native_archive_dirs=[self.archive],derive_observed=True,**options)

    def test_archive_merge_precedes_derivation_and_common_eight_cases_make_twelve_cells(self):
        self.assertEqual(len(self.native_records),40)
        rows,binding,intake=self.load(cohort_size=8)
        self.assertEqual(len(rows),96);self.assertEqual(len({row['model_id'] for row in rows}),12)
        self.assertEqual(len([r for r in rows if 'input_derivation' in r]),56)
        self.assertEqual(intake['cohort_race_count'],8)
        self.assertEqual(intake['cohort_input_record_count'],40)
        self.assertFalse(intake['cohort_selected_by_winning_order'])
        self.assertEqual(intake['derived_input_availability_basis'],
                         'DERIVED_FROM_AUTHENTICATED_PRE_CUTOFF_NATIVE_CAPSULE')
        self.assertTrue(all(row['stage']=='P1' for row in rows))
        self.assertTrue(all(row['input_derivation']['schema'].endswith('_V2')
                            for row in rows if 'input_derivation' in row))
        trained=fit(rows,now=self.now)
        verify_training(trained)
        self.assertEqual(len(trained['models']),12)
        self.assertEqual({(m['unique_races'],m['train_races'],m['validation_races'])
                          for m in trained['models'].values()},{(8,6,2)})
        cohorts={(tuple(m['train_race_ids']),tuple(m['validation_race_ids'])) for m in trained['models'].values()}
        # Native adapters preserve documented BOAT aliases. Compare canonical
        # race identity rather than requiring identical identifier spelling.
        from race_ai.existing_model_dispatch import _race_key
        normalized={(tuple(_race_key(r,'boat') for r in train),tuple(_race_key(r,'boat') for r in valid))
                    for train,valid in cohorts}
        self.assertEqual(len(normalized),1)
        self.assertEqual(binding['intake_sha256'],cli._intake_identity(rows))

    def test_alias_selection_and_reexecution_preserve_data_scope_without_old_derived_clocks(self):
        races=[f'20300401-24-{i:02d}' if i%2 else f'boat:2030-04-01:boatrace-jcd-24:{i}' for i in range(1,9)]
        first,binding,_=self.load(cohort_race_ids=list(reversed(races)))
        later=self.now+timedelta(minutes=5);self.now=later
        second,new,_=self.load(cohort_race_ids=races)
        self.assertEqual(binding['intake_sha256'],new['intake_sha256'])
        self.assertNotEqual(digest(first),digest(second))
        self.assertTrue(all(r['input_derivation']['derived_at']==later.isoformat()
                            for r in second if 'input_derivation' in r))
        changed=deepcopy(self.native_records)
        for row in changed:row['result']['ordered_top3']=list(reversed(row['result']['ordered_top3']))
        selected,audit=cli._select_native_cohort(changed,size=8)
        self.assertEqual(audit['cohort_races_sha256'],cli._select_native_cohort(self.native_records,size=8)[1]['cohort_races_sha256'])

    def test_missing_native_cell_or_duplicate_alias_does_not_borrow_g7_or_fake_eighth_case(self):
        missing=self.native_records[1:]
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_RACES'):
            cli._select_native_cohort(missing,size=8)
        races=[f'20300401-24-{i:02d}' for i in range(1,9)]
        races[-1]='boat:2030-04-01:boatrace-jcd-24:1'
        with self.assertRaisesRegex(ValueError,'UNIQUE_RACES_REQUIRED'):
            cli._select_native_cohort(self.native_records,race_ids=races)
        with self.assertRaisesRegex(ValueError,'FIVE_FROZEN_CELLS_REQUIRED'):
            cli._select_native_cohort(self.native_records,race_ids=[f'20300401-24-{i:02d}' for i in range(2,10)])


if __name__=='__main__':unittest.main()
