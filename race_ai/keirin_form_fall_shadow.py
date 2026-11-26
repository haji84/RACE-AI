"""Non-destructive form/fall A/B shadow attached to the SHA-locked old model.

This module never patches or replaces the historical generator. Its research
A/B shadow is a DIFFERENT model, separately encrypted, not a replacement
for the earlier original or a third independently proven follow-line model C.
"""
from __future__ import annotations

from datetime import timezone
from hashlib import sha256
from itertools import permutations
from pathlib import Path
import base64
import json
import os
import re
import stat
import zlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import keirin_nationwide_auto_generator as core
from . import keirin_nationwide_auto_storage as storage
from . import keirin_rider_form_evidence as form

SUPPLEMENT_SCHEMA = "RACE_AI_KEIRIN_PRIVATE_FORM_SUPPLEMENT_V1"
SCHEMA = "RACE_AI_KEIRIN_CONDITIONED_AB_SHADOW_V1"
SEALED_SCHEMA = "RACE_AI_KEIRIN_PRIVATE_CONDITIONED_AB_CIPHER_V1"
BRANCH_ID = re.compile(r"^L([1-9])_V([0-3])$")
# Nine riders can require six recent results plus both sides of a fall.
# Preserve each actual result receipt instead of fabricating a combined URL.
MAX_CONDITION_SOURCE_PAGES = 128


class ConditionShadowError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise ConditionShadowError(reason)


def source_bundle(snapshot, supplement, *, generated_at):
    """Join only a private auxiliary source receipt, without changing core."""
    need(type(supplement) is dict and
         set(supplement) == {"schema", "race_id", "source_pages", "condition_evidence"} and
         supplement["schema"] == SUPPLEMENT_SCHEMA and
         supplement["race_id"] == snapshot["race_id"] and
         type(supplement["source_pages"]) is list and
         1 <= len(supplement["source_pages"]) <= MAX_CONDITION_SOURCE_PAGES,
         "FORM_SUPPLEMENT_SCHEMA_OR_RACE_INVALID")
    pages = supplement["source_pages"]
    need(all(type(p) is dict and
             set(p) == {"kind", "url", "bytes_sha256", "captured_at"} and
             p["kind"] == "PROGRAM" and
             type(p["bytes_sha256"]) is str and
             core.SHA.fullmatch(p["bytes_sha256"]) is not None
             for p in pages), "FORM_SUPPLEMENT_PAGES_INVALID")
    now = core.when(generated_at)
    asof = max([core.when(snapshot["as_of"])] +
               [core.when(p["captured_at"]) for p in pages])
    need(asof <= now and
         (core.when(snapshot["published_cutoff_at"]) - now).total_seconds() >= 65,
         "FORM_SOURCE_AFTER_PREDICTION_OR_CUTOFF")
    for p in pages:
        core._url(p["url"])
    try:
        assessed = form.assess(
            supplement["condition_evidence"],
            starters={r["car"] for r in snapshot["riders"]},
            source_pages=pages, as_of=asof.isoformat(),
            target_race_id=snapshot["race_id"],
            target_cutoff_at=snapshot["published_cutoff_at"])
    except form.FormEvidenceError as exc:
        raise ConditionShadowError(str(exc)) from None
    return pages, assessed


