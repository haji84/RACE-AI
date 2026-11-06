"""Private native-model execution from retained, source-bound BOAT inputs.

No transport, secret lookup, fitting, or independent receipt acquisition occurs
here. Runtime admission flags and normalized independently verified receipts
are supplied by the owner caller after authenticated restore/readback.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3

from .actions_contract import digest
from .boat_active_exhibition import SCHEMA as BEFORE_SCHEMA, _program
from .boat_observation_context import JST, _identity
from .boat_all_model_inputs import build_native_inputs
from .boat_history_store import HistoryStore, wire
from .boat_model_runtime import FILE_LIMITS, _validate_pointer as _validate_runtime_pointer
from .boat_pdca_recipient import _json as bounded_json
from .dispatch_product_projection import project_dispatch
from .existing_model_dispatch import dispatch, GROUPS, _native_hash, _bind
from .existing_model_coverage import catalog
from .observed_p1_connection import locator
from scripts.boat_history_collect import private_root, save

SCHEMA = "RACE_AI_BOAT_ALL_MODEL_ROUND_V1"
INPUT_SCHEMA = "RACE_AI_BOAT_RETAINED_NATIVE_INPUT_V1"
CAPSULE_SCHEMA = "RACE_AI_BOAT_FROZEN_NATIVE_DISPATCH_INPUT_V1"
MAX_NATIVE_CAPSULE_BYTES = 12 * 1024 * 1024
MAX_NATIVE_GROUP_BYTES = 2 * 1024 * 1024
REPO_ID = "1416489937"
REPO = "haji84/RACE-AI"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HEAD = re.compile(r"[a-f0-9]{40}\Z")
_KNOWN = {s["model_id"] for s in catalog()}


def _need(ok, reason):
    if not ok:
        raise ValueError("BOAT_ALL_MODEL_CYCLE_" + reason)


def _time(value):
    try:
        parsed = value if type(value) is datetime else datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(parsed.utcoffset() is not None, "AWARE_TIME_REQUIRED")
        return parsed
    except (ValueError, AttributeError, TypeError, OverflowError):
        raise ValueError("BOAT_ALL_MODEL_CYCLE_AWARE_TIME_REQUIRED") from None


def _clock(now):
    _need(type(now) is datetime and now.utcoffset() is not None, "EXPLICIT_AWARE_NOW_REQUIRED")
    return now


def _json_copy(value):
    # The native hashes seal canonical JSON. Normalize physical-lane dictionary
    # keys once at the storage boundary and verify through projection afterward.
    return json.loads(wire(value))


def _context(program, beforeinfo, as_of):
    asof = _time(as_of)
    _need(type(beforeinfo) is dict and beforeinfo.get("schema") == BEFORE_SCHEMA
          and beforeinfo.get("body_identity_verified") is True and beforeinfo.get("status") == "AVAILABLE"
          and beforeinfo.get("information_phase") == "pre_race", "OWNED_EXHIBITION_REQUIRED")
    active, rows, withdrawn = _program(program, beforeinfo.get("captured_at"))
    program_source = program.get("source", {})
    _need(program_source.get("source_url") == program["source_url"]
          and program_source.get("sha256") == program["source_sha256"]
          and _time(program_source.get("captured_at")) == _time(program["captured_at"]), "PROGRAM_SOURCE_BINDING_INVALID")
    rid, cutoff = program["race_id"], program["closed_at"]
    _need(beforeinfo.get("race_id") == rid and beforeinfo.get("closed_at") == cutoff
          and _identity(beforeinfo["source_url"], "beforeinfo") == _identity(program["source_url"], "racelist"), "SOURCE_RACE_OR_CUTOFF_MISMATCH")
    ctx = beforeinfo.get("context", {})
    source = ctx.get("source", {})
    _need(ctx.get("status") == "PARSED" and ctx.get("roster_binding_status") == "VERIFIED"
          and ctx.get("race_id") == rid and ctx.get("source_cutoff_at") == cutoff
          and source.get("source_url") == beforeinfo["source_url"]
          and source.get("sha256") == beforeinfo.get("source_sha256")
          and type(source.get("sha256")) is str and _SHA.fullmatch(source["sha256"])
          and _time(source.get("captured_at")) == _time(beforeinfo["captured_at"]), "EXHIBITION_SOURCE_BINDING_INVALID")
    _need(_time(program["captured_at"]) <= _time(beforeinfo["captured_at"]) <= asof, "SOURCE_AFTER_AS_OF")
    expected = {r["lane"]: r for r in active}
    measured = beforeinfo.get("data", {}).get("boats", [])
    extras = ctx.get("participants", [])
    supplemental = {r["lane"]: r for r in extras}
    _need(type(measured) is list and len(measured) == len(expected)
          and {r.get("lane") for r in measured} == set(expected)
          and len(extras) == len(expected) and set(supplemental) == set(expected)
          and beforeinfo.get("active_lanes") == sorted(expected)
          and beforeinfo.get("withdrawn_lanes") == withdrawn, "ACTIVE_EXHIBITION_ROSTER_INVALID")
    for row in measured:
        lane = row["lane"]; known = expected[lane]; extra = supplemental[lane]
        value = row.get("display_time")
        _need(row.get("racer_registration_id") == known["registration_number"] == extra.get("registration_number")
              and row.get("name") == extra.get("name")
              and type(value) in (int, float) and math.isfinite(value) and 4 <= value <= 12
              and value == extra.get("display_time") and row.get("tilt") == extra.get("tilt")
              and row.get("preview_st") == extra.get("exhibition_st")
              and row.get("preview_st_status") == ("PENDING" if extra.get("exhibition_st_status") == "NOT_PUBLISHED"
                                                     else extra.get("exhibition_st_status")), "EXHIBITION_VALUE_OR_IDENTITY_INVALID")
    _need(beforeinfo["data"].get("weather") == ctx.get("weather"), "WEATHER_BINDING_INVALID")
    current = dict(program=deepcopy(program), beforeinfo=deepcopy(beforeinfo), as_of=asof.isoformat())
    return current, active, [rows[n] for n in withdrawn]


def retain_current_input(program, beforeinfo, as_of, folder):
    """Retain the first immutable 0600 JSON for this race, outside Git.

    ``as_of`` is the supplied observation/dispatch clock, never a disk-save
    attestation. Physical availability must subsequently come from a receipt.
    """
    current, _, _ = _context(program, beforeinfo, as_of)
    _need(_time(current["as_of"]) < _time(program["closed_at"])
          and program.get("pre_cutoff_eligible") is True and beforeinfo.get("eligible_pre_race") is True, "INPUT_NOT_PRE_CUTOFF")
    supplied = Path(folder).absolute()
    _need(not any(p.is_symlink() for p in (supplied, *supplied.parents)), "PRIVATE_SYMLINK_REJECTED")
    record = dict(schema=INPUT_SCHEMA, **current, physical_save_time_attested=False)
    body = (wire(record) + "\n").encode()
    _need(len(body) <= 2 * 1024 * 1024, "CURRENT_INPUT_BOUND_INVALID")
    root = private_root(supplied)
    path = root / (program["race_id"] + ".json")
    if path.exists():
        _need(not path.is_symlink() and not path.stat().st_mode & 0o077, "PRIVATE_FILE_REQUIRED")
    save(path, body)
    return path


def _private_file(path, limit, *, read=True):
    _need(path is not None, "RUNTIME_FILE_REQUIRED")
    path = Path(path).absolute()
    _need(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file()
          and not path.stat().st_mode & 0o077 and not path.parent.stat().st_mode & 0o077
          and not any((p / ".git").exists() for p in path.parents)
          and 0 < path.stat().st_size <= limit, "PRIVATE_RUNTIME_FILE_REQUIRED")
    if not read:
        return path
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _need(0 < len(raw) <= limit, "RUNTIME_FILE_BOUND_INVALID")
    return raw


def _runtime(files, runtime_pointer=None):
    _need(type(files) is dict and all(files.get(k) is True for k in
          ("verified_runtime", "history_identity_verified", "owner_reviewed")), "TRUSTED_RESTORED_RUNTIME_REQUIRED")
    head = files.get("source_code_commit")
    _need(type(head) is str and _HEAD.fullmatch(head), "SOURCE_CODE_COMMIT_REQUIRED")
    history_path = _private_file(files.get("history.sqlite"), FILE_LIMITS["history.sqlite"], read=False)
    metadata = _private_file(files.get("metadata.json"), FILE_LIMITS["metadata.json"])
    _need(type(bounded_json(metadata, FILE_LIMITS["metadata.json"])) is dict, "RUNTIME_METADATA_INVALID")
    model = None
    if files.get("ranker.json") is not None:
        try:
            model = bounded_json(_private_file(files["ranker.json"], FILE_LIMITS["ranker.json"]), FILE_LIMITS["ranker.json"])
            if type(model) is not dict:
                model = None
        except (ValueError, OSError):
            model = None
    provenance = dict(source_code_commit=head, metadata_sha256=sha256(metadata).hexdigest(),
                      history_identity_verified=True, owner_reviewed=True)
    if runtime_pointer is not None:
        pointer = deepcopy(_validate_runtime_pointer(runtime_pointer))
        for name, expected in pointer['header']['files'].items():
            path = _private_file(files.get(name), FILE_LIMITS[name], read=False)
            actual = sha256(); size = 0
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    size += len(block)
                    _need(size <= FILE_LIMITS[name], 'RUNTIME_FILE_BOUND_INVALID')
                    actual.update(block)
            _need(dict(sha256=actual.hexdigest(), size=size) == expected, 'RUNTIME_POINTER_FILE_MISMATCH')
        provenance.update(runtime_pointer=pointer, runtime_pointer_sha256=digest(pointer),
                          runtime_cipher_sha256=pointer['cipher_sha256'])
    history = _ReadOnlyHistoryStore(history_path)
    return history, model, provenance


class _ReadOnlyHistoryStore(HistoryStore):
    """Use HistoryStore's genuine queries without its schema-writing opener.

    Restored bundles are complete standalone SQLite snapshots. Immutable read
    mode preserves their authenticated byte identity and forbids any reset.
    """
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA trusted_schema=OFF")
            self.db.execute("PRAGMA query_only=ON")
            _need(self.db.execute("PRAGMA user_version").fetchone()[0] in (0, 1)
                  and [row[1] for row in self.db.execute("PRAGMA table_info(imports)")] ==
                  ["id", "day", "available_at", "b_sha", "k_sha", "payload"], "HISTORY_SCHEMA_REQUIRED_NO_RESET")
        except Exception:
            self.db.close()
            raise
        self._cache = None
        self._validated_key = None

    def _selected(self, as_of):
        from .boat_entry_observations import HISTORY_SCHEMA, _source, _proof_hash
        values = super()._selected(as_of)
        if self._validated_key == self._cache[0]:
            return values
        for packet in values:
            _need(type(packet) is dict and type(packet.get("facts")) is list
                  and type(packet.get("history")) is dict, "HISTORY_PAYLOAD_INVALID")
            day = date.fromisoformat(packet["day"])
            history = packet["history"]; sources = history.get("source_proofs", {})
            _need(history.get("schema") == HISTORY_SCHEMA and history.get("date_jst") == packet["day"]
                  and set(sources) == {"B", "K"} and history.get("source_proofs_sha256") == _proof_hash(sources),
                  "HISTORY_SOURCE_PROOF_INVALID")
            for kind in ("B", "K"):
                _source(sources[kind], kind, day)
            available = max(_time(sources[k]["captured_at"]) for k in ("B", "K"))
            _need(_time(packet["available_at"]) == available, "HISTORY_AVAILABILITY_INVALID")
            bound = self.db.execute("SELECT b_sha,k_sha FROM imports WHERE day=? AND available_at=?",
                                    (packet["day"], packet["available_at"])).fetchall()
            _need(bound and all(tuple(row) == (sources["B"]["source_sha256"], sources["K"]["source_sha256"]) for row in bound),
                  "HISTORY_IMPORT_BINDING_INVALID")
            for fact in packet["facts"]:
                _need(fact.get("day") == packet["day"] and _time(fact["available_at"]) == available
                      and fact.get("source_sha256") == sources["K"]["source_sha256"]
                      and type(fact.get("racer_id")) is str and re.fullmatch(r"[0-9]{4}", fact["racer_id"])
                      and type(fact.get("lane")) is int and 1 <= fact["lane"] <= 6, "HISTORY_FACT_BINDING_INVALID")
        self._validated_key = self._cache[0]
        return values


def _receipt(value, expected_hash, head, run_id=None):
    fields = {"repository_id", "repository", "run_id", "head_sha", "artifact_id", "created_at", "payload_sha256", "independently_verified"}
    _need(type(value) is dict and set(value) == fields and value["repository_id"] == REPO_ID
          and value["repository"] == REPO and value["independently_verified"] is True
          and type(value["run_id"]) in (str, int) and re.fullmatch(r"[1-9][0-9]{0,19}", str(value["run_id"]))
          and type(value["artifact_id"]) is int and value["artifact_id"] > 0
          and value["head_sha"] == head and type(head) is str and _HEAD.fullmatch(head)
          and value["payload_sha256"] == expected_hash, "VERIFIED_RECEIPT_BINDING_REQUIRED")
    _need(run_id is None or str(value["run_id"]) == str(run_id), "RECEIPT_RUN_MISMATCH")
    _time(value["created_at"])
    return deepcopy(value)


def _not_before(earlier, saved):
    a, b = _time(earlier), _time(saved)
    return a <= b or b.microsecond == 0 and b <= a < b + timedelta(seconds=1)


def _originals(document, receipt, contexts, head, now):
    if document is None:
        _need(receipt is None, "BASELINE_DOCUMENT_REQUIRED")
        return [], None
    _need(document.get("schema") == "RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1", "BASELINE_SCHEMA_INVALID")
    proof = _receipt(receipt, digest(document), head)
    _need(_time(proof["created_at"]) <= now, "BASELINE_RECEIPT_IN_FUTURE")
    originals = []; parents = {}
    def add(prediction, rid, at, context=None, input_hash=None):
        current = contexts[rid]; cutoff = current["program"]["closed_at"]
        _need(_time(at) <= now and _not_before(at, proof["created_at"]), "BASELINE_SAVE_BEFORE_GENERATION")
        originals.append(dict(race_id=rid, sport="boat", stage="P1", cutoff_at=cutoff,
            model_id=prediction["model_id"], model_version=prediction.get("model_version"), prediction=deepcopy(prediction),
            prediction_sha256=_native_hash(prediction), output_sha256=digest(prediction), native_context=deepcopy(context),
            original_input_sha256=input_hash,
            scope="OPERATOR_SUPPLIED_RESEARCH", dispatch_generated_at=at, external_receipt_verified=False, official_prediction=False))
    for pair in document.get("paired_forecasts", []):
        rid = pair.get("race_id")
        if rid not in contexts:
            continue
        _native_hash(pair)
        current = contexts[rid]
        _need(pair["cutoff_at"] == current["program"]["closed_at"]
              and pair["program_source_sha256"] == current["program"]["source_sha256"]
              and pair["beforeinfo_source_sha256"] == current["beforeinfo"]["source_sha256"], "BASELINE_CURRENT_SOURCE_MISMATCH")
        parents[rid] = pair
        for prediction in pair["models"]:
            add(prediction, rid, pair["generated_at"], pair, pair["source_sha256"])
    for prediction in document.get("additional_official_feature_shadows", []):
        rid = prediction.get("race_id")
        if rid in parents and "bundle_sha256" in prediction:
            _need(prediction["source_snapshot_sha256"] == parents[rid]["source_sha256"], "BASELINE_C_SOURCE_MISMATCH")
            add(prediction, rid, prediction["as_of"], input_hash=prediction["source_snapshot_sha256"])
    for bundle in document.get("observed_pairwise_p1_bundles", []):
        rid = bundle.get("race_id")
        if rid not in parents or "suite" not in bundle:
            continue
        _native_hash(bundle)
        snap, suite = bundle["snapshot"], bundle["suite"]
        _need(suite["suite_sha256"] == digest({k: v for k, v in suite.items() if k != "suite_sha256"})
              and bundle["base_source_sha256"] == parents[rid]["source_sha256"]
              and suite["snapshot_sha256"] == digest(snap) and suite["observations"] == snap["participants"]
              and suite["source_evidence"] == snap["sources"] and snap["stage"] == "P1"
              and snap["sales_cutoff_at"] == parents[rid]["cutoff_at"], "BASELINE_OBSERVED_BINDING_INVALID")
        current = contexts[rid]
        active = {p["lane"]: p["racer_registration_id"] for p in current["program"]["boats"] if p["entry_status"] == "listed"}
        _need({p["lane"]: p["registration_no"] for p in snap["participants"]} == active
              and _time(snap["as_of"]) == _time(parents[rid]["generated_at"])
              and len(bundle.get("http_provenance", [])) >= 2 and len(snap["sources"]) >= 2, "BASELINE_OBSERVED_ROSTER_INVALID")
        for kind, source, http, actual in zip(("racelist", "beforeinfo"), snap["sources"][:2], bundle["http_provenance"][:2],
                                              (current["program"], current["beforeinfo"])):
            _need(http["request_url"] == actual["source_url"]
                  and source["source_url"] == locator(actual["source_url"], kind, rid)
                  and source["source_id"] == http["source_id"]
                  and source["source_sha256"] == http["source_sha256"] == actual["source_sha256"]
                  and _time(source["captured_at"]) == _time(http["captured_at"]) == _time(actual["captured_at"]),
                  "BASELINE_OBSERVED_HTTP_BINDING_INVALID")
        for prediction in suite["models"].values():
            _need(prediction.get("snapshot_sha256") == suite["snapshot_sha256"], "BASELINE_OBSERVED_MODEL_INPUT_INVALID")
            add(prediction, rid, snap["as_of"], input_hash=suite["snapshot_sha256"])
    return originals, dict(document_sha256=digest(document), receipt=proof)


def _schedule(current, active, withdrawn, stage="P1"):
    program = current["program"]
    return dict(race_id=program["race_id"], sport="boat", stage=stage, cutoff_at=program["closed_at"],
        venue="boatrace-jcd-" + program["venue"], race_no=int(program["race_id"][-2:]),
        participants=[dict(number=r["lane"], registration_no=r["registration_number"], name=r.get("name"), active=True) for r in active],
        withdrawn_participants=[dict(number=r["lane"], registration_no=r.get("racer_registration_id"), name=r.get("name"), active=False) for r in withdrawn],
        offering_status="UNKNOWN")


def _issued(value):
    _need(value is None or type(value) is dict, "ISSUED_MODELS_INVALID")
    out = {}
    for rid, mids in (value or {}).items():
        _need(type(rid) is str and type(mids) in (set, list, tuple) and set(mids) <= _KNOWN, "ISSUED_MODELS_INVALID")
        out[rid] = set(mids)
    return out


def _postprocess(report, issued, readiness, stage):
    for slot in report["slots"]:
        if slot["status"] in ("ORIGINAL_REUSED", "NOT_APPLICABLE"):
            continue
        if slot["model_id"] in issued:
            slot.update(status="RULE_FILTERED", reason="SAVED_ORIGINAL_RETAINED_IN_OWNER_FEED", prediction=None,
                        prediction_sha256=None, output_sha256=None, native_context=None, dispatch_generated_at=None)
        elif slot["model_id"] == "seller-shadow-v1-20261104" and stage == "P1":
            slot.update(status="RULE_FILTERED", reason="MODEL_P0_ONLY")
    report["status_counts"] = dict(Counter(s["status"] for s in report["slots"]))


def _native_capsule(schedule, native, clock, report, analysis_source_refs):
    capsule = dict(schema=CAPSULE_SCHEMA, race_id=schedule['race_id'], sport=schedule['sport'],
        stage=schedule['stage'], generated_at=clock.isoformat(), dispatch_input_sha256=report['input_sha256'],
        native_inputs=deepcopy(native), group_model_ids={g: list(dict(GROUPS)[g]) for g in native},
        native_payload_sha256={g: digest(p) for g, p in native.items()},
        analysis_source_refs=[list(pair) for pair in sorted(analysis_source_refs)])
    capsule['capsule_sha256'] = digest(capsule)
    return capsule


def verify_native_input_capsules(payload):
    """Return private frozen inputs after hash, identity and native output replay.

    Callers authenticate ciphertext and its external receipt first. Replaying
    the saved source pairs checks structural bindings; it grants no new source
    permission and does not attest any physical save clock. Older payloads
    without capsules remain readable and return an empty list.
    """
    return _verify_native_input_capsules(payload, replay_outputs=True)


def _verify_native_input_capsules(payload, *, replay_outputs):
    _need(type(payload) is dict and payload.get('schema') == SCHEMA, 'ROUND_SCHEMA_INVALID')
    if 'native_input_capsules' not in payload:
        return []
    from . import all_existing_model_registry as registry
    capsules = payload['native_input_capsules']; reports = payload.get('dispatch_reports')
    _need(type(capsules) is list and type(reports) is list and len(capsules) == len(reports) <= 288,
          'NATIVE_CAPSULE_COUNT_INVALID')
    _need(len(wire(capsules).encode()) <= MAX_NATIVE_CAPSULE_BYTES, 'NATIVE_CAPSULE_BOUND_INVALID')
    provenance = payload.get('runtime_provenance', {})
    _need(type(provenance) is dict and provenance.get('source_code_commit') == payload.get('source_code_commit'),
          'RUNTIME_PROVENANCE_HEAD_MISMATCH')
    if any(k in provenance for k in ('runtime_pointer', 'runtime_pointer_sha256', 'runtime_cipher_sha256')):
        pointer = _validate_runtime_pointer(provenance.get('runtime_pointer'))
        _need(provenance.get('runtime_pointer_sha256') == digest(pointer) and
              provenance.get('runtime_cipher_sha256') == pointer['cipher_sha256'] and
              provenance.get('metadata_sha256') == pointer['header']['files']['metadata.json']['sha256'],
              'RUNTIME_POINTER_BINDING_INVALID')
    fields = {'schema', 'race_id', 'sport', 'stage', 'generated_at', 'dispatch_input_sha256',
              'native_inputs', 'group_model_ids', 'native_payload_sha256', 'analysis_source_refs', 'capsule_sha256'}
    known = dict(GROUPS); seen = set()
    for capsule, report in zip(capsules, reports):
        _need(type(capsule) is dict and set(capsule) == fields and capsule['schema'] == CAPSULE_SCHEMA and
              capsule['capsule_sha256'] == digest({k: v for k, v in capsule.items() if k != 'capsule_sha256'}),
              'NATIVE_CAPSULE_HASH_INVALID')
        schedule = report.get('schedule')
        _need(type(schedule) is list and len(schedule) == 1, 'NATIVE_CAPSULE_SCHEDULE_INVALID')
        row = schedule[0]; key = (capsule['race_id'], capsule['stage'])
        _need(key not in seen and capsule['race_id'] == row['race_id'] and capsule['sport'] == row['sport'] == 'boat'
              and capsule['stage'] == row['stage'] == payload['stage'] and
              _time(capsule['generated_at']) == _time(report['as_of']) == _time(payload['generated_at']),
              'NATIVE_CAPSULE_IDENTITY_INVALID')
        seen.add(key); clock = _time(capsule['generated_at']); native = capsule['native_inputs']
        _need(type(native) is dict and set(native) <= set(known) and
              capsule['group_model_ids'] == {g: list(known[g]) for g in native} and
              capsule['native_payload_sha256'] == {g: digest(p) for g, p in native.items()},
              'NATIVE_CAPSULE_GROUP_BINDING_INVALID')
        inputs = {row['race_id']: {row['stage']: native}}
        _need(capsule['dispatch_input_sha256'] == report['input_sha256'] == digest(inputs),
              'NATIVE_CAPSULE_DISPATCH_HASH_INVALID')
        source_refs = capsule['analysis_source_refs']
        _need(type(source_refs) is list and len(source_refs) <= 4096 and all(
              type(pair) is list and len(pair) == 2 and all(type(v) is str and 0 < len(v) <= 4096 for v in pair)
              for pair in source_refs), 'NATIVE_CAPSULE_SOURCE_SCOPE_INVALID')
        refs = {tuple(pair) for pair in source_refs}
        _need(source_refs == [list(pair) for pair in sorted(refs)], 'NATIVE_CAPSULE_SOURCE_SCOPE_INVALID')
        allow = lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in refs
        roster = {str(p['number']): p['registration_no'] for p in row['participants'] if p.get('active') is True}
        for group, value in native.items():
            _need(type(value) is dict and len(wire(value).encode()) <= MAX_NATIVE_GROUP_BYTES,
                  'NATIVE_CAPSULE_GROUP_BOUND_INVALID')
            _bind(group, value, row, clock)
            for mid in known[group]:
                info = registry.validate_payload(mid, row['sport'], value, at=clock, allow_source=allow)
                _need(info['roster'] == roster and _time(info['race_cutoff_at']) == _time(row['cutoff_at']),
                      'NATIVE_CAPSULE_ROSTER_OR_CUTOFF_MISMATCH')
        if not replay_outputs:
            continue
        replay = _json_copy(dispatch(schedule, inputs, now=clock, allow_source=allow,
                                    originals=report.get('retained_originals', [])))
        _need(replay['native_invocations'] == report['native_invocations'], 'NATIVE_CAPSULE_INVOCATION_REPLAY_MISMATCH')
        by_model = {(s['model_id'], s.get('model_version')): s for s in replay['slots']}
        for slot in report['slots']:
            if slot['status'] not in ('GENERATED_UNATTESTED', 'ORIGINAL_REUSED'):
                continue
            actual = by_model.get((slot['model_id'], slot.get('model_version')))
            _need(actual is not None and actual['status'] == slot['status'] and
                  all(actual.get(k) == slot.get(k) for k in ('prediction', 'prediction_sha256', 'output_sha256', 'native_context')),
                  'NATIVE_CAPSULE_PREDICTION_REPLAY_MISMATCH')
    return deepcopy(capsules)


def forecast_round(contexts, runtime_files, *, now, baseline_document=None, baseline_receipt=None, issued_models=None,
                   runtime_pointer=None):
    """Run each ready P1 family once; reuse baseline originals and issued slots."""
    clock = _clock(now)
    _need(type(contexts) is list and len(contexts) <= 288, "BOUNDED_CONTEXTS_REQUIRED")
    current = {}; schedules = {}
    for supplied in contexts:
        item, active, withdrawn = _context(supplied["program"], supplied["beforeinfo"], supplied["as_of"])
        rid = item["program"]["race_id"]
        _need(rid not in current and _time(item["as_of"]) <= clock, "DUPLICATE_OR_FUTURE_CONTEXT")
        current[rid] = item; schedules[rid] = _schedule(item, active, withdrawn)
    history, fitted, provenance = _runtime(runtime_files, runtime_pointer)
    try:
        originals, baseline = _originals(baseline_document, baseline_receipt, current, provenance["source_code_commit"], clock)
        issued = _issued(issued_models); reports = []; readiness_rows = []; skipped = []; capsules = []
        for rid, item in current.items():
            own_originals = [p for p in originals if p["race_id"] == rid]
            saved = issued.get(rid, set()) | {p["model_id"] for p in own_originals}
            cutoff = _time(item["program"]["closed_at"])
            eligible = (item["program"].get("pre_cutoff_eligible") is True
                        and item["beforeinfo"].get("eligible_pre_race") is True
                        and _time(item["as_of"]) < cutoff)
            native = {}; readiness = {}; refs = set()
            if clock >= cutoff or not eligible:
                skipped.append(dict(race_id=rid, reason="AT_OR_AFTER_CUTOFF" if clock >= cutoff else "SOURCE_NOT_PRE_CUTOFF_ELIGIBLE"))
            else:
                built = build_native_inputs(item["program"], item["beforeinfo"], as_of=item["as_of"],
                    history_context=dict(history_store=history, history_identity_verified=True, owner_reviewed=True), fitted_model=fitted)
                native = built["native_inputs"]; readiness = built["readiness"]
                def admit(evidence):
                    for e in evidence:
                        _need(type(e) is dict and type(e.get("source_sha256")) is str and _SHA.fullmatch(e["source_sha256"]), "SOURCE_EVIDENCE_INVALID")
                        refs.add((e["source_ref"], e["source_rights_ref"]))
                        if e.get("source_members"):
                            admit(e["source_members"])
                admit(built["source_evidence"])
                for group, mids in GROUPS:
                    if set(mids) <= saved:
                        native.pop(group, None)
                        readiness[group] = dict(state="RULE_FILTERED", reasons=["SAVED_ORIGINAL_RETAINED_IN_OWNER_FEED"])
            report = dispatch([schedules[rid]], {rid: {"P1": native}}, now=clock,
                              allow_source=lambda ref, rights, purpose: purpose == "analysis" and (ref, rights) in refs,
                              originals=own_originals)
            report["schedule"] = [schedules[rid]]
            _postprocess(report, issued.get(rid, set()), readiness, "P1")
            capsules.append(_native_capsule(schedules[rid], native, clock, report, refs))
            reports.append(report); readiness_rows.append(dict(race_id=rid, stage="P1", groups=readiness))
        payload = dict(schema=SCHEMA, stage="P1", generated_at=clock.isoformat(), as_of=clock.isoformat(),
            source_code_commit=provenance["source_code_commit"], run_id=runtime_files.get("run_id"),
            runtime_provenance=provenance, current_inputs=list(current.values()), dispatch_reports=reports,
            model_readiness=readiness_rows, skipped_contexts=skipped, baseline=baseline, native_input_capsules=capsules,
            summary=dict(contexts=len(contexts), generated_forecasts=sum(s["status"] == "GENERATED_UNATTESTED" for r in reports for s in r["slots"]),
                         reused_baseline_forecasts=sum(s["status"] == "ORIGINAL_REUSED" for r in reports for s in r["slots"])),
            source_requests=0, originals_overwritten=False)
        payload = _json_copy(payload)
        _verify_native_input_capsules(payload, replay_outputs=False)
        return payload
    finally:
        history.close()


def project_round(payload, receipt):
    """Project saved outputs using independently supplied real physical clocks."""
    _need(type(payload) is dict and payload.get("schema") == SCHEMA and payload.get("source_requests") == 0
          and payload.get("originals_overwritten") is False, "ROUND_SCHEMA_INVALID")
    current_receipt = _receipt(receipt, digest(payload), payload["source_code_commit"], payload.get("run_id"))
    _need(_not_before(payload["generated_at"], current_receipt["created_at"]), "RECEIPT_BEFORE_DISPATCH")
    verify_native_input_capsules(payload)
    baseline = payload.get("baseline")
    prior_receipt = (_receipt(baseline["receipt"], baseline["document_sha256"], baseline["receipt"]["head_sha"])
                     if baseline is not None else None)
    records = []; by_id = {c["program"]["race_id"]: c for c in payload.get("current_inputs", [])}
    for report in payload["dispatch_reports"]:
        view = project_dispatch(report, dataset_status="REAL_REPORTED")
        slots = {(s["race_id"], s["model_id"], s.get("model_version")): s for s in report["slots"]}
        for row in view["records"]:
            ctx = by_id.get(row["race_id"])
            bindings = (dict(program_sha256=ctx["program"]["source_sha256"], beforeinfo_sha256=ctx["beforeinfo"]["source_sha256"],
                             program_url=ctx["program"]["source_url"], beforeinfo_url=ctx["beforeinfo"]["source_url"])
                        if ctx else deepcopy(payload.get("input_origins", {}).get(row["race_id"], {})))
            row["withdrawn_participants"] = deepcopy(report["schedule"][0].get("withdrawn_participants", []))
            row["missing_reasons"] = [reason for reason in row["missing_reasons"] if reason != "INDEPENDENT_RECEIPT_NOT_VERIFIED"]
            row.update(external_receipt_verified=True, source_provenance=deepcopy(bindings), source_sha256=digest(bindings))
            for p in ([row["prediction"]] if row["prediction"] else []) + row["comparison_predictions"]:
                slot = slots[row["race_id"], p["model_id"], p.get("model_version")]
                reused = slot["status"] == "ORIGINAL_REUSED"
                proof = prior_receipt if reused else current_receipt
                _need(proof is not None, "ORIGINAL_RECEIPT_REQUIRED")
                generated = p.get("generated_at") or slot.get("dispatch_generated_at")
                asof = p.get("as_of") or (slot.get("dispatch_generated_at") if reused else
                                           ctx["as_of"] if ctx else report["as_of"])
                _need(generated is not None and _not_before(generated, proof["created_at"]), "SAVED_BEFORE_GENERATION")
                eligible = max(_time(asof), _time(generated), _time(proof["created_at"])) < _time(row["cutoff_at"])
                p.update(persisted_at=proof["created_at"], server_saved_at=proof["created_at"], artifact_id=proof["artifact_id"],
                         original_json_sha256=proof["payload_sha256"], source_code_commit=proof["head_sha"],
                         original_json_hash_scope="CANONICAL_DOCUMENT_SHA256",
                         generated_at=generated, as_of=asof, external_receipt_verified=True, eligible_pre_cutoff=eligible,
                         source_provenance=bindings, receipt_run_id=str(proof["run_id"]))
                if p.get("input_sha256") is None:
                    p["input_sha256"] = slot.get("original_input_sha256") if reused else report["input_sha256"]
                    p["input_hash_scope"] = "BASELINE_NATIVE_INPUT_BINDING" if reused else "DISPATCH_NATIVE_INPUT_MAP"
                if p.get("source_sha256") is None:
                    p["source_sha256"] = digest(bindings); p["source_hash_scope"] = "SOURCE_BINDING_MANIFEST"
                p["missing_reasons"] = [r for r in p["missing_reasons"] if r not in
                    {"INDEPENDENT_RECEIPT_NOT_VERIFIED", "GENERATED_AT_NOT_SAVED", "INPUT_SHA_NOT_SAVED", "SOURCE_SHA_NOT_SAVED"}]
                if not eligible:
                    p["missing_reasons"].append("SAVED_AFTER_CUTOFF")
            records.append(row)
    days = {row["event_date_jst"] for row in records}
    return dict(schema="RACE_AI_PRIVATE_CYCLE_VIEW_V1", dataset_status="REAL_REPORTED", records=records,
                event_date_jst=next(iter(days)) if len(days) == 1 else None, as_of=payload["as_of"],
                input_sha256=digest([report["input_sha256"] for report in payload["dispatch_reports"]]),
                dispatch_status_counts=dict(Counter(slot["status"] for report in payload["dispatch_reports"] for slot in report["slots"])),
                retained_original_count=sum(len(report.get("retained_originals", [])) for report in payload["dispatch_reports"]),
                independent_receipts_verified=True, source_requests=0, official_metrics_eligible=False,
                research_only=True, evidence_imported_only=True, schedule_completeness_proven=False,
                all_models_operational=False, external_receipts_created=False, new_model_created=False,
                originals_overwritten=False)


def forecast_saved_p0(document, receipt, runtime_files, *, now, issued_models=None, runtime_pointer=None):
    """Issue new P0 families now from exact older, authenticated source inputs.

    Original observed predictions remain untouched. Only the new shared input's
    race.as_of changes to the actual caller clock. Every original source clock,
    snapshot identity and save receipt is retained under input_origins.
    """
    from .boat_all_model_inputs import shared_snapshot_from_observed
    from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
    from .first_receipt_continuity import first_receipt_rows
    from .observed_weight_learning import attach_snapshots
    from .frozen_day_cycle import official_id, rank_check
    clock = _clock(now)
    _need(type(document) is dict and document.get("schema") == "RACE_AI_EXISTING_P0_DAY_V1"
          and document.get("actual_purchases") is False and type(document.get("predictions")) is list
          and document.get("race_count") == len(document["predictions"]) <= 288, "SAVED_P0_DOCUMENT_INVALID")
    proof = _receipt(receipt, digest(document), receipt.get("head_sha"))
    _need(_time(proof["created_at"]) <= clock, "P0_ORIGINAL_RECEIPT_IN_FUTURE")
    rows = []; seen = set()
    for suite in document["predictions"]:
        rid = official_id(suite["race_id"])
        _need(rid not in seen and suite["stage"] == "P0" and suite["event_date_jst"] == document["day_jst"]
              and suite["suite_sha256"] == digest({k: v for k, v in suite.items() if k != "suite_sha256"})
              and set(suite["models"]) == set(OBSERVED), "SAVED_P0_SUITE_INVALID")
        seen.add(rid)
        _need(_not_before(suite["as_of"], proof["created_at"])
              and _time(proof["created_at"]) < _time(suite["sales_cutoff_at"]), "SAVED_P0_ORIGINAL_CLOCK_INVALID")
        roster = {str(p["lane"]): p["registration_no"] for p in suite["observations"]}
        lanes = set(map(int, roster))
        for mid, prediction in suite["models"].items():
            _need(prediction["model_id"] == mid and _native_hash(prediction) is not None
                  and prediction["race_id"] == suite["race_id"] and prediction["as_of"] == suite["as_of"]
                  and prediction["sales_cutoff_at"] == suite["sales_cutoff_at"]
                  and prediction["snapshot_sha256"] == suite["snapshot_sha256"], "SAVED_P0_MODEL_BINDING_INVALID")
            ranked = [p["combination"] for p in prediction["candidates"]]
            rank_check(ranked, prediction["ordered_top8"], lanes=lanes)
            rows.append(dict(race_id=rid, sport="boat", stage="P0", model_id=mid, as_of=suite["as_of"],
                cutoff_at=suite["sales_cutoff_at"], server_saved_at=proof["created_at"], artifact_id=proof["artifact_id"],
                original_json_sha256=digest(document), model_sha256=prediction["prediction_sha256"], roster=roster,
                top8=prediction["ordered_top8"], ranked=ranked, calibrated=False))
    _need(len(rows) == document.get("model_forecast_count"), "SAVED_P0_MODEL_COUNT_INVALID")
    first, duplicates = first_receipt_rows(rows)
    enriched = attach_snapshots(document, first)
    history, fitted, provenance = _runtime(runtime_files, runtime_pointer)
    try:
        issued = _issued(issued_models); reports = []; origins = {}; readiness_rows = []; skipped = []; capsules = []
        for row in enriched:
            rid = row["race_id"]
            if rid in origins:
                continue
            observed = row.get("learning_snapshot")
            _need(type(observed) is dict and digest(observed) == row["learning_snapshot_sha256"], "SAVED_P0_SNAPSHOT_REQUIRED")
            snap = shared_snapshot_from_observed(observed)
            original_asof = observed["as_of"]
            snap["race"]["as_of"] = clock.isoformat()
            origins[rid] = dict(original_as_of=original_asof, original_snapshot_sha256=digest(observed),
                original_document_sha256=digest(document), original_receipt=proof, source_evidence=deepcopy(observed["sources"]),
                forecast_as_of=clock.isoformat(), source_age_seconds=(clock - _time(original_asof)).total_seconds())
            refs = {(s["source_url"], s["source_rights_ref"]) for s in observed["sources"]}
            native = {}; cutoff = _time(row["cutoff_at"])
            current_day = document["day_jst"] == clock.astimezone(JST).date().isoformat()
            ready = clock < cutoff and current_day
            if ready:
                native["shared"] = dict(snapshot=snap)
                if fitted is not None:
                    native["shared_learned"] = dict(snapshot=deepcopy(snap), learned_model=deepcopy(fitted))
            else:
                skipped.append(dict(race_id=rid, reason="AT_OR_AFTER_CUTOFF" if clock >= cutoff else "SOURCE_EVENT_DAY_MISMATCH"))
            saved = issued.get(rid, set()) | set(OBSERVED)
            for group, mids in GROUPS:
                if set(mids) <= saved:
                    native.pop(group, None)
            schedule = dict(race_id=rid, sport="boat", stage="P0", cutoff_at=row["cutoff_at"],
                venue=observed["venue"], race_no=int(rid[-2:]), offering_status="UNKNOWN",
                participants=[dict(number=p["lane"], registration_no=p["registration_no"], name=None, active=True)
                              for p in observed["participants"]], withdrawn_participants=[])
            report = dispatch([schedule], {rid: {"P0": native}}, now=clock,
                allow_source=lambda ref, rights, purpose: purpose == "analysis" and (ref, rights) in refs)
            report["schedule"] = [schedule]
            _postprocess(report, saved, {}, "P0")
            p1_only = {mid for group, mids in GROUPS if group in {"boat_ab", "boat_clite", "boat_tactical", "boat_full", "boat_pdca"} for mid in mids}
            for slot in report["slots"]:
                if slot["model_id"] in p1_only and slot["model_id"] not in saved:
                    slot.update(status="RULE_FILTERED", reason="WAITING_EXHIBITION")
            report["status_counts"] = dict(Counter(s["status"] for s in report["slots"]))
            capsules.append(_native_capsule(schedule, native, clock, report, refs))
            reports.append(report)
            readiness_rows.append(dict(race_id=rid, stage="P0", groups={group: dict(
                state=next(s["status"] for s in report["slots"] if s["model_id"] == mids[0]),
                reasons=[next(s["reason"] for s in report["slots"] if s["model_id"] == mids[0])]) for group, mids in GROUPS}))
        payload = _json_copy(dict(schema=SCHEMA, stage="P0", generated_at=clock.isoformat(), as_of=clock.isoformat(),
            source_code_commit=provenance["source_code_commit"], run_id=runtime_files.get("run_id"), runtime_provenance=provenance,
            current_inputs=[], input_origins=origins, dispatch_reports=reports, model_readiness=readiness_rows,
            skipped_contexts=skipped, baseline=None, source_requests=0, originals_overwritten=False, native_input_capsules=capsules,
            summary=dict(contexts=len(origins), generated_forecasts=sum(s["status"] == "GENERATED_UNATTESTED" for r in reports for s in r["slots"]),
                         reused_baseline_forecasts=0), first_receipt_duplicates=duplicates))
        _verify_native_input_capsules(payload, replay_outputs=False)
        return payload
    finally:
        history.close()
