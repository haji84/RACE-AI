"""Vault replay uses invented encrypted originals, local Git and no source requests."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import base64
import importlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V, saved_view_feed as F
from scripts import boat_saved_view_feed as CLI
from tests import test_boat_private_original_vault as VF
from tests.test_racer_result_bridge import FixtureFeed, saved_view
from tests.test_saved_result_sync import packet, receipt

try:
    R = importlib.import_module('race_ai.boat_vault_result_replay')
except ModuleNotFoundError:
    R = None

DAY = '2030-04-01'
NOW = datetime(2030, 4, 1, 12, tzinfo=timezone.utc)


class VaultReplayTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(R, 'authenticated PC vault replay adapter is absent')
        self.v = VF.VaultTests(); self.v.setUp(); self.addCleanup(self.v.doCleanups)
        self.raw = packet(); self.receipt = receipt(self.raw)
        self.observation = F.parse_capture(self.raw, self.receipt)
        inner = VF.packed({'status.json': V._wire({'day_jst': DAY}),
                          'official-result-observations.json': V._wire([self.observation])})
        sealed = V.native.seal_original_zip(inner, run_id=2, head_sha=VF.HEAD, kind='RESULT', key=VF.KEY)
        original = VF.packed({'private-original.enc': sealed})
        self.meta = dict(id=901, name='race-existing-cycle-2', expired=False,
            created_at='2030-04-01T03:01:00Z', expires_at='2030-04-08T03:01:00Z',
            size_in_bytes=len(original), digest='sha256:'+V._sha(original),
            workflow_run=dict(id=2, head_sha=VF.HEAD, repository_id=1416489937, head_repository_id=1416489937))
        retained = V.retain_originals([(original, V._wire(self.meta))], self.v.writer.repo,
            expected_parent=self.v.parent, key=VF.KEY, transport=self.v.writer,
            readback_transport=self.v.reader, now=NOW)
        locator = V.retain_capture_bundle([(self.raw, V._wire(self.receipt))], self.v.writer.repo,
            run_id=2, head_sha=VF.HEAD, expected_parent=retained['source_commit'], key=VF.KEY,
            transport=self.v.writer, readback_transport=self.v.reader, now=NOW)
        self.config = dict(schema='RACE_AI_BOAT_VAULT_RESULT_REPLAY_INPUT_V1', run_id=2,
            head_sha=VF.HEAD, day=DAY, result_artifact_id=901, expected_capture_count=1, capture_locator=locator)
        self.view = saved_view(('2030-03-31', DAY))
        for row in self.view['records']:
            row.update(venue='INVENTED',offering_status='UNKNOWN')
            row['prediction'].update(prediction_sha256='a'*64,missing_reasons=[])
            cutoff=row['event_date_jst']+'T11:00:00+09:00'
            row['cutoff_at']=row['prediction']['cutoff_at']=cutoff
            row['saved_cutoff_variants']=[cutoff]
        self.git=FixtureFeed(self.v.writer.repo)
        self.bootstrap=dict(key=b'x'*32, view_id='a'*64, cipher_sha256='c'*64,
            forecast_sha256=F.originals_sha(self.view), pages_commit='d'*40)
        self.seed(self.view)

    def seed(self, view):
        raw=F.encrypt_view(view,self.bootstrap['key'],view_id=self.bootstrap['view_id'],
            source_sha='c'*64,generation=1,previous='d'*64)
        ident=V._sha(raw); header=json.loads(raw)['header']; parent=self.git.head()
        commit=self.git.commit({'views/'+ident+'.json':raw,
            'latest.json':V._wire(dict(header=header,cipher_sha256=ident))},parent)
        self.git.push(commit,parent)

    def evidence(self, **changes):
        return R.load_evidence(self.v.reader.repo, self.config, key=VF.KEY,
            transport=self.v.reader, now=NOW, **changes)

    def replay(self):
        return R.replay(self.v.writer.repo, self.config, day=DAY, bootstrap=self.bootstrap,
            feed=self.git, vault=self.v.reader, readback=FixtureFeed(self.v.reader.repo), key=VF.KEY,
            now=NOW, validate_view=CLI._validate_forecast_only_view)

    def test_new_journal_observation_publishes_without_http_or_runtime_and_replay_is_quiet(self):
        vault_head=self.v.writer.head()
        with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')), \
                patch.object(CLI, 'intake_saved_models', side_effect=AssertionError('runtime forbidden')), \
                patch.object(CLI, 'gh', side_effect=AssertionError('live artifact forbidden')):
            report=self.replay()
        self.assertEqual(report['status'],'VAULT_RESULTS_REPLAYED')
        self.assertEqual(report['source_requests'],0)
        self.assertTrue(report['readback_verified'])
        head,_,_,view=F.current_view(self.git,self.bootstrap)
        target=next(row for row in view['records'] if row['event_date_jst']==DAY)
        self.assertEqual(target['result']['status'],'final')
        self.assertEqual(target['result_observations'],[self.observation])
        self.assertEqual(view['records'][0],self.view['records'][0])
        self.assertEqual(F.forecast_inventory(view),F.forecast_inventory(self.view))
        self.assertEqual(self.v.writer.head(),vault_head)
        again=self.replay()
        self.assertEqual(again['changed_races'],0);self.assertEqual(self.git.head(),head)

    def test_old_observation_and_prior_rejection_generation_remain_exact_in_two_day_history(self):
        old=deepcopy(self.view); row=old['records'][1]
        row['result_observations']=[deepcopy(self.observation)]
        row['result']=dict(status='unsupported',winning_combinations=[],confirmed_at=None,
            observed_at=self.receipt['captured_at'],official=False,source_sha256=self.receipt['source_sha256'])
        row['result_observation_rejections']=[dict(captured_at=self.receipt['captured_at'],
            source_sha256=self.receipt['source_sha256'],reason='RESULT_CUTOFF_MISMATCH')]
        self.seed(old)
        p,previous,g,current=F.current_view(self.git,self.bootstrap)
        F.publish_view(self.git,self.bootstrap,current,parent=p,previous=previous,generation=g,history=True)
        parent,previous,_,before=F.current_view(self.git,self.bootstrap,day=DAY)
        old_cipher=self.git.read(parent,'views/'+previous+'.json',F.MAX_WIRE)
        self.replay()
        _,_,_,after=F.current_view(self.git,self.bootstrap,day=DAY)
        self.assertEqual(after['records'][0]['result']['status'],'final')
        self.assertEqual(after['records'][0]['result_observations'],[self.observation])
        self.assertEqual(after['records'][0]['result_revisions'],before['records'][0]['result_revisions'])
        self.assertEqual(after['records'][0]['result_observation_rejections'],[])
        self.assertEqual(self.git.read(parent,'views/'+previous+'.json',F.MAX_WIRE),old_cipher)
        class Prior:
            def head(inner):return parent
            def __getattr__(inner,name):return getattr(self.git,name)
        restored=F.current_view(Prior(),self.bootstrap,day=DAY)[3]
        self.assertEqual(restored,before)
        self.assertEqual(F.current_view(self.git,self.bootstrap,day='2030-03-31')[3]['records'],[old['records'][0]])

    def test_same_clock_original_conflict_never_publishes(self):
        old=deepcopy(self.view); changed=deepcopy(self.observation);changed['reason']='INVENTED_DIFFERENT_NATIVE'
        old['records'][1]['result_observations']=[changed];self.seed(old);head=self.git.head()
        with self.assertRaisesRegex(ValueError,'OBSERVATION_CONFLICT'):
            self.replay()
        self.assertEqual(self.git.head(),head)

    def test_wrong_key_scope_count_or_corrupt_cipher_holds(self):
        with self.assertRaises(ValueError):
            R.load_evidence(self.v.reader.repo,self.config,key=b'z'*32,transport=self.v.reader,now=NOW)
        for fields in ({'run_id':3},{'head_sha':'f'*40},{'day':'2030-04-02'}, {'expected_capture_count':2}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                R.load_evidence(self.v.reader.repo,dict(self.config,**fields),key=VF.KEY,transport=self.v.reader,now=NOW)
        original=self.v.reader.read
        def corrupt(commit,path,limit):
            raw=original(commit,path,limit)
            return raw[:-1]+bytes([raw[-1]^1]) if path.endswith('.enc') else raw
        with patch.object(self.v.reader,'read',side_effect=corrupt),self.assertRaises(ValueError):
            self.evidence()

    def test_new_observation_requires_exact_receipt_and_newer_orphan_cannot_fall_back(self):
        journal,captures,_=self.evidence()
        for mutate in (lambda r:r.update(source_sha256='f'*64),lambda r:r.update(captured_at='2030-04-01T03:00:01Z'),
                       lambda r:r.update(source_url=r['source_url'].replace('rno=1','rno=2'))):
            wrong=deepcopy(captures);mutate(wrong[0][1])
            with self.subTest(),self.assertRaises(ValueError):
                R.prepare(self.view,journal,wrong,day=DAY,synced_at=NOW.isoformat())
        old=deepcopy(self.view);old['records'][1]['result_observations']=[self.observation]
        newer=deepcopy(captures);newer[0][1]['captured_at']='2030-04-01T03:00:01Z'
        with self.assertRaisesRegex(ValueError,'NEWER_UNMATCHED_CAPTURE'):
            R.prepare(old,[],newer,day=DAY,synced_at=NOW.isoformat())

    def test_old_exact_observation_without_current_raw_is_kept_and_unselected_capture_counted(self):
        old=deepcopy(self.view);old['records'][1]['result_observations']=[self.observation]
        other=deepcopy(self.receipt);other['source_url']=other['source_url'].replace('jcd=01','jcd=02')
        after,counts=R.prepare(old,[self.observation],[(self.raw,other)],day=DAY,synced_at=NOW.isoformat())
        self.assertEqual(after['records'][1]['result_observations'],[self.observation])
        self.assertEqual(counts['unselected_captures'],1)

    def test_cli_existing_feed_replay_needs_no_pr72_collector_runtime_or_source(self):
        from race_ai.boat_pdca_recipient import receiver_document
        root=self.v.writer.repo; config_dir=root/'audit'/'state';config_dir.mkdir(parents=True)
        (root/'web').symlink_to(Path(CLI.__file__).resolve().parents[1]/'web',target_is_directory=True)
        bootstrap=F.seal_bootstrap(self.bootstrap['key'],self.bootstrap['view_id'],self.bootstrap['cipher_sha256'],
            self.git.head(),self.bootstrap['forecast_sha256'],
            receiver_document(key=VF.KEY,run_id='2',source_head=VF.HEAD))
        (config_dir/'boat-saved-view-input.json').write_bytes(V._wire(dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1',
            bootstrap=base64.b64encode(bootstrap).decode(),bootstrap_sha256=V._sha(bootstrap),
            catchup_artifact_id=999,catchup_sha256='f'*64)))
        (config_dir/'replay.json').write_bytes(V._wire(self.config))
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',
            GH_TOKEN='invented-token-not-a-credential',RACE_AI_STATE_KEY=base64.b64encode(VF.KEY).decode(),
            PATH=os.environ.get('PATH','/usr/bin:/bin'))
        def vault(repo,*,ref=V.VAULT_REF):return VF.LocalGit(repo,ref=self.v.writer.ref)
        with patch.dict(os.environ,env,clear=True),patch.object(CLI,'ROOT',root), \
                patch.object(F,'FeedRepository',FixtureFeed),patch.object(V,'VaultGitRepository',side_effect=vault), \
                patch.dict(sys.modules,{'scripts.existing_day_program':None,'scripts.boat_all_model_cycle':None,
                                        'race_ai.boat_observed_program_bridge':None}), \
                patch.object(CLI,'intake_saved_models',side_effect=AssertionError('runtime forbidden')), \
                patch.object(CLI,'observations',side_effect=AssertionError('catchup forbidden')), \
                patch.object(CLI,'gh',side_effect=AssertionError('live artifact forbidden')), \
                patch('urllib.request.urlopen',side_effect=AssertionError('source forbidden')), \
                patch.object(R,'datetime') as clock,redirect_stdout(io.StringIO()) as stream:
            clock.now.return_value=NOW
            code=CLI.main(['--replay-vault-config','audit/state/replay.json','--day',DAY])
        self.assertEqual(code,0,stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())['status'],'VAULT_RESULTS_REPLAYED')

    def test_future_capture_clock_rejects_even_when_bundle_is_authentic(self):
        meta=deepcopy(self.receipt);meta['captured_at']='2030-04-01T03:02:00Z'
        locator=V.retain_capture_bundle([(self.raw,V._wire(meta))],self.v.writer.repo,
            run_id=2,head_sha=VF.HEAD,expected_parent=self.v.writer.head(),key=VF.KEY,
            transport=self.v.writer,readback_transport=self.v.reader,now=NOW)
        with self.assertRaisesRegex(ValueError,'CAPTURE_CLOCK_INVALID'):
            R.load_evidence(self.v.reader.repo,dict(self.config,capture_locator=locator),
                key=VF.KEY,transport=self.v.reader,now=NOW)


class ReplayRoutingTests(unittest.TestCase):
    def test_actual_node_reader_receives_no_parent_credentials_or_node_configuration(self):
        import tempfile
        from tests.test_boat_saved_model_view import view
        actual_reader=Path(CLI.__file__).resolve().parents[1]/'web'/'product-data.js'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'web').mkdir()
            preload=root/'poison.cjs';poison_marker=root/'poison-ran';validated=root/'validated'
            preload.write_text('require("node:fs").writeFileSync('+json.dumps(str(poison_marker))+',"poison");')
            wrapper='''const actual=require(ACTUAL);
exports.parse=value=>{
  const forbidden=['RACE_AI_STATE_KEY','GH_TOKEN','NODE_OPTIONS','NODE_PATH','GIT_CONFIG_COUNT','GIT_CONFIG_VALUE_0'];
  if(forbidden.some(key=>Object.hasOwn(process.env,key))) throw new Error('parent environment reached reader');
  if(process.env.LANG!=='C.UTF-8'||process.env.TZ!=='UTC'||!process.env.PATH) throw new Error('reader environment invalid');
  const parsed=actual.parse(value);
  require('node:fs').writeFileSync(MARKER,'actual reader accepted');
  return parsed;
};'''.replace('ACTUAL',json.dumps(str(actual_reader))).replace('MARKER',json.dumps(str(validated)))
            (root/'web'/'product-data.js').write_text(wrapper)
            poison=dict(RACE_AI_STATE_KEY='INVENTED_PARENT_KEY',GH_TOKEN='INVENTED_PARENT_TOKEN',
                NODE_OPTIONS='--require='+str(preload),NODE_PATH=str(root/'untrusted'),
                GIT_CONFIG_COUNT='1',GIT_CONFIG_VALUE_0='INVENTED_PARENT_GIT_CREDENTIAL')
            with patch.dict(os.environ,poison),patch.object(CLI,'ROOT',root):
                CLI._validate_forecast_only_view(view())
            self.assertTrue(validated.exists(),'the actual product reader must validate the input')
            self.assertFalse(poison_marker.exists(),'parent NODE_OPTIONS must not execute in the reader')

    def test_option_conflicts_and_missing_day_stop_before_private_io(self):
        for option in ('--seed-only','--forecasts-only','--result-artifact','--recover-model-run',
                       '--recover-model-config','--hydrate-originals','--history','--history-when-compatible',None):
            args=['--replay-vault-config','audit/state/public.json']
            if option is not None:
                args+=['--day',DAY,option]
                if option in ('--result-artifact','--recover-model-run'):args+=['901']
            with self.subTest(option=option),redirect_stdout(io.StringIO()), \
                    patch.object(CLI,'_read',side_effect=AssertionError('private read before validation')):
                self.assertEqual(CLI.main(args),2)

    def test_missing_owner_stops_before_config_or_git(self):
        with patch.dict(os.environ,{},clear=True),redirect_stdout(io.StringIO()), \
                patch.object(CLI,'_read',side_effect=AssertionError('private read before owner guard')):
            self.assertEqual(CLI.main(['--replay-vault-config','audit/state/public.json','--day',DAY]),2)
