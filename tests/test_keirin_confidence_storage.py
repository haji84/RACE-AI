"""Synthetic confidence sidecars, real local RSA/AES, no provider or owner key."""
from copy import deepcopy
from hashlib import sha256
import base64
import json
from math import fsum
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_auto_settlement as settlement
from race_ai.keirin_legacy_evening_replay import _python311_sum
from tests.test_keirin_nationwide_auto_generator import fixture, AT
from tests.test_keirin_nationwide_auto_storage import make_key

ASSESSED = '2026-11-18T09:01:01+09:00'
SEALED = '2026-11-18T09:01:05+09:00'


class ConfidenceStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key,cls.public,cls.pin=make_key()
        cls.private=cls.key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())

    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.root.chmod(0o700)
        pin=patch.object(storage,'PINNED_OWNER_SPKI_SHA256',self.pin)
        pin.start();self.addCleanup(pin.stop)
        self.snapshot=fixture()
        self.baseline=model.generate_A_B(self.snapshot,generated_at=AT)

    def assessment(self):
        from race_ai import keirin_confidence as confidence
        return confidence.assess_baseline(self.snapshot,self.baseline,assessed_at=ASSESSED)

    def seal(self,**kwargs):
        path=self.root/'original.json'
        receipt=storage.seal_once(snapshot=self.snapshot,prediction=self.baseline,
            public_key_pem=self.public,path=path,sealed_at=SEALED,**kwargs)
        return path.read_bytes(),receipt

    def read(self,raw, *, replay_python311=False):
        return settlement.decrypt_original_with_assessment(raw_cipher=raw,
            expected_cipher_sha256=sha256(raw).hexdigest(),owner_private_pem=self.private,
            replay_python311=replay_python311)

    def rewrite_arm(self,raw,role,change):
        """Mutate authenticated plaintext to exercise semantic tamper checks."""
        envelope=json.loads(raw);row=envelope[role]
        aes=self.key.decrypt(base64.b64decode(row['rsa_oaep_sha256_wrapped_key_b64']),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        nonce=base64.b64decode(row['aesgcm_nonce_b64']);aad=row['aad_ascii'].encode()
        compressed=AESGCM(aes).decrypt(nonce,base64.b64decode(row['ciphertext_b64']),aad)
        data=json.loads(zlib.decompress(compressed));change(data)
        plain=model.canonical(data)+b'\n';compressed=zlib.compress(plain,level=9)
        cipher=AESGCM(aes).encrypt(nonce,compressed,aad)
        row.update(ciphertext_b64=base64.b64encode(cipher).decode(),
            ciphertext_sha256=sha256(cipher).hexdigest(),plaintext_sha256=sha256(plain).hexdigest(),
            compressed_sha256=sha256(compressed).hexdigest())
        return model.canonical(envelope)+b'\n'

    def test_legacy_pair_stays_readable_without_attaching_confidence(self):
        raw,_=self.seal()
        self.assertTrue(callable(getattr(settlement,'decrypt_original_with_assessment',None)),
            'Sidecar readback must preserve the legacy three-value API')
        manifest,baseline,starters,assessment=self.read(raw)
        self.assertIsNone(assessment)
        self.assertEqual(baseline,self.baseline)
        old=settlement.decrypt_original_pair(raw_cipher=raw,
            expected_cipher_sha256=sha256(raw).hexdigest(),owner_private_pem=self.private)
        self.assertEqual(old,(manifest,baseline,starters))

    def test_confidence_is_private_and_survives_replay_without_rescoring(self):
        from race_ai import keirin_confidence as confidence
        assessment=self.assessment();before=deepcopy(self.baseline)
        with patch.object(confidence,'assess_baseline',side_effect=AssertionError('no reassessment')):
            raw,_=self.seal(confidence_assessment=assessment)
            _,baseline,starters,saved=self.read(raw)
        self.assertEqual(saved,assessment)
        self.assertEqual(baseline,before)
        self.assertEqual(self.baseline,before)
        self.assertEqual(starters,set(range(1,8)))
        for private in (b'confidence_assessment',b'evaluations',b'ranked_tickets',
                        assessment['source_prediction_sha256'].encode()):
            self.assertNotIn(private,raw)

    def test_official_replay_is_exact_when_python_float_sum_changes(self):
        def compensated_sum(values, start=0):
            return sum(values, start) if isinstance(start, list) else fsum(values)

        with patch.object(model, 'sum', _python311_sum, create=True):
            self.baseline = model.generate_A_B(self.snapshot, generated_at=AT)
            assessment = self.assessment()
            raw, _ = self.seal(confidence_assessment=assessment)

        with patch.object(model, 'sum', compensated_sum, create=True):
            native = model.generate_A_B(self.snapshot, generated_at=AT)
            self.assertNotEqual(native['prediction_sha256'], self.baseline['prediction_sha256'])
            with self.assertRaisesRegex(ValueError, 'A_B_DECRYPTED_PREDICTION_NOT_REPRODUCIBLE'):
                self.read(raw)
            _, replay, _, saved = self.read(raw, replay_python311=True)
            self.assertEqual(self.baseline, replay)
            self.assertEqual(assessment, saved)
            self.assertIs(model.sum, compensated_sum)
            altered = self.rewrite_arm(raw, 'B', lambda d: d['prediction']['ranked_tickets'].reverse())
            with self.assertRaisesRegex(ValueError, 'A_B_DECRYPTED_PREDICTION_NOT_REPRODUCIBLE'):
                self.read(altered, replay_python311=True)

    def test_invalid_binding_time_or_shape_is_rejected_before_writing(self):
        original=self.assessment()
        changes=(lambda a:a.__setitem__('source_prediction_sha256','f'*64),
            lambda a:a.__setitem__('source_facts_sha256','e'*64),
            lambda a:a.__setitem__('unexpected',True),
            lambda a:a.__setitem__('assessed_at','2026-11-18T09:01:06+09:00'),
            lambda a:a.__setitem__('assessed_at','2026-11-18T11:58:56+09:00'),
            lambda a:a.__setitem__('assessed_at','2026-11-18T09:00:59+09:00'))
        for change in changes:
            bad=deepcopy(original);change(bad)
            with self.subTest(fields=set(bad)):
                with self.assertRaises(ValueError):self.seal(confidence_assessment=bad)
                self.assertFalse((self.root/'original.json').exists())

    def test_both_arm_sidecars_must_match_and_only_known_shapes_are_accepted(self):
        raw,_=self.seal(confidence_assessment=self.assessment())
        changes=(lambda d:d.pop('confidence_assessment'),
            lambda d:d['confidence_assessment'].__setitem__('assessed_at','2026-11-18T09:01:02+09:00'),
            lambda d:d.__setitem__('extra_private_metadata',True),
            lambda d:d['confidence_assessment'].__setitem__('extra_grade',True),
            lambda d:d.__setitem__('confidence_assessment',None))
        for change in changes:
            altered=self.rewrite_arm(raw,'B',change)
            with self.assertRaises(ValueError):self.read(altered)


if __name__=='__main__':
    unittest.main()
