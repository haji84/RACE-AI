"""Pure private saved-cycle projection; no forecasts, rescoring, fetching or I/O.

The output is intentionally a separate partial research view, not audit V1.
Saved state integrity does not authenticate source rights or external receipts.
Missing metadata remains null, and source capture events remain observations,
never invented numbered official result revisions.
"""
from copy import deepcopy
from datetime import date, timezone, timedelta
import json
import math
import re

from .actions_contract import digest, stamp
from .boat_observed_pairwise_models import MODEL_IDS
from .frozen_day_cycle import check_clock, official_id

SCHEMA = "RACE_AI_PRIVATE_CYCLE_VIEW_V1"
INPUT_SCHEMAS = {"RACE_AI_RECOVERED_FIRST_RECEIPTS_V1", "RACE_AI_PRIVATE_ARTIFACT_READBACK_V1"}
MAX_BYTES = 32 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
RID = re.compile(r"(\d{4})(\d\d)(\d\d)-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
JST = timezone(timedelta(hours=9))
VIDEO_SHADOW_SCHEMA = "RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1"
VIDEO_SHADOW_VARIANT = "LEARNED_VIDEO_EXPERIMENTAL"
LEARNED_VARIANTS = frozenset(("LEARNED_SHADOW", VIDEO_SHADOW_VARIANT))


class PrivateCycleProjectionError(ValueError):
    """A rejected private record is described without echoing its contents."""


class _ResultObservationRejection(ValueError):
    """A fixed reason code for one structurally readable result observation."""


def _result_need(condition, reason):
    if not condition:
        raise _ResultObservationRejection(reason)


def _need(condition, reason):
    if not condition:
        raise PrivateCycleProjectionError("private saved cycle rejected: " + reason)


def _sha(value, *, optional=False):
    _need(optional and value is None or type(value) is str and SHA.fullmatch(value) is not None, "SHA format")


def _json_value(value, depth=0):
    _need(depth <= 64, "JSON depth")
    kind = type(value)
    if kind is dict:
        _need(all(type(k) is str for k in value), "JSON object keys")
        for child in value.values(): _json_value(child, depth + 1)
    elif kind is list:
        for child in value: _json_value(child, depth + 1)
    else:
        _need(kind in (str, int, float, bool, type(None)) and (kind is not float or math.isfinite(value)), "JSON value")


def read_state_json(raw):
    """Bounded strict JSON decoder usable by a local caller without file I/O."""
    _need(type(raw) in (str, bytes), "JSON bytes required")
    _need(len(raw) <= MAX_BYTES, "JSON size")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            _need(key not in out, "duplicate JSON key")
            out[key] = value
        return out
    try:
        out = json.loads(raw, object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(PrivateCycleProjectionError("private saved cycle rejected: nonfinite JSON")))
        _json_value(out)
        return out
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PrivateCycleProjectionError("private saved cycle rejected: JSON syntax") from exc


def _clone(value):
    _json_value(value)
    wire = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    _need(len(wire.encode("utf-8")) <= MAX_BYTES, "JSON size")
    return deepcopy(value)


def _label(value):
    _need(type(value) is str and 0 < len(value) <= 128 and value == value.strip(), "identity label")


def _ticket(value):
    return type(value) is list and len(value) == 3 and all(type(n) is int and 1 <= n <= 6 for n in value) and len(set(value)) == 3


def _ranking(top, ranked):
    _need(type(top) is list and len(top) == 8 and all(_ticket(t) for t in top), "Top8 format")
    _need(type(ranked) is list and len(ranked) == 120 and all(_ticket(t) for t in ranked), "ranking format")
    _need(len({tuple(t) for t in ranked}) == 120 and ranked[:8] == top, "ranking/Top8 mismatch")


def _race(value, day):
    match = RID.fullmatch(value) if type(value) is str else None
    _need(match is not None, "native race identity")
    y, m, d, venue, number = match.groups()
    event_day = f"{y}-{m}-{d}"
    _need(event_day == day and date.fromisoformat(event_day).isoformat() == day, "race day mismatch")
    return venue, int(number)


def _clock(value):
    try:
        return stamp(value)
    except (ValueError, TypeError) as exc:
        raise PrivateCycleProjectionError("private saved cycle rejected: timestamp") from exc


def _cutoff(value, day):
    clock = _clock(value)
    _need(clock.astimezone(JST).date().isoformat() == day, "cutoff day mismatch")
    return clock


def _seal(value, field):
    _need(type(value) is dict and field in value, "native seal missing")
    _sha(value[field])
    _need(value[field] == digest({k:v for k,v in value.items() if k != field}), "native seal mismatch")


def _native_entries(documents):
    """Index exact sealed native records; no model/replay function is called."""
    entries = {}
    _need(type(documents) is list and len(documents) <= 2000, "original document count")
    def add(model, parent, stage, hash_field, wrapper, *, source_sha=None):
        _seal(model, hash_field)
        mid = model.get("model_id"); _label(mid)
        rid = parent.get("race_id")
        if type(rid) is str and rid.startswith("boat:"):
            rid = official_id(rid)
        _need(stage in ("P0", "P1"), "native stage")
        cutoff = model.get("sales_cutoff_at", model.get("cutoff_at", parent.get("sales_cutoff_at", parent.get("cutoff_at"))))
        as_of = model.get("as_of", parent.get("as_of", parent.get("generated_at")))
        if "race_id" in model:
            model_rid = official_id(model["race_id"]) if model["race_id"].startswith("boat:") else model["race_id"]
            _need(model_rid == rid, "native model race binding")
        _need(model.get("stage", stage) == stage, "native model stage binding")
        if "ordered_top8" in model:
            top = model["ordered_top8"]
            ranked = [c["combination"] for c in model.get("candidates", [])]
            _need(all(type(c) is dict and type(c.get("score")) in (int,float) and c["score"] >= 0 for c in model.get("candidates", [])), "native candidate scores")
        else:
            def triples(rows):
                _need(type(rows) is list, "native ticket list")
                out = []
                for row in rows:
                    _need(type(row) is dict and type(row.get("ticket")) is str and re.fullmatch(r"[1-6]-[1-6]-[1-6]", row["ticket"]) is not None, "native ticket")
                    out.append([int(n) for n in row["ticket"].split("-")])
                return out
            top, ranked = triples(model.get("top8")), triples(model.get("full_120"))
        _ranking(top, ranked)
        data = dict(model=model, parent=parent, stage=stage, race_id=rid, cutoff_at=cutoff, as_of=as_of,
                    top8=top, ranked=ranked, source_sha256=source_sha,
                    artifact_id=wrapper.get("artifact_id"), member_sha256=wrapper.get("member_sha256"))
        entries.setdefault((rid, stage, mid, model[hash_field]), []).append(data)
    for supplied in documents:
        _need(type(supplied) is dict, "original document object")
        wrapper = supplied if "document" in supplied else {}
        doc = supplied.get("document", supplied)
        if wrapper:
            _need(type(wrapper.get("artifact_id")) is int and wrapper["artifact_id"] > 0, "original artifact identity")
            _sha(wrapper.get("member_sha256"))
            member = wrapper.get("member_name")
            if member in ("official-result-observations.json", "status.json", "trained_observed_models.json"):
                _need(type(doc) is (list if member == "official-result-observations.json" else dict), "nonforecast original shape")
                continue
        _need(type(doc) is dict, "native original document")
        schema = doc.get("schema")
        if schema == "RACE_AI_EXISTING_P0_DAY_V1":
            for suite in doc.get("predictions", []):
                _seal(suite, "suite_sha256")
                _need(suite.get("stage") == "P0", "native P0 stage")
                for mid, model in suite.get("models", {}).items():
                    _need(mid == model.get("model_id") and model.get("snapshot_sha256") == suite.get("snapshot_sha256") and model.get("as_of") == suite.get("as_of"), "native suite binding")
                    add(model, suite, "P0", "prediction_sha256", wrapper)
        elif schema == "RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1":
            for pair in doc.get("paired_forecasts", []):
                _seal(pair, "bundle_sha256")
                _sha(pair.get("source_sha256"))
                for model in pair.get("models", []):
                    add(model, pair, "P1", "model_sha256", wrapper, source_sha=pair["source_sha256"])
            for model in doc.get("additional_official_feature_shadows", []):
                if "bundle_sha256" in model:
                    add(model, model, "P1", "bundle_sha256", wrapper)
            for bundle in doc.get("observed_pairwise_p1_bundles", []):
                if "suite" not in bundle: continue
                _seal(bundle, "bundle_sha256"); suite = bundle["suite"]
                _seal(suite, "suite_sha256")
                _need(digest(bundle.get("snapshot")) == suite.get("snapshot_sha256"), "native observed snapshot binding")
                _need(official_id(suite["race_id"]) == bundle.get("race_id"), "native observed race binding")
                for mid, model in suite.get("models", {}).items():
                    _need(mid == model.get("model_id") and model.get("snapshot_sha256") == suite.get("snapshot_sha256"), "native observed model binding")
                    add(model, suite, "P1", "prediction_sha256", wrapper)
            for model in doc.get("learned_pairwise_shadows", []):
                add(model, model, model.get("stage"), "prediction_sha256", wrapper)
        else:
            _need(False, "unsupported original document schema")
    return entries


def _video_research(model):
    """Check saved experimental identity and limits, without authenticating video."""
    _need(model.get("variant") == VIDEO_SHADOW_VARIANT and model.get("model_id") in MODEL_IDS and
          model.get("model_version") == "0.3.0-VIDEO-EXPERIMENTAL", "video research identity")
    _need(all(model.get(field) is False for field in ("auto_promoted", "actual_purchases", "calibrated",
          "production_eligible", "independent_human_heldout_verified")) and
          model.get("raw_report_validation_status") == "UNVALIDATED" and
          model.get("performance_claim") == "NOT_A_PROSPECTIVE_ACCURACY_RESULT", "video research flags")
    _sha(model.get("video_context_sha256"))


def _saved_learned_rows(entries, baseline_rows, existing_shadows, receipts):
    """Preserve raw saved learned outputs without replaying their producer."""
    known = {(r.get("race_id"),r.get("stage"),r.get("model_id"),r.get("model_sha256")) for r in existing_shadows}
    known.update((r.get("race_id"),r.get("stage"),r.get("model_id"),r.get("model_sha256"))
                 for r in baseline_rows if r.get("variant") == VIDEO_SHADOW_VARIANT)
    baseline = {(r.get("race_id"),r.get("stage"),r.get("model_id"),r.get("model_sha256")):r for r in baseline_rows}
    by_receipt = {}
    _need(type(receipts) is list, "receipt metadata list")
    for receipt in receipts:
        _need(type(receipt) is dict and type(receipt.get("id")) is int, "receipt metadata identity")
        _need(receipt["id"] not in by_receipt or by_receipt[receipt["id"]] == receipt, "conflicting receipt metadata")
        by_receipt[receipt["id"]] = receipt
    added, unresolved = [], []
    for key, candidates in entries.items():
        native = candidates[0]; model = native["model"]
        if model.get("schema") not in ("RACE_AI_EXISTING_OBSERVED_LEARNED_SHADOW_V1", VIDEO_SHADOW_SCHEMA): continue
        is_video = model["schema"] == VIDEO_SHADOW_SCHEMA
        if is_video: _video_research(model)
        if key in known: continue
        base = baseline.get((*key[:3], model.get("baseline_model_sha256")))
        receipt = by_receipt.get(native["artifact_id"])
        if base is None or receipt is None or native["member_sha256"] is None:
            unresolved.append(dict(race_id=key[0],stage=key[1],model_id=key[2],prediction_sha256=key[3],
                                   reason="LEARNED_ORIGINAL_BASELINE_OR_RECEIPT_METADATA_MISSING"))
            continue
        _need(model.get("variant") == (VIDEO_SHADOW_VARIANT if is_video else "LEARNED_SHADOW") and model.get("auto_promoted") is False and
              model.get("actual_purchases") is False, "learned research flags")
        _sha(model.get("input_sha256")); _sha(model.get("training_sha256")); _label(model.get("model_version"))
        _need(_clock(native["as_of"]) == _clock(base["as_of"]) and
              _clock(native["cutoff_at"]) == _clock(base["cutoff_at"]), "learned baseline race/time mismatch")
        baselines = entries.get((*key[:3],base["model_sha256"]), [])
        for parent in baselines:
            source_hash = parent["model"].get("snapshot_sha256",parent["model"].get("input_sha256"))
            if source_hash is not None:
                _need(model["input_sha256"] == source_hash, "learned baseline snapshot mismatch")
        row = {k:deepcopy(v) for k,v in base.items() if k not in ("learning_snapshot","learning_snapshot_sha256")}
        if is_video:
            for field in ("generated_at", "source_sha256", "odds_independent"):
                row.pop(field, None)
        row.update(model_version=model["model_version"],variant=model["variant"],model_sha256=key[3],
                   input_sha256=model["input_sha256"],top8=deepcopy(native["top8"]),ranked=deepcopy(native["ranked"]),
                   artifact_id=native["artifact_id"],original_json_sha256=native["member_sha256"],
                   server_saved_at=receipt.get("created_at"),training_sha256=model["training_sha256"],
                   baseline_model_sha256=model["baseline_model_sha256"])
        if type(model.get("training_receipt")) is dict:
            row["training_artifact_id"] = model["training_receipt"].get("id")
            row["training_receipt_digest"] = model["training_receipt"].get("digest")
        added.append(row); known.add(key)
    return added, unresolved


def _prediction(row, entries):
    _need(type(row) is dict and row.get("sport") == "boat" and row.get("stage") in ("P0","P1"), "saved forecast identity")
    _label(row.get("model_id")); _sha(row.get("model_sha256")); _sha(row.get("original_json_sha256"))
    _need(type(row.get("artifact_id")) is int and row["artifact_id"] > 0, "artifact identity")
    _ranking(row.get("top8"), row.get("ranked"))
    _clock(row.get("as_of")); _clock(row.get("server_saved_at"))
    try:
        check_clock(row["as_of"], row["cutoff_at"], row["server_saved_at"])
    except (ValueError, TypeError) as exc:
        raise PrivateCycleProjectionError("private saved cycle rejected: forecast chronology") from exc
    roster = row.get("roster")
    _need(type(roster) is dict and set(roster) == set(map(str, range(1,7))) and
          all(type(v) is str and re.fullmatch(r"\d{4}",v) for v in roster.values()) and len(set(roster.values())) == 6, "saved roster")
    p = dict(model_id=row["model_id"], model_version=row.get("model_version"), stage=row["stage"],
             ordered_top8=deepcopy(row["top8"]), ordered_candidates=deepcopy(row["ranked"]),
             prediction_sha256=row["model_sha256"], input_sha256=row.get("input_sha256"), source_sha256=row.get("source_sha256"),
             as_of=row["as_of"], generated_at=row.get("generated_at"), source_captured_at=None, persisted_at=row["server_saved_at"],
             cutoff_at=row["cutoff_at"], odds_independent=row.get("odds_independent"), external_receipt_verified=False,
             source_provenance="OWNER_LOCAL_RECOVERED_CYCLE", missing_reasons=[])
    if row.get("learning_snapshot") is not None:
        _sha(row.get("learning_snapshot_sha256"))
        _need(digest(row["learning_snapshot"]) == row["learning_snapshot_sha256"], "saved learning snapshot hash")
        snapshot = row["learning_snapshot"]
        _need(type(snapshot) is dict and official_id(snapshot.get("race_id")) == row["race_id"] and
              snapshot.get("stage") == row["stage"] and _clock(snapshot.get("as_of")) == _clock(row["as_of"]) and
              _clock(snapshot.get("sales_cutoff_at")) == _clock(row["cutoff_at"]), "saved learning snapshot identity")
        _need(type(snapshot.get("participants")) is list and len(snapshot["participants"]) == 6 and
              {str(r.get("lane")):r.get("registration_no") for r in snapshot["participants"]} == roster,
              "saved learning snapshot roster")
        p["input_sha256"] = row["learning_snapshot_sha256"]
    key = (row["race_id"], row["stage"], row["model_id"], row["model_sha256"])
    native = entries.get(key, [])
    matches = [n for n in native if (n["artifact_id"] is None or n["artifact_id"] == row["artifact_id"]) and
               (n["member_sha256"] is None or n["member_sha256"] == row["original_json_sha256"]) and
               n["top8"] == row["top8"] and n["ranked"] == row["ranked"] and
               _clock(n["cutoff_at"]) == _clock(row["cutoff_at"]) and _clock(n["as_of"]) == _clock(row["as_of"])]
    _need(not native or matches, "native original lineage mismatch")
    if matches:
        native = matches[0]; model = native["model"]
        if model.get("schema") == VIDEO_SHADOW_SCHEMA:
            _video_research(model)
        enrichment = dict(model_version=model.get("model_version"), generated_at=model.get("generated_at", native["parent"].get("generated_at")),
                          source_captured_at=model.get("source_captured_at", native["parent"].get("source_captured_at")),
                          input_sha256=model.get("input_sha256", model.get("snapshot_sha256", model.get("source_snapshot_sha256"))),
                          source_sha256=model.get("source_sha256", native["source_sha256"]), odds_independent=model.get("odds_independent"))
        for field, value in enrichment.items():
            if value is not None:
                _need(p[field] is None or p[field] == value, "saved/native metadata conflict")
                p[field] = value
        if "candidates" in model: p["candidates"] = deepcopy(model["candidates"])
    for field in ("model_sha256","original_json_sha256","artifact_id","server_saved_at","variant","training_sha256",
                  "baseline_model_sha256","training_artifact_id","training_receipt_digest","calibrated"):
        if field in row: p[field] = deepcopy(row[field])
    if matches and model.get("schema") == VIDEO_SHADOW_SCHEMA:
        for field in ("variant", "training_sha256", "baseline_model_sha256", "video_context_sha256", "calibrated"):
            value = model[field]
            _need(field not in row or row[field] == value, "saved/native video metadata conflict")
            p[field] = deepcopy(value)
        receipt = model.get("training_receipt")
        if type(receipt) is dict:
            for field, key in (("training_artifact_id", "id"), ("training_receipt_digest", "digest")):
                _need(field not in row or row[field] == receipt.get(key), "saved/native video metadata conflict")
                p[field] = receipt.get(key)
    if p.get("variant") == VIDEO_SHADOW_VARIANT:
        # Saved JSON and local archive correlation cannot establish independent
        # video receipts, field validity, calibration or production readiness.
        p.update(calibrated=False, production_eligible=False, auto_promoted=False, actual_purchases=False,
                 raw_report_validation_status="UNVALIDATED", independent_human_heldout_verified=False,
                 video_context_receipt_verified=False, training_receipt_verified=False,
                 performance_claim="NOT_A_PROSPECTIVE_ACCURACY_RESULT")
        p["missing_reasons"].extend(("VIDEO_CONTEXT_RECEIPT_NOT_INDEPENDENTLY_VERIFIED",
                                     "VIDEO_FIELD_VALIDATION_NOT_PROVEN"))
    for field, reason in (("model_version","MODEL_VERSION_NOT_SAVED"),("generated_at","GENERATED_AT_NOT_SAVED"),
                          ("input_sha256","INPUT_SHA_NOT_SAVED"),("source_sha256","SOURCE_SHA_NOT_SAVED"),
                          ("odds_independent","ODDS_INDEPENDENCE_ASSERTION_NOT_SAVED")):
        if p[field] is None: p["missing_reasons"].append(reason)
    for field in ("input_sha256","source_sha256"): _sha(p[field], optional=True)
    if p["model_version"] is not None: _label(p["model_version"])
    if p["source_captured_at"] is not None:
        _clock(p["source_captured_at"])
    if p["generated_at"] is not None:
        try:
            # The unchanged archive reader admits subsecond generation inside
            # the artifact service's reported whole second. Preserve both exact
            # timestamps instead of rounding or fabricating a later receipt.
            check_clock(p["generated_at"], p["cutoff_at"], p["persisted_at"])
        except (ValueError, TypeError) as exc:
            raise PrivateCycleProjectionError("private saved cycle rejected: native generation chronology") from exc
    _need(p["odds_independent"] is None or type(p["odds_independent"]) is bool, "odds assertion format")
    p["missing_reasons"].append("EXTERNAL_RECEIPT_NOT_INDEPENDENTLY_VERIFIED")
    if p.get("variant") in LEARNED_VARIANTS:
        p["missing_reasons"].append("TRAINING_RECEIPT_NOT_INDEPENDENTLY_VERIFIED")
    return p, roster


def _observation(observation, row):
    _result_need(observation["race_id"] == row["race_id"], "RESULT_RACE_IDENTITY_MISMATCH")
    if "saved_observation_cutoff_variants" in row:
        _result_need(False, "RESULT_AMBIGUOUS_OBSERVATION_CUTOFF")
    _result_need(row["cutoff_at"] is not None,
                 "RESULT_AMBIGUOUS_FORECAST_CUTOFF" if row["saved_cutoff_variants"] else "RESULT_AMBIGUOUS_SCHEDULE_CUTOFF")
    _result_need(_clock(observation["closed_at"]) == _clock(row["cutoff_at"]), "RESULT_CUTOFF_MISMATCH")
    _result_need(_clock(observation["captured_at"]) >= _clock(row["cutoff_at"]), "RESULT_CAPTURE_BEFORE_CUTOFF")
    result = dict(status="pending", winning_combinations=[], confirmed_at=None, observed_at=observation["captured_at"],
                  official=False, source_sha256=observation.get("source_sha256"))
    data = observation.get("data")
    _result_need(observation.get("body_identity_verified") is True, "RESULT_IDENTITY_UNVERIFIED")
    if data is None: return result
    _need(type(data) is dict, "result payload")
    for field in ("refund_boats","refunds","refund_combinations","dead_heat"):
        if field in data: result[field] = deepcopy(data[field])
    refunds = data.get("refund_boats", [])
    _need(type(refunds) is list and all(type(n) is int and 1 <= n <= 6 for n in refunds) and len(set(refunds)) == len(refunds), "refund boats")
    records = data.get("results", [])
    _need(type(records) is list and all(type(r) is dict and type(r.get("lane")) is int for r in records), "result roster format")
    if records:
        roster = {str(r["lane"]):r.get("racer_registration_id") for r in records}
        _result_need(len(records) == 6 and set(roster) == set(map(str,range(1,7))) and len(roster) == len(records), "RESULT_ROSTER_LANES_MISMATCH")
        _result_need(all(type(pid) is str and re.fullmatch(r"\d{4}",pid) for pid in roster.values()) and
                     len(set(roster.values())) == 6, "RESULT_ROSTER_IDENTITY_MISMATCH")
        _result_need(all("race_id" not in r or r["race_id"] == row["race_id"] for r in records), "RESULT_RACE_IDENTITY_MISMATCH")
        _result_need(all("verified_official" not in r or r["verified_official"] is True for r in records), "RESULT_IDENTITY_UNVERIFIED")
        if row.get("participants"):
            _result_need(roster == {str(p["number"]):p["registration_no"] for p in row["participants"]}, "RESULT_ROSTER_MISMATCH")
    if observation.get("status") != "AVAILABLE": return result
    if data.get("confirmed") is True and data.get("status") in ("cancelled","no_contest"):
        result["status"] = "void"
        return result
    _need(type(data.get("payouts", [])) is list, "result payouts")
    payouts = [p for p in data.get("payouts", []) if type(p) is dict and p.get("bet_type") == "trifecta"]
    if data.get("status") == "settled" and data.get("confirmed") is True and data.get("finish_confirmed") is True and payouts:
        _result_need(records, "RESULT_ROSTER_MISSING")
        winners = []
        for payout in payouts:
            combo, amount = payout.get("combination"), payout.get("payout_per_100_yen")
            _result_need(_ticket(combo) and type(amount) is int and amount >= 0, "RESULT_PAYOUT_INVALID")
            winners.append(deepcopy(combo))
        _result_need(len({tuple(t) for t in winners}) == len(winners) and data.get("top3") in winners, "RESULT_WINNER_MISMATCH")
        _result_need(all(type(r.get("finish")) is int and 1 <= r["finish"] <= 6 or
                         r.get("finish") is None and r.get("finish_status") != "FINISHED" for r in records),
                     "RESULT_FINISH_ORDER_MISMATCH")
        finishes = {r["lane"]:r.get("finish") for r in records}
        places = [p for p in finishes.values() if p is not None]
        tied = data.get("dead_heat") is True
        _result_need(tied or len(set(places)) == len(places), "RESULT_FINISH_ORDER_MISMATCH")
        for winner in winners:
            order = [finishes[n] for n in winner]
            _result_need(all(r.get("finish_status") == "FINISHED" for r in records if r["lane"] in winner) and
                         all(type(p) is int for p in order), "RESULT_FINISH_ORDER_MISMATCH")
            _result_need(order == [1,2,3] if not tied else
                         order == sorted(order) and order[0] == 1 and order[-1] <= 3 and
                         all(n in winner for n,p in finishes.items() if p is not None and p < order[-1]),
                         "RESULT_FINISH_ORDER_MISMATCH")
        result.update(status="final", winning_combinations=winners)
        if len(payouts) == 1: result["payout_yen_per_100"] = payouts[0]["payout_per_100_yen"]
        else: result["payouts"] = deepcopy(payouts)
    return result


def project_state(state, *, dataset_status, original_documents=None):
    """Convert a pinned local recovery/readback object to a partial private UI view."""
    _need(dataset_status in ("REAL_REPORTED", "SYNTHETIC_ONLY"), "explicit dataset status required")
    state = _clone(state)
    _need(type(state) is dict and state.get("schema") in INPUT_SCHEMAS, "state schema")
    _sha(state.get("state_sha256"))
    _need(state["state_sha256"] == digest({k:v for k,v in state.items() if k != "state_sha256"}), "state hash mismatch")
    day = state.get("day_jst")
    _need(type(day) is str and date.fromisoformat(day).isoformat() == day, "state day")
    source_rows, shadows, observations = state.get("rows", []), state.get("learning_shadows", []), state.get("observations", [])
    _need(type(source_rows) is list and type(shadows) is list and len(source_rows)+len(shadows) <= 20000 and
          type(observations) is list and len(observations) <= 20000, "state record count")
    documents = state.get("original_documents", []) if original_documents is None else original_documents
    entries = _native_entries(_clone(documents))
    added_shadows, unresolved = _saved_learned_rows(entries, source_rows, shadows, state.get("receipts", []))
    shadows = shadows + added_shadows
    scope = "synthetic" if dataset_status == "SYNTHETIC_ONLY" else "research"
    records = {}
    def race(rid, cutoff, *, unknown_observation_cutoff=False):
        venue, number = _race(rid, day)
        if not unknown_observation_cutoff:
            _cutoff(cutoff, day)
        if rid in records:
            return records[rid]
        row = dict(race_id=rid, sport="boat", venue="場コード"+venue, race_no=number, event_date_jst=day,
                   cutoff_at=cutoff, saved_cutoff_variants=[], saved_schedule_cutoff_variants=[],
                   offering_status="UNKNOWN", scope=scope, source_provenance="OWNER_LOCAL_RECOVERED_CYCLE",
                   source_sha256=None, participants=[], prediction=None, comparison_predictions=[], result=None,
                   result_observations=[], result_observation_rejections=[], result_revisions=[], missing_reasons=[])
        records[rid] = row
        return row
    seen = set()
    for source in source_rows + shadows:
        _need(type(source) is dict, "saved forecast object")
        row = race(source.get("race_id"), source.get("cutoff_at"))
        identity = (source["race_id"], source.get("stage"), source.get("model_id"), source.get("model_version"), source.get("variant"))
        _need(identity not in seen, "duplicate saved forecast identity")
        seen.add(identity)
        prediction, roster = _prediction(source, entries)
        if prediction["cutoff_at"] not in row["saved_cutoff_variants"]:
            row["saved_cutoff_variants"].append(prediction["cutoff_at"])
        if len({_clock(c) for c in row["saved_cutoff_variants"]}) > 1:
            row["cutoff_at"] = None
            if "SAVED_FORECAST_CUTOFF_CONFLICT" not in row["missing_reasons"]:
                row["missing_reasons"].append("SAVED_FORECAST_CUTOFF_CONFLICT")
        participants = [dict(number=int(n), registration_no=pid) for n,pid in sorted(roster.items(), key=lambda item:int(item[0]))]
        _need(not row["participants"] or row["participants"] == participants, "one race roster conflict")
        row["participants"] = participants
        if row["prediction"] is None: row["prediction"] = prediction
        else: row["comparison_predictions"].append(prediction)
    schedule = state.get("schedule", [])
    cached = state.get("schedule_cache", {})
    _need(type(schedule) is list and type(cached) is dict, "schedule shape")
    registry = cached.get("official_race_registry", [])
    _need(type(registry) is list and len(schedule)+len(registry) <= 10000, "schedule count")
    for item in schedule + registry:
        _need(type(item) is dict, "schedule row")
        row = race(item.get("race_id"), item.get("cutoff_at"))
        cutoff = item["cutoff_at"]
        if cutoff not in row["saved_schedule_cutoff_variants"]:
            row["saved_schedule_cutoff_variants"].append(cutoff)
        known = row["saved_cutoff_variants"]
        if known:
            conflict = not any(_clock(c) == _clock(cutoff) for c in known)
        else:
            conflict = len({_clock(c) for c in row["saved_schedule_cutoff_variants"]}) > 1
            if conflict:
                row["cutoff_at"] = None
        if conflict and "SAVED_SCHEDULE_CUTOFF_CONFLICT" not in row["missing_reasons"]:
            row["missing_reasons"].append("SAVED_SCHEDULE_CUTOFF_CONFLICT")
    captures, observation_cutoffs = set(), {}
    for observation in observations:
        _need(type(observation) is dict, "result observation object")
        rid = observation.get("race_id"); _race(rid, day)
        _clock(observation.get("closed_at"))
        captured = _clock(observation.get("captured_at"))
        _sha(observation.get("source_sha256"), optional=True)
        _need(observation.get("data") is None or type(observation["data"]) is dict, "result payload")
        key = (rid, captured)
        _need(key not in captures, "duplicate result capture")
        captures.add(key)
        if rid not in records:
            variants = observation_cutoffs.setdefault(rid, [])
            if observation["closed_at"] not in variants:
                variants.append(observation["closed_at"])
    for rid, variants in observation_cutoffs.items():
        ambiguous = len({_clock(c) for c in variants}) > 1
        row = race(rid, None if ambiguous else variants[0], unknown_observation_cutoff=ambiguous)
        if ambiguous:
            row["saved_observation_cutoff_variants"] = variants
            row["missing_reasons"].append("SAVED_OBSERVATION_CUTOFF_CONFLICT")
    for observation in observations:
        # An observation cannot replace a forecast, schedule, or agreed observation clock.
        row = records[observation["race_id"]]
        row["result_observations"].append(deepcopy(observation))
        try:
            result = _observation(observation, row)
        except _ResultObservationRejection as exc:
            row["result_observation_rejections"].append(dict(captured_at=observation["captured_at"],
                source_sha256=observation.get("source_sha256"), reason=str(exc)))
            result = dict(status="unsupported", winning_combinations=[], confirmed_at=None,
                          observed_at=observation["captured_at"], official=False, source_sha256=observation.get("source_sha256"))
        if row["result"] is None or _clock(result["observed_at"]) > _clock(row["result"]["observed_at"]): row["result"] = result
    for row in records.values():
        if row["prediction"] is None: row["missing_reasons"].append("NO_SAVED_PREDICTION")
        if row["result"] is None: row["missing_reasons"].append("NO_SAVED_RESULT_OBSERVATION")
        if row["result_observation_rejections"]: row["missing_reasons"].append("RESULT_OBSERVATION_REJECTED")
        row["missing_reasons"].append("PRIVATE_IMPORT_NOT_INDEPENDENTLY_VERIFIED")
    _need(len(records) <= 10000, "race count")
    return dict(schema=SCHEMA, dataset_status=dataset_status, event_date_jst=day,
                source_state_sha256=state["state_sha256"], source_complete=state.get("complete"),
                coverage_scope=state.get("coverage_scope", "SAVED_STATE_ONLY_NOT_COMPLETE_RACE_DISCOVERY"),
                independent_receipt_verified=False, independent_source_verified=False,
                original_document_references=[{k:deepcopy(d[k]) for k in ("artifact_id","member_name","member_sha256")}
                    for d in documents if "document" in d],
                unresolved_learned_dependencies=deepcopy(state.get("unresolved_learned_dependencies", []))+unresolved,
                note="Private saved research view; missing metadata remains unknown; captures are not official revision numbers.",
                records=list(records.values()))
