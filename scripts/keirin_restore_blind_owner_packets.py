"""Restore existing owner-private RSA-OAEP/AES-GCM blind-review ZIP envelopes.

Consumes the three *already sealed* Takeo 2R research packets. Do not add a
second prediction/video engine or turn temporary local encryption into a
production storage guarantee. Refuse extraction unless an externally known
ZIP SHA and frozen proposal SHA match. Never print source frames or keys.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import base64
import io
import json
import os
import re
import stat

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEX=re.compile(r"^[a-f0-9]{64}$")
SCHEMA="RACE_AI_KEIRIN_OWNER_PRIVATE_BLIND_SEALED_V1"
ALLOWED_KINDS=frozenset((
  "FROZEN_COLOR_PROPOSALS",
  "BLIND_REVIEWER_A_PENDING",
  "BLIND_REVIEWER_B_PENDING",
))


class BlindRestoreError(ValueError):
    pass


def need(ok,code):
    if not ok:raise BlindRestoreError(code)


def sha(v):
    return type(v) is str and HEX.fullmatch(v) is not None


def _owner_dir(path):
    p=Path(path)
    need(p.is_dir() and not p.is_symlink() and
         p.stat().st_mode&0o077==0,
         "OWNER_PRIVATE_REVIEW_DIR_REQUIRED")
    return p


def _write_once(path,data):
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    try: fd=os.open(path,flags,0o600)
    except OSError:
        raise BlindRestoreError("PRIVATE_RESTORE_ALREADY_EXISTS_OR_UNSAFE") from None
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    need(path.read_bytes()==data,"PRIVATE_RESTORE_READBACK_MISMATCH")


def restore(*,sealed_archive,owner_private_key,private_output,
            expected_envelope_sha256,expected_frozen_proposal_sha256):
    """Exact ciphertext+GCM+SHA readback; never use untrusted paths from ZIP."""
    need(sha(expected_envelope_sha256) and
         sha(expected_frozen_proposal_sha256),
         "OUT_OF_BAND_EXPECTED_HASH_REQUIRED")
    dest_root=_owner_dir(private_output)
    archive=Path(sealed_archive)
    secret=Path(owner_private_key)
    need(archive.is_file() and not archive.is_symlink() and
         secret.is_file() and not secret.is_symlink() and
         secret.stat().st_mode&0o077==0 and
         secret.parent.stat().st_mode&0o077==0,
         "OWNER_PRIVATE_SOURCE_AND_KEY_REQUIRED")
    need(archive.stat().st_size<=45_000_000 and
         sha256(archive.read_bytes()).hexdigest()==expected_envelope_sha256,
         "SEALED_ARCHIVE_SHA_MISMATCH")
    try:
        with ZipFile(archive) as outer:
            need(sorted(outer.namelist())==[
                "envelope.json","payload.aesgcm"],
                "SEALED_ARCHIVE_UNEXPECTED_FILES")
            envelope=json.loads(outer.read("envelope.json"))
            ciphertext=outer.read("payload.aesgcm")
    except (BadZipFile,KeyError,ValueError):
        raise BlindRestoreError("SEALED_ARCHIVE_NOT_DECODABLE") from None
    need(type(envelope) is dict and
         envelope.get("schema")==SCHEMA and
         envelope.get("payload_kind") in ALLOWED_KINDS and
         envelope.get("cipher")=="AES-256-GCM" and
         envelope.get("wrapped_key_cipher")=="RSA-OAEP-SHA256" and
         envelope.get("proposal_sha256")==expected_frozen_proposal_sha256 and
         sha(envelope.get("video_sha256")) and
         sha(envelope.get("detector_code_sha256")),
         "SEALED_ARCHIVE_SOURCE_OR_MODEL_MISMATCH")
    need(sha(envelope.get("payload_ciphertext_sha256")) and
         sha256(ciphertext).hexdigest()==envelope["payload_ciphertext_sha256"],
         "AES_CIPHERTEXT_TAMPERED")
    try:
        private=serialization.load_pem_private_key(
            secret.read_bytes(),password=None)
        need(isinstance(private,rsa.RSAPrivateKey) and
             private.key_size>=3072,
             "OWNER_PRIVATE_RSA_KEY_REQUIRED")
        key=private.decrypt(base64.b64decode(
            envelope["wrapped_key_b64"],validate=True),padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),
            label=None))
        raw=AESGCM(key).decrypt(
            base64.b64decode(envelope["nonce_b64"],validate=True),
            ciphertext,base64.b64decode(envelope["aad_b64"],validate=True))
    except Exception:
        raise BlindRestoreError("PRIVATE_RESTORE_AUTHENTICATION_FAILED") from None
    need(sha(envelope.get("payload_plaintext_sha256")) and
         sha256(raw).hexdigest()==envelope["payload_plaintext_sha256"] and
         len(raw)<=45_000_000,
         "PRIVATE_RESTORE_PLAINTEXT_SHA_INVALID")
    kind=envelope["payload_kind"]
    # All paths are defined locally, never from untrusted envelope content.
    out=dest_root/("restored_"+kind)
    need(not out.exists() and not out.is_symlink(),
         "PRIVATE_RESTORE_ALREADY_EXISTS_OR_UNSAFE")
    files=[]
    if kind=="FROZEN_COLOR_PROPOSALS":
        doc=json.loads(raw)
        need(type(doc) is dict and
             doc.get("proposal_sha256")==expected_frozen_proposal_sha256 and
             doc.get("recording_sha256")==envelope["video_sha256"],
             "RESTORED_PROPOSAL_SHA_MISMATCH")
        files=[("frozen_color_proposals.json",raw)]
    else:
        try:
            with ZipFile(io.BytesIO(raw)) as inner:
                names=inner.namelist()
                need(1<=len(names)<=100 and
                     len(names)==len(set(names)),
                     "REVIEW_PACKET_DUPLICATE_OR_MISSING")
                byte_count=0
                for entry in inner.infolist():
                    name=entry.filename
                    pure=Path(name)
                    need(not name.startswith("/") and
                         pure.name==name and ".." not in pure.parts and
                         re.fullmatch(r"(?:source_\d{3}\.png|manifest\.json|review_UNFINISHED\.json)",
                                      name) is not None and
                         not stat.S_ISLNK(entry.external_attr>>16),
                         "REVIEW_PACKET_UNSAFE_FILE_NAME")
                    need(entry.file_size<=2_000_000,
                         "PRIVATE_REVIEW_IMAGE_TOO_LARGE")
                    data=inner.read(entry)
                    byte_count+=len(data)
                    need(byte_count<=40_000_000,
                         "PRIVATE_REVIEW_ARCHIVE_TOO_LARGE")
                    files.append((name,data))
        except (BadZipFile,KeyError,ValueError):
            raise BlindRestoreError("PRIVATE_REVIEW_ZIP_INVALID") from None
        need(len([x for x,_ in files if x.startswith("source_")])>=1 and
             set(name for name,_ in files)>={
                 "manifest.json","review_UNFINISHED.json"},
             "PRIVATE_REVIEW_REQUIRED_MANIFEST_MISSING")
        review=json.loads(dict(files)["review_UNFINISHED.json"])
        need(review.get("review_sha256") is None and
             review.get("independent_source_frame_read") is False and
             all(type(x) is dict and not x.get("annotations")
                 for x in review.get("frames",[])),
             "PRIVATE_REVIEW_MUST_NOT_ARRIVE_PRESIGNED")
    out.mkdir(mode=0o700)
    for name,data in files:
        _write_once(out/name,data)
    return {
        "schema":"RACE_AI_KEIRIN_OWNER_BLIND_REVIEW_RESTORE_V1",
        "race_id":envelope["race_id"],
        "source_video_sha256":envelope["video_sha256"],
        "frozen_proposal_sha256":expected_frozen_proposal_sha256,
        "payload_kind":kind,
        "restored_private_file_count":len(files),
        "reviewer_ground_truth_completed":False,
        "separate_host_replay_proven":False,
        "model_prediction_weights_modified":False,
        "plaintext_or_private_key_printed":False,
    }


def main():
    p=ArgumentParser()
    p.add_argument("--sealed",type=Path,required=True)
    p.add_argument("--owner-private-key",type=Path,required=True)
    p.add_argument("--private-output",type=Path,required=True)
    p.add_argument("--expected-sealed-zip-sha256",required=True)
    p.add_argument("--expected-frozen-proposal-sha256",required=True)
    args=p.parse_args()
    report=restore(
        sealed_archive=args.sealed,
        owner_private_key=args.owner_private_key,
        private_output=args.private_output,
        expected_envelope_sha256=args.expected_sealed_zip_sha256,
        expected_frozen_proposal_sha256=args.expected_frozen_proposal_sha256)
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
