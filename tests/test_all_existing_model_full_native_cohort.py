"""Authored native originals; full selection never recalculates old bytes."""
from copy import deepcopy
from datetime import datetime,timedelta
import base64
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.all_existing_model_learning import fit,verify_training
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.all_existing_model_intake import records_from_private_artifact
from race_ai.boat_all_model_inputs import build_native_inputs
from race_ai.boat_history_store import HistoryStore
from race_ai.boat_venue_learning import seal_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.four_sport_learning import LEARNED_ID
from scripts import all_existing_model_learning as cli
from scripts import all_existing_model_learning_ci as ci
from tests import test_all_existing_model_learning_ci as fixtures
from tests.test_all_existing_model_learning import observed_records
from tests.test_all_existing_model_matrix import _shift_dates
from tests.test_boat_all_model_inputs import official_inputs,ASOF
from tests.test_boat_pdca_history_inputs import retain_days
from tests.test_boat_venue_research import SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER


class FullNativeManifestTests(unittest.TestCase):
    def test_v3_selects_original_fourteen_cell_cohort_without_derivation(self):
        fixture=fixtures.ExistingModelLearningCiTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        manifest=deepcopy(fixture.manifest)
        manifest.update(schema='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V3',
            full_native_boat_cohort=True,keep_other_sports=False)
        seen=[]
        def fit(arguments,*,now):
            seen.extend(arguments)
            print(json.dumps(dict(state='FITTED_SHADOW_ONLY',fitted_model_count=14,derived_record_count=0)))
            return 0
        code,summary,_=fixture.invoke(manifest,fit=fit)
        self.assertEqual(code,0)
        self.assertIn('--full-native-boat-cohort',seen);self.assertNotIn('--derive-from-observed',seen)
        self.assertNotIn('--keep-other-sports',seen)
        self.assertEqual(summary['fitted_model_count'],14)
        self.assertEqual(summary['derived_record_count'],0)


