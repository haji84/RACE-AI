"""Display-only exact B/TERM name pairs, admitted from retained source bytes.

Persisted facts rely on the caller's authenticated encrypted view. Their digest
detects accidental rewriting; it is not an independent publication receipt.
No spelling, abbreviation or prefix rule is inferred from a name.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import base64
import json
import re
import sqlite3
import unicodedata

from .actions_contract import digest
from .boat_history_store import wire

MANIFEST = 'RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1'
SCHEMA = 'RACE_AI_BOAT_OFFICIAL_B_TERM_NAME_ALIAS_V1'
FIELD = 'official_name_aliases'
MAX_FACTS = 32768
MAX_ROW_FACTS = 96
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_BUILD_TOKEN = object()


class _VerifiedFacts(list):
    """An unchanged result of this process's source-reparse admission step."""
    def __init__(self, values, token):
        _need(token is _BUILD_TOKEN, 'SOURCE_REPARSE_ADMISSION_REQUIRED')
        super().__init__(values)
        self.source_check_sha256 = digest(self)


class NameAliasError(ValueError):
    def __init__(self, reason):
        self.reason_code = 'SAVED_MODEL_VIEW_NAME_ALIAS_'+reason
        super().__init__(self.reason_code)


def _need(ok, reason):
    if not ok: raise NameAliasError(reason)


def _key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def _time(value, *, optional=False):
    if value is None and optional: return None
    try:
        _need(type(value) is str and 0 < len(value) <= 64, 'CLOCK_INVALID')
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(at.utcoffset() is not None, 'CLOCK_INVALID')
        return at
    except (ValueError, TypeError, OverflowError):
        raise NameAliasError('CLOCK_INVALID') from None


def _day(value):
    try:
        _need(type(value) is str and date.fromisoformat(value).isoformat() == value, 'DAY_INVALID')
        return date.fromisoformat(value)
    except (ValueError, TypeError): raise NameAliasError('DAY_INVALID') from None


def _b_url(day):
    d = _day(day)
    return f'https://www1.mbrace.or.jp/od2/B/{d:%Y%m}/b{d:%y%m%d}.lzh'


def full_source_kind(fact):
    return fact['full_source'].get('kind', 'VERIFIED_RACER_REGISTRY')


def _program_url(url, rid):
    _need(type(url) is str and len(url) <= 2000, 'PROGRAM_URL_INVALID')
    p = urlsplit(url); q = parse_qs(p.query, keep_blank_values=True)
    _need(p.scheme == 'https' and p.netloc == 'www.boatrace.jp' and p.path == '/owpc/pc/race/racelist'
          and not p.fragment and set(q) == {'hd', 'jcd', 'rno'} and all(len(v) == 1 for v in q.values())
          and q['hd'] == [rid[:8]] and q['jcd'] == [rid[9:11]] and q['rno'] == [str(int(rid[-2:]))], 'PROGRAM_URL_INVALID')


