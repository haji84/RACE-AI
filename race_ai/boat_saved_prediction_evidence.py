"""Hydrate omitted native metadata beside immutable saved forecast bodies.

The caller supplies independently obtained GitHub ZIP bytes and actual metadata.
No source requests, inference, fitting, original rewrites or key exports occur.
Native as-of, explicit generation time and recorded computation completion are
different facts. An authenticated pre-cutoff original proves that its plan
existed then; it does not invent a missing generation timestamp.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import struct

from .actions_contract import digest
from .boat_private_original_archive import open_original_zip
from .boat_saved_model_view import saved_prediction_identity
from .frozen_day_cycle import check_clock, official_id, sealed, ts
from .private_cycle_projection import _native_entries, read_state_json

SCHEMA = "RACE_AI_SAVED_PREDICTION_EVIDENCE_V1"
COVERAGE_SCHEMA = "RACE_AI_SAVED_NATIVE_COVERAGE_V1"
REPOSITORY_ID = 1416489937


def _need(ok, reason):
    if not ok:
        raise ValueError("SAVED_PREDICTION_EVIDENCE_"+reason)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _content_tree(value):
    """Cross-language value binding; integer/float JSON spellings stay in digest.

    The independent full-original digest retains Python's original numeric
    spellings. This additional typed IEEE-754 binding is reproducible after a
    browser JSON parse, without duplicating any forecast in its evidence.
    """
    if value is None: return ["null"]
    if type(value) is bool: return ["boolean", value]
    if type(value) in (int, float): return ["number", struct.pack(">d", float(value)).hex()]
    if type(value) is str: return ["string", value]
    if type(value) is list: return ["array", [_content_tree(v) for v in value]]
    if type(value) is dict: return ["object", [[k, _content_tree(value[k])] for k in sorted(value)]]
    raise ValueError("SAVED_PREDICTION_EVIDENCE_CONTENT_INVALID")


def prediction_content_binding(prediction):
    return hashlib.sha256(_wire(_content_tree(prediction)).encode()).hexdigest()


def _clock_equal(a, b):
    return ts(a) == ts(b)


def _before_save(at, saved):
    # GitHub records whole seconds. Keep its established subsecond tolerance.
    from datetime import timedelta
    a, s = ts(at), ts(saved)
    return a <= s or s.microsecond == 0 and s <= a < s+timedelta(seconds=1)


def _roster(people):
    _need(type(people) is list and 3 <= len(people) <= 6, "ROSTER_INVALID")
    result = {}
    for person in people:
        lane = person.get("number", person.get("lane"))
        reg = person.get("registration_no", person.get("racer_id", person.get("racer_registration_id")))
        _need(type(lane) is int and 1 <= lane <= 6 and lane not in result and
              type(reg) is str and re.fullmatch(r"\d{4}", reg), "ROSTER_INVALID")
        result[lane] = reg
    _need(len(set(result.values())) == len(result), "ROSTER_INVALID")
    return result


def _read_archive(raw, metadata, key):
    _need(type(metadata) is dict and type(metadata.get("id")) is int and metadata["id"] > 0,
          "ARTIFACT_INVALID")
    run = metadata.get("workflow_run", {})
    _need(run.get("repository_id") == REPOSITORY_ID and run.get("head_repository_id") == REPOSITORY_ID and
          type(run.get("head_sha")) is str and re.fullmatch(r"[a-f0-9]{40}", run["head_sha"]),
          "ARTIFACT_SCOPE_INVALID")
    name = metadata.get("name", "")
    phase = "P0" if name.startswith("boat-p0-existing-") else "P1" if name.startswith("boat-national-cutoff-") else None
    _need(phase is not None, "ARTIFACT_PHASE_INVALID")
    member = "forecasts.json" if phase == "P0" else "national.json"
    with open_original_zip(raw, metadata, expected_kind=phase, key=key,
                           max_plain_zip_bytes=32*1024*1024) as archive:
        _need(archive.namelist() == [member], "ARTIFACT_LAYOUT_INVALID")
        body = archive.read(member)
    doc = read_state_json(body)
    schema = "RACE_AI_EXISTING_P0_DAY_V1" if phase == "P0" else "RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1"
    _need(doc.get("schema") == schema, "ARTIFACT_SCHEMA_INVALID")
    if phase == "P0":
        _need(doc.get("actual_purchases") is False and doc.get("race_count") == len(doc.get("predictions", [])) and
              doc.get("model_forecast_count") == sum(len(p.get("models", {})) for p in doc["predictions"]),
              "P0_COUNTS_INVALID")
    wrapped = dict(artifact_id=metadata["id"], member_name=member,
                   member_sha256=hashlib.sha256(body).hexdigest(), document=doc)
    entries = _native_entries([wrapped])
    _need(all(k[1] == phase for k in entries), "NATIVE_PHASE_INVALID")
    return doc, entries, wrapped


def _native_facts(doc, entry, metadata):
    model, parent = entry["model"], entry["parent"]
    stage, rid = entry["stage"], entry["race_id"]
    generated = model.get("generated_at", parent.get("generated_at"))
    completed = doc.get("completed_at")
    source_clocks = []
    if stage == "P0":
        from .observed_weight_learning import source_snapshot
        snapshot = source_snapshot(parent)
        people = snapshot["participants"]
        source_clocks = [s["captured_at"] for s in snapshot["sources"]]
        _need(parent.get("event_date_jst") == doc.get("day_jst") and official_id(parent["race_id"]) == rid,
              "P0_DAY_INVALID")
        source_sha = model.get("source_sha256")
    else:
        pairs = [p for p in doc.get("paired_forecasts", []) if p.get("race_id") == rid]
        _need(len(pairs) <= 1, "P1_PAIR_AMBIGUOUS")
        pair = pairs[0] if pairs else None
        if pair:
            sealed(pair, "bundle_sha256")
            check_clock(pair["generated_at"], pair["cutoff_at"], metadata["created_at"])
            source_clocks.append(pair["source_captured_at"])
        if parent.get("observations") is not None:
            people = parent["observations"]
            source_clocks += [s["captured_at"] for s in parent.get("source_evidence", [])]
        elif model.get("features") is not None:
            people = model["features"]
        else:
            shadow = [s for s in doc.get("additional_official_feature_shadows", []) if s.get("race_id") == rid and "bundle_sha256" in s]
            _need(len(shadow) == 1 and pair is not None, "P1_ROSTER_UNBOUND")
            sealed(shadow[0], "bundle_sha256")
            _need(shadow[0].get("source_snapshot_sha256") == pair.get("source_sha256"), "P1_SOURCE_UNBOUND")
            people = shadow[0]["features"]
        source_sha = model.get("source_sha256", entry.get("source_sha256"))
        # The unchanged observed adapter validates every exact source clock and
        # snapshot seal. Learned outputs must cite one such saved baseline.
        for bundle in doc.get("observed_pairwise_p1_bundles", []):
            if bundle.get("race_id") != rid: continue
            from .observed_p1_connection import verified_rows
            verified_rows(bundle, metadata, entry["member_sha256"])
            if pair:
                _need(bundle["base_source_sha256"] == pair["source_sha256"] and
                      _clock_equal(bundle["snapshot"]["as_of"], pair["generated_at"]), "P1_SOURCE_UNBOUND")
            if model.get("baseline_model_sha256"):
                base = bundle["suite"]["models"].get(model["model_id"])
                if base and base["prediction_sha256"] == model["baseline_model_sha256"]:
                    _need(model.get("input_sha256") == bundle["suite"]["snapshot_sha256"], "LEARNED_INPUT_UNBOUND")
                    people = bundle["snapshot"]["participants"]
        if model.get("baseline_model_sha256"):
            bases = [b["suite"]["models"].get(model["model_id"], {}) for b in doc.get("observed_pairwise_p1_bundles", [])
                     if b.get("race_id") == rid]
            _need(sum(b.get("prediction_sha256") == model["baseline_model_sha256"] for b in bases) == 1,
                  "LEARNED_BASELINE_UNBOUND")
    asof, cutoff, saved = entry["as_of"], entry["cutoff_at"], metadata["created_at"]
    check_clock(asof, cutoff, saved)
    _need(all(ts(at) <= ts(asof) for at in source_clocks), "SOURCE_CLOCK_INVALID")
    if generated is not None:
        _need(ts(asof) <= ts(generated) and _before_save(generated, saved), "GENERATION_CLOCK_INVALID")
    if completed is not None:
        _need(ts(asof) <= ts(completed) and _before_save(completed, saved) and
              (generated is None or ts(generated) <= ts(completed)), "COMPLETION_CLOCK_INVALID")
    return dict(model_id=model["model_id"], stage=stage, model_version=model.get("model_version"),
                prediction_sha256=model.get("prediction_sha256", model.get("model_sha256", model.get("bundle_sha256"))),
                input_sha256=model.get("input_sha256", model.get("snapshot_sha256", model.get("source_snapshot_sha256"))),
                source_sha256=source_sha, as_of=asof, cutoff_at=cutoff, generated_at=generated,
                generation_completed_no_later_than=completed), _roster(people), source_clocks


def _official_schedule(rows):
    """Validate the caller's separately authenticated official schedule ledger.

    A forecast's own cutoff is never an independent official schedule. The
    caller must authenticate these source SHA/capture bindings before intake.
    """
    _need(type(rows) is list and len(rows) <= 288, "OFFICIAL_SCHEDULE_INVALID")
    result = {}
    for row in rows:
        _need(type(row) is dict and set(row) == {
            "race_id", "cutoff_at", "schedule_captured_at", "source_sha256"}, "OFFICIAL_SCHEDULE_INVALID")
        rid = row["race_id"]
        _need(type(rid) is str and re.fullmatch(r"[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])", rid)
              and rid not in result and type(row["source_sha256"]) is str
              and re.fullmatch("[a-f0-9]{64}", row["source_sha256"]), "OFFICIAL_SCHEDULE_INVALID")
        cutoff, captured = ts(row["cutoff_at"]), ts(row["schedule_captured_at"])
        from .boat_observation_context import JST
        # A late first-P0 capture must retain already-closed races in the day
        # ledger. Their own native qualification still requires capture<=input.
        _need(cutoff.astimezone(JST).strftime("%Y%m%d") == rid[:8]
              and captured.astimezone(JST).strftime("%Y%m%d") == rid[:8],
              "OFFICIAL_SCHEDULE_CLOCK_INVALID")
        result[rid] = row
    return result


def _coverage_evidence(row, prediction, native, source_clocks, schedule, now):
    """Derive metadata beside a prediction; this never modifies its body."""
    _need(isinstance(now, datetime) and now.utcoffset() is not None, "COVERAGE_CLOCK_INVALID")
    _need(type(native) is dict and native.get("schema") == SCHEMA and
          native.get("verification_scope") == "AUTHENTICATED_NATIVE_ARTIFACT_IMPORT" and
          native.get("saved_prediction_identity") == saved_prediction_identity(prediction) and
          native.get("prediction_original_sha256") == digest(prediction) and
          native.get("prediction_binding_sha256") == prediction_content_binding(prediction),
          "COVERAGE_ORIGINAL_UNBOUND")
    facts, artifact = native["native"], native["artifact"]
    _need(facts["model_id"] == prediction["model_id"] and facts["stage"] == prediction["stage"] and
          facts["prediction_sha256"] == prediction.get("prediction_sha256", prediction.get("model_sha256")) and
          _clock_equal(facts["as_of"], prediction["as_of"]) and
          _clock_equal(facts["cutoff_at"], prediction["cutoff_at"]) and
          artifact["id"] == prediction["artifact_id"] and artifact["repository_id"] == REPOSITORY_ID and
          artifact["member_sha256"] == prediction["original_json_sha256"] and
          _clock_equal(artifact["created_at"], prediction["persisted_at"]) and
          type(artifact["run_id"]) is int and artifact["run_id"] > 0 and
          re.fullmatch("[a-f0-9]{40}", artifact["head_sha"]) and
          re.fullmatch("sha256:[a-f0-9]{64}", artifact["digest"]) and
          artifact["member"] == ("national.json" if prediction["stage"] == "P1" else "forecasts.json") and
          (prediction.get("source_code_commit") is None or prediction["source_code_commit"] == artifact["head_sha"]),
          "COVERAGE_NATIVE_UNBOUND")
    for field in ("generated_at", "source_sha256", "input_sha256", "model_version"):
        _need(prediction.get(field) is None or facts.get(field) is None or prediction[field] == facts[field],
              "COVERAGE_NATIVE_CONFLICT")
    _need(type(source_clocks) is list and all(type(at) is str and ts(at) <= ts(facts["as_of"])
                                            for at in source_clocks), "COVERAGE_SOURCE_CLOCK_INVALID")
    generated, asof, saved = facts["generated_at"], facts["as_of"], artifact["created_at"]
    if generated is not None:
        _need(ts(asof) <= ts(generated) and _before_save(generated, saved), "COVERAGE_GENERATION_CLOCK_INVALID")
    source_at = max(source_clocks, key=ts) if source_clocks else None
    reason = None
    if schedule is None:
        reason = "OFFICIAL_SCHEDULE_MISSING"
    elif row.get("cutoff_at") is None:
        reason = "ROW_OFFICIAL_CUTOFF_MISSING"
    elif (ts(schedule["cutoff_at"]) != ts(facts["cutoff_at"]) or
          ts(row["cutoff_at"]) != ts(schedule["cutoff_at"])):
        reason = "OFFICIAL_CUTOFF_CONFLICT"
    elif ts(schedule["schedule_captured_at"]) > ts(asof):
        reason = "OFFICIAL_SCHEDULE_AFTER_INPUT"
    elif generated is None:
        reason = "NATIVE_GENERATED_AT_MISSING"
    elif source_at is None or type(facts.get("source_sha256")) is not str or not re.fullmatch("[a-f0-9]{64}", facts["source_sha256"]):
        reason = "NATIVE_SOURCE_EVIDENCE_MISSING"
    elif max(ts(at) for at in (asof, generated, saved, source_at)) > now:
        reason = "NATIVE_CLOCK_IN_FUTURE"
    elif max(ts(at) for at in (asof, generated, saved, source_at)) >= ts(schedule["cutoff_at"]):
        reason = "NATIVE_NOT_PHYSICALLY_BEFORE_CUTOFF"
    elif prediction.get("eligible_pre_cutoff") is False:
        reason = "SAVED_PREDICTION_EXPLICITLY_INELIGIBLE"
    return dict(schema=COVERAGE_SCHEMA, native_evidence_sha256=digest(native),
                checked_at=now.isoformat(), official_schedule=deepcopy(schedule), source_capture_clocks=deepcopy(source_clocks),
                status="HOLD" if reason else "QUALIFIED_PRE_CUTOFF", reason=reason,
                model_id=facts["model_id"], stage=facts["stage"], as_of=asof, generated_at=generated,
                source_captured_at=source_at, source_sha256=facts.get("source_sha256"), server_saved_at=saved,
                cutoff_at=schedule["cutoff_at"] if schedule else None, artifact_id=artifact["id"],
                original_json_sha256=artifact["member_sha256"])


def native_coverage_evidence(row, prediction, *, now):
    """Read a separately bound AES-native coverage proof, or None when absent.

    Use only on an authenticated saved view. This validates the derivation and
    original binding; it cannot independently authenticate the view or sources.
    Missing genuine generation clocks remain HOLD even after their race ends.
    """
    identity = digest([row["race_id"], saved_prediction_identity(prediction)])
    values = row.get("saved_prediction_coverage", {})
    _need(type(values) is dict, "COVERAGE_INVALID")
    proof = values.get(identity)
    if proof is None: return None
    _need(type(proof) is dict and proof.get("schema") == COVERAGE_SCHEMA and
          isinstance(now, datetime) and now.utcoffset() is not None, "COVERAGE_INVALID")
    native = row.get("saved_prediction_evidence", {}).get(identity)
    _need(type(native) is dict and proof.get("native_evidence_sha256") == digest(native), "COVERAGE_EVIDENCE_UNBOUND")
    schedule = proof.get("official_schedule")
    if schedule is not None:
        _need(row["race_id"] in _official_schedule([schedule]), "COVERAGE_SCHEDULE_UNBOUND")
    checked = ts(proof["checked_at"])
    _need(checked <= now, "COVERAGE_CHECK_IN_FUTURE")
    expected = _coverage_evidence(row, prediction, native, proof.get("source_capture_clocks"), schedule, checked)
    _need(proof == expected, "COVERAGE_DERIVATION_CHANGED")
    return deepcopy(proof)


def hydrate_prediction_evidence(view, archives, *, key=None, official_schedule=None, now=None):
    """Return ``(new_view, aggregate_counts)`` with separately bound evidence.

    ``archives`` contains exact ``(actual_github_zip_bytes, metadata_dict)``
    pairs. Authentication of the metadata's retrieval belongs to the caller.
    Existing evidence is append-only; conflicts and source mismatch stop intake.
    An optional independently authenticated official schedule adds separate
    coverage evidence. Missing exact native clocks are recorded as HOLD.
    """
    from .saved_view_feed import forecast_inventory
    _need(type(view) is dict and type(view.get("records")) is list and len(view["records"]) <= 5000,
          "VIEW_INVALID")
    before = forecast_inventory(view)
    output = deepcopy(view)
    schedule = None if official_schedule is None else _official_schedule(official_schedule)
    if schedule is not None:
        _need(isinstance(now, datetime) and now.utcoffset() is not None, "COVERAGE_CLOCK_INVALID")
    originals = {}
    for raw, metadata in archives:
        doc, entries, wrapper = _read_archive(raw, metadata, key)
        ident = metadata["id"]
        value = (doc, entries, wrapper, metadata)
        _need(ident not in originals or originals[ident][2:] == value[2:], "ARTIFACT_ID_CONFLICT")
        originals[ident] = value
    total = Counter()
    for row in output["records"]:
        predictions = [p for p in [row.get("prediction"), *row.get("comparison_predictions", [])] if p is not None]
        evidence = row.get("saved_prediction_evidence", {})
        _need(type(evidence) is dict, "EXISTING_EVIDENCE_INVALID")
        identities = {digest([row["race_id"], saved_prediction_identity(p)]):p for p in predictions}
        _need(all(i in identities and e.get("prediction_original_sha256") == digest(identities[i]) and
                  e.get("prediction_binding_sha256") == prediction_content_binding(identities[i])
                  for i, e in evidence.items()), "EXISTING_EVIDENCE_UNBOUND")
        for identity, prediction in identities.items():
            original = originals.get(prediction.get("artifact_id"))
            if original is None: continue
            doc, entries, wrapper, metadata = original
            native = entries.get((row["race_id"], prediction["stage"], prediction["model_id"],
                                  prediction.get("prediction_sha256", prediction.get("model_sha256"))), [])
            _need(len(native) == 1, "NATIVE_ORIGINAL_NOT_FOUND")
            entry = native[0]
            _need(row.get("sport") == "boat" and prediction.get("original_json_sha256") == wrapper["member_sha256"] and
                  prediction.get("ordered_top8") == entry["top8"] and
                  _clock_equal(prediction["as_of"], entry["as_of"]) and
                  _clock_equal(prediction["cutoff_at"], entry["cutoff_at"]) and
                  _clock_equal(prediction["persisted_at"], metadata["created_at"]) and
                  (prediction.get("source_code_commit") is None or prediction["source_code_commit"] == metadata["workflow_run"]["head_sha"]),
                  "SAVED_ORIGINAL_UNBOUND")
            facts, roster, source_clocks = _native_facts(doc, entry, metadata)
            rosters = [row.get("participants", []), *[s.get("participants", []) for s in row.get("saved_participant_rosters", [])]]
            _need(any(_roster(people) == roster for people in rosters), "SAVED_ROSTER_UNBOUND")
            for field in ("model_version", "input_sha256", "source_sha256", "generated_at"):
                _need(prediction.get(field) is None or facts.get(field) is None or prediction[field] == facts[field],
                      "SAVED_METADATA_CONFLICT")
            current = dict(schema=SCHEMA, saved_prediction_identity=saved_prediction_identity(prediction),
                prediction_original_sha256=digest(prediction), prediction_binding_sha256=prediction_content_binding(prediction),
                verification_scope="AUTHENTICATED_NATIVE_ARTIFACT_IMPORT",
                artifact=dict(id=metadata["id"], digest=metadata["digest"], member=wrapper["member_name"],
                              member_sha256=wrapper["member_sha256"], created_at=metadata["created_at"],
                              run_id=metadata["workflow_run"]["id"], head_sha=metadata["workflow_run"]["head_sha"],
                              repository_id=REPOSITORY_ID), native=facts,
                clock_kind="EXACT_NATIVE_GENERATED_AT" if facts["generated_at"] is not None else
                           "NATIVE_ASOF_AND_COMPLETION_UPPER_BOUND" if facts["generation_completed_no_later_than"] is not None else
                           "NATIVE_ASOF_AND_PRE_CUTOFF_ORIGINAL")
            _need(identity not in evidence or evidence[identity] == current, "EXISTING_EVIDENCE_CONFLICT")
            evidence[identity] = current
            if schedule is not None:
                coverage = row.setdefault("saved_prediction_coverage", {})
                _need(type(coverage) is dict, "COVERAGE_INVALID")
                old = coverage.get(identity)
                checked = ts(old["checked_at"]) if old is not None else now
                proof = _coverage_evidence(row, prediction, current, source_clocks, schedule.get(row["race_id"]), checked)
                _need(old is None or old == proof, "EXISTING_COVERAGE_CONFLICT")
                coverage[identity] = proof
        if evidence:
            row["saved_prediction_evidence"] = evidence
            for item in evidence.values():
                total["evidenced_predictions"] += 1
                total["exact_generation_clocks" if item["native"]["generated_at"] is not None else "native_asof_clocks"] += 1
                total["completion_upper_bounds"] += item["native"]["generation_completed_no_later_than"] is not None
        if schedule is not None:
            _need(set(row.get("saved_prediction_coverage", {})) <= set(identities), "COVERAGE_ORIGINAL_MISSING")
            for prediction in predictions:
                proof = native_coverage_evidence(row, prediction, now=now)
                if proof is not None:
                    total["native_pre_cutoff_qualified" if proof["status"] == "QUALIFIED_PRE_CUTOFF" else "native_pre_cutoff_held"] += 1
    _need(forecast_inventory(output) == before, "ORIGINAL_INVENTORY_CHANGED")
    counts = dict(schema="RACE_AI_SAVED_PREDICTION_EVIDENCE_COUNTS_V1", authenticated_archives=len(originals),
                  saved_predictions=len(before), **{k:total[k] for k in ("evidenced_predictions", "exact_generation_clocks", "native_asof_clocks", "completion_upper_bounds")},
                  originals_unchanged=True, accuracy_improvement_proven=False, actual_purchases=False)
    if schedule is not None:
        counts.update({k:total[k] for k in ("native_pre_cutoff_qualified", "native_pre_cutoff_held")})
    return output, counts
