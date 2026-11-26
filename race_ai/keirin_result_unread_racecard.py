"""Select posted entry facts for result-unread KEIRIN research."""

from __future__ import annotations

import re
from unicodedata import normalize
from urllib.parse import urlsplit

from .keirin_nationwide_auto_generator import VENUE
from .keirin_public_two_source_normalizer import (
    PublicPageNormalizeError, _float, _mark, _selected_net_link, _style, _url_role, need,
)


CAR = re.compile(r'[1-9]')
WITHDRAWN = {'欠場', '病気欠場', '負傷欠場', '欠車', '出走取消', '出走取り消し', '不出走'}
LINE_MISSING = '並び予想を取得できません。'
LINE_CONFLICT = '並び予想の車番と出走表が一致しません。'
LINE_CONTEST = '並び予想に競りの記載があり、単一の並びを確定できません。'


def _one(nodes, error):
    need(len(nodes) == 1, error)
    return nodes[0]


def _text(node):
    return normalize('NFKC', node.get_text(' ', strip=True))


def _compact(text):
    return ''.join(text.split())


def _name(node):
    # Direct text excludes demographics and favorite-button SVG captions.
    return next((part.strip() for part in node.find_all(string=True, recursive=False)
                 if part.strip()), '')


def _document(raw, url):
    from bs4 import BeautifulSoup

    need(type(raw) is bytes and 0 < len(raw) <= 6_000_000, 'RACECARD_BYTES_REQUIRED')
    try:
        html = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise PublicPageNormalizeError('RACECARD_NOT_UTF8') from None
    document = BeautifulSoup(html, 'html.parser')
    canonical = _one(document.select('head > link[rel~=canonical]'), 'RACECARD_CANONICAL_REQUIRED')
    need(canonical.get('href') == url, 'RACECARD_CANONICAL_URL_MISMATCH')
    return document


def _table_rows(table):
    return table.select(':scope > thead > tr, :scope > tbody > tr, :scope > tr')


def _withdrawn(row, identity):
    notices = row.select(':scope > td.absence, :scope > td.cancel')
    notices.extend(identity.select(':scope > span, :scope > a.Player01 > span'))
    return any(_compact(_text(notice)) in WITHDRAWN for notice in notices)


def _competition(content):
    label = _one(content.select(':scope > div.racecard_header h2.title > span.status'),
                 'KDREAMS_SELECTED_CLASS_REQUIRED')
    title = _compact(_text(label))
    for text, competition in (('ガールズ', 'GIRLS'), ('L級', 'GIRLS'), ('チャレンジ', 'CHALLENGE'),
                              ('S級', 'S'), ('A級', 'A1_A2')):
        if text in title:
            return competition
    need(False, 'KDREAMS_SELECTED_CLASS_REQUIRED')