def validate_fact(fact, *, race_id=None, day=None):
    from .boat_racer_term import term_info
    fields = {'schema', 'race_id', 'event_date_jst', 'number', 'registration_no',
              'short_name', 'full_name', 'b_source', 'full_source', 'display_only', 'fact_sha256'}
    _need(type(fact) is dict and set(fact) == fields and fact['schema'] == SCHEMA
          and fact['display_only'] is True, 'FACT_SCHEMA_INVALID')
    d = _day(fact['event_date_jst']); rid = fact['race_id']
    _need(type(rid) is str and re.fullmatch(d.strftime('%Y%m%d')+r'-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])', rid)
          and (race_id is None or rid == race_id) and (day is None or fact['event_date_jst'] == day), 'RACE_DAY_INVALID')
    _need(type(fact['number']) is int and 1 <= fact['number'] <= 6 and
          type(fact['registration_no']) is str and re.fullmatch(r'[0-9]{4}', fact['registration_no']), 'ROSTER_INVALID')
    _need(all(type(fact[k]) is str and 0 < len(fact[k]) <= 128 and fact[k] == fact[k].strip()
              for k in ('short_name', 'full_name')) and _key(fact['short_name']) != _key(fact['full_name']), 'NAME_PAIR_INVALID')
    b, full = fact['b_source'], fact['full_source']
    _need(type(b) is dict and set(b) == {'source_url', 'source_sha256', 'captured_at'}
          and b['source_url'] == _b_url(fact['event_date_jst']) and type(b['source_sha256']) is str
          and _SHA.fullmatch(b['source_sha256']), 'B_SOURCE_INVALID')
    _time(b['captured_at'], optional=True)
    _need(type(full) is dict and type(full.get('source_sha256')) is str
          and _SHA.fullmatch(full['source_sha256']), 'FULL_SOURCE_INVALID')
    if full.get('kind') == 'SAME_RACE_PROGRAM':
        _need(set(full) == {'kind', 'source_url', 'source_sha256', 'captured_at', 'native_payload_sha256',
            'native_capsule_sha256', 'physical_receipt_sha256', 'repository_id', 'run_id', 'head_sha',
            'artifact_id', 'created_at', 'evidence_scope'} and full['repository_id'] == '1416489937'
            and type(full['run_id']) is str and re.fullmatch(r'[1-9][0-9]{0,19}', full['run_id'])
            and type(full['head_sha']) is str and re.fullmatch(r'[a-f0-9]{40}', full['head_sha'])
            and type(full['artifact_id']) is int and full['artifact_id'] > 0
            and full['evidence_scope'] == 'AUTHENTICATED_NATIVE_PROGRAM'
            and all(type(full[k]) is str and _SHA.fullmatch(full[k]) for k in
                    ('native_payload_sha256', 'physical_receipt_sha256'))
            and (full['native_capsule_sha256'] is None or type(full['native_capsule_sha256']) is str
                 and _SHA.fullmatch(full['native_capsule_sha256'])), 'PROGRAM_FULL_SOURCE_INVALID')
        _program_url(full['source_url'], rid)
        from .boat_all_model_cycle import _not_before
        _need(_not_before(full['captured_at'], full['created_at']), 'PROGRAM_RECEIPT_CLOCK_INVALID')
    else:
        _need(set(full) == {'term', 'source_url', 'source_sha256', 'captured_at', 'verified'}
              and full['verified'] is True, 'FULL_SOURCE_INVALID')
        _need(full['source_url'] == term_info(full['term'])['source_url'], 'FULL_SOURCE_URL_INVALID')
    _time(full['captured_at'])
    _need(type(fact['fact_sha256']) is str and _SHA.fullmatch(fact['fact_sha256'])
          and fact['fact_sha256'] == digest({k:v for k,v in fact.items() if k != 'fact_sha256'}), 'FACT_DIGEST_INVALID')
    return fact


def collect_alias_facts(rows):
    output = []; seen = set(); pairs = {}
    for row in rows:
        values = row.get(FIELD, [])
        _need(type(values) is list and len(values) <= MAX_ROW_FACTS, 'ROW_FACT_BOUND_INVALID')
        for fact in values:
            validate_fact(fact, race_id=row['race_id'], day=row['event_date_jst'])
            binding = (fact['number'], fact['registration_no'], _key(fact['short_name']))
            full = _key(fact['full_name'])
            _need(binding not in pairs or pairs[binding] == full, 'CONFLICTING_FULL_NAME')
            pairs[binding] = full
            if fact['fact_sha256'] not in seen:
                output.append(deepcopy(fact)); seen.add(fact['fact_sha256'])
    _need(len(output) <= MAX_ROW_FACTS, 'ROW_FACT_BOUND_INVALID')
    return output


def person_aliases(person, facts):
    pid = next((person[k] for k in ('registration_no', 'registration_number', 'registration_id',
                                  'racer_registration_id', 'racer_id') if person.get(k) is not None), None)
    return [f for f in facts if f['number'] == person['number'] and f['registration_no'] == pid]


def validate_person_alias(person, facts):
    matches = person_aliases(person, facts)
    if not matches or person.get('name') is None: return
    key = _key(person['name']); source = person.get('name_source') or {}
    _need(any(key in (_key(f['short_name']), _key(f['full_name'])) for f in matches), 'NAME_OUTSIDE_EXACT_PAIR')
    if any(key == _key(f['short_name']) for f in matches):
        _need(source.get('kind') == 'SAME_RACE_PROGRAM' and any(
            source.get('source_sha256') == f['b_source']['source_sha256'] and
            source.get('source_url') == f['b_source']['source_url'] for f in matches), 'B_NAME_SOURCE_MISMATCH')
    elif source.get('kind') == 'VERIFIED_RACER_REGISTRY':
        _need(any(full_source_kind(f) == 'VERIFIED_RACER_REGISTRY' and
                  source.get('source_sha256') == f['full_source']['source_sha256'] and
                  source.get('source_url') == f['full_source']['source_url'] for f in matches), 'FULL_NAME_SOURCE_MISMATCH')
    elif source.get('kind') == 'SAME_RACE_PROGRAM' and any(full_source_kind(f) == 'SAME_RACE_PROGRAM' for f in matches):
        _need(any(full_source_kind(f) == 'SAME_RACE_PROGRAM' and
                  source.get('source_sha256') == f['full_source']['source_sha256'] and
                  source.get('source_url') == f['full_source']['source_url'] for f in matches), 'FULL_NAME_SOURCE_MISMATCH')


