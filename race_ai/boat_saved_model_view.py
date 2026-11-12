"""Pure append-only union of saved private projections and registration-bound names.

This module never fetches, predicts, scores or verifies an external receipt. A
prediction is copied verbatim. Its save identity excludes its output hash/body:
changing either under the same source, clock and receipt binding is a conflict.

``names`` accepts ``{"races": {race_id: {registration_no: name_or_metadata}},
"registry": {registration_no: metadata}}``. Same-race metadata may include a
physical ``number``; registry metadata requires ``verified=True`` and an actual
``source_sha256``. Neither a lane nor a ticket is a racer registration identity.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
import re
import unicodedata

SCHEMA = "RACE_AI_PRIVATE_CYCLE_VIEW_V1"
MAX_BYTES = 64 * 1024 * 1024
MAX_PREDICTIONS = 32768
MAX_PER_RACE_PREDICTIONS = 128
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_REGISTRATION = re.compile(r"\d{4}\Z")
_JST = timezone(timedelta(hours=9))

# A new as-of, source, cutoff, training artifact or save receipt is a distinct
# original, even when the model's stage/version and its tickets are unchanged.
PREDICTION_IDENTITY_FIELDS = (
    "stage", "native_stage", "model_id", "model_version", "variant", "source_code_commit", "as_of", "cutoff_at",
    "input_sha256", "source_sha256", "source_captured_at", "source_provenance",
    "artifact_id", "original_json_sha256", "physical_receipt_sha256", "pair_sha256",
    "persisted_at", "server_saved_at", "training_sha256", "training_artifact_id", "training_receipt_digest",
)


class SavedModelViewError(ValueError):
    """A fixed diagnostic without private source data in the error message."""


def _need(condition, reason):
    if not condition:
        error=SavedModelViewError("saved model view rejected: " + reason)
        # All callers supply fixed literals. Preserve a public diagnostic code
        # without exposing row bodies, racer identities or forecast contents.
        error.reason_code='SAVED_MODEL_VIEW_'+re.sub('[^A-Za-z0-9]+','_',reason).strip('_').upper()
        raise error


def _tree(value, depth=0):
    _need(depth <= 64, "JSON depth")
    if type(value) is dict:
        _need(all(type(key) is str for key in value), "JSON object keys")
        for child in value.values(): _tree(child, depth + 1)
    elif type(value) is list:
        for child in value: _tree(child, depth + 1)
    else:
        _need(type(value) in (str, int, float, bool, type(None)) and
              (type(value) is not float or math.isfinite(value)), "JSON value")


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _clone(value):
    _tree(value)
    _need(len(_wire(value).encode("utf-8")) <= MAX_BYTES, "JSON size")
    return deepcopy(value)


def _clock(value):
    try:
        _need(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value), "timestamp")
        clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(clock.utcoffset() is not None, "timestamp timezone")
        return clock
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SavedModelViewError): raise
        raise SavedModelViewError("saved model view rejected: timestamp") from exc


def _day(value):
    try:
        _need(type(value) is str and date.fromisoformat(value).isoformat() == value, "event day")
    except (ValueError, TypeError) as exc:
        if isinstance(exc, SavedModelViewError): raise
        raise SavedModelViewError("saved model view rejected: event day") from exc


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "SHA format")


def _label(value, maximum=500):
    _need(type(value) is str and 0 < len(value) <= maximum and value == value.strip(), "name or identity label")


def _name_key(value):
    """Compare official spelling/spacing without changing a saved display name.

    This is the existing venue-detail join's NFKC/whitespace rule. Registration,
    race and lane remain separate strict bindings; differing letters still fail.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def saved_prediction_identity(prediction):
    """Return the stable JSON save binding; output hashes are not identity keys."""
    _need(type(prediction) is dict, "prediction object")
    reference = prediction.get("native_source_reference")
    if type(reference) is dict:
        reference = {k:v for k,v in reference.items() if k not in ("prediction_sha256", "output_sha256", "model_sha256")}
    return _wire([*[prediction.get(field) for field in PREDICTION_IDENTITY_FIELDS], reference])


