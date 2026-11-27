"""Temporal, policy-specific set-coverage calibration for DT-R1 research.

``fit_calibrator(rows, split_manifest=..., lineage=..., config=None)`` fits a
binned monotonic isotonic map on calibration ONLY. Manifest entries fit/tune/
calibration/audit each contain inclusive ISO-date start/end; all four must be
strictly ordered. Lineage requires model_id, model_sha256 and policy_sha256;
optional input_schema_sha256 is enforced. Individual input_sha256 is required
on every row. Rows are selection summaries plus hit, day, field_size and class.
An optional result_at must be after cutoff_at; prospective rows require clocks.

``audit_calibrator(artifact, rows)`` returns a NEW sealed artifact, measuring the
frozen map on the independent later audit set. It never refits or chooses a map
from audit results. ``assess_selection(selection, artifact)`` returns n, Wilson
intervals, calibrated set probability and explicit fallback. It returns HOLD
without audit support; raw probability can never itself award a label.

Cells back off class+field -> field -> global, always retaining the SAME market,
actual ticket count and exact policy/model lineage. The level is chosen from
calibration support BEFORE examining audit performance. Thresholds are fixed at
90/80/60%; an upper label also requires its audit Wilson lower bound to meet that
threshold. Low labels require audit upper bound <60%. All CIs describe observed
set hit rates, not per-ticket probabilities. Sparse evidence and extrapolation
remain HOLD. Source authenticity and untouched-study claims require external
receipts; hashes here detect accidental artifact mutation, not adversarial data.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import math
from statistics import NormalDist

try:
    from .policy import (PolicyError, checked_day, checked_sha, check_race_day, clock, digest,
                         finite_number, probability, require)
except ImportError:  # Direct research-directory execution.
    from policy import (PolicyError, checked_day, checked_sha, check_race_day, clock, digest,
                        finite_number, probability, require)


THRESHOLDS = ((.90, "HOT", "激アツ"), (.80, "HIGH", "高"), (.60, "MEDIUM", "中"))


def wilson_interval(hits, n, confidence=.95):
    """Binomial Wilson interval; returns None when no observations exist."""
    require(isinstance(n, int) and not isinstance(n, bool) and n >= 0, "INVALID_SAMPLE_N")
    require(isinstance(hits, int) and not isinstance(hits, bool) and 0 <= hits <= n, "INVALID_HIT_COUNT")
    confidence = probability(confidence)
    require(0 < confidence < 1, "INVALID_CI_LEVEL")
    if not n:
        return None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = hits / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def _configuration(config):
    cfg = {"bins": 10, "min_calibration_n": 50, "min_audit_n": 100,
           "min_audit_days": 5, "confidence_level": .95, "max_calibration_error": .10,
           "prior_alpha": 1.0, "prior_beta": 1.0}
    if config is not None:
        require(isinstance(config, dict) and set(config) <= set(cfg), "INVALID_CALIBRATION_CONFIG")
        cfg.update(config)
    for key in ("bins", "min_calibration_n", "min_audit_n", "min_audit_days"):
        require(isinstance(cfg[key], int) and not isinstance(cfg[key], bool) and cfg[key] > 0, "INVALID_" + key.upper())
    require(cfg["bins"] <= 100, "TOO_MANY_CALIBRATION_BINS")
    require(0 < probability(cfg["confidence_level"]) < 1, "INVALID_CI_LEVEL")
    probability(cfg["max_calibration_error"])
    for key in ("prior_alpha", "prior_beta"):
        cfg[key] = finite_number(cfg[key])
        require(cfg[key] > 0, "INVALID_CALIBRATION_PRIOR")
    return cfg


def _manifest(manifest):
    require(isinstance(manifest, dict) and set(manifest) == {"fit", "tune", "calibration", "audit"}, "SPLIT_MANIFEST_REQUIRED")
    last = None
    out = {}
    for phase in ("fit", "tune", "calibration", "audit"):
        span = manifest[phase]
        require(isinstance(span, dict) and set(span) == {"start", "end"}, "INVALID_SPLIT_SPAN")
        start, end = checked_day(span["start"]), checked_day(span["end"])
        require(start <= end and (last is None or last < start), "TEMPORAL_SPLITS_OVERLAP")
        out[phase] = dict(span)
        last = end
    return out


def _lineage(lineage):
    require(isinstance(lineage, dict), "LINEAGE_REQUIRED")
    require(isinstance(lineage.get("model_id"), str) and bool(lineage["model_id"].strip()), "MODEL_ID_REQUIRED")
    for key in ("model_sha256", "policy_sha256"):
        checked_sha(lineage.get(key), "INVALID_" + key.upper())
    if lineage.get("input_schema_sha256") is not None:
        checked_sha(lineage["input_schema_sha256"])
    return {key: lineage[key] for key in ("model_id", "model_sha256", "policy_sha256", "input_schema_sha256") if key in lineage}


def _row(row, lineage, *, outcome=False):
    require(isinstance(row, dict), "INVALID_SELECTION_ROW")
    require(isinstance(row.get("race_id"), str) and bool(row["race_id"].strip()), "RACE_ID_REQUIRED")
    checked_day(row.get("day"))
    for key, expected in lineage.items():
        require(row.get(key) == expected, "LINEAGE_MISMATCH_" + key.upper())
    checked_sha(row.get("input_sha256"), "INVALID_INPUT_SHA256")
    if row.get("policy") is not None:
        require(digest(row["policy"]) == row["policy_sha256"], "POLICY_PAYLOAD_HASH_MISMATCH")
    require(row.get("cohort") in ("retrospective", "prospective"), "INVALID_COHORT")
    pred, cutoff = row.get("prediction_at"), row.get("cutoff_at")
    require((pred is None) == (cutoff is None), "PARTIAL_FORECAST_CLOCKS")
    if row["cohort"] == "prospective":
        require(pred is not None, "PROSPECTIVE_CLOCKS_REQUIRED")
    if pred is not None:
        require(clock(pred) < clock(cutoff), "PREDICTION_NOT_BEFORE_CUTOFF")
        check_race_day(row["day"], cutoff)
        if row.get("decision_at") is not None:
            require(clock(pred) <= clock(row["decision_at"]) < clock(cutoff), "SELECTION_CLOCK_ORDER")
    require(row.get("market") in ("trifecta", "exacta"), "INVALID_MARKET")
    count = row.get("ticket_count")
    require(isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= (12 if row["market"] == "trifecta" else 2), "INVALID_TICKET_COUNT")
    size = row.get("field_size")
    require(isinstance(size, int) and not isinstance(size, bool) and 3 <= size <= 9, "INVALID_FIELD_SIZE")
    require(isinstance(row.get("class"), str) and bool(row["class"].strip()), "CLASS_REQUIRED")
    raw = probability(row.get("raw_coverage"))
    require(row.get("status", "SELECTED") == "SELECTED", "SELECTION_NOT_SELECTED")
    if outcome:
        policy = row.get("policy", {})
        if policy.get("version") == "dt-r1-fixed-k-v1":
            possible = math.perm(size, 3 if row["market"] == "trifecta" else 2)
            require(count == min(policy["k"], possible), "FIXED_POLICY_TICKET_COUNT_MISMATCH")
        require(type(row.get("hit")) in (int, bool) and row["hit"] in (0, 1), "BINARY_HIT_REQUIRED")
        if row.get("result_at") is not None:
            require(cutoff is not None and clock(row["result_at"]) > clock(cutoff), "RESULT_CLOCK_ORDER")
        elif row["cohort"] == "prospective":
            raise PolicyError("PROSPECTIVE_RESULT_CLOCK_REQUIRED")
    return dict(row, raw_coverage=raw)


def _keys(row):
    base = [row["market"], row["ticket_count"]]
    return [("class_field", json_key(base + [row["field_size"], row["class"]])),
            ("field", json_key(base + [row["field_size"], None])),
            ("global", json_key(base + [None, None]))]


def json_key(parts):
    # Canonical JSON avoids delimiter collisions in externally supplied classes.
    import json
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _seal(artifact):
    out = {k: v for k, v in artifact.items() if k != "artifact_sha256"}
    return dict(out, artifact_sha256=digest(out))


def _check_artifact(artifact):
    require(isinstance(artifact, dict), "CALIBRATOR_REQUIRED")
    checked_sha(artifact.get("artifact_sha256"), "CALIBRATOR_HASH_REQUIRED")
    require(digest({k: v for k, v in artifact.items() if k != "artifact_sha256"}) == artifact["artifact_sha256"], "CALIBRATOR_HASH_MISMATCH")
    require(artifact.get("version") == "dt-r1-isotonic-coverage-v1", "UNSUPPORTED_CALIBRATOR")
    return artifact


def _checked_rows(rows, lineage, span, forbidden=()):
    require(isinstance(rows, list), "ROWS_MUST_BE_LIST")
    checked, seen = [], set(forbidden)
    for item in rows:
        row = _row(item, lineage, outcome=True)
        require(row["race_id"] not in seen, "DUPLICATE_OR_REUSED_RACE")
        seen.add(row["race_id"])
        require(span["start"] <= row["day"] <= span["end"], "ROW_OUTSIDE_TEMPORAL_SPLIT")
        if row.get("result_at") is not None:
            # A late result cannot be silently used by an earlier frozen stage.
            require(clock(row["result_at"]).date() <= checked_day(span["end"]), "RESULT_AFTER_SPLIT_FREEZE")
        checked.append(row)
    require(len({r["cohort"] for r in checked}) <= 1, "MIXED_CALIBRATION_COHORTS")
    return checked


def _isotonic(rows, cfg):
    bins = defaultdict(list)
    for row in rows:
        index = min(cfg["bins"] - 1, int(row["raw_coverage"] * cfg["bins"]))
        bins[index].append(row)
    blocks = []
    for index, members in sorted(bins.items()):
        hits, n = sum(int(r["hit"]) for r in members), len(members)
        block = {"left_bin": index, "right_bin": index, "n": n, "hits": hits,
                 "pseudo_hits": hits + cfg["prior_alpha"],
                 "pseudo_n": n + cfg["prior_alpha"] + cfg["prior_beta"],
                 "days": set(r["day"] for r in members)}
        blocks.append(block)
        while len(blocks) >= 2 and blocks[-2]["pseudo_hits"] / blocks[-2]["pseudo_n"] > blocks[-1]["pseudo_hits"] / blocks[-1]["pseudo_n"]:
            right, left = blocks.pop(), blocks.pop()
            blocks.append({"left_bin": left["left_bin"], "right_bin": right["right_bin"],
                           "n": left["n"] + right["n"], "hits": left["hits"] + right["hits"],
                           "pseudo_hits": left["pseudo_hits"] + right["pseudo_hits"],
                           "pseudo_n": left["pseudo_n"] + right["pseudo_n"],
                           "days": left["days"] | right["days"]})
    return [{"left_bin": b["left_bin"], "right_bin": b["right_bin"], "n": b["n"], "hits": b["hits"],
             "day_n": len(b["days"]), "probability": b["pseudo_hits"] / b["pseudo_n"],
             "ci": wilson_interval(b["hits"], b["n"], cfg["confidence_level"])} for b in blocks]


def fit_calibrator(rows, *, split_manifest, lineage, config=None):
    """Fit monotonic set coverage on the designated calibration interval only."""
    cfg, manifest, bound = _configuration(config), _manifest(split_manifest), _lineage(lineage)
    checked = _checked_rows(rows, bound, manifest["calibration"])
    cells = defaultdict(list)
    for row in checked:
        for _, key in _keys(row):
            cells[key].append(row)
    artifact = {
        "version": "dt-r1-isotonic-coverage-v1", "lineage": bound, "config": cfg,
        "split_manifest": manifest, "cohort": checked[0]["cohort"] if checked else None,
        "calibration_n": len(checked), "calibration_rows_sha256": digest(checked),
        "calibration_race_ids": sorted(r["race_id"] for r in checked),
        "cells": {key: _isotonic(members, cfg) for key, members in sorted(cells.items())},
        "status": "AWAITING_INDEPENDENT_AUDIT", "source_attested": False,
        "ci_method": "Wilson interval for empirical set coverage (independent Bernoulli assumption); prior-smoothed bins pooled by isotonic regression. Minimum day count does not correct within-day dependence.",
    }
    artifact["calibration_sha256"] = digest(artifact)
    return _seal(artifact)


def _block(artifact, key, raw):
    index = min(artifact["config"]["bins"] - 1, int(raw * artifact["config"]["bins"]))
    for number, block in enumerate(artifact["cells"].get(key, [])):
        if block["left_bin"] <= index <= block["right_bin"]:
            return number, block
    return None, None


def audit_calibrator(artifact, audit_rows):
    """Measure a frozen calibrator on the reserved audit set; never refit it."""
    original = _check_artifact(artifact)
    require("audit" not in original, "AUDIT_ALREADY_ATTACHED")
    rows = _checked_rows(audit_rows, original["lineage"], original["split_manifest"]["audit"], original["calibration_race_ids"])
    if rows and original["cohort"] is not None:
        require(rows[0]["cohort"] == original["cohort"], "AUDIT_COHORT_MISMATCH")
    buckets = defaultdict(list)
    for row in rows:
        for _, key in _keys(row):
            number, block = _block(original, key, row["raw_coverage"])
            if block is not None:
                buckets[(key, number)].append(row)
    evidence = {}
    for (key, number), members in sorted(buckets.items()):
        n, hits = len(members), sum(int(r["hit"]) for r in members)
        evidence.setdefault(key, {})[str(number)] = {
            "n": n, "hits": hits, "day_n": len({r["day"] for r in members}),
            "hit_rate": hits / n, "ci": wilson_interval(hits, n, original["config"]["confidence_level"]),
            "calibrated_probability": original["cells"][key][number]["probability"],
        }
    out = copy.deepcopy(original)
    out["audit"] = {"n": len(rows), "rows_sha256": digest(rows), "race_ids": sorted(r["race_id"] for r in rows),
                    "calibration_sha256": original["calibration_sha256"], "cells": evidence,
                    "cohort": rows[0]["cohort"] if rows else None, "refit": False}
    out["status"] = "AUDITED_SUPPORT_CHECK_REQUIRED_PER_SELECTION"
    return _seal(out)


def assess_selection(selection, artifact=None):
    """Return HOLD unless this exact policy/count/context has independent support."""
    require(isinstance(selection, dict), "INVALID_SELECTION")
    out = {"label": "HOLD", "display_label": "判定保留", "raw_coverage": selection.get("raw_coverage"),
           "calibrated_probability": None, "ticket_count": selection.get("ticket_count"),
           "calibration_n": 0, "calibration_ci": None, "audit_n": 0, "audit_ci": None,
           "fallback_level": None, "cell": None, "hold_reasons": [], "source_attested": False,
           "probability_scope": "selected_set_conditional_on_unique_normal_finish"}
    if artifact is None:
        out["hold_reasons"] = ["CALIBRATION_REQUIRED"]
        return out
    artifact = _check_artifact(artifact)
    row = _row(selection, artifact["lineage"])
    out["calibrator_sha256"] = artifact["artifact_sha256"]
    policy = row.get("policy", {})
    if policy.get("version") == "dt-r1-fixed-k-v1":
        possible = math.perm(row["field_size"], 3 if row["market"] == "trifecta" else 2)
        if row["ticket_count"] != min(policy["k"], possible):
            out["hold_reasons"] = ["FIXED_POLICY_TICKET_COUNT_MISMATCH"]
            return out
    if row["day"] <= artifact["split_manifest"]["audit"]["end"]:
        out["hold_reasons"].append("SELECTION_NOT_AFTER_AUDIT_PERIOD")
    seen = set(artifact["calibration_race_ids"]) | set(artifact.get("audit", {}).get("race_ids", []))
    if row["race_id"] in seen:
        out["hold_reasons"].append("IN_SAMPLE_SELECTION")
    if row.get("cohort") != artifact["cohort"] and artifact["cohort"] is not None:
        out["hold_reasons"].append("COHORT_TRANSFER_UNVALIDATED")
    chosen = None
    for level, key in _keys(row):
        number, block = _block(artifact, key, row["raw_coverage"])
        if block is not None and block["n"] >= artifact["config"]["min_calibration_n"]:
            chosen = level, key, number, block
            break
    if chosen is None:
        out["hold_reasons"].append("INSUFFICIENT_CALIBRATION_CELL_SUPPORT")
        return out
    level, key, number, block = chosen
    out.update(calibrated_probability=block["probability"], calibration_n=block["n"],
               calibration_ci=block["ci"], fallback_level=level, cell=key)
    if "audit" not in artifact:
        out["hold_reasons"].append("INDEPENDENT_AUDIT_REQUIRED")
        return out
    evidence = artifact["audit"]["cells"].get(key, {}).get(str(number))
    if evidence is None:
        out["hold_reasons"].append("INSUFFICIENT_AUDIT_CELL_SUPPORT")
        return out
    out.update(audit_n=evidence["n"], audit_ci=evidence["ci"], audit_hit_rate=evidence["hit_rate"], audit_day_n=evidence["day_n"])
    cfg = artifact["config"]
    if evidence["n"] < cfg["min_audit_n"] or evidence["day_n"] < cfg["min_audit_days"]:
        out["hold_reasons"].append("INSUFFICIENT_AUDIT_CELL_SUPPORT")
    if abs(evidence["hit_rate"] - block["probability"]) > cfg["max_calibration_error"]:
        out["hold_reasons"].append("AUDIT_CALIBRATION_ERROR")
    label, display, lower_threshold = "LOW", "低", None
    for threshold, candidate, candidate_display in THRESHOLDS:
        if block["probability"] >= threshold:
            label, display, lower_threshold = candidate, candidate_display, threshold
            break
    supported = (evidence["ci"][0] >= lower_threshold if lower_threshold is not None else evidence["ci"][1] < .60)
    if not supported:
        out["hold_reasons"].append("AUDIT_INTERVAL_DOES_NOT_SUPPORT_LABEL")
    if not out["hold_reasons"]:
        out.update(label=label, display_label=display)
    return out
