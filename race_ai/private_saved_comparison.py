"""Private, descriptive BOAT comparison of saved originals and saved results.

No fetching, I/O, prediction replay, fitting, ticket selection or promotion.
Local archive/member correlations do not authenticate timestamps or sources.
The supplied schedule is a declared scope, never proof of complete discovery.
"""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import re

from .actions_contract import digest
from .boat_observed_pairwise_models import MODEL_IDS
from .private_cycle_projection import (
    INPUT_SCHEMAS, LEARNED_VARIANTS, VIDEO_SHADOW_VARIANT, _clone, _clock, _cutoff, _label, _native_entries,
    _need, _prediction, _race, _saved_learned_rows, _sha, _ticket,
)
from .repeated_cycle import matches

SCHEMA = "RACE_AI_PRIVATE_SAVED_COMPARISON_V1"


def _configuration(comparison):
    _need(type(comparison) is dict and set(comparison) == {
        "comparison_id", "sport", "stage", "starts_at", "ends_at", "baseline", "learned"},
        "comparison columns")
    _label(comparison["comparison_id"])
    _need(comparison["sport"] in ("boat", "keirin", "autorace", "horse") and
          comparison["stage"] in ("P0", "P1"), "comparison sport/stage")
    _need(_clock(comparison["starts_at"]) < _clock(comparison["ends_at"]), "comparison window")
    for role in ("baseline", "learned"):
        pin = comparison[role]
        keys = {"model_id", "model_version"} | ({"training_sha256"} if role == "learned" else set())
        _need(type(pin) is dict and set(pin) == keys, "comparison version pins")
        _label(pin["model_id"]); _label(pin["model_version"])
    _sha(comparison["learned"]["training_sha256"])


def _receipts(items):
    _need(type(items) is list and len(items) <= 2000, "receipt count")
    by_id = {}
    for item in items:
        _need(type(item) is dict and type(item.get("id")) is int and item["id"] > 0, "receipt identity")
        old = by_id.setdefault(item["id"], item)
        _need(old == item, "conflicting receipt metadata")
    return by_id