def generate_shadow(snapshot, supplement, *, baseline, generated_at):
    """Compute candidate rankings and explain impacts, never alter baseline."""
    core.validate_snapshot(snapshot, computed_at=generated_at)
    need(type(baseline) is dict and
         baseline.get("schema") == core.PREDICTION and
         baseline.get("race_id") == snapshot["race_id"] and
         baseline.get("generated_at") == generated_at and
         baseline.get("source_facts_sha256") == core.digest(snapshot) and
         baseline.get("prediction_sha256") == core.digest({
             k: v for k, v in baseline.items() if k != "prediction_sha256"}),
         "FORM_BASELINE_FORECAST_NOT_SHA_BOUND")
    pages, assessed = source_bundle(snapshot, supplement,
                                     generated_at=generated_at)
    max_tickets = len(baseline["A"]["ranked_tickets"])
    need(1 <= max_tickets <= 12, "FORM_BASELINE_TICKET_LIMIT_INVALID")
    power = core._strengths(snapshot["riders"])
    power = {car: strength + assessed[car]["score_adjustment"]
             for car, strength in power.items()}
    ranked_a = core._baseline_A(snapshot, power, max_tickets=max_tickets)
    original_scenarios = baseline["B"]["six_phase_scenarios"]
    adjusted = []
    distribution = {}
    for item in original_scenarios:
        sid = item["scenario_id"]
        match = BRANCH_ID.fullmatch(sid)
        need(match is not None, "FORM_ORIGINAL_SCENARIO_ID_INVALID")
        car, variant = int(match.group(1)), int(match.group(2))
        effect = assessed[car]["score_adjustment"]
        factor = 1.0 + 2.0*effect if variant in (0,3) else 1.0 - effect
        rawweight = item["relative_research_weight"] * factor
        ticket = tuple(item["projected_3ren_tan"])
        adjusted.append((sid, ticket, rawweight))
        distribution[ticket] = distribution.get(ticket, 0.0) + rawweight
    need(bool(adjusted) and sum(x[2] for x in adjusted) > 0,
         "FORM_SHADOW_SCENARIOS_EMPTY")
    ranked_b = [list(t) for t in sorted(
        distribution, key=lambda t: (-distribution[t], t))[:max_tickets]]
    result = {
        "schema": SCHEMA, "race_id": snapshot["race_id"],
        "generated_at": generated_at,
        "published_cutoff_at": snapshot["published_cutoff_at"],
        "baseline_source_sha256": baseline["source_facts_sha256"],
        "baseline_prediction_sha256": baseline["prediction_sha256"],
        "condition_supplement_sha256": core.digest(supplement),
        "A_research": {
            "model": "baseline-plus-documented-form-v1",
            "ranked_tickets": ranked_a,
            "baseline_ranked_tickets": baseline["A"]["ranked_tickets"],
            "changed_from_original": ranked_a != baseline["A"]["ranked_tickets"]},
        "B_research": {
            "model": "six-phase-plus-documented-form-v1",
            "ranked_tickets": ranked_b,
            "baseline_ranked_tickets": baseline["B"]["ranked_tickets"],
            "changed_from_original": ranked_b != baseline["B"]["ranked_tickets"],
            "branch_condition_factors": [
                {"scenario_id": sid,
                 "relative_weight_after": round(weight / sum(x[2] for x in adjusted), 8)}
                for sid, _ticket, weight in adjusted],
            "branch_factor_is_uncalibrated": True},
        "rider_assessments": [assessed[n] for n in sorted(assessed)],
        "verified_source_receipt_count": len(pages),
        "medical_recovery_or_crash_causality_inferred": False,
        "comments_quoted_in_private_supplement_only": True,
        "historical_originals_mutated": False,
        "is_official_calibrated_or_production_forecast": False,
        "C_optional_unrelated": True,
    }
    result["sha256"] = core.digest(result)
    return result


