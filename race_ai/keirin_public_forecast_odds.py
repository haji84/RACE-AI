"""Read the dated Kdreams trifecta display independently of prediction inputs."""
from math import isfinite
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from . import keirin_nationwide_forecast_view as nationwide
from . import keirin_public_forecasts as public
from .keirin_nationwide_auto_generator import when
from .keirin_public_two_source_normalizer import _url_role

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_FORECAST_ODDS_V1'
COMBINATION = re.compile(r'[1-9]-[1-9]-[1-9]')
SOURCE_TIME = re.compile(r'(20\d\d)/(\d\d)/(\d\d)\s+(\d\d):(\d\d)現在')


def _source_url(race_id, url):
    _url_role(url, 'k', race_id)
    public.need(url == 'https://keirin.kdreams.jp'+urlsplit(url).path, 'ODDS_SOURCE_URL')


def _day(clock):
    return when(clock).astimezone(nationwide.JST).date().isoformat()


def checked(body):
    public.need(type(body) is dict and set(body) == {'schema','day','published_at','races'} and
                body['schema'] == SCHEMA, 'ODDS_SCHEMA')
    day = nationwide._day(body['day'])
    published = when(body['published_at'])
    rows = body['races']
    public.need(type(rows) is list and 0 < len(rows) <= nationwide.MAX_RACES, 'ODDS_RACES')
    for row in rows:
        public.need(type(row) is dict and set(row) == {'race_id','source_url','source_at','observed_at','quotes'}, 'ODDS_ROW')
        _source_url(row['race_id'], row['source_url'])
        public.need(_day(row['source_at']) == day and
                    when(row['source_at']) <= when(row['observed_at']) <= published, 'ODDS_CLOCK')
        quotes = row['quotes']
        public.need(type(quotes) is dict and 0 < len(quotes) <= 504 and all(
            type(key) is str and COMBINATION.fullmatch(key) and len(set(key.split('-'))) == 3 and
            type(value) in (int,float) and isfinite(value) and 0 < value < 9999.9
            for key,value in quotes.items()), 'ODDS_QUOTE')
    nationwide._ids([row['race_id'] for row in rows], day)
    return body


def _text(node):
    return node.get_text(' ',strip=True) if node is not None else ''


def _car(node):
    text = _text(node)
    public.need(re.fullmatch('[1-9]',text), 'ODDS_CAR')
    return int(text)


def _number(node):
    text = _text(node).replace(',','')
    value = float(text) if re.fullmatch(r'\d+(?:\.\d+)?',text) else None
    return value if value is not None and 0 < value < 9999.9 else None


def _selection(root, selector):
    nodes = root.select(selector)
    public.need(len(nodes) == 1, 'ODDS_SOURCE_LAYOUT')
    return nodes[0]


def _table_quotes(market, starters):
    found, quotes = set(), {}
    for table in market.select('.odds_table_wrapper table.bt5'):
        rows = table.select(':scope > tbody > tr, :scope > tr')
        public.need(len(rows) == len(starters)+2, 'ODDS_TABLE_ROWS')
        first = _car(_selection(rows[0],'span.number'))
        public.need(first in starters and first not in found, 'ODDS_STARTERS')
        found.add(first)
        others = starters-{first}
        seconds = [_car(cell) for cell in rows[1].select(':scope > th[class]')]
        public.need(len(seconds) == len(others) and set(seconds) == others, 'ODDS_STARTERS')
        thirds = set()
        for line in rows[3:]:
            labels = [_car(cell) for cell in line.select(':scope > th[class]')]
            public.need(1 <= len(labels) <= 2 and len(set(labels)) == 1, 'ODDS_THIRD_HEADING')
            third = labels[0]
            cells = line.select(':scope > td')
            public.need(third in others and third not in thirds and len(cells) == len(seconds), 'ODDS_STARTERS')
            thirds.add(third)
            for second,cell in zip(seconds,cells):
                if second != third:
                    quotes[f'{first}-{second}-{third}'] = _number(cell)
        public.need(thirds == others, 'ODDS_STARTERS')
    public.need(found == starters, 'ODDS_STARTERS')
    return quotes


def parse_racecard(raw, *, race_id, url, starters, observed_at, wanted):
    """Select actual published odds for displayed tickets, never payout cells."""
    _source_url(race_id, url)
    cars = set(starters)
    public.need(5 <= len(cars) <= 9 and len(cars) == len(starters) and
                all(type(car) is int and 1 <= car <= 9 for car in cars), 'ODDS_STARTERS')
    soup = BeautifulSoup(raw, 'html.parser')
    public.need(_selection(soup,'head link[rel~=canonical]').get('href') == url, 'ODDS_CANONICAL')
    timestamp = SOURCE_TIME.fullmatch(_text(_selection(soup,'#JS_ODDSSTATUS_3rentan p.time')))
    public.need(timestamp is not None, 'ODDS_SOURCE_CLOCK')
    year, month, day, hour, minute = timestamp.groups()
    date = f'{year}-{month}-{day}'
    source_at = f'{date}T{hour}:{minute}:00+09:00'
    public.need(date.replace('-','') == race_id[:8] and when(source_at) <= when(observed_at), 'ODDS_CLOCK')
    market = _selection(soup,'#JS_ODDSCONTENTS_3rentan')
    quotes = _table_quotes(market,cars)
    popular = _selection(market,'.oddspop_table_wrapper')
    compared = 0
    for cell in popular.select('td'):
        key = _text(cell.select_one('span.num'))
        if COMBINATION.fullmatch(key):
            public.need(key in quotes and quotes[key] == _number(cell.select_one('span.odds')), 'ODDS_POPULAR_CROSSCHECK')
            compared += 1
    public.need(compared > 0, 'ODDS_POPULAR_CROSSCHECK')
    return dict(race_id=race_id, source_url=url, source_at=source_at, observed_at=observed_at,
                quotes={key:quotes[key] for key in sorted(wanted & quotes.keys()) if quotes[key] is not None})
