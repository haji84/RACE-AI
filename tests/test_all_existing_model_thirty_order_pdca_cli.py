"""Synthetic PR71 Actions and real owner-fixture codecs; no live network/key."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_all_existing_model_thirty_order_pdca_artifacts as fixture


def api(test):
    test.assertIsNotNone(importlib.util.find_spec('scripts.all_existing_model_thirty_order_pdca'),
                         'explicit all-thirty order-only CLI absent')
    return importlib.import_module('scripts.all_existing_model_thirty_order_pdca')


def pin(meta):
    return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])


class ThirtyOrderManifestTests(unittest.TestCase):
    def test_explicit_thirty_manifest_rejects_legacy_cash_and_unknown_fields(self):
        module=api(self)
        base=dict(id=1,digest='sha256:'+'a'*64,run_id=42,head_sha='d'*40)
        value=dict(schema='RACE_AI_ALL_THIRTY_ORDER_PDCA_INPUT_V1',candidate_cell_count=30,
            future_artifact=base,origin_artifact=dict(base,id=2),
            result_artifacts=[dict(base,id=3,kind='BOAT'),dict(base,id=4,kind='OFFICIAL')],additional_native_artifacts=[])
        self.assertEqual(module.validate_manifest(value),value)
        for change in (dict(candidate_cell_count=19),dict(candidate_cell_count=True),dict(extra=True),
                       dict(schema='RACE_AI_ORDER_ONLY_PDCA_INPUT_V1'),dict(result_artifacts=[]),
                       dict(result_artifacts=[dict(base,kind='BOAT')])):
            with self.subTest(change=change),self.assertRaises(ValueError):module.validate_manifest(dict(value,**change))

    def test_untrusted_context_never_consults_an_owner_key(self):
        module=api(self)
        for values in ({},{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'fork/project'}):
            with self.subTest(values=values),patch.dict(os.environ,values,clear=True),\
                 patch.object(module.shared,'state_key',side_effect=AssertionError('KEY_LOOKUP_FORBIDDEN')):
                with self.assertRaises(ValueError):module.environment()


class ThirtyOrderCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=fixture.full_fixture()
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name);self.out=self.root/'score'
        self.now=fixture.EVALUATED;self.calls=[]
        self.manifest=dict(schema='RACE_AI_ALL_THIRTY_ORDER_PDCA_INPUT_V1',candidate_cell_count=30,
            future_artifact=pin(self.source['native_metadata']),origin_artifact=pin(self.source['origin_metadata']),
            result_artifacts=[dict(pin(item['metadata']),kind=item['kind']) for item in self.source['results']],
            additional_native_artifacts=[])
        self.actual={201:self.source['native_metadata'],202:self.source['origin_metadata']}
        self.archives={201:self.source['native_raw'],202:self.source['origin_raw']}
        for item in self.source['results']:
            self.actual[item['metadata']['id']]=item['metadata'];self.archives[item['metadata']['id']]=item['raw']
        self.path=self.root/'input.json';self.path.write_text(json.dumps(self.manifest))
        self.event=self.root/'event.json';self.event.write_text(json.dumps(dict(number=71,pull_request=dict(number=71,
            head=dict(sha='a'*40,repo=dict(id=1416489937,full_name='haji84/RACE-AI')),
            base=dict(repo=dict(id=1416489937,full_name='haji84/RACE-AI'))))))
        settings=dict(RACE_AI_STATE_KEY=fixture.base64.b64encode(fixture.KEY).decode(),GITHUB_ACTIONS='true',
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='61',
            RUNNER_TEMP=str(self.root),GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/71/merge',GITHUB_EVENT_PATH=str(self.event))
        env=patch.dict(os.environ,settings);env.start();self.addCleanup(env.stop)
        deny=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('all real network forbidden'))
        deny.start();self.addCleanup(deny.stop)
    def transport(self,path):
        self.calls.append(path)
        if path=='actions/runs/61':
            return json.dumps(dict(id=61,head_sha='a'*40,repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))).encode()
        ident=int(path.split('/')[2]);return self.archives[ident] if path.endswith('/zip') else json.dumps(self.actual[ident]).encode()
    def run_cli(self,extra=()):
        module=api(self);stdout=io.StringIO()
        with patch.object(module.future,'gh',side_effect=self.transport),patch.object(module,'utc_now',side_effect=lambda:self.now),\
             patch.dict(os.environ,GITHUB_OUTPUT=str(self.root/'github-output')),redirect_stdout(stdout):
            result=module.main(['--input',str(self.path),'--out-dir',str(self.out),*extra])
        return result,json.loads(stdout.getvalue())
    def test_real_fixture_all_thirty_rank_only_cli_and_independent_exact_zip_readback(self):
        _,status=self.run_cli();self.assertTrue(status['ready'],status)
        self.assertEqual(status['teacher_matched_forecasts'],30);self.assertTrue(status['all_thirty_cells_scored'])
        self.assertFalse(status['monetary_evaluation_available']);self.assertEqual(status['source_requests'],0)
        for text in ('ordered_top3','raw_base64','roster','source_ref','scoreboard','payout_per_100_yen','roi'):
            self.assertNotIn(text,json.dumps(status))
        raw=fixture.boat.zipped(self.out)
        self.actual[401]=fixture.actual_metadata(raw,401,status['artifact_name'],61,'a'*40,self.now+timedelta(seconds=2))
        self.archives[401]=raw;self.now+=timedelta(seconds=3)
        _,checked=self.run_cli(['--readback-artifact','401'])
        self.assertTrue(checked['ready']);self.assertTrue(checked['independent_pdca_artifact_receipt_verified'])
        self.assertEqual(checked['partition_count'],30)
    def test_missing_key_or_fork_holds_before_any_github_read(self):
        for changes in (dict(RACE_AI_STATE_KEY=''),dict(GITHUB_REF='refs/pull/72/merge'),dict(GITHUB_REPOSITORY='fork/project')):
            self.calls=[]
            with patch.dict(os.environ,changes):_,status=self.run_cli()
            self.assertFalse(status['ready']);self.assertEqual(self.calls,[]);self.assertFalse(self.out.exists())
    def test_bad_source_metadata_is_rejected_before_any_zip_download(self):
        original=deepcopy(self.actual[202])
        for changes in (dict(expired=True),dict(name='all-native-future-origin-43-900010'),dict(digest='sha256:'+'f'*64)):
            self.actual[202]=dict(original,**changes);self.calls=[]
            _,status=self.run_cli();self.assertFalse(status['ready']);self.assertFalse(self.out.exists())
            self.assertFalse(any(path.endswith('/zip') for path in self.calls))
        self.actual[202]=original


if __name__=='__main__':unittest.main()
