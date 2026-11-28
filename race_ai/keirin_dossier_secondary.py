"""Display-only dossier facts from previously captured Kdreams racecards."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
import re
from unicodedata import normalize
from urllib.parse import urlsplit

from . import keirin_dossier_race_context as context
from . import keirin_result_unread_racecard as card
from .keirin_public_two_source_normalizer import JST, _url_role


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_SECONDARY_V1'
RACE_FIELDS = {'race_id','cutoff_at','source_cutoff_at','source_at','source_sha256','source_url','riders'}
COVERAGE_FIELDS = {'registered_races','verified_races','registered_riders','verified_riders',
                   'comments_confirmed','comments_held','comments_missing'}
STAT_COLUMNS = {
    'competition_points': (4, 150),
    'back_count': (6, 200),
    'escape_count': (7, 200),
    'makuri_count': (8, 200),
    'difference_count': (9, 200),
    'mark_count': (10, 200),
    'win_rate_percent': (15, 100),
}
STATS_FIELDS = {'home_count', *STAT_COLUMNS}
ENTRY_HEADINGS = ('競走得点','S','B','逃','捲','差','マ','1着','2着','3着','着外','勝率','2連対率','3連対率')
TABLES = ':scope > div.racecard_contents > table.racecard_table'
PERFORMANCE_FIELDS = {'source_at','source_sha256','source_url','riders'}
FINISH_COUNTS = ('1着','2着','3着','着外')


def _need(ok, code):
    if not ok:
        raise ValueError('PUBLIC_DOSSIER_SECONDARY_' + code)


def _url(value, race_id):
    _need(type(value) is str, 'URL')
    _url_role(value, 'k', race_id)
    _need(value == 'https://keirin.kdreams.jp' + urlsplit(value).path, 'ORDINARY_URL')


def _performance_url(value, race_id):
    _need(type(value) is str, 'PERFORMANCE_URL')
    _url_role(value, 'k', race_id)
    parsed = urlsplit(value)
    ordinary = 'https://keirin.kdreams.jp' + parsed.path
    _need(value in (ordinary, ordinary + '?pageType=yoso', ordinary + '?pageType=showResult'), 'PERFORMANCE_URL')
    return ordinary


def _name(value):
    _need(type(value) is str and 0 < len(value) <= 160, 'ROSTER_NAME')
    joined = ''.join(normalize('NFKC', value).split())
    _need(joined, 'ROSTER_NAME')
    return joined


def _headings(table):
    return [tuple(card._compact(card._text(cell)) for cell in row.find_all('th',recursive=False))
            for row in card._table_rows(table) if row.find('th',recursive=False)]


def _stat(raw, key, maximum):
    if raw in ('','-','--','―','—'):
        return None
    if key == 'win_rate_percent':
        raw = raw.removesuffix('%')
    decimal = key in ('competition_points','win_rate_percent')
    _need(re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,4})?' if decimal else r'[0-9]{1,3}', raw),
          'STATS_FORMAT')
    number = float(raw) if decimal else int(raw)
    _need(0 <= number <= maximum, 'STATS_RANGE')
    return number


def _entry_stats(table, starters):
    headings = _headings(table)
    _need(len(headings) == 2 and headings[0][-1] == '直近4ヶ月の成績' and
          headings[1] == ENTRY_HEADINGS, 'STATS_HEADINGS')
    stats = {}
    for row in card._table_rows(table):
        number = row.select_one(':scope > td.num')
        if number is None or not card.CAR.fullmatch(card._text(number)):
            continue
        car = int(card._text(number))
        if car not in starters:
            continue
        cells = row.find_all('td', recursive=False)
        offset = cells.index(row.select_one(':scope > td.rider'))
        stats[car] = {'home_count': None, **{
            field: _stat(card._text(cells[offset+column]), field, maximum)
            for field,(column,maximum) in STAT_COLUMNS.items()
        }}
    _need(stats.keys() == starters.keys(), 'STATS_ROSTER')
    return stats


def _comments(content, starters, official):
    tables = [table for table in content.select(TABLES)
              if any('選手コメント' in row for row in _headings(table))]
    _need(len(tables) <= 1, 'COMMENT_TABLE')
    if not tables:
        return {}
    summaries = {}
    for row in card._table_rows(tables[0]):
        number = row.select_one(':scope > td.num')
        if number is None or not card.CAR.fullmatch(card._text(number)):
            continue
        car = int(card._text(number))
        if car not in starters:
            continue
        identity = row.select_one(':scope > td.rider')
        _need(car not in summaries and identity is not None and
              _name(card._name(identity)) == _name(starters[car]['name']), 'COMMENT_ROSTER')
        cell = row.select_one(':scope > td.comment')
        if cell is not None:
            summaries[car] = context._public_comment(card._text(cell), car, official)
        else:
            summaries[car] = {'state': 'NOT_PUBLISHED'}
    return summaries


def _source_cutoff(content, day):
    labels = content.select(':scope > div.racecard_header dl.time > dt')
    clocks = [label.find_next_sibling() for label in labels
              if card._compact(card._text(label)) in ('締切','投票締切')]
    _need(len(clocks) == 1 and clocks[0] is not None and clocks[0].name == 'dd', 'CUTOFF')
    match = re.fullmatch(r'([0-9]{1,2}):([0-9]{2})',card._compact(card._text(clocks[0])))
    _need(match and int(match[1]) < 24 and int(match[2]) < 60, 'CUTOFF')
    return context._aware(f'{day}T{int(match[1]):02d}:{match[2]}:00+09:00')


def _receipt(raw, receipt, now):
    published = context._aware(now if now is not None else datetime.now(timezone.utc))
    _need(type(receipt) is dict and set(receipt) == {'url','bytes_sha256','bytes','status','captured_at'} and
          receipt['status'] == 200 and type(receipt['bytes']) is int and type(raw) is bytes and
          0 < receipt['bytes'] == len(raw) <= 6_000_000 and
          receipt['bytes_sha256'] == sha256(raw).hexdigest(), 'RECEIPT')
    source_at = context._aware(receipt['captured_at'])
    _need(source_at <= published, 'RECEIPT_CLOCK')
    return source_at


def _race_content(raw, url):
    document = card._document(raw,url)
    return card._one(document.select('section.raceinfo_section div.raceinfo_contents'),
                     'KDREAMS_SELECTED_RACE_CONTENT_REQUIRED')


def source_card(raw, receipt, race_id, *, now=None):
    """Check the archived card and expose only its selected normalized racing fields."""
    day = context._race_day(race_id)
    source_at = _receipt(raw, receipt, now)
    url = receipt['url']
    _url(url,race_id)
    content = _race_content(raw,url)
    card._competition(content)
    provider, _ = card._kdreams_riders(content)
    _need(5 <= len(provider) <= 9, 'ROSTER_SIZE')
    source_cutoff = _source_cutoff(content,day)
    entry = card._one(content.select(TABLES + ':not(.none,.past_racecard_table,[hidden])'),
                      'KDREAMS_SELECTED_ENTRY_TABLE_REQUIRED')
    stats = _entry_stats(entry,provider)
    comments = _comments(content,provider,provider.values())
    return dict(race_id=race_id, source_cutoff_at=source_cutoff.isoformat(), source_at=source_at.isoformat(),
                source_sha256=receipt['bytes_sha256'], source_url=url, riders=[
                    dict(number=number,name=_name(provider[number]['name']),stats=stats[number],
                         comment=comments.get(number,{'state':'NOT_PUBLISHED'}))
                    for number in sorted(provider)])


def project_card(raw, receipt, official_starters_row, *, official_cutoff_at, now):
    """Bind an admitted Kdreams card to the independently supplied official registry."""
    source = source_card(raw, receipt, official_starters_row['race_id'], now=now)
    return _project_card(source, official_starters_row, official_cutoff_at=official_cutoff_at, now=now)


def _project_card(source, official_starters_row, *, official_cutoff_at, now):
    race_id = official_starters_row['race_id']
    _need(source['race_id'] == race_id, 'ROSTER_RACE')
    official = official_starters_row['riders']
    identities = context._identity(official,'number','registration')
    names = {row['number']:_name(row['name']) for row in official}
    _need({row['number']:row['name'] for row in source['riders']} == names, 'ROSTER')
    result = {**source, 'cutoff_at':context._aware(official_cutoff_at).isoformat(), 'riders':[
        dict(number=row['number'],registration=identities[row['number']],stats=row['stats'],comment=row['comment'])
        for row in source['riders']
    ]}
    _checked_race(result,context._race_day(race_id),context._aware(now))
    return result


def _performance_counts(table, names, width, offset):
    rows = {}
    for row in card._table_rows(table):
        number = row.select_one(':scope > td.num')
        if number is None:
            continue
        value = card._text(number)
        _need(card.CAR.fullmatch(value), 'PERFORMANCE_ROSTER')
        car = int(value)
        identity = row.select_one(':scope > td.rider')
        _need(car in names and car not in rows and identity is not None and
              _name(card._name(identity)) == names[car], 'PERFORMANCE_ROSTER')
        cells = row.find_all('td',recursive=False)
        _need(len(cells) in (9 + width, 10 + width) and
              re.fullmatch(r'[0-9]+\.[0-9]+',card._text(cells[-width-1])), 'PERFORMANCE_COLUMNS')
        values = [card._text(cell) for cell in cells[-width:][offset:offset+4]]
        _need(all(re.fullmatch(r'[0-9]{1,3}',value) and int(value) <= 600 for value in values),
              'PERFORMANCE_COUNTS')
        counts = list(map(int,values))
        rows[car] = counts if sum(counts) else None
    _need(rows.keys() == names.keys(), 'PERFORMANCE_ROSTER')
    return rows


def _performance_tables(content, names):
    tables = [(table,_headings(table)) for table in content.select(TABLES)]
    annual = [(table,headings) for table,headings in tables if headings and headings[0][-1] == '年間勝利度数']
    venue = [(table,headings) for table,headings in tables if headings and headings[0][-1] == '当所5年']
    _need(len(annual) == len(venue) == 1, 'PERFORMANCE_TABLES')
    annual_table, annual_headings = annual[0]
    venue_table, venue_headings = venue[0]
    _need(annual_headings[1:] == [('決勝','特選','準決','予選'),FINISH_COUNTS * 4] and
          venue_headings[1:] == [FINISH_COUNTS], 'PERFORMANCE_HEADINGS')
    return (_performance_counts(annual_table,names,16,8), _performance_counts(venue_table,names,4,0))


def project_performance(raw, receipt, official_starters_row, *, now):
    """Bind the provider's annual semifinals and five-year venue counts to official starters."""
    rid = official_starters_row['race_id']
    source_at = _receipt(raw,receipt,now)
    ordinary = _performance_url(receipt['url'],rid)
    content = _race_content(raw,ordinary)
    official = official_starters_row['riders']
    identities = context._identity(official,'number','registration')
    names = {row['number']:_name(row['name']) for row in official}
    provider, _ = card._kdreams_riders(content)
    _need(5 <= len(identities) <= 9 and
          {number:_name(row['name']) for number,row in provider.items()} == names, 'PERFORMANCE_ROSTER')
    semi, venue = _performance_tables(content,names)
    result = dict(source_url=receipt['url'],source_sha256=receipt['bytes_sha256'],source_at=source_at.isoformat(),
                  riders=[dict(number=number,registration=identities[number],semi=semi[number],venue=venue[number])
                          for number in sorted(identities)])
    _checked_performance(result,rid,context._aware(now),identities)
    return result


