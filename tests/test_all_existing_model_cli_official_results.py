"""Separate sport identities and explicit mixed research scope; invented data."""
from copy import deepcopy
from datetime import datetime,timedelta
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import all_existing_model_learning as cli
from scripts import all_existing_model_learning_ci as ci
from tests import test_all_existing_model_learning_ci as ci_fixtures
from tests import test_all_existing_model_native_cohort as boat_fixture
from tests import test_jra_official_sparse_adapter as card_fixture
from tests import test_jra_official_result_adapter as result_fixture


class GenericOfficialCliTests(unittest.TestCase):
    def test_sport_identity_is_never_sent_through_boat_race_normalization(self):
        boat=dict(race_id='20300401-24-01',captured_at='2030-04-01T12:00:00+00:00',source_sha256='a'*64)
        horse=dict(race_id='horse:2030-04-01:jra-03:1',sport='horse',captured_at=boat['captured_at'],
            source_sha256='b'*64,status='pending')
        values=cli._merge_verified_result_observations([boat,horse])
        self.assertEqual(len(values),2)
        self.assertEqual(next(v for v in values if v.get('sport')=='horse'),horse)
        changed=deepcopy(horse);changed['source_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'CONFLICTING_REVISIONS'):
            cli._merge_verified_result_observations([boat,horse,changed])

    def test_ci_v2_requires_explicit_keep_other_sports_while_v1_remains_strict(self):
        fixture=ci_fixtures.ExistingModelLearningCiTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        manifest=deepcopy(fixture.manifest);manifest['schema']='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V2'
        manifest['keep_other_sports']=True
        fixture.metadata[82]['name']='all-existing-official-results-42-1'
        seen=[]
        def fit(arguments,*,now):
            seen.extend(arguments);print(json.dumps(dict(state='FITTED_SHADOW_ONLY',fitted_model_count=17)))
            return 0
        code,summary,_=fixture.invoke(manifest,fit=fit)
        self.assertEqual(code,0);self.assertIn('--keep-other-sports',seen)
        self.assertEqual(summary['fitted_model_count'],17)
        manifest['schema']=ci.SCHEMA
        code,summary,_=fixture.invoke(manifest,fit=fit)
        self.assertEqual(code,2)

    def test_actual_encrypted_inputs_results_and_explicit_mixed_cohort_fit_seventeen_cells(self):
        from race_ai.all_existing_model_learning import fit,verify_training
        from race_ai.all_existing_model_pairs import make_private_pairs
        from race_ai.all_existing_model_official_results import build_result_payload,seal_results
        from race_ai.jra_official_sparse_adapter import build_sparse_payload
        from race_ai.jra_official_result_adapter import parse_result
        from race_ai.manual_official_capture import official_rights_ref
        from race_ai.four_sport_model_suite import ALL_MODELS
        from race_ai.four_sport_learning import LEARNED_ID
        boat_fixture.NativeCommonCohortTests.setUpClass()
        fixture=boat_fixture.NativeCommonCohortTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups);root=fixture.root
        conversion=datetime.fromisoformat('2030-04-06T01:10:00+00:00')
        generated=datetime.fromisoformat('2030-04-06T07:01:00+00:00');now=generated+timedelta(seconds=10)
        rights=official_rights_ref('horse');requests=[];captures=[];observations=[];frozen=[]
        rule=card_fixture.evidence();rule['raw']=rule['raw'].replace(b'2026',b'2030')
        rule['rule_id']='JRA_2030_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS'
        rule['metadata']=card_fixture.metadata(rule['raw'],card_fixture.RULE_URL,
            completed='2030-04-06T01:00:03+00:00');rule['metadata']['fetched_at']='2030-04-06T01:00:00+00:00'
        for number in range(1,9):
            text=card_fixture.card().decode('cp932').replace('2026年11月7日（土曜）3回福島1日 11レース',
                f'2030年4月6日（土曜）3回福島1日 {number}レース')
            for old,new in (('2026年10月1日','2030年3月1日'),('2026年9月1日','2030年2月1日'),
                            ('2026年8月1日','2030年1月1日'),('2026年7月1日','2029年12月1日')):
                text=text.replace(old,new)
            raw=text.encode('cp932')
            url=f'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde010320300301{number:02d}20300406/AA'
            meta=card_fixture.metadata(raw,url,completed='2030-04-06T01:00:03+00:00')
            meta['fetched_at']='2030-04-06T01:00:00+00:00'
            converted=build_sparse_payload(raw,meta,now=conversion,source_rights_ref=rights,cutoff_evidence=rule)
            self.assertEqual(converted['state'],'READY')
            payload=converted['native_payload'];frozen.append(payload)
            requests.extend(dict(cell_key='horse/'+mid,native_payload=deepcopy(payload)) for mid in (*ALL_MODELS,LEARNED_ID))
            result_text=result_fixture.result_html().decode('cp932').replace(
                '2026年11月7日（土曜）3回福島1日 11レース',f'2030年4月6日（土曜）3回福島1日 {number}レース')
            body=result_text.encode('cp932')
            result_url=f'https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde100320300301{number:02d}20300406/AA'
            received=datetime.fromisoformat('2030-04-06T07:00:00+00:00')+timedelta(seconds=number)
            metadata=card_fixture.metadata(body,result_url,completed=received.isoformat())
            metadata['fetched_at']=(received-timedelta(seconds=2)).isoformat()
            observation=parse_result(body,metadata,frozen_native_payload=payload,now=generated,source_rights_ref=rights)
            observations.append(observation)
            captures.append(dict(raw_base64=base64.b64encode(body).decode(),metadata=metadata))
        output=root/'horse-pairs'
        make_private_pairs(fixture.fixture.context,requests,output,now=conversion,allow_source=lambda *_:True)
        def packed(members):
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,body in members:archive.writestr(name,body)
            return buffer.getvalue()
        native_raw=packed((folder.name+'/'+name,(folder/name).read_bytes()) for folder in output.iterdir()
            if folder.is_dir() for name in ('learning.enc','learning.json','summary.json'))
        native_meta=dict(fixture.metadata,id=802,name='all-existing-model-pairs-99-2',size_in_bytes=len(native_raw),
            digest='sha256:'+hashlib.sha256(native_raw).hexdigest(),created_at=(conversion+timedelta(seconds=3)).isoformat())
        result_payload=build_result_payload(captures,observations,run_id=99,code_sha=boat_fixture.fixtures.HEAD,
            generated_at=generated,day_jst='2030-04-06',frozen_native_payloads=frozen)
        result_raw=packed([('results.enc',seal_results(result_payload,round_no=1,frozen_native_payloads=frozen))])
        result_meta=dict(native_meta,id=803,name='all-existing-official-results-99-1',size_in_bytes=len(result_raw),
            digest='sha256:'+hashlib.sha256(result_raw).hexdigest(),created_at=(generated+timedelta(seconds=2)).isoformat())
        def save(name,raw,metadata):
            path=root/name;path.mkdir(mode=0o700)
            for filename,data in (('archive.zip',raw),('metadata.json',json.dumps(metadata).encode())):
                file=path/filename;file.write_bytes(data);file.chmod(0o600)
            return path
        native_path=save('horse-input',native_raw,native_meta);result_path=save('horse-results',result_raw,result_meta)
        metadata_by_id={800:fixture.metadata,802:native_meta,803:result_meta}
        def external(url):return deepcopy(metadata_by_id[int(url.rsplit('/',1)[1])])
        options=dict(now=now,derive_observed=True,native_archive_dirs=[fixture.archive,native_path],
            result_archive_dirs=[result_path],cohort_size=8)
        source=deepcopy((fixture.rows,fixture.old_observations+fixture.results,boat_fixture.SOURCE,boat_fixture.CONTENT))
        with patch.object(cli,'load_verified_intake',return_value=source),patch.object(cli,'_github_json',side_effect=external):
            original,old_scope,_=cli.load_intake(root/'restored','source',fixture.dataset,**options)
            records,scope,intake=cli.load_intake(root/'restored','source',fixture.dataset,keep_other_sports=True,**options)
        self.assertEqual(len(original),96);self.assertEqual(len(records),136)
        self.assertNotEqual(old_scope['intake_sha256'],scope['intake_sha256'])
        self.assertEqual(intake['kept_other_sport_record_count'],40)
        trained=fit(records,now=now);verify_training(trained)
        self.assertEqual(len(trained['models']),17)
        self.assertEqual({(m['unique_races'],m['train_races'],m['validation_races'])
            for m in trained['models'].values()},{(8,6,2)})
        self.assertEqual(sum(key.startswith('horse/') for key in trained['models']),5)
        self.assertTrue(all(row['result']['published_at'] is None for row in records if row['sport']=='horse'))


if __name__=='__main__':unittest.main()