def _kdreams_riders(content):
    table = _one(content.select(':scope > div.racecard_contents > '
                                'table.racecard_table:not(.none,.past_racecard_table,[hidden])'),
                 'KDREAMS_SELECTED_ENTRY_TABLE_REQUIRED')
    rows = _table_rows(table)
    headings = [row.find_all('th', recursive=False) for row in rows]
    headings = [cells for cells in headings if cells]
    # Read only the headings for fields that bind the allowed entry columns.
    need(len(headings) == 2 and len(headings[0]) == 10 and len(headings[1]) == 14
         and [_compact(_text(headings[0][index])) for index in (0, 4, 5, 7)] ==
         ['予想', '車番', '選手名府県/年齢/期別', '脚質']
         and _compact(_text(headings[1][0])) == '競走得点', 'KDREAMS_ENTRY_COLUMNS_CHANGED')

    riders, scratches = {}, set()
    for row in rows:
        number = row.select_one(':scope > td.num')
        identity = row.select_one(':scope > td.rider')
        if number is None and identity is None:
            continue
        need(number is not None and identity is not None, 'KDREAMS_ENTRY_ROW_INCOMPLETE')
        raw_car = _text(number)
        need(CAR.fullmatch(raw_car), 'KDREAMS_ENTRY_CAR_INVALID')
        car = int(raw_car)
        need(car not in riders and car not in scratches, 'KDREAMS_ENTRY_CAR_DUPLICATED')
        if _withdrawn(row, identity):
            scratches.add(car)
            continue

        name = _name(identity)
        cells = row.find_all('td', recursive=False)
        offset = cells.index(identity)
        need(1 <= len(name) <= 160 and len(cells) - offset == 18,
             'KDREAMS_ENTRY_ROW_INCOMPLETE')
        tip = _one(row.select(':scope > td.tip'), 'KDREAMS_ENTRY_MARK_COLUMN_REQUIRED')
        published_style = _text(cells[offset + 2])
        score = _text(cells[offset + 4])
        points = None if score in ('', '-', '--', '―', '—') else _float(score, lo=0, hi=150) or None
        riders[car] = dict(car=car, name=name, competition_points=points,
                           mark_rank=_mark(_text(tip), 9),
                           style=_style(published_style) if published_style in ('逃', '追', '両') else 'UNKNOWN')
    return riders, scratches


def _netkeirin_riders(document, url, race_id):
    selected = _one(document.select('div.RaceList_NameBox > div.RaceList_NameBox_inner'),
                    'NETKEIRIN_SELECTED_ENTRY_REQUIRED')
    tab = _one(selected.parent.select('a.Active'), 'NETKEIRIN_SELECTED_RACE_TAB_REQUIRED')
    heading = _one(selected.select('.Race_Num'), 'NETKEIRIN_SELECTED_RACE_NUMBER_REQUIRED')
    need(_selected_net_link(tab.get('href'), url, race_id) and
         _text(heading) == f'{int(race_id[-2:])}R', 'NETKEIRIN_SELECTED_RACE_MISMATCH')
    table = _one(document.select('div.RaceCard_PlayerList01 > div.RaceCard_Simple_Table_Static > '
                                 'table#RaceCard_Table_Static.RaceCard_Table'),
                 'NETKEIRIN_SELECTED_ENTRY_TABLE_REQUIRED')
    names, scratches = {}, set()
    for row in _table_rows(table):
        if 'PlayerList' not in row.get('class', []):
            continue
        number = _one(row.select(':scope > td.RaceCardCell01:nth-child(2)'), 'NETKEIRIN_ENTRY_CAR_REQUIRED')
        raw_car = _text(number)
        need(CAR.fullmatch(raw_car) and row.get('id') == f'player-{raw_car}', 'NETKEIRIN_ENTRY_CAR_INVALID')
        car = int(raw_car)
        need(car not in names and car not in scratches, 'NETKEIRIN_ENTRY_CAR_DUPLICATED')
        identity = _one(row.select(':scope > td.Player_Info'), 'NETKEIRIN_ENTRY_IDENTITY_REQUIRED')
        if _withdrawn(row, identity):
            scratches.add(car)
            continue
        player = _one(identity.select(':scope > a.Player01 dt.PlayerName'), 'NETKEIRIN_ENTRY_IDENTITY_REQUIRED')
        names[car] = _name(player)
        need(1 <= len(names[car]) <= 160, 'NETKEIRIN_ENTRY_IDENTITY_REQUIRED')
    return names, scratches