def seal_shadow_once(*, snapshot, supplement, shadow, public_key_pem,
                     path, sealed_at):
    """New independent RSA/AES owner-only original; fail on reusing target."""
    need(shadow.get("schema") == SCHEMA and
         shadow.get("sha256") == core.digest({
             k:v for k,v in shadow.items() if k != "sha256"}) and
         shadow["baseline_source_sha256"] == core.digest(snapshot) and
         shadow["condition_supplement_sha256"] == core.digest(supplement),
         "FORM_SHADOW_ORIGINAL_SHA_INVALID")
    now = core.when(sealed_at)
    need(core.when(shadow["generated_at"]) <= now and
         (core.when(shadow["published_cutoff_at"]) - now).total_seconds() >= 65,
         "FORM_SHADOW_SEALED_AFTER_CUTOFF")
    path = Path(path)
    need(path.parent.is_dir() and not path.parent.is_symlink() and
         stat.S_IMODE(path.parent.stat().st_mode) == 0o700 and
         not path.exists() and not path.is_symlink() and path.name.endswith(".form.sealed.json"),
         "FORM_SHADOW_CREATE_ONCE_PRIVATE_PATH_REQUIRED")
    key = storage.checked_public_key(public_key_pem)
    raw = core.canonical({"shadow": shadow, "supplement": supplement}) + b"\n"
    need(len(raw) <= 2_000_000, "FORM_SHADOW_SOURCE_TOO_LARGE")
    aes = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    aad = ("RACE_AI_FORM_FALL_V1|" + shadow["race_id"] + "|" +
           shadow["baseline_prediction_sha256"]).encode("ascii")
    cipher = AESGCM(aes).encrypt(nonce, zlib.compress(raw, 9), aad)
    wrapped = key.encrypt(aes, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), label=None))
    document = {
        "schema": SEALED_SCHEMA, "race_id": shadow["race_id"],
        "generated_at": shadow["generated_at"],
        "sealed_at": sealed_at,
        "cutoff_at": shadow["published_cutoff_at"],
        "original_baseline_sha256": shadow["baseline_prediction_sha256"],
        "private_shadow_plaintext_sha256": sha256(raw).hexdigest(),
        "owner_spki_sha256": storage.PINNED_OWNER_SPKI_SHA256,
        "rsa_wrapped_aes_key_b64": base64.b64encode(wrapped).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "aad_ascii": aad.decode("ascii"),
        "ciphertext_b64": base64.b64encode(cipher).decode("ascii"),
        "ciphertext_sha256": sha256(cipher).hexdigest(),
        "actual_official_result_included": False,
    }
    data = core.canonical(document) + b"\n"
    need(len(data) < 2_000_000, "FORM_SHADOW_CIPHER_TOO_LARGE")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        need(path.read_bytes() == data, "FORM_SHADOW_PRIVATE_READBACK_FAILED")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"file_sha256": sha256(data).hexdigest(),
            "cipher_sha256": document["ciphertext_sha256"],
            "baseline_prediction_sha256": shadow["baseline_prediction_sha256"]}


def readback_shadow(path, *, expected_sha, expected_baseline_sha, expected_race):
    """A fresh runner checks bytes and ciphertext only, never private claims."""
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < 2_000_000,
         "FORM_SHADOW_CIPHER_FILE_INVALID")
    raw = p.read_bytes()
    need(sha256(raw).hexdigest() == expected_sha,
         "FORM_SHADOW_CIPHER_FILE_SHA_MISMATCH")
    try:
        payload = json.loads(raw)
        cipher = base64.b64decode(payload["ciphertext_b64"], validate=True)
        nonce = base64.b64decode(payload["nonce_b64"], validate=True)
        wrapped = base64.b64decode(payload["rsa_wrapped_aes_key_b64"],validate=True)
    except (ValueError, TypeError, KeyError):
        raise ConditionShadowError("FORM_SHADOW_CIPHER_FIELDS_INVALID") from None
    need(payload.get("schema") == SEALED_SCHEMA and
         payload.get("race_id") == expected_race and
         payload.get("original_baseline_sha256") == expected_baseline_sha and
         payload.get("owner_spki_sha256") == storage.PINNED_OWNER_SPKI_SHA256 and
         payload.get("actual_official_result_included") is False and
         len(nonce) == 12 and len(wrapped) >= 384 and len(cipher) >= 16 and
         sha256(cipher).hexdigest() == payload.get("ciphertext_sha256"),
         "FORM_SHADOW_CIPHER_AUTHENTICITY_UNVERIFIED")
    need(core.when(payload["generated_at"]) <= core.when(payload["sealed_at"]) and
         (core.when(payload["cutoff_at"]) -
          core.when(payload["sealed_at"])).total_seconds() >= 65,
         "FORM_SHADOW_READBACK_AFTER_CUTOFF")
    return {"race_id": expected_race, "cipher_file_sha256": expected_sha,
            "cipher_sha256": payload["ciphertext_sha256"],
            "rsa_private_decryption_verified": False}
