"""Permission-scoped source delivery into the existing four-sport research suite.

No provider is pre-authorized. HTTP fetch requires a separately authenticated,
purpose-scoped reviewer policy. A signed policy is technical evidence of review,
NOT proof that the upstream rightsholder actually granted the stated rights.
No betting, public publishing, training, result fetching or freeze is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, HTTPRedirectHandler

from .comprehensive_four_sport_models import RESEARCH, SYNTHETIC, digest, moment
from .four_sport_model_suite import run_suite, verify_suite

POLICY_SCHEMA = "RACE_AI_REVIEWED_SOURCE_POLICY_V1"
FEED_SCHEMA = "RACE_AI_NORMALIZED_FEATURE_FEED_V1"
DELIVERY_SCHEMA = "RACE_AI_PRIVATE_DELIVERY_V1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
ALLOWED_PURPOSES = frozenset({"collection", "analysis", "private_storage", "private_derived", "odds_display"})
SUPPLEMENTAL_KEYS = {
    "common": {
        "scheduled_start_at", "daypart", "sunset_offset_minutes",
        "illumination_mode", "meeting_day", "daily_race_number",
        "opponent_strength_adjusted", "head_to_head_form",
        "same_day_course_bias", "rest_recovery", "weather_trend",
        "time_band_win_rate", "time_band_top3_rate",
    },
    "boat": {
        "historical_1m_to_2m_transition", "historical_2m_to_finish_transition",
        "turn2_overtake_rate", "wake_resilience", "motor_exit_acceleration",
        "same_day_second_race_change",
    },
    "keirin": {
        "race_format", "line_role", "girls_keirin_rules",
        "time_band_line_success", "line_break_rate", "final_back_to_finish",
        "bank_time_band_fit",
    },
    "autorace": {
        "same_handicap_grid_order", "same_handicap_start_advantage",
        "start_to_first_corner", "traffic_overtake_rate",
        "handicap_time_band_fit", "track_temp_change",
    },
    "horse": {
        "race_code", "jra_local_banei_category",
        "early_pace_pressure", "corner_position_change",
        "jockey_swap_fit", "current_track_bias", "gate_break_quality",
        "last_sectional_adjusted",
    },
}


FORBIDDEN_MARKET = ("odds", "popularity", "payout", "dividend", "winning_combo",
                    "winning_ticket", "race_result", "actual_finish", "market", "配当", "人気")
SOURCE_KEY = re.compile(r"[A-Za-z0-9._:/?&=%+-]{10,512}\Z")


class SourceDeliveryError(ValueError):
    """A missing, invalid or insufficient source contract blocks delivery."""


def _strict_pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise SourceDeliveryError("duplicate JSON key: " + k)
        result[k] = v
    return result


def read_json_bytes(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_SOURCE_BYTES:
        raise SourceDeliveryError("bounded JSON bytes required")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                          parse_constant=lambda v: (_ for _ in ()).throw(
                              SourceDeliveryError("invalid non-finite number")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceDeliveryError("invalid UTF-8 or JSON") from exc


def _utc(value):
    try:
        t = moment(value)
        return t.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise SourceDeliveryError("timestamp requires valid timezone") from exc


def _https(url):
    if not isinstance(url, str) or len(url) > 512:
        raise SourceDeliveryError("fixed HTTPS source URL required")
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
        or p.fragment or p.port not in (None, 443)):
        raise SourceDeliveryError("source URL must be a fixed HTTPS endpoint")
    try:
        ipaddress.ip_address(p.hostname)
    except ValueError:
        pass
    else:
        raise SourceDeliveryError("literal IP endpoints prohibited")
    if (p.hostname.lower() in {"localhost", "localhost.localdomain"}
        or p.hostname.lower().endswith((".local", ".internal"))):
        raise SourceDeliveryError("internal endpoint prohibited")
    return url


def _grant_fields(item):
    mandatory = {"source_ref", "rights_ref", "transport_url", "purposes",
                 "evidence_url", "reviewer", "checked_at", "expires_at",
                 "max_bytes", "max_requests", "max_cost_jpy"}
    if not isinstance(item, dict) or set(item) != mandatory:
        raise SourceDeliveryError("grant schema incomplete")
    for k in ("source_ref", "rights_ref", "reviewer"):
        if not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > 512:
            raise SourceDeliveryError("grant identity or reviewer missing")
    _https(item["source_ref"])
    _https(item["transport_url"])
    _https(item["evidence_url"])
    if (not isinstance(item["purposes"], list) or
        not item["purposes"] or len(set(item["purposes"])) != len(item["purposes"]) or
        not set(item["purposes"]) <= ALLOWED_PURPOSES):
        raise SourceDeliveryError("unsupported purpose or duplicate")
    if type(item["max_bytes"]) is not int or not 1 <= item["max_bytes"] <= MAX_SOURCE_BYTES:
        raise SourceDeliveryError("bounded provider size limit required")
    if type(item["max_requests"]) is not int or not 1 <= item["max_requests"] <= 10:
        raise SourceDeliveryError("bounded provider request limit required")
    if type(item["max_cost_jpy"]) is not int or item["max_cost_jpy"] != 0:
        raise SourceDeliveryError("paid source not approved for zero-cost mode")
    if not _utc(item["checked_at"]) < _utc(item["expires_at"]):
        raise SourceDeliveryError("invalid permission effective dates")


class PermissionPolicy:
    """Authenticated by reviewer-held secret, separately supplied from feed.

    HMAC validates provenance/integrity of the *review record*. It cannot
    validate the real-world legal grant or replace independent rights review.
    """

    def __init__(self, document, key, *, at):
        if not isinstance(document, dict) or set(document) != {"schema", "policy", "signature"}:
            raise SourceDeliveryError("independently signed policy required")
        if document["schema"] != POLICY_SCHEMA or not isinstance(document["policy"], dict):
            raise SourceDeliveryError("source policy schema invalid")
        policy = document["policy"]
        if set(policy) != {"authority", "grants"} or not isinstance(policy["authority"], str):
            raise SourceDeliveryError("policy authority identity required")
        if not policy["authority"].strip() or not isinstance(policy["grants"], list) or not policy["grants"]:
            raise SourceDeliveryError("empty source grants prohibited")
        if not isinstance(key, bytes) or len(key) < 32:
            raise SourceDeliveryError("independent reviewer key not configured")
        mac = hmac.new(key, digest(policy).encode("ascii"), hashlib.sha256).hexdigest()
        if not isinstance(document["signature"], str) or not hmac.compare_digest(mac, document["signature"]):
            raise SourceDeliveryError("source policy signature unverified")
        self.at = _utc(at)
        self.grants = {}
        self.document_sha256 = digest(document)
        for grant in policy["grants"]:
            _grant_fields(grant)
            if _utc(grant["checked_at"]) > self.at or _utc(grant["expires_at"]) <= self.at:
                raise SourceDeliveryError("source grant not currently effective")
            lookup = (grant["source_ref"], grant["rights_ref"])
            if lookup in self.grants:
                raise SourceDeliveryError("duplicate rights reference")
            self.grants[lookup] = grant
        self.calls = {}

    def authorize(self, source_ref, rights_ref, purpose):
        entry = self.grants.get((source_ref, rights_ref))
        return entry is not None and purpose in entry["purposes"]

    def for_fetch(self, url):
        _https(url)
        matches = [g for g in self.grants.values()
                   if g["transport_url"] == url and "collection" in g["purposes"]]
        if not matches:
            raise SourceDeliveryError("collection not approved for exact provider endpoint")
        # Effective limit is the strictest of the approvals for this endpoint.
        count = self.calls.get(url, 0)
        if count >= min(g["max_requests"] for g in matches):
            raise SourceDeliveryError("provider request budget exceeded")
        self.calls[url] = count + 1
        return min(g["max_bytes"] for g in matches)

    def check_snapshot(self, snapshot, *, needs_storage, supplemental=()):
        if not isinstance(snapshot, dict) or snapshot.get("scope") != RESEARCH:
            raise SourceDeliveryError("production delivery requires explicitly scoped research input")
        entries = []
        for p in snapshot.get("participants", []):
            if not isinstance(p, dict):
                raise SourceDeliveryError("participant schema invalid")
            entries.extend(p.get("features", {}).values())
        entries.extend(snapshot.get("environment", {}).values())
        entries.extend(supplemental)
        if not entries:
            raise SourceDeliveryError("empty features prohibited")
        purposes = {"analysis"}
        if needs_storage:
            purposes |= {"private_storage", "private_derived"}
        for v in entries:
            if not isinstance(v, dict):
                raise SourceDeliveryError("feature provenance missing")
            for purpose in purposes:
                if not self.authorize(v.get("source_ref"), v.get("source_rights_ref"), purpose):
                    raise SourceDeliveryError("SOURCE_PERMISSION_NOT_ADMITTED:" + purpose)
        return True


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceDeliveryError("upstream redirect prohibited")


def bounded_fetch(url, policy, *, opener=None):
    limit = policy.for_fetch(url)  # fail closed before making any HTTP request
    client = opener or build_opener(NoRedirect(), HTTPSHandler(), HTTPHandler())
    req = Request(url, method="GET", headers={
        "Accept": "application/json",
        "User-Agent": "RACE-AI-approved-source-delivery/1",
        "Cache-Control": "no-store",
    })
    try:
        with client.open(req, timeout=8) as response:
            if response.geturl() != url:
                raise SourceDeliveryError("final URL differs from approved endpoint")
            if response.status != 200:
                raise SourceDeliveryError("unexpected provider status")
            typ = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
            if typ != "application/json":
                raise SourceDeliveryError("source is not normalized JSON")
            raw = response.read(limit + 1)
    except SourceDeliveryError:
        raise
    except Exception as exc:
        raise SourceDeliveryError("authorized source request failed") from exc
    if len(raw) > limit:
        raise SourceDeliveryError("provider payload exceeds approved bound")
    return raw


def _reject_market(node):
    if isinstance(node, dict):
        for key, val in node.items():
            if any(t in str(key).lower() for t in FORBIDDEN_MARKET):
                raise SourceDeliveryError("market or result field in input")
            _reject_market(val)
    elif isinstance(node, list):
        for item in node:
            _reject_market(item)



def _verify_supplemental(rows, snapshot, policy, *, at):
    """Retain as-of-legal contextual facts without secretly changing model weights.

    Historical race trajectories are distinct from current-race in-play facts;
    the latter cannot arrive before prediction and are not accepted here.
    """
    if not isinstance(rows, list) or len(rows) > 256:
        raise SourceDeliveryError("bounded optional feature list required")
    sport = snapshot["race"]["sport"]
    known = SUPPLEMENTAL_KEYS["common"] | SUPPLEMENTAL_KEYS[sport]
    participants = {x["number"] for x in snapshot["participants"]}
    as_of = _utc(snapshot["race"]["as_of"])
    seen = set()
    for v in rows:
        if not isinstance(v, dict) or set(v) != {
            "feature_key", "subject_number", "value", "published_at",
            "captured_at", "source_ref", "source_rights_ref",
            "sample_n", "transform_id",
        }:
            raise SourceDeliveryError("supplemental feature schema invalid")
        key = v["feature_key"]
        if key not in known:
            raise SourceDeliveryError("unsupported or post-race supplemental feature")
        who = v["subject_number"]
        if who is not None and (type(who) is not int or who not in participants):
            raise SourceDeliveryError("supplemental feature subject mismatch")
        value = v["value"]
        if type(value) in (float, int):
            import math
            if not math.isfinite(value):
                raise SourceDeliveryError("non-finite supplemental value")
        elif not isinstance(value, (str, bool)) or (isinstance(value, str) and len(value) > 128):
            raise SourceDeliveryError("supplemental value type invalid")
        if (type(v["sample_n"]) is not int or not 1 <= v["sample_n"] <= 10000000
            or not isinstance(v["transform_id"], str) or not v["transform_id"]):
            raise SourceDeliveryError("supplemental observation provenance incomplete")
        if not _utc(v["published_at"]) <= _utc(v["captured_at"]) <= as_of:
            raise SourceDeliveryError("supplemental information published after as_of")
        dedup = (key, who)
        if dedup in seen:
            raise SourceDeliveryError("duplicate supplemental observation")
        seen.add(dedup)
        for purpose in ("analysis", "private_storage", "private_derived"):
            if not policy.authorize(v["source_ref"], v["source_rights_ref"], purpose):
                raise SourceDeliveryError("SOURCE_PERMISSION_NOT_ADMITTED:supplemental")
    return rows


def deliver(raw, policy, *, at, persist=True):
    """Transported normalized JSON -> four-sport suite, no official freeze.

    This deliberately requires a provider-normalized feature schema. Raw HTML,
    PDFs, race odds, and arbitrary CSV are not transformed by guesswork.
    """
    record = read_json_bytes(raw)
    if (not isinstance(record, dict) or set(record) not in (
        {"schema", "snapshot"}, {"schema", "snapshot", "supplemental"})
        or record["schema"] != FEED_SCHEMA):
        raise SourceDeliveryError("unsupported normalized source feed")
    snapshot = record["snapshot"]
    _reject_market(record)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("race"), dict):
        raise SourceDeliveryError("race input missing")
    now = _utc(at)
    as_of = _utc(snapshot["race"]["as_of"])
    cutoff = _utc(snapshot["race"]["sales_cutoff_at"])
    if as_of > now or now >= cutoff:
        raise SourceDeliveryError("MISSED_DEADLINE_OR_FUTURE_INPUT")
    extra = _verify_supplemental(record.get("supplemental", []), snapshot, policy, at=now)
    policy.check_snapshot(snapshot, needs_storage=persist, supplemental=extra)
    suite = run_suite(snapshot, allow_source=policy.authorize)
    if not verify_suite(suite):
        raise SourceDeliveryError("model suite output hash mismatch")
    result = {
        "schema": DELIVERY_SCHEMA,
        "race_id": snapshot["race"]["race_id"],
        "sport": snapshot["race"]["sport"],
        "ingested_at": now.isoformat(),
        "source_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "policy_record_sha256": policy.document_sha256,
        "feature_snapshot_sha256": digest(snapshot),
        "snapshot": snapshot,
        "supplemental_evidence": extra,
        "supplemental_features_used_by_models": False,
        "research_suite": suite,
        "status": "PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN",
        "source_terms_independently_verified_by_code": False,
        "official_prediction": False,
        "external_receipt": None,
        "can_count_in_hit_at_8": False,
        "automatic_betting": False,
    }
    result["delivery_sha256"] = digest(result)
    return result


def _private_write(path, document):
    requested = Path(path).expanduser().absolute()
    dest = requested.parent.resolve(strict=True) / requested.name
    if any((p / ".git").exists() for p in (dest.parent, *dest.parent.parents)):
        raise SourceDeliveryError("do not write private source data into a Git repository")
    if not dest.parent.is_dir():
        raise SourceDeliveryError("private output directory must already exist")
    data = (json.dumps(document, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise SourceDeliveryError("private evidence output already exists or unavailable") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Opt-in signed, permissioned source-to-model delivery")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="separately provided, normalized UTF-8 JSON")
    source.add_argument("--fetch", help="explicitly approved exact HTTPS JSON endpoint")
    parser.add_argument("--policy", required=True, help="reviewer-signed policy JSON")
    parser.add_argument("--key-env", default="RACE_AI_SOURCE_REVIEW_KEY",
                        help="environment variable with reviewer-held signing secret")
    parser.add_argument("--output", required=True, help="new PRIVATE non-Git file only")
    args = parser.parse_args(argv)
    try:
        secret = os.environ.get(args.key_env, "").encode("utf-8")
        doc = read_json_bytes(Path(args.policy).read_bytes())
        now = datetime.now(timezone.utc)
        policy = PermissionPolicy(doc, secret, at=now)
        if args.fetch:
            raw = bounded_fetch(args.fetch, policy)
        else:
            with Path(args.file).open("rb") as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
        result = deliver(raw, policy, at=now)
        _private_write(args.output, result)
        print(json.dumps({"status":result["status"],"race_id":result["race_id"],
                          "delivery_sha256":result["delivery_sha256"],
                          "official_prediction":False}, ensure_ascii=False))
        return 0
    except (SourceDeliveryError, OSError, KeyError, TypeError, ValueError) as exc:
        # Deliberately omit provider response text, data and signing secrets.
        print("SOURCE_DELIVERY_BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
