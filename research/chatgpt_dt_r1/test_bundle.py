"""Synthetic full preservation/restore and public-boundary tests, no live proof."""
import copy
import base64
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from research.chatgpt_dt_r1 import bundle
from research.chatgpt_dt_r1.calibration import fit_calibrator, audit_calibrator, assess_selection
from research.chatgpt_dt_r1.features import FEATURE_NAMES
from research.chatgpt_dt_r1.model import RankModel, digest
from research.chatgpt_dt_r1.pipeline import DEFAULT_SPLITS, freeze_evaluation_contract, write_private_json
from research.chatgpt_dt_r1.policy import fixed_selection
from research.chatgpt_dt_r1.test_calibration_policy_comparison import forecast, SPLITS


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai import keirin_official_run_history as codec
        cls.codec = codec
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.secret = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner_pin = patch.object(self.codec.storage, 'PINNED_OWNER_SPKI_SHA256', self.pin)
        self.owner_pin.start(); self.addCleanup(self.owner_pin.stop)
        self.study = self.root / 'study'
        self.model = RankModel.zero(FEATURE_NAMES).to_dict()
        source = {'dataset_sha256': 'a' * 64, 'unique_races': 1, 'sources': [],
                  'private_marker': 'PRIVATE_SOURCE_DO_NOT_PUBLISH'}
        contract = freeze_evaluation_contract(self.study, DEFAULT_SPLITS, source)
        f = forecast('PRIVATE_FORECAST_DO_NOT_PUBLISH')
        f['model_sha256'] = self.model['model_sha256']
        selection = fixed_selection(f, 1)
        lineage = {key: selection[key] for key in ('model_id', 'model_sha256', 'policy_sha256')}
        def rows(month):
            return [dict(selection, race_id=f'PRIVATE_CALIBRATION_{month}_{i}', day=f'2026-{month}-{10+i:02}', hit=i % 2)
                    for i in range(4)]
        self.calibrator = audit_calibrator(fit_calibrator(rows('08'), split_manifest=SPLITS, lineage=lineage,
            config={'min_calibration_n': 1, 'min_audit_n': 1, 'min_audit_days': 1}), rows('09'))
        report = {'schema': 'dt-r1-real-archive-study-v1', 'production_promoted': False,
                  'source_audit': source, 'evaluation_contract': contract, 'model_sha256': self.model['model_sha256'],
                  'selected_candidate': 'full_with_pairs', 'feature_count': len(FEATURE_NAMES),
                  'final_period': {'registered': 1, 'evaluable': 1, 'predicted_evaluable': 1},
                  'private_extra': 'PRIVATE_REPORT_DO_NOT_PUBLISH'}
        docs = {'frozen_model.json': self.model, 'aggregate_report.json': report,
                'trifecta_1.calibration.json': self.calibrator,
                'selection_receipt.json': {'model_sha256': self.model['model_sha256'], 'selected': 'full_with_pairs',
                                            'test_results_consulted': False},
                'pre_test_freeze.json': {'model_sha256': self.model['model_sha256'],
                    'contract_sha256': contract['contract_sha256'], 'calibration_sha256': {'trifecta_1': digest(self.calibrator)}},
                'test_forecasts.private.json': [f],
                'test_registry.private.json': [{'race_id': f['race_id']}],
                'test_outcomes.private.json': [{'race_id': f['race_id'], 'top3': [1, 2, 3]}]}
        for name, value in docs.items(): write_private_json(self.study / name, value)

    def export(self, name='public'):
        dest = self.root / name
        receipt = bundle.export_study(self.study, dest, self.public, now='2026-11-27T18:00:00Z', chunk_bytes=1024)
        return dest, receipt

    def test_complete_encrypted_roundtrip_preserves_calibrator_and_original_bytes(self):
        dest, receipt = self.export()
        self.assertGreater(receipt['shards'], 1)
        for path in dest.iterdir():
            self.assertNotIn(b'PRIVATE_', path.read_bytes())
        restored = self.root / 'restored'
        result = bundle.restore_study(dest, restored, expected_manifest_sha256=receipt['manifest_sha256'], owner_private_pem=self.secret)
        self.assertFalse(result['production_promoted'])
        for path in self.study.iterdir():
            self.assertEqual(path.read_bytes(), (restored / path.name).read_bytes())
            self.assertEqual((restored / path.name).stat().st_mode & 0o777, 0o600)
        f = json.loads((restored / 'test_forecasts.private.json').read_text())[0]
        recovered = json.loads((restored / 'trifecta_1.calibration.json').read_text())
        self.assertEqual(assess_selection(fixed_selection(f, 1), recovered), assess_selection(fixed_selection(f, 1), self.calibrator))

    def test_external_pin_tamper_missing_shard_and_existing_destination_stop(self):
        dest, receipt = self.export()
        restored = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'MANIFEST_SHA'):
            bundle.restore_study(dest, restored, expected_manifest_sha256='0' * 64, owner_private_pem=self.secret)
        self.assertFalse(restored.exists())
        manifest = bundle.verify_bundle(dest, expected_manifest_sha256=receipt['manifest_sha256'])
        shard = dest / manifest['shards'][0]['file']; original = shard.read_bytes()
        shard.write_bytes(original[:-1] + b'X')
        with self.assertRaisesRegex(ValueError, 'SHARD_SHA'):
            bundle.restore_study(dest, restored, expected_manifest_sha256=receipt['manifest_sha256'], owner_private_pem=self.secret)
        self.assertFalse(restored.exists()); shard.write_bytes(original)
        restored.mkdir(); sentinel = restored / 'keep'; sentinel.write_text('original')
        with self.assertRaisesRegex(ValueError, 'NO_RESET'):
            bundle.restore_study(dest, restored, expected_manifest_sha256=receipt['manifest_sha256'], owner_private_pem=self.secret)
        self.assertEqual(sentinel.read_text(), 'original')
        shard.unlink()
        with self.assertRaisesRegex(ValueError, 'MISSING_OR_SYMLINK'):
            bundle.verify_bundle(dest, expected_manifest_sha256=receipt['manifest_sha256'])

    def test_wrong_owner_key_fails_without_plaintext_destination(self):
        dest, receipt = self.export()
        wrong = rsa.generate_private_key(public_exponent=65537, key_size=3072).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        restored = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'PRIVATE_PIN_MISMATCH'):
            bundle.restore_study(dest, restored, expected_manifest_sha256=receipt['manifest_sha256'], owner_private_pem=wrong)
        self.assertFalse(restored.exists())

    def test_unexpected_raw_file_and_nested_public_metadata_rejected(self):
        secret = self.study / 'owner-private.pem'; secret.write_text('PRIVATE_KEY_SENTINEL')
        with self.assertRaisesRegex(ValueError, 'UNEXPECTED'):
            self.export()
        self.assertFalse((self.root / 'public').exists()); secret.unlink()
        model = copy.deepcopy(self.model); model['fit_meta']['context'] = {'raw_source': 'PRIVATE_SOURCE'}
        model['model_sha256'] = digest({k: v for k, v in model.items() if k != 'model_sha256'})
        with self.assertRaisesRegex(ValueError, 'NESTED_FIELDS'):
            bundle.validate_public_model(model)

    def test_calibration_changed_without_pretest_pin_and_git_restore_are_rejected(self):
        path = self.study / 'trifecta_1.calibration.json'
        value = json.loads(path.read_text()); value['calibration_race_ids'].append('injected')
        value['artifact_sha256'] = digest({k: v for k, v in value.items() if k != 'artifact_sha256'})
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'CALIBRATOR_BINDING'):
            self.export()
        path.write_text(json.dumps(self.calibrator))
        dest, receipt = self.export()
        git = self.root / 'git'; git.mkdir(); (git / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_GIT'):
            bundle.restore_study(dest, git / 'private', expected_manifest_sha256=receipt['manifest_sha256'], owner_private_pem=self.secret)

    def test_dataset_identity_is_validated_before_publication_and_after_decryption(self):
        report_path = self.study / 'aggregate_report.json'
        report = json.loads(report_path.read_text()); original = report_path.read_bytes()
        report['source_audit']['dataset_sha256'] = 'PRIVATE_DATASET_SENTINEL'
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'DATASET_SHA_REQUIRED'):
            self.export()
        self.assertFalse((self.root / 'public').exists())
        report_path.write_bytes(original)
        dest, receipt = self.export()
        path = dest / 'manifest.json'; manifest = json.loads(path.read_text())
        manifest['dataset_sha256'] = 'f' * 64
        raw = bundle._canonical(manifest); path.write_bytes(raw)
        restored = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'RESTORED_IDENTITY_MISMATCH'):
            bundle.restore_study(dest, restored, expected_manifest_sha256=sha256(raw).hexdigest(), owner_private_pem=self.secret)
        self.assertFalse(restored.exists())

    def test_dashboard_cannot_show_unbound_study_periods(self):
        path = self.study / 'aggregate_report.json'
        report = json.loads(path.read_text())
        report['evaluation_contract']['splits']['fit']['end'] = '2026-11-22'
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'EMBEDDED_CONTRACT_MISMATCH'):
            self.export()
        self.assertFalse((self.root / 'public').exists())

    def test_compressed_extensions_rejected_before_interpretation_or_publication(self):
        dest, receipt = self.export()
        manifest = bundle.verify_bundle(dest, expected_manifest_sha256=receipt['manifest_sha256'])
        compressed = b''.join(base64.b64decode(self.codec.decrypt_evidence(
            (dest / item['file']).read_bytes(), self.secret)['data_b64']) for item in manifest['shards'])
        header = tarfile.TarInfo('unregistered-extension'); header.type = tarfile.XHDTYPE; header.size = 2 * 1024 * 1024
        poisoned = gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT) + bytes(header.size) + gzip.decompress(compressed))
        for item in manifest['shards']: (dest / item['file']).unlink()
        payload = {'schema': bundle.SCHEMA, 'day_jst': manifest['day'], 'bundle_id': manifest['bundle_id'],
                   'ordinal': 0, 'data_b64': base64.b64encode(poisoned).decode(),
                   'safe_report': {'day_jst': manifest['day']}}
        sealed = self.codec.seal_evidence(payload, self.public, manifest['day'], manifest['created_at'])
        name = 'shard-000000.sealed.json'; (dest / name).write_bytes(sealed)
        manifest['shards'] = [{'file': name, 'ordinal': 0, 'bytes': len(sealed),
                              'sha256': sha256(sealed).hexdigest(), 'data_bytes': len(poisoned)}]
        manifest['archive'].update(sha256=sha256(poisoned).hexdigest(), bytes=len(poisoned))
        raw = bundle._canonical(manifest); (dest / 'manifest.json').write_bytes(raw)
        restored = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'TAR_EXTENSIONS_REFUSED'):
            bundle.restore_study(dest, restored, expected_manifest_sha256=sha256(raw).hexdigest(), owner_private_pem=self.secret)
        self.assertFalse(restored.exists())

    def test_unexpected_file_in_public_directory_invalidates_bundle(self):
        dest, receipt = self.export()
        (dest / 'private.json').write_text('PRIVATE_SENTINEL')
        with self.assertRaisesRegex(ValueError, 'UNEXPECTED_PUBLIC_FILE'):
            bundle.verify_bundle(dest, expected_manifest_sha256=receipt['manifest_sha256'])


if __name__ == '__main__':
    unittest.main()
