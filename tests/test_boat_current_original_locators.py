"""Current-worker locator hints; actual vault crypto and local Git only."""
import base64
from copy import deepcopy
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import github_existing_cycle as cycle
from race_ai import boat_original_recovery as recovery
from race_ai import boat_private_original_vault as vault
from tests import test_boat_private_original_vault as f


class CurrentOriginalLocatorsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=f.VaultTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.raw,self.metadata=f.original()
        self.locator=self.fixture.retain((self.raw,self.metadata))
        self.temp=self.fixture.root/'runner-temp';self.temp.mkdir(mode=0o700)
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_RUN_ID='2',
                      GITHUB_SHA=f.HEAD,RUNNER_TEMP=str(self.temp),RACE_AI_ORIGINAL_VAULT_ENABLED='true',
                      RACE_AI_STATE_KEY=base64.b64encode(f.KEY).decode())
        self.context=patch.dict(os.environ,self.env,clear=True);self.context.start();self.addCleanup(self.context.stop)
        root=patch.object(cycle,'ROOT',self.fixture.reader.repo);root.start();self.addCleanup(root.stop)
        self.live=[]

    def report(self, locator=None, *, name='boat-baseline-original-vault-9.json', **changes):
        locator=self.locator if locator is None else locator
        value=dict(status='EXACT_ORIGINAL_VAULT_RETAINED',source_commit=locator['source_commit'],
                   retained_originals=1,locators=[deepcopy(locator)],
                   independent_git_readback_verified=True,plaintext_published=False)
        value.update(changes)
        path=self.temp/name;path.write_bytes(f.wire(value)+b'\n');path.chmod(0o600)
        return path,value

    def load(self):
        fn=getattr(cycle,'_current_original_locators',None)
        self.assertTrue(callable(fn),'current private capture report selection is missing')
        return fn()

    def call(self, endpoint, *, head_fails=True, live=None):
        original=recovery.ArtifactRecovery
        def factory(get,repo,**kwargs):
            return original(get,repo,transport=self.fixture.reader,**kwargs)
        def denied(path):
            self.live.append(path)
            if live:return live(path)
            raise AssertionError('current original must not use live GitHub')
        head=patch.object(self.fixture.reader,'head',side_effect=ValueError('STATE_GIT_OPERATION_FAILED')) if head_fails else \
             patch.object(self.fixture.reader,'head',wraps=self.fixture.reader.head)
        with patch.object(cycle,'_ORIGINAL_READER',None), \
             patch('scripts.boat_saved_view_feed.git_auth'), \
             patch.object(recovery,'ArtifactRecovery',side_effect=factory), \
             patch.object(cycle,'_live_gh',side_effect=denied),head:
            return cycle.gh(endpoint)

    def test_constructor_accepts_known_locator_without_querying_mutable_head(self):
        self.assertIn('known_locators',inspect.signature(recovery.ArtifactRecovery).parameters,
                      'known immutable locators are not forwarded to the existing vault reader')
        with patch.object(self.fixture.reader,'head',side_effect=AssertionError('mutable head')):
            reader=recovery.ArtifactRecovery(lambda _:self.fail('live GET'),self.fixture.reader.repo,
                key=f.KEY,transport=self.fixture.reader,known_locators={101:self.locator})
            self.assertEqual(reader('actions/artifacts/101/zip'),self.raw)

    def test_verified_current_capture_uses_exact_commit_even_when_head_lookup_fails(self):
        self.report()
        try:actual=self.call('actions/artifacts/101/zip')
        except ValueError as error:self.fail('current immutable capture still depends on mutable head: '+str(error))
        self.assertEqual(actual,self.raw)
        self.assertEqual(self.live,[])

    def test_current_p1_and_result_captures_preserve_exact_native_originals(self):
        from tests.private_cycle_ui_fixture import _artifacts
        pairs,_,_=_artifacts();admitted=[];seen=set()
        for raw,meta in pairs:
            if meta['name'].startswith('boat-p0'):continue
            kind=vault._kind(meta)
            if kind in seen:continue
            seen.add(kind)
            meta=deepcopy(meta);meta.update(size_in_bytes=len(raw),expires_at='2030-04-08T12:00:00Z')
            meta['workflow_run'].update(repository_id=1416489937,head_sha=f.HEAD)
            admitted.append((raw,f.wire(meta)))
        saved=vault.retain_originals(admitted,self.fixture.writer.repo,expected_parent=self.locator['source_commit'],
            key=f.KEY,transport=self.fixture.writer,readback_transport=self.fixture.reader,now=f.NOW)
        for locator in saved['locators']:
            prefix='baseline' if locator['kind']=='P1' else 'result'
            self.report(locator,name=f'boat-{prefix}-original-vault-9.json')
        os.environ['GITHUB_RUN_ID']='99'
        for raw,metadata in admitted:
            ident=json.loads(metadata)['id']
            self.assertEqual(self.call(f'actions/artifacts/{ident}'),metadata)
            self.assertEqual(self.call(f'actions/artifacts/{ident}/zip'),raw)
        self.assertEqual(self.live,[])

    def test_bad_report_schema_flags_counts_and_commit_are_rejected_before_git(self):
        cases=[dict(status='UNVERIFIED'),dict(independent_git_readback_verified=False),
               dict(independent_git_readback_verified=1),dict(plaintext_published=True),
               dict(retained_originals=2),dict(source_commit='f'*40),dict(extra='private text')]
        for change in cases:
            with self.subTest(fields=list(change)):
                self.report(**change)
                with self.assertRaises(ValueError):self.load()

    def test_private_report_modes_symlinks_hardlinks_and_size_are_rejected(self):
        path,_=self.report();path.chmod(0o644)
        with self.assertRaises(ValueError):self.load()
        path.chmod(0o600);target=self.temp/'other.json';path.rename(target);path.symlink_to(target)
        with self.assertRaises(ValueError):self.load()
        path.unlink();os.link(target,path)
        with self.assertRaises(ValueError):self.load()
        path.unlink();target.unlink();path.write_bytes(b'x'*(128*1024+1));path.chmod(0o600)
        with self.assertRaises(ValueError):self.load()

    def test_only_fixed_prefix_and_canonical_rounds_are_admitted_without_a_24_round_cap(self):
        path,_=self.report(name='boat-baseline-original-vault-999999.json')
        self.assertEqual(self.load(),{101:self.locator})
        path.unlink()
        for name in ('boat-baseline-original-vault-0.json','boat-baseline-original-vault-1000000.json',
                     'boat-baseline-original-vault-09.json','boat-result-original-vault-1.json.extra',
                     'foreign-original-vault-9.json'):
            self.report(name=name)
        self.assertEqual(self.load(),{})

    def test_duplicate_conflicting_locator_rejects_but_identical_hint_is_idempotent(self):
        self.report();path,_=self.report(name='boat-baseline-original-vault-10.json')
        self.assertEqual(self.load(),{101:self.locator})
        self.report(dict(self.locator,source_commit='f'*40),name=path.name)
        with self.assertRaisesRegex(ValueError,'CONFLICT'):self.load()

    def test_locator_shape_kind_and_hash_tampering_cannot_become_a_receipt(self):
        for change in (dict(schema='FOREIGN'),dict(batch_path='../private'),dict(batch_sha256='F'*64),dict(kind='RESULT')):
            with self.subTest(field=list(change)):
                self.report(dict(self.locator,**change))
                with self.assertRaises(ValueError):self.load()
        self.report(dict(self.locator,batch_sha256='f'*64))
        with self.assertRaises(ValueError):self.call('actions/artifacts/101/zip')
        self.assertEqual(self.live,[])

    def test_current_owner_run_and_head_are_checked_after_authenticated_restore(self):
        self.report()
        for name,value in [('GITHUB_RUN_ID','3'),('GITHUB_SHA','b'*40)]:
            with self.subTest(field=name),patch.dict(os.environ,{name:value}):
                with self.assertRaisesRegex(ValueError,'CURRENT_ORIGINAL_OWNER'):self.call('actions/artifacts/101/zip')
        self.assertEqual(self.live,[])

    def test_wrong_valid_key_and_forged_batch_mac_never_fall_back_to_live(self):
        self.report()
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(1,33))).decode()):
            with self.assertRaises(ValueError):self.call('actions/artifacts/101/zip')
        batch=self.locator['batch_path']
        data=json.loads(self.fixture.writer.read(self.locator['source_commit'],batch,2*1024*1024))
        data['mac']='0'*64;body=f.wire(data)+b'\n';digest=sha256(body).hexdigest()
        forged_path=str(Path(batch).with_name(digest+'.json'))
        bad=self.fixture.writer.commit({forged_path:body},self.locator['source_commit'])
        self.fixture.writer.push(bad,self.locator['source_commit'])
        locator=dict(self.locator,source_commit=bad,batch_path=forged_path,batch_sha256=digest)
        self.report(locator)
        with self.assertRaisesRegex(ValueError,'AUTHENTICATION'):self.call('actions/artifacts/101/zip')
        self.assertEqual(self.live,[])

    def test_runner_temp_traversal_symlink_and_repository_paths_are_rejected(self):
        self.report();link=self.fixture.root/'link';link.symlink_to(self.temp,target_is_directory=True)
        for path in (str(self.temp/'..'/'runner-temp'),str(link),str(self.fixture.reader.repo)):
            with self.subTest(path_kind='unsafe'),patch.dict(os.environ,RUNNER_TEMP=path):
                with self.assertRaises(ValueError):self.load()

    def test_no_current_report_keeps_legacy_unknown_lookup_and_denial_stop(self):
        self.assertEqual(self.load(),{})
        for status in (403,429):
            self.live.clear()
            def denial(_):raise RuntimeError(f'GITHUB_API_READ_HTTP_{status}_HALT')
            with self.assertRaisesRegex(RuntimeError,str(status)):
                self.call('actions/artifacts/999/zip',head_fails=False,live=denial)
            self.assertEqual(self.live,['actions/artifacts/999/zip'])


