"""Authenticated P1 without a RESULT is retained, never counted as completed."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from tests.test_boat_pending_round_recovery import fixture, encrypted, DAY, NOW
from tests.test_boat_private_original_vault import packed, KEY, HEAD
from race_ai import boat_pending_round_recovery as recovery
from race_ai import boat_private_original_archive as archive
from race_ai import boat_source_control as public
from race_ai.actions_contract import digest
from race_ai.frozen_day_cycle import read_p1


def orphan_fixture():
    run,_,responses=fixture()
    run['name']='BOAT nationwide cutoff-ordered A/B research (no Vercel)'
    p1=deepcopy(json.loads(responses['actions/artifacts/123']))
    p1['name']='boat-national-cutoff-99-cycle-07'
    p1_raw=responses['actions/artifacts/123/zip']
    session=dict(schema='RACE_AI_CONTINUOUS_REPEAT_V2',run_id=99,day_jst=DAY,
        requests_used=70,completed_round=6,prepared_round=7,
        lifetime_requests_base=11742,lifetime_requests=11812,
        lifetime_completed_rounds_base=632,lifetime_completed_rounds=638,
        day_start_lifetime_requests=11524,source_wait=None,halted_reason=None)
    session['session_sha256']=digest(session)
    cipher=archive.seal_original_zip(packed({'repeat-session.json':json.dumps(session)}),
        run_id=99,head_sha=HEAD,kind='CONTINUITY',key=KEY)
    continuity=packed({'private-original.enc':cipher})
    summary=public.build_summary(cipher,run_id=99,head_sha=HEAD,key=KEY)
    control_zip=packed({'source-control.json':json.dumps(summary)})
    def metadata(ident,name,raw,created):
        return dict(id=ident,name=name,created_at=created,expired=False,
            expires_at='2030-04-08T02:00:00Z',size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(),workflow_run=dict(id=99,
                head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
    continuity_meta=metadata(702,'race-cycle-continuity-99',continuity,'2030-04-01T02:31:00Z')
    control_meta=metadata(703,'race-source-control-99',control_zip,'2030-04-01T02:31:01Z')
    control=public.read_summary(control_zip,control_meta,continuity,continuity_meta,
                                run_id=99,head_sha=HEAD)
    items=[p1,continuity_meta,control_meta]
    replies={'actions/runs/99':json.dumps(run).encode(),
             'actions/runs/99/artifacts?per_page=100':json.dumps(dict(total_count=3,artifacts=items)).encode()}
    for raw,meta in [(p1_raw,p1),(continuity,continuity_meta),(control_zip,control_meta)]:
        replies[f'actions/artifacts/{meta["id"]}']=json.dumps(meta).encode()
        replies[f'actions/artifacts/{meta["id"]}/zip']=raw
    _,rows=read_p1(p1_raw,p1)
    state=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=DAY,
               source_control=control,rows=rows,receipts=[p1],complete=True)
    return run,control,replies,state


class OrphanP1RecoveryTests(unittest.TestCase):
    def setUp(self):
        import base64,os
        from unittest.mock import patch
        env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        env.start();self.addCleanup(env.stop)
        self.run_meta,self.control,self.replies,self.state=orphan_fixture()

    def restore(self):
        return recovery.reconcile_restored_state(self.state,lambda route:self.replies[route],
                                                 now=NOW,expected_head=HEAD)

    def test_producer_requires_current_checkout_or_explicit_reviewed_origin(self):
        for expected in (None,'e'*40):
            with self.subTest(expected=expected),self.assertRaises(ValueError):
                recovery.reconcile_restored_state(self.state,lambda route:self.replies[route],
                                                 now=NOW,expected_head=expected)

    def test_new_release_recovers_only_exact_reviewed_checkpoints(self):
        from scripts.boat_recover_failed_owner import recover_history
        from tests.test_frozen_day_cycle import sample
        from race_ai.frozen_day_cycle import read_p0
        reviewed=('eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
                  '86b029ae5bddd5d4956497d8b32b2c92b8eec521',
                  'f55351dce855177a51330f72c37d6238ba2c9e3e')
        expected='e'*40
        for origin in (*reviewed,'f'*40):
            with self.subTest(origin=origin):
                previous=origin
                with patch(__name__+'.HEAD',origin), \
                     patch('tests.test_boat_pending_round_recovery.HEAD',origin):
                    run,control,replies,state=orphan_fixture()
                before=deepcopy((run,control,replies,state))
                get=lambda route:replies[route]
                if origin not in reviewed:
                    with self.assertRaisesRegex(ValueError,'ORPHAN_SOURCE_NOT_REVIEWED'):
                        recovery.reconcile_restored_state(state,get,now=NOW,expected_head=expected)
                    continue
                _,raw,meta=sample();_,p0=read_p0(raw,meta,expected_day=DAY)
                replay=deepcopy(state);replay['rows']=p0+replay['rows'];replay['receipts'].append(meta)
                with patch('urllib.request.urlopen',side_effect=AssertionError('provider access')):
                    restored,pending=recovery.reconcile_restored_state(
                        state,get,now=NOW,expected_head=expected)
                    proof=recover_history([run],get=get,load_control=lambda _:deepcopy(control),
                        replay_day=lambda:replay,
                        retain=lambda *_:dict(independent_git_readback_verified=True,source_commit='d'*40),
                        now=NOW,expected_head=expected)
                self.assertEqual(pending['run']['head_sha'],previous)
                self.assertEqual((restored['source_control']['completed_round'],
                                  restored['source_control']['prepared_round']),(6,None))
                for name in ('previous_session_requests','lifetime_requests',
                             'day_start_lifetime_requests','lifetime_completed_rounds'):
                    self.assertEqual(restored['source_control'][name],control[name])
                self.assertEqual(proof['head_sha'],expected)
                self.assertEqual(proof['repairs'][0]['original_head_sha'],previous)
                self.assertEqual(proof['repairs'][0]['original_artifact_ids'],[123,702,703])
                self.assertIsNotNone(recovery.verify_dispatch_proof(proof,[run],control,expected,NOW))
                old_authority=deepcopy(proof);old_authority['head_sha']=previous
                self.assertIsNone(recovery.verify_dispatch_proof(old_authority,[run],control,expected,NOW))
                self.assertEqual((run,control,replies,state),before)

    def test_reviewed_eff_checkout_cannot_execute_new_release_recovery(self):
        self._assert_reviewed_checkout_refused('eff296f6d54ad4be297d93e32f1ee0d4592ad9e3')

    def test_reviewed_m2_checkout_cannot_execute_new_release_recovery(self):
        self._assert_reviewed_checkout_refused('86b029ae5bddd5d4956497d8b32b2c92b8eec521')

    def test_reviewed_f553_checkout_cannot_execute_new_release_recovery(self):
        self._assert_reviewed_checkout_refused('f55351dce855177a51330f72c37d6238ba2c9e3e')

    def test_reviewed_f553_origin_still_requires_exact_source_cipher_bytes(self):
        import io,zipfile
        origin='f55351dce855177a51330f72c37d6238ba2c9e3e'
        with patch(__name__+'.HEAD',origin), \
             patch('tests.test_boat_pending_round_recovery.HEAD',origin):
            run,control,replies,state=orphan_fixture()
        with zipfile.ZipFile(io.BytesIO(replies['actions/artifacts/123/zip'])) as z:
            cipher=z.read('private-original.enc')
        wrong_tag=packed({'private-original.enc':cipher[:-1]+bytes([cipher[-1]^1])})
        for case,raw in (
                ('other_source_cipher',self.replies['actions/artifacts/123/zip']),
                ('unauthenticated_plaintext',packed({'forecasts.json':b'{}'})),
                ('tampered_cipher',wrong_tag)):
            changed=deepcopy(replies)
            metadata=json.loads(changed['actions/artifacts/123'])
            metadata.update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
            changed['actions/artifacts/123']=json.dumps(metadata).encode()
            changed['actions/artifacts/123/zip']=raw
            route='actions/runs/99/artifacts?per_page=100';listing=json.loads(changed[route])
            listing['artifacts']=[metadata if item['id']==123 else item for item in listing['artifacts']]
            changed[route]=json.dumps(listing).encode()
            before=deepcopy((run,control,changed,state));reads=[]
            def get(route):
                reads.append(route)
                return changed[route]
            with self.subTest(case=case), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('provider access')):
                with self.assertRaises(ValueError):
                    recovery.reconcile_restored_state(state,get,now=NOW,expected_head='e'*40)
                self.assertIn('actions/artifacts/123/zip',reads)
                self.assertEqual((run,control,changed,state),before)

    def _assert_reviewed_checkout_refused(self,previous):
        from contextlib import redirect_stdout
        import io,os,tempfile
        from pathlib import Path
        from scripts import boat_recover_failed_owner as cli
        from tests.test_boat_recovery_invocation import callback,MAIN,WORKFLOW_REF
        document=callback();document['workflow_run']['head_sha']=previous
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);event=root/'event.json';event.write_text(json.dumps(document))
            env=dict(GITHUB_EVENT_NAME='workflow_run',GITHUB_EVENT_PATH=str(event),
                GITHUB_WORKFLOW_REF=WORKFLOW_REF,GITHUB_REF='refs/heads/main',GITHUB_SHA=MAIN)
            out=io.StringIO()
            with patch.dict(os.environ,env),patch.object(cli,'_packages'), \
                 patch('scripts.boat_private_original_vault._environment',return_value=root), \
                 patch.object(cli.subprocess,'check_output',return_value=previous.encode()), \
                 patch('scripts.boat_private_original_vault._private_path') as output, \
                 patch('scripts.github_existing_cycle.gh',side_effect=AssertionError('remote access')) as remote, \
                 redirect_stdout(out):
                code=cli.main(['--history',str(root/'history.json'),'--expected-head','e'*40,
                               '--output',str(root/'proof.json')])
            report=json.loads(out.getvalue())
            self.assertEqual(code,2)
            self.assertEqual(report['reason'],'ROUND_RECOVERY_CHECKOUT_RELEASE_CHANGED')
            self.assertFalse(report['successor_dispatch_allowed'])
            output.assert_not_called();remote.assert_not_called()
            self.assertFalse((root/'proof.json').exists())

    def test_producer_restores_orphan_without_inventing_completed_round_or_result(self):
        before=deepcopy((self.control,self.replies,self.state))
        restored,pending=self.restore()
        c=restored['source_control']
        self.assertEqual((c['completed_round'],c['prepared_round']),(6,None))
        self.assertEqual((c['previous_session_requests'],c['lifetime_requests'],
                          c['day_start_lifetime_requests'],c['lifetime_completed_rounds']),
                         (70,11812,11524,638))
        self.assertEqual(restored['rows'],self.state['rows'])
        self.assertEqual((self.control,self.replies,self.state),before)
        self.assertEqual(c['recovery']['schema'],'RACE_AI_ORPHAN_P1_ABANDONMENT_V1')
        self.assertFalse(c['recovery']['completed_round_advanced'])
        self.assertEqual(pending['verified']['new_forecasts'],0)
        self.assertEqual(pending['verified']['official_source_requests'],0)
        self.assertNotIn('race-existing-cycle-99-cycle-07',json.dumps(c))

    def test_listed_but_unreadable_result_must_not_be_treated_as_absent(self):
        route='actions/runs/99/artifacts?per_page=100';listing=json.loads(self.replies[route])
        listing['artifacts'].append(dict(id=799,name='race-existing-cycle-99-cycle-07'))
        listing['total_count']+=1;self.replies[route]=json.dumps(listing).encode()
        with self.assertRaises((ValueError,KeyError)):self.restore()
        self.assertEqual(self.control['prepared_round'],7)

    def test_public_control_must_match_actual_checkpoint_AES(self):
        self.control['lifetime_requests']+=1
        with self.assertRaises(ValueError):self.restore()

    def test_rehashed_public_counter_does_not_replace_checkpoint_aes_authentication(self):
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(self.replies['actions/artifacts/703/zip'])) as z:
            summary=json.loads(z.read('source-control.json'))
        summary['control']['lifetime_requests']+=1
        raw=packed({'source-control.json':json.dumps(summary)})
        meta=json.loads(self.replies['actions/artifacts/703'])
        meta.update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
        self.replies['actions/artifacts/703/zip']=raw
        self.replies['actions/artifacts/703']=json.dumps(meta).encode()
        route='actions/runs/99/artifacts?per_page=100';listing=json.loads(self.replies[route])
        listing['artifacts']=[meta if item['id']==703 else item for item in listing['artifacts']]
        self.replies[route]=json.dumps(listing).encode()
        self.control['lifetime_requests']+=1
        self.control['source_control_receipt']['digest']=meta['digest']
        with self.assertRaises(ValueError):self.restore()

    def test_successor_inherits_exact_usage_and_does_not_advance_the_abandoned_round(self):
        import tempfile
        from pathlib import Path
        from race_ai import repeated_cycle
        restored,_=self.restore()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json'
            state=repeated_cycle.start(path,day=DAY,run_id=100,now=NOW,
                                        source_control=restored['source_control'])
            self.assertEqual((state['completed_round'],state['lifetime_completed_rounds']),(0,638))
            repeated_cycle.prepare(path,1,now=NOW)
            repeated_cycle.SourceGuard(path,clock=lambda:NOW).charge('forecast')
            latest=repeated_cycle.load(path)
            self.assertEqual((latest['lifetime_requests'],latest['day_start_lifetime_requests']),(11813,11524))
            self.assertEqual(latest['source_control']['recovery']['original_control']['prepared_round'],7)

    def test_successor_must_not_skip_an_unresolved_same_day_prepared_round(self):
        import tempfile
        from pathlib import Path
        from race_ai import repeated_cycle
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
            repeated_cycle.start(Path(folder)/'session.json',day=DAY,run_id=100,now=NOW,
                                 source_control=self.control)

    def proof(self):
        from scripts.boat_recover_failed_owner import recover_history
        from tests.test_frozen_day_cycle import sample
        from race_ai.frozen_day_cycle import read_p0
        _,raw,meta=sample();_,p0=read_p0(raw,meta,expected_day=DAY)
        state=deepcopy(self.state);state['rows']=p0+state['rows'];state['receipts'].append(meta)
        return recover_history([self.run_meta],get=lambda p:self.replies[p],
            load_control=lambda _:deepcopy(self.control),replay_day=lambda:state,
            retain=lambda checked,run:dict(independent_git_readback_verified=True,source_commit='d'*40),
            now=NOW,expected_head=HEAD)

    def test_actual_main_recovery_path_accepts_typed_abandonment_after_retention(self):
        proof=self.proof()
        accepted=recovery.verify_dispatch_proof(proof,[self.run_meta],self.control,HEAD,NOW)
        self.assertIsNotNone(accepted)
        self.assertEqual((accepted['completed_round'],accepted['prepared_round'],
                          accepted['lifetime_completed_rounds']),(6,None,638))
        self.assertEqual(proof['repairs'][0]['original_artifact_ids'],[123,702,703])
        self.assertEqual(proof['repairs'][0]['original_head_sha'],HEAD)

    def test_abandonment_proof_cannot_be_changed_into_completion_or_counter_reset(self):
        proof=self.proof()
        for changes in (dict(completed_round=7),dict(lifetime_completed_rounds=639),
                        dict(lifetime_requests=0),dict(day_start_lifetime_requests=0)):
            altered=deepcopy(proof);altered['repairs'][0]['control'].update(changes)
            altered['latest_control']=deepcopy(altered['repairs'][0]['control'])
            with self.subTest(changes=changes):
                self.assertIsNone(recovery.verify_dispatch_proof(altered,[self.run_meta],self.control,HEAD,NOW))
        for flag in ('checkpoint_AES_authenticated','missing_result_inventory_verified','first_receipt_union_verified'):
            altered=deepcopy(proof);altered['repairs'][0]['control']['recovery'][flag]=False
            altered['latest_control']=deepcopy(altered['repairs'][0]['control'])
            with self.subTest(flag=flag):
                self.assertIsNone(recovery.verify_dispatch_proof(altered,[self.run_meta],self.control,HEAD,NOW))

    def test_real_local_vault_retains_exact_orphan_and_checkpoint_trio_idempotently(self):
        from scripts.boat_recover_failed_owner import retain_verified_pair
        from tests.test_boat_private_original_vault import VaultTests
        _,pending=self.restore();fixture_git=VaultTests();fixture_git.setUp()
        self.addCleanup(fixture_git.doCleanups)
        def retain():
            return retain_verified_pair(pending['verified'],self.run_meta,fixture_git.writer.repo,
                now=NOW,transport=fixture_git.writer,readback_transport=fixture_git.reader)
        first=retain();self.assertTrue(first['independent_git_readback_verified'])
        self.assertEqual(len(first['locators']),3)
        for locator in first['locators']:
            self.assertEqual(fixture_git.restore(locator)['raw_zip'],
                             self.replies[f'actions/artifacts/{locator["artifact_id"]}/zip'])
        commit=fixture_git.writer.head();second=retain()
        self.assertEqual(second['status'],'EXACT_ORIGINAL_VAULT_UNCHANGED')
        self.assertEqual(fixture_git.writer.head(),commit)

    def test_full_day_replay_preserves_publication_waits_without_refreshing_stale_schedule(self):
        import io,tempfile,zipfile
        from pathlib import Path
        from race_ai import cycle_recovery,repeated_cycle
        from tests.test_frozen_day_cycle import sample
        _,p0_raw,p0_meta=sample();p0_meta=deepcopy(p0_meta)
        p0_meta.update(name='boat-p0-existing-99',expires_at='2030-04-08T02:00:00Z')
        p0_meta['workflow_run']['id']=99
        p0_raw,p0_meta=encrypted(p0_raw,p0_meta,'P0')
        with archive.open_original_zip(self.replies['actions/artifacts/123/zip'],
                                      json.loads(self.replies['actions/artifacts/123']),
                                      expected_kind='P1') as z:
            document=json.loads(z.read('national.json'))
        document.pop('observed_pairwise_p1_bundles',None)
        document.pop('additional_official_feature_shadows',None)
        captured='2030-04-01T02:00:00+00:00';cutoff='2030-04-01T03:00:00+00:00'
        wait=dict(race_id='20300401-01-01',cutoff_at=cutoff,state='WAITING_PUBLICATION',
                  reason='SOURCE_NOT_YET_PUBLISHED',retry_at='2030-04-01T02:45:00+00:00',
                  http_status=200,attempts=1)
        captured=(public._time(json.loads(self.replies['actions/artifacts/123'])['created_at'])-
                  timedelta(minutes=1)).isoformat()
        cache=dict(official_day_source=dict(url='https://www.boatrace.jp/owpc/pc/race/index?hd=20300401',
            captured_at=captured,source_sha256='a'*64),verified_active_venues=['01'],
            official_race_registry=[dict(race_id='20300401-01-01',cutoff_at=cutoff,
                schedule_captured_at=captured)],candidate_source_waits=[wait],
            next_check_at=wait['retry_at'])
        document.update(cache)
        p1=json.loads(self.replies['actions/artifacts/123'])
        plain=packed({'national.json':json.dumps(document)})
        p1_raw,p1=encrypted(plain,p1,'P1')
        replies=deepcopy(self.replies)
        for raw,meta in [(p0_raw,p0_meta),(p1_raw,p1)]:
            replies[f'actions/artifacts/{meta["id"]}']=json.dumps(meta).encode()
            replies[f'actions/artifacts/{meta["id"]}/zip']=raw
        route='actions/runs/99/artifacts?per_page=100';listing=json.loads(replies[route])
        listing['artifacts']=[p1 if a['id']==123 else a for a in listing['artifacts']]+[p0_meta]
        listing['total_count']=len(listing['artifacts']);replies[route]=json.dumps(listing).encode()
        def get(route):
            if route.startswith('actions/workflows/') and '/runs?' in route:
                return json.dumps(dict(total_count=1,workflow_runs=[self.run_meta])).encode()
            return replies[route]
        before=deepcopy(replies)
        with tempfile.TemporaryDirectory() as folder:
            state=cycle_recovery.recover(get,DAY,current_run=100,out=Path(folder)/'replay',clock=lambda:NOW)
        self.assertEqual(state['schedule_cache'],cache)
        self.assertEqual(state['schedule_cache_receipt']['id'],123)
        self.assertFalse(repeated_cycle.usable_schedule(state['schedule_cache'],day=DAY,now=NOW))
        self.assertEqual(state['schedule_cache']['candidate_source_waits'][0]['retry_at'],wait['retry_at'])
        self.assertEqual(replies,before)

    def test_corrupt_checkpoint_and_orphan_cipher_fail_closed(self):
        for ident in (123,702):
            with self.subTest(artifact=ident):
                old=self.replies[f'actions/artifacts/{ident}/zip']
                self.replies[f'actions/artifacts/{ident}/zip']=old+b'corrupt'
                with self.assertRaises(ValueError):self.restore()
                self.replies[f'actions/artifacts/{ident}/zip']=old

    def test_duplicate_inventory_and_additional_pending_forecasts_are_not_discarded(self):
        route='actions/runs/99/artifacts?per_page=100';original=self.replies[route]
        for name in ('boat-national-cutoff-99-cycle-07','boat-all-model-forecasts-99-r7'):
            doc=json.loads(original);doc['artifacts'].append(dict(id=799,name=name));doc['total_count']+=1
            self.replies[route]=json.dumps(doc).encode()
            with self.subTest(name=name),self.assertRaises(ValueError):self.restore()
        self.replies[route]=original
