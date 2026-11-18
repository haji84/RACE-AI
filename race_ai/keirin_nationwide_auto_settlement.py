"""Owner-private all-race A/B settlement from existing immutable RSA/AES originals.

Read pre-cutoff sealed A/B, independently SHA-pin the ORIGINAL ciphertext,
decrypt only inside the trusted owner runtime, recompute the two original
algorithms from the authenticated pre-race snapshot, then join later results.

This module performs no network access, does not discover results or
independently certify Git commit timing, actual organizer cutoff, source-use
rights, or the source result. Those THREE independent verifiers must be
supplied by separate trusted acquisition/readback boundaries. Without them
everything stays HOLD, never a fabricated formal hit.
"""
from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit
import base64
import json
import re
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from . import keirin_nationwide_auto_generator as model
from . import keirin_nationwide_auto_storage as storage
from . import keirin_nationwide_AB_results as nationwide_results
from . import keirin_available_prediction_audit as audit

SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_ENCRYPTED_AB_RESULT_JOIN_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_SEALED = storage.MAX_CIPHER_BYTES
MAX_PLAIN = storage.MAX_INPUT_BYTES


class AutoSettlementError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise AutoSettlementError(code)


def _strict_pairs(pairs):
    d = {}
    for key, value in pairs:
        need(key not in d, "DUPLICATE_JSON_FIELD")
        d[key] = value
    return d


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              AutoSettlementError("NONFINITE_JSON_NUMBER")))
    except (UnicodeError, ValueError, TypeError):
        raise AutoSettlementError("UNREADABLE_JSON_BYTES") from None


def _b64(encoded):
    need(type(encoded) is str, "BASE64_REQUIRED")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise AutoSettlementError("INVALID_BASE64_BYTES") from None


def decrypt_original_pair(*, raw_cipher, expected_cipher_sha256,
                          owner_private_pem):
    """RSA/AES authentication + independent model replay, no plaintext I/O."""
    need(type(raw_cipher) is bytes and 0 < len(raw_cipher) < MAX_SEALED and
         type(expected_cipher_sha256) is str and
         SHA.fullmatch(expected_cipher_sha256) and
         sha256(raw_cipher).hexdigest() == expected_cipher_sha256,
         "IMMUTABLE_CIPHER_FILE_SHA_NOT_MATCHED")
    manifest = _json(raw_cipher)
    storage.validate_cipher(manifest)
    need(type(owner_private_pem) is bytes and
         0 < len(owner_private_pem) <= 20000, "OWNER_PRIVATE_KEY_REQUIRED")
    try:
        key = serialization.load_pem_private_key(owner_private_pem, password=None)
    except (TypeError, ValueError):
        raise AutoSettlementError("OWNER_PRIVATE_PEM_INVALID") from None
    need(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 3072,
         "OWNER_RSA_PRIVATE_KEY_3072_REQUIRED")
    pub = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    need(sha256(pub).hexdigest() == storage.PINNED_OWNER_SPKI_SHA256,
         "OWNER_PRIVATE_PUBLIC_FINGERPRINT_MISMATCH")

    originals = {}
    snap = None
    for role in ("A", "B"):
        row = manifest[role]
        try:
            aes = key.decrypt(
                _b64(row["rsa_oaep_sha256_wrapped_key_b64"]),
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                             algorithm=hashes.SHA256(), label=None))
            need(len(aes) == 32, "AES_256_KEY_REQUIRED")
            compressed = AESGCM(aes).decrypt(
                _b64(row["aesgcm_nonce_b64"]),
                _b64(row["ciphertext_b64"]), row["aad_ascii"].encode("ascii"))
            need(sha256(compressed).hexdigest() == row["compressed_sha256"],
                 "COMPRESSED_SHA_MISMATCH")
            decompressor = zlib.decompressobj()
            plain = decompressor.decompress(compressed, MAX_PLAIN + 1)
            need(len(plain) <= MAX_PLAIN and decompressor.eof and
                 not decompressor.unused_data and
                 not decompressor.unconsumed_tail and
                 sha256(plain).hexdigest() == row["plaintext_sha256"],
                 "PRIVATE_ARM_UNBOUNDED_OR_SHA_INVALID")
        except (ValueError, InvalidTag, zlib.error, UnicodeError):
            raise AutoSettlementError("OWNER_DECRYPT_OR_ZLIB_AUTH_FAILED") from None
        data = _json(plain)
        need(type(data) is dict and set(data) == {
            "schema", "role", "race_id", "prediction", "generated_at",
            "pre_race_facts", "pre_race_facts_sha256", "prediction_sha256",
            "official_result_not_included"} and
             data["schema"] == "RACE_AI_KEIRIN_NATIONWIDE_AB_PRIVATE_ARM_V1" and
             data["role"] == role and
             data["race_id"] == manifest["race_id"] and
             data["generated_at"] == manifest["generated_at"] and
             data["official_result_not_included"] is True and
             type(data["pre_race_facts"]) is dict and
             data["pre_race_facts_sha256"] ==
                 manifest["original_source_sha256"] ==
                 model.digest(data["pre_race_facts"]),
             "PRIVATE_ARM_ROLE_OR_SOURCE_LINEAGE_FAILED")
        if snap is None:
            snap = data["pre_race_facts"]
        else:
            need(model.digest(data["pre_race_facts"]) == model.digest(snap),
                 "A_B_PLAIN_SNAPSHOTS_NOT_IDENTICAL")
        originals[role] = data
    need(snap["race_id"] == manifest["race_id"] and
         snap["published_cutoff_at"] == manifest["published_cutoff_at"] and
         model.when(manifest["generated_at"]) <=
         model.when(manifest["sealed_at"]), "ORIGINAL_RACE_OR_CUTOFF_DRIFT")
    replay = model.generate_A_B(snap, generated_at=manifest["generated_at"])
    for role in ("A", "B"):
        need(originals[role]["prediction_sha256"] ==
                 replay["prediction_sha256"] and
             originals[role]["prediction"] == replay[role],
             "A_B_DECRYPTED_PREDICTION_NOT_REPRODUCIBLE")
    return manifest, replay