def _checked_performance(supplement, rid, published, identities):
    _need(type(supplement) is dict and set(supplement) == PERFORMANCE_FIELDS, 'PERFORMANCE_FIELDS')
    _performance_url(supplement['source_url'],rid)
    _need(context._aware(supplement['source_at']) <= published and
          type(supplement['source_sha256']) is str and context.SHA.fullmatch(supplement['source_sha256']),
          'PERFORMANCE_CLOCK')
    rows = supplement['riders']
    _need(type(rows) is list and all(type(row) is dict and set(row) == {'number','registration','semi','venue'}
                                   for row in rows), 'PERFORMANCE_FIELDS')
    _need(context._identity(rows,'number','registration') == identities, 'PERFORMANCE_ROSTER')
    for row in rows:
        for field in ('semi','venue'):
            counts = row[field]
            _need(counts is None or type(counts) is list and len(counts) == 4 and
                  all(type(value) is int and 0 <= value <= 600 for value in counts) and sum(counts) > 0,
                  'PERFORMANCE_COUNTS')


def _checked_race(row, day, published):
    _need(type(row) is dict and RACE_FIELDS <= set(row) <= RACE_FIELDS | {'performance'}, 'RACE_FIELDS')
    rid = row['race_id']
    _need(context._race_day(rid) == day, 'RACE_DAY')
    _url(row['source_url'],rid)
    cutoff, source_cutoff, captured = map(context._aware, (
        row['cutoff_at'],row['source_cutoff_at'],row['source_at']))
    _need(day == cutoff.astimezone(JST).date().isoformat() == source_cutoff.astimezone(JST).date().isoformat() and
          captured <= published and type(row['source_sha256']) is str and context.SHA.fullmatch(row['source_sha256']),
          'RACE_CLOCK')
    identities = context._identity(row['riders'],'number','registration')
    _need(5 <= len(identities) <= 9, 'ROSTER_SIZE')
    if 'performance' in row:
        _checked_performance(row['performance'],rid,published,identities)
    for item in row['riders']:
        _need(set(item) == {'number','registration','stats','comment'}, 'RIDER_FIELDS')
        stats = item['stats']
        _need(type(stats) is dict and set(stats) == STATS_FIELDS and stats['home_count'] is None, 'STATS_FIELDS')
        for field,(_,maximum) in STAT_COLUMNS.items():
            value = stats[field]
            allowed = (int,float) if field in ('competition_points','win_rate_percent') else (int,)
            _need(value is None or type(value) in allowed and 0 <= value <= maximum and isfinite(value), 'STATS_VALUE')
        comment = item['comment']
        _need(type(comment) is dict, 'COMMENT')
        state = comment.get('state')
        if state == 'SUMMARIZED':
            code = comment.get('code')
            follow = code == 'FOLLOW'
            _need(set(comment) == {'state','code','summary'} | ({'target_car'} if follow else set()) and
                  type(code) is str and context.COMMENT_SUMMARIES.get(code) == comment['summary'] and
                  isinstance(comment['summary'],str) and (not follow or
                  type(comment['target_car']) is int and comment['target_car'] in identities and
                  comment['target_car'] != item['number']), 'COMMENT')
        else:
            _need(set(comment) == {'state'} and state in ('UNINTERPRETED','NOT_PUBLISHED'), 'COMMENT')
    return identities


