"""Offline, source-byte-bound adapter for an *authorized* player history export.

This does NOT fetch web pages or attest a publisher's rights. A trusted
independent grant verifier must approve the exact rights reference and
source bytes before admission. It binds a persistent official athlete ID to
the existing pre-race roster; matching *only* car numbers is forbidden.

Only private output may be fed to the existing conditioned A/B research
shadow. Actual nationwide provider connection is a separate live gate.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from . import keirin_nationwide_auto_generator as model
from . import keirin_form_fall_shadow as shadow
from . import keirin_rider_form_evidence as form
from . import keirin_winticket_interviews as interviews

SCHEMA = "RACE_AI_KEIRIN_AUTHORIZED_HISTORY_EXPORT_V1"
MAX_BYTES = 2_000_000
MAX_RIDERS = 9
MAX_RESULTS = 40
USES = frozenset((
    "automated_fetch", "pre_race", "history_analysis",
    "model_inference", "private_retention", "comments_use"))


class HistoryAdapterError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise HistoryAdapterError(code)


def _review(verify, *args, code):
    need(callable(verify), code)
    try:
        return verify(*args)
    except Exception:
        raise HistoryAdapterError(code) from None


def _verification_sha(verify, *args, code):
    receipt = _review(verify, *args, code=code)
    need(type(receipt) is str and model.SHA.fullmatch(receipt), code)
    return receipt


def build_supplement(*, raw_export, source_url, captured_at, snapshot,
                     independently_authorize_source,
                     independently_verify_identity,
                     independently_verify_interview=None,
                     independently_verify_finish=None):
    """Pure local conversion. No source GET, no synthetic rider identities.

    The trusted caller must authenticate usage rights and bytes with a real
    provider contract; merely returning True from a test mock is not a grant.
    WINTICKET records additionally need a verified source race, rider, cutoff
    and observation time bound to these exact export bytes. The two WINTICKET
    verification callbacks return the SHA of their independent evidence.
    Interview verification covers text, timing and official race completion
    for a post-race interview. Finish verification covers official starter,
    outcome, event time and availability of the official result.
    """
    need(type(raw_export) is bytes and 0 < len(raw_export) <= MAX_BYTES,
         "HISTORY_EXPORT_BYTES_REQUIRED")
    need(callable(independently_authorize_source),
         "HISTORY_EXTERNAL_RIGHTS_VALIDATOR_REQUIRED")
    need(callable(independently_verify_identity),
         "HISTORY_EXTERNAL_IDENTITY_VALIDATOR_REQUIRED")
    model.validate_snapshot(snapshot, computed_at=captured_at)
    try:
        model._url(source_url)
        export = json.loads(raw_export)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise HistoryAdapterError("HISTORY_JSON_OR_URL_INVALID") from None
    need(type(export) is dict and
         set(export) == {"schema", "race_id", "issued_at",
                         "rights_ref", "allowed_uses", "riders"} and
         export["schema"] == SCHEMA and
         export["race_id"] == snapshot["race_id"] and
         type(export["rights_ref"]) is str and
         1 <= len(export["rights_ref"]) <= 256 and
         type(export["allowed_uses"]) is list and
         set(export["allowed_uses"]) == USES and
         len(export["allowed_uses"]) == len(USES),
         "HISTORY_EXPORT_SCHEMA_OR_RIGHTS_MISMATCH")
    now, published, asof = (model.when(captured_at),
                            model.when(export["issued_at"]),
                            model.when(snapshot["as_of"]))
    need(published <= now and now <
         model.when(snapshot["published_cutoff_at"]) and
         (model.when(snapshot["published_cutoff_at"]) - now).total_seconds() >= 65,
         "HISTORY_EXPORT_NOT_PROSPECTIVE")
    digest = sha256(raw_export).hexdigest()
    rights_code = "HISTORY_INDEPENDENT_RIGHTS_NOT_VERIFIED"
    need(_review(independently_authorize_source,
        export["rights_ref"], source_url, digest,
        tuple(sorted(USES)), code=rights_code) is True, rights_code)
    starters = {r["car"]: r.get("athlete_id") for r in snapshot["riders"]}
    # The current two-source normalizer does not authenticate official IDs:
    # those rows use athlete_id=None, which MUST HOLD rather than link history
    # to a car number that another person could use tomorrow.
    need(all(type(rid) is str and model.RID.fullmatch(rid)
             for rid in starters.values()),
         "HISTORY_ROSTER_REGISTRATION_IDS_UNVERIFIED")
    need(type(export["riders"]) is list and
         1 <= len(export["riders"]) <= min(MAX_RIDERS, len(starters)),
         "HISTORY_EXPORT_RIDER_COUNT_INVALID")
    output = []
    seen = set()
    card_sources = tuple((p["url"], p["bytes_sha256"]) for p in snapshot["source_pages"]
                         if p["kind"] == "RACECARD")
    for record in export["riders"]:
        need(type(record) is dict and
             set(record) == {"car", "registration_id",
                             "results", "absences", "comments"},
             "HISTORY_RIDER_FIELDS_INVALID")
        car, ident = record["car"], record["registration_id"]
        need(type(car) is int and car in starters and car not in seen and
             type(ident) is str and
             model.RID.fullmatch(ident) is not None and
             ident == starters[car],
             "HISTORY_OFFICIAL_ID_AND_STARTER_MISMATCH")
        identity_code = "HISTORY_INDEPENDENT_ROSTER_ID_NOT_VERIFIED"
        need(_review(independently_verify_identity, snapshot["race_id"], car, ident, card_sources,
                     code=identity_code) is True, identity_code)
        seen.add(car)
        # Every historical row must explicitly attribute the same athlete,
        # not just use today's car number. Our existing V1 form evaluator
        # receives only the checked and stripped inner fields.
        inner = {}
        for kind, bound in (("results", MAX_RESULTS),
                            ("absences", 8), ("comments", 12)):
            entries = record[kind]
            need(type(entries) is list and len(entries) <= bound,
                 "HISTORY_EVENT_COUNT_INVALID")
            inner[kind] = []
            for event in entries:
                need(type(event) is dict and
                     type(event.get("registration_id")) is str and
                     event["registration_id"] == ident and
                     event.get("source_ref") == "THIS_EXPORT",
                     "HISTORY_EVENT_OFFICIAL_ID_OR_SHA_MISMATCH")
                clean = {k:v for k,v in event.items()
                         if k not in ("registration_id","source_ref")}
                clean["source_sha256"] = digest
                if kind == "comments" and "winticket" in clean:
                    interviews.validate(clean, target_race_id=snapshot["race_id"],
                        target_car=car, available_at=published,
                        target_cutoff_at=snapshot["published_cutoff_at"])
                    clean["verification_sha256"] = _verification_sha(
                        independently_verify_interview, digest, ident, clean,
                        code="INTERVIEW_SOURCE_NOT_VERIFIED")
                inner[kind].append(clean)
        if any("winticket" in comment for comment in inner["comments"]):
            for race_result in inner["results"]:
                race_result["verification_sha256"] = _verification_sha(
                    independently_verify_finish, digest, ident, race_result,
                    code="INTERVIEW_FINISH_NOT_VERIFIED")
        output.append({"car":car, **inner})
    evidence = {"schema":form.SCHEMA,
                "as_of": now.isoformat(),
                "riders": output}
    receipt = {"kind":"PROGRAM", "url":source_url,
               "bytes_sha256":digest, "captured_at":captured_at}
    try:
        form.validate(evidence, starters=set(starters),
                      source_pages=[receipt],
                      as_of=now.isoformat(),
                      target_race_id=snapshot["race_id"],
                      target_cutoff_at=snapshot["published_cutoff_at"])
    except form.FormEvidenceError as exc:
        raise HistoryAdapterError(str(exc)) from None
    # Avoid promoting a copied owner's bytes checksum into a provider's
    # digital signature or any recovery/medical diagnosis.
    return {
        "schema":shadow.SUPPLEMENT_SCHEMA,
        "race_id":snapshot["race_id"],
        "source_pages":[receipt],
        "condition_evidence":evidence,
    }


def verified_history_loader(*, reviewed_export_for_race, independently_authorize_source,
                            independently_verify_identity, independently_verify_interview,
                            independently_verify_finish):
    """Adapt the existing independent review service to the private batch runner.

    The review service supplies the exact URL, SHA and observation time from
    a separately reviewed export. An input directory cannot approve itself.
    """
    need(all(callable(callback) for callback in (
        reviewed_export_for_race, independently_authorize_source, independently_verify_identity,
        independently_verify_interview, independently_verify_finish)),
        "HISTORY_INDEPENDENT_REVIEW_SERVICE_REQUIRED")

    def load(*, snapshot, raw_pages_dir, captured_at):
        reviewed = _review(reviewed_export_for_race, snapshot["race_id"], code="HISTORY_REVIEW_UNAVAILABLE")
        if reviewed is None:
            return None
        need(type(reviewed) is dict and set(reviewed) == {"url", "bytes_sha256", "captured_at"} and
             type(reviewed["bytes_sha256"]) is str and model.SHA.fullmatch(reviewed["bytes_sha256"]) and
             model.when(reviewed["captured_at"]) <= model.when(captured_at),
             "HISTORY_REVIEW_RECEIPT_INVALID")
        digest = reviewed["bytes_sha256"]
        path = Path(raw_pages_dir)/(digest + ".html")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            need(stat.S_ISREG(info.st_mode) and info.st_mode & 0o077 == 0 and
                 info.st_uid == os.geteuid() and 0 < info.st_size <= MAX_BYTES,
                 "HISTORY_REVIEW_PRIVATE_FILE_REQUIRED")
            raw = handle.read(MAX_BYTES + 1)
        need(0 < len(raw) <= MAX_BYTES and sha256(raw).hexdigest() == digest,
             "HISTORY_REVIEW_EXPORT_SHA_MISMATCH")
        return build_supplement(
            raw_export=raw, source_url=reviewed["url"], captured_at=reviewed["captured_at"],
            snapshot=snapshot, independently_authorize_source=independently_authorize_source,
            independently_verify_identity=independently_verify_identity,
            independently_verify_interview=independently_verify_interview,
            independently_verify_finish=independently_verify_finish)

    return load
