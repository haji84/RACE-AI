"""Race-ID-bound adapter for PR71's GitHub external timestamp verifier.

PR71's verify_github_freeze checks prediction hash and cutoff but only checks
that its pinned anchor has *a* non-empty race ID, rather than the expected
race ID. This adapter fixes the acceptance gap WITHOUT modifying PR71,
existing prediction bytes, or model code.

Use only with an independently validated race ID and a trusted GitHub API
transport. No network, write, new receipt or legal source rights by default.
"""
from __future__ import annotations
import base64
import binascii
import json
import re

class BoundReceiptError(ValueError):
    """Missing/mismatched race identity or untrusted verifier must fail closed."""

_B64_MAX=100_000
_ID=re.compile(r"[A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff.:-]{8,250}\Z")

def _unique(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:
            raise BoundReceiptError("duplicate GitHub anchor JSON field")
        obj[k]=v
    return obj

def verify_bound_receipt(receipt, content_hash, persisted_at, cutoff_at,
                         *, expected_race_id, trusted_legacy_verifier,
                         github_fetch):
    """Verify external GitHub run AND exact race identity of the pinned anchor.

    trusted_legacy_verifier MUST be the pinned PR71 verify_github_freeze,
    not a user-provided true/false flag. github_fetch must fetch GitHub HTTPS
    API responses independently. Adapter intercepts the SAME pinned blob
    that the legacy verifier checks; no local/self-attested anchor qualifies.
    """
    if (not isinstance(expected_race_id,str) or
        not _ID.fullmatch(expected_race_id)):
        raise BoundReceiptError("expected canonical race ID required")
    if not callable(trusted_legacy_verifier) or not callable(github_fetch):
        raise BoundReceiptError("trusted verifier and GitHub reader required")
    if not isinstance(receipt,dict) or set(receipt)!={"run_id","path"}:
        raise BoundReceiptError("receipt schema invalid")
    checked_blobs=0

    def guarded(url):
        nonlocal checked_blobs
        # All URL path, run association, SHA pin and server time checks
        # remain owned by PR71's legacy verifier.
        data=github_fetch(url)
        if "/contents/" not in url:
            return data
        checked_blobs+=1
        if checked_blobs>1:
            raise BoundReceiptError("unexpected multiple GitHub anchors")
        if not isinstance(data,dict) or data.get("encoding")!="base64":
            raise BoundReceiptError("pinned GitHub anchor missing")
        encoded=data.get("content")
        if not isinstance(encoded,str) or len(encoded)>_B64_MAX:
            raise BoundReceiptError("bounded base64 anchor required")
        try:
            raw=base64.b64decode("".join(encoded.split()), validate=True)
            anchor=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique,
                              parse_constant=lambda v: (_ for _ in ()).throw(
                                  BoundReceiptError("non-finite anchor number")))
        except BoundReceiptError:
            raise
        except (UnicodeDecodeError,binascii.Error,ValueError) as exc:
            raise BoundReceiptError("invalid pinned GitHub anchor") from exc
        if not isinstance(anchor,dict) or anchor.get("race_id")!=expected_race_id:
            raise BoundReceiptError("EXTERNAL_ANCHOR_RACE_ID_MISMATCH")
        if anchor.get("prediction_sha256")!=content_hash or anchor.get("cutoff_at")!=cutoff_at:
            raise BoundReceiptError("anchor fingerprint/cutoff mismatch")
        return data

    passed=trusted_legacy_verifier(receipt,content_hash,persisted_at,
                                   cutoff_at,_fetch=guarded)
    if passed is not True or checked_blobs!=1:
        raise BoundReceiptError("external run/anchor verification incomplete")
    return True
