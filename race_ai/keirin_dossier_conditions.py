"""Round and meeting-grade strata from verified source documents and numeric finishes."""
from collections import defaultdict
from datetime import date
from hashlib import sha256
import re

from . import keirin_official_canary_card as cards
from . import keirin_official_form_history as form
from . import keirin_official_schedule as calendar
from . import keirin_official_sp_receipt as receipt
from .keirin_dossier_race_context import MAX_RACES, REGISTRATION, SHA, _race_day

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONDITIONS_V1'
RESULT_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONDITION_RESULTS_V1'
ARCHIVE_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONDITION_ARCHIVE_V1'
SCOPE = 'OFFICIAL_SP_RESULT_REPLAY'
ARCHIVE_SCOPE = 'PINNED_KDREAMS_ARCHIVE_IDENTITY_RECONCILIATION'
MIXED_SCOPE = 'PINNED_KDREAMS_ARCHIVE_AND_OFFICIAL_SP_RESULT_REPLAY'
MAX_DAYS = 400
MAX_RIDERS = 10000
MAX_BYTES = 8 * 1024 * 1024
GRADES = frozenset({'F1','F2','G1','G2','G3','GP'})
ROUND_PATTERNS = {
    'PRELIMINARY': re.compile(r'(?:特|一(?:次)?|二(?:次)?|特別選抜)?予選'
                              r'(?:[12]|[AB]|\(第[12]走\)[AB]?)?|二予|予[12]'),
    'QUARTER_FINAL': re.compile(r'準々決勝[AB]?'),
    'SEMI_FINAL': re.compile(r'準決勝?'),
    'FINAL': re.compile(r'決勝[AB]?'),
    'CONSOLATION': re.compile(r'敗者(?:戦|一般)'),
    'GENERAL': re.compile(r'特?一般(?:\([12]\)|[AB])?'),
    'INITIAL_SPECIAL': re.compile(r'初(?:日)?特選'),
    'SPECIAL_SELECTION': re.compile(r'特選(?:\([12]\))?'),
    'SELECTION': re.compile(r'選抜(?:\([12]\))?'),
}
_PREFIX = re.compile(r'^(?:東日本|西日本|東|西)?'
                     r'(?:A級チャレンジ|チャレンジ|A級|S級|L級ガールズ新人|L級ガールズ|'
                     r'ガールズ新人|ガールズ|男子新人アドバンス|アドバンス|男)?')
_LABEL = re.compile(r'[A-Za-z0-9一-龯々ぁ-ゖァ-ヺー・&＋+()\-]{1,80}')
_COUNTS = ('numeric_finishes', 'wins', 'top2', 'top3')


def _need(ok, reason):
    if not ok:
        raise ValueError('KEIRIN_DOSSIER_CONDITIONS_' + reason)


