"""Missing-aware BOAT research contrasts; pure offline, untrained, never betting.

Missing pairs contribute no contrast. That is a neutrality assumption, not an
observed average, and can advantage sparse entrants. Completion bounds describe
only missing-value sensitivity within the declared ranges. Source/time/window
identifiers are supplied claims; this module authenticates none of them.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta, timezone
from fractions import Fraction
import json
import math
import re
from urllib.parse import urlsplit

from .actions_contract import ContractError, canonical, digest, stamp
from .legacy_boat_rank import plackett_luce


SCHEMA = "RACE_AI_BOAT_OBSERVED_PAIRWISE_V1"
SUITE_SCHEMA = "RACE_AI_BOAT_OBSERVED_PAIRWISE_SUITE_V1"
MODEL_IDS = ("boat-observed-pairwise-factor-v1", "boat-observed-pairwise-start-v1")
MODEL_VERSION = "0.1.0-UNTRAINED"
FEATURE_RANGES = {
    "national_win_rate": (0, 10), "motor_top2_rate": (0, 100),
    "recent_mean_finish": (1, 6), "course_mean_finish": (1, 6),
    "recent_mean_st": (0, 1), "course_mean_st": (0, 1),
    "exhibition_time_seconds": (1, 20), "exhibition_start_seconds": (0, 1),
}
FEATURE_TRANSFORMS = dict(zip(FEATURE_RANGES, (
    "official_B_national_win_rate_points_v1", "official_B_motor_top2_percent_v1",
    "strict_numeric_finish_mean_v1", "strict_numeric_finish_mean_v1",
    "strict_ok_start_mean_seconds_v1", "strict_ok_start_mean_seconds_v1",
    "official_exhibition_time_seconds_v1", "official_exhibition_start_seconds_v1",
)))
WEIGHTS = dict(zip(MODEL_IDS, (
    (1.25, .75, 1, .65, .35, .20, .35, .20),
    (.75, .50, .80, .35, .90, .35, .70, .50),
)))
MISSING_REASONS = frozenset(("MISSING", "NOT_YET_PUBLISHED", "SOURCE_UNAVAILABLE",
                            "RIGHTS_BLOCKED", "UNRESOLVED_DISPOSITION", "F", "L",
                            "NO_PRIOR_SAMPLES", "NO_VERIFIED_COURSE"))
HISTORY_FIELDS = frozenset(("recent_mean_finish", "course_mean_finish",
                            "recent_mean_st", "course_mean_st"))
EXHIBITION_FIELDS = frozenset(("exhibition_time_seconds", "exhibition_start_seconds"))
RATE_FIELDS = frozenset(("national_win_rate", "motor_top2_rate"))
ROOT_FIELDS = frozenset(("schema", "scope", "race_id", "event_date_jst", "venue",
                         "race_revision", "sales_cutoff_at", "as_of", "stage",
                         "race_source_id", "sources", "participants"))
SOURCE_FIELDS = frozenset(("source_id", "source_url", "source_sha256", "source_rights_ref",
                           "published_at", "captured_at", "evidence_basis"))
FEATURE_FIELDS = frozenset(("value", "sample_n", "source_id", "transform_id"))
HISTORY_KEYS = frozenset(("window_id", "total_n", "ok_n", "f_n", "l_n", "missing_n", "unresolved_n"))
JST = timezone(timedelta(hours=9))


class ObservedPairwiseError(ValueError):
    """Invalid supplied research contract; no forecast was produced."""


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ObservedPairwiseError(label + ": exact fields required")


def _label(value, label, maximum=256):
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ObservedPairwiseError("invalid " + label)


def _time(value, label):
    try:
        return stamp(value)
    except (TypeError, ValueError) as exc:
        raise ObservedPairwiseError("invalid " + label) from exc


def _positive_count(value):
    return type(value) is int and value > 0


def _url(value, scope):
    if value == "synthetic://fixture" and scope == "SYNTHETIC_ONLY":
        return
    if (type(value) is not str or len(value) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in ("?", "#", "\\"))):
        raise ObservedPairwiseError("source URL must be plain HTTPS without query/fragment")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        valid = (parsed.scheme == "https" and hostname is not None
                 and parsed.username is None and parsed.password is None
                 and parsed.port != 0
                 and re.fullmatch(r"[A-Za-z0-9.-]+", hostname)
                 and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", part)
                         for part in hostname.split(".")))
    except ValueError as exc:
        raise ObservedPairwiseError("invalid source URL") from exc
    if not valid:
        raise ObservedPairwiseError("source URL must be plain HTTPS without credentials")


def _validate_sources(snapshot, as_of):
    sources = snapshot["sources"]
    if type(sources) is not list:
        raise ObservedPairwiseError("sources must be a list")
    ids, urls, hashes = set(), set(), set()
    for source in sources:
        _exact(source, SOURCE_FIELDS, "source")
        _label(source["source_id"], "source identity")
        _label(source["source_rights_ref"], "source rights reference")
        _url(source["source_url"], snapshot["scope"])
        sha = source["source_sha256"]
        if type(sha) is not str or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ObservedPairwiseError("source SHA256 required")
        if source["source_id"] in ids or source["source_url"] in urls or sha in hashes:
            raise ObservedPairwiseError("unique source IDs, URLs and hashes required")
        ids.add(source["source_id"])
        urls.add(source["source_url"])
        hashes.add(sha)
        captured = _time(source["captured_at"], "source captured_at")
        if captured > as_of:
            raise ObservedPairwiseError("source captured after as_of")
        if source["evidence_basis"] == "SOURCE_PUBLISHED_AT_CLAIM":
            published = _time(source["published_at"], "source published_at")
            if published > captured:
                raise ObservedPairwiseError("source published after capture")
        elif source["evidence_basis"] == "CAPTURED_BY_CLAIM":
            if source["published_at"] is not None:
                raise ObservedPairwiseError("captured-only claim requires null publication")
        else:
            raise ObservedPairwiseError("unsupported source evidence basis")
    if type(snapshot["race_source_id"]) is not str or snapshot["race_source_id"] not in ids:
        raise ObservedPairwiseError("race_source_id must reference a supplied source")
    return ids


def _validate_history(feature, name):
    history = feature["history"]
    _exact(history, HISTORY_KEYS, name + " history")
    _label(history["window_id"], "claimed history window")
    counts = [history[key] for key in HISTORY_KEYS if key != "window_id"]
    if any(type(count) is not int or count < 0 for count in counts):
        raise ObservedPairwiseError("history counts must be nonnegative integers")
    if (not _positive_count(feature["sample_n"]) or feature["sample_n"] != history["ok_n"]
            or history["total_n"] != sum(history[k] for k in ("ok_n", "f_n", "l_n", "missing_n", "unresolved_n"))
            or history["unresolved_n"] != 0):
        raise ObservedPairwiseError("history counts/sample_n inconsistent or unresolved")
    if name.endswith("finish") and any(history[key] for key in ("f_n", "l_n", "missing_n")):
        raise ObservedPairwiseError("finish mean requires known numeric finishes throughout window")


def _validate_feature(feature, name, source_ids):
    fields = FEATURE_FIELDS | {"history"} if name in HISTORY_FIELDS else FEATURE_FIELDS
    _exact(feature, fields, name)
    value = feature["value"]
    low, high = FEATURE_RANGES[name]
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ObservedPairwiseError("invalid finite value for " + name)
    if type(feature["source_id"]) is not str or feature["source_id"] not in source_ids:
        raise ObservedPairwiseError("feature references unknown source")
    if feature["transform_id"] != FEATURE_TRANSFORMS[name]:
        raise ObservedPairwiseError("unsupported transform for " + name)
    if name in HISTORY_FIELDS:
        _validate_history(feature, name)
    elif name in RATE_FIELDS:
        if feature["sample_n"] is not None and not _positive_count(feature["sample_n"]):
            raise ObservedPairwiseError("aggregate sample_n must be null or positive integer")
    elif feature["sample_n"] is not None:
        raise ObservedPairwiseError("instantaneous exhibition sample_n must be null")


def _validate(snapshot):
    _exact(snapshot, ROOT_FIELDS, "snapshot")
    if snapshot["schema"] != SCHEMA:
        raise ObservedPairwiseError("unsupported snapshot schema")
    if snapshot["scope"] not in ("SYNTHETIC_ONLY", "OPERATOR_SUPPLIED_RESEARCH"):
        raise ObservedPairwiseError("explicit research scope required")
    if snapshot["stage"] not in ("P0", "P1"):
        raise ObservedPairwiseError("stage must be P0 or P1")
    if not _positive_count(snapshot["race_revision"]):
        raise ObservedPairwiseError("positive integer race_revision required")
    try:
        day = date.fromisoformat(snapshot["event_date_jst"])
    except (TypeError, ValueError) as exc:
        raise ObservedPairwiseError("canonical JST event date required") from exc
    if day.isoformat() != snapshot["event_date_jst"]:
        raise ObservedPairwiseError("canonical JST event date required")
    race = snapshot["race_id"]
    match = re.fullmatch(r"boat:(\d{4}-\d{2}-\d{2}):(boatrace-jcd-(\d{2})):([1-9]|1[0-2])", race) if type(race) is str else None
    if (match is None or match[1] != snapshot["event_date_jst"]
            or match[2] != snapshot["venue"] or not 1 <= int(match[3]) <= 24):
        raise ObservedPairwiseError("race/date/venue identity mismatch")
    cutoff = _time(snapshot["sales_cutoff_at"], "sales cutoff")
    as_of = _time(snapshot["as_of"], "as_of")
    if not as_of < cutoff or cutoff.astimezone(JST).date() != day:
        raise ObservedPairwiseError("as_of must precede JST event cutoff")
    sources = _validate_sources(snapshot, as_of)
    participants = snapshot["participants"]
    if type(participants) is not list or len(participants) != 6:
        raise ObservedPairwiseError("exactly six participants required")
    lanes, registrations = set(), set()
    history_claims = {}
    exhibition_n = 0
    for row in participants:
        _exact(row, {"lane", "registration_no", "features", "missing"}, "participant")
        lane, registration = row["lane"], row["registration_no"]
        if type(lane) is not int or not 1 <= lane <= 6 or lane in lanes:
            raise ObservedPairwiseError("unique integer lanes 1..6 required")
        if type(registration) is not str or not re.fullmatch(r"[0-9]{4}", registration) or registration in registrations:
            raise ObservedPairwiseError("unique four-digit registration identities required")
        lanes.add(lane)
        registrations.add(registration)
        features, missing = row["features"], row["missing"]
        if (type(features) is not dict or type(missing) is not dict
                or set(features) & set(missing)
                or set(features) | set(missing) != set(FEATURE_RANGES)):
            raise ObservedPairwiseError("features/missing must exactly partition eight fields")
        if any(type(reason) is not str or reason not in MISSING_REASONS for reason in missing.values()):
            raise ObservedPairwiseError("explicit supported missing reason required")
        for name, feature in features.items():
            _validate_feature(feature, name, sources)
            if name in HISTORY_FIELDS:
                provenance = (registration, feature["source_id"],
                              feature["history"]["window_id"], feature["transform_id"])
                if provenance in history_claims and history_claims[provenance] != feature:
                    raise ObservedPairwiseError("conflicting history provenance measurements")
                history_claims[provenance] = feature
            exhibition_n += name in EXHIBITION_FIELDS
    if snapshot["stage"] == "P0" and exhibition_n:
        raise ObservedPairwiseError("P0 cannot contain exhibition features")
    if snapshot["stage"] == "P1" and not exhibition_n:
        raise ObservedPairwiseError("P1 requires at least one numeric exhibition observation")


def _research_flags():
    return {"trained": False, "calibrated": False, "official_prediction": False,
            "source_authentication": False, "independent_availability_verified": False,
            "result_or_cutoff_proof_eligible": False, "purchase_decision": "NO_BET"}


def _spec():
    return {
        "model_ids": list(MODEL_IDS), "model_version": MODEL_VERSION,
        "feature_ranges": deepcopy(FEATURE_RANGES), "feature_transforms": deepcopy(FEATURE_TRANSFORMS),
        "history_schema": sorted(HISTORY_KEYS), "missing_reasons": sorted(MISSING_REASONS),
        "history_consistency": "same participant/source/window/transform requires same value and counts",
        "orientation": {name: "up" if name in RATE_FIELDS else "down" for name in FEATURE_RANGES},
        "weights": {model_id: dict(zip(FEATURE_RANGES, weights)) for model_id, weights in WEIGHTS.items()},
        "utility": "sum_k (w_k/6) sum_j!=i,both_observed (z_ik-z_jk)",
        "arithmetic": "exact rational JSON-decimal contrasts; float exponential and legacy PL",
        "completion_bounds": "missing z independently in [0,1]; conservative per-entrant utility bounds",
        "candidate_rule": "legacy_boat_rank.plackett_luce; score descending then lexical combination; Top8",
        "missing_assumption": "absent contrast is neutral; no dynamic weight normalization",
    }


def _contrasts(snapshot):
    rows = sorted(snapshot["participants"], key=lambda row: row["lane"])
    normalized = {}
    counts, pair_counts, discriminating_counts = {}, {}, {}
    comparisons = {lane: {} for lane in range(1, 7)}
    contrasts = []
    for name, (low, high) in FEATURE_RANGES.items():
        values = {}
        for row in rows:
            if name in row["features"]:
                raw = Fraction(str(row["features"][name]["value"]))
                values[row["lane"]] = (raw - low) / (high - low) if name in RATE_FIELDS else (high - raw) / (high - low)
        normalized[name] = values
        counts[name] = len(values)
        pair_counts[name] = len(values) * (len(values) - 1) // 2
        discriminating_counts[name] = 0
        for lane in range(1, 7):
            comparisons[lane][name] = len(values) - 1 if lane in values else 0
        for left in range(1, 7):
            for right in range(left + 1, 7):
                if left in values and right in values:
                    delta = values[left] - values[right]
                    discriminating_counts[name] += delta != 0
                    contrasts.append({"feature": name, "left_lane": left, "right_lane": right,
                                      "normalized_difference": float(delta)})
    coverage = {
        "observed_feature_counts": counts, "observed_pair_counts": pair_counts,
        "discriminating_pair_counts": discriminating_counts,
        "observed_feature_value_count": sum(counts.values()), "possible_feature_value_count": 48,
        "observed_pair_count": sum(pair_counts.values()), "possible_pair_count": 120,
        "discriminating_pair_count": sum(discriminating_counts.values()),
        "entrant_comparisons": [{"lane": lane, "by_feature": comparisons[lane],
                                  "total": sum(comparisons[lane].values())} for lane in range(1, 7)],
    }
    return normalized, contrasts, coverage


def _model_result(model_id, normalized, coverage, binding):
    utilities = []
    for lane in range(1, 7):
        utility, lower, upper = Fraction(0), Fraction(0), Fraction(0)
        for name, weight in zip(FEATURE_RANGES, WEIGHTS[model_id]):
            scale = Fraction(str(weight)) / 6
            values = normalized[name]
            for other in range(1, 7):
                if lane == other:
                    continue
                if lane in values and other in values:
                    lo = hi = values[lane] - values[other]
                    utility += scale * lo
                elif lane in values:
                    lo, hi = values[lane] - 1, values[lane]
                elif other in values:
                    lo, hi = -values[other], 1 - values[other]
                else:
                    lo, hi = -1, 1
                lower += scale * lo
                upper += scale * hi
        utilities.append({"lane": lane, "utility": float(utility), "strength": math.exp(float(utility)),
                          "completion_lower": float(lower), "completion_upper": float(upper),
                          "observed_comparisons": coverage["entrant_comparisons"][lane - 1]["total"]})
    score_discriminating = len({row["utility"] for row in utilities}) > 1
    ranked = plackett_luce({row["lane"]: row["strength"] for row in utilities})
    candidates = [{"combination": row["combination"], "score": row["probability"]} for row in ranked["triples"]]
    candidates.sort(key=lambda row: (-row["score"], row["combination"]))
    result = {
        **binding, **_research_flags(), "model_id": model_id, "model_version": MODEL_VERSION,
        "status": "OBSERVED_CONTRASTS" if score_discriminating else "UNINFORMATIVE_TIE_BREAK",
        "score_discriminating": score_discriminating,
        "model_status": "RESEARCH_UNTRAINED_NOT_CALIBRATED", "validation_status": "UNVALIDATED",
        "utilities": utilities, "coverage": deepcopy(coverage),
        "candidates": candidates, "candidate_scores_sha256": digest(candidates),
        "ordered_top8": [deepcopy(row["combination"]) for row in candidates[:8]],
    }
    result["prediction_sha256"] = digest(result)
    return result


def predict_pair(snapshot, *, allow_source=None):
    """Return a hashed, research-only suite for this exact supplied snapshot.

    The optional permission callback receives (URL, rights reference, 'analysis')
    and must return exact True for every research source. Callback arguments are
    immutable strings; all inference binds a detached JSON copy made before any
    callback. A callback closing over the caller's original can mutate that
    original, but cannot mutate the copy scored and hashed here.
    """
    try:
        frozen = json.loads(canonical(snapshot))
    except (ContractError, TypeError, ValueError, OverflowError) as exc:
        raise ObservedPairwiseError("finite canonical JSON snapshot required") from exc
    _validate(frozen)
    snapshot_sha = digest(frozen)
    if frozen["scope"] == "OPERATOR_SUPPLIED_RESEARCH":
        if not callable(allow_source):
            raise ObservedPairwiseError("research source analysis permission callback required")
        for source in frozen["sources"]:
            try:
                allowed = allow_source(source["source_url"], source["source_rights_ref"], "analysis")
            except Exception as exc:
                raise ObservedPairwiseError("source analysis permission callback failed") from exc
            if allowed is not True:
                raise ObservedPairwiseError("source analysis permission denied")
    spec = _spec()
    binding = {key: frozen[key] for key in ("scope", "race_id", "event_date_jst", "venue", "race_revision",
                                           "stage", "as_of", "sales_cutoff_at", "race_source_id")}
    binding.update(snapshot_sha256=snapshot_sha, model_spec_sha256=digest(spec))
    normalized, contrasts, coverage = _contrasts(frozen)
    results = {model_id: _model_result(model_id, normalized, coverage, binding) for model_id in MODEL_IDS}
    suite = {
        "schema": SUITE_SCHEMA, **binding, **_research_flags(),
        "model_spec": spec, "source_evidence": deepcopy(frozen["sources"]),
        "observations": sorted(deepcopy(frozen["participants"]), key=lambda row: row["lane"]),
        "coverage": coverage, "observed_contrasts": contrasts, "models": results,
        "limitations": [
            "Missing pairs are neutral assumptions and can advantage sparse entrants.",
            "Completion bounds cover missing domain values, not measurement error or calibrated confidence.",
            "Source rights callback permits analysis only; authenticity, independent timing and freeze are unverified.",
            "History windows and counts are supplied lineage claims, not independently verified membership.",
            "Stage labels do not establish physical exhibition chronology; neither stage rewrites another.",
            "Scores are untrained PL model weights, not calibrated accuracy or purchase advice.",
        ],
    }
    suite["suite_sha256"] = digest(suite)
    return suite
