"""Pure parser for the observed BOATCAST three-column original exhibition tab.

No network, media handling, rights grant or durable-save claim. These public TSV
bodies have names, but no registration IDs, dated body or closing time. Identity
therefore binds exact URLs and six names to a separately approved program.
Venue-defined timings must not be treated as cross-venue calibrated measures.
"""
from datetime import datetime
import hashlib
import re

import unicodedata
if __package__:
    from .race_contract import canonical, program_digest, stamp, JST
else:
    from race_contract import canonical, program_digest, stamp, JST


def canonical_name(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))

MAX_BYTES = 1024 * 1024
FIELDS = ('lap_s', 'turn_s', 'straight_s')
LABELS = ('一周', 'まわり足', '直線')
TOP = {'schema_version', 'kind', 'race_id', 'closed_at', 'program_identity_sha256',
       'status', 'body_date_verified', 'identity_evidence', 'capture_eligible_pre_race',
       'sources', 'measurement_scope', 'boats', 'snapshot_id'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def endpoint(race_id, component):
    require(isinstance(race_id, str), 'original race identity invalid')
    match = re.fullmatch(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])', race_id)
    require(match is not None and component in {'original', 'standard'}, 'original race identity invalid')
    day, venue, number = match.groups()
    try:
        datetime.strptime(day, '%Y%m%d')
    except ValueError as exc:
        raise ValueError('original race date invalid') from exc
    path, prefix = ('txt', 'bc_oriten') if component == 'original' else ('hp_txt', 'bc_j_tkz')
    return f'https://race.boatcast.jp/{path}/{venue}/{prefix}_{day}_{venue}_{number}.txt'


def _time(value):
    return datetime.fromisoformat(stamp(value))


def _keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), 'original fields invalid')


def _rows(raw):
    require(isinstance(raw, bytes) and 1 <= len(raw) <= MAX_BYTES, 'original source bytes outside bounds')
    rows = [line.split('\t') for line in raw.decode('utf-8-sig').splitlines()]
    require(len(rows) == 9 and rows[0] == ['data='], 'original source envelope invalid')
    return rows


def _measurement(token):
    if token == '-':
        return None
    require(isinstance(token, str) and re.fullmatch(r'[0-9]{1,3}\.[0-9]{2}', token) is not None,
            'original numeric token invalid')
    value = float(token)
    require(0 < value <= 999.99, 'original numeric value outside bounds')
    return value


def _source(raw, component, url, captured):
    return dict(component=component, source_url=url, source_sha256=hashlib.sha256(raw).hexdigest(),
                captured_at=stamp(captured), available_at=stamp(captured), upstream_published_at=None)