def _verified(verifier, *args):
    if not callable(verifier):
        return False
    try:
        return verifier(*args) is True
    except Exception:
        return False


def _ticket(t, starters):
    need(type(t) is list and len(t) == 3 and
         all(type(x) is int and x in starters for x in t) and
         len(set(t)) == 3, "RESULT_TRIPLE_NOT_ACTUAL_STARTERS")
    return tuple(t)


def _checked_result(result, manifest, starters):
    need(type(result) is dict and set(result) == {
        "race_id", "status", "refund_status", "official_cutoff_at",
        "source_published_at", "observed_at", "source_url",
        "source_sha256", "provider_revision_ref",
        "winning_triples", "payouts_100yen"
    } and result["race_id"] == manifest["race_id"],
         "RESULT_ID_OR_CONTRACT_INCONSISTENT")
    url = result["source_url"]
    try:
        parsed = urlsplit(url)
        good_url = (parsed.scheme == "https" and
                    parsed.hostname in ("keirin.jp", "www.keirin.jp") and
                    parsed.username is None and parsed.password is None and
                    parsed.port is None and bool(parsed.path) and
                    not parsed.fragment)
    except (TypeError, ValueError):
        good_url = False
    need(good_url and type(result["source_sha256"]) is str and
         SHA.fullmatch(result["source_sha256"]) and
         type(result["provider_revision_ref"]) is str and
         1 <= len(result["provider_revision_ref"]) <= 256,
         "RESULT_OFFICIAL_URL_OR_SOURCE_RECEIPT_MISSING")
    need(result["status"] == "FINAL_NORMAL" and
         result["refund_status"] == "NONE", "RESULT_UNSETTLED_OR_REFUNDED")
    cutoff = model.when(result["official_cutoff_at"])
    need((cutoff-model.when(manifest["sealed_at"])).total_seconds() >= 65 and
         model.when(result["source_published_at"]) > cutoff and
         model.when(result["observed_at"]) >=
             model.when(result["source_published_at"]),
         "OFFICIAL_CUTOFF_OR_RESULT_PUBLICATION_ORDER_INVALID")
    winners = result["winning_triples"]
    payouts = result["payouts_100yen"]
    need(type(winners) is list and type(payouts) is list and
         1 <= len(winners) <= 20 and len(winners) == len(payouts),
         "RESULT_WINNERS_OR_PAYOUTS_INVALID")
    wins = [_ticket(x, starters) for x in winners]
    need(len(set(wins)) == len(wins), "RESULT_WINNER_DUPLICATE")
    paid = {}
    for entry in payouts:
        need(type(entry) is dict and set(entry) == {"triple", "yen"} and
             type(entry["yen"]) is int and
             100 <= entry["yen"] <= 10**9, "RESULT_PAYOUT_INVALID")
        key = _ticket(entry["triple"], starters)
        need(key not in paid, "RESULT_PAYOUT_DUPLICATE")
        paid[key] = entry["yen"]
    need(set(paid) == set(wins), "RESULT_WINNER_PAYOUT_INCONSISTENT")
    return paid


def _score(tickets, paid):
    need(type(tickets) is list and 1 <= len(tickets) <= 12,
         "PREDICTION_TICKET_COUNT_INVALID")
    chosen = [tuple(t) for t in tickets]
    need(len(set(chosen)) == len(chosen), "PREDICTION_TICKET_DUPLICATE")
    return {"hit_at_1": chosen[0] in paid,
            "hit_at_all": any(x in paid for x in chosen),
            "stake_yen": 100 * len(chosen),
            "payout_yen": sum(paid.get(x, 0) for x in chosen)}