def _receipt_valid(meta, artifact_id):
    if type(meta) is not dict or meta.get("id") != artifact_id or meta.get("expired") is not False:
        return False
    run = meta.get("workflow_run")
    if (type(run) is not dict or type(run.get("id")) is not int or run["id"] <= 0 or
            run.get("head_repository_id") != 1416489937 or
            type(meta.get("digest")) is not str or
            not re.fullmatch(r"sha256:[a-f0-9]{64}", meta.get("digest", ""))):
        return False
    try:
        _clock(meta["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _reference(document, meta):
    return dict(artifact_id=document["artifact_id"], member_name=document["member_name"],
                member_sha256=document["member_sha256"], saved_at=meta["created_at"],
                archive_digest=meta["digest"], independently_verified=False)


def _forecast_rows(state, documents, receipts):
    # Native extraction chooses its first occurrence. Sort by receipt before
    # extracting, independently of result contents and caller document order.
    def order(document):
        meta = receipts.get(document.get("artifact_id"), {})
        try:
            return (False, _clock(meta["created_at"]), document["artifact_id"])
        except (ValueError, TypeError, KeyError):
            return (True, None, document.get("artifact_id", 0))
    documents = sorted(documents, key=order)
    entries = _native_entries(documents)
    source = state.get("rows", [])
    _need(type(source) is list and len(source) <= 20000, "saved row count")
    learned, unresolved = _saved_learned_rows(entries, source, [], list(receipts.values()))
    rows = []
    for row in source + learned:
        prediction, roster = _prediction(row, entries)
        native = entries.get((row["race_id"], row["stage"], row["model_id"], row["model_sha256"]), [])
        native = [n for n in native if n["artifact_id"] == row["artifact_id"] and
                  n["member_sha256"] == row["original_json_sha256"]]
        meta = receipts.get(row["artifact_id"])
        bound = bool(native) and _receipt_valid(meta, row["artifact_id"])
        if bound:
            member = "forecasts.json" if row["stage"] == "P0" else "national.json"
            prefix = "boat-p0-existing-" if row["stage"] == "P0" else "boat-national-cutoff-"
            bound = (matches(meta.get("name"), prefix+str(meta["workflow_run"]["id"])) and
                     _clock(meta["created_at"]) == _clock(row["server_saved_at"]))
            if bound:
                prediction["original_reference"] = _reference(dict(artifact_id=row["artifact_id"],
                    member_name=member, member_sha256=row["original_json_sha256"]), meta)
        rows.append(dict(prediction=prediction, roster=roster, native=native[0]["model"] if native else None,
                         bound=bool(bound), race_id=row["race_id"]))
    return rows, unresolved


def _training(row, documents, receipts):
    """Check separately saved lineage; an embedded copy never supplies proof."""
    native = row["native"] or {}
    declared = native.get("training_receipt", {})
    if type(declared) is not dict:
        return "UNVERIFIED"
    ident = declared.get("id"); meta = receipts.get(ident)
    if not _receipt_valid(meta, ident) or declared != meta:
        return "UNVERIFIED"
    separate = [d for d in documents if d.get("artifact_id") == ident and
                d.get("member_name") == "trained_observed_models.json"]
    if not separate:
        return "UNVERIFIED"
    try:
        training = separate[0]["document"]
        _need(all(d["document"] == training for d in separate), "training originals conflict")
        _need(type(training) is dict and training.get("training_sha256") == native.get("training_sha256") ==
              digest({k:v for k,v in training.items() if k != "training_sha256"}), "training seal")
        is_video = native.get("variant") == VIDEO_SHADOW_VARIANT
        expected_schema = ("RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1" if is_video else
                           "RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1")
        expected_state = "FITTED_VIDEO_EXPERIMENTAL" if is_video else "FITTED_SHADOW_ONLY"
        _need(training == native.get("training") and
              training.get("schema") == expected_schema and
              training.get("state") == expected_state and training.get("auto_promoted") is False and
              training.get("accuracy_improvement_proven") is False, "training original binding")
        if is_video:
            from .observed_weight_learning import verify_training
            verify_training(training)
        created, saved, as_of = _clock(training["created_at"]), _clock(meta["created_at"]), _clock(native["as_of"])
        _need(created <= saved+timedelta(seconds=1) and saved < as_of and created < as_of and
              _clock(training["data_available_until"]) <= created, "training chronology")
        lineage = training["source_lineage"]
        _need(type(lineage) is list and lineage and all(type(r) is dict and
              r.get("race_id") != row["race_id"] and _clock(r["result_captured_at"]) <= created for r in lineage),
              "training lineage")
        _need(training["models"][native["model_id"]]["model_version"] == native["model_version"], "training version")
    except (ValueError, TypeError, KeyError, AttributeError):
        return "UNVERIFIED"
    return "SEPARATE_SAVED_TRAINING_CONSISTENT"


def _captures(state, documents, receipts, evaluated):
    events = state.get("observations", [])
    _need(type(events) is list and len(events) <= 20000, "saved capture count")
    supplied = [(event, None) for event in events]
    for document in documents:
        if document.get("member_name") == "official-result-observations.json":
            _need(type(document["document"]) is list and len(document["document"]) <= 20000, "result journal")
            supplied.extend((event, document) for event in document["document"])
    _need(len(supplied) <= 100000, "combined capture count")
    by_race = {}
    for event, document in supplied:
        _need(type(event) is dict, "result capture object")
        rid = event.get("race_id"); _label(rid)
        group = by_race.setdefault(rid, {})
        identity = digest(event)
        capture = group.setdefault(identity, dict(original=deepcopy(event), references=[], available_at_boundary=False))
        try:
            captured = _clock(event["captured_at"])
        except (ValueError, TypeError, KeyError):
            capture["invalid_timestamp"] = True
            continue
        if document is None:
            continue
        ident = document["artifact_id"]; meta = receipts.get(ident)
        if not _receipt_valid(meta, ident):
            continue
        if not matches(meta.get("name"), "race-existing-cycle-"+str(meta["workflow_run"]["id"])):
            continue
        saved = _clock(meta["created_at"])
        if captured > saved+timedelta(seconds=1):
            continue
        reference = _reference(document, meta)
        if reference not in capture["references"]:
            capture["references"].append(reference)
        if captured <= evaluated and saved <= evaluated:
            capture["available_at_boundary"] = True
    return {rid:list(group.values()) for rid,group in by_race.items()}


def _result(schedule, captures, selected_rows, evaluated):
    if any(c.get("invalid_timestamp") for c in captures):
        return "RESULT_REJECTED", None
    visible = [c for c in captures if _clock(c["original"]["captured_at"]) <= evaluated]
    if not visible:
        return "RESULT_PENDING", None
    latest = max(_clock(c["original"]["captured_at"]) for c in visible)
    last = [c for c in visible if _clock(c["original"]["captured_at"]) == latest]
    if len(last) != 1:
        return "RESULT_CAPTURE_CONFLICT", None
    capture = last[0]
    if not capture["references"]:
        return "RESULT_UNBOUND", None
    if not capture["available_at_boundary"]:
        return "RESULT_PENDING", None
    event = capture["original"]
    selected = dict(captured_at=event["captured_at"], source_sha256=event.get("source_sha256"),
                    references=deepcopy(capture["references"]), winning_combination=None)
    try:
        _need(event.get("body_identity_verified") is True and
              _clock(event["closed_at"]) == _clock(schedule["cutoff_at"]) <= _clock(event["captured_at"]), "result identity/time")
        _sha(event.get("source_sha256"))
        data = event.get("data")
        if event.get("status") != "AVAILABLE" or data is None:
            return "RESULT_PENDING", selected
        _need(type(data) is dict, "result data")
        if data.get("confirmed") is True and data.get("status") in ("cancelled", "no_contest"):
            return ("CANCELLED" if data["status"] == "cancelled" else "NO_CONTEST"), selected
        if data.get("finish_confirmed") is not True or data.get("confirmed") is not True or data.get("status") != "settled":
            return "RESULT_PENDING", selected
        results = data.get("results", [])
        _need(type(results) is list and 3<=len(results)<=6 and all(type(r) is dict and
              type(r.get("lane")) is int and re.fullmatch(r"\d{4}", r.get("racer_registration_id", "")) for r in results), "result roster")
        roster = {str(r["lane"]):r["racer_registration_id"] for r in results}
        active_references=[row for row in selected_rows if row is not None and len(row.get('roster',{}))<6]
        if type(schedule.get('roster')) is dict and len(schedule['roster'])<6:
            active_references.append(schedule)
        all_result_lanes={r['lane'] for r in results}
        if active_references:
            from .boat_active_roster import match_result_roster, result_roster_bindings
            proofs=[(row,result_roster_bindings(row,race_id=schedule['race_id'])) for row in active_references]
            known={}
            for _,(_,bindings,_) in proofs:
                _need(all(known[n]==pid for n,pid in bindings.items() if n in known),'conflicting saved result identities')
                known.update(bindings)
            _need(len(set(known.values()))==len(known),'conflicting saved registration lanes')
            reference=min(proofs,key=lambda item:(len(item[0]['roster']),-len(item[1][1])))[0]
            results=match_result_roster(reference,results,race_id=schedule['race_id'])
            _need(all(len(row['roster'])!=len(reference['roster']) or row['roster']==reference['roster']
                      for row in active_references),'conflicting active result references')
            roster={str(r['lane']):r['racer_registration_id'] for r in results}
        else:
            _need(len(results)==6 and set(roster) == set(map(str,range(1,7))) and len(set(roster.values())) == 6 and
                  all(row is None or row["roster"] == roster for row in selected_rows), "result/frozen roster")
        refunds = data.get("refund_boats", [])
        _need(type(refunds) is list and all(type(n) is int and 1 <= n <= 6 for n in refunds) and
              len(set(refunds)) == len(refunds), "refund format")
        if any(str(n) in roster or n not in all_result_lanes for n in refunds) or data.get("refunds") or data.get("refund_combinations"):
            return "REFUND_REVIEW_REQUIRED", selected
        if any(r.get("finish_status") != "FINISHED" for r in results):
            return "ABNORMAL_FINISH_REVIEW_REQUIRED", selected
        finishes = [r.get("finish") for r in results]
        _need(all(type(n) is int and 1 <= n <= len(results) for n in finishes), "normal finish positions")
        if len(set(finishes)) != len(results):
            return "SPECIAL_SETTLEMENT_REVIEW_REQUIRED", selected
        ordered = [r["lane"] for r in sorted(results, key=lambda r:r["finish"])]
        _need(_ticket(data.get("top3")) and data.get("top3") == ordered[:3], "finish order/top3 conflict")
        payouts = [p for p in data.get("payouts", []) if type(p) is dict and p.get("bet_type") == "trifecta"]
        if schedule.get("trifecta_offered") is False:
            _need(not payouts, "unoffered trifecta payout conflict")
            return "NO_TRIFECTA", selected
        if len(payouts) != 1 or data.get("dead_heat"):
            return "SPECIAL_SETTLEMENT_REVIEW_REQUIRED", selected
        winner = payouts[0].get("combination"); payout = payouts[0].get("payout_per_100_yen")
        _need(_ticket(winner) and data.get("top3") == winner and type(payout) is int and payout >= 0, "winner/payout")
        selected["winning_combination"] = deepcopy(winner)
        return "FINAL_NORMAL", selected
    except (ValueError, TypeError, KeyError, AttributeError):
        return "RESULT_REJECTED", selected


def evaluate_saved_comparison(state, *, schedule, comparison, evaluated_at, dataset_status):
    """Describe one pinned BOAT observed-family base/learned comparison.

    ``schedule`` is the full caller-declared list of race_id, sport, cutoff_at;
    optional trifecta_offered is boolean/null. The window is [start, end).
    Missing originals score zero ONLY for saved normal final eligible results.
    Unresolved/special outcomes have no hit value. All output stays private
    research, including when caller metadata claims external authentication.
    """
    state, schedule, comparison = _clone(state), _clone(schedule), _clone(comparison)
    _need(type(state) is dict and state.get("schema") in INPUT_SCHEMAS, "state schema")
    _need(state.get("state_sha256") == digest({k:v for k,v in state.items() if k != "state_sha256"}), "state seal")
    _need(dataset_status in ("REAL_REPORTED", "SYNTHETIC_ONLY"), "explicit dataset status")
    _configuration(comparison); evaluated = _clock(evaluated_at)
    _need(type(schedule) is list and len(schedule) <= 10000, "declared full schedule")
    ledger = []; seen = set()
    for slot in schedule:
        _need(type(slot) is dict and {"race_id","sport","cutoff_at"} <= set(slot) <=
              {"race_id","sport","cutoff_at","trifecta_offered"}, "schedule columns")
        _label(slot["race_id"])
        _need(slot["sport"] in ("boat", "keirin", "autorace", "horse") and
              (slot.get("trifecta_offered") is None or type(slot["trifecta_offered"]) is bool), "schedule sport/offering")
        key = (slot["sport"], slot["race_id"])
        _need(key not in seen, "duplicate scheduled race"); seen.add(key)
        cutoff = _clock(slot["cutoff_at"])
        if slot["sport"] == "boat":
            _race(slot["race_id"], state["day_jst"]); _cutoff(slot["cutoff_at"], state["day_jst"])
        if slot["sport"] == comparison["sport"] and _clock(comparison["starts_at"]) <= cutoff < _clock(comparison["ends_at"]):
            ledger.append(slot)
    report = dict(schema=SCHEMA, dataset_status=dataset_status, source_state_sha256=state["state_sha256"],
        comparison=comparison, evaluated_at=evaluated_at, status="RESEARCH_DESCRIPTIVE_ONLY", research_only=True,
        declared_scheduled_races=len(schedule), independent_receipts_verified=False, official_results_authenticated=False,
        schedule_completeness_proven=False, accuracy_improvement_proven=False, auto_promoted=False,
        official_hit_at_8_all=None, official_recovery_rate=None, actual_purchases=False,
        denominator=dict(declared_races_in_window=len(ledger), normal_final_eligible=0), models={},
        paired=dict(races=0, both_hit=0, baseline_only=0, learned_only=0, both_miss=0), races=[],
        scope_note="Caller-declared schedule and local saved originals only; no independent prospective or complete-day proof.")
    if comparison["sport"] != "boat":
        report["status"] = "UNSUPPORTED_SAVED_SPORT"
        return report
    if comparison["baseline"]["model_id"] not in MODEL_IDS or comparison["learned"]["model_id"] != comparison["baseline"]["model_id"]:
        report["status"] = "NO_SUPPORTED_EXISTING_LEARNED_FAMILY"
        return report
    documents = state.get("original_documents", [])
    _need(type(documents) is list and len(documents) <= 2000, "original document count")
    member_pins = {}
    for document in documents:
        _need(type(document) is dict and {"artifact_id","member_name","member_sha256","document"} <= set(document), "original wrapper")
        _need(type(document["artifact_id"]) is int and document["artifact_id"] > 0, "original artifact")
        _sha(document["member_sha256"])
        _need(document["member_name"] in ("forecasts.json", "national.json", "official-result-observations.json",
              "status.json", "trained_observed_models.json"), "original member name")
        if document["member_name"] in ("forecasts.json", "national.json"):
            expected = ("RACE_AI_EXISTING_P0_DAY_V1" if document["member_name"] == "forecasts.json" else
                        "RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1")
            _need(type(document["document"]) is dict and document["document"].get("schema") == expected,
                  "original member/schema binding")
        identity = (document["artifact_id"], document["member_name"])
        prior = member_pins.setdefault(identity, document)
        _need(prior["member_sha256"] == document["member_sha256"] and prior["document"] == document["document"],
              "conflicting original member pins")
    receipts = _receipts(state.get("receipts", []))
    rows, unresolved = _forecast_rows(state, documents, receipts)
    report["unresolved_learned_dependencies"] = deepcopy(unresolved)
    captures = _captures(state, documents, receipts, evaluated)
    for slot in sorted(ledger, key=lambda r:(_clock(r["cutoff_at"]), r["race_id"])):
        race = dict(race_id=slot["race_id"], cutoff_at=slot["cutoff_at"], same_conditions=False,
                    captures=deepcopy(captures.get(slot["race_id"], [])))
        selected = {}
        for role in ("baseline", "learned"):
            pin = comparison[role]
            candidates = [r for r in rows if r["race_id"] == slot["race_id"] and
                r["prediction"]["stage"] == comparison["stage"] and
                r["prediction"]["model_id"] == pin["model_id"] and
                r["prediction"]["model_version"] == pin["model_version"] and
                (r["prediction"].get("variant") in LEARNED_VARIANTS) == (role == "learned") and
                (role != "learned" or r["prediction"].get("training_sha256") == pin["training_sha256"]) and
                _clock(r["prediction"]["persisted_at"]) <= evaluated]
            candidates.sort(key=lambda r:(_clock(r["prediction"]["persisted_at"]),r["prediction"]["artifact_id"]))
            chosen = candidates[0] if candidates else None; selected[role] = chosen
            item = dict(state="NO_SAVED_PINNED_ORIGINAL", prediction=None, hit=None, counted_hit=None)
            if chosen is not None:
                _need(_clock(chosen["prediction"]["cutoff_at"]) == _clock(slot["cutoff_at"]), "schedule/forecast cutoff conflict")
                item.update(state="SAVED_ORIGINAL" if chosen["bound"] else "ORIGINAL_UNBOUND", prediction=deepcopy(chosen["prediction"]))
                if role == "learned":
                    item["training_state"] = _training(chosen, documents, receipts)
                    if item["training_state"] == "UNVERIFIED":
                        item["state"] = "TRAINING_UNVERIFIED"
                        if chosen["prediction"].get("variant") == VIDEO_SHADOW_VARIANT:
                            report["unresolved_learned_dependencies"].append(dict(race_id=slot["race_id"],
                                stage=comparison["stage"], model_id=pin["model_id"],
                                prediction_sha256=chosen["prediction"]["prediction_sha256"],
                                training_sha256=pin["training_sha256"],
                                reason="LEARNED_SEPARATE_TRAINING_OR_RECEIPT_UNVERIFIED"))
            race[role] = item
        base, learned = selected["baseline"], selected["learned"]
        if base is not None and learned is not None:
            a,b = base["prediction"],learned["prediction"]
            race["same_conditions"] = (b.get("baseline_model_sha256") == a["prediction_sha256"] and
                a.get("input_sha256") is not None and a["input_sha256"] == b.get("input_sha256") and
                base["roster"] == learned["roster"] and _clock(a["as_of"]) == _clock(b["as_of"]) and
                _clock(a["cutoff_at"]) == _clock(b["cutoff_at"]))
        result_state, result = _result(slot, race["captures"], list(selected.values()), evaluated)
        race.update(result_state=result_state, selected_result=result, eligible=result_state == "FINAL_NORMAL", paired=False)
        if race["eligible"]:
            for role in ("baseline", "learned"):
                item = race[role]
                if item["state"] == "SAVED_ORIGINAL":
                    item["hit"] = result["winning_combination"] in item["prediction"]["ordered_top8"]
                item["counted_hit"] = int(item["hit"] is True)
            race["paired"] = race["same_conditions"] and all(race[role]["hit"] is not None for role in ("baseline", "learned"))
            if race["paired"]:
                a,b = race["baseline"]["hit"],race["learned"]["hit"]
                key = "both_hit" if a and b else "baseline_only" if a else "learned_only" if b else "both_miss"
                report["paired"][key] += 1; report["paired"]["races"] += 1
        report["races"].append(race)
    eligible = [r for r in report["races"] if r["eligible"]]; n = len(eligible)
    report["denominator"].update(normal_final_eligible=n, result_state_counts=dict(Counter(r["result_state"] for r in report["races"])))
    for role in ("baseline", "learned"):
        hits = sum(r[role]["counted_hit"] for r in eligible)
        report["models"][role] = dict(**comparison[role], eligible_races=n, hits=hits,
            saved_normal_forecasts=sum(r[role]["hit"] is not None for r in eligible),
            missing_or_unverified_forecasts=sum(r[role]["hit"] is None for r in eligible),
            descriptive_hit_at_8_all=hits/n if n else None)
    return report