def _predictions(row):
    _need(row.get("prediction") is None or type(row["prediction"]) is dict, "primary prediction")
    comparisons = row.get("comparison_predictions", [])
    _need(type(comparisons) is list and len(comparisons) <= MAX_PER_RACE_PREDICTIONS, "comparison count")
    out = ([row["prediction"]] if row.get("prediction") is not None else []) + comparisons
    _need(len(out) <= MAX_PER_RACE_PREDICTIONS, "per-race saved prediction limit")
    for p in out:
        _need(type(p) is dict, "prediction object")
        _need(p.get("stage") in ("P0", "P1", "UNKNOWN", "A_PRE_TRIAL", "B_POST_TRIAL"), "prediction stage")
        for field in ("model_id", "model_version", "variant"):
            if p.get(field) is not None: _label(p[field])
        _need(p.get("source_code_commit") is None or type(p["source_code_commit"]) is str and
              re.fullmatch(r"[a-f0-9]{40}",p["source_code_commit"]), "source code commit")
        for field in ("as_of", "generated_at", "persisted_at", "server_saved_at", "cutoff_at", "source_captured_at"):
            if p.get(field) is not None: _clock(p[field])
        for field in ("prediction_sha256", "output_sha256", "input_sha256", "source_sha256", "model_sha256",
                      "original_json_sha256", "physical_receipt_sha256", "pair_sha256", "training_sha256"):
            if p.get(field) is not None: _sha(p[field])
        if p.get("artifact_id") is not None:
            _need(type(p["artifact_id"]) is int and p["artifact_id"] > 0, "artifact identity")
        _need(p.get("odds_independent") is None or type(p["odds_independent"]) is bool, "odds independence assertion")
        _need(p.get("race_id") is None or p["race_id"] == row["race_id"], "prediction race binding")
        _need(p.get("prediction_sha256") is not None or p.get("native_dispatch_prediction") is True and
              p.get("output_sha256") is not None and p.get("hash_basis") == "NATIVE_OUTPUT_CONTENT", "prediction hash missing")
        top = p.get("ordered_top8")
        maximum = 6 if row["sport"] == "boat" else 99
        _need(type(top) is list and 1 <= len(top) <= 8 and all(type(t) is list and len(t) == 3 and
              all(type(n) is int and 1 <= n <= maximum for n in t) and len(set(t)) == 3 for t in top) and
              len({tuple(t) for t in top}) == len(top), "saved tickets")
        if p.get("cutoff_at") is not None:
            _need(_clock(p["cutoff_at"]).astimezone(_JST).date().isoformat() == row["event_date_jst"], "prediction cutoff day")
    return out


def _unique(rows):
    out, seen = [], set()
    for item in rows:
        key = _wire(item)
        if key not in seen:
            out.append(deepcopy(item)); seen.add(key)
    return out


def _registration(person):
    values = [person[key] for key in ("registration_no", "registration_number", "registration_id", "racer_registration_id", "racer_id") if person.get(key) is not None]
    _need(values and all(type(v) is str and _REGISTRATION.fullmatch(v) and v == values[0] for v in values), "participant registration")
    return values[0]


def _participants(row):
    people = row.get("participants")
    if people is None: return []
    _need(type(people) is list and len(people) <= (6 if row["sport"] == "boat" else 99), "participant count")
    lanes, registrations = set(), set()
    for person in people:
        _need(type(person) is dict, "participant object")
        number = person.get("number")
        _need(type(number) is int and 1 <= number <= (6 if row["sport"] == "boat" else 99) and number not in lanes, "participant number")
        lanes.add(number)
        if row["sport"] == "boat":
            pid = _registration(person)
            _need(pid not in registrations, "duplicate participant registration"); registrations.add(pid)
        if person.get("name") is not None: _label(person["name"])
        if person.get("name_source") is not None:
            source = person["name_source"]
            _need(type(source) is dict and source.get("kind") in ("SAME_RACE_PROGRAM", "SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT", "VERIFIED_CURRENT_OFFICIAL_PROFILE", "VERIFIED_RACER_REGISTRY"), "name source kind")
            _need(source.get("registration_no") == _registration(person), "name source registration")
            if source["kind"] in ("SAME_RACE_PROGRAM", "SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT", "VERIFIED_CURRENT_OFFICIAL_PROFILE"): _need(source.get("race_id") == row["race_id"], "name source race")
            _name_metadata(dict(source, name=person.get("name")), _registration(person),
                           race_id=row["race_id"] if source["kind"] in ("SAME_RACE_PROGRAM", "SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT", "VERIFIED_CURRENT_OFFICIAL_PROFILE") else None,
                           registry=source["kind"] == "VERIFIED_RACER_REGISTRY")
    return people


