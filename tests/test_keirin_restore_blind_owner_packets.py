"""Synthetic AES-GCM/RSA owner packet restoration, no real images or keys."""
from __future__ import annotations

from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile,ZIP_DEFLATED,ZIP_STORED
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import io
import json
import os
import unittest

from scripts.keirin_restore_blind_owner_packets import (
    restore,BlindRestoreError,SCHEMA,
)

RID="203001151201"
VIDEO_SHA="a"*64
PROPOSAL_SHA="b"*64
CODE_SHA="c"*64


def b64(x):return b64encode(x).decode("ascii")


def review_payload(*,unsafe=False,finished=False):
    mem=io.BytesIO()
    name="../leak.txt" if unsafe else "source_000.png"
    with ZipFile(mem,"w",ZIP_DEFLATED) as z:
        z.writestr(name,b"FAKE_SYNTHETIC_PIXELS_NOT_A_REAL_FRAME")
        z.writestr("manifest.json",json.dumps({"fake":True}))
        z.writestr("review_UNFINISHED.json",json.dumps({
            "review_sha256":"a"*64 if finished else None,
            "independent_source_frame_read":bool(finished),
            "frames":[{"annotations":[{"example":"FAKE"}] if finished else []}],
        }))
    return mem.getvalue()


class PrivateOwnerPacketRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        os.chmod(self.base,0o700)
        self.review=self.base/"private_output"
        self.review.mkdir(mode=0o700)
        self.archive=self.base/"sealed.zip"
        self.keyfile=self.base/"owner_private.pem"
        self.private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.keyfile.write_bytes(self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        os.chmod(self.keyfile,0o600)

    def seal(self,*,kind="FROZEN_COLOR_PROPOSALS",unsafe=False,finished=False,
             tamper=False):
        raw=(json.dumps({"proposal_sha256":PROPOSAL_SHA,
                         "recording_sha256":VIDEO_SHA}).encode()
             if kind=="FROZEN_COLOR_PROPOSALS"
             else review_payload(unsafe=unsafe,finished=finished))
        k=os.urandom(32);n=os.urandom(12)
        aad=(RID+":"+kind).encode()
        ct=AESGCM(k).encrypt(n,raw,aad)
        m={
            "schema":SCHEMA,"race_id":RID,"payload_kind":kind,
            "video_sha256":VIDEO_SHA,"proposal_sha256":PROPOSAL_SHA,
            "detector_code_sha256":CODE_SHA,
            "cipher":"AES-256-GCM",
            "wrapped_key_cipher":"RSA-OAEP-SHA256",
            "payload_plaintext_sha256":sha256(raw).hexdigest(),
            "payload_ciphertext_sha256":sha256(ct).hexdigest(),
            "wrapped_key_b64":b64(self.private.public_key().encrypt(k,
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                algorithm=hashes.SHA256(),label=None))),
            "nonce_b64":b64(n),"aad_b64":b64(aad),
        }
        if tamper:ct=ct[:-1]+bytes([ct[-1]^0xff])
        with ZipFile(self.archive,"w",ZIP_STORED) as z:
            z.writestr("envelope.json",json.dumps(m))
            z.writestr("payload.aesgcm",ct)
        os.chmod(self.archive,0o600)
        return sha256(self.archive.read_bytes()).hexdigest()

    def call(self,hashed):
        return restore(sealed_archive=self.archive,
                       owner_private_key=self.keyfile,
                       private_output=self.review,
                       expected_envelope_sha256=hashed,
                       expected_frozen_proposal_sha256=PROPOSAL_SHA)

    def test_recover_frozen_proposal_with_verified_hashes(self):
        h=self.seal()
        r=self.call(h)
        self.assertEqual(r["restored_private_file_count"],1)
        self.assertEqual(r["payload_kind"],"FROZEN_COLOR_PROPOSALS")
        self.assertFalse(r["reviewer_ground_truth_completed"])
        dest=self.review/"restored_FROZEN_COLOR_PROPOSALS"
        self.assertEqual(dest.stat().st_mode&0o077,0)
        self.assertEqual((dest/"frozen_color_proposals.json").stat().st_mode&0o077,0)
        with self.assertRaisesRegex(
            BlindRestoreError,"PRIVATE_RESTORE_ALREADY_EXISTS_OR_UNSAFE"):
            self.call(h)

    def test_restore_blind_package_but_not_mark_complete(self):
        h=self.seal(kind="BLIND_REVIEWER_A_PENDING")
        r=self.call(h)
        self.assertEqual(r["restored_private_file_count"],3)
        self.assertFalse(r["reviewer_ground_truth_completed"])
        names=sorted(x.name for x in
                     (self.review/"restored_BLIND_REVIEWER_A_PENDING").iterdir())
        self.assertEqual(names,[
            "manifest.json","review_UNFINISHED.json","source_000.png"])

    def test_wrong_external_hash_blocks_read(self):
        self.seal()
        with self.assertRaisesRegex(
            BlindRestoreError,"SEALED_ARCHIVE_SHA_MISMATCH"):
            self.call("f"*64)
        self.assertEqual(list(self.review.iterdir()),[])

    def test_authenticated_cipher_tamper_rejected(self):
        h=self.seal(tamper=True)
        with self.assertRaisesRegex(
            BlindRestoreError,"AES_CIPHERTEXT_TAMPERED"):
            self.call(h)
        self.assertEqual(list(self.review.iterdir()),[])

    def test_encrypted_zip_traversal_rejected(self):
        h=self.seal(kind="BLIND_REVIEWER_B_PENDING",unsafe=True)
        with self.assertRaisesRegex(
            BlindRestoreError,"REVIEW_PACKET_UNSAFE_FILE_NAME"):
            self.call(h)
        self.assertEqual(list(self.review.iterdir()),[])

    def test_a_presigned_review_must_not_be_restored_as_blank(self):
        h=self.seal(kind="BLIND_REVIEWER_A_PENDING",finished=True)
        with self.assertRaisesRegex(
            BlindRestoreError,"PRIVATE_REVIEW_MUST_NOT_ARRIVE_PRESIGNED"):
            self.call(h)
        self.assertEqual(list(self.review.iterdir()),[])

    def test_world_readable_rsa_key_denied(self):
        h=self.seal()
        os.chmod(self.keyfile,0o644)
        with self.assertRaisesRegex(
            BlindRestoreError,"OWNER_PRIVATE_SOURCE_AND_KEY_REQUIRED"):
            self.call(h)


if __name__=="__main__":
    unittest.main()
