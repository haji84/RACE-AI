"""Fixture-only GitHub artifact capture; never contacts a provider or GitHub."""
import copy
from hashlib import sha256
import importlib
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from tests.test_frozen_day_cycle import sample

try:
    capture = importlib.import_module('race_ai.private_cycle_capture')
except ModuleNotFoundError:
    capture = None


class PrivateCycleCaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(capture, 'private original capture is not connected')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.document, self.archive, self.metadata = sample()
        self.calls = []

    def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == 'actions/artifacts/1':
            return json.dumps(self.metadata).encode()
        if endpoint == 'actions/artifacts/1/zip':
            return self.archive
        raise AssertionError('unexpected source request: '+endpoint)

    def run_capture(self, **options):
        return capture.capture_artifacts('2030-04-01', [1], self.root/'private',
                                         github_get=self.get, **options)

    def test_exact_original_bytes_private_modes_and_local_pins(self):
        manifest = self.run_capture()
        entry = manifest['artifacts'][0]
        self.assertEqual(self.calls, ['actions/artifacts/1','actions/artifacts/1/zip'])
        self.assertEqual(manifest['repo'], 'haji84/RACE-AI')
        self.assertEqual(manifest['repository_id'], 1416489937)
        self.assertEqual(entry['kind'], 'p0')
        self.assertEqual(entry['run_id'], 2)
        self.assertEqual((self.root/'private'/entry['zip_file']).read_bytes(), self.archive)
        self.assertEqual(entry['zip_sha256'], sha256(self.archive).hexdigest())
        metadata = (self.root/'private'/entry['metadata_file']).read_bytes()
        self.assertEqual(entry['metadata_sha256'], sha256(metadata).hexdigest())
        self.assertEqual(json.loads(metadata), self.metadata)
        self.assertEqual((self.root/'private').stat().st_mode & 0o777, 0o700)
        for p in (self.root/'private').iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_existing_output_is_never_overwritten_and_no_remote_read_occurs(self):
        out = self.root/'private';out.mkdir();(out/'keep').write_bytes(b'original')
        with self.assertRaises(ValueError): self.run_capture()
        self.assertEqual(self.calls, [])
        self.assertEqual((out/'keep').read_bytes(), b'original')

    def test_git_root_and_symlink_parent_are_rejected_before_remote_read(self):
        (self.root/'.git').mkdir()
        with self.assertRaises(ValueError): self.run_capture()
        self.assertEqual(self.calls, [])
        (self.root/'.git').rmdir()
        link=self.root/'alias';link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            capture.capture_artifacts('2030-04-01',[1],link/'private',github_get=self.get)
        self.assertEqual(self.calls, [])

    def test_corruption_foreign_repo_expiry_and_pin_mismatch_never_create_output(self):
        original=copy.deepcopy(self.metadata)
        for change in ({'expired': True}, {'workflow_run': {'id':2,'head_repository_id':999}},
                       {'id': 2}, {'id': True},
                       {'workflow_run': {'id':2,'head_repository_id':1416489937,'repository_id':999}},
                       {'name':'unrelated-artifact'}, {'digest':'sha256:'+'f'*64}):
            self.metadata={**copy.deepcopy(original), **change};self.calls.clear()
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_capture()
            self.assertFalse((self.root/'private').exists())
        self.metadata=original
        with self.assertRaises(ValueError): self.run_capture(expected_zip_sha256={1:'0'*64})
        self.assertFalse((self.root/'private').exists())

    def test_wrong_day_or_unbounded_selection_does_not_fetch(self):
        for day, ids in [('2030-02-31',[1]),('2030-04-01',[1,1]),('2030-04-01',[]),
                         ('2030-04-01',[True]),('2030-04-01',list(range(1,102)))]:
            with self.subTest(day=day, ids=ids[:3]), self.assertRaises(ValueError):
                capture.capture_artifacts(day,ids,self.root/'private',github_get=self.get)
        self.assertEqual(self.calls, [])

    def test_api_failure_is_not_retried_or_exposed_as_private_server_text(self):
        def denied(endpoint):
            self.calls.append(endpoint);raise OSError('private token and path')
        with self.assertRaisesRegex(ValueError,'GITHUB_ARTIFACT_READ_UNAVAILABLE') as caught:
            capture.capture_artifacts('2030-04-01',[1],self.root/'private',github_get=denied)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('private token',str(caught.exception))
        self.assertFalse((self.root/'private').exists())

    def test_metadata_size_gate_stops_before_downloading_large_archive(self):
        self.metadata['size_in_bytes']=33*1024*1024
        with self.assertRaises(ValueError): self.run_capture()
        self.assertEqual(self.calls,['actions/artifacts/1'])

    def test_saved_empty_historical_p0_attempt_is_preserved_without_creating_forecasts(self):
        doc={'schema':'RACE_AI_EXISTING_P0_DAY_V1','day_jst':'2030-04-01',
             'predictions':[],'race_count':None,'model_forecast_count':None,'actual_purchases':False}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('forecasts.json',json.dumps(doc))
        self.archive=buf.getvalue();self.metadata['digest']='sha256:'+sha256(self.archive).hexdigest()
        manifest=self.run_capture()
        self.assertEqual(len(manifest['artifacts']),1)
        self.assertEqual((self.root/'private'/manifest['artifacts'][0]['zip_file']).read_bytes(),self.archive)

    def test_parent_swapped_during_download_cannot_redirect_originals_into_git(self):
        original=self.root/'holder';original.mkdir(mode=0o700)
        foreign=self.root/'checkout';foreign.mkdir();(foreign/'.git').mkdir()
        def swapped(endpoint):
            raw=self.get(endpoint)
            if endpoint.endswith('/zip'):
                original.rename(self.root/'old-holder')
                original.symlink_to(foreign,target_is_directory=True)
            return raw
        with self.assertRaises((ValueError,OSError)):
            capture.capture_artifacts('2030-04-01',[1],original/'private',github_get=swapped)
        self.assertEqual(list(foreign.iterdir()),[foreign/'.git'])
        self.assertFalse((self.root/'old-holder'/'private').exists())

    def test_git_marker_added_during_download_rejects_before_output(self):
        def changed(endpoint):
            raw=self.get(endpoint)
            if endpoint.endswith('/zip'): (self.root/'.git').write_text('gitdir: elsewhere')
            return raw
        with self.assertRaises(ValueError):
            capture.capture_artifacts('2030-04-01',[1],self.root/'private',github_get=changed)
        self.assertFalse((self.root/'private').exists())


if __name__ == '__main__':
    unittest.main()
