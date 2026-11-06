"""Official exhibition observations bound to the program's actual entrants.

Only explicit program withdrawals remove an exhibition requirement. An absent
active entrant clock remains pending, independently of optional start timing.
This parser has no transport, predictor, source permission or receipt writer.
"""
import re
import unicodedata

from .boat_active_roster import active_roster
from .boat_official_program import SCHEMA as PROGRAM_SCHEMA
from .boat_observation_context import (
    MISSING, _Unsupported, _cells, _context, _identity, _moment, _number,
    _one, _participant, _table, _weather, eligibility_for_cutoff,
)

SCHEMA = 'RACE_AI_BOAT_ACTIVE_EXHIBITION_V1'


def _need(ok, reason):
    if not ok:
        raise ValueError('BOAT_ACTIVE_EXHIBITION_'+reason)


def _bound_roster(rows):
    active_roster(rows, identity_key='registration_number')
    _need(all(row.get('name') is None or type(row['name']) is str for row in rows), 'ROSTER_NAME_INVALID')
    return {row['lane']: row for row in rows}


def _program(program, captured_at):
    _need(type(program) is dict and program.get('schema') == PROGRAM_SCHEMA
          and program.get('body_identity_verified') is True
          and program.get('status') == 'OFFICIAL_BODY_IDENTITY_VERIFIED'
          and program.get('race_status') == 'LISTED', 'VERIFIED_LISTED_PROGRAM_REQUIRED')
    expected = _identity(program['source_url'], 'racelist')
    day, venue, number = expected
    _need(program['race_id'] == f'{day}-{venue}-{number:02d}', 'PROGRAM_RACE_MISMATCH')
    _need(type(program.get('source_sha256')) is str
          and re.fullmatch(r'[0-9a-f]{64}', program['source_sha256']), 'PROGRAM_SOURCE_HASH_INVALID')
    captured = _moment(program['captured_at'])
    _need(captured <= _moment(captured_at), 'PROGRAM_CAPTURE_AFTER_EXHIBITION_CAPTURE')
    cutoff = _moment(program['closed_at'])
    _need(cutoff.strftime('%Y%m%d') == day and cutoff.utcoffset().total_seconds() == 9*3600,
          'PROGRAM_CUTOFF_IDENTITY_INVALID')
    rows = program['boats']
    _need(type(rows) is list and 3 <= len(rows) <= 6, 'PROGRAM_ROSTER_INVALID')
    by_lane, registrations = {}, set()
    for row in rows:
        _need(type(row) is dict, 'PROGRAM_ROW_INVALID')
        lane, registration = row.get('lane'), row.get('racer_registration_id')
        _need(type(lane) is int and 1 <= lane <= 6 and lane not in by_lane, 'PROGRAM_LANE_INVALID')
        _need(row.get('entry_status') in ('listed', 'withdrawn'), 'PROGRAM_DISPOSITION_INVALID')
        _need(row.get('race_id') == program['race_id'] and row.get('closed_at') == program['closed_at']
              and row.get('source_url') == program['source_url'] and row.get('verified_source') is True
              and _moment(row.get('captured_at')) == captured, 'PROGRAM_ROW_SOURCE_MISMATCH')
        _need(registration is None and row['entry_status'] == 'withdrawn'
              or type(registration) is str and re.fullmatch(r'[0-9]{4}', registration)
              and registration not in registrations, 'PROGRAM_REGISTRATION_INVALID')
        if registration is not None:
            registrations.add(registration)
        by_lane[lane] = row
    active = [dict(lane=row['lane'], registration_number=row['racer_registration_id'], name=row.get('name'))
              for row in sorted(rows, key=lambda row:row['lane']) if row['entry_status'] == 'listed']
    bound = _bound_roster(active)
    _need(program.get('active_lanes') == list(bound) and program.get('active_entrant_count') == len(bound),
          'PROGRAM_ACTIVE_ROSTER_MISMATCH')
    withdrawn = sorted(lane for lane,row in by_lane.items() if row['entry_status'] == 'withdrawn')
    return active, by_lane, withdrawn


def _starts(frame, source_rows):
    table = _table(frame, 'スタート展示', 'コース', 'ST')
    rows = list(_one(table.find('tbody'), layout=True).find('tr'))
    _need(len(rows) <= 6, 'START_GRID_TOO_LARGE')
    result, positions, seen = {}, set(), set()
    for row in rows:
        if (len(_cells(row)) == 1 and _cells(row)[0].attrs.get('colspan') == '3'
                and not row.text().strip() and not list(row.find('img'))
                and not list(row.find(css='table1_boatImage1Number'))
                and not list(row.find(css='table1_boatImage1Time'))):
            continue
        image = _one((node for node in row.find('img') if re.fullmatch(
            r'/static_extra/pc/images/img_boat2_[1-6]\.png', node.attrs.get('src', ''))), layout=True)
        lane = int(image.attrs['src'][-5])
        _need(lane in source_rows and lane not in seen, 'START_IDENTITY_INVALID')
        seen.add(lane)
        if source_rows[lane]['entry_status'] == 'withdrawn':
            continue
        position = _one(row.find(css='table1_boatImage1Number'), layout=True).text().strip()
        token = _one(row.find(css='table1_boatImage1Time'), layout=True).text().strip()
        _need(re.fullmatch(r'[1-6]', position)
              and int(position) not in positions, 'START_IDENTITY_INVALID')
        positions.add(int(position))
        if token in MISSING:
            value, status = None, 'NOT_PUBLISHED'
        elif re.fullmatch(r'0?\.[0-9]{2}', token):
            value, status = float(token), 'OK'
        elif re.fullmatch(r'[FL](?:0?\.[0-9]{2})?', token):
            value, status = None, token[0]
        else:
            raise ValueError('BOAT_ACTIVE_EXHIBITION_START_VALUE_INVALID')
        result[lane] = dict(exhibition_st=value, exhibition_st_status=status,
            exhibition_st_raw=token or None, exhibition_source_position_number=int(position), exhibition_course=None)
    return result


