"""Invented recovery/scoring bindings; no owner key or actual result is read."""
import base64
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import keirin_joint_original_readback as reader
from scripts import keirin_joint_forward_score as scorer
from tests.test_keirin_joint_original_readback import invented_note, canonical

NOW = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)
CREATED = '2026-11-25T12:01:00+00:00'
WITNESSED = '2026-11-25T12:03:00+00:00'


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


class JointRecoveryScoreTests(unittest.TestCase):
    def setUp(self):
        self.note,_=invented_note()
        self.note_raw=canonical(self.note)
        self.note_sha=sha256(self.note_raw).hexdigest()
        self.cipher=b'Invented RSA envelope, decoded only by a test double.'
        self.cipher_sha=sha256(self.cipher).hexdigest()
        self.private=b'PRIVATE PEM CANARY never print this value'
        inputs=json.loads(self.note['files']['data/2026-11-25/comparison_inputs.json']['text'])['races']
        self.ids=[row['race_id'] for row in inputs]
        self.publication=dict(schema='KEIRIN_JOINT_COMPARISON_FREEZE_RECEIPT_V1',
            generated_at=self.note['imported_at'],original_snapshot_created_at=CREATED,
            original_note_sha256=self.note_sha,git_readback_at='2026-11-25T12:02:00+00:00',
            cipher_sha256='c'*64,races=len(inputs),race_ids=self.ids,
            cutoffs={row['race_id']:row['cutoff_at'] for row in inputs},
            pre_cutoff_git_readback=True,private_plaintext_uploaded=False,production_weights_promoted=False,
            publication=dict(source_commit='d'*40,state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED'))
        self.witness=dict(state='INDEPENDENT_RUNNER_CIPHER_SHA_READBACK_VERIFIED',
            archive_commit='d'*40,cipher_sha256='c'*64,observed_at=WITNESSED,
            action_run=101,job_id=202,registered_comparison_races=2,still_pre_cutoff_races=2,
            plaintext_decrypted=False,private_key_used=False,formal_pre_cutoff_original_authenticated=False)
        stem='state/keirin/research/joint-comparison/v1/2026-11-25/'+self.cipher_sha
        self.receipt=dict(schema='KEIRIN_JOINT_ORIGINAL_RECOVERY_RECEIPT_V1',
            recovery_cipher_sha256=self.cipher_sha,recovery_cipher_bytes=len(self.cipher),
            original_note_sha256=self.note_sha,original_cipher_sha256='c'*64,
            original_archive_commit='d'*40,expected_original_created_at=CREATED,
            expected_original_git_readback_at=WITNESSED,original_witness_run=101,original_witness_job=202,
            recovery_archive_commit='e'*40,recovery_archive_path=stem+'.sealed.json',
            copy_is_new_pre_cutoff_forecast=False,encryption_format_only_not_official_result=True,
            formal_PR71_admission=False,private_plaintext_uploaded=False,original_cipher_rewritten=False)
        self.payload=dict(schema=reader.SCHEMA,day_jst='2026-11-25',original_note_sha256=self.note_sha,
            original_cipher_sha256='c'*64,original_archive_commit='d'*40,
            original_note_b64=base64.b64encode(self.note_raw).decode(),safe_report=dict(
                day_jst='2026-11-25',original_created_at=CREATED,original_git_readback_at=WITNESSED,
                earliest_cutoff=inputs[0]['cutoff_at'],original_header=dict(
                    schema='RACE_AI_SAVED_WEB_VIEW_V1',source_content_sha256=self.note_sha)))
        self.readback=dict(schema='KEIRIN_JOINT_ORIGINAL_READBACK_V1',
            state='INDEPENDENT_RESEARCH_ORIGINAL_PLAINTEXT_READBACK_VERIFIED',
            original_note_sha256=self.note_sha,original_cipher_sha256='c'*64,original_archive_commit='d'*40,
            recovery_cipher_sha256=self.cipher_sha,original_created_at=CREATED,
            original_git_readback_at=WITNESSED,readback_at=NOW.isoformat(),paired_races=2,
            full_forecast_records_verified=4,all_originals_before_earliest_cutoff=True,
            independent_research_plaintext_readback=True,actual_organizer_cutoff_authenticated=False,
            formal_PR71=False,production_weights_promoted=False)
        self.roster=dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1',date='2026-11-25',
            generated_at='2026-11-25T11:00:00+00:00',forecast_asset_sha256='f'*64,races=[dict(
                race_id=row['race_id'],date='2026-11-25',venue='玉野',race_no=int(row['race_id'][-2:]),
                published_cutoff_at=row['cutoff_at'],source_url=row['source']['source_url'],
                observed_riders=[dict(number=p['car']) for p in row['roster']]) for row in inputs])
        self.results=dict(schema='KEIRIN_PUBLISHED_RESULTS_V1',date='2026-11-25',checked_at=NOW.isoformat(),
            races=[dict(race_id=rid,state='pending',reason='invented_unpublished_result') for rid in self.ids])

    def module(self):
        try:
            return importlib.import_module('scripts.keirin_joint_recovery_score')
        except ModuleNotFoundError:
            self.fail('The recovery-to-existing-joint-score adapter is not implemented.')

    def call(self,module=None):
        return (module or self.module()).score_recovery(self.cipher,self.private,canonical(self.receipt),
            canonical(self.publication),canonical(self.witness),canonical(self.roster),canonical(self.results),clock=lambda:NOW)

    def mocked(self):
        stack=ExitStack()
        stack.enter_context(patch.object(reader,'verify_recovery',return_value=self.readback))
        stack.enter_context(patch.object(reader.history,'decrypt_evidence',return_value=self.payload))
        return stack

    def test_verified_recovery_returns_safe_existing_aggregates_and_pending_outcomes(self):
        with self.mocked():
            report=self.call()
        self.assertEqual((report['registered'],report['matched'],report['published_hits'],report['trial_hits']),(2,0,0,0))
        self.assertEqual(report['result_states'],dict(pending=2))
        self.assertEqual(report['original_plaintext_authentication'],'INDEPENDENT_RSA_READBACK_VERIFIED')
        self.assertEqual(report['rsa_readback_report_sha256'],sha256(canonical(self.readback)).hexdigest())
        self.assertEqual(report['rsa_readback_source']['cipher_sha256'],self.cipher_sha)
        self.assertEqual(report['flow_state'],'NO_PRE_CUTOFF_FLOW_ORIGINAL')
        self.assertIs(report['formalPR71'],False)
        self.assertIs(report['accuracy_improvement_proven'],False)
        rendered=json.dumps(report)
        for private in ('Invented person','original_note_b64','rank_probabilities','trifectas','raw_path',self.private.decode()):
            self.assertNotIn(private,rendered)

    def test_wrong_cipher_is_refused_before_reader_or_decrypt(self):
        self.module()
        self.cipher+=b' changed'
        with patch.object(reader,'verify_recovery') as verify,patch.object(reader.history,'decrypt_evidence') as decrypt:
            with self.assertRaisesRegex(ValueError,'CIPHER_SHA'):
                self.call()
        verify.assert_not_called()
        decrypt.assert_not_called()

    def test_second_decrypt_note_hash_is_checked_before_any_score(self):
        self.module()
        self.payload['original_note_b64']=base64.b64encode(self.note_raw+b' changed').decode()
        with self.mocked(),patch.object(scorer,'score_joint') as score:
            with self.assertRaisesRegex(ValueError,'NOTE_SHA'):
                self.call()
        score.assert_not_called()

    def test_wrong_job_or_witness_clock_cannot_reuse_original_authority(self):
        self.module()
        for field,value in [('original_witness_job',999),('expected_original_git_readback_at','2026-11-25T12:04:00+00:00')]:
            before=deepcopy(self.receipt)
            self.receipt[field]=value
            with patch.object(reader,'verify_recovery') as verify:
                with self.assertRaisesRegex(ValueError,'ORIGIN_'):
                    self.call()
                verify.assert_not_called()
            self.receipt=before

    def test_reader_failure_never_reaches_second_decrypt_or_score(self):
        self.module()
        with patch.object(reader,'verify_recovery',side_effect=ValueError(self.private.decode())), \
                patch.object(reader.history,'decrypt_evidence') as decrypt,patch.object(scorer,'score_joint') as score:
            with self.assertRaisesRegex(ValueError,'VERIFY_FAILED'):
                self.call()
        decrypt.assert_not_called()
        score.assert_not_called()

    def test_incomplete_safe_readback_cannot_promote_plaintext_authentication(self):
        self.module()
        for field,value in [('state','UNVERIFIED'),('original_note_sha256','a'*64),('paired_races',1)]:
            before=deepcopy(self.readback)
            self.readback[field]=value
            with self.mocked(),self.assertRaisesRegex(ValueError,'READBACK_'):
                self.call()
            self.readback=before

    def test_changed_guarded_source_is_refused_before_reading_private_payload(self):
        module=self.module()
        changed=dict(module.SOURCE_SHA256)
        changed['scripts/keirin_joint_original_readback.py']='0'*64
        with patch.object(module,'SOURCE_SHA256',changed),patch.object(reader,'verify_recovery') as verify:
            with self.assertRaisesRegex(ValueError,'SOURCE_SHA'):
                self.call(module)
        verify.assert_not_called()

    def test_existing_full_reader_is_used_before_existing_scorer_with_no_actual_key(self):
        self.module()
        with patch.object(reader.history,'decrypt_evidence',return_value=self.payload),patch.object(reader,'datetime',FixedDatetime):
            report=self.call()
        self.assertEqual(report['original_plaintext_authentication'],'INDEPENDENT_RSA_READBACK_VERIFIED')
        self.assertEqual(report['registered'],2)

    def test_cli_pops_secret_before_guards_and_never_prints_private_exception_text(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={'cipher':self.cipher,'receipt':canonical(self.receipt),'publication':canonical(self.publication),
                'witness':canonical(self.witness),'roster':canonical(self.roster),'results':canonical(self.results)}
            argv=[]
            for name,raw in files.items():
                target=root/(name+'.json');target.write_bytes(raw);argv.extend(['--'+name,str(target)])
            output,error=StringIO(),StringIO()
            original=module._guard_sources
            def guard():
                self.assertNotIn(module.KEY_ENV,os.environ)
                return original()
            with patch.dict(os.environ,{module.KEY_ENV:self.private.decode()}),patch.object(module,'_guard_sources',side_effect=guard), \
                    patch.object(reader,'verify_recovery',side_effect=ValueError(self.private.decode())),redirect_stdout(output),redirect_stderr(error):
                code=module.main(argv)
                self.assertNotIn(module.KEY_ENV,os.environ)
            self.assertEqual(code,2)
            self.assertNotIn(self.private.decode(),output.getvalue()+error.getvalue())
            self.assertNotIn('Traceback',output.getvalue()+error.getvalue())
            self.assertIs(json.loads(output.getvalue())['formalPR71'],False)

    def test_invalid_cli_arguments_are_fixed_codes_after_secret_removal(self):
        module=self.module();output,error=StringIO(),StringIO()
        with patch.dict(os.environ,{module.KEY_ENV:self.private.decode()}),redirect_stdout(output),redirect_stderr(error):
            code=module.main(['--unknown',self.private.decode()])
            self.assertNotIn(module.KEY_ENV,os.environ)
        self.assertEqual(code,2)
        self.assertNotIn(self.private.decode(),output.getvalue()+error.getvalue())
        self.assertNotIn('Traceback',output.getvalue()+error.getvalue())

    def test_malformed_secret_encoding_is_a_safe_hold_after_environment_removal(self):
        module=self.module();output,error=StringIO(),StringIO()
        with patch.dict(os.environ,{module.KEY_ENV:'PRIVATE-CANARY-\udcff'}),redirect_stdout(output),redirect_stderr(error):
            code=module.main([])
            self.assertNotIn(module.KEY_ENV,os.environ)
        self.assertEqual(code,2)
        self.assertNotIn('PRIVATE-CANARY',output.getvalue()+error.getvalue())
        self.assertNotIn('Traceback',output.getvalue()+error.getvalue())


if __name__=='__main__':
    unittest.main()