def settle_day(*, registry, sealed_by_race, expected_sha_by_race,
               final_results_by_race, owner_private_pem,
               independently_verify_immutable_origin=None,
               independently_verify_official_cutoff=None,
               independently_verify_final_result=None):
    """One full-cohort run. Unverified races never enter the scored denominator."""
    rows, _ = nationwide_results._rows(registry)
    ids = [r["race_id"] for r in rows]
    scope = set(ids)
    need(type(sealed_by_race) is dict and
         type(expected_sha_by_race) is dict and
         type(final_results_by_race) is dict and
         all(type(m) is dict and set(m) <= scope for m in (
             sealed_by_race, expected_sha_by_race, final_results_by_race)),
         "RESULT_INPUT_OUTSIDE_REGISTERED_DAY")
    need(type(owner_private_pem) is bytes, "OWNER_PRIVATE_PEM_REQUIRED")
    statuses = []
    paired = []
    accepted = {}
    for rid in ids:
        state = "HOLD_NO_PRE_CUTOFF_FORECAST"
        if rid in sealed_by_race and rid in expected_sha_by_race:
            state = "HOLD_NO_OFFICIAL_RESULT"
            if rid in final_results_by_race:
                try:
                    raw = sealed_by_race[rid]
                    expected = expected_sha_by_race[rid]
                    # Independent GitHub readback must bind immutable BYTES
                    # and timestamp; reading the local file alone is not proof.
                    need(_verified(independently_verify_immutable_origin,
                                   rid, expected, raw),
                         "IMMUTABLE_GITHUB_ORIGIN_NOT_INDEPENDENTLY_VERIFIED")
                    manifest, forecast = decrypt_original_pair(
                        raw_cipher=raw,
                        expected_cipher_sha256=expected,
                        owner_private_pem=owner_private_pem)
                    result = final_results_by_race[rid]
                    need(_verified(independently_verify_official_cutoff,
                                   rid, manifest, result),
                         "ACTUAL_OFFICIAL_CUTOFF_NOT_INDEPENDENTLY_VERIFIED")
                    need(_verified(independently_verify_final_result,
                                   rid, result),
                         "OFFICIAL_FINAL_RESULT_NOT_INDEPENDENTLY_VERIFIED")
                    starters = {x["car"] for x in
                                _json(base64.b64decode("e30=")).values()} if False else None
                    # Decrypt returns the original prediction and its
                    # authenticated source. The original starter set is
                    # checked by replaying model input from the encrypted arm.
                    # Extracted source car IDs are necessary for refunds /
                    # ties and must never appear in the public summary.
                    need(type(result) is dict, "RESULT_OBJECT_REQUIRED")
                    # The correct starters are the actual pre-race registered
                    # entries, not an inferred 1..9 default or winning IDs.
                    starter_count = forecast.get("starter_cars")
                    need(starter_count is not None, "REPLAY_STARTERS_REQUIRED")
                    paid = _checked_result(result, manifest, set(starter_count))
                    a = _score(forecast["A"]["ranked_tickets"], paid)
                    b = _score(forecast["B"]["ranked_tickets"], paid)
                    report = {
                        "schema": audit.AUDIT_SCHEMA, "race_id": rid,
                        "state": "A_B_RESEARCH_SETTLED", "ab_evaluable": True,
                        "abc_evaluable": False,
                        "A_existing": a, "B_six_phase": b,
                        "C_six_phase_plus_line": None,
                    }
                    paired.append(report)
                    accepted[rid] = report
                    state = "AB_SETTLED_FROM_INDEPENDENT_RECEIPTS"
                except (AutoSettlementError, storage.AutoSealError,
                        model.AutomaticForecastError, ValueError, KeyError,
                        TypeError, InvalidTag):
                    state = "HOLD_UNVERIFIED_CIPHER_CUTOFF_OR_RESULT"
        statuses.append({"race_id":rid,"state":state})
    summary = nationwide_results.summarize(
        registry=registry, paired_reports=paired,
        independently_verify_settled_report=lambda rid, report:
            accepted.get(rid) is report)
    return {
        "schema": SCHEMA, "day_jst": registry["day_jst"],
        "registered_races": len(ids),
        "paired_A_B_scored": summary["ab_independently_scored_races"],
        "formal_accuracy_proven": False,
        "official_source_rights_not_established_by_this_code": True,
        "C_optional_not_blocking_A_B": True,
        "predictions_never_rewritten": True,
        "statuses": statuses,
        "scorecard": summary,
    }