def exact_alias_pair(left, right, facts):
    # Both candidates were separately validated, including the actual short
    # name's B source. Different full names never become aliases via a pid.
    matches = person_aliases(left, facts)
    a, b = _key(left['name']), _key(right['name'])
    return any({a, b} == {_key(f['short_name']), _key(f['full_name'])} for f in matches)


def _term_names(path, now):
    from .boat_racer_term import extract_term, parse_term, term_info
    p = Path(path)
    _need(p.is_file() and not p.is_symlink() and 16 <= p.stat().st_size <= 8*1024*1024, 'RACER_DB_BOUND_INVALID')
    db = sqlite3.connect(p.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
    try:
        _need(db.execute('PRAGMA quick_check').fetchall() == [('ok',)] and
              db.execute('SELECT schema FROM meta').fetchall() == [('RACE_AI_ALL_BOAT_RACERS_V1',)], 'RACER_DB_INVALID')
        sources = db.execute("SELECT id,sha,logical_key,url,captured_at,raw FROM sources WHERE kind='TERM'").fetchall()
        _need(len(sources) <= 16, 'TERM_SOURCE_BOUND_INVALID')
        verified = []
        for sid, sha, term, url, captured, raw in sources:
            _need(type(raw) is bytes and sha256(raw).hexdigest() == sha and url == term_info(term)['source_url']
                  and _time(captured) <= now, 'TERM_SOURCE_HASH_URL_OR_CLOCK_INVALID')
            parsed = parse_term(extract_term(raw, term=term), term=term)
            expected = {r['racer_id']:{k:v for k,v in r.items() if k != 'courses'} for r in parsed}
            stored = {pid:json.loads(body) for pid,body in db.execute('SELECT racer_id,document FROM racers WHERE source_id=?', (sid,))}
            _need(stored == expected, 'TERM_DOCUMENT_REPARSE_MISMATCH')
            verified.append((term, _time(captured), sid, expected,
                dict(term=term, source_url=url, source_sha256=sha, captured_at=captured, verified=True)))
        if not verified: return {}, None
        latest = max(verified, key=lambda x:x[:3])
        return latest[3], latest[4]
    finally: db.close()


def _b_programs(manifest, now):
    from .program_race_isolation import normalize_races
    from .official_lzh_extract import extract_daily_lzh
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(manifest) is dict and set(manifest) == {'schema', 'b_sources'} and manifest['schema'] == MANIFEST
          and type(manifest['b_sources']) is list and len(manifest['b_sources']) <= 16, 'MANIFEST_INVALID')
    output = []
    for source in manifest['b_sources']:
        _need(type(source) is dict and set(source) <= {'day', 'raw_b_base64', 'source_url', 'source_sha256', 'captured_at'}
              and all(k in source for k in ('day', 'raw_b_base64', 'source_url', 'source_sha256')), 'B_SOURCE_SCHEMA_INVALID')
        day = _day(source['day']); encoded = source['raw_b_base64']
        _need(type(encoded) is str and 0 < len(encoded) <= 3*1024*1024, 'B_SOURCE_BOUND_INVALID')
        try: raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError): raise NameAliasError('B_BASE64_INVALID') from None
        _need(0 < len(raw) <= 2*1024*1024 and base64.b64encode(raw).decode() == encoded
              and sha256(raw).hexdigest() == source['source_sha256'] and source['source_url'] == _b_url(source['day']),
              'B_SOURCE_HASH_OR_URL_INVALID')
        captured = source.get('captured_at'); clock = _time(captured, optional=True)
        _need(clock is None or clock <= now, 'B_SOURCE_FUTURE_CLOCK')
        program = normalize_races(extract_daily_lzh(raw, 'B'+day.strftime('%y%m%d')+'.TXT'), day=day,
            source_url=source['source_url'], observed_at=captured, archive_sha256=source['source_sha256'])
        output.append((source, program))
    return output


