"""Synthetic bounded canary integration; no network, real forecasts or keys."""
from copy import deepcopy
from hashlib import sha256
from datetime import datetime
import importlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_cipher_history as archive
from scripts import keirin_official_day_pipeline as pipeline
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_official_run_history as history
from race_ai import keirin_nationwide_auto_settlement as settlement
from tests.test_keirin_nationwide_auto_generator import fixture
from tests.test_keirin_rider_form_evidence import pack


class OriginalReaderRegression(unittest.TestCase):
    def test_conditioned_siblings_do_not_hide_existing_baseline(self):
        race = '202611189801'
        day = '2026-11-18'
        sealed, receipt = archive._refs(race)
        conditioned, conditioned_receipt = archive._form_refs(race)
        raw = b'invented encrypted bytes'
        metadata = dict(cipher_sha256=sha256(raw).hexdigest(),
                        producer_run_id='123456', producer_commit='a'*40)
        listing = '\n'.join((sealed, receipt, conditioned, conditioned_receipt))
        with (patch.object(archive, '_remote', return_value=Path('/synthetic')),
             patch.object(archive, '_refresh', return_value='b'*40),
             patch.object(archive, '_cmd', return_value=(0, listing)),
             patch.object(archive, '_read_at', return_value=metadata),
             patch.object(archive, 'read_blob_bytes', side_effect=lambda repo, head, name, **kwargs:
                          json.dumps(metadata).encode() if name == receipt else raw)):
            result = pipeline.read_originals('/synthetic', day)
        self.assertEqual(set(result), {race})
        self.assertEqual(result[race]['raw_cipher'], raw)

    def test_canary_private_revisions_do_not_pollute_general_day_fold(self):
        packet = dict(schema='RACE_AI_KEIRIN_OFFICIAL_FORM_CANARY_PRE_CUTOFF_V1',
                      day_jst='2026-11-20', race_id='202611208105', safe_report={})
        with patch.object(history, 'decrypt_evidence', return_value=packet):
            state = pipeline.replay_day_evidence('2026-11-20', b'invented-key',
                [dict(raw_cipher=b'invented-authenticated-envelope', receipt={})])
        self.assertIsNone(state['schedule'])
        self.assertIsNone(state['safe_report'])
        self.assertEqual(state['official_records'], {})
        self.assertEqual(state['revision_receipts'], [])


class FrozenCanaryPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = cls.key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.pin = sha256(cls.key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def api(self):
        name = 'scripts.keirin_official_form_canary'
        self.assertIsNotNone(importlib.util.find_spec(name), 'FUTURE_CANARY_SCRIPT_REQUIRED')
        return importlib.import_module(name)

    def inputs(self):
        snap = fixture(6, girls=True)
        snap.update(race_id='202611208105', as_of='2026-11-20T13:00:00+09:00',
                    published_cutoff_at='2026-11-20T17:07:00+09:00')
        snap['cutoff_source']['captured_at'] = snap['as_of']
        for row in snap['source_pages']:
            row['captured_at'] = snap['as_of']
        supplement = pack()
        supplement['race_id'] = snap['race_id']
        supplement['condition_evidence']['as_of'] = snap['as_of']
        supplement['source_pages'][0]['captured_at'] = snap['as_of']
        return dict(snapshot=snap, supplement=supplement,
                    identity_proof={'synthetic_only': True}, availability={'synthetic_only': True})

    def test_four_arms_and_exact_sources_are_owner_encrypted_and_not_logged(self):
        api = self.api()
        raw = b'only synthetic official source'
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin):
            out = api.freeze_package(inputs=self.inputs(), card_manifest={'fixture': 'card'},
                history_manifest={'fixture': 'history'}, source_bytes_by_sha={sha256(raw).hexdigest():raw},
                private_root=Path(folder), public_pem=self.public,
                generated_at='2026-11-20T13:01:00+09:00', sealed_at='2026-11-20T13:01:01+09:00',
                producer_run_id='123456', producer_commit='a'*40)
            payload = pipeline.restore_private_snapshot_json(history.decrypt_evidence(
                out['evidence_cipher'], self.private))
            self.assertEqual(payload['source_bytes_by_sha'][sha256(raw).hexdigest()], raw)
            _, baseline, _ = settlement.decrypt_original_pair(raw_cipher=out['baseline_cipher'],
                expected_cipher_sha256=out['baseline_cipher_sha256'], owner_private_pem=self.private)
            self.assertEqual(payload['baseline'], baseline)
            conditioned = api.decrypt_conditioned(out['conditioned_cipher'],
                expected_sha256=out['conditioned_cipher_sha256'], owner_private_pem=self.private,
                baseline=baseline)
            self.assertEqual(conditioned['shadow'], payload['conditioned'])
            self.assertEqual(conditioned['supplement'], payload['supplement'])
            public = json.dumps(out['safe_report'])
            self.assertNotIn('ranked_tickets', public)
            self.assertNotIn('athlete_id', public)
            self.assertNotIn('only synthetic official source', public)
            self.assertEqual(out['safe_report']['new_A_B_sealed'], 1)
            self.assertFalse(out['safe_report']['server_origin_verified'])

    def test_different_target_cannot_use_scoped_canary(self):
        api = self.api()
        inputs = self.inputs()
        inputs['snapshot']['race_id'] = '202611208106'
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin):
            with self.assertRaisesRegex(ValueError, 'FIXED_CANARY_RACE_OR_CUTOFF_REQUIRED'):
                api.freeze_package(inputs=inputs, card_manifest={}, history_manifest={},
                    source_bytes_by_sha={}, private_root=Path(folder), public_pem=self.public,
                    generated_at='2026-11-20T13:01:00+09:00', sealed_at='2026-11-20T13:01:01+09:00',
                    producer_run_id='123456', producer_commit='a'*40)
            self.assertFalse(list(Path(folder).glob('*.sealed.json')))

    def test_runtime_rejects_non_main_and_does_not_enable_global_optin(self):
        api = self.api()
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
                   GITHUB_REPOSITORY_ID='1416489937', GITHUB_REF='refs/heads/untrusted',
                   GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_ID='123456', GITHUB_SHA='a'*40)
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaisesRegex(ValueError, 'MAIN_ONLY_CANARY_RUNTIME_REQUIRED'):
                api.check_runtime('capture', datetime.fromisoformat('2026-11-20T13:00:00+09:00'))
            import os
            self.assertNotIn('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED', os.environ)

    def test_real_crypto_server_proof_and_official_parser_reach_same_four_arm_scorer(self):
        from tests.test_keirin_form_canary_origin import fixture as origin_fixture, replace_report
        from race_ai import keirin_official_reviewed_pdf as unit_source
        api = self.api()
        inputs = self.inputs()
        source = b'invented pre-race source'
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin):
            package = api.freeze_package(inputs=inputs, card_manifest={}, history_manifest={},
                source_bytes_by_sha={sha256(source).hexdigest():source}, private_root=Path(folder),
                public_pem=self.public, generated_at='2026-11-20T13:01:00+09:00',
                sealed_at='2026-11-20T13:01:01+09:00', producer_run_id='123456', producer_commit='a'*40)
            producer, reader = origin_fixture()
            for packet, member in ((producer,'summary.json'), (reader,'keirin-git-independent.json')):
                with ZipFile(BytesIO(packet['archive_bytes'])) as z:
                    report = json.loads(z.read(member))
                row = report['new_encrypted_originals' if packet is producer else 'records'][0]
                row.update(cipher_sha256=package['baseline_cipher_sha256'],
                    conditioned_cipher_sha256=package['conditioned_cipher_sha256'],
                    baseline_prediction_sha256=package['payload']['baseline']['prediction_sha256'],
                    cohort_sha256=api.core.digest(api.COHORT))
                replace_report(packet, member, report)
                for section in ('run','job','artifact'):
                    for key, value in packet[section].items():
                        if isinstance(value, str) and value.startswith('2026-11-20T'):
                            packet[section][key] = value.replace('T00:', 'T03:').replace('T01:', 'T04:')
            producer['artifact']['created_at'] = '2026-11-20T04:01:10Z'
            producer['artifact']['updated_at'] = '2026-11-20T04:01:10Z'
            producer['job']['completed_at'] = '2026-11-20T04:01:15Z'
            starters = [dict(car=r['car'], registration_id=r['athlete_id']) for r in inputs['snapshot']['riders']]
            rows = [dict(syaban=str(r['car']), sensyuRegistNo=r['registration_id'],
                         tyaku=str(r['car']), kojinStateItemSubData=[]) for r in starters]
            head = dict(txtEventDate='2026/11/20', selRaceNo=5, aftBetDate='202611201707',
                        flgRaceCancel=False, flgKekkaRefund=False)
            final = dict(resultCd=0, tyakujyunDispFlg=True, haraiGakuDispFlg=True, bikouDispFlg=False,
                lastUpdateTime='2026/11/20 17:11&nbsp;更新',
                digestUrl='https://wm.st.keirin.jp/wm-keirin81/20261120-81-02-05-01-00.mp4',
                tyakujyunItemSubData=rows,
                haraiGakuSubData=dict(APartReturnDispFlg=False, RT3HaraiGakuDispItemSubData=[
                    dict(kumiBan='1-2-3', haraiGaku='1,230', kumiDispFlg=True)]))
            raw = ('<html><body><script>var jsonData = {};jsonData["SC0201"] = '+
                json.dumps(dict(resultCd=0,C0201data=head))+';jsonData["SJ0326"] = '+json.dumps(final)+
                ';</script></body></html>').encode()
            url = 'https://www.hofukeirin.jp/ticket/'
            guide = unit_source.UNIT_URLS[url].encode()
            guide_sha = sha256(guide).hexdigest()
            capture = dict(raw_result=raw, observed_at='2026-11-20T17:12:00+09:00',
                expected_reference=dict(source_url='https://keirin.jp/sp/race', method='POST',disp='SJ0326',
                    token='D'*43, official_cutoff_at=api.CUTOFF,starters=starters),
                unit_evidence=dict(url=url, source_sha256=guide_sha,observed_at='2026-11-20T17:10:00+09:00',
                    verified_payout_basis_yen=100,exact_excerpt=unit_source.UNIT_URLS[url]),
                source_bytes_by_sha={guide_sha:guide,sha256(raw).hexdigest():raw})
            # Source joining is exercised independently with raw grammar fixtures;
            # this test crosses real encryption, both server proofs and final parser.
            with patch.object(api.join, 'build_inputs', return_value=inputs):
                out = api.compare_frozen(payload=package['payload'], raw_baseline=package['baseline_cipher'],
                    raw_conditioned=package['conditioned_cipher'], owner_private_pem=self.private,
                    packets=dict(producer=producer,readback=reader),final_capture=capture)
                self.assertEqual(out['comparison']['paired_comparable_races'],1)
                self.assertEqual(out['comparison']['metrics']['A']['original']['stake_yen'],1200)
                self.assertEqual(out['comparison']['metrics']['A']['conditioned']['stake_yen'],1200)
                self.assertTrue(out['official_result']['monetary_comparison_eligible'])
                altered_inputs = deepcopy(inputs)
                altered_inputs['snapshot']['riders'][0]['h_count'] += 1
                altered_payload = dict(package['payload'], snapshot=altered_inputs['snapshot'])
                with patch.object(api.join,'build_inputs',return_value=altered_inputs):
                    with self.assertRaisesRegex(ValueError,'AUTHENTICATED_ORIGINALS_DIFFER_FROM_BUNDLE'):
                        api.compare_frozen(payload=altered_payload, raw_baseline=package['baseline_cipher'],
                            raw_conditioned=package['conditioned_cipher'], owner_private_pem=self.private,
                            packets=dict(producer=producer,readback=reader),final_capture=capture)
                replaced = deepcopy(capture)
                replaced['expected_reference']['starters'][0]['registration_id']='999999'
                replaced['raw_result']=raw.replace(b'"sensyuRegistNo": "015001"',b'"sensyuRegistNo": "999999"')
                with self.assertRaisesRegex(ValueError,'REGISTERED_ROSTER_COMPARISON_UNVERIFIED'):
                    api.compare_frozen(payload=package['payload'], raw_baseline=package['baseline_cipher'],
                        raw_conditioned=package['conditioned_cipher'], owner_private_pem=self.private,
                        packets=dict(producer=producer,readback=reader),final_capture=replaced)
                safe=api._report('REAL_FUTURE_CANARY_FOUR_ARMS_COMPARISON_COMPLETE')
                safe.update(paired_comparable_races=1,nationwide_expansion_gate_passed=True)
                saved=dict(schema=api.SETTLEMENT_SCHEMA,day_jst=api.DAY,race_id=api.RACE,
                    pre_cutoff_evidence_plaintext_sha256='f'*64,
                    baseline_cipher_sha256=package['baseline_cipher_sha256'],
                    conditioned_cipher_sha256=package['conditioned_cipher_sha256'],
                    producer_run_id='123456',producer_commit='a'*40,settler_run_id='123457',settler_commit='b'*40,
                    origin_packets=dict(producer=producer,readback=reader),final_capture=capture,**out,safe_report=safe)
                saved_cipher=history.seal_evidence(pipeline.private_snapshot_json(saved),self.public,api.DAY,
                                                  '2026-11-20T17:20:00+09:00')
                saved_plain=pipeline.restore_private_snapshot_json(history.decrypt_evidence(saved_cipher,self.private))
                record=dict(producer_run_id='123457',cipher_sha256=sha256(saved_cipher).hexdigest())
                public_path=Path(folder)/'public.pem'
                public_path.write_bytes(self.public)
                env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
                    GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='schedule',GITHUB_RUN_ID='123458',
                    GITHUB_SHA='c'*40,RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true')
                with (patch.dict('os.environ',env,clear=True),
                      patch.object(api,'_load_original_bundle',return_value=(package['payload'],
                        {'evidence_plaintext_sha256':'f'*64},[(saved_plain,record)])),
                      patch.object(api,'_archived_pair',return_value=(package['baseline_cipher'],package['conditioned_cipher'],{})),
                      patch.object(api,'collect_final_result',side_effect=AssertionError('must not fetch again')) as fetch,
                      patch.object(api.history,'append_revision',side_effect=AssertionError('must not append again')) as append):
                    reused=api.run_settle(repo='/synthetic',private_root=Path(folder)/'resume',
                        owner_public_pem=public_path,owner_private_pem=self.private,
                        clock=lambda:datetime.fromisoformat('2026-11-20T17:30:00+09:00'))
                    self.assertEqual(reused['state'],'EXISTING_VERIFIED_CANARY_COMPARISON_REUSED')
                    self.assertEqual(reused['paired_comparable_races'],1)
                    fetch.assert_not_called();append.assert_not_called()
                reader['job']['completed_at']='2026-11-20T08:05:56Z'
                with self.assertRaises(ValueError):
                    api.compare_frozen(payload=package['payload'], raw_baseline=package['baseline_cipher'],
                        raw_conditioned=package['conditioned_cipher'], owner_private_pem=self.private,
                        packets=dict(producer=producer,readback=reader),final_capture=capture)

    def test_denial_is_persisted_but_timeout_or_server_error_is_not_relabelled_denial(self):
        api = self.api()
        clock = lambda:datetime.fromisoformat('2026-11-20T13:00:00+09:00')
        with patch.object(api.provider_stop,'record_denial') as save:
            for code in (None, 200, 500, 503):
                api._persist_denial('/synthetic',clock,status=code)
            save.assert_not_called()
            with self.assertRaisesRegex(ValueError,'DENIED_PERSISTED_NO_RETRY'):
                api._persist_denial('/synthetic',clock,status=403)
            save.assert_called_once()
        with patch.object(api.provider_stop,'read_for_observed_day',return_value={'code':'DENIED'}):
            with self.assertRaisesRegex(ValueError,'PERSISTENT_PROVIDER_STOP'):
                api._provider_preflight('/synthetic')

    def test_final_public_form_follows_current_result_reference_and_guide_first(self):
        from urllib.parse import urlsplit
        from tests.test_keirin_official_schedule import page,venue,meeting
        from tests.test_keirin_official_sp_receipt import header,html
        api=self.api()
        def link(raw, paths):
            return raw.replace(b'</body>', ''.join('<script src="'+p+'"></script>' for p in paths).encode()+b'</body>')
        calendar=link(page([venue(81,[meeting('2026-11-18','2026-11-23')])],year='2026',month='11'),
            ['/sp/static/js/SJ0201.js','/sp/static/js/commonSubmit.js'])
        rows=[dict(strRaceNo=str(n),strSyumokuName='架空区分',strArrow='',strArrowName='',
            strRaceLnk='/sp/race',strRaceLnkPrm=chr(64+n)*43,strRaceLnkKbn='2',strColorClass='') for n in range(1,6)]
        listing=dict(SC0201=dict(resultCd=0,C0201data=header('2026/11/20')),
            SJ0301=dict(resultCd=0,kaisaiDayList=[dict(strKaisaiNitijName='3日目(11/20)',raceProgramList=rows)]))
        responses={
            '/sp/raceschedule':calendar,
            '/sp/static/js/SJ0201.js':b'params["encp"]=encp;params["disp"]="SJ0301";commonSubmit.formPost(next,params,null);',
            '/sp/static/js/commonSubmit.js':b'$form.attr("method","post");',
            '/sp/static/js/SJ0301_v.js':b'raceProgram.strRaceLnk;raceProgram.strRaceLnkPrm;raceProgram.strRaceLnkKbn;',
            '/sp/static/js/SJ0301_c.js':b'var action=$(children[1]).attr("value");params["encp"]=$(children[2]).attr("value");if(dispDI==2){dispDI="SJ0326";}commonSubmit.formPost(action,params);',
            '/sp/race':b'<html><body>invented final document bytes</body></html>',
            '/ticket/':api.payout_unit.UNIT_URLS['https://www.hofukeirin.jp/ticket/'].encode(),
        }
        for available in (True,False):
            with (self.subTest(available=available),tempfile.TemporaryDirectory() as folder,
                  patch.object(api,'_provider_preflight')):
                rows[4]['strRaceLnkKbn']='2' if available else '1'
                responses['/sp/racelist']=link(html(listing),['/sp/static/js/SJ0301_c.js','/sp/static/js/SJ0301_v.js'])
                calls=[]
                now=datetime.fromisoformat('2026-11-20T17:12:00+09:00')
                def request(url,fields=None,referer=None):
                    calls.append((url,fields))
                    return dict(url=url,status=200,raw=responses[urlsplit(url).path],observed_at=now)
                frozen=dict(race_id=api.RACE,official_cutoff_at=api.CUTOFF,
                    riders=[dict(car=n,registration_id=f'{15000+n:06d}') for n in range(1,7)])
                if available:
                    out=api.collect_final_result(repo='/synthetic',private_root=folder,
                        frozen_card=frozen,clock=lambda:now,request=request)
                    self.assertEqual(out['expected_reference']['token'],'E'*43)
                    self.assertEqual(calls[-2][0],'https://www.hofukeirin.jp/ticket/')
                    self.assertEqual(calls[-1],('https://keirin.jp/sp/race',[('encp','E'*43),('disp','SJ0326')]))
                    self.assertEqual(len(calls),8)
                else:
                    with self.assertRaisesRegex(ValueError,'RESULT_NOT_PUBLISHED_YET'):
                        api.collect_final_result(repo='/synthetic',private_root=folder,
                            frozen_card=frozen,clock=lambda:now,request=request)
                    self.assertEqual(len(calls),6)


if __name__ == '__main__':
    unittest.main()