def build_day(starters, rows, *, published_at):
    """Bind and count captured starter appearances against the existing official registry."""
    published = context._aware(published_at)
    day = context._day(starters['day'])
    races = starters['races']
    _need(starters['schema'] == context.STARTERS_SCHEMA and type(races) is list and type(rows) is list and
          len(rows) <= len(races) <= context.MAX_RACES and context._aware(starters['published_at']) <= published,
          'REGISTRY')
    fields = {}
    for race in races:
        rid = race['race_id']
        _need(context._race_day(rid) == day and rid not in fields, 'REGISTRY_RACE')
        fields[rid] = context._identity(race['riders'],'number','registration')
    selected = {}
    counts = Counter()
    for row in rows:
        identity = _checked_race(row,day,published)
        rid = row['race_id']
        _need(rid not in selected and identity == fields.get(rid), 'REGISTRY_ROSTER')
        selected[rid] = row
        counts.update(item['comment']['state'] for item in row['riders'])
    registered = sum(map(len,fields.values()))
    coverage = dict(registered_races=len(fields),verified_races=len(selected),registered_riders=registered,
                    verified_riders=sum(counts.values()),comments_confirmed=counts['SUMMARIZED'],
                    comments_held=counts['UNINTERPRETED'],comments_missing=registered-counts['SUMMARIZED']-counts['UNINTERPRETED'])
    return checked_day(dict(schema=SCHEMA,day=day,published_at=published.isoformat(),
                            coverage=coverage,races=[selected[rid] for rid in sorted(selected)]))


