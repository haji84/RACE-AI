"""Public-key AES fixtures, not authentication of the actual retained original."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch

# Dependencies come only from the selected immutable owner checkout; the new
# helper itself must be loaded from this exact main checkout, never a fallback.
import importlib.util
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT/'owner-source'
MAIN_HELPER = ROOT/'race_ai/all_existing_model_archived_native.py'
ALLOWED_OWNER_SHAS = ('eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
                      '86b029ae5bddd5d4956497d8b32b2c92b8eec521')
assert subprocess.check_output(['git','-C',str(OWNER),'rev-parse','HEAD'],
    timeout=10).decode().strip() in ALLOWED_OWNER_SHAS
if str(OWNER) not in sys.path:sys.path.insert(0,str(OWNER))
import race_ai, tests, scripts
assert Path(race_ai.__file__).resolve() == OWNER/'race_ai/__init__.py'
for folder,pin in (('pr64-reference','761247bee0209e37b1af6b8885e92cad3e9260a5'),
                   ('pr72-reference','7a432e5acc4d3495a0e82bd79726929e2f8085fe')):
    package=OWNER/folder/'race_ai'
    assert package.is_dir()
    assert subprocess.check_output(['git','-C',str(package.parent),'rev-parse','HEAD'],
        timeout=10).decode().strip()==pin
    if str(package) not in race_ai.__path__:race_ai.__path__.append(str(package))
for package,folder in ((tests,OWNER/'tests'),(scripts,OWNER/'scripts')):
    if str(folder) not in package.__path__:package.__path__.append(str(folder))
assert MAIN_HELPER.is_file() and not MAIN_HELPER.is_symlink(), 'EXACT_MAIN_HELPER_REQUIRED'
module_name='race_ai.all_existing_model_archived_native'
if module_name in sys.modules:
    assert Path(sys.modules[module_name].__file__).resolve()==MAIN_HELPER
else:
    spec=importlib.util.spec_from_file_location(module_name,MAIN_HELPER)
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module
    spec.loader.exec_module(module)
assert Path(sys.modules[module_name].__file__).resolve()==MAIN_HELPER

from race_ai import boat_private_original_vault as vault
from race_ai import all_existing_model_official_results as results
from scripts import all_existing_model_official_result_freeze as freeze
from tests import test_boat_private_original_vault_private_pairs as pair_fixture

KEY = pair_fixture.KEY
FORECAST_NOW = pair_fixture.FORECAST_NOW


class ArchivedNativeOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pair_fixture.PrivatePairsVaultTests.setUpClass()

    def setUp(self):
        self.api = importlib.import_module('race_ai.all_existing_model_archived_native')
        self.assertEqual(Path(self.api.__file__).resolve(), MAIN_HELPER)
        for dependency in (vault, results, freeze, pair_fixture):
            self.assertTrue(Path(dependency.__file__).resolve().is_relative_to(OWNER))
        self.fixture = pair_fixture.PrivatePairsVaultTests(
            'test_eight_input_only_races_forty_native_capsules_preserve_exact_originals')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.raw, self.metadata_raw, self.members, _ = self.fixture.artifact(input_only=True)
        self.metadata = json.loads(self.metadata_raw)
        self.locator = self.fixture.retain(self.raw, self.metadata_raw)
        self.archived = FORECAST_NOW + timedelta(hours=1)
        self.now = FORECAST_NOW + timedelta(days=10)
        self.binding = self.fixture_binding()
        self.pin = dict(id=self.metadata['id'], digest=self.metadata['digest'],
            run_id=self.metadata['workflow_run']['id'], head_sha=self.metadata['workflow_run']['head_sha'])

    def fixture_binding(self):
        entry = json.loads(self.fixture.remote.objects[self.locator['source_commit']][
            self.locator['batch_path']])['state']['entries'][0]
        return replace(self.api._FIXED_BINDING,
            artifact_id=self.metadata['id'], workflow_run_id=self.metadata['workflow_run']['id'],
            head_sha=self.metadata['workflow_run']['head_sha'], artifact_name=self.metadata['name'],
            original_zip_sha256=sha256(self.raw).hexdigest(), original_zip_size=len(self.raw),
            metadata_sha256=sha256(self.metadata_raw).hexdigest(), metadata_size=len(self.metadata_raw),
            original_saved_at=self.metadata['created_at'], archived_at=self.archived.isoformat(),
            source_commit=self.locator['source_commit'], batch_path=self.locator['batch_path'],
            batch_sha256=self.locator['batch_sha256'], entry_sha256=self.locator['entry_sha256'],
            cipher_sha256=entry['cipher_sha256'], cipher_size=entry['cipher_size'],
            record_count=8, native_capsule_count=40)

    def summary(self, *, pin=None, key=KEY, now=None, binding=None):
        with patch.object(self.api, '_FIXED_BINDING', binding or self.binding):
            return self.api.safe_summary(self.pin if pin is None else pin, self.fixture.reader.repo,
                now=self.now if now is None else now, key=key, transport=self.fixture.reader)

    def test_summary_replays_authentic_fixture_at_original_clock_and_exposes_no_private_material(self):
        with patch.object(vault, 'restore_original', wraps=vault.restore_original) as restored, \
                patch.object(self.api, '_verified_private_pairs_artifact',
                    wraps=self.api._verified_private_pairs_artifact) as replay:
            summary = self.summary()
        restored.assert_called_once()
        self.assertEqual(restored.call_args.args[0], self.locator)
        self.assertEqual(replay.call_args.args, (self.raw, self.metadata))
        self.assertEqual(replay.call_args.kwargs['now'], self.archived)
        self.assertLess(datetime.fromisoformat(self.metadata['expires_at']), self.now)
        self.assertEqual(summary['original_zip_sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(summary['original_metadata_sha256'], sha256(self.metadata_raw).hexdigest())
        self.assertEqual((summary['source_record_count'], summary['native_capsule_count']), (8,40))
        self.assertEqual(summary['new_model_input_count'], 0)
        self.assertTrue(summary['archived_original_replay_verified'])
        self.assertEqual(summary['current_artifact_status'], 'NOT_QUERIED')
        for name in ('github_artifact_receipt_created', 'current_native_admission_created',
            'provider_permission_granted', 'current_generation_authorized', 'dispatch_authorized',
            'label_or_training_authorization_granted'):
            self.assertIs(summary[name], False)
        text = json.dumps(summary) + repr(summary)
        for private in ('native_payload', 'snapshot', 'roster', 'fictional-track', 'source_ref',
                        'learning.enc', 'https://', 'ordered_top8', 'raw_zip', 'metadata_raw'):
            self.assertNotIn(private, text)
        for name in ('ready', 'independent_pre_cutoff_receipt_verified', 'key'):
            self.assertNotIn(name, summary)

    def test_detached_body_hash_or_report_cannot_be_reverified_or_used_as_fresh_native_inputs(self):
        summary = self.summary()
        changed = dict(summary, archived_capsules_sha256='f'*64,
                       source_records_sha256='f'*64, current_generation_authorized=True)
        for supplied in (summary, changed):
            with patch.object(vault, 'restore_original') as read, self.assertRaises(ValueError):
                self.summary(pin=supplied)
            read.assert_not_called()
            with self.assertRaises(ValueError):results._frozen([supplied])
            with self.assertRaises(ValueError):freeze._actual_metadata(supplied, self.pin, self.now)
        self.assertEqual(tuple(inspect.signature(self.api.safe_summary).parameters),
                         ('pin','repo','now','key','transport'))
        self.assertFalse(hasattr(self.api, 'ArchivedNativeOriginal'))
        self.assertFalse(hasattr(self.api, 'ArchivedNativeCapsule'))

    def test_all_exact_pin_fields_and_types_are_required_before_archive_access(self):
        changes = ({'id':self.pin['id']+1}, {'id':float(self.pin['id'])}, {'id':True},
            {'run_id':self.pin['run_id']+1}, {'run_id':float(self.pin['run_id'])},
            {'head_sha':'f'*40}, {'digest':'sha256:'+'f'*64}, {'extra':True})
        for change in changes:
            with self.subTest(change=change), patch.object(vault, 'restore_original') as read:
                with self.assertRaises(ValueError):self.summary(pin=dict(self.pin, **change))
                read.assert_not_called()
        for value in (None, [], tuple(self.pin.items())):
            with self.subTest(value=value), patch.object(vault, 'restore_original') as read, \
                    patch.object(self.api, '_FIXED_BINDING', self.binding):
                with self.assertRaises(ValueError):
                    self.api.safe_summary(value, self.fixture.reader.repo,
                        now=self.now, key=KEY, transport=self.fixture.reader)
                read.assert_not_called()

    def test_current_clock_must_be_aware_and_not_before_archived_admission(self):
        for now in (self.archived-timedelta(microseconds=1), self.now.replace(tzinfo=None),
                    self.now.isoformat(), 1, True):
            with self.subTest(now=now), patch.object(vault, 'restore_original') as read:
                with self.assertRaises(ValueError):self.summary(now=now)
                read.assert_not_called()

    def test_original_source_entry_cipher_and_file_bounds_cannot_be_substituted(self):
        changes = (('source_commit','a'*40), ('batch_sha256','a'*64), ('entry_sha256','a'*64),
            ('batch_path','state/other.json'), ('cipher_sha256','a'*64), ('cipher_size',1),
            ('metadata_sha256','a'*64), ('metadata_size',self.binding.metadata_size+1),
            ('original_zip_size',len(self.raw)+1))
        for field, value in changes:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.summary(binding=replace(self.binding, **{field:value}))

    def test_missing_wrong_and_mistyped_keys_never_return_a_readback(self):
        for key in (b'x'*32, b'short', bytearray(KEY), True):
            with self.subTest(key_type=type(key).__name__), self.assertRaises(ValueError):
                self.summary(key=key)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            self.summary(key=None)

    def test_cipher_and_batch_mutation_are_refused_without_live_fallback(self):
        tree = self.fixture.remote.objects[self.locator['source_commit']]
        entry = json.loads(tree[self.locator['batch_path']])['state']['entries'][0]
        for path in (self.locator['batch_path'], entry['chunks'][0]['path']):
            saved = tree[path];tree[path] = saved[:-1]+bytes([saved[-1]^1])
            try:
                with self.subTest(kind='batch' if path == self.locator['batch_path'] else 'cipher'):
                    with self.assertRaises(ValueError):self.summary()
            finally:tree[path] = saved

    def test_exact_original_metadata_and_archival_only_provenance_are_required(self):
        original = vault.restore_original(self.locator, self.fixture.reader.repo,
            key=KEY, transport=self.fixture.reader)
        changes = []
        for name in ('raw_zip', 'metadata_raw'):
            bad = deepcopy(original);bad[name] += b'\n';changes.append(bad)
            bad = deepcopy(original);bad[name] = bytearray(bad[name]);changes.append(bad)
        for field, value in (('name','all-existing-model-pairs-99-900003'),
            ('id',self.metadata['id']+1), ('expired',True), ('size_in_bytes',len(self.raw)+1)):
            bad = deepcopy(original);bad['metadata'][field] = value;changes.append(bad)
        for field, value in (('receipt_scope','LIVE_GITHUB_ARTIFACT_RESPONSE'),
            ('current_artifact_status','UNEXPIRED'), ('archived_at',self.now.isoformat()),
            ('source_commit','e'*40), ('entry_sha256','e'*64),
            ('independent_git_readback_verified',1), ('github_artifact_receipt_created',True)):
            bad = deepcopy(original);bad['provenance'][field] = value;changes.append(bad)
        bad = deepcopy(original);bad['provenance']['extra'] = True;changes.append(bad)
        for index, bad in enumerate(changes):
            with self.subTest(case=index), patch.object(vault, 'restore_original', return_value=bad):
                with self.assertRaises(ValueError):self.summary()

    def test_record_counts_context_and_bounded_error_output_are_required(self):
        for field in ('record_count', 'native_capsule_count'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.summary(binding=replace(self.binding, **{field:1}))
        for stage, module, name in (('restore',vault,'restore_original'),
                                   ('replay',self.api,'_verified_private_pairs_artifact')):
            with self.subTest(stage=stage), patch.object(module, name,
                    side_effect=ValueError('private source context https://private.invalid/roster')):
                with self.assertRaises(ValueError) as caught:self.summary()
            self.assertRegex(str(caught.exception), '^ARCHIVED_NATIVE_[A-Z_]+$')
            self.assertNotIn('private', str(caught.exception))

    def test_valid_outer_vault_aes_cannot_replace_inner_partition_context_authentication(self):
        first = next(iter(self.members)).split('/')[0]
        wrong = 'f'*64 if first != 'f'*64 else 'e'*64
        bad_members = {(wrong+name[len(first):] if name.startswith(first+'/') else name):body
                       for name,body in self.members.items()}
        bad_raw = pair_fixture.packed(bad_members)
        bad_meta = dict(self.metadata, digest='sha256:'+sha256(bad_raw).hexdigest(),
                        size_in_bytes=len(bad_raw))
        bad_meta_raw = json.dumps(bad_meta, indent=3).encode()+b'\n\n'
        old_tree = self.fixture.remote.objects[self.locator['source_commit']]
        old_entry = json.loads(old_tree[self.locator['batch_path']])['state']['entries'][0]
        # Build an adversarial outer archive using only the public fixture key.
        # The real restore below must still replay/reject its inner source context.
        record = dict(files={'original.zip':bad_raw, 'metadata.json':bad_meta_raw},
                      metadata=bad_meta, summary=old_entry['header']['summary'])
        self.fixture.remote = pair_fixture.MemoryRemote()
        self.fixture.writer = pair_fixture.MemoryVault(self.fixture.remote, self.fixture.root/'other-writer')
        self.fixture.reader = pair_fixture.MemoryVault(self.fixture.remote, self.fixture.root/'other-reader')
        self.fixture.parent = self.fixture.remote.current
        with patch.object(vault, '_artifact', return_value=record):
            self.locator = self.fixture.retain(bad_raw, bad_meta_raw)
        self.raw,self.metadata_raw,self.metadata = bad_raw,bad_meta_raw,bad_meta
        self.binding = self.fixture_binding();self.pin['digest'] = bad_meta['digest']
        with self.assertRaisesRegex(ValueError, '^ARCHIVED_NATIVE_RESTORE_REJECTED$'):
            self.summary()

    def test_live_default_expiry_and_generation_dispatch_markers_are_unchanged(self):
        with patch.object(freeze.future, 'metadata', return_value=self.metadata), \
                patch.object(freeze.future, 'gh') as fetch, \
                patch.object(vault, 'restore_original') as archived:
            with self.assertRaisesRegex(ValueError, 'NATIVE_ARTIFACT_CLOCK'):
                freeze.frozen_inputs(dict(native_artifacts=[self.pin]), now=self.now)
        fetch.assert_not_called();archived.assert_not_called()
        from scripts import all_existing_model_official_result_retain as retain
        for function in (freeze.frozen_inputs, freeze.generate, retain.retain_manifest):
            self.assertNotIn('archive', str(inspect.signature(function)))
        manifest = dict(native_artifacts=[self.pin], result_artifacts=[], allow_order_only=True)
        scope = retain._scope(manifest, dict(run_id=42, head_sha='a'*40))
        self.assertEqual(set(scope), {'repository_id','workflow_run_id','head_sha','manifest_sha256'})
        done,held = retain._paths(Path('/private-fixture'), scope)
        self.assertEqual(done.name, 'done-42-'+scope['manifest_sha256']+'.json')
        self.assertEqual(held.name, 'hold-42-'+scope['manifest_sha256']+'.json')
        self.assert_workflow_upload_owns_the_report()

    def assert_workflow_upload_owns_the_report(self):
        workflow=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        block=workflow.split("python - <<'PY_ARCHIVED_NATIVE'\n",1)[1].split(
            '\n          PY_ARCHIVED_NATIVE',1)[0]
        block=textwrap.dedent(block)
        upload=workflow.split('      - name: Retain only fixed-original count proof or static HOLD reason',1)[1]
        self.assertIn("steps.archived_native_readback.outputs.report_written == 'true'",upload)
        marker='SYNTHETIC_PRIVATE_PREEXISTING_REPORT_MUST_NEVER_UPLOAD'
        for kind in ('fresh_hold','collision','symlink','fsync_failure'):
            root=self.fixture.root/('workflow-output-'+kind);root.mkdir(mode=0o700)
            target=root/'retained-native-13559236491-aes-counts.json'
            flag=root/'github-output'
            private=root/'private-marker.txt'
            if kind=='collision':target.write_text(marker);target.chmod(0o600)
            if kind=='symlink':
                private.write_text(marker);private.chmod(0o600);target.symlink_to(private)
            script=block
            if kind=='fsync_failure':
                script=("import os\ndef fail_fsync(*args):raise OSError('fixture private write failure')\n"
                        'os.fsync=fail_fsync\n'+script)
            environment=dict(os.environ,RUNNER_TEMP=str(root),GITHUB_OUTPUT=str(flag),
                             OWNER_AUDIT_SOURCE_SHA='unlisted-source')
            for name in ('GH_TOKEN','GITHUB_TOKEN'):environment.pop(name,None)
            child=subprocess.run([sys.executable,'-'],input=script,text=True,capture_output=True,
                                 cwd=OWNER,env=environment,timeout=30)
            with self.subTest(output_case=kind):
                self.assertEqual(child.returncode,2)
                self.assertNotIn(marker,child.stdout+child.stderr)
                self.assertEqual(child.stderr,'')
                outputs=flag.read_text() if flag.exists() else ''
                if kind=='fresh_hold':
                    self.assertEqual(outputs,'report_written=true\n')
                    report=json.loads(target.read_text())
                    self.assertEqual(report['status'],'HOLD_ARCHIVED_NATIVE_ORIGINAL_READBACK')
                    self.assertIs(report['archived_original_replay_verified'],False)
                    self.assertNotIn('source_record_count',report)
                    self.assertNotIn('native_capsule_count',report)
                    self.assertEqual(target.stat().st_mode&0o777,0o600)
                else:
                    self.assertNotIn('report_written=true',outputs)
                if kind=='collision':self.assertEqual(target.read_text(),marker)
                if kind=='symlink':
                    self.assertTrue(target.is_symlink());self.assertEqual(private.read_text(),marker)

    def test_production_binding_is_exact_public_record_never_fixture_relabelled(self):
        b = self.api._FIXED_BINDING
        self.assertEqual((b.artifact_id,b.workflow_run_id,b.original_zip_size,b.metadata_size,
                          b.record_count,b.native_capsule_count),
                         (13559236491,42334526055,7399390,740,16,88))
        self.assertEqual(b.artifact_name, 'all-existing-model-pairs-42334526055-900001')
        self.assertEqual(b.original_zip_sha256,
            '864d9e43e1ffbcc231a38fc8467648ee21179f402523680700ace75ef397a248')
        self.assertEqual(b.metadata_sha256,
            'fe7ca01fabf94e33340bf60b24096081f5e05c98fa62600977c81398262a8bd3')
        self.assertEqual(b.source_commit, '0490a9d5273d58ae4b50252542608dd40f932431')
        self.assertEqual(b.entry_sha256,
            'e43f9b465b177fb20b834bbdd07069b74437cd3ae057e0b7aaa5f50b38546699')


if __name__ == '__main__':
    unittest.main()