def parse_original(raw, companion_raw, *, race, source_url, captured_at,
                   companion_source_url, companion_captured_at, now):
    """Parse supplied bytes only; registration identity comes from race, not TSV."""
    try:
        race_id = race['race_id']
        require(source_url == endpoint(race_id, 'original')
                and companion_source_url == endpoint(race_id, 'standard'), 'original source URL mismatch')
        digest = program_digest(race)
        first, second = _rows(raw), _rows(companion_raw)
        require(first[1] == ['1', '3'] and len(first[2]) == 3
                and tuple(canonical_name(label) for label in first[2]) == LABELS,
                'unsupported original timing columns or source status')
        require(second[1] == ['1'] and all(len(row) == 29 for row in second[2:8])
                and len(second[8]) == 18, 'standard exhibition source shape invalid')
        # Triplets are structural evidence only. They are not exported as ST or
        # interpreted as physical entry course by this original-timing adapter.
        triplets = [second[8][offset:offset+3] for offset in range(0, 18, 3)]
        require([row[0] for row in triplets] == [str(n) for n in range(1, 7)],
                'standard exhibition six-boat structure invalid')
        identities = {boat['lane']: boat for boat in race['boats']}
        boats = []
        for lane, (row, standard) in enumerate(zip(first[3:9], second[2:8]), 1):
            require(len(row) == 5 and row[0] == str(lane), 'original six-lane structure invalid')
            expected = identities[lane]
            require(canonical_name(row[1]) == canonical_name(standard[0]) == canonical_name(expected['name']),
                    'original and program racer names differ')
            times = {key: _measurement(token) for key, token in zip(FIELDS, row[2:5])}
            display = _measurement(standard[1])
            require(display is None or display <= 100, 'standard display outside bounds')
            missing = {key: 'SOURCE_NOT_PUBLISHED' for key, value in times.items() if value is None}
            if display is None:
                missing['display_time_s'] = 'SOURCE_NOT_PUBLISHED'
            boats.append(dict(lane=lane, racer_registration_id=expected['racer_registration_id'],
                              name=expected['name'], registration_source='approved_program',
                              display_time_s=display, original_times=times, missing_reasons=missing))
        sources = [_source(raw, 'original', source_url, captured_at),
                   _source(companion_raw, 'standard', companion_source_url, companion_captured_at)]
        present = sum(value is not None for boat in boats
                      for value in [boat['display_time_s'], *boat['original_times'].values()])
        close = _time(race['closed_at'])
        value = dict(schema_version=1, kind='boatcast_original', race_id=race_id,
                     closed_at=stamp(race['closed_at']), program_identity_sha256=digest,
                     status='AVAILABLE' if present == 24 else 'PARTIAL' if present else 'PENDING',
                     body_date_verified=False, identity_evidence='EXACT_SOURCE_URLS_AND_SIX_PROGRAM_NAMES',
                     capture_eligible_pre_race=all(_time(source['captured_at']) < close for source in sources),
                     sources=sources, measurement_scope=dict(venue_code=race_id[9:11],
                         labels=dict(zip(FIELDS, first[2])),
                         definition_status='VENUE_DEFINED_NOT_CROSS_VENUE_CALIBRATED'), boats=boats)
        value['snapshot_id'] = hashlib.sha256(canonical(value)).hexdigest()
        validate_original_observation(value, race, now)
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError('original exhibition source malformed') from exc


