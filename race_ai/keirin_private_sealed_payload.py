"""RSA-OAEP/AES-256-GCM envelope for private video feature/model JSON.

Runs in a temporary, isolated GitHub Actions worker. The public repository
contains ONLY the public RSA wrapping key, never private keys or raw frames.
Ciphertext is not a replacement for a durable private object store.
"""
from __future__ import annotations
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA="RACE_AI_PRIVATE_KEIRIN_ENCRYPTED_JSON_V1"

class SealedResearchError(ValueError): pass

def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode("utf-8")

def seal_json(obj,public_key,*,aad):
    if not isinstance(aad,str) or not aad.startswith("RACE_AI_PRIVATE_KEIRIN:"):
        raise SealedResearchError("INVALID_ENCRYPTION_CONTEXT")
    if type(public_key) not in (bytes,bytearray):
        public_key=Path(public_key).read_bytes()
    public=serialization.load_pem_public_key(public_key)
    if not isinstance(public,rsa.RSAPublicKey) or public.key_size<3072:
        raise SealedResearchError("RSA_KEY_TOO_SMALL")
    raw=canonical(obj)
    if len(raw)>25_000_000:
        raise SealedResearchError("RESEARCH_JSON_TOO_LARGE")
    secret=os.urandom(32)
    nonce=os.urandom(12)
    aad_bytes=aad.encode("utf-8")
    ciphertext=AESGCM(secret).encrypt(nonce,raw,aad_bytes)
    wrapped=public.encrypt(secret,padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    return {
        "schema":SCHEMA,
        "context":aad,
        "plaintext_sha256":sha256(raw).hexdigest(),
        "ciphertext_sha256":sha256(ciphertext).hexdigest(),
        "nonce_b64":base64.b64encode(nonce).decode("ascii"),
        "wrapped_key_b64":base64.b64encode(wrapped).decode("ascii"),
        "ciphertext_b64":base64.b64encode(ciphertext).decode("ascii"),
        "source_is_private":True,
        "plaintext_embedded":False,
    }

def open_sealed_json(envelope,private_key,*,aad):
    """Owner-side only. NEVER call in a public Actions job or print the output."""
    if (type(envelope) is not dict or
        envelope.get("schema")!=SCHEMA or
        envelope.get("context")!=aad or
        envelope.get("source_is_private") is not True):
        raise SealedResearchError("ENVELOPE_PROVENANCE_INVALID")
    private=serialization.load_pem_private_key(
        private_key if isinstance(private_key,bytes)
        else Path(private_key).read_bytes(),password=None)
    if not isinstance(private,rsa.RSAPrivateKey):
        raise SealedResearchError("UNSUPPORTED_PRIVATE_KEY")
    data=base64.b64decode(envelope["ciphertext_b64"],validate=True)
    if sha256(data).hexdigest()!=envelope["ciphertext_sha256"]:
        raise SealedResearchError("CIPHER_TAMPER")
    aes_key=private.decrypt(base64.b64decode(
        envelope["wrapped_key_b64"],validate=True),padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),label=None))
    try:
        plain=AESGCM(aes_key).decrypt(base64.b64decode(
           envelope["nonce_b64"],validate=True),data,aad.encode())
    except Exception as exc:
        raise SealedResearchError("AUTHENTICATION_FAILED") from exc
    if sha256(plain).hexdigest()!=envelope["plaintext_sha256"]:
        raise SealedResearchError("RESEARCH_SHA_MISMATCH")
    return json.loads(plain)