def checked_day(packet):
    """Recheck public shape, provenance clocks and coverage before consumption."""
    _need(type(packet) is dict and set(packet) == {'schema','day','published_at','coverage','races'} and
          packet['schema'] == SCHEMA, 'PACKET_FIELDS')
    day = context._day(packet['day'])
    published = context._aware(packet['published_at'])
    races, coverage = packet['races'],packet['coverage']
    _need(day <= published.astimezone(JST).date().isoformat() and type(coverage) is dict and
          set(coverage) == COVERAGE_FIELDS and all(type(value) is int and value >= 0 for value in coverage.values()) and
          type(races) is list and len(races) == coverage['verified_races'] <= coverage['registered_races'] <= context.MAX_RACES and
          coverage['registered_races'] <= coverage['registered_riders'] <= 9 * coverage['registered_races'],
          'COVERAGE')
    counts = Counter()
    previous = ''
    for race in races:
        _checked_race(race,day,published)
        _need(previous < race['race_id'], 'RACE_ORDER')
        previous = race['race_id']
        counts.update(item['comment']['state'] for item in race['riders'])
    _need(coverage['verified_riders'] == sum(counts.values()) <= coverage['registered_riders'] and
          coverage['comments_confirmed'] == counts['SUMMARIZED'] and coverage['comments_held'] == counts['UNINTERPRETED'] and
          coverage['comments_missing'] == coverage['registered_riders'] - counts['SUMMARIZED'] - counts['UNINTERPRETED'],
          'COVERAGE')
    return packet