def _predicted_lines(content, cars):
    labels = [dt for dt in content.select(':scope > dl.racecard_footer-contents > dt')
              if _compact(_text(dt)) == '並び予想']
    if len(labels) != 1:
        return None, [LINE_MISSING]
    panel = labels[0].find_next_sibling()
    if panel is None or panel.name != 'dd':
        return None, [LINE_MISSING]
    layouts = panel.select(':scope > div.line_position')
    if len(layouts) != 1:
        return None, [LINE_MISSING]
    layout = layouts[0]
    inner = layout.select(':scope > div.line_position_inner')
    if len(inner) > 1:
        return None, [LINE_CONFLICT]
    if inner:
        layout = inner[0]
    icons = layout.select(':scope > span.icon_p')
    if layout.select(':scope > span.bracket_open, :scope > span.bracket_close'):
        return None, [LINE_CONTEST]
    groups = [[]]
    for icon in icons:
        if 'space' in icon.get('class', []):
            if groups[-1]:
                groups.append([])
            continue
        if icon.select_one(':scope > span.p000'):
            continue  # Pacemaker icon has no assigned car.
        parts = icon.find_all('span', recursive=False)
        number = _text(parts[0]) if parts else ''
        if not CAR.fullmatch(number):
            return None, [LINE_CONFLICT]
        if len(parts) > 1 and _text(parts[1]) == '競り':
            return None, [LINE_CONTEST]
        groups[-1].append(int(number))
    groups = [group for group in groups if group]
    flat = [car for group in groups for car in group]
    if not flat:
        return None, [LINE_MISSING]
    if len(flat) != len(cars) or set(flat) != cars:
        return None, [LINE_CONFLICT]
    return groups, []


def snapshot_from_cards(*, race_id, kdreams_raw, kdreams_url, netkeirin_raw=None, netkeirin_url=None):
    """Build the existing evidence model's limited snapshot from selected racecards.

    The ordinary netkeirin card can cross-check car/name and published
    withdrawals. Kdreams supplies the displayed score, mark, style and line
    hypothesis. Time and source-byte receipts belong to the caller.
    """
    need(type(race_id) is str and VENUE.fullmatch(race_id), 'RACECARD_RACE_ID_REQUIRED')
    _url_role(kdreams_url, 'k', race_id)
    expected = 'https://keirin.kdreams.jp' + urlsplit(kdreams_url).path
    need(kdreams_url == expected, 'KDREAMS_ORDINARY_RACECARD_URL_REQUIRED')
    need((netkeirin_raw is None) == (netkeirin_url is None), 'NETKEIRIN_CARD_AND_URL_REQUIRED')

    document = _document(kdreams_raw, kdreams_url)
    content = _one(document.select('section.raceinfo_section div.raceinfo_contents'),
                   'KDREAMS_SELECTED_RACE_CONTENT_REQUIRED')
    competition = _competition(content)
    riders, scratches = _kdreams_riders(content)
    if netkeirin_raw is not None:
        _url_role(netkeirin_url, 'net', race_id)
        need(netkeirin_url == f'https://keirin.netkeiba.com/race/entry/?race_id={race_id}',
             'NETKEIRIN_ORDINARY_RACECARD_URL_REQUIRED')
        net = _document(netkeirin_raw, netkeirin_url)
        names, net_scratches = _netkeirin_riders(net, netkeirin_url, race_id)
        scratches |= net_scratches
        common = set(riders) - scratches
        need(common == set(names) - scratches and all(
            _compact(normalize('NFKC', riders[car]['name'])) == _compact(normalize('NFKC', names[car]))
            for car in common), 'NETKEIRIN_ROSTER_CONFLICT')

    cars = set(riders) - scratches
    need(5 <= len(cars) <= 9, 'RACECARD_FIVE_TO_NINE_STARTER_ROSTER_REQUIRED')
    starters = [riders[car] for car in sorted(cars)]
    need(any(rider['competition_points'] for rider in starters), 'RACECARD_COMPETITION_POINTS_REQUIRED')
    groups, warnings = _predicted_lines(content, cars)
    if competition == 'GIRLS':
        if groups is None:
            groups = [[car] for car in sorted(cars)]
            warnings.append('ガールズは車番順の単独枠で扱い、掲載の初周位置は未確認です。')
        else:
            groups = [[car] for group in groups for car in group]
    return dict(race_id=race_id, riders=starters, competition=competition,
                line_groups=groups, line_warnings=warnings)
