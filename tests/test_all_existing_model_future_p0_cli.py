"""Actual fixture codecs and nine fitted cells; no Git/provider/network/real key."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
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
from race_ai import boat_model_runtime as runtime
from race_ai.boat_pdca_recipient import receiver_document
from race_ai.boat_venue_learning import seal_candidate
from race_ai.boat_observed_pairwise_models import predict_pair
from scripts import all_existing_model_future_p0 as cli
from tests.test_all_existing_model_future_p0 import fitted_nine_training, NOW
from tests.test_boat_all_model_cycle import fitted_ranker
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_frozen_day_cycle import sample

KEY = bytes(range(32))  # Deliberately public fixture-only key.
RUN_HEAD = 'b'*40


def zipped(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items(): archive.writestr(name, raw)
    return output.getvalue()


class FutureP0CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = fitted_nine_training()
        cls.baseline = fitted_ranker()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.repo = self.base/'repo'; self.repo.mkdir(mode=0o700)
        self.temp = self.base/'private'; self.temp.mkdir(mode=0o700)
        self.root = self.temp/'future'; self.outputs = self.temp/'outputs'; self.outputs.touch(mode=0o600)
        self.now = NOW+timedelta(days=1)
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_RUN_ID='42', GITHUB_SHA='a'*40, RUNNER_TEMP=str(self.temp), GITHUB_OUTPUT=str(self.outputs),
            RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        for item in (patch.dict(os.environ, env), patch.object(cli, 'ROOT', self.repo),
                     patch.object(cli, 'utc_now', side_effect=lambda: self.now), patch.object(cli, 'git_auth')):
            item.start(); self.addCleanup(item.stop)
        candidate = self.temp/'candidate'
        seal_candidate(dict(training=deepcopy(self.training), summary=dict(state='FICTIONAL_NINE_FITTED_CELLS'), excluded=[]), candidate)
        self.candidate_zip = zipped({p.name: p.read_bytes() for p in candidate.iterdir()})
        self.candidate_meta = self.metadata(200, 'boat-venue-learning-42-1', self.candidate_zip,
            saved=(self.now-timedelta(seconds=10)).isoformat(), head=RUN_HEAD)
        snapshot = json.loads(json.dumps(fixture(research=True)).replace('2030-04-01', '2030-04-02'))
        document, _, _ = sample()
        document.update(day_jst='2030-04-02', predictions=[predict_pair(snapshot, allow_source=lambda *_: True)],
            schedule=[dict(race_id='20300402-01-01', cutoff_at=snapshot['sales_cutoff_at'])])
        self.source_zip = zipped({'forecasts.json': cli.wire(document)})
        self.source_meta = self.metadata(100, 'boat-p0-existing-42', self.source_zip,
            saved='2030-04-02T01:43:00Z', head='a'*40)
        proof = cli._receipt(self.source_meta, document)
        db = __import__('sqlite3').connect(':memory:'); db.execute('CREATE TABLE invented (id INTEGER)'); db.commit()
        raw_db = db.serialize(); db.close()
        files = {'history.sqlite': raw_db, 'racers.sqlite': raw_db, 'ranker.json': cli.wire(self.baseline),
            'metadata.json': b'{"schema":"EXPLICITLY_FICTIONAL_RUNTIME"}',
            'p0-source.json': cli.wire(dict(document=document, receipt=proof))}
        self.runtime_cipher, header = runtime.seal_runtime(files,
            receiver_document(key=KEY, run_id='42', source_head='a'*40), created_at=self.now.isoformat())
        self.pointer = dict(schema=runtime.SCHEMA, purpose=runtime.PURPOSE, repository_id=runtime.REPO_ID,
            ref=runtime.RUNTIME_REF, cipher_path='runtime/'+sha256(self.runtime_cipher).hexdigest()+'.enc',
            cipher_sha256=sha256(self.runtime_cipher).hexdigest(), header=header, status='READY', source_commit='c'*40)
        path = self.repo/runtime.INPUT_PATH; path.parent.mkdir(parents=True); path.write_bytes(cli.wire(self.pointer))
        actual_run = dict(id=42, head_sha=RUN_HEAD,
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        self.mapping = {'actions/runs/42': cli.wire(actual_run),
            'actions/artifacts/200/zip': self.candidate_zip, 'actions/artifacts/200': cli.wire(self.candidate_meta),
            'actions/artifacts/100/zip': self.source_zip, 'actions/artifacts/100': cli.wire(self.source_meta)}
        self.calls = []
        def gh(route):
            self.calls.append(route)
            return self.mapping[route]
        def restore(pointer, repo, private_dir):
            self.assertEqual(pointer, self.pointer)
            files = runtime.open_runtime(self.runtime_cipher, key=KEY)
            private_dir.mkdir(mode=0o700)
            paths = {}
            for name, raw in files.items():
                path = private_dir/name; path.write_bytes(raw); path.chmod(0o600); paths[name] = str(path)
            self.runtime_plain = private_dir
            return dict(files=paths)
        for item in (patch.object(cli, 'gh', side_effect=gh), patch.object(runtime, 'restore_runtime', side_effect=restore)):
            item.start(); self.addCleanup(item.stop)

    def metadata(self, ident, name, raw, *, saved, head):
        return dict(id=ident, name=name, expired=False, digest='sha256:'+sha256(raw).hexdigest(),
            size_in_bytes=len(raw), created_at=saved, expires_at=(self.now+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42, repository_id=1416489937, head_repository_id=1416489937, head_sha=head))

    def run_cli(self, option='--candidate-artifact', ident=200):
        stream = io.StringIO()
        with redirect_stdout(stream): code = cli.main([option, str(ident), '--out-dir', str(self.root)])
        self.assertEqual(code, 0)
        self.assertNotIn(base64.b64encode(KEY).decode(), stream.getvalue())
        return json.loads(stream.getvalue())

    def test_actual_candidate_runtime_nine_cipher_pairs_and_actual_upload_readback(self):
        result = self.run_cli()
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['forecast_partition_count'], 9)
        self.assertEqual(result['expected_head_sha'], RUN_HEAD)  # Actual run head, not checkout/merge env SHA.
        self.assertFalse(result['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(len(list(self.root.iterdir())), 9)
        self.assertFalse((self.root/'summary.json').exists())
        self.assertFalse(self.runtime_plain.exists())
        self.assertTrue(self.root.with_name(self.root.name+'.status.json').is_file())
        self.assertNotIn('source_audit', result)
        raw = zipped({str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.mapping['actions/artifacts/201/zip'] = raw
        self.mapping['actions/artifacts/201'] = cli.wire(self.metadata(201, 'all-existing-model-pairs-42-900001', raw,
            saved=(self.now+timedelta(seconds=3)).isoformat(), head=RUN_HEAD))
        self.now += timedelta(seconds=4)
        verified = self.run_cli('--readback-artifact', 201)
        self.assertTrue(verified['independent_pre_cutoff_receipt_verified'], verified)
        self.assertEqual(verified['forecast_partition_count'], 9)
        self.assertTrue(all(route.startswith('actions/') for route in self.calls))

    def test_wrong_actual_candidate_head_holds_without_runtime_restore(self):
        self.candidate_meta['workflow_run']['head_sha'] = 'f'*40
        self.mapping['actions/artifacts/200'] = cli.wire(self.candidate_meta)
        with patch.object(runtime, 'restore_runtime', side_effect=AssertionError('unverified candidate consumed runtime')):
            result = self.run_cli()
        self.assertFalse(result['ready'])
        self.assertFalse(self.root.exists())

    def test_source_receipt_tamper_missing_baseline_and_late_actual_clock_do_not_fabricate(self):
        self.source_meta['digest'] = 'sha256:'+'f'*64
        self.mapping['actions/artifacts/100'] = cli.wire(self.source_meta)
        result = self.run_cli()
        self.assertFalse(result['ready'])
        self.assertFalse(self.root.exists())
        self.assertFalse(self.runtime_plain.exists())

    def test_missing_owner_key_stops_before_any_github_request(self):
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            result = self.run_cli()
        self.assertFalse(result['ready'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