def parse_active_beforeinfo(raw: bytes, *, program, source_url, captured_at):
    """Return pinned-style observations and supplemental context for 3..6 entrants.

    ``program`` is the owned source-attested official program. Late retained
    captures can be replayed, with ``eligible_pre_race`` explicitly false.
    The program's listed roster remains authoritative when a clock is blank.
    """
    active, source_rows, withdrawn = _program(program, captured_at)
    frame, bound, context = _context(raw, kind='beforeinfo', source_url=source_url,
        captured_at=captured_at, expected_race_id=program['race_id'], roster=active, roster_validator=_bound_roster)
    _need(_moment(context['source_cutoff_at']) == _moment(program['closed_at']), 'PROGRAM_EXHIBITION_CUTOFF_MISMATCH')
    try:
        table = _table(frame, 'ボートレーサー', '体重', '展示', 'チルト', 'プロペラ', '部品交換', '調整重量')
        starts = _starts(frame, source_rows)
        participants, seen = [], set()
        for body in table.find('tbody'):
            rows = list(body.find('tr'))
            cells = [_cells(row) for row in rows]
            _need(bool(cells) and bool(cells[0]), 'PARTICIPANT_ROW_MISSING')
            token = unicodedata.normalize('NFKC', cells[0][0].text()).strip()
            _need(re.fullmatch(r'[1-6]', token) and cells[0][0].has('is-boatColor'+token), 'PARTICIPANT_LANE_INVALID')
            lane = int(token)
            _need(lane in source_rows and lane not in seen, 'PARTICIPANT_NOT_IN_PROGRAM_OR_DUPLICATE')
            seen.add(lane)
            if source_rows[lane]['entry_status'] == 'withdrawn':
                continue
            if (len(cells) != 4 or [len(row) for row in cells] != [10, 2, 3, 2]
                    or [cells[1][0].text().strip(), cells[2][1].text().strip(), cells[3][0].text().strip()]
                       != ['進入', 'ST', '着順']):
                raise _Unsupported()
            first = cells[0]
            row = _participant(first, bound)
            marker = first[6].text().strip()
            _need(marker in MISSING | {'新'}, 'PROPELLER_MARKER_UNKNOWN')
            labels = _one(first[7].find(css='labelGroup1'), layout=True)
            parts = [label.text().strip() for label in labels.find('li') if label.text().strip()]
            row.update(bodyweight_kg=_number(first[3].text(), low=20, high=150, suffix='kg'),
                adjustmentweight_kg=_number(cells[2][0].text(), high=30),
                display_time=_number(first[4].text(), low=.01), tilt=_number(first[5].text(), low=-10, high=10),
                propeller_change_marker=marker if marker == '新' else None,
                propeller_change_status='REPORTED_NEW' if marker == '新' else 'NOT_PUBLISHED', parts_replacement=parts or None)
            row.update(starts.get(lane,dict(exhibition_st=None, exhibition_st_status='NOT_PUBLISHED',
                exhibition_st_raw=None, exhibition_source_position_number=None, exhibition_course=None)))
            participants.append(row)
        _need({row['lane'] for row in participants} == set(bound), 'ACTIVE_PARTICIPANTS_INCOMPLETE')
        participants.sort(key=lambda row:row['lane'])
        context.update(status='PARSED', roster_binding_status='VERIFIED', participants=participants, weather=_weather(frame))
    except _Unsupported:
        raise ValueError('BOAT_ACTIVE_EXHIBITION_UNSUPPORTED_STRUCTURE') from None
    boats = [dict(lane=row['lane'], racer_registration_id=row['registration_number'], name=row['name'],
        display_time=row['display_time'], tilt=row['tilt'], preview_st=row['exhibition_st'],
        preview_st_status='PENDING' if row['exhibition_st_status'] == 'NOT_PUBLISHED' else row['exhibition_st_status'],
        preview_raw_st=row['exhibition_st_raw'] or '', preview_course=None, actual_course=None) for row in participants]
    complete = all(row['display_time'] is not None for row in boats)
    eligibility = eligibility_for_cutoff(context, cutoff_at=program['closed_at'])
    return dict(schema=SCHEMA, race_id=program['race_id'], closed_at=program['closed_at'], kind='beforeinfo',
        status='AVAILABLE' if complete else 'PENDING', body_identity_verified=True,
        information_phase='pre_race', eligible_pre_race=eligibility['pre_cutoff_eligible'],
        data=dict(boats=boats, weather=context['weather']), source_url=source_url,
        source_sha256=context['source']['sha256'], captured_at=context['source']['captured_at'],
        context=context, active_lanes=list(bound), withdrawn_lanes=withdrawn)
