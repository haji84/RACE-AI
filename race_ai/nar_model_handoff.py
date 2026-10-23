"""NAR official-format staging -> authorized four-sport horse research models.

This bridge never crawls a source, invents NAR horse IDs, trusts user-declared
cutoff times, writes an official prediction, or signs an external freeze.  The
NAR's 66/36-column CSV pair lacks a trustworthy sales cutoff, durable horse IDs
and the full feature set.  All three require *independently supplied evidence*.

Callbacks are interfaces for separately implemented real source verification.
Test callbacks are NOT authenticated evidence. Output stays research-only.
"""
from __future__ import annotations

from datetime import datetime
import math

from .comprehensive_four_sport_models import RESEARCH, digest, moment
from .nar_official_csv_adapter import STAGE_SCHEMA, NarFormatError
from .permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError, read_json_bytes, deliver,
    _reject_market,
)

CUTOFF_SCHEMA = "RACE_AI_NAR_INDEPENDENT_CUTOFF_WITNESS_V1"
IDENTITY_SCHEMA = "RACE_AI_NAR_INDEPENDENT_IDENTITY_WITNESS_V1"
BRIDGE_SCHEMA = "RACE_AI_NAR_MODEL_HANDOFF_V1"
PURPOSES = ("analysis", "private_storage", "private_derived")
SURFACES = {"芝": "turf", "ダート": "dirt"}


def _error(reason):
    raise NarFormatError(reason)


def _time(value, what):
    try:
        return moment(value)
    except (TypeError, ValueError) as exc:
        raise NarFormatError(what + " invalid or missing timezone") from exc


def _provenance(witness, *, policy, at, snapshot_as_of):
    for key in ("source_ref", "source_rights_ref", "published_at", "captured_at"):
        if not isinstance(witness.get(key), str) or not witness[key]:
            _error("witness source or time missing")
    if not (_time(witness["published_at"], "publication") <=
            _time(witness["captured_at"], "capture") <=
            _time(snapshot_as_of, "as_of") <= _time(at, "current")):
        _error("witness timestamp after prediction as_of")
    for purpose in PURPOSES:
        if not policy.authorize(witness["source_ref"], witness["source_rights_ref"], purpose):
            _error("SOURCE_PERMISSION_NOT_ADMITTED:witness:" + purpose)


def _gate(callback, witness, kind):
    # A callable supplied by an operator cannot *prove* it contacted an
    # independent authority: the verifier implementation must be audited.
    if callback is None or callback(witness) is not True:
        _error("UNVERIFIED_" + kind + "_WITNESS")


