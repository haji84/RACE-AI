"""Fictional GitHub byte responses; no network, provider or production key."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import all_existing_model_learning_ci as ci

NOW=datetime(2030,4,1,12,tzinfo=timezone.utc)


class ExistingModelLearningCiTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.runner=self.root/'runner';self.runner.mkdir(mode=0o700)
        self.raw={81:b'fictional encrypted native ZIP',82:b'fictional encrypted result ZIP'}
        self.metadata={ident:dict(id=ident,name=('all-existing-model-pairs-42-1' if ident==81 else
            'race-existing-cycle-42'),digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            size_in_bytes=len(raw),expired=False,created_at=(NOW-timedelta(hours=1)).isoformat(),
            expires_at=(NOW+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha='a'*40,
                repository_id=1416489937,head_repository_id=1416489937)) for ident,raw in self.raw.items()}
        self.manifest=dict(schema='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V1',
            native_artifacts=[dict(id=81,digest=self.metadata[81]['digest'])],
            result_artifacts=[dict(id=82,digest=self.metadata[82]['digest'])],cohort_size=8,
            owner_research_record='audit/state/all-existing-model-owner-research.json')
        self.path=self.root/'manifest.json';self.output=self.root/'candidate';self.calls=[]
        env=patch.dict('os.environ',RUNNER_TEMP=str(self.runner));env.start();self.addCleanup(env.stop)
        ready=patch.object(ci,'_key_ready',return_value=True);ready.start();self.addCleanup(ready.stop)

    def fetch(self,path):
        self.calls.append(path)
        ident=int(path.split('/')[-2] if path.endswith('/zip') else path.split('/')[-1])
        return self.raw[ident] if path.endswith('/zip') else json.dumps(self.metadata[ident]).encode()

    def invoke(self,manifest=None,*,fit=None):
        self.path.write_text(json.dumps(self.manifest if manifest is None else manifest))
        output=io.StringIO()
        with redirect_stdout(output):
            result=ci.main(['--manifest',str(self.path),'--restored-dir',str(self.root/'restored'),
                '--out-dir',str(self.output)],now=NOW,_fetch=self.fetch,_fit=fit)
        return result,json.loads(output.getvalue()),output.getvalue()

    def test_manifest_downloads_only_bound_github_cipher_and_calls_explicit_fit(self):
        seen=[]
        def fitter(arguments,*,now):
            self.assertEqual(arguments[0],'fit');self.assertEqual(now,NOW)
            self.assertIn('--derive-from-observed',arguments)
            self.assertEqual(arguments[arguments.index('--cohort-size')+1],'8')
            self.assertNotIn('issue-decision',arguments)
            for flag,ident in (('--native-archive-dir',81),('--result-archive-dir',82)):
                folder=Path(arguments[arguments.index(flag)+1]);seen.append(folder)
                self.assertEqual(folder.stat().st_mode&0o777,0o700)
                self.assertEqual({p.name for p in folder.iterdir()},{'metadata.json','archive.zip'})
                self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in folder.iterdir()))
                self.assertEqual((folder/'archive.zip').read_bytes(),self.raw[ident])
            print(json.dumps(dict(state='FITTED_SHADOW_ONLY',fitted_model_count=12,production_promoted=False)))
            return 0
        code,summary,public=self.invoke(fit=fitter)
        self.assertEqual(code,0);self.assertEqual(summary['fitted_model_count'],12)
        self.assertEqual(summary['ci_native_artifacts_downloaded'],1)
        self.assertEqual(summary['ci_result_artifacts_downloaded'],1)
        self.assertEqual(summary['provider_source_requests'],0)
        self.assertEqual(len(self.calls),4)
        self.assertTrue(all(path.startswith('repos/haji84/RACE-AI/actions/artifacts/') for path in self.calls))
        self.assertTrue(all(not folder.exists() for folder in seen))
        self.assertNotIn('fictional encrypted',public);self.assertNotIn('metadata.json',public)

    def test_missing_key_and_existing_output_stop_before_fetch_or_fit(self):
        with patch.object(ci,'_key_ready',return_value=False):
            code,summary,_=self.invoke(fit=lambda *_:self.fail('no fit'))
        self.assertEqual(code,0);self.assertEqual(summary['state'],'HOLD_OWNER_STATE_KEY_MISSING')
        self.assertEqual(self.calls,[])
        self.output.mkdir(mode=0o700)
        code,summary,_=self.invoke(fit=lambda *_:self.fail('no fit'))
        self.assertEqual(code,2);self.assertEqual(self.calls,[])

    def test_unknown_schema_extra_fields_duplicate_ids_scope_paths_and_wrong_cohort_reject(self):
        variants=[]
        for change in ({'schema':'unknown'},{'extra':True},{'cohort_size':7},
                       {'owner_research_record':'../private-key'},
                       {'owner_research_record':'/tmp/record.json'},
                       {'native_artifacts':[]}):
            variant=deepcopy(self.manifest);variant.update(change);variants.append(variant)
        duplicate=deepcopy(self.manifest);duplicate['result_artifacts']=duplicate['native_artifacts'];variants.append(duplicate)
        for manifest in variants:
            with self.subTest(manifest=manifest):
                code,summary,_=self.invoke(manifest,fit=lambda *_:self.fail('no fit'))
                self.assertEqual(code,2);self.assertEqual(summary['state'],'HOLD_ALL_MODEL_CI_INTAKE')
        self.assertEqual(self.calls,[])

    def test_manifest_digest_or_expired_metadata_rejects_before_archive_get(self):
        for change in ({'digest':'sha256:'+'0'*64},{'expired':True},
                       {'created_at':(NOW+timedelta(seconds=1)).isoformat()},
                       {'expires_at':NOW.isoformat()}, {'size_in_bytes':64*1024*1024+1}):
            original=deepcopy(self.metadata[81]);self.metadata[81].update(change);self.calls=[]
            code,summary,_=self.invoke(fit=lambda *_:self.fail('no fit'))
            self.assertEqual(code,2);self.assertTrue(all(not path.endswith('/zip') for path in self.calls))
            self.metadata[81]=original

    def test_archive_byte_digest_mismatch_never_invokes_fitter(self):
        self.raw[81]=b'tampered ZIP'
        code,summary,_=self.invoke(fit=lambda *_:self.fail('no fit'))
        self.assertEqual(code,2);self.assertEqual(summary['reason'],'ALL_MODEL_CI_ARCHIVE_BYTES_MISMATCH')

    def test_transport_stderr_url_and_fit_unstructured_output_are_not_published(self):
        def broken(path):raise RuntimeError('https://secret.example/?sig=TOKEN RACE_AI_STATE_KEY=SECRET')
        self.path.write_text(json.dumps(self.manifest));output=io.StringIO()
        with redirect_stdout(output):
            code=ci.main(['--manifest',str(self.path),'--restored-dir','unused','--out-dir',str(self.output)],
                         now=NOW,_fetch=broken,_fit=lambda *_:self.fail('no fit'))
        self.assertEqual(code,2);self.assertNotIn('secret',output.getvalue());self.assertNotIn('TOKEN',output.getvalue())
        def bad_fit(*args,**kwargs):print('private secret not JSON');return 2
        code,summary,public=self.invoke(fit=bad_fit)
        self.assertEqual(code,2);self.assertNotIn('private secret',public)


if __name__=='__main__':unittest.main()