class GitFailureDiagnosticsTests(unittest.TestCase):
    def test_nonzero_git_reports_fixed_operation_and_status_without_retry_or_private_text(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        cases=[('ls-remote','REMOTE_LOOKUP',b'HTTP 401','HTTP_401'),
               ('fetch','FETCH',b'The requested URL returned error: 403','HTTP_403'),
               ('push','PUSH',b'HTTP/2 429','HTTP_429'),
               ('show','LOCAL',b'HTTP: 500','HTTP_500'),
               ('ls-remote','REMOTE_LOOKUP',b'authentication failed','UNKNOWN'),
               ('ls-remote','REMOTE_LOOKUP',b'HTTP 401 then HTTP 403','UNKNOWN')]
        for kind,prefix in ((GitStateRepository,'STATE'),(vault.VaultGitRepository,'VAULT')):
            git=object.__new__(kind);git.repo=Path('.')
            for command,label,status,text in cases:
                with self.subTest(transport=prefix,command=command,status=text):
                    failure=subprocess.CompletedProcess(['git',command,'private-argv-token'],1,
                        b'private-stdout-body',b'https://private-token@example.invalid/private-source '+status)
                    with patch.object(git,'_reject_rewrites'),patch(
                            'race_ai.boat_pdca_github_handoff.subprocess.run',return_value=failure) as run:
                        with self.assertRaises(ValueError) as rejected:
                            git._run([command,'private-argv-token'])
                    self.assertEqual(str(rejected.exception),f'{prefix}_GIT_OPERATION_FAILED_{label}_{text}')
                    self.assertEqual(run.call_count,1)
                    for private in ('private','token','example.invalid','https://'):
                        self.assertNotIn(private,repr(rejected.exception))


if __name__=='__main__':unittest.main()
