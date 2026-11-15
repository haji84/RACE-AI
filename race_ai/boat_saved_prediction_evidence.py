"""Hydrate omitted native metadata beside immutable saved forecast bodies.

The caller supplies independently obtained GitHub ZIP bytes and actual metadata.
No source requests, inference, fitting, original rewrites or key exports occur.
Native as-of, explicit generation time and recorded computation completion are
different facts. An authenticated pre-cutoff original proves that its plan
existed then; it does not invent a missing generation timestamp.
"""
from collections import Counter
from copy import deepcopy
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
                generation_completed_no_later_than=completed), _roster(people)


def hydrate_prediction_evidence(view, archives, *, key=None):
    """Return ``(new_view, aggregate_counts)`` with separately bound evidence.

    ``archives`` contains exact ``(actual_github_zip_bytes, metadata_dict)``
    pairs. Authentication of the metadata's retrieval belongs to the caller.
    Existing evidence is append-only; conflicts and source mismatch stop intake.
    """
    from .saved_view_feed import forecast_inventory
    _need(type(view) is dict and type(view.get("records")) is list and len(view["records"]) <= 5000,
          "VIEW_INVALID")
    before = forecast_inventory(view)
    output = deepcopy(view)
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
            facts, roster = _native_facts(doc, entry, metadata)
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
        if evidence:
            row["saved_prediction_evidence"] = evidence
            for item in evidence.values():
                total["evidenced_predictions"] += 1
                total["exact_generation_clocks" if item["native"]["generated_at"] is not None else "native_asof_clocks"] += 1
                total["completion_upper_bounds"] += item["native"]["generation_completed_no_later_than"] is not None
    _need(forecast_inventory(output) == before, "ORIGINAL_INVENTORY_CHANGED")
    counts = dict(schema="RACE_AI_SAVED_PREDICTION_EVIDENCE_COUNTS_V1", authenticated_archives=len(originals),
                  saved_predictions=len(before), **{k:total[k] for k in ("evidenced_predictions", "exact_generation_clocks", "native_asof_clocks", "completion_upper_bounds")},
                  originals_unchanged=True, accuracy_improvement_proven=False, actual_purchases=False)
    return output, counts