def _day(value):
    _need(type(value) is str and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', value), 'DAY')
    return date.fromisoformat(value).isoformat()


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _label(value):
    if type(value) is str:
        value = receipt._norm(value)
        if _LABEL.fullmatch(value):
            return value
    return None


def round_stage(value):
    label = _label(value)
    if label is None:
        return None
    body = _PREFIX.sub('', label, count=1)
    return next((stage for stage, pattern in ROUND_PATTERNS.items() if pattern.fullmatch(body)), None)


def calendar_meeting_grades(calendar_receipt, *, day, now):
    """Read the grade icon only from the validated meeting row owning the navigation reference."""
    at = form._aware(calendar_receipt['observed_at'])
    raw, digest = calendar_receipt['raw_bytes'], calendar_receipt['expected_sha256']
    parsed = calendar.parse_calendar(raw, source_url=calendar.OFFICIAL_DOCUMENT, body_sha256=digest,
                                     received_at=at, now=form._aware(now), http_status=200)
    current = calendar.project_day(parsed, event_day=day)['calendar_meeting_candidates']
    document = receipt._body(raw, digest)
    grades, meetings = {}, {}
    for node in document.nodes:
        if node.tag == 'table' and calendar._class(node, 'race_tbl'):
            key = sha256(calendar._attribute(node, 'onclick').encode()).hexdigest()
            meetings[key] = node
    for item in current:
        venue = item['venue_code']
        _need(venue not in grades, 'AMBIGUOUS_MEETING')
        table = meetings[item['navigation_reference_sha256']]
        cells = [cell for cell in calendar._descendants(table)
                 if cell.tag == 'td' and calendar._class(cell, 'grade')]
        icons = [node for node in cells[0].children if node.tag == 'img'] if len(cells) == 1 else []
        grade = calendar._attribute(icons[0], 'alt') if len(icons) == 1 else ''
        if grade in GRADES and calendar._attribute(icons[0], 'src') == (
                '/sp/static/img/icon/grade/ico_' + grade.lower() + '.png'):
            grades[venue] = grade
        else:
            grades[venue] = None
    return grades


def official_race_conditions(*, calendar_receipt, list_sources, day, now):
    day, now = _day(day), form._aware(now)
    grades = calendar_meeting_grades(calendar_receipt, day=day, now=now)
    cal = dict(calendar_receipt, observed_at=form._aware(calendar_receipt['observed_at']))
    _need(type(list_sources) is list and len(list_sources) <= len(grades), 'SOURCE_COUNT')
    rows, seen = {}, set()
    for source in list_sources:
        venue, raw = source['venue_code'], source['raw_bytes']
        at = form._aware(source['observed_at'])
        _need(venue in grades and venue not in seen and at <= now, 'SOURCE_BINDING')
        listed = receipt.parse_race_list(raw, expected_day=day, expected_venue_code=venue,
            observed_at=at, expected_sha256=source['expected_sha256'], calendar_receipt=cal)
        titles = {int(receipt._norm(row['strRaceNo'])): _label(row['strSyumokuName'])
                  for row in cards._current_rows(raw, day)}
        for row in listed['day_roster_manifest']['races']:
            label = titles[row['race_no']]
            rid = row['race_id']
            rows[rid] = dict(race_id=rid, meeting_grade=grades[venue],
                             round_stage=round_stage(label), round_label=label,
                             list_sha256=source['expected_sha256'], source_at=at.isoformat())
        seen.add(venue)
    return dict(sorted(rows.items()))


def condition_for_card(card_arguments, *, now):
    """Verify the exact calendar and race list retained by the accepted official card."""
    a = card_arguments
    venue, day, number = a['venue_code'], a['expected_day'], a['race_number']
    rows = official_race_conditions(calendar_receipt=a['calendar_receipt'], day=day, now=now,
        list_sources=[dict(venue_code=venue, raw_bytes=a['list_raw'],
                           observed_at=a['list_observed_at'], expected_sha256=a['list_sha256'])])
    return rows[day.replace('-', '') + f'{venue:02d}{number:02d}']


def _registration(value):
    return type(value) is str and REGISTRATION.fullmatch(value) and value != '000000'


def _axes(grade, stage):
    return (grade is None or grade in GRADES) and (stage is None or stage in ROUND_PATTERNS)


def _cells(tallies):
    riders = defaultdict(list)
    for (reg, grade, stage), counts in sorted(tallies.items(), key=lambda row: (
            row[0][0], row[0][1] or '', row[0][2] or '')):
        riders[reg].append(dict(meeting_grade=grade, round_stage=stage, **dict(zip(_COUNTS, counts))))
    return [dict(registration=reg, cells=cells) for reg, cells in riders.items()]


def result_slice(day, source_sha256, observations):
    """Reduce verified numeric finishes, including one-axis matches, without publishing race-level results."""
    _day(day)
    _need(_sha(source_sha256), 'RESULT_SHA')
    return checked_result_slice(dict(schema=RESULT_SCHEMA, day=day, source_sha256=source_sha256,
                                    **_result_totals(observations)))


def archive_slice(*, start_day, end_day, archive_sha256s, registry_sha256, observations):
    return checked_archive_slice(dict(schema=ARCHIVE_SCHEMA, scope=ARCHIVE_SCOPE, start_day=start_day,
        end_day=end_day, archive_sha256s=sorted(archive_sha256s), registry_sha256=registry_sha256,
        historical_as_of_authenticated=False, **_result_totals(observations)))


def _result_totals(observations):
    tallies = defaultdict(lambda: [0] * 4)
    total = matched = 0
    for reg, grade, stage, place in observations:
        _need(_registration(reg) and _axes(grade, stage) and type(place) is int and 1 <= place <= 9,
              'RESULT_START')
        total += 1
        if grade is None and stage is None:
            continue
        matched += 1
        for key in {(reg, grade, stage), (reg, grade, None), (reg, None, stage)} - {(reg, None, None)}:
            for i, value in enumerate((1, place == 1, place <= 2, place <= 3)):
                tallies[key][i] += value
    return dict(numeric_finishes=total, condition_matched_finishes=matched, riders=_cells(tallies))


def _check_cells(riders, numeric, matched, *, limit):
    _need(type(numeric) is int and type(matched) is int and 0 <= matched <= numeric <= limit, 'RESULT_TOTAL')
    _need(type(riders) is list and len(riders) <= min(MAX_RIDERS, matched), 'RESULT_RIDERS')
    previous = ''
    union = 0
    for rider in riders:
        _need(type(rider) is dict and set(rider) == {'registration','cells'}, 'RESULT_RIDER')
        reg, cells = rider['registration'], rider['cells']
        _need(_registration(reg) and previous < reg and type(cells) is list and
              1 <= len(cells) <= 100, 'RESULT_RIDER')
        previous, prior_key = reg, ('', '')
        margins, pairs = {}, defaultdict(lambda: [0] * 4)
        for cell in cells:
            _need(type(cell) is dict and set(cell) == {'meeting_grade','round_stage',*_COUNTS}, 'RESULT_CELL')
            grade, stage = cell['meeting_grade'], cell['round_stage']
            _need(_axes(grade, stage), 'RESULT_AXES')
            key = grade or '', stage or ''
            n, wins, top2, top3 = values = [cell[name] for name in _COUNTS]
            _need(prior_key < key and all(type(value) is int for value in values) and
                  0 <= wins <= top2 <= top3 <= n <= matched and n > 0, 'RESULT_COUNTS')
            prior_key = key
            if grade is None or stage is None:
                margins[grade, stage] = values
                union += n
            else:
                union -= n
                for marginal in ((grade, None),(None, stage)):
                    for i, value in enumerate(values):
                        pairs[marginal][i] += value
        for key, totals in pairs.items():
            _need(key in margins and all(a <= b for a, b in zip(totals, margins[key])), 'RESULT_MARGINS')
    _need(union == matched, 'RESULT_UNION')


def checked_result_slice(row):
    _need(type(row) is dict and set(row) == {'schema','day','source_sha256','numeric_finishes',
          'condition_matched_finishes','riders'} and row['schema'] == RESULT_SCHEMA and
          _day(row['day']) and _sha(row['source_sha256']), 'RESULT_SCHEMA')
    _check_cells(row['riders'], row['numeric_finishes'], row['condition_matched_finishes'], limit=9 * MAX_RACES)
    return row


def checked_archive_slice(row):
    _need(type(row) is dict and set(row) == {'schema','scope','start_day','end_day',
          'archive_sha256s','registry_sha256','historical_as_of_authenticated','numeric_finishes',
          'condition_matched_finishes','riders'} and row['schema'] == ARCHIVE_SCHEMA and
          row['scope'] == ARCHIVE_SCOPE and row['historical_as_of_authenticated'] is False and
          _day(row['start_day']) <= _day(row['end_day']) and _sha(row['registry_sha256']), 'ARCHIVE_SCHEMA')
    hashes = row['archive_sha256s']
    _need(type(hashes) is list and len(hashes) == 2 and all(_sha(value) for value in hashes)
          and hashes == sorted(set(hashes)), 'ARCHIVE_SHA')
    _check_cells(row['riders'], row['numeric_finishes'], row['condition_matched_finishes'],
                 limit=9 * MAX_RACES * 800)
    return row


def build_day(*, day, published_at, registered_races, calendar_sha256, races, past_results,
              history_archive=None):
    """Aggregate distinct archive days strictly before the race day."""
    day, when = _day(day), form._aware(published_at)
    _need(type(past_results) is list and len(past_results) <= MAX_DAYS, 'RESULT_DAYS')
    parts = sorted((checked_result_slice(part) for part in past_results), key=lambda part: part['day'])
    days = [part['day'] for part in parts]
    _need(len(days) == len(set(days)) and all(d < day for d in days), 'RESULT_FORWARD_DAY')
    hashes = [part['source_sha256'] for part in parts]
    first = days[0] if days else None
    last = days[-1] if days else None
    scope = SCOPE
    if history_archive is not None:
        base = checked_archive_slice(history_archive)
        _need(base['end_day'] < (first or day), 'ARCHIVE_OVERLAP')
        first, last = base['start_day'], last or base['end_day']
        hashes.extend(base['archive_sha256s'])
        parts.insert(0, base)
        scope = MIXED_SCOPE
    tallies = defaultdict(lambda: [0] * 4)
    for part in parts:
        for rider in part['riders']:
            for cell in rider['cells']:
                counts = tallies[rider['registration'], cell['meeting_grade'], cell['round_stage']]
                for i, key in enumerate(_COUNTS):
                    counts[i] += cell[key]
    history = dict(start_day=first, end_day=last, source_sha256s=sorted(hashes),
        numeric_finishes=sum(part['numeric_finishes'] for part in parts),
        condition_matched_finishes=sum(part['condition_matched_finishes'] for part in parts), scope=scope)
    return checked_day(dict(schema=SCHEMA, day=day, published_at=when.isoformat(),
        registered_races=registered_races, calendar_sha256=calendar_sha256,
        races=[races[rid] for rid in sorted(races)], history=history, riders=_cells(tallies)))


def checked_day(packet):
    _need(type(packet) is dict and set(packet) == {'schema','day','published_at','registered_races',
          'calendar_sha256','races','history','riders'} and packet['schema'] == SCHEMA, 'SCHEMA')
    day, at, rows = _day(packet['day']), form._aware(packet['published_at']), packet['races']
    registered = packet['registered_races']
    _need(type(registered) is int and type(rows) is list and 0 <= len(rows) <= registered <= MAX_RACES and
          _sha(packet['calendar_sha256']) and day <= at.astimezone(form.JST).date().isoformat(), 'REGISTRY')
    previous = ''
    for row in rows:
        _need(type(row) is dict and set(row) == {'race_id','meeting_grade','round_stage','round_label',
              'list_sha256','source_at'}, 'RACE_FIELDS')
        rid, label, stage = row['race_id'], row['round_label'], row['round_stage']
        _need(_race_day(rid) == day and previous < rid and _axes(row['meeting_grade'], stage) and
              (label is None or label == _label(label)) and stage == round_stage(label) and
              _sha(row['list_sha256']) and form._aware(row['source_at']) <= at, 'RACE_EVIDENCE')
        previous = rid
    history = packet['history']
    _need(type(history) is dict and set(history) == {'start_day','end_day','source_sha256s',
          'numeric_finishes','condition_matched_finishes','scope'} and history['scope'] in {SCOPE,MIXED_SCOPE}, 'HISTORY')
    hashes = history['source_sha256s']
    archive_limit = 800 if history['scope'] == MIXED_SCOPE else 0
    _need(type(hashes) is list and len(hashes) <= MAX_DAYS + (2 if archive_limit else 0)
          and (not archive_limit or len(hashes) >= 2) and all(_sha(value) for value in hashes)
          and hashes == sorted(set(hashes)), 'HISTORY_SHA')
    if hashes:
        _need(_day(history['start_day']) <= _day(history['end_day']) < day, 'HISTORY_PERIOD')
    else:
        _need(history['start_day'] is None and history['end_day'] is None, 'HISTORY_PERIOD')
    _check_cells(packet['riders'], history['numeric_finishes'], history['condition_matched_finishes'],
                 limit=9 * MAX_RACES * (len(hashes) + archive_limit))
    return packet


def rider_feature(packet, *, registration, meeting_grade, round_stage, as_of):
    """Return an exact historical pair only, with the caller pinning the public packet bytes."""
    packet = checked_day(packet)
    if (meeting_grade is None or round_stage is None or
            form._aware(packet['published_at']) > form._aware(as_of)):
        return None
    return next((cell for row in packet['riders'] if row['registration'] == registration
                 for cell in row['cells'] if cell['meeting_grade'] == meeting_grade and
                 cell['round_stage'] == round_stage), None)