def _name_metadata(value, registration, *, race_id=None, registry=False):
    _need(type(registration) is str and _REGISTRATION.fullmatch(registration), "name registration key")
    item = dict(name=value) if type(value) is str and not registry else value
    _need(type(item) is dict, "name metadata")
    _label(item.get("name"))
    for key in ("registration_no", "registration_number", "registration_id", "racer_registration_id", "racer_id"):
        _need(item.get(key) is None or item[key] == registration, "name registration mismatch")
    _need(item.get("race_id") is None or item["race_id"] == race_id, "name race mismatch")
    _need(item.get("number") is None or type(item["number"]) is int and 1 <= item["number"] <= 6, "name physical lane")
    if registry:
        _need(item.get("verified") is True, "registry verification missing")
        _sha(item.get("source_sha256"))
    elif item.get("source_sha256") is not None:
        _sha(item["source_sha256"])
    if item.get("captured_at") is not None: _clock(item["captured_at"])
    if item.get("source_url") is not None: _label(item["source_url"], 2000)
    if item.get("kind") == "VERIFIED_CURRENT_OFFICIAL_PROFILE":
        # This name has a separate AEAD-verified current official HTML
        # receipt. It does not reconstruct the older 2026-11-07 HTML.
        _need(race_id is not None
              and item.get("verified_current") is True
              and item.get("historical_source_sha_matched") is False
              and item.get("source_sha256") is not None
              and item.get("captured_at") is not None
              and item.get("source_url") ==
                  "https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=" + registration
              and _clock(item["captured_at"]).astimezone(_JST).date().strftime("%Y%m%d") >= race_id[:8],
              "fresh official profile provenance")
    if item.get("kind") in ("SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT"):
        from .racer_intraday_source import identity as official_result_identity
        kind = item["kind"]
        _need(race_id is not None and item.get("source_sha256") is not None
              and item.get("captured_at") is not None and
              item.get("source_url") is not None, "official result name provenance")
        day, venue, number = official_result_identity(item["source_url"])
        source_rid = f"{day.replace('-', '')}-{venue}-{number:02d}"
        if kind == "SAME_RACE_RESULT":
            _need(source_rid == race_id, "same-race result URL identity")
        else:
            _need(type(item.get("source_race_id")) is str
                  and item["source_race_id"] == source_rid
                  and race_id[:8] == source_rid[:8],
                  "same-day result registration scope")
    return item


def _names(names):
    if names is None: return {}, {}
    _need(type(names) is dict and set(names) <= {"races", "registry"}, "name mapping")
    races, registry = names.get("races", {}), names.get("registry", {})
    _need(type(races) is dict and type(registry) is dict, "name mapping objects")
    for rid, rows in races.items():
        _label(rid); _need(type(rows) is dict, "race name mapping")
        for pid, item in rows.items(): _name_metadata(item, pid, race_id=rid)
    for pid, item in registry.items(): _name_metadata(item, pid, registry=True)
    return races, registry


def _rosters(rows, aliases=()):
    from .boat_name_aliases import validate_person_alias, exact_alias_pair, person_aliases
    snapshots, bindings, named, current_people = [], {}, {}, []
    active = []
    for row in rows:
        people = _participants(row)
        current_people.extend(people)
        if aliases:
            withdrawn_people = row.get('withdrawn_participants', [])
            _need(type(withdrawn_people) is list and all(type(p) is dict for p in withdrawn_people),
                  "withdrawn participant names")
            known_withdrawn = [p for p in withdrawn_people if any(p.get(k) is not None for k in
                ('registration_no', 'registration_number', 'registration_id', 'racer_registration_id', 'racer_id'))]
            _participants(dict(row, participants=known_withdrawn))
            current_people.extend(known_withdrawn)
        original = row.get("saved_participant_rosters")
        if original is None:
            original = [dict(participants=deepcopy(people), source_sha256=row.get("source_sha256"),
                             observed_at=row.get("observed_at"), source_provenance=row.get("source_provenance"))] if people else []
        _need(type(original) is list, "saved roster snapshots")
        for snapshot in original:
            _need(type(snapshot) is dict and type(snapshot.get("participants")) is list, "saved roster snapshot")
            _participants(dict(row, participants=snapshot["participants"]))
            snapshots.append(snapshot)
        # An older snapshot may predate display-name enrichment. Retain the
        # exact current B spelling before replacing that display with full,
        # separately sourced registry text; derived full displays need no new
        # snapshot on replay.
        if aliases and people and any(person.get('name') and any(
                _name_key(person['name']) == _name_key(f['short_name']) for f in person_aliases(person, aliases))
                for person in people) and not any(s['participants'] == people for s in original):
            snapshots.append(dict(participants=deepcopy(people), source_sha256=row.get('source_sha256'),
                observed_at=row.get('observed_at'), source_provenance=row.get('source_provenance')))
        if people:
            withdrawn = row.get("withdrawn_lanes", [])
            _need(type(withdrawn) is list and all(type(n) is int and 1 <= n <= 6 for n in withdrawn) and len(set(withdrawn)) == len(withdrawn), "withdrawn lanes")
            withdrawn = set(withdrawn) | {p["number"] for p in people if p.get("active") is False or p.get("withdrawn") is True}
            explicit = row.get("roster_status") == "OFFICIAL_ACTIVE" or bool(withdrawn) or all(p.get("active") is True for p in people)
            active.append(([p for p in people if p["number"] not in withdrawn], explicit, withdrawn))
    snapshots = _unique(snapshots)
    all_named_people = current_people + [p for snapshot in snapshots for p in snapshot["participants"]]
    for person in all_named_people:
        number, pid = person["number"], _registration(person)
        _need(number not in bindings or bindings[number] == pid, "same-race roster identity conflict")
        _need(pid not in bindings.values() or bindings.get(number) == pid, "same-race registration lane conflict")
        bindings[number] = pid
    for fact in aliases:
        _need(bindings.get(fact['number']) == fact['registration_no'], "name alias roster mismatch")
    for person in all_named_people:
        pid = _registration(person)
        validate_person_alias(person, aliases)
        if person.get("name") and (person.get("name_source") or {}).get("kind") != "VERIFIED_RACER_REGISTRY":
            _need(pid not in named or _name_key(named[pid]["name"]) == _name_key(person["name"])
                  or exact_alias_pair(named[pid], person, aliases), "same-race name conflict")
            named.setdefault(pid, person)
    if not active: return [], snapshots, named, [], []
    full = set(bindings)
    selected = active[0][0]
    explicit_sets = []
    for people, explicit, withdrawn in active:
        lanes = {p["number"] for p in people}
        if lanes != full:
            _need(explicit and (not withdrawn or full - lanes <= withdrawn), "unexplained participant subset")
        if explicit: explicit_sets.append((people, lanes, withdrawn))
    if explicit_sets:
        # Withdrawals reduce the active field; older full-roster saves cannot
        # silently restore a withdrawn entrant when replayed later.
        selected, selected_lanes, _ = min(explicit_sets, key=lambda item: len(item[1]))
        _need(all(selected_lanes <= lanes for _, lanes, _ in explicit_sets), "incompatible active rosters")
    missing = full - {p["number"] for p in selected}
    all_people = {p["number"]:p for p in [p for snapshot in snapshots for p in snapshot["participants"]] + current_people}
    withdrawn_people = [dict(deepcopy(all_people[n]), active=False, withdrawn=True) for n in sorted(missing)]
    return deepcopy(selected), snapshots, named, sorted(missing), withdrawn_people


