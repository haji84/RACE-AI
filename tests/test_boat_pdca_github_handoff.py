"""Fictional inputs only; local bare Git exercises immutable publication."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_pdca_state import PdcaState
from race_ai.boat_history_store import HistoryStore,instant,wire
from race_ai.boat_history_comparison import prepare_pair,freeze_pair
from tests.test_boat_history_store import archives,DAY
from tests.test_boat_history_comparison import current,NOW
from tests.test_boat_pdca_state import result

TEST_KEY=os.urandom(32)  # Ephemeral invented-data test key; never actual data.


def invented_research_state(root):
    history=HistoryStore(root/'history.sqlite');raw,proof=archives()
    history.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
    pair=prepare_pair(current(),history,NOW);history.close()
    p=root/'pair.json';freeze_pair(pair,p,clock=lambda:instant(NOW))
    state=PdcaState.create(root/'state.sqlite',mode='production');state.retain_pair(p)
    state.score(pair['pair_sha256'],result(pair),'2026-11-06T12:00:00+09:00');state.close()
    return root/'state.sqlite',pair


class GithubHandoffTests(unittest.TestCase):
    def test_exact_state_fetch_uses_blobless_transport_but_preserves_full_history(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        git=object.__new__(GitStateRepository)
        git.fetch_url='https://github.com/haji84/RACE-AI.git'
        with patch.object(git,'_run',return_value=b'') as run:
            git.fetch('a'*40)
            args=run.call_args.args[0]
            self.assertEqual(args,[
                'fetch','--filter=blob:none','--no-tags','--no-write-fetch-head',
                'https://github.com/haji84/RACE-AI.git',
                'a'*40+':refs/race-ai/pinned-state/'+'a'*40])
            self.assertNotIn('--depth',args)
            with self.assertRaises(ValueError):
                git.fetch('--upload-pack=malicious')
        self.assertEqual(run.call_count,1)

    def test_pinned_fetches_remain_reachable_for_incremental_following_fetch(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        class LocalFixtureGit(GitStateRepository):
            def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bare=root/'remote.git';producer=root/'producer';consumer=root/'consumer'
            subprocess.run(['git','init','--bare',str(bare)],check=True,capture_output=True)
            for path in (producer,consumer):
                subprocess.run(['git','init',str(path)],check=True,capture_output=True)
                subprocess.run(['git','-C',str(path),'remote','add','origin',str(bare)],check=True,capture_output=True)
            source=LocalFixtureGit(producer);first=source.commit({'one.enc':b'invented'},None);source.push(first,None)
            second=source.commit({'two.enc':b'more invented'},first);source.push(second,first)
            reader=LocalFixtureGit(consumer);reader.fetch(first)
            reachable=lambda:set(reader._run(['rev-list','--all']).decode().splitlines())
            self.assertIn(first,reachable())
            reader.fetch(second);self.assertTrue({first,second}<=reachable())
            with patch.object(reader,'_run') as network:
                with self.assertRaises(ValueError):reader.fetch('--upload-pack=unexpected')
                network.assert_not_called()

    def test_large_pinned_fetch_has_a_bounded_longer_timeout_than_local_commands(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        git=object.__new__(GitStateRepository);git.repo=Path('.')
        with patch.object(git,'_reject_rewrites'),patch('race_ai.boat_pdca_github_handoff.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as run:
            git._run(['fetch','fixture'])
            self.assertGreater(run.call_args.kwargs['timeout'],60)
            self.assertLessEqual(run.call_args.kwargs['timeout'],180)
            git._run(['rev-list','--all'])
            self.assertLessEqual(run.call_args.kwargs['timeout'],60)

    def test_cli_missing_key_reports_hold_and_unexpected_errors_do_not_echo_private_data(self):
        import io
        from contextlib import redirect_stdout
        from scripts.boat_pdca_github import main
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{},clear=True):
            root=Path(d);out=io.StringIO()
            with redirect_stdout(out):code=main(['publish','--state',str(root/'missing.sqlite'),'--repo',str(root/'repo'),
                '--output',str(root/'out'),'--initialize'])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(out.getvalue())['status'],'HOLD_OWNER_STATE_KEY_MISSING')
            self.assertFalse((root/'out').exists())
            pointer=root/'input.json';pointer.write_text('{}');out=io.StringIO()
            with patch('scripts.boat_pdca_github.readback',side_effect=RuntimeError('private-source-sentinel')),redirect_stdout(out):
                code=main(['readback','--input',str(pointer),'--private-dir',str(root/'read')])
            self.assertEqual(code,2);self.assertNotIn('private-source-sentinel',out.getvalue())

    def test_every_fetch_and_push_url_must_be_one_expected_repository(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);subprocess.run(['git','init',str(root)],check=True,capture_output=True)
            run=lambda *args:subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
            good='https://github.com/haji84/RACE-AI.git'
            run('remote','add','origin','https://example.invalid/other.git')
            run('config','remote.origin.pushurl',good)
            with self.assertRaisesRegex(ValueError,'REPOSITORY_REJECTED'):GitStateRepository(root)
            run('remote','set-url','origin',good)
            run('config','--add','remote.origin.pushurl','https://example.invalid/other.git')
            with self.assertRaisesRegex(ValueError,'REPOSITORY_REJECTED'):GitStateRepository(root)
            run('config','--unset-all','remote.origin.pushurl')
            git=GitStateRepository(root)
            with patch.object(git,'_run',return_value=b'') as cmd:git.head()
            self.assertIn(good,cmd.call_args.args[0])

    def test_deleted_or_dangling_heads_cannot_pass_regression_check(self):
        from race_ai.boat_pdca_github_handoff import _no_regression
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old=PdcaState.create(root/'old.sqlite',mode='production')
            with old.db:old._put('history.sqlite',b'invented database bytes')
            new=PdcaState.create(root/'new.sqlite',mode='production');old.db.backup(new.db)
            with new.db:new.db.execute("DELETE FROM heads WHERE name='history.sqlite'")
            with self.assertRaisesRegex(ValueError,'HEAD'):_no_regression(old,new)
            old.db.backup(new.db)
            with new.db:new.db.execute("UPDATE heads SET sha=? WHERE name='history.sqlite'",('0'*64,))
            with self.assertRaisesRegex(ValueError,'HEAD'):_no_regression(old,new)
            new.close();old.close()

    def test_owner_key_file_is_private_and_cli_never_echoes_its_value(self):
        import base64,io
        from contextlib import redirect_stdout
        from scripts.boat_pdca_github import owner_key_file,main
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);key=root/'owner.b64';encoded=base64.b64encode(TEST_KEY)
            key.write_bytes(encoded+b'\n');key.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'PRIVATE_KEY_FILE'):owner_key_file(key)
            key.chmod(0o600);self.assertEqual(owner_key_file(key),TEST_KEY)
            alias=root/'linked';alias.symlink_to(key)
            with self.assertRaises(ValueError):owner_key_file(alias)
            p=root/'input.json';p.write_text(json.dumps(dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',
                status='WAITING_ENCRYPTED_INPUT',repository_id='1416489937')))
            out=io.StringIO()
            with redirect_stdout(out):code=main(['readback','--input',str(p),'--private-dir',str(root/'out'),'--owner-key-file',str(key)])
            self.assertEqual(code,0);self.assertNotIn(encoded.decode(),out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['status'],'HOLD_ENCRYPTED_INPUT_REQUIRED')

    def test_unregistered_generation_file_cannot_be_overwritten(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository,publish_checkpoint
        class LocalFixtureGit(GitStateRepository):
            def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);repo=root/'repo';repo.mkdir();remote=root/'remote.git'
            for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):
                subprocess.run(args,check=True,capture_output=True)
            state_path,_=invented_research_state(root);git=LocalFixtureGit(repo)
            first=publish_checkpoint(state_path,repo,root/'one',initialize=True,key=TEST_KEY,transport=git,now='2026-11-06T12:00:00+09:00')
            reserved='state/boat-pdca/v1/g000002/state.enc'
            parent=git.commit({reserved:b'existing unpublished ciphertext'},first['source_commit']);git.push(parent,first['source_commit'])
            with self.assertRaisesRegex(ValueError,'GENERATION_ALREADY_EXISTS'):
                publish_checkpoint(state_path,repo,root/'two',expected_parent=parent,key=TEST_KEY,transport=git,now='2026-11-06T12:00:00+09:00')
            self.assertEqual(git.read(parent,reserved,128*1024*1024),b'existing unpublished ciphertext')
            self.assertEqual(git.head(),parent)

    def test_absent_owner_key_has_no_git_or_source_activity(self):
        from race_ai.boat_pdca_github_handoff import publish_checkpoint,readback
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{},clear=True), \
             patch('race_ai.boat_pdca_github_handoff.GitStateRepository',side_effect=AssertionError('unexpected Git access')):
            p=Path(d)
            with self.assertRaisesRegex(ValueError,'OWNER_STATE_KEY'):publish_checkpoint(p/'missing.sqlite',p,p/'out',initialize=True)
            report=readback({'status':'WAITING_ENCRYPTED_INPUT'},p/'read',fetch=lambda u:(_ for _ in ()).throw(AssertionError('unexpected GET')))
            self.assertEqual(report['status'],'HOLD_OWNER_STATE_KEY_MISSING')
            self.assertEqual(report['source_gets'],0);self.assertFalse((p/'read').exists())

    def test_two_generations_roundtrip_real_git_and_reject_missing_anchor_or_regression(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository,publish_checkpoint,readback,STATE_REF
        class LocalFixtureGit(GitStateRepository):
            def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'repo';source.mkdir();bare=root/'remote.git'
            for argv in (['git','init','--bare',str(bare)],['git','init',str(source)],
                         ['git','-C',str(source),'remote','add','origin',str(bare)]):
                subprocess.run(argv,check=True,capture_output=True)
            state_path,pair=invented_research_state(root);git=LocalFixtureGit(source)
            first=publish_checkpoint(state_path,source,root/'one',initialize=True,key=TEST_KEY,transport=git,now='2026-11-06T12:00:00+09:00')
            def fetch(pointer):return lambda url:git.read(pointer['source_commit'],pointer['cipher_path'],128*1024*1024)
            checked=readback(first,root/'restored',key=TEST_KEY,fetch=fetch(first),now='2026-11-06T12:00:00+09:00')
            self.assertTrue(checked['production_schema_readback_verified'])
            self.assertEqual(checked['pairs_verified'],1);self.assertEqual(checked['score_replays'],1)
            self.assertFalse(checked['accuracy_improvement_proven'])
            with self.assertRaisesRegex(ValueError,'PARENT'):publish_checkpoint(state_path,source,root/'no-anchor',key=TEST_KEY,transport=git)
            state=PdcaState(state_path);correction=result(pair);correction['captured_at']='2026-11-06T11:20:00+09:00'
            correction['source_sha256']='e'*64;correction['data']['payouts'][0]['payout_per_100_yen']=1500
            state.score(pair['pair_sha256'],correction,'2026-11-06T12:00:00+09:00');state.close()
            second=publish_checkpoint(state_path,source,root/'two',expected_parent=first['source_commit'],key=TEST_KEY,transport=git,now='2026-11-06T12:00:00+09:00')
            self.assertEqual(second['scope']['generation'],2)
            self.assertEqual(second['scope']['previous_cipher_sha256'],first['cipher_sha256'])
            self.assertEqual(git.read(first['source_commit'],first['cipher_path'],128*1024*1024),(root/'one/state.enc').read_bytes())
            regress=PdcaState.create(root/'regress.sqlite',mode='production');regress.close()
            with self.assertRaisesRegex(ValueError,'REGRESSION'):
                publish_checkpoint(root/'regress.sqlite',source,root/'regress',expected_parent=second['source_commit'],key=TEST_KEY,transport=git)
            self.assertEqual(git.head(),second['source_commit'])

    def test_pointer_wrong_repo_path_hash_or_key_is_rejected(self):
        from race_ai.boat_pdca_github_handoff import readback
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state_path,_=invented_research_state(root)
            state=PdcaState(state_path);proof=state.checkpoint(root/'sealed',generation=1,key=TEST_KEY);state.close()
            pointer=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
                source_commit='a'*40,cipher_path='state/boat-pdca/v1/g000001/state.enc',cipher_sha256=proof['cipher_sha256'],scope=proof['scope'])
            for field,value in [('repository_id','other'),('cipher_path','../../plain.sqlite'),('cipher_sha256','0'*64)]:
                bad=dict(pointer,**{field:value})
                with self.subTest(field=field),self.assertRaises(ValueError):
                    readback(bad,root/field,key=TEST_KEY,fetch=lambda u:(root/'sealed/state.enc').read_bytes())
                self.assertFalse((root/field/'state.sqlite').exists())
            with self.assertRaises(ValueError):readback(pointer,root/'wrongkey',key=bytes(reversed(range(32))),fetch=lambda u:(root/'sealed/state.enc').read_bytes())
            self.assertFalse((root/'wrongkey/state.sqlite').exists())
