"""Private participant ledger and offline shadow-cycle runtime; no official authority.

ResearchLedger.initialize(path, participant_ids=three_ids, pins={}, now=None)
creates a new private SQLite ledger. open(path) never initializes missing state.
Participant pins may be bound once with bind_participant; forecasts cannot be
admitted for an unbound entrant. Pins include model_sha256 and policy_sha256.
register_race(binding, source_verifier=callback), register_forecast(f, selection,
readback_verifier=callback), and append_result(outcome, result_verifier=callback)
append immutable hash-chained events. Every verifier must return a dict with
verified=True, independent=True, verifier, receipt_sha256, payload_sha256 matching
the exact callback payload; a boolean True is rejected. Callbacks must invoke
the existing independently trusted verifier. Supplying a callable or a hash is
not itself real-world authentication; synthetic callbacks are never live proof.

The binding includes race_id/day/starters/input_sha256/cohort/cutoff_at. Forecasts
also require feature_input_sha256 and exact selection/model/input/policy binding.
Prospective prediction and actual seal must precede cutoff by >=15 minutes.
Seal clocks come from the runtime clock, never a supplied historical timestamp.
``now`` injects a callable for deterministic synthetic tests, not source evidence.

An incomplete calendar remains a race event. admit_calendar(race_id, binding,
source_verifier=...) may append one independently verified race_admission before
the forecast margin, only while no source admission, participant original or
final result exists. registry() resolves that admission without editing the
calendar. run_shadow_cycle uses the actual new clock for such an upgrade.
Official results can settle calendar-only races with input_roster_unknown=True;
their optional result_roster is separate from the still-unknown pre-race roster.
This branch requires an independent receipt with authority='official' and a
source_sha256. Unsupported result adapters must HOLD, never manufacture proof.

checkpoint(directory, owner_public_pem) uses the EXISTING pinned-owner
keirin_official_run_history seal_evidence codec, in <=4 MiB plaintext shards.
restore_checkpoint(... expected_manifest_sha256=externally_retained_sha,
owner_private_pem=...) restores to a nonexistent private path only. It checks all
shards and the event chain. No alternative crypto, new key or reset fallback.
Plaintext exports/DBs are refused anywhere beneath a Git working tree.

run_shadow_cycle runs the existing feature/forecast/policy/comparison APIs on
already admitted records. Rivals are supplied frozen exports, never simulated.
Candidate scheduling invokes a supplied fit callback in a new private directory.
candidate_adoption_check only returns KEEP/REVIEW_READY; it never changes pins,
the active model, production, permissions, schedules or external services.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .policy import (RACE_TIMEZONE, PolicyError, checked_cars, checked_day, checked_sha,
                     check_race_day, clock, digest, finite_number, fixed_selection,
                     probability, require, select_tickets, ticket_cap, validate_forecast)


SCHEMA = 'DT_R1_PARTICIPANT_LEDGER_V1'
CHECKPOINT_SCHEMA = 'DT_R1_ENCRYPTED_LEDGER_CHECKPOINT_V1'
MAX_SHARD_BYTES = 4 * 1024 * 1024
ZERO_SHA = '0' * 64
SQL = '''
CREATE TABLE events (seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, event_key TEXT NOT NULL,
 observed_at TEXT NOT NULL, body TEXT NOT NULL, previous_sha256 TEXT NOT NULL,
 event_sha256 TEXT NOT NULL UNIQUE, UNIQUE(kind,event_key));
CREATE TRIGGER immutable_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LEDGER'); END;
CREATE TRIGGER immutable_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LEDGER'); END;
'''


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def _private_path(path):
    raw = Path(path).expanduser()
    require(not raw.is_symlink(), 'SYMLINK_STATE_PATH_REFUSED')
    path = raw.resolve()
    require(not any((parent / '.git').exists() for parent in (path, *path.parents)), 'PRIVATE_STATE_MUST_BE_OUTSIDE_GIT')
    return path


def _new_file(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not path.exists(), 'STATE_ALREADY_EXISTS')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)


def _write(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _checked_receipt(result, payload):
    require(isinstance(result, dict) and result.get('verified') is True and result.get('independent') is True,
            'INDEPENDENT_VERIFIER_RECEIPT_REQUIRED')
    require(isinstance(result.get('verifier'), str) and bool(result['verifier'].strip()), 'VERIFIER_ID_REQUIRED')
    checked_sha(result.get('receipt_sha256'), 'VERIFICATION_RECEIPT_SHA_REQUIRED')
    require(result.get('payload_sha256') == digest(payload), 'VERIFICATION_PAYLOAD_SHA_MISMATCH')
    return result


def _verified(verifier, payload):
    require(callable(verifier), 'INDEPENDENT_VERIFIER_REQUIRED')
    return _checked_receipt(verifier(copy.deepcopy(payload)), payload)


def _selection_core(selection):
    out = {key: value for key, value in selection.items() if key not in
           ('selection_sha256', 'odds_evidence', 'confidence_assessment', 'calibration_binding')}
    return {**out, 'confidence': 'HOLD'}


def _selection_seal(selection):
    out = {key: value for key, value in selection.items() if key != 'selection_sha256'}
    return {**out, 'selection_sha256': digest(out)}


def _odds_payload(forecast, selection, snapshot):
    return {'purpose': 'DT_R1_ODDS_FOR_FROZEN_FORECAST', 'forecast_sha256': digest(validate_forecast(forecast)),
            'race_id': forecast['race_id'], 'model_sha256': forecast['model_sha256'],
            'policy_sha256': selection['policy_sha256'], 'decision_at': selection['decision_at'],
            'odds_snapshot': snapshot}


def _check_odds_availability(snapshot, decision_at):
    if isinstance(snapshot, dict) and snapshot.get('available_at') is not None:
        require(clock(snapshot['available_at']) <= clock(snapshot.get('captured_at')) <= clock(decision_at),
                'ODDS_AVAILABLE_AFTER_CAPTURE_OR_DECISION')


def _validate_selection(forecast, selection):
    """A caller-recomputed hash cannot bypass the frozen distribution or policy."""
    policy = selection.get('policy')
    require(isinstance(policy, dict) and digest(policy) == selection['policy_sha256'], 'SELECTION_POLICY_HASH_MISMATCH')
    require(policy.get('version') in ('dt-r1-fixed-k-v1', 'dt-r1-odds-policy-v1'), 'UNSUPPORTED_SELECTION_POLICY')
    market = selection.get('market')
    require(market in ('trifecta', 'exacta') and policy.get('market') == market, 'SELECTION_MARKET_MISMATCH')
    selected = selection.get('selected_tickets')
    require(isinstance(selected, list), 'SELECTION_TICKETS_REQUIRED')
    require(type(selection.get('ticket_count')) is int and selection['ticket_count'] == len(selected), 'SELECTION_COUNT_MISMATCH')
    if selection.get('status') == 'HOLD':
        require(not selected and selection.get('raw_coverage') == 0 and selection.get('total_stake') == 0, 'HOLD_SELECTION_MUST_BE_EMPTY')
        return
    require(selection.get('status') == 'SELECTED' and bool(selected), 'SELECTION_STATUS_INVALID')
    ranked = forecast[market + 's']
    support = {tuple(item['cars']): item['probability'] for item in ranked}
    seen, total, coverage, gross = set(), 0.0, 0.0, 0.0
    for item in selected:
        require(isinstance(item, dict), 'SELECTION_TICKET_INVALID')
        ticket = checked_cars(item.get('cars'), 3 if market == 'trifecta' else 2)
        require(ticket in support and ticket not in seen, 'SELECTION_OUTSIDE_FROZEN_SUPPORT_OR_DUPLICATE')
        seen.add(ticket)
        p = probability(item.get('probability'))
        require(abs(p - support[ticket]) <= 1e-7, 'SELECTION_PROBABILITY_MISMATCH')
        stake = finite_number(item.get('stake', selection.get('stake_per_ticket')))
        require(stake > 0, 'SELECTION_STAKE_INVALID')
        total += stake
        coverage += p
        if policy['version'] == 'dt-r1-odds-policy-v1':
            odds = finite_number(item.get('odds'))
            require(odds > 0, 'SELECTION_ODDS_INVALID')
            require(p >= probability(policy.get('min_marginal_probability')) and
                    p * odds - 1 >= finite_number(policy.get('min_expected_net_per_unit')), 'SELECTION_MARGINAL_GATES_MISMATCH')
            require(stake == finite_number(policy.get('stake_per_ticket')), 'SELECTION_POLICY_STAKE_MISMATCH')
            gross += p * odds * stake
    require(abs(probability(selection.get('raw_coverage')) - min(1.0, coverage)) <= 1e-7, 'SELECTION_SET_COVERAGE_MISMATCH')
    require(math.isfinite(total) and abs(finite_number(selection.get('total_stake')) - total) <= 1e-7, 'SELECTION_TOTAL_STAKE_MISMATCH')
    if policy['version'] == 'dt-r1-fixed-k-v1':
        expected = fixed_selection(forecast, policy.get('k'), market)
        require(digest(selected) == digest(expected['selected_tickets']) and selection.get('cap') == expected['cap'] and
                selection.get('anchor_ticket') == expected['anchor_ticket'] and total == expected['total_stake'], 'FIXED_SELECTION_POLICY_MISMATCH')
    else:
        anchor = ranked[0]['cars']
        require(selection.get('anchor_ticket') == anchor, 'SELECTION_ANCHOR_MISMATCH')
        cap = ticket_cap(selection.get('anchor_odds')) if market == 'trifecta' else 2
        require(selection.get('cap') == cap and len(selected) <= cap, 'SELECTION_CAP_MISMATCH')
        require(math.isfinite(gross) and abs(finite_number(selection.get('expected_gross')) - gross) <= 1e-7 and
                abs(finite_number(selection.get('expected_net')) - (gross - total)) <= 1e-7, 'SELECTION_EXPECTATION_MISMATCH')
        checked_sha(selection.get('odds_source_sha256'), 'SELECTION_ODDS_SOURCE_REQUIRED')
        pred, cutoff = clock(forecast['prediction_at']), clock(forecast['cutoff_at'])
        captured, decision = clock(selection.get('odds_captured_at')), clock(selection.get('decision_at'))
        require(clock(selection.get('odds_published_at')) <= captured and pred <= captured <= decision < cutoff and
                clock(selection.get('anchor_fixed_at')) == pred, 'SELECTION_ODDS_CLOCK_MISMATCH')
        evidence = selection.get('odds_evidence')
        require(isinstance(evidence, dict), 'INDEPENDENT_ODDS_EVIDENCE_REQUIRED')
        snapshot = evidence.get('snapshot')
        _check_odds_availability(snapshot, selection['decision_at'])
        _checked_receipt(evidence.get('receipt'), _odds_payload(forecast, selection, snapshot))
        config = {key: policy[key] for key in ('market', 'min_marginal_probability',
                  'min_expected_net_per_unit', 'target_coverage', 'stake_per_ticket')}
        expected = select_tickets(forecast, snapshot, config=config, decision_at=selection['decision_at'])
        require(digest(_selection_core(selection)) == digest(_selection_core(expected)), 'FROZEN_ODDS_POLICY_SELECTION_MISMATCH')


def _event(sql_row):
    return {'seq': sql_row[0], 'kind': sql_row[1], 'key': sql_row[2], 'observed_at': sql_row[3],
            'body': json.loads(sql_row[4]), 'previous_sha256': sql_row[5], 'event_sha256': sql_row[6]}


def _validate_event(event, expected_seq, previous, last_clock):
    require(isinstance(event, dict) and set(event) == {'seq', 'kind', 'key', 'observed_at', 'body', 'previous_sha256', 'event_sha256'}, 'LEDGER_EVENT_FIELDS_INVALID')
    require(event['seq'] == expected_seq and event['previous_sha256'] == previous, 'LEDGER_CHAIN_ORDER_INVALID')
    require(isinstance(event['body'], dict), 'LEDGER_BODY_INVALID')
    at = clock(event['observed_at'])
    require(last_clock is None or at >= last_clock, 'LEDGER_BACKDATED_EVENT')
    require(digest({k: v for k, v in event.items() if k != 'event_sha256'}) == event['event_sha256'], 'LEDGER_EVENT_HASH_MISMATCH')
    return event['event_sha256'], at


def _calendar_incomplete(binding):
    return (len(binding.get('starters', ())) < 3 or
            (binding.get('cohort') == 'prospective' and binding.get('cutoff_at') is None))


class ResearchLedger:
    """Append-only participant events; open() refuses absent or corrupt state."""
    def __init__(self, path, connection, now=None):
        self.path, self.connection = path, connection
        self._clock = now or (lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def initialize(cls, path, *, participant_ids, pins=None, now=None):
        require(isinstance(participant_ids, (list, tuple)) and len(participant_ids) == 3 and
                len(set(participant_ids)) == 3 and all(isinstance(p, str) and p for p in participant_ids), 'THREE_PARTICIPANTS_REQUIRED')
        require(isinstance(pins or {}, dict) and set(pins or {}) <= set(participant_ids), 'UNKNOWN_PARTICIPANT_PIN')
        path = _private_path(path)
        _new_file(path)
        con = sqlite3.connect(path, isolation_level=None)
        con.executescript(SQL)
        ledger = cls(path, con, now)
        ledger._append('initialize', 'ledger', {'schema': SCHEMA, 'participant_ids': list(participant_ids), 'official_authority': False})
        for model_id, pin in (pins or {}).items():
            ledger.bind_participant(model_id, pin)
        return ledger

    @classmethod
    def open(cls, path, *, now=None):
        path = _private_path(path)
        require(path.is_file(), 'MISSING_STATE_STOP_NO_RESET')
        require(path.stat().st_mode & 0o077 == 0, 'STATE_NOT_PRIVATE')
        con = sqlite3.connect(f'file:{path}?mode=rw', uri=True, isolation_level=None)
        ledger = cls(path, con, now)
        try:
            require(con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLITE_INTEGRITY_FAILED')
            previous, last, n = ZERO_SHA, None, 0
            for sql_row in con.execute('SELECT * FROM events ORDER BY seq'):
                n += 1
                previous, last = _validate_event(_event(sql_row), n, previous, last)
            first = ledger.events('initialize')
            require(n > 0 and len(first) == 1 and first[0]['seq'] == 1 and first[0]['body'].get('schema') == SCHEMA, 'LEDGER_SCHEMA_INVALID')
            return ledger
        except Exception:
            con.close()
            raise

    def close(self):
        self.connection.close()

    def _now(self):
        value = self._clock()
        return clock(value).isoformat()

    def _append(self, kind, key, body):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            # Timestamp after acquiring the write lock, not before a possible
            # wait that could carry a forecast across the cutoff margin.
            at = self._now()
            body = copy.deepcopy(body)
            if kind == 'forecast':
                body['sealed_at'] = at
            if kind == 'race_admission':
                # Recheck while holding the write lock. A concurrent original
                # or a clock crossing the margin cannot slip into an upgrade.
                require(self.can_admit_calendar(key), 'CALENDAR_ADMISSION_NO_LONGER_ELIGIBLE')
                current = {row['race_id']: row for row in self.registry()}[key]
                require(digest(current) == body['previous_binding_sha256'], 'CALENDAR_BINDING_CHANGED')
                if body['binding']['cohort'] == 'prospective':
                    require((clock(body['binding']['cutoff_at']) - clock(at)).total_seconds() >= 900,
                            'CALENDAR_ADMISSION_AFTER_15_MINUTE_MARGIN')
            head = self.connection.execute('SELECT seq,event_sha256,observed_at FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            require(head is None or clock(at) >= clock(head[2]), 'BACKDATED_APPEND_REFUSED')
            seq, previous = (head[0] + 1, head[1]) if head else (1, ZERO_SHA)
            event = {'seq': seq, 'kind': kind, 'key': key, 'observed_at': at,
                     'body': copy.deepcopy(body), 'previous_sha256': previous}
            event['event_sha256'] = digest(event)
            try:
                self.connection.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',
                    (seq, kind, key, at, _canonical(body).decode(), previous, event['event_sha256']))
            except sqlite3.IntegrityError as error:
                raise PolicyError('IMMUTABLE_ORIGINAL_ALREADY_EXISTS') from error
            self.connection.execute('COMMIT')
            return event
        except Exception:
            self.connection.execute('ROLLBACK')
            raise

    def events(self, kind=None):
        rows = self.connection.execute('SELECT * FROM events ORDER BY seq') if kind is None else self.connection.execute('SELECT * FROM events WHERE kind=? ORDER BY seq', (kind,))
        return [_event(row) for row in rows]

    @property
    def participant_ids(self):
        return self.events('initialize')[0]['body']['participant_ids']

    def participant_pins(self):
        return {e['key']: e['body'] for e in self.events('participant')}

    def bind_participant(self, model_id, pin):
        require(model_id in self.participant_ids and isinstance(pin, dict), 'UNKNOWN_PARTICIPANT')
        require(set(pin) <= {'model_sha256', 'policy_sha256', 'feature_schema_sha256'} and
                {'model_sha256', 'policy_sha256'} <= set(pin), 'PARTICIPANT_PIN_FIELDS_REQUIRED')
        for value in pin.values():
            checked_sha(value)
        return self._append('participant', model_id, pin)

    def bind_calibrator(self, artifact, *, expected_sha256, calibration_verifier):
        """Freeze one independently audited calibrator per participant policy.

        expected_sha256 is supplied from the caller's prior freeze. The verifier
        must authenticate the full artifact, its independent audit and its actual
        frozen_at clock. An artifact's own self-hash is insufficient provenance.
        """
        from .calibration import _check_artifact
        checked_sha(expected_sha256, 'EXTERNAL_CALIBRATOR_SHA_REQUIRED')
        artifact = _check_artifact(artifact)
        require(artifact['artifact_sha256'] == expected_sha256, 'FROZEN_CALIBRATOR_SHA_MISMATCH')
        lineage = artifact.get('lineage', {})
        pin = self.participant_pins().get(lineage.get('model_id'))
        require(pin is not None and lineage.get('model_sha256') == pin['model_sha256'] and
                lineage.get('policy_sha256') == pin['policy_sha256'], 'CALIBRATOR_PARTICIPANT_POLICY_PIN_MISMATCH')
        key = json.dumps([lineage['model_id'], lineage['policy_sha256']], separators=(',', ':'))
        existing = [event for event in self.events('calibrator') if event['key'] == key]
        if existing:
            require(existing[0]['body']['artifact']['artifact_sha256'] == expected_sha256, 'IMMUTABLE_CALIBRATOR_PIN_MISMATCH')
            return existing[0]
        require(isinstance(artifact.get('audit'), dict) and artifact['audit'].get('refit') is False,
                'CALIBRATOR_INDEPENDENT_AUDIT_REQUIRED')
        payload = {'purpose': 'DT_R1_FROZEN_CALIBRATOR', 'artifact': artifact,
                   'expected_artifact_sha256': expected_sha256, 'participant_pin': pin}
        verified = _verified(calibration_verifier, payload)
        require(verified.get('audit_verified') is True, 'INDEPENDENT_CALIBRATION_AUDIT_RECEIPT_REQUIRED')
        require(clock(verified.get('frozen_at')) <= clock(self._now()), 'CALIBRATOR_FREEZE_FROM_FUTURE')
        return self._append('calibrator', key, {'artifact': artifact, 'payload': payload, 'receipt': verified})

    def _validate_confidence(self, selection):
        from .calibration import assess_selection
        assessment = selection.get('confidence_assessment')
        if assessment is None:
            require(selection.get('confidence', 'HOLD') == 'HOLD', 'AUDITED_CONFIDENCE_BINDING_REQUIRED')
            return
        require(isinstance(assessment, dict) and assessment.get('label') == selection.get('confidence') and
                assessment.get('ticket_count') == selection.get('ticket_count') and
                assessment.get('raw_coverage') == selection.get('raw_coverage'), 'CONFIDENCE_SELECTION_BINDING_MISMATCH')
        binding = selection.get('calibration_binding')
        if binding is None:
            require(assessment.get('label') == 'HOLD' and assessment.get('calibrated_probability') is None and
                    assessment.get('calibration_n') == 0 and assessment.get('audit_n') == 0,
                    'AUDITED_CONFIDENCE_BINDING_REQUIRED')
            return
        require(isinstance(binding, dict) and binding.get('selection_core_sha256') == digest(_selection_core(selection)),
                'CALIBRATION_SELECTION_SHA_MISMATCH')
        matches = [event for event in self.events('calibrator') if event['event_sha256'] == binding.get('calibrator_event_sha256')]
        require(len(matches) == 1, 'FROZEN_CALIBRATOR_EVENT_REQUIRED')
        body = matches[0]['body']
        _checked_receipt(body['receipt'], body['payload'])
        require(body['receipt'].get('audit_verified') is True, 'INDEPENDENT_CALIBRATION_AUDIT_RECEIPT_REQUIRED')
        at = selection.get('prediction_at') or selection.get('decision_at')
        require(at is not None and clock(body['receipt']['frozen_at']) <= clock(at), 'CALIBRATOR_FROZEN_AFTER_PREDICTION')
        expected = assess_selection(_selection_core(selection), body['artifact'])
        expected['source_attested'] = True
        require(digest(expected) == digest(assessment), 'CONFIDENCE_RECOMPUTATION_MISMATCH')

    def record_hold(self, race_id, model_id, reason):
        require(model_id in self.participant_ids, 'UNKNOWN_PARTICIPANT')
        require(isinstance(reason, str) and bool(reason), 'HOLD_REASON_REQUIRED')
        body = {'race_id': race_id, 'model_id': model_id, 'reason': reason}
        for event in reversed(self.events('hold')):
            if event['body'] == body:
                return event
        return self._append('hold', uuid.uuid4().hex, body)

    def _source_hold(self, race_id, reason):
        body = {'race_id': race_id, 'reason': reason}
        if not any(event['body'] == body for event in self.events('source_hold')):
            self._append('source_hold', uuid.uuid4().hex, body)
        return {'status': 'HOLD', **body}

    def _source_admitted(self, race_id, binding):
        bound_sha = digest(binding)
        if any(event['key'] == race_id and event['body']['binding_sha256'] == bound_sha
               for event in self.events('source_verified')):
            return True
        return any(event['key'] == race_id and digest(event['body']['binding']) == bound_sha
                   for event in self.events('race_admission'))

    def can_admit_calendar(self, race_id):
        current = {row['race_id']: row for row in self.registry()}.get(race_id)
        return (current is not None and _calendar_incomplete(current) and
                not any(event['key'] == race_id for event in self.events('source_verified')) and
                not any(event['key'] == race_id for event in self.events('race_admission')) and
                not any(event['body']['forecast']['race_id'] == race_id for event in self.events('forecast')) and
                not any(event['body']['outcome']['race_id'] == race_id and
                        event['body']['outcome']['status'] != 'pending' for event in self.events('result')))

    def admit_calendar(self, race_id, binding, *, source_verifier):
        """Append one verified full card over an unadmitted calendar placeholder.

        The initial race event is never edited. Identity/day/cohort stay fixed;
        no admitted source, any entrant original, or settled result may exist.
        Failure returns HOLD and leaves registry() on the prior calendar.
        """
        try:
            require(isinstance(binding, dict), 'RACE_BINDING_REQUIRED')
            old = {row['race_id']: row for row in self.registry()}.get(race_id)
            require(old is not None, 'CALENDAR_RACE_NOT_REGISTERED')
            require(all(binding.get(key) == old.get(key) for key in ('race_id', 'day', 'cohort')),
                    'CALENDAR_ADMISSION_IDENTITY_MISMATCH')
            if digest(old) == digest(binding) and self._source_admitted(race_id, old):
                return {'status': 'REGISTERED', 'race_id': race_id}
            require(self.can_admit_calendar(race_id), 'CALENDAR_ADMISSION_REQUIRES_UNADMITTED_PLACEHOLDER')
            checked_day(binding.get('day')); checked_sha(binding.get('input_sha256'), 'RACE_INPUT_SHA_REQUIRED')
            cars = checked_cars(binding.get('starters'))
            require(3 <= len(cars) <= 9 and not _calendar_incomplete(binding), 'COMPLETE_AUTHENTIC_CARD_REQUIRED')
            at = self._now()
            if binding['cohort'] == 'prospective':
                check_race_day(binding['day'], binding.get('cutoff_at'))
                require((clock(binding['cutoff_at']) - clock(at)).total_seconds() >= 900,
                        'CALENDAR_ADMISSION_AFTER_15_MINUTE_MARGIN')
            if binding.get('context_as_of') is not None:
                require(clock(binding['context_as_of']) <= clock(at), 'CONTEXT_SNAPSHOT_FROM_FUTURE')
                if old.get('context_as_of') is not None:
                    require(clock(binding['context_as_of']) > clock(old['context_as_of']), 'CALENDAR_ADMISSION_REQUIRES_FRESH_CONTEXT_CLOCK')
            verified = _verified(source_verifier, binding)
            calendar = next(event for event in self.events('race') if event['key'] == race_id)
            self._append('race_admission', race_id, {'binding': binding, 'receipt': verified,
                         'previous_binding_sha256': digest(old), 'calendar_event_sha256': calendar['event_sha256']})
            return {'status': 'REGISTERED', 'race_id': race_id}
        except Exception as error:
            return self._source_hold(race_id, str(error) if isinstance(error, PolicyError) else 'CALENDAR_ADMISSION_FAILED')

    def register_race(self, binding, *, source_verifier):
        require(isinstance(binding, dict), 'RACE_BINDING_REQUIRED')
        require(isinstance(binding.get('race_id'), str) and bool(binding['race_id']), 'RACE_ID_REQUIRED')
        rid = binding['race_id']
        current = {row['race_id']: row for row in self.registry()}.get(rid)
        if current is not None and digest(current) != digest(binding):
            if _calendar_incomplete(current):
                return self.admit_calendar(rid, binding, source_verifier=source_verifier)
            raise PolicyError('IMMUTABLE_RACE_BINDING_MISMATCH')
        checked_day(binding.get('day'))
        checked_sha(binding.get('input_sha256'), 'RACE_INPUT_SHA_REQUIRED')
        cars = checked_cars(binding.get('starters'))
        # Incomplete schedules remain in the registry. Only a complete, admitted
        # 3--9 rider forecast may later pass validate_forecast.
        require(len(cars) <= 9 and binding.get('cohort') in ('prospective', 'retrospective'), 'RACE_BINDING_INVALID')
        missing_cutoff = binding.get('cohort') == 'prospective' and binding.get('cutoff_at') is None
        if binding.get('cohort') == 'prospective' and not missing_cutoff:
            check_race_day(binding['day'], binding.get('cutoff_at'))
        if current is None:
            self._append('race', rid, binding)
        if missing_cutoff:
            return self._source_hold(rid, 'AUTHENTIC_CUTOFF_REQUIRED')
        if len(cars) < 3:
            return self._source_hold(rid, 'AUTHENTIC_ROSTER_REQUIRED')
        if self._source_admitted(rid, binding):
            return {'status': 'REGISTERED', 'race_id': rid}
        try:
            verified = _verified(source_verifier, binding)
            self._append('source_verified', rid, {'binding_sha256': digest(binding), 'receipt': verified})
            return {'status': 'REGISTERED', 'race_id': rid}
        except (ValueError, TypeError) as error:
            return self._source_hold(rid, str(error))

    def registry(self):
        active = {event['key']: event['body'] for event in self.events('race')}
        for event in self.events('race_admission'):
            active[event['key']] = event['body']['binding']
        return list(active.values())

    def register_forecast(self, forecast, selection, *, readback_verifier):
        f = validate_forecast(forecast)
        rid, model_id = f['race_id'], f['model_id']
        bindings = {r['race_id']: r for r in self.registry()}
        require(rid in bindings, 'RACE_NOT_REGISTERED')
        binding = bindings[rid]
        require(self._source_admitted(rid, binding), 'SOURCE_NOT_INDEPENDENTLY_ADMITTED')
        require(f['day'] == binding['day'] and f['input_sha256'] == binding['input_sha256'] and
                f['cohort'] == binding['cohort'] and sorted(f['starters']) == sorted(binding['starters']), 'FORECAST_REGISTRY_BINDING_MISMATCH')
        checked_sha(f.get('feature_input_sha256'), 'FEATURE_INPUT_SHA_REQUIRED')
        if binding.get('feature_model_id', model_id) == model_id and binding.get('feature_input_sha256') is not None:
            require(f['feature_input_sha256'] == binding['feature_input_sha256'], 'REGISTERED_FEATURE_INPUT_MISMATCH')
        if f['cohort'] == 'prospective' and binding.get('context_as_of') is not None:
            require(clock(binding['context_as_of']) <= clock(f['prediction_at']), 'CONTEXT_AFTER_PREDICTION')
        pin = self.participant_pins().get(model_id)
        require(pin is not None, 'PARTICIPANT_MODEL_PIN_REQUIRED')
        require(f['model_sha256'] == pin['model_sha256'], 'MODEL_PIN_MISMATCH')
        require(isinstance(selection, dict) and selection.get('policy_sha256') == pin['policy_sha256'], 'POLICY_PIN_MISMATCH')
        for key in ('race_id', 'day', 'model_id', 'model_sha256', 'input_sha256', 'cohort', 'prediction_at', 'cutoff_at'):
            require(selection.get(key) == f.get(key), 'SELECTION_FORECAST_BINDING_MISMATCH')
        require(selection.get('selection_sha256') == digest({k: v for k, v in selection.items() if k != 'selection_sha256'}), 'SELECTION_DIGEST_MISMATCH')
        _validate_selection(f, selection)
        self._validate_confidence(selection)
        key = json.dumps([rid, model_id], separators=(',', ':'))
        existing = [e for e in self.events('forecast') if e['key'] == key]
        if existing:
            original = existing[0]
            require(digest(original['body']['forecast']) == digest(forecast) and
                    digest(original['body']['selection']) == digest(selection) and
                    original['body']['registry_binding_sha256'] == digest(binding), 'IMMUTABLE_FORECAST_PAYLOAD_MISMATCH')
            if any(e['key'] == key for e in self.events('readback_verified')):
                return original
        at = self._now() if not existing else original['observed_at']
        if selection.get('decision_at') is not None:
            require(clock(selection['decision_at']) <= clock(at), 'SELECTION_DECISION_AFTER_SEAL')
        if f['cohort'] == 'prospective':
            require(clock(f['cutoff_at']) == clock(binding['cutoff_at']), 'CUTOFF_BINDING_MISMATCH')
            require(clock(f['prediction_at']) <= clock(at), 'FUTURE_PREDICTION_SEAL')
            require((clock(f['cutoff_at']) - clock(at)).total_seconds() >= 900, 'PRE_CUTOFF_15_MINUTES_REQUIRED')
            require((clock(f['cutoff_at']) - clock(f['prediction_at'])).total_seconds() >= 900, 'PRE_CUTOFF_15_MINUTES_REQUIRED')
        if pin.get('feature_schema_sha256') is not None:
            require(f.get('feature_schema_sha256') == pin['feature_schema_sha256'], 'FEATURE_SCHEMA_PIN_MISMATCH')
        if not existing:
            packet = {'forecast': copy.deepcopy(forecast), 'selection': copy.deepcopy(selection),
                      'sealed_at': at, 'feature_input_sha256': f['feature_input_sha256'], 'registry_binding_sha256': digest(binding)}
            original = self._append('forecast', key, packet)
        # Failed readback preserves the immutable original; it cannot be retried by
        # overwriting that original or silently counted as independently verified.
        try:
            if selection.get('decision_at') is not None:
                require(clock(selection['decision_at']) <= clock(original['observed_at']), 'SELECTION_DECISION_AFTER_SEAL')
            if f['cohort'] == 'prospective':
                require((clock(f['cutoff_at']) - clock(original['observed_at'])).total_seconds() >= 900,
                        'ACTUAL_SEAL_CROSSED_15_MINUTE_BOUNDARY')
            verified = _verified(readback_verifier, original['body'])
            self._append('readback_verified', key, {'forecast_event_sha256': original['event_sha256'], 'receipt': verified})
        except Exception:
            self.record_hold(rid, model_id, 'INDEPENDENT_READBACK_FAILED_OR_UNAVAILABLE')
            raise
        return original

    def forecasts(self, *, include_unverified=False):
        verified = {e['key'] for e in self.events('readback_verified')}
        return [{**e['body']['forecast'], 'selection': e['body']['selection']}
                for e in self.events('forecast') if include_unverified or e['key'] in verified]

    def append_result(self, outcome, *, result_verifier):
        require(isinstance(outcome, dict), 'RESULT_REQUIRED')
        outcome = copy.deepcopy(outcome)
        registered = {r['race_id']: r for r in self.registry()}
        rid = outcome.get('race_id')
        require(rid in registered and outcome.get('day') == registered[rid]['day'], 'RESULT_RACE_BINDING_MISMATCH')
        require(outcome.get('status') in ('settled', 'cancelled', 'pending', 'dead_heat'), 'RESULT_STATUS_INVALID')
        unknown_input = _calendar_incomplete(registered[rid]) and not self._source_admitted(rid, registered[rid])
        if outcome['status'] == 'settled':
            top3 = checked_cars(outcome.get('top3'), 3)
            if not unknown_input:
                require(set(top3) <= set(registered[rid]['starters']), 'RESULT_STARTERS_MISMATCH')
        if unknown_input:
            # A final official result may settle a missed calendar race. Its
            # roster is separate evidence, never a reconstructed pre-race card.
            outcome['input_roster_unknown'] = True
            result_roster = outcome.get('result_roster')
            if result_roster is not None:
                result_roster = checked_cars(result_roster)
                require(3 <= len(result_roster) <= 9, 'INVALID_RESULT_ROSTER')
                if outcome['status'] == 'settled':
                    require(set(top3) <= set(result_roster), 'RESULT_TOP3_ROSTER_MISMATCH')
                outcome['result_roster'] = list(result_roster)
            else:
                outcome['result_roster'] = None
            outcome.setdefault('field_size', None)
            if outcome['field_size'] is not None:
                require(type(outcome['field_size']) is int and 3 <= outcome['field_size'] <= 9, 'INVALID_RESULT_FIELD_SIZE')
                if result_roster is not None:
                    require(outcome['field_size'] == len(result_roster), 'RESULT_FIELD_SIZE_ROSTER_MISMATCH')
        at = self._now()
        if outcome.get('result_at') is not None:
            require(clock(outcome['result_at']) <= clock(at), 'FUTURE_RESULT_NOT_OBSERVED')
            require(clock(outcome['result_at']).astimezone(RACE_TIMEZONE).date() >= checked_day(outcome['day']),
                    'RESULT_BEFORE_RACE_DAY')
            if registered[rid].get('cutoff_at') is not None:
                require(clock(outcome['result_at']) > clock(registered[rid]['cutoff_at']), 'RESULT_NOT_AFTER_CUTOFF')
        else:
            require(registered[rid]['cohort'] == 'retrospective', 'PROSPECTIVE_RESULT_CLOCK_REQUIRED')
        prior = [e for e in self.events('result') if e['body']['outcome']['race_id'] == rid]
        if prior and digest(prior[-1]['body']['outcome']) == digest(outcome):
            return prior[-1]
        if prior and prior[-1]['body']['outcome'].get('result_at') and outcome.get('result_at'):
            require(clock(outcome['result_at']) >= clock(prior[-1]['body']['outcome']['result_at']), 'BACKDATED_RESULT_REVISION')
        verified = _verified(result_verifier, outcome)
        if unknown_input:
            require(verified.get('authority') == 'official', 'OFFICIAL_CALENDAR_RESULT_AUTHORITY_REQUIRED')
            checked_sha(verified.get('source_sha256'), 'OFFICIAL_RESULT_SOURCE_SHA_REQUIRED')
        revision = len(prior) + 1
        require(outcome.get('revision', revision) == revision, 'RESULT_REVISION_MISMATCH')
        return self._append('result', json.dumps([rid, revision]), {'revision': revision, 'outcome': outcome, 'receipt': verified})

    def latest_results(self):
        latest = {}
        for event in self.events('result'):
            latest[event['body']['outcome']['race_id']] = event['body']['outcome']
        return list(latest.values())

    def coverage(self):
        expected = len(self.registry()) * len(self.participant_ids)
        actual = len(self.forecasts())
        return {'scheduled_races': len(self.registry()), 'expected_forecasts': expected,
                'verified_forecasts': actual, 'missing_forecasts': expected - actual,
                'unverified_originals': len(self.forecasts(include_unverified=True)) - actual,
                'explicit_hold_events': len(self.events('hold')) + len(self.events('source_hold')),
                'verification_scope': 'Caller-supplied independent verifier receipts; synthetic receipts do not prove live operation.'}

    def checkpoint(self, directory, owner_public_pem, *, max_shard_bytes=MAX_SHARD_BYTES):
        from race_ai import keirin_official_run_history as codec
        require(type(max_shard_bytes) is int and 1024 <= max_shard_bytes <= MAX_SHARD_BYTES, 'INVALID_SHARD_BOUND')
        directory = _private_path(directory)
        require(not directory.exists(), 'CHECKPOINT_DIRECTORY_ALREADY_EXISTS')
        directory.mkdir(mode=0o700, parents=True)
        head = self.connection.execute('SELECT seq,event_sha256 FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        at = self._now(); day = clock(at).astimezone(RACE_TIMEZONE).date().isoformat()
        identity = digest({'event_count': head[0], 'head_sha256': head[1]})
        manifest = {'schema': CHECKPOINT_SCHEMA, 'checkpoint_id': identity, 'event_count': head[0],
                    'head_sha256': head[1], 'owner_spki_sha256': codec.storage.PINNED_OWNER_SPKI_SHA256,
                    'created_at': at, 'day': day, 'shards': []}
        batch = []
        def flush():
            ordinal = len(manifest['shards'])
            payload = {'day_jst': day, 'checkpoint_id': identity, 'ordinal': ordinal, 'events': list(batch),
                       'safe_report': {'day_jst': day, 'event_count': len(batch), 'scope': SCHEMA}}
            require(len(_canonical(payload)) <= max_shard_bytes, 'SINGLE_LEDGER_EVENT_EXCEEDS_SHARD_BOUND')
            sealed = codec.seal_evidence(payload, owner_public_pem, day, at)
            name = f'shard-{ordinal:06d}.sealed.json'
            _write(directory / name, sealed)
            manifest['shards'].append({'file': name, 'sha256': sha256(sealed).hexdigest(), 'bytes': len(sealed), 'event_count': len(batch)})
            batch.clear()
        for sql_row in self.connection.execute('SELECT * FROM events WHERE seq<=? ORDER BY seq', (head[0],)):
            event = _event(sql_row)
            if batch and len(_canonical(batch + [event])) + 512 > max_shard_bytes:
                flush()
            batch.append(event)
        if batch:
            flush()
        raw = _canonical(manifest)
        _write(directory / 'manifest.json', raw)
        return {'manifest_path': str(directory / 'manifest.json'), 'manifest_sha256': sha256(raw).hexdigest(),
                'event_count': head[0], 'shard_count': len(manifest['shards'])}

    def schedule_candidate(self, schedule_id, due_at):
        require(isinstance(schedule_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', schedule_id), 'INVALID_CANDIDATE_ID')
        clock(due_at)
        return self._append('candidate_schedule', schedule_id, {'due_at': due_at, 'status': 'DUE_WHEN_CLOCK_REACHED'})

    def run_due_candidates(self, fit_callback, study_root):
        require(callable(fit_callback), 'FIT_CALLBACK_REQUIRED')
        root = _private_path(study_root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        attempted = {e['body']['schedule_id'] for e in self.events('candidate_state')}
        results = []
        for event in self.events('candidate_schedule'):
            sid = event['key']
            if sid in attempted or clock(event['body']['due_at']) > clock(self._now()):
                continue
            directory = root / sid
            require(not directory.exists(), 'CANDIDATE_STUDY_DIRECTORY_ALREADY_EXISTS')
            directory.mkdir(mode=0o700)
            self._append('candidate_state', sid + ':pending', {'schedule_id': sid, 'status': 'PENDING', 'study_directory': str(directory)})
            try:
                output = fit_callback(study_directory=directory)
                require(isinstance(output, dict), 'CANDIDATE_RESULT_REQUIRED')
                checked_sha(output.get('model_sha256')); checked_sha(output.get('study_manifest_sha256'))
                result = {'schedule_id': sid, 'status': 'REVIEW_RECOMMENDATION', 'candidate': output, 'changes_active_model': False}
            except Exception as error:
                result = {'schedule_id': sid, 'status': 'FAILED_HOLD', 'reason': type(error).__name__, 'changes_active_model': False}
            self._append('candidate_state', sid + ':finished', result)
            results.append(result)
        return results


def restore_checkpoint(directory, path, *, expected_manifest_sha256, owner_private_pem, now=None):
    """Authenticate every shard and chain before atomically exposing a new DB."""
    from race_ai import keirin_official_run_history as codec
    checked_sha(expected_manifest_sha256, 'EXTERNAL_MANIFEST_SHA_REQUIRED')
    directory, path = _private_path(directory), _private_path(path)
    require(not path.exists(), 'RESTORE_DESTINATION_EXISTS_NO_RESET')
    raw = (directory / 'manifest.json').read_bytes()
    require(len(raw) <= 8 * 1024 * 1024 and sha256(raw).hexdigest() == expected_manifest_sha256, 'CHECKPOINT_MANIFEST_SHA_MISMATCH')
    manifest = json.loads(raw)
    require(_canonical(manifest) == raw and manifest.get('schema') == CHECKPOINT_SCHEMA, 'CHECKPOINT_MANIFEST_INVALID')
    require(manifest.get('owner_spki_sha256') == codec.storage.PINNED_OWNER_SPKI_SHA256, 'CHECKPOINT_OWNER_PIN_MISMATCH')
    require(isinstance(manifest.get('shards'), list) and 0 < len(manifest['shards']) <= 100000, 'CHECKPOINT_SHARDS_REQUIRED')
    temporary = path.with_name(path.name + '.restoring-' + uuid.uuid4().hex)
    _new_file(temporary)
    con = sqlite3.connect(temporary, isolation_level=None)
    con.executescript(SQL)
    previous, last, n = ZERO_SHA, None, 0
    published_inode = None
    try:
        con.execute('BEGIN IMMEDIATE')
        for ordinal, item in enumerate(manifest['shards']):
            require(item.get('file') == f'shard-{ordinal:06d}.sealed.json', 'SHARD_PATH_OR_ORDER_INVALID')
            shard = directory / item['file']
            require(shard.is_file() and not shard.is_symlink(), 'MISSING_CHECKPOINT_SHARD_STOP')
            require(shard.stat().st_size == item['bytes'] and 0 < item['bytes'] <= codec.MAX_CIPHER_BYTES, 'CHECKPOINT_SHARD_SIZE_MISMATCH')
            data = shard.read_bytes()
            require(sha256(data).hexdigest() == item['sha256'], 'CHECKPOINT_SHARD_SHA_MISMATCH')
            payload = codec.decrypt_evidence(data, owner_private_pem)
            require(payload.get('checkpoint_id') == manifest['checkpoint_id'] and payload.get('ordinal') == ordinal and
                    payload.get('day_jst') == manifest['day'], 'CHECKPOINT_SHARD_BINDING_MISMATCH')
            require(len(_canonical(payload)) <= MAX_SHARD_BYTES and isinstance(payload.get('events'), list) and
                    len(payload['events']) == item['event_count'], 'CHECKPOINT_SHARD_ROWS_INVALID')
            for event in payload['events']:
                n += 1
                previous, last = _validate_event(event, n, previous, last)
                con.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (event['seq'], event['kind'], event['key'], event['observed_at'],
                            _canonical(event['body']).decode(), event['previous_sha256'], event['event_sha256']))
        require(n == manifest['event_count'] and previous == manifest['head_sha256'], 'CHECKPOINT_CHAIN_HEAD_MISMATCH')
        require(digest({'event_count': n, 'head_sha256': previous}) == manifest['checkpoint_id'], 'CHECKPOINT_IDENTITY_MISMATCH')
        con.execute('COMMIT')
        con.close()
        checked = ResearchLedger.open(temporary, now=now)
        checked.close()
        require(_private_path(path) == path and not path.exists(), 'RESTORE_DESTINATION_CHANGED')
        os.link(temporary, path)  # Exclusive atomic publication; never replace an existing destination.
        info = path.lstat()
        published_inode = (info.st_dev, info.st_ino)
        require(_private_path(path) == path, 'RESTORE_PARENT_CHANGED_AFTER_PUBLICATION')
        temporary.unlink()
        return ResearchLedger.open(path, now=now)
    except Exception:
        con.close()
        # Remove only the exact inode this call exclusively published. A file
        # subsequently replaced by another writer is never deleted by cleanup.
        if published_inode is not None:
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) == published_inode:
                    path.unlink()
            except FileNotFoundError:
                pass
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + '-journal').unlink(missing_ok=True)
        raise


def _snapshot_value(value):
    if is_dataclass(value):
        return _snapshot_value(asdict(value))
    if isinstance(value, dict):
        return {key: _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item) for item in value]
    if hasattr(value, 'tolist'):
        return _snapshot_value(value.tolist())
    return value


def _runtime_confidence(ledger, selection, *, calibrators, calibrator_sha256, calibration_verifier):
    from .calibration import assess_selection
    out = {key: value for key, value in selection.items() if key != 'selection_sha256'}
    assessment = assess_selection(out)
    try:
        require(out['status'] == 'SELECTED', 'POLICY_SELECTION_HOLD')
        policy_sha = out['policy_sha256']
        require(isinstance(calibrators, dict) and policy_sha in calibrators, 'POLICY_SPECIFIC_CALIBRATION_REQUIRED')
        require(isinstance(calibrator_sha256, dict) and policy_sha in calibrator_sha256, 'EXTERNAL_CALIBRATOR_SHA_REQUIRED')
        frozen = ledger.bind_calibrator(calibrators[policy_sha], expected_sha256=calibrator_sha256[policy_sha],
                                       calibration_verifier=calibration_verifier)
        at = out.get('prediction_at') or out.get('decision_at')
        require(at is not None and clock(frozen['body']['receipt']['frozen_at']) <= clock(at),
                'CALIBRATOR_FROZEN_AFTER_PREDICTION')
        assessment = assess_selection(out, frozen['body']['artifact'])
        assessment['source_attested'] = True
        out['calibration_binding'] = {'calibrator_event_sha256': frozen['event_sha256'],
                                      'selection_core_sha256': digest(_selection_core(out))}
    except Exception as error:
        # No unauthenticated artifact is allowed to supply displayed n, CI or
        # calibrated probability, even when its label would have been HOLD.
        assessment = assess_selection(out)
        assessment['hold_reasons'] = [str(error) if isinstance(error, PolicyError) else 'CALIBRATION_VERIFICATION_FAILED']
    out['confidence_assessment'] = assessment
    out['confidence'] = assessment['label']
    return _selection_seal(out)


def _runtime_odds_selection(ledger, forecast, *, odds_snapshots, odds_provider, odds_verifier,
                            policy_config, calibrators, calibrator_sha256, calibration_verifier):
    # Freeze/check the policy and forecast first. A provider receives no outcome
    # or post-race data and cannot change the probability-ranked anchor.
    declared = select_tickets(forecast, None, config=policy_config, decision_at=forecast.get('prediction_at'))
    pin = ledger.participant_pins().get(forecast['model_id'])
    require(pin is not None and pin['model_sha256'] == forecast['model_sha256'], 'MODEL_PIN_MISMATCH')
    require(pin['policy_sha256'] == declared['policy_sha256'], 'POLICY_PIN_MISMATCH')
    if pin.get('feature_schema_sha256') is not None:
        require(pin['feature_schema_sha256'] == forecast.get('feature_schema_sha256'), 'FEATURE_SCHEMA_PIN_MISMATCH')
    provider_error, snapshot = None, None
    try:
        snapshot = (odds_provider(copy.deepcopy(forecast)) if odds_provider is not None
                    else (odds_snapshots or {}).get(forecast['race_id']))
        snapshot = copy.deepcopy(snapshot)
    except Exception:
        provider_error = 'ODDS_PROVIDER_FAILED'
    decision_at = ledger._now()
    selected = select_tickets(forecast, snapshot, config=policy_config, decision_at=decision_at)
    if provider_error:
        selected['hold_reasons'] = [provider_error]
    elif selected['status'] == 'SELECTED':
        try:
            _check_odds_availability(snapshot, decision_at)
            verified = _verified(odds_verifier, _odds_payload(forecast, selected, snapshot))
            selected['odds_evidence'] = {'snapshot': snapshot, 'receipt': verified}
        except Exception as error:
            selected = select_tickets(forecast, None, config=policy_config, decision_at=decision_at)
            selected['hold_reasons'] = [str(error) if isinstance(error, PolicyError) else 'ODDS_VERIFICATION_FAILED']
    return _runtime_confidence(ledger, selected, calibrators=calibrators, calibrator_sha256=calibrator_sha256,
                               calibration_verifier=calibration_verifier)


def run_shadow_cycle(ledger, records, model, *, source_verifier, result_verifier, readback_verifier,
                     external_forecasts=(), k=1, history_records=(), venue_store=None, timing_records=(),
                     context_as_of=None, allow_current_geometry_assumption=False,
                     odds_snapshots=None, odds_provider=None, odds_verifier=None, policy_config=None,
                     calibrators=None, calibrator_sha256=None, calibration_verifier=None):
    """Run target races with explicit prior history and evidenced context snapshots.

    History and targets must have disjoint race IDs. Future history is rejected;
    same-day rows are excluded by the existing feature builder. Context-enabled
    model schemas require the sidecars declared in fit_meta.context. Missing
    sidecars produce a registered feature-schema HOLD, never fabricated columns.
    A supplied context_as_of must be <= the actual runtime clock. On a repeated
    cycle the original context clock is reused and all immutable bindings are
    rechecked; identical originals/results are not rewritten or duplicated.
    Source verifiers receive dataset/history/context snapshot hashes, actual
    feature-input/schema hashes and upstream provenance, so they can authenticate
    the full inputs, not merely the current racecard.

    Optional odds mode is enabled by policy_config, odds_snapshots (race_id ->
    complete snapshot), or odds_provider(frozen_forecast). Supply only one odds
    source. The provider runs after the anchor is fixed; snapshot captured_at
    must be >= prediction_at and <= the actual decision clock. odds_verifier
    independently authenticates the full snapshot/forecast/policy payload using
    the same receipt contract as source_verifier. Invalid/missing odds produce
    an empty policy HOLD while retaining the original distribution. A retry
    reuses the entire original selection and never asks for replacement odds.

    calibrators and calibrator_sha256 map exact policy hashes to frozen artifacts
    and externally retained artifact hashes. calibration_verifier must additionally
    return audit_verified=True and authenticated frozen_at <= prediction_at.
    Each model/policy calibrator is pinned once in the ledger; archive evidence
    cannot certify prospective confidence. Omitted optional inputs keep fixed-K.
    """
    from .features import build_features, require_history_available
    from .pipeline import forecast_row, _result_key
    from .comparison import compare_models
    from .context import augment_features
    for callback in (source_verifier, result_verifier, readback_verifier):
        require(callable(callback), 'SOURCE_RESULT_READBACK_VERIFIERS_REQUIRED')
    require(odds_snapshots is None or isinstance(odds_snapshots, dict), 'ODDS_SNAPSHOTS_MAPPING_REQUIRED')
    require(odds_provider is None or callable(odds_provider), 'ODDS_PROVIDER_MUST_BE_CALLABLE')
    require(odds_snapshots is None or odds_provider is None, 'ONE_ODDS_SOURCE_REQUIRED')
    odds_mode = any(value is not None for value in (odds_snapshots, odds_provider, policy_config))
    targets, history = list(records), list(history_records)
    all_rows = history + targets
    require(all(isinstance(row, dict) and isinstance(row.get('race_id'), str) for row in all_rows), 'NORMALIZED_RECORDS_REQUIRED')
    all_ids = [row['race_id'] for row in all_rows]
    require(len(all_ids) == len(set(all_ids)), 'DUPLICATE_HISTORY_OR_TARGET_RACE')
    for row in all_rows:
        checked_day(row.get('day'))
    if targets:
        first_target_day = min(row['day'] for row in targets)
        require(all(row['day'] <= first_target_day for row in history), 'FUTURE_HISTORY_RECORD_REFUSED')
    actual_now = ledger._now()
    requested_as_of = context_as_of or actual_now
    require(clock(requested_as_of) <= clock(actual_now), 'CONTEXT_SNAPSHOT_FROM_FUTURE')
    existing_bindings = {row['race_id']: row for row in ledger.registry()}
    calendar_upgrades = {row['race_id'] for row in targets if ledger.can_admit_calendar(row['race_id']) and
                         len(row.get('riders', ())) >= 3 and
                         (row.get('cohort') != 'prospective' or row.get('cutoff_at') or row.get('published_cutoff_at'))}
    for target in targets:
        if target.get('cohort') == 'prospective':
            effective_clock = (actual_now if target['race_id'] in calendar_upgrades else
                               existing_bindings.get(target['race_id'], {}).get('context_as_of', requested_as_of))
            require_history_available([row for row in all_rows if row['day'] < target['day']], effective_clock)
    for row in history:
        if row.get('available_at') is not None:
            require(clock(row['available_at']) <= clock(requested_as_of), 'HISTORY_SOURCE_AFTER_CONTEXT_SNAPSHOT')
    if targets:
        last_target_day = max(row['day'] for row in targets)
        for row in all_rows:
            # Earlier target results also feed later targets in the builder.
            # A past race date is not proof its outcome was available yet.
            if row['day'] < last_target_day and row.get('result_at') is not None:
                require(clock(row['result_at']) <= clock(requested_as_of), 'HISTORY_RESULT_AFTER_CONTEXT_SNAPSHOT')
    target_ids = {row['race_id'] for row in targets}
    featured = [row for row in build_features(all_rows) if row['race_id'] in target_ids]
    model_id = model.to_dict()['model_id']
    existing_originals = {(e['body']['forecast']['race_id'], e['body']['forecast']['model_id']): e['body'] for e in ledger.events('forecast')}
    history_snapshot = digest(_snapshot_value(sorted(history, key=lambda row: (row['day'], row['race_id']))))
    timing_supplied = not (isinstance(timing_records, tuple) and len(timing_records) == 0)
    timing_rows = list(timing_records)
    venue_snapshot = _snapshot_value(list(venue_store.records)) if venue_store is not None else None
    context_required = any(name.startswith(('context_', 'history_observed_')) for name in model.feature_names)
    declared_context = model.fit_meta.get('context', {})
    missing_context = (context_required and (
        (bool(declared_context.get('venue_file_sha256')) and venue_store is None) or
        (bool(declared_context.get('timing_file_sha256')) and not timing_supplied) or
        (not declared_context and venue_store is None and not timing_supplied)))
    require(not allow_current_geometry_assumption or venue_store is not None, 'GEOMETRY_STORE_REQUIRED_FOR_ASSUMPTION')
    for row in featured:
        prior_original = existing_originals.get((row['race_id'], model_id))
        original_binding = existing_bindings.get(row['race_id'], {})
        # A complete newly admitted card gets the actual new observation clock;
        # retrying a calendar HOLD or an admitted original keeps its old clock.
        effective_as_of = (actual_now if row['race_id'] in calendar_upgrades else
                           original_binding.get('context_as_of', requested_as_of))
        require(clock(effective_as_of) <= clock(actual_now), 'ORIGINAL_CONTEXT_CLOCK_FROM_FUTURE')
        if prior_original and row.get('cohort') == 'prospective':
            require(clock(effective_as_of) <= clock(prior_original['forecast']['prediction_at']), 'ORIGINAL_CONTEXT_AFTER_PREDICTION')
        runtime_hold = 'FEATURE_SCHEMA_CONTEXT_SIDECARS_REQUIRED' if missing_context else None
        if context_required and not missing_context and row.get('feature_status') == 'READY':
            # The runtime refuses to attach timing measurements to explicitly
            # unresolved identities, including when another target resolves the
            # same text. Core timing joins are not used as identity verification.
            identities = {str(r.get('identity_key', r.get('athlete_id', ''))) for r in row['riders'] if r.get('identity_usable') is True}
            usable_timings = [record for record in timing_rows if str((_snapshot_value(record)).get('rider_id', (_snapshot_value(record)).get('identity_key', ''))) in identities]
            try:
                row = augment_features([row], venue_store=venue_store, timing_records=usable_timings,
                        as_of=effective_as_of, allow_current_geometry_assumption=allow_current_geometry_assumption)[0]
            except (ValueError, TypeError, KeyError) as error:
                runtime_hold = 'FEATURE_SCHEMA_CONTEXT_HOLD:' + str(error)
        if tuple(row.get('feature_names', ())) != tuple(model.feature_names):
            runtime_hold = runtime_hold or 'FEATURE_SCHEMA_MISMATCH'
        schema_sha = digest(list(row.get('feature_names', ())))
        context_snapshot = digest({'venue_records': venue_snapshot, 'timing_records': _snapshot_value(timing_rows),
                                   'weather_observation': _snapshot_value(row.get('weather_observation')),
                                   'as_of': effective_as_of, 'allow_current_geometry_assumption': allow_current_geometry_assumption})
        dataset_snapshot = digest({'target_input_sha256': row['input_sha256'], 'declared_dataset_sha256': row.get('dataset_sha256'),
                                   'source_sha256': _snapshot_value(row.get('source_sha256')), 'history_snapshot_sha256': history_snapshot})
        binding = {'race_id': row['race_id'], 'day': row['day'], 'starters': [r['car'] for r in row['riders']],
                   'input_sha256': row['input_sha256'], 'cohort': row.get('cohort', 'retrospective'),
                   'cutoff_at': (row.get('cutoff_at') or row.get('published_cutoff_at')) if row.get('cohort') == 'prospective' else None,
                   'field_size': len(row['riders']), 'class': row.get('race_class', 'UNKNOWN'), 'venue': row.get('venue_code', 'UNKNOWN'),
                   'feature_model_id': model_id, 'feature_input_sha256': row.get('feature_input_sha256'),
                   'feature_schema_sha256': schema_sha, 'history_snapshot_sha256': history_snapshot,
                   'dataset_snapshot_sha256': dataset_snapshot, 'context_snapshot_sha256': context_snapshot,
                   'context_as_of': effective_as_of, 'context_evidence': _snapshot_value(row.get('context_evidence')),
                   'history_evidence_sha256': digest(_snapshot_value(row.get('history_evidence')))}
        try:
            registration = ledger.register_race(binding, source_verifier=source_verifier)
        except (ValueError, TypeError, KeyError) as error:
            registration = ledger._source_hold(row['race_id'], str(error) if isinstance(error, PolicyError) else 'SOURCE_ADMISSION_HOLD')
        try:
            require(registration['status'] == 'REGISTERED', 'SOURCE_ADMISSION_HOLD')
            require(runtime_hold is None, runtime_hold or 'FEATURE_SCHEMA_MISMATCH')
            f = copy.deepcopy(prior_original['forecast']) if prior_original else forecast_row(model, row, prediction_at=ledger._now() if row.get('cohort') == 'prospective' else None)
            require(f['status'] == 'READY', 'FEATURE_OR_MODEL_HOLD')
            if not prior_original:
                f['feature_schema_sha256'] = schema_sha
                f['context_as_of'] = effective_as_of
                f['upstream_snapshot_sha256'] = digest(binding)
            if prior_original:
                selected = copy.deepcopy(prior_original['selection'])
                if policy_config is not None:
                    requested = select_tickets(f, None, config=policy_config, decision_at=f.get('prediction_at'))
                    require(requested['policy_sha256'] == selected['policy_sha256'], 'IMMUTABLE_POLICY_CONFIG_MISMATCH')
            elif odds_mode:
                selected = _runtime_odds_selection(ledger, f, odds_snapshots=odds_snapshots,
                    odds_provider=odds_provider, odds_verifier=odds_verifier, policy_config=policy_config,
                    calibrators=calibrators, calibrator_sha256=calibrator_sha256,
                    calibration_verifier=calibration_verifier)
            else:
                selected = fixed_selection(f, k)
                if calibrators is not None:
                    selected = _runtime_confidence(ledger, selected, calibrators=calibrators,
                        calibrator_sha256=calibrator_sha256, calibration_verifier=calibration_verifier)
            ledger.register_forecast(f, selected, readback_verifier=readback_verifier)
            if selected['status'] == 'HOLD':
                for reason in selected.get('hold_reasons', ['POLICY_SELECTION_HOLD']):
                    ledger.record_hold(row['race_id'], model_id, 'POLICY_HOLD:' + reason)
        except (ValueError, KeyError) as error:
            ledger.record_hold(row['race_id'], model_id, str(error))
        top = _result_key(row)
        if top is not None or str(row.get('result_status', '')).lower() in ('cancelled', 'dead_heat'):
            active_binding = {item['race_id']: item for item in ledger.registry()}.get(row['race_id'])
            unknown_input = (active_binding is not None and _calendar_incomplete(active_binding) and
                             not ledger._source_admitted(row['race_id'], active_binding))
            outcome = {'race_id': row['race_id'], 'day': row['day'], 'top3': list(top) if top else None,
                       'status': 'settled' if top else str(row['result_status']).lower(),
                       'field_size': row.get('result_field_size') if unknown_input else len(row['riders']),
                       'class': row.get('race_class', 'UNKNOWN'), 'venue': row.get('venue_code', 'UNKNOWN')}
            if unknown_input and row.get('result_roster') is not None:
                outcome['result_roster'] = row['result_roster']
            if row.get('result_at') is not None:
                outcome['result_at'] = row['result_at']
            try:
                ledger.append_result(outcome, result_verifier=result_verifier)
            except (ValueError, KeyError) as error:
                ledger.record_hold(row['race_id'], model_id, 'RESULT_HOLD:' + str(error))
    for export in external_forecasts:
        require(isinstance(export, dict) and export.get('forecast', {}).get('model_id') != model_id, 'EXTERNAL_FROZEN_EXPORT_REQUIRED')
        ledger.register_forecast(export['forecast'], export['selection'], readback_verifier=readback_verifier)
    report = compare_models(ledger.forecasts(), ledger.latest_results(), ledger.registry(), expected_model_ids=ledger.participant_ids,
                            expected_model_sha256={m: p['model_sha256'] for m, p in ledger.participant_pins().items()})
    return {'scope': 'PARTICIPANT_SHADOW_NOT_OFFICIAL_AUTHORITY', 'coverage': ledger.coverage(), 'comparison': report,
            'production_promoted': False, 'direct_network_calls': 0,
            'callback_network_activity': 'caller_controlled_not_measured'}


def candidate_adoption_check(evidence, contract, *, evidence_verifier):
    """Review only. Paired CI is candidate minus baseline, in the frozen metric's units."""
    reasons = []
    direction = None
    try:
        require(isinstance(evidence, dict) and isinstance(contract, dict), 'EVIDENCE_AND_FROZEN_CONTRACT_REQUIRED')
        for key in ('min_races', 'min_days'):
            require(type(contract.get(key)) is int and contract[key] > 0, 'PREDECLARED_SUPPORT_REQUIRED')
        require(evidence.get('cohort') == 'prospective' and evidence.get('independent_future') is True and
                evidence.get('previously_examined') is False, 'INDEPENDENT_FUTURE_EVIDENCE_REQUIRED')
        require(evidence.get('contract_sha256') == digest(contract), 'FROZEN_CONTRACT_SHA_MISMATCH')
        require(clock(contract['frozen_at']) < clock(evidence['period_start']) <= clock(evidence['period_end']), 'CONTRACT_NOT_FROZEN_BEFORE_FUTURE_PERIOD')
        require(evidence.get('common_race_n', 0) >= contract['min_races'] and evidence.get('common_day_n', 0) >= contract['min_days'], 'INSUFFICIENT_FUTURE_SUPPORT')
        require(evidence.get('same_inputs_and_policy') is True, 'COMPARISON_INPUT_POLICY_MISMATCH')
        require(isinstance(contract.get('primary_metric'), str) and evidence.get('primary_metric') == contract['primary_metric'], 'PREDECLARED_PRIMARY_METRIC_MISMATCH')
        metric = contract['primary_metric']
        higher = {f'trifecta_hit_at_{k}' for k in (1, 2, 4, 9, 12)} | {f'exacta_hit_at_{k}' for k in (1, 2)}
        lower = {'joint_top3_log_loss', 'trifecta_nll', 'exacta_nll', 'trifecta_brier', 'exacta_brier'}
        require(metric in higher | lower, 'UNSUPPORTED_FROZEN_PRIMARY_METRIC')
        direction = 'higher_is_better' if metric in higher else 'lower_is_better'
        require(contract.get('primary_metric_direction', direction) == direction, 'FROZEN_METRIC_DIRECTION_INVALID')
        expected = contract.get('expected_model_ids')
        require(isinstance(expected, list) and len(set(expected)) == 3 and set(evidence.get('model_ids', [])) == set(expected), 'THREE_REAL_ENTRANTS_REQUIRED')
        interval = evidence.get('paired_primary_ci')
        require(isinstance(interval, list) and len(interval) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in interval), 'PAIRED_FUTURE_CI_REQUIRED')
        require(interval[0] <= interval[1] and (interval[0] > 0 if metric in higher else interval[1] < 0), 'FUTURE_IMPROVEMENT_NOT_SUPPORTED')
        required = contract.get('required_class_counts')
        require(isinstance(required, dict) and bool(required), 'PREDECLARED_CLASS_COVERAGE_REQUIRED')
        require(all(type(n) is int and n > 0 and evidence.get('class_counts', {}).get(key, 0) >= n for key, n in required.items()), 'FUTURE_CLASS_COVERAGE_INCOMPLETE')
        _verified(evidence_verifier, evidence)
    except (ValueError, TypeError, KeyError) as error:
        reasons.append(str(error) if isinstance(error, PolicyError) else 'FUTURE_EVIDENCE_INCOMPLETE')
    return {'status': 'KEEP' if reasons else 'REVIEW_READY', 'reasons': reasons,
            'changes_active_model': False, 'automatic_promotion': False, 'primary_metric_direction': direction}