def _apply_names(row, named, race_names, registry, aliases=()):
    from .boat_name_aliases import person_aliases, validate_person_alias, full_source_kind
    mapping = race_names.get(row["race_id"], {})
    people = row.get("participants", []) + row.get("withdrawn_participants", [])
    by_registration = {_registration(p):p for p in people}
    for pid, item in mapping.items():
        meta = _name_metadata(item, pid, race_id=row["race_id"])
        _need(pid in by_registration, "same-race name absent from roster")
        _need(meta.get("number") is None or meta["number"] == by_registration[pid]["number"], "name lane mismatch")
        if person_aliases(by_registration[pid], aliases):
            validate_person_alias(dict(by_registration[pid], name=meta['name'], name_source=dict(
                kind='SAME_RACE_PROGRAM', **{k:meta[k] for k in ('source_url', 'source_sha256') if k in meta})), aliases)
    for person in people:
        pid = _registration(person)
        alias = person_aliases(person, aliases)
        if alias:
            validate_person_alias(person, aliases)
            if pid in registry:
                _need(any(_name_key(registry[pid]['name']) == _name_key(f['full_name']) for f in alias),
                      "name alias registry conflict")
            fact = alias[0]; source = fact['full_source']
            person['name'] = fact['full_name']
            kind = full_source_kind(fact)
            person['name_source'] = dict(kind=kind, registration_no=pid,
                **({'verified':True} if kind == 'VERIFIED_RACER_REGISTRY' else {'race_id':row['race_id']}),
                **{k:deepcopy(source[k]) for k in ('source_sha256', 'source_url', 'captured_at')})
            continue
        if pid in mapping:
            item = _name_metadata(mapping[pid], pid, race_id=row["race_id"]); kind = item.get("kind", "SAME_RACE_PROGRAM")
            _need(kind in ("SAME_RACE_PROGRAM", "SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT", "VERIFIED_CURRENT_OFFICIAL_PROFILE"), "same-race name source kind")
        elif pid in named:
            person["name"] = named[pid]["name"]
            if named[pid].get("name_source") is not None: person["name_source"] = deepcopy(named[pid]["name_source"])
            continue
        elif pid in registry:
            item = _name_metadata(registry[pid], pid, registry=True); kind = "VERIFIED_RACER_REGISTRY"
        else:
            # Keep an existing explicitly bound display name, or honest null.
            person.setdefault("name", None)
            continue
        person["name"] = item["name"]
        person["name_source"] = dict(kind=kind, registration_no=pid,
            **({"race_id":row["race_id"], **({"source_race_id":item["source_race_id"]} if kind == "SAME_DAY_OFFICIAL_RESULT" else {})} if kind in ("SAME_RACE_PROGRAM", "SAME_RACE_RESULT", "SAME_DAY_OFFICIAL_RESULT", "VERIFIED_CURRENT_OFFICIAL_PROFILE") else {}),
            **{k:deepcopy(item[k]) for k in ("verified", "verified_current", "historical_source_sha_matched", "source_sha256", "source_url", "captured_at") if k in item})