def link_nar_stage_to_features(stage, normalized_feed_bytes, identity_witness,
                               cutoff_witness, policy, *, at,
                               verify_identity=None, verify_cutoff=None):
    """Reconcile true raw-source identity + separately validated features.

    Model output is research-only even if both external callbacks accept.
    The bridge DOES NOT certify callback authenticity or source entitlements.
    """
    if not isinstance(stage, dict) or stage.get("schema") != STAGE_SCHEMA:
        _error("NAR stage schema mismatch")
    if stage.get("stage_sha256") != digest(
            {k: v for k, v in stage.items() if k != "stage_sha256"}):
        _error("NAR staging record was altered")
    if (stage.get("scope") != "PRIVATE_SOURCE_PREFLIGHT_ONLY" or
        stage.get("model_ready") is not False or
        stage.get("forecast_frozen") is not False or
        stage.get("eligible_hit_at_8") is not False or
        stage.get("official_cutoff_verified") is not False or
        stage.get("sales_cutoff_at") is not None or
        stage.get("external_receipt") is not None):
        _error("staging record cannot self-certify model/forecast readiness")
    if (stage.get("status") != "MISSING_STABLE_HORSE_IDS_AND_FEATURES_AND_CUTOFF" or
        stage.get("declared_entries") != stage.get("observed_entries") or
        not isinstance(stage.get("participants"), list)):
        _error("NAR staged entries incomplete or scratched")
    if not isinstance(policy, PermissionPolicy):
        _error("externally reviewed source policy required")
    for purpose in PURPOSES:
        if not policy.authorize(stage.get("source_ref"), stage.get("source_rights_ref"), purpose):
            _error("SOURCE_PERMISSION_NOT_ADMITTED:NAR_CSV:" + purpose)

    feed = read_json_bytes(normalized_feed_bytes)
    if not isinstance(feed, dict) or set(feed) not in (
            {"schema", "snapshot"}, {"schema", "snapshot", "supplemental"}):
        _error("normalized source feed required")
    snapshot = feed.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("race"), dict):
        _error("model race snapshot missing")
    race = snapshot["race"]
    if (snapshot.get("scope") != RESEARCH or
        race.get("sport") != "horse" or
        race.get("race_id") != stage["race_id"] or
        race.get("event_date_jst") != stage["event_date_jst"] or
        race.get("venue") != stage["venue"] or
        race.get("surface") != SURFACES.get(stage.get("surface"))):
        _error("NAR stage/model identity or race type mismatch")
    try:
        dist = int(stage["distance_m"])
    except (TypeError, ValueError) as exc:
        raise NarFormatError("NAR distance missing") from exc
    if type(race.get("distance_m")) not in (int, float) or (
            not math.isfinite(race["distance_m"]) or race["distance_m"] != dist):
        _error("NAR stage/model race distance mismatch")
    if _time(stage["observed_at_claimed"], "NAR observation") > _time(race["as_of"], "model as_of"):
        _error("model snapshot predates NAR source observation")

    if (not isinstance(identity_witness, dict) or
        set(identity_witness) != {"schema", "race_id", "horses", "source_ref",
                                 "source_rights_ref", "published_at", "captured_at"} or
        identity_witness["schema"] != IDENTITY_SCHEMA or
        identity_witness["race_id"] != stage["race_id"]):
        _error("NAR stable-ID witness missing or wrong race")
    if (not isinstance(cutoff_witness, dict) or
        set(cutoff_witness) != {"schema", "race_id", "sales_cutoff_at",
                               "source_ref", "source_rights_ref",
                               "published_at", "captured_at"} or
        cutoff_witness["schema"] != CUTOFF_SCHEMA or
        cutoff_witness["race_id"] != stage["race_id"]):
        _error("NAR cutoff witness missing or wrong race")
    _reject_market(identity_witness)
    _reject_market(cutoff_witness)
    _provenance(identity_witness, policy=policy, at=at,
                snapshot_as_of=race["as_of"])
    _provenance(cutoff_witness, policy=policy, at=at,
                snapshot_as_of=race["as_of"])
    if (_time(cutoff_witness["sales_cutoff_at"], "official cutoff") !=
            _time(race["sales_cutoff_at"], "model cutoff")):
        _error("model cutoff differs from separately witnessed sales cutoff")
    if not (_time(at, "now") < _time(race["sales_cutoff_at"], "cutoff") <
            _time(stage["scheduled_start_at"], "scheduled start")):
        _error("MISSED_DEADLINE_OR_BAD_CUTOFF")
    _gate(verify_identity, identity_witness, "IDENTITY")
    _gate(verify_cutoff, cutoff_witness, "CUTOFF")

    known = stage["participants"]
    offered = identity_witness["horses"]
    predicted = snapshot.get("participants")
    if not isinstance(offered, list) or not isinstance(predicted, list):
        _error("stable identity witness/participants missing")
    if not (len(known) == len(offered) == len(predicted) ==
            stage["declared_entries"]):
        _error("NAR participants count mismatch")
    ordered = sorted(known, key=lambda x: x["horse_number"])
    mappings, stable_seen = {}, set()
    for row in offered:
        if not isinstance(row, dict) or set(row) != {
            "horse_number", "frame_number", "horse_name", "stable_horse_id"
        }:
            _error("stable identity mapping schema invalid")
        no, stable = row["horse_number"], row["stable_horse_id"]
        if (type(no) is not int or not isinstance(stable, str) or
            not 3 <= len(stable) <= 128 or no in mappings or stable in stable_seen):
            _error("duplicate or unreliable stable horse identifier")
        mappings[no] = row
        stable_seen.add(stable)
    for row in ordered:
        mapping = mappings.get(row["horse_number"])
        if (mapping is None or mapping["horse_name"] != row["horse_name"] or
            mapping["frame_number"] != row["frame_number"]):
            _error("NAR horse number/frame/name mismatch")
    if len(mappings) != len(known):
        _error("NAR identity witness contains extra horse")
    seen = set()
    for row in predicted:
        if not isinstance(row, dict) or type(row.get("number")) is not int:
            _error("model participant number missing")
        no = row["number"]
        if no not in mappings or no in seen or (
                row.get("identity") != mappings[no]["stable_horse_id"]):
            _error("model participant stable identity mismatch")
        seen.add(no)
        # draw is a normalized 1..N start rank, not the NAR frame number;
        # frame/horse distinction is preserved by the witness.
        rank = 1 + [item["horse_number"] for item in ordered].index(no)
        if row.get("draw") != rank:
            _error("model start order conflicts with NAR horse numbers")
    if seen != set(mappings):
        _error("incomplete model identities")

    output = deliver(normalized_feed_bytes, policy, at=at)
    output.update({
        "handoff_schema": BRIDGE_SCHEMA,
        "nar_stage_sha256": stage["stage_sha256"],
        "nar_source_csv_sha256": stage["original_csv_sha256"],
        "identity_witness_sha256": digest(identity_witness),
        "cutoff_witness_sha256": digest(cutoff_witness),
        "identity_and_cutoff_callbacks_accepted": True,
        "source_authenticity_not_established_by_this_bridge": True,
        "external_freeze_receipt": None,
        "official_prediction": False,
        "can_count_in_hit_at_8": False,
        "status": "NAR_PRIVATE_RESEARCH_UNFROZEN",
    })
    output["delivery_sha256"] = digest(
        {k: v for k, v in output.items() if k != "delivery_sha256"})
    return output
