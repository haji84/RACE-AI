"""Synthetic dossiers, clocks and a decrypt double. No owner key is needed."""
import base64
from contextlib import redirect_stdout
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import importlib
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

DAY = '2099-01-03'
START, END = '2098-01-01', '2099-01-02'
AT = '2099-01-03T01:00:00Z'
NOW = datetime(2099, 1, 3, 2, tzinfo=timezone.utc)
NATIONAL, REGISTRY = 'national-dossiers.json', 'official-current-registry.json'
def raw(doc):
    return json.dumps(doc, sort_keys=True).encode()
def digest(b):
    return sha256(b).hexdigest()

class DossierRecoveryTests(unittest.TestCase):
    def setUp(self):
        name = 'scripts.keirin_rider_dossier_readback'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Standalone recovery CLI missing')
        self.mod = importlib.import_module(name)
        self.cipher = raw({'day_jst': DAY, 'observed_at': AT, 'fixture': True})
        base = {'registration':'012345','name':'PRIVATE_NAME_CANARY','captured_at':AT}
        self.reg = {'schema':'KEIRIN_OFFICIAL_CURRENT_REGISTRY_V1',
                    'scope':'NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT',
                    'complete':True,'retrieval_started_at':AT,'retrieval_completed_at':AT,'riders':[base]}
        self.doc = {'schema':'KEIRIN_BASIC_RIDER_DOSSIERS_V1','scope':'RETROSPECTIVE_CURRENT_REGISTRY_IDENTITY_RECONCILIATION',
                    'as_of_exclusive':DAY,'generated_at':AT,'identity_knowledge_as_of':AT,
                    'historical_as_of_authenticated':False,'registry_captured_after_history_cutoff':True,
                    'source_download_started_at':AT,'source_download_completed_at':AT,
                    'archive_sources':[{'included_start_day':START,'included_end_day':END}],
                    'dossiers':[{'registration':base['registration'],'name':base['name'],
                                 'finish_history':{'registration':base['registration'],'as_of_exclusive':DAY,
                                   'periods':{'all':{'observed_count':1,'missing_finish_count':None,
                                     'first_observed_day':START,'latest_observed_day':END,
                                     'finish_counts':{str(i):int(i==1) for i in range(1,10)}}}}}]}
        self.metrics={'day_jst':DAY,'registered_riders':1,'riders_with_numeric_history':1,'numeric_finish_records':1,
                      'history_start_day':START,'history_end_day':END}
        self.prepare()

    def prepare(self):
        self.doc['registry_sha256']=digest(raw(self.reg))
        self.originals={NATIONAL:raw(self.doc), REGISTRY:raw(self.reg)}
        pins={key:{'bytes':len(b),'sha256':digest(b)} for key,b in self.originals.items()}
        self.receipt={'schema':'KEIRIN_RIDER_DOSSIER_RECOVERY_RECEIPT_V1',**self.metrics,
                      'recovery_cipher_sha256':digest(self.cipher),'recovery_cipher_bytes':len(self.cipher),'files':pins}
        self.payload={'schema':'KEIRIN_RIDER_DOSSIER_RECOVERY_V1','day_jst':DAY,'safe_report':dict(self.metrics),
                      'files':{key:{**pin,'gzip_base64':base64.b64encode(gzip.compress(self.originals[key])).decode()}
                               for key,pin in pins.items()}}

    def verify(self, output=None):
        with patch.object(self.mod.history,'decrypt_evidence',return_value=self.payload):
            return self.mod.verify_recovery(self.cipher,b'FAKE_KEY',self.receipt,output_dir=output,now=NOW)

    def test_external_counts_hashes_and_secret_free_output(self):
        report=self.verify()
        self.assertEqual(report['numeric_finish_records'],1)
        self.assertFalse(report['files_restored'])
        for key in ('forecast_original_authenticated','official_results_verified','accuracy_improvement_proven','historical_as_of_authenticated'):
            self.assertIs(report[key],False)
        for secret in ('PRIVATE_NAME_CANARY','012345','FAKE_KEY','gzip_base64'):
            self.assertNotIn(secret,json.dumps(report))

    def test_wrong_cipher_and_files_rejected_before_restoring(self):
        self.receipt['recovery_cipher_bytes']+=1
        with self.assertRaises(ValueError):self.verify()
        self.prepare()
        self.payload['files'][REGISTRY]['bytes']+=1
        with self.assertRaises(ValueError):self.verify()
        self.prepare()
        self.receipt['files'][NATIONAL]['sha256']='a'*64
        with self.assertRaises(ValueError):self.verify()

    def test_declared_counts_periods_and_source_clocks_are_checked(self):
        self.doc['dossiers'][0]['finish_history']['periods']['all']['observed_count']=2
        self.prepare()
        with self.assertRaises(ValueError):self.verify()
        self.doc['dossiers'][0]['finish_history']['periods']['all']['observed_count']=1
        self.doc['generated_at']='2099-01-04T00:00:00Z'
        self.prepare()
        with self.assertRaises(ValueError):self.verify()
        self.doc['generated_at']=AT
        self.doc['historical_as_of_authenticated']=True
        self.prepare()
        with self.assertRaises(ValueError):self.verify()

    def test_previously_captured_registry_page_can_be_reused_on_resume(self):
        self.reg['riders'][0]['captured_at']='2099-01-03T00:20:00Z'
        self.prepare()
        self.assertEqual(self.verify()['registered_riders'],1)

    def test_duplicated_registrations_and_dossier_identity_mismatch(self):
        self.reg['riders']*=2
        self.prepare()
        with self.assertRaises(ValueError):self.verify()
        self.reg['riders'].pop()
        self.doc['dossiers'][0]['registration']='111111'
        self.prepare()
        with self.assertRaises(ValueError):self.verify()

    def test_extra_members_padding_truncation_and_decompression_bound(self):
        item=self.payload['files'][NATIONAL]
        compressed=base64.b64decode(item['gzip_base64'])
        for bad in (compressed+b'\0',compressed+gzip.compress(b'next'),compressed[:-2]):
            item['gzip_base64']=base64.b64encode(bad).decode()
            with self.assertRaises(ValueError):self.verify()
        self.prepare()
        with patch.object(self.mod,'MAX_EXPANDED',64),self.assertRaises(ValueError):self.verify()
        with patch.object(self.mod,'MAX_COMPRESSED',8),self.assertRaises(ValueError):self.verify()

    def test_decompression_cannot_exceed_declared_expanded_size(self):
        entry = self.payload['files'][NATIONAL]
        oversized = self.originals[NATIONAL] + bytes(1024 * 1024)
        entry['gzip_base64'] = base64.b64encode(gzip.compress(oversized)).decode()
        with self.assertRaisesRegex(self.mod.DossierHold, '^DOSSIER_FILE_BYTES_MISMATCH$'):
            self.verify()

    def test_restore_is_private_and_refuses_to_overwrite_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'output'
            report=self.verify(root)
            self.assertTrue(report['files_restored'])
            for name,content in self.originals.items():
                self.assertEqual((root/name).read_bytes(),content)
                self.assertEqual((root/name).stat().st_mode & 0o777,0o600)
            (root/NATIONAL).unlink()
            with self.assertRaises(ValueError):self.verify(root)
            self.assertFalse((root/NATIONAL).exists())
            parent=Path(temp)/'alias';parent.symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):self.verify(parent/'child')
            self.assertFalse((root/'child').exists())

    def test_output_under_checkout_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp)
            (checkout / '.git').mkdir()
            destination = checkout / 'private-data'
            with self.assertRaises(self.mod.DossierHold):
                self.verify(destination)
            self.assertFalse(destination.exists())

    def test_cli_removes_secret_uses_fixed_failure_and_avoids_private_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'receipt').write_bytes(raw(self.receipt));(root/'cipher').write_bytes(self.cipher)
            out=StringIO()
            def fail(*_):
                self.assertNotIn(self.mod.KEY_ENV,os.environ)
                raise ValueError('PRIVATE_NAME_CANARY_FAKE_KEY')
            with patch.dict(os.environ,{self.mod.KEY_ENV:'FAKE_KEY'}),patch.object(self.mod.history,'decrypt_evidence',side_effect=fail),redirect_stdout(out):
                self.assertNotEqual(self.mod.main(['--cipher',str(root/'cipher'),'--receipt',str(root/'receipt')]),0)
            self.assertNotIn('CANARY',out.getvalue());self.assertNotIn('FAKE_KEY',out.getvalue())