class FullNativeOriginalIntegrationTests(unittest.TestCase):
    def test_eight_actual_cipher_admissions_keep_all_112_native_originals_and_fit_fourteen(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode())
        env.start();self.addCleanup(env.stop)
        records=json.loads(json.dumps(observed_records()).replace('2030-04-01','2030-01-01').replace('20300401','20300101'))
        for row in records:
            row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['scope']=row['scope']
            row['native_payload']['snapshot']['scope']=row['scope'];row['input_sha256']=digest(row['native_payload'])
        training=fit(records,now=datetime.fromisoformat('2030-01-02T00:00:00+00:00'),
            allow_source=lambda *_:True,allow_training=lambda *_:True)
        candidate=root/'candidate'
        seal_candidate(dict(training=training,excluded=[],summary=dict(state=training['state'],
            fitted_model_count=2,production_promoted=False,actual_purchases=False,plaintext_published=False)),candidate)
        def packed(members):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,raw in members:archive.writestr(name,raw)
            return output.getvalue()
        candidate_raw=packed((name,(candidate/name).read_bytes()) for name in ('learning.enc','learning.json','summary.json'))
        base_meta=dict(id=700,name='all-existing-model-learning-42-1',expired=False,size_in_bytes=len(candidate_raw),
            digest='sha256:'+sha256(candidate_raw).hexdigest(),created_at='2030-01-02T00:00:02+00:00',
            expires_at='2030-02-01T00:00:00+00:00',workflow_run=dict(id=42,head_sha='a'*40,
                repository_id=1416489937,head_repository_id=1416489937))
        context=context_from_encrypted_artifact(candidate_raw,700,now=datetime.fromisoformat(ASOF),_fetch=lambda _:base_meta)
        history=HistoryStore(root/'history.sqlite');self.addCleanup(history.close);retain_days(history)
        artifacts=[];observations=[];metadata_by_id={};expected=[]
        final=datetime.fromisoformat('2030-01-23T00:00:00+00:00')
        for number in range(8):
            program,before=official_inputs(lanes=(1,2,3,4,5,6))
            program=_shift_dates(program,number);before=_shift_dates(before,number)
            asof=datetime.fromisoformat(_shift_dates(ASOF,number))
            built=build_native_inputs(program,before,as_of=asof.isoformat(),
                history_context=dict(history_store=history,history_identity_verified=True,owner_reviewed=True))
            native=built['native_inputs'];native['shared_learned']=deepcopy(native['shared'])
            requests=[dict(cell_key=cell['cell_key'],native_payload=deepcopy(native[cell['group']]))
                for cell in registry.cells() if cell['sport']=='boat' and cell['group']!='seller']
            self.assertEqual(len(requests),14)
            generated=asof+timedelta(seconds=10)
            output=root/f'pairs-{number}';make_private_pairs(context,requests,output,now=generated,allow_source=lambda *_:True)
            raw=packed((folder.name+'/'+name,(folder/name).read_bytes()) for folder in output.iterdir()
                if folder.is_dir() for name in ('learning.enc','learning.json','summary.json'))
            metadata=dict(base_meta,id=800+number,name=f'all-existing-model-pairs-42-{number+1}',
                size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
                created_at=(generated+timedelta(seconds=3)).isoformat())
            cutoff=datetime.fromisoformat(program['closed_at'])
            info=registry.identity(requests[0]['cell_key'].split('/',1)[1],'boat',requests[0]['native_payload'])
            observation=dict(race_id=program['race_id'],sport='boat',status='settled',ordered_top3=[1,2,3],
                captured_at=(cutoff+timedelta(minutes=1)).isoformat(),published_at=None,
                source_ref='https://www.boatrace.jp/fixture-result/'+str(number),
                source_rights_ref='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106',source_sha256=f'{number+1:064x}',
                identity_verified=True,roster=info['roster'],payout_per_100_yen=1230,refund_numbers=[])
            observations.append(observation)
            expected.extend(records_from_private_artifact(raw,metadata,[observation],now=final,
                expected_run_id=42,expected_head_sha='a'*40)['records'])
            archive=root/f'archive-{number}';archive.mkdir(mode=0o700)
            for name,body in (('archive.zip',raw),('metadata.json',json.dumps(metadata).encode())):
                path=archive/name;path.write_bytes(body);path.chmod(0o600)
            artifacts.append(archive);metadata_by_id[metadata['id']]=metadata
        dataset=root/'dataset.json';dataset.write_text(json.dumps(POINTER))
        def external(url):return deepcopy(metadata_by_id[int(url.rsplit('/',1)[1])])
        with patch.object(cli,'load_verified_intake',return_value=([],observations,SOURCE,CONTENT)), \
                patch.object(cli,'_github_json',side_effect=external):
            selected,_,intake=cli.load_intake(root/'unused','unused',dataset,now=final,
                native_archive_dirs=artifacts,full_native_boat_cohort=True,cohort_size=8)
        self.assertEqual(len(selected),112);self.assertEqual(intake['derived_record_count'],0)
        self.assertEqual(intake['cohort_required_frozen_cells'],14)
        self.assertTrue(all('input_derivation' not in row for row in selected))
        self.assertEqual({digest(row) for row in selected},{digest(row) for row in expected})
        trained=fit(selected,now=final,allow_source=lambda *_:True,allow_training=lambda *_:True)
        verify_training(trained)
        self.assertEqual(len(trained['models']),14)
        self.assertEqual({(m['unique_races'],m['train_races'],m['validation_races'])
                          for m in trained['models'].values()},{(8,6,2)})
        # Rehashing a summary never repairs a forged generation proof. Exercise
        # the restore verifier as well as the original record admission.
        for kind in ('reported_time','late_partition','conflicting_partition','missing_field'):
            altered=deepcopy(trained);key=next(iter(altered['models']))
            model=altered['models'][key];line=model['source_lineage'][0]
            if kind=='reported_time':line['actual_native_generated_at']=line['as_of']
            elif kind=='missing_field':line.pop('native_generation_partitions_sha256')
            else:
                parts=line['native_generation_evidence']['partitions']
                if kind=='late_partition':parts[0]['generated_at']=line['cutoff_at']
                else:
                    duplicate=deepcopy(parts[0])
                    duplicate['generated_at']=(datetime.fromisoformat(duplicate['generated_at'])+
                        timedelta(microseconds=1)).isoformat()
                    parts.append(duplicate)
                line['native_generation_partitions_sha256']=digest(parts)
            model['model_sha256']=digest({k:v for k,v in model.items() if k!='model_sha256'})
            altered['training_sha256']=digest({k:v for k,v in altered.items() if k!='training_sha256'})
            with self.subTest(tampered_generation=kind),self.assertRaisesRegex(ValueError,'NATIVE_GENERATION'):
                verify_training(altered)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_RACES'):
            cli._select_native_cohort(selected[1:],size=8,full_native_boat_cohort=True)


if __name__=='__main__':unittest.main()