def _observations(rows, field, *, rejection=False):
    output, seen = [], {}
    for row in rows:
        values = row.get(field, [])
        _need(type(values) is list and len(values) <= 10000, "result observation count")
        for item in values:
            _need(type(item) is dict, "result observation object")
            captured = _clock(item.get("captured_at"))
            if item.get("source_sha256") is not None: _sha(item["source_sha256"])
            if not rejection: _need(item.get("race_id") == row["race_id"], "result race binding")
            key = (captured, item.get("source_sha256")) if rejection else captured
            wire = _wire(item)
            if key in seen and seen[key] != wire:
                from .result_observation_conflict_diagnostics import result_conflict_counts
                try:
                    _need(False, "conflicting result observation")
                except SavedModelViewError as error:
                    error.conflict_counts = result_conflict_counts(json.loads(seen[key]), item)
                    raise
            if key not in seen: output.append(deepcopy(item)); seen[key] = wire
    return sorted(output, key=lambda item: _clock(item["captured_at"]))


def validate_cutoff_reconciliation(row, result):
    """Validate a caller's raw-bound reference projection, never authenticate it.

    The raw parser/retainer owns provenance verification. Legacy references keep
    their one-minute bound. An explicit SP race header can bind each saved model
    to its own cutoff and the source cutoff, with the same roster and chronology.
    No original clock or formal evaluation eligibility is changed.
    """
    proof = result.get("cutoff_reconciliation")
    if proof is None: return False
    per_model = type(proof) is dict and proof.get("basis") == "RAW_OFFICIAL_SP_RESULT_PER_SAVED_MODEL_CUTOFF"
    _need(type(proof) is dict and result.get("status") == "final" and row.get("sport") == "boat" and
          (per_model or proof.get("basis") == "RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF") and proof.get("formal_eligible") is False and
          proof.get("roster_identity_verified") is True and proof.get("all_originals_saved_before_both") is True,
          "cutoff reconciliation scope")
    cutoffs, originals = row.get("saved_cutoff_variants", []), proof.get("original_cutoffs")
    _need(type(originals) is list and all(type(c) is str for c in originals) and len(originals) == len(set(originals)) and
          set(originals) == set(cutoffs) and len({_clock(c) for c in cutoffs}) > 1, "cutoff reconciliation originals")
    clocks = [_clock(c) for c in originals]
    schedule = {_clock(c) for c in row.get("saved_schedule_cutoff_variants", [])}
    # SP can reconcile saved schedule revisions only when every schedule clock
    # is already an original model cutoff. Keep the conflict/history intact;
    # unknown schedule or observation clocks remain a hold.
    schedule_bound = (len(schedule) <= 1 and "SAVED_SCHEDULE_CUTOFF_CONFLICT" not in row.get("missing_reasons", [])) or (per_model and len(schedule) > 1)
    _need(schedule_bound and schedule <= set(clocks) and not row.get("saved_observation_cutoff_variants"), "cutoff reconciliation schedule")
    maximum = proof.get("maximum_offset_seconds")
    _need(type(maximum) in (int,float) and 0 <= maximum <= (86400 if per_model else 60), "cutoff reconciliation maximum offset")
    _sha(proof.get("source_sha256"))
    _need(proof["source_sha256"] == result.get("source_sha256"), "cutoff reconciliation source")
    people = _participants(row)
    _need(3 <= len(people) <= 6, "cutoff reconciliation registered roster")
    roster = {p["number"]:_registration(p) for p in people}
    observations = row.get("result_observations", [])
    captured = _clock(result.get("observed_at"))
    _need(observations and captured == max(_clock(o["captured_at"]) for o in observations), "cutoff reconciliation latest observation")
    matching = [o for o in observations if _clock(o["captured_at"]) == captured and o.get("source_sha256") == proof["source_sha256"]]
    _need(len(matching) == 1, "cutoff reconciliation observation source")
    observation = matching[0]; data = observation.get("data")
    _need(observation.get("body_identity_verified") is True and observation.get("status") == "AVAILABLE" and
          type(data) is dict and data.get("status") == "settled" and data.get("confirmed") is True and data.get("finish_confirmed") is True,
          "cutoff reconciliation raw result")
    records = data.get("results")
    from .boat_active_roster import match_result_roster
    try:
        active_results=match_result_roster(row,records,race_id=row['race_id'])
    except (ValueError,TypeError,KeyError):
        raise SavedModelViewError("saved model view rejected: cutoff reconciliation result roster") from None
    _need({p['lane']:p.get('racer_registration_id') for p in active_results}==roster,
          "cutoff reconciliation result roster")
    payouts = [p for p in data.get("payouts", []) if type(p) is dict and p.get("bet_type") == "trifecta"]
    winners = result.get("winning_combinations")
    _need(type(winners) is list and winners and len(payouts) == len(winners) and
          _wire(sorted([p.get("combination") for p in payouts])) == _wire(sorted(winners)) and data.get("top3") in winners and
          all(type(p.get("payout_per_100_yen")) is int and p["payout_per_100_yen"] >= 0 for p in payouts), "cutoff reconciliation result payouts")
    if len(payouts) == 1:
        _need(result.get("payout_yen_per_100") == payouts[0]["payout_per_100_yen"], "cutoff reconciliation payout amount")
    else:
        _need(_wire(result.get("payouts")) == _wire(payouts), "cutoff reconciliation payout amounts")
    if result.get("payouts") is not None: _need(_wire(result["payouts"]) == _wire(payouts), "cutoff reconciliation payout details")
    for field in ("refund_boats", "refunds", "refund_combinations", "dead_heat"):
        _need(_wire(result.get(field)) == _wire(data.get(field)), "cutoff reconciliation refund binding")
    source_cutoff = _clock(observation.get("closed_at"))
    if per_model:
        binding=proof.get("source_schedule_binding",observation.get("schedule_binding"))
        _need(binding == "SP_EXPLICIT_RACE_HEADER" and observation.get("schedule_binding") in (None,"SP_EXPLICIT_RACE_HEADER") and
              _clock(proof.get("source_cutoff_at")) == source_cutoff, "cutoff reconciliation explicit source cutoff")
        from .racer_intraday_source import identity
        try:
            day,venue,number=identity(observation.get("source_url"))
        except (ValueError,TypeError,AttributeError):
            _need(False,"cutoff reconciliation explicit source URL")
        _need(day.replace('-','')+f'-{venue}-{number:02d}' == row['race_id'],"cutoff reconciliation explicit source URL")
    clocks.append(source_cutoff)
    _need(all(c.astimezone(_JST).date().isoformat() == row["event_date_jst"] for c in clocks) and
          (max(clocks)-min(clocks)).total_seconds() <= maximum and captured >= max(clocks), "cutoff reconciliation clock span")
    predictions = _predictions(row)
    _need(predictions, "cutoff reconciliation predictions")
    for p in predictions:
        if per_model:
            _need(p.get("cutoff_at") is not None and _clock(p["cutoff_at"]) in clocks[:-1], "cutoff reconciliation model cutoff")
        limit = min(_clock(p["cutoff_at"]),source_cutoff) if per_model else min(clocks)
        saved = p.get("persisted_at") or p.get("server_saved_at")
        _need(saved is not None and _clock(saved) < limit, "cutoff reconciliation saved chronology")
        for field in ("as_of", "generated_at", "source_captured_at", "server_saved_at"):
            _need(p.get(field) is None or _clock(p[field]) < limit, "cutoff reconciliation original chronology")
    return True