def validate_original_observation(value, race, now):
    """Strict normalized projection; cloud receipts remain a separate authority."""
    try:
        _keys(value, TOP)
        raw = canonical({key: item for key, item in value.items() if key != 'snapshot_id'})
        require(value['snapshot_id'] == hashlib.sha256(raw).hexdigest(), 'original content hash mismatch')
        require(type(value['schema_version']) is int and value['schema_version'] == 1
                and value['kind'] == 'boatcast_original', 'original schema invalid')
        race_id = race['race_id']
        require(value['race_id'] == race_id and value['closed_at'] == stamp(race['closed_at'])
                and value['program_identity_sha256'] == program_digest(race), 'original program identity mismatch')
        require(value['body_date_verified'] is False
                and value['identity_evidence'] == 'EXACT_SOURCE_URLS_AND_SIX_PROGRAM_NAMES',
                'original body cannot prove date or registration')
        clock, close = _time(now), _time(race['closed_at'])
        require(isinstance(value['sources'], list) and len(value['sources']) == 2, 'original sources incomplete')
        captures = []
        for source, component in zip(value['sources'], ('original', 'standard')):
            _keys(source, {'component', 'source_url', 'source_sha256', 'captured_at', 'available_at', 'upstream_published_at'})
            require(source['component'] == component and source['source_url'] == endpoint(race_id, component),
                    'original source URL mismatch')
            require(isinstance(source['source_sha256'], str)
                    and re.fullmatch(r'[0-9a-f]{64}', source['source_sha256']) is not None, 'original source hash invalid')
            captured = _time(source['captured_at'])
            require(_time(source['available_at']) == captured <= clock
                    and captured.astimezone(JST).date() >= close.astimezone(JST).date()
                    and source['upstream_published_at'] is None, 'original capture/availability invalid')
            captures.append(captured)
        require(type(value['capture_eligible_pre_race']) is bool
                and value['capture_eligible_pre_race'] == all(captured < close for captured in captures),
                'original capture phase mismatch')
        scope = value['measurement_scope']
        _keys(scope, {'venue_code', 'labels', 'definition_status'})
        _keys(scope['labels'], FIELDS)
        require(scope['venue_code'] == race_id[9:11]
                and scope['definition_status'] == 'VENUE_DEFINED_NOT_CROSS_VENUE_CALIBRATED'
                and tuple(canonical_name(scope['labels'][key]) for key in FIELDS) == LABELS,
                'original venue measurement scope invalid')
        identities = {boat['lane']: boat for boat in race['boats']}
        require(isinstance(value['boats'], list) and len(value['boats']) == 6, 'original boats incomplete')
        seen = set(); present = 0
        for boat in value['boats']:
            _keys(boat, {'lane', 'racer_registration_id', 'name', 'registration_source',
                         'display_time_s', 'original_times', 'missing_reasons'})
            lane = boat['lane']
            require(type(lane) is int and lane in identities and lane not in seen, 'original lane invalid')
            seen.add(lane); expected = identities[lane]
            require(boat['racer_registration_id'] == expected['racer_registration_id']
                    and canonical_name(boat['name']) == canonical_name(expected['name'])
                    and boat['registration_source'] == 'approved_program', 'original racer identity mismatch')
            _keys(boat['original_times'], FIELDS)
            require(isinstance(boat['missing_reasons'], dict), 'original missing reasons invalid')
            metrics = {'display_time_s': boat['display_time_s'], **boat['original_times']}
            require(set(boat['missing_reasons']) == {key for key, number in metrics.items() if number is None},
                    'original missing reason/value conflict')
            for key, number in metrics.items():
                if number is None:
                    require(boat['missing_reasons'][key] == 'SOURCE_NOT_PUBLISHED', 'original missing reason invalid')
                else:
                    maximum = 100 if key == 'display_time_s' else 999.99
                    require(type(number) in (int, float) and 0 < number <= maximum
                            and float(f'{number:.2f}') == number, 'original numeric value invalid')
                    present += 1
        require(value['status'] == ('AVAILABLE' if present == 24 else 'PARTIAL' if present else 'PENDING'),
                'original timing coverage status mismatch')
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError('original normalized observation malformed') from exc


def validate_original_receipt(value,race,now):
    """Validate measured current-day runner/cloud evidence, without storage I/O."""
    try:
        require(isinstance(now,datetime) and now.tzinfo is not None and now.utcoffset() is not None,
                'actual original receipt clock required')
        clock,close=_time(now),_time(race['closed_at']);day=close.astimezone(JST).date()
        require(clock.astimezone(JST).date()==day,'current JST original receipt required')
        _keys(value,{'schema_version','request_id','observation','runner_saved_at','cloud_saved_at',
                     'cloud_eligible_pre_race','program_identity_sha256'})
        require(type(value['schema_version']) is int and value['schema_version']==1
            and isinstance(value['request_id'],str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',value['request_id']) is not None
            and value['program_identity_sha256']==program_digest(race) and len(canonical(value))<=256_000,
            'original receipt schema/identity invalid')
        observation=value['observation'];validate_original_observation(observation,race,clock)
        runner,cloud=_time(value['runner_saved_at']),_time(value['cloud_saved_at'])
        captures=[_time(source['captured_at']) for source in observation['sources']]
        require(max(captures)<=runner<=cloud<=clock
            and all(value.astimezone(JST).date()==day for value in [*captures,runner,cloud]),
            'original runner/cloud time invalid')
        eligible=observation['capture_eligible_pre_race'] and runner<close and cloud<close
        require(type(value['cloud_eligible_pre_race']) is bool and value['cloud_eligible_pre_race']==eligible,
            'original actual cloud eligibility invalid')
        return value
    except (TypeError,KeyError,AttributeError,UnicodeError,OverflowError) as exc:
        raise ValueError('original receipt malformed') from exc