def build_name_aliases(manifest, racers_path, *, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    names, full_source = _term_names(racers_path, now); facts = []; seen = set()
    for source, program in _b_programs(manifest, now):
        for venue in program['venues']:
            for race in venue['races']:
                for person in race['boats']:
                    pid = person['racer_registration_id']; full = names.get(pid, {}).get('name'); short = person['name']
                    if full is None or _key(full) == _key(short): continue
                    f = dict(schema=SCHEMA, race_id=race['race_id'], event_date_jst=source['day'], number=person['lane'],
                        registration_no=pid, short_name=short, full_name=full, display_only=True,
                        b_source=dict(source_url=source['source_url'], source_sha256=source['source_sha256'], captured_at=source.get('captured_at')),
                        full_source=deepcopy(full_source))
                    f['fact_sha256'] = digest(f); validate_fact(f)
                    if f['fact_sha256'] not in seen: facts.append(f); seen.add(f['fact_sha256'])
                    _need(len(facts) <= MAX_FACTS, 'FACT_COUNT_BOUND_INVALID')
    return _VerifiedFacts(sorted(facts, key=lambda f:(f['race_id'], f['number'], f['fact_sha256'])), _BUILD_TOKEN)


def build_program_name_aliases(manifest, payload, receipt, *, now=None):
    """Use an authenticated saved P1 program; no model invocation or source GET.

    The external caller supplies the actual independently read physical receipt,
    exactly as project_round requires. Capsule hashes/bindings are checked here
    without repeating model output replay; legacy current-input journals retain
    their explicit payload/receipt scope and do not gain a capsule assertion.
    """
    from . import boat_all_model_cycle as E
    now = datetime.now(timezone.utc) if now is None else now
    programs = _b_programs(manifest, now)
    _need(type(payload) is dict and payload.get('schema') == E.SCHEMA and payload.get('stage') in ('P0', 'P1')
          and payload.get('source_requests') == 0 and payload.get('originals_overwritten') is False,
          'PROGRAM_PAYLOAD_SCHEMA_INVALID')
    proof = E._receipt(receipt, digest(payload), payload.get('source_code_commit'), payload.get('run_id'))
    _need(_time(proof['created_at']) <= now and E._not_before(payload['generated_at'], proof['created_at']),
          'PROGRAM_PHYSICAL_RECEIPT_INVALID')
    capsules = E._verify_native_input_capsules(payload, replay_outputs=False)
    if payload['stage'] == 'P0': return _VerifiedFacts([], _BUILD_TOKEN)
    caps = {c['race_id']:c for c in capsules}
    contexts = payload.get('current_inputs'); reports = payload.get('dispatch_reports')
    _need(type(contexts) is list and len(contexts) <= 288 and type(reports) is list and len(reports) <= 288,
          'PROGRAM_INPUT_BOUND_INVALID')
    schedules = {}
    for report in reports:
        rows = report.get('schedule')
        _need(type(rows) is list and len(rows) == 1 and rows[0]['race_id'] not in schedules, 'PROGRAM_SCHEDULE_INVALID')
        schedules[rows[0]['race_id']] = rows[0]
    verified = {}
    for context in contexts:
        checked, active, withdrawn = E._context(context['program'], context['beforeinfo'], context['as_of'])
        program = checked['program']; rid = program['race_id']; row = schedules.get(rid)
        _need(rid not in verified and row is not None and row['stage'] == 'P1'
              and row['cutoff_at'] == program['closed_at'] and _time(checked['as_of']) <= _time(payload['generated_at']),
              'PROGRAM_INPUT_SCHEDULE_MISMATCH')
        expected = {p['lane']:(p['registration_number'], p.get('name')) for p in active}
        actual = {p['number']:(p['registration_no'], p.get('name')) for p in row['participants']}
        _need(actual == expected and len(actual) == len(row['participants']), 'PROGRAM_NAME_OR_ROSTER_MISMATCH')
        # The schedule is itself hashed into capsule group/dispatch bindings.
        verified[rid] = (program, expected)
    facts = []; seen = set()
    for source, b in programs:
        for venue in b['venues']:
            for race in venue['races']:
                rid = race['race_id']
                if rid not in verified: continue
                program, people = verified[rid]
                for person in race['boats']:
                    lane, pid, short = person['lane'], person['racer_registration_id'], person['name']
                    if lane not in people: continue
                    _need(people[lane][0] == pid, 'PROGRAM_B_REGISTRATION_MISMATCH')
                    full = people[lane][1]
                    _need(type(full) is str and full, 'PROGRAM_FULL_NAME_MISSING')
                    if _key(short) == _key(full): continue
                    full_source = dict(kind='SAME_RACE_PROGRAM', source_url=program['source_url'],
                        source_sha256=program['source_sha256'], captured_at=program['captured_at'],
                        native_payload_sha256=digest(payload), native_capsule_sha256=caps.get(rid, {}).get('capsule_sha256'),
                        physical_receipt_sha256=digest(proof), repository_id=proof['repository_id'],
                        run_id=str(proof['run_id']), head_sha=proof['head_sha'], artifact_id=proof['artifact_id'],
                        created_at=proof['created_at'], evidence_scope='AUTHENTICATED_NATIVE_PROGRAM')
                    f = dict(schema=SCHEMA, race_id=rid, event_date_jst=source['day'], number=lane,
                        registration_no=pid, short_name=short, full_name=full, display_only=True,
                        b_source=dict(source_url=source['source_url'], source_sha256=source['source_sha256'],
                                      captured_at=source.get('captured_at')), full_source=full_source)
                    f['fact_sha256'] = digest(f); validate_fact(f)
                    if f['fact_sha256'] not in seen: facts.append(f); seen.add(f['fact_sha256'])
                    _need(len(facts) <= MAX_FACTS, 'FACT_COUNT_BOUND_INVALID')
    return _VerifiedFacts(sorted(facts, key=lambda f:(f['race_id'], f['number'], f['fact_sha256'])), _BUILD_TOKEN)


def attach_name_aliases(view, facts):
    from .saved_view_feed import forecast_anchor, forecast_inventory
    _need(isinstance(facts, list) and len(facts) <= MAX_FACTS, 'FACT_COUNT_BOUND_INVALID')
    _need(not facts or isinstance(facts, _VerifiedFacts) and facts.source_check_sha256 == digest(facts),
          'SOURCE_REPARSE_ADMISSION_REQUIRED')
    by_race = {}
    for fact in facts:
        validate_fact(fact); by_race.setdefault(fact['race_id'], []).append(fact)
    output = deepcopy(view); changed = False
    for row in output['records']:
        new = by_race.get(row['race_id'], [])
        if not new: continue
        people = [*row.get('participants', []), *row.get('withdrawn_participants', []),
                  *[p for snapshot in row.get('saved_participant_rosters', []) for p in snapshot['participants']]]
        bindings = {}
        for person in people:
            values = [person[k] for k in ('registration_no', 'registration_number', 'registration_id',
                      'racer_registration_id', 'racer_id') if person.get(k) is not None]
            if not values: continue  # An explicitly unknown withdrawal stays unknown here.
            _need(all(type(v) is str and re.fullmatch(r'[0-9]{4}', v) and v == values[0] for v in values)
                  and type(person.get('number')) is int and 1 <= person['number'] <= 6, 'ATTACH_ROSTER_INVALID')
            number, pid = person['number'], values[0]
            _need(number not in bindings or bindings[number] == pid, 'ATTACH_ROSTER_MISMATCH')
            _need(pid not in bindings.values() or bindings.get(number) == pid, 'ATTACH_ROSTER_MISMATCH')
            bindings[number] = pid
        scoped = []
        for fact in new:
            if fact['number'] not in bindings: continue
            _need(bindings[fact['number']] == fact['registration_no'], 'ATTACH_ROSTER_MISMATCH')
            scoped.append(fact)
        if not scoped: continue
        merged = collect_alias_facts([row, dict(row, **{FIELD:scoped})])
        if merged != row.get(FIELD, []): row[FIELD] = merged; changed = True
    if not changed: return view
    output['forecast_base_sha256'] = forecast_anchor(view)
    _need(forecast_inventory(output) == forecast_inventory(view), 'ORIGINAL_CHANGED')
    _need(len(wire(output).encode()) <= 64*1024*1024, 'VIEW_BOUND_INVALID')
    return output