def _result(row, rows):
    results = [source["result"] for source in rows if source.get("result") is not None]
    for result in results:
        _need(type(result) is dict and result.get("status") in ("final", "pending", "unsupported", "void"), "result status")
        _clock(result.get("observed_at"))
    newest = max([_clock(result["observed_at"]) for result in results] +
                 [_clock(o["captured_at"]) for o in row["result_observations"]], default=None)
    if newest is None: return None
    options = _unique([r for r in results if _clock(r["observed_at"]) == newest])
    observations = [o for o in row["result_observations"] if _clock(o["captured_at"]) == newest]
    rejected = [r for r in row["result_observation_rejections"] if _clock(r["captured_at"]) == newest]
    ambiguous = bool(row.get("saved_observation_cutoff_variants")) or row.get("cutoff_at") is None and bool(row.get("saved_cutoff_variants") or row.get("saved_schedule_cutoff_variants"))
    reconciled = [r for r in options if validate_cutoff_reconciliation(row, r)]
    if reconciled and all(r["reason"] == "RESULT_AMBIGUOUS_FORECAST_CUTOFF" for r in rejected):
        _need(len(reconciled) == 1 and all(r.get("status") == "unsupported" or
              _wire({k:v for k,v in r.items() if k != "cutoff_reconciliation"}) ==
              _wire({k:v for k,v in reconciled[0].items() if k != "cutoff_reconciliation"}) for r in options), "conflicting reconciled result")
        return deepcopy(reconciled[0])
    if len(options) == 1 and options[0]["status"] in ("pending", "void") and not rejected:
        return deepcopy(options[0])
    if not options or rejected or ambiguous:
        source = observations[0] if observations else options[0]
        result = dict(status="unsupported", winning_combinations=[], confirmed_at=None,
            observed_at=source.get("captured_at", source.get("observed_at")), official=False, source_sha256=source.get("source_sha256"))
        if ambiguous and observations and not rejected:
            row["result_observation_rejections"].append(dict(captured_at=source["captured_at"], source_sha256=source.get("source_sha256"), reason="RESULT_AMBIGUOUS_FORECAST_CUTOFF"))
        return result
    _need(len(options) == 1, "conflicting projected result")
    return deepcopy(options[0])


