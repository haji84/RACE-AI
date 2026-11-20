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

from . import keirin_nationwide_auto_generator as model
from . import keirin_form_fall_shadow as shadow
from . import keirin_rider_form_evidence as form

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


def build_supplement(*, raw_export, source_url, captured_at, snapshot,
                     independently_authorize_source,
                     independently_verify_identity):
    """Pure local conversion. No source GET, no synthetic rider identities.

    The trusted caller must authenticate usage rights and bytes with a real
    provider contract; merely returning True from a test mock is not a grant.
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
    except (TypeError, ValueError, UnicodeError):
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
    need(independently_authorize_source(
        export["rights_ref"], source_url, sha256(raw_export).hexdigest(),
        tuple(sorted(USES))) is True,
        "HISTORY_INDEPENDENT_RIGHTS_NOT_VERIFIED")
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
    digest = sha256(raw_export).hexdigest()
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
        need(independently_verify_identity(
            snapshot["race_id"], car, ident,
            tuple((p["url"],p["bytes_sha256"]) for p in
                  snapshot["source_pages"] if p["kind"] == "RACECARD")) is True,
            "HISTORY_INDEPENDENT_ROSTER_ID_NOT_VERIFIED")
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
                inner[kind].append(clean)
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
                      target_race_id=snapshot["race_id"])
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