def _merge_record(rows, race_names, registry):
    row = deepcopy(rows[0])
    for other in rows[1:]:
        for field in ("race_id", "sport", "event_date_jst", "race_no"):
            _need(row.get(field) is None or other.get(field) is None or row[field] == other[field], "race identity conflict")
        for field, value in other.items():
            if row.get(field) is None: row[field] = deepcopy(value)
    metadata_fields = ("source_sha256", "source_sha", "source_provenance", "observed_at", "as_of", "updated_at", "offering_status", "race_status")
    metadata = _unique([item for source in rows for item in source.get("saved_row_metadata",
        [{field:deepcopy(source.get(field)) for field in metadata_fields}])])
    row["saved_row_metadata"] = metadata
    def source_clock(item):
        return max([_clock(item[k]) for k in ("observed_at", "as_of", "updated_at") if item.get(k) is not None],
                   default=datetime.min.replace(tzinfo=timezone.utc))
    latest = max(metadata, key=source_clock)
    for field in metadata_fields:
        if field in row or latest.get(field) is not None: row[field] = deepcopy(latest.get(field))
    for field in ("offering_status", "race_status"):
        known = [item for item in metadata if item.get(field) not in (None, "UNKNOWN")]
        if known: row[field] = deepcopy(max(known, key=source_clock)[field])
    predictions, identities = [], {}
    for source in rows:
        for p in _predictions(source):
            key = saved_prediction_identity(p)
            wire = _wire(p)
            _need(key not in identities or identities[key] == wire, "original prediction identity conflict")
            if key not in identities: predictions.append(deepcopy(p)); identities[key] = wire
    _need(len(predictions) <= MAX_PER_RACE_PREDICTIONS, "per-race saved prediction limit")
    row["prediction"] = predictions[0] if predictions else None
    row["comparison_predictions"] = predictions[1:]
    for field in ("saved_cutoff_variants", "saved_schedule_cutoff_variants", "saved_observation_cutoff_variants", "missing_reasons"):
        values = []
        for source in rows:
            _need(type(source.get(field, [])) is list, "saved metadata list")
            values.extend(source.get(field, []))
        if field == "saved_cutoff_variants": values.extend(p["cutoff_at"] for p in predictions if p.get("cutoff_at") is not None)
        if values or field in row: row[field] = _unique(values)
    cutoffs = row.get("saved_cutoff_variants", [])
    if cutoffs:
        row["cutoff_at"] = cutoffs[0] if len({_clock(c) for c in cutoffs}) == 1 else None
        if row["cutoff_at"] is None: row.setdefault("missing_reasons", []).append("SAVED_FORECAST_CUTOFF_CONFLICT")
    elif len({_clock(c) for c in row.get("saved_schedule_cutoff_variants", [])}) > 1:
        row["cutoff_at"] = None
    if row.get("sport") == "boat":
        from .boat_name_aliases import collect_alias_facts, FIELD as ALIAS_FIELD
        aliases = collect_alias_facts(rows)
        people, snapshots, named, withdrawn, withdrawn_people = _rosters(rows, aliases)
        row["participants"] = people
        if snapshots: row["saved_participant_rosters"] = snapshots
        if withdrawn:
            row.update(withdrawn_lanes=withdrawn, withdrawn_participants=withdrawn_people, roster_status="OFFICIAL_ACTIVE")
        if aliases: row[ALIAS_FIELD] = aliases
        _apply_names(row, named, race_names, registry, aliases)
    row["result_observations"] = _observations(rows, "result_observations")
    row["result_observation_rejections"] = _observations(rows, "result_observation_rejections", rejection=True)
    for source in rows: _need(not source.get("result_revisions"), "official result revisions in private view")
    row["result_revisions"] = []
    row["result"] = _result(row, rows)
    if row["result_observation_rejections"]: row.setdefault("missing_reasons", []).append("RESULT_OBSERVATION_REJECTED")
    row["missing_reasons"] = _unique(row.get("missing_reasons", []))
    if predictions: row["missing_reasons"] = [r for r in row["missing_reasons"] if r != "NO_SAVED_PREDICTION"]
    if row["result"]: row["missing_reasons"] = [r for r in row["missing_reasons"] if r != "NO_SAVED_RESULT_OBSERVATION"]
    stages = _unique([s for source in rows for s in source.get("scheduled_stages", [])] + [p["stage"] for p in predictions if p["stage"] != "UNKNOWN"])
    if stages and any("scheduled_stages" in source for source in rows): row["scheduled_stages"] = stages
    attempts = []
    for source in rows:
        attempts.extend(source.get("saved_dispatch_slot_observations", [dict(as_of=source.get("as_of", source.get("observed_at")), slot=deepcopy(slot)) for slot in source.get("dispatch_slots", [])]))
    if attempts:
        row["native_dispatch_view"] = True
        row["saved_dispatch_slot_observations"] = _unique(attempts)
        current = {}
        for attempt in sorted(row["saved_dispatch_slot_observations"], key=lambda a: _clock(a["as_of"]) if a.get("as_of") else datetime.min.replace(tzinfo=timezone.utc)):
            slot = attempt["slot"]; current[_wire([slot.get(k) for k in ("stage", "model_id", "model_version")])] = deepcopy(slot)
        row["dispatch_slots"] = list(current.values())
    return row


def merge_saved_views(base, additions=(), *, names=None):
    """Union private projections, preserving original order, bodies and saves.

    ``additions`` can be one view or a list/tuple of views. All views must have
    the same explicit real/synthetic dataset status. Errors leave every input
    untouched. The output remains a private research projection, not an audit.
    """
    if type(additions) is dict: additions = [additions]
    _need(type(additions) in (list, tuple), "addition views")
    views = _clone([base, *additions]); names = _clone(names)
    race_names, registry = _names(names)
    records, status = {}, views[0].get("dataset_status") if type(views[0]) is dict else None
    _need(status in ("REAL_REPORTED", "SYNTHETIC_ONLY"), "dataset status")
    for doc in views:
        _need(type(doc) is dict and doc.get("schema") == SCHEMA and doc.get("dataset_status") == status, "view schema or dataset status")
        _need(type(doc.get("records")) is list and len(doc["records"]) <= 10000, "race count")
        seen = set()
        for row in doc["records"]:
            _need(type(row) is dict and type(row.get("race_id")) is str and row["race_id"] not in seen, "race object or duplicate")
            seen.add(row["race_id"]); _label(row["race_id"], 250); _day(row.get("event_date_jst"))
            _need(row.get("sport") in ("boat", "horse", "keirin", "autorace"), "sport")
            _need(doc.get("event_date_jst") is None or doc["event_date_jst"] == row["event_date_jst"], "view event day")
            if row.get("as_of") is None and doc.get("as_of") is not None:
                _clock(doc["as_of"]); row["as_of"] = doc["as_of"]
            records.setdefault(row["race_id"], []).append(row)
    _need(len(records) <= 10000, "union race count")
    out = deepcopy(views[0])
    out["records"] = [_merge_record(rows, race_names, registry) for rows in records.values()]
    _need(sum((1 if row["prediction"] is not None else 0)+len(row["comparison_predictions"]) for row in out["records"]) <= MAX_PREDICTIONS,
          "total saved prediction limit")
    days = {row["event_date_jst"] for row in out["records"]}
    out["event_date_jst"] = next(iter(days)) if len(days) == 1 else None
    for field in ("original_document_references", "unresolved_learned_dependencies"):
        if any(field in doc for doc in views): out[field] = _unique([item for doc in views for item in doc.get(field, [])])
    synced = [doc["results_synced_at"] for doc in views if doc.get("results_synced_at") is not None]
    if synced: out["results_synced_at"] = max(synced, key=_clock)
    clocks = [doc["as_of"] for doc in views if doc.get("as_of") is not None]
    if clocks: out["as_of"] = max(clocks, key=_clock)
    hashes = _unique([sha for doc in views for sha in doc.get("source_state_sha256s", [doc["source_state_sha256"]] if doc.get("source_state_sha256") else [])])
    if hashes: out["source_state_sha256s"] = hashes
    out["saved_view_union"] = True
    _need(len(_wire(out).encode("utf-8")) <= MAX_BYTES, "union JSON size")
    return out
