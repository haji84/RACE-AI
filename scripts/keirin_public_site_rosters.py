"""Register the original site's publicly listed daily forecasts for result matching."""
from __future__ import annotations

import argparse
from collections import defaultdict
import fcntl
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
from http.client import HTTPException
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

from bs4 import BeautifulSoup

from race_ai import keirin_secondary_result_consensus as consensus
from scripts import keirin_discover_public_race_links as day_links
from scripts.keirin_capture_public_two_sources import NoRedirect, SourceCaptureError, fetch_once
from scripts.keirin_public_site_results import checked, validate_roster

SITE = 'https://keirin-20261119-race-note.chankuma.chatgpt.site'
KD = 'https://keirin.kdreams.jp'
FILE = re.compile(r'/data/keirin_(20[0-9]{6})_(blind|reference|ranked(?:_v[23])?)_public\.json')
SCHEMA = {'blind': 'KEIRIN_RESULT_UNREAD_DAY_RESEARCH_V1', 'reference': 'KEIRIN_RESULT_UNREAD_DAY_RESEARCH_V1',
          'ranked': 'KEIRIN_PUBLISHED_LINE_RANK_V1', 'ranked_v2': 'KEIRIN_PUBLISHED_LINE_RANK_V2',
          'ranked_v3': 'KEIRIN_PUBLISHED_LINE_RANK_V3'}
SITE_FIELDS = ('data-public-reference-source', 'data-published-history-sources', 'data-published-source')
MAX_ASSET = 90 * 1024 * 1024  # Same decoded packet limit as the public viewer.
MAX_PAGE = 2 * 1024 * 1024
JST = timezone(timedelta(hours=9))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decoded(raw, limit):
    checked(isinstance(raw, bytes) and 0 < len(raw) <= limit, 'PUBLIC_ASSET_SIZE_INVALID')
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=BytesIO(raw)) as compressed:
            raw = compressed.read(limit + 1)
        checked(0 < len(raw) <= limit, 'PUBLIC_ASSET_SIZE_INVALID')
    return raw


def fetch_site(url):
    home = url == SITE + '/'
    checked(home or url.startswith(SITE + '/') and FILE.fullmatch(url[len(SITE):]),
            'UNAPPROVED_SITE_PATH')
    limit = MAX_PAGE if home else MAX_ASSET
    request = Request(url, headers={'User-Agent': 'RACE-AI-PublicResults/1.0 (+https://github.com/haji84/RACE-AI)',
                                    'Accept': 'text/html' if home else 'application/json', 'Accept-Encoding': 'gzip'})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        checked(response.status == 200 and response.geturl() == url, 'SITE_RESPONSE_UNEXPECTED')
        media = response.headers.get_content_type()
        checked(media in (('text/html',) if home else ('application/json', 'application/gzip')), 'SITE_CONTENT_TYPE_INVALID')
        return response.read(limit + 1)


def published_paths(raw):
    soup = BeautifulSoup(decoded(raw, MAX_PAGE), 'html.parser')
    roots = soup.select('main#daily-root')
    checked(len(roots) == 1, 'PUBLIC_DAILY_ROOT_MISSING')
    days = defaultdict(set)
    invalid = False
    for attr in SITE_FIELDS:
        for path in roots[0].get(attr, '').split():
            match = FILE.fullmatch(path)
            if not match:
                invalid = True
                continue
            try:
                day = date.fromisoformat(match[1]).isoformat()
            except ValueError:
                invalid = True
                continue
            days[day].add(path)
    checked(days, 'NO_PUBLIC_FORECAST_ASSETS')
    return days, invalid


def calendar_sources(day, needed, fetch):
    """Use actual anchors on the dated results index; an unfinished day may need racecards."""
    index = KD + '/raceresult/' + day.replace('-', '/') + '/'
    try:
        html = fetch(index)
    except SourceCaptureError as exc:
        if exc.http_status != 404:
            raise
        # A future race-day schedule can exist before a results index is available.
        return schedule_sources(day, needed, fetch)
    soup = BeautifulSoup(html, 'html.parser')
    canonicals = soup.select('link[rel~=canonical]')
    checked(len(canonicals) == 1 and canonicals[0].get('href') == index, 'RESULT_CALENDAR_DATE_MISMATCH')
    calendar_day = date.fromisoformat(day)
    header = calendar_day.strftime('%Y年%m月%d日 レース結果一覧')
    checked(any(h.get_text(' ', strip=True) in (header, '本日 ' + header) for h in soup.select('h2')),
            'RESULT_CALENDAR_DATE_MISMATCH')
    tables = soup.select('.raceinfo_table')
    checked(len(tables) == 1, 'RESULT_CALENDAR_TABLE_MISSING')
    found = {}
    for anchor in tables[0].select('a[href]'):
        link = urlsplit(urljoin(index, anchor['href']))
        if '/racedetail/' not in link.path:
            continue
        match = day_links.DETAIL.fullmatch(link.path)
        checked(match and link.scheme == 'https' and link.netloc == 'keirin.kdreams.jp' and
                link.query in ('', 'pageType=showResult', 'pageType=result') and not link.fragment,
                'RESULT_CALENDAR_LINK_INVALID')
        rid = day.replace('-', '') + match[1] + match[4]
        if rid not in needed:
            continue
        label = anchor.get_text(' ', strip=True)
        checked(re.fullmatch(str(int(match[4])) + r'R(?:\s*[（(]?(?:競走中止|開催中止|レース中止|中止)[）)]?)?', label),
                'RESULT_CALENDAR_RACE_NUMBER_MISMATCH')
        canonical = KD + link.path
        consensus.check_race_url(provider='Kdreams', url=canonical, race_id=rid)
        checked(rid not in found or found[rid] == canonical, 'CONFLICTING_DAY_LINKS')
        found[rid] = canonical
    missing = needed - found.keys()
    if missing:
        found.update(schedule_sources(day, missing, fetch))
    checked(needed == found.keys(), 'PUBLISHED_RACE_NOT_IN_SOURCE_CALENDAR')
    return found


def schedule_sources(day, needed, fetch):
    schedule = day_links.discover(day_jst=day, registered_ids=sorted(needed), fetch=fetch)
    links = {r['race_id']: r['kdreams_url'] for r in schedule['manifest']['races']}
    checked(needed == links.keys(), 'PUBLISHED_RACE_NOT_IN_SOURCE_CALENDAR')
    return links


def forecast_row(row, day, ranked):
    rid = row['race_id']
    checked(isinstance(rid, str) and re.fullmatch(day.replace('-', '') + r'[0-9]{4}', rid), 'PUBLIC_RACE_ID_MISMATCH')
    number = int(rid[-2:])
    if ranked:
        selected = row['predictions']
        if selected is None and row['lines'] is None:
            return None
        cutoff = row['cutoff_at']
        riders = row['riders']
        checked(all(isinstance(selected[m], list) and selected[m] for m in ('2t', '3t')), 'RANKED_FORECAST_MISSING')
        markets = [(selected['2t'], 2), (selected['3t'], 3)]
    else:
        checked(row['date'] == day and row['race_no'] == number and
                all(isinstance(row.get(arm), dict) for arm in ('A', 'B')), 'LEGACY_FORECAST_INVALID')
        cutoff = row['published_cutoff_at']
        riders = row['observed_riders']
        markets = [(row[arm][field], places) for arm in ('A', 'B')
                   for field, places in [('ranked_tickets', 3), ('ranked_2ren_tan', 2)]]
    cars = {r['number'] for r in riders}
    for tickets, places in markets:
        checked(isinstance(tickets, list) and all(isinstance(ticket, list) and len(ticket) == places and
                all(type(n) is int and n in cars for n in ticket) and len(set(ticket)) == places
                for ticket in tickets), 'PUBLIC_TICKET_ROSTER_MISMATCH')
    at = datetime.fromisoformat(cutoff)
    checked(at.utcoffset() is not None and at.astimezone(JST).date().isoformat() == day, 'PUBLIC_CUTOFF_DAY_MISMATCH')
    src = row['source_url']
    checked(isinstance(src, str), 'PUBLIC_FORECAST_SOURCE_REQUIRED')
    if src == 'https://keirin.netkeiba.com/race/entry/?race_id=' + rid:
        src = None
    if src is not None:
        consensus.check_race_url(provider='Kdreams', url=src, race_id=rid)
        checked(not urlsplit(src).query, 'RESULT_SOURCE_NOT_CANONICAL')
    quote_url = (row.get('quote') or {}).get('source_url')
    if quote_url:
        consensus.check_race_url(provider='Kdreams', url=quote_url, race_id=rid)
        checked(not urlsplit(quote_url).query and src in (None, quote_url), 'CONFLICTING_PUBLISHED_SOURCES')
        src = quote_url
    return {'race_id': rid, 'date': day, 'race_no': number, 'venue': row['venue'],
            'published_cutoff_at': cutoff, 'source_url': src,
            'observed_riders': [{'number': r['number']} for r in riders]}


def build_roster(raw, path, day, previous, fetch_calendar):
    payload = decoded(raw, MAX_ASSET)
    digest = sha(payload)
    packet = json.loads(payload)
    kind = FILE.fullmatch(path)[2]
    ranked = kind.startswith('ranked')
    checked(packet['schema'] == SCHEMA[kind] and packet['date'] == day, 'PUBLIC_FORECAST_SCHEMA_OR_DAY_MISMATCH')
    checked(isinstance(packet['races'], list) and 0 < len(packet['races']) <= 300, 'PUBLIC_ROSTER_SIZE_INVALID')
    previous_rows = {}
    same_asset = False
    if previous is not None:
        validate_roster(previous, consensus)
        expected = previous['forecast_asset_sha256']
        same_asset = expected == digest
        old_time = datetime.fromisoformat(previous['generated_at'])
        new_time = datetime.fromisoformat(packet['generated_at'])
        # The legacy publisher fingerprinted the original deterministic gzip file.
        if not ranked and not same_asset and old_time == new_time:
            same_asset = expected in (sha(raw), sha(gzip.compress(payload, compresslevel=9, mtime=0)))
        checked(same_asset or new_time > old_time, 'EXISTING_PUBLIC_FORECAST_CHANGED')
        previous_rows = {r['race_id']: r for r in previous['races']}
    ids = [r['race_id'] for r in packet['races']]
    checked(len(ids) == len(set(ids)), 'DUPLICATE_PUBLIC_RACE_ID')
    rows = [value for r in packet['races'] if (value := forecast_row(r, day, ranked)) is not None]
    needs_calendar = set()
    for row in rows:
        rid = row['race_id']
        if row['source_url'] is None and rid in previous_rows:
            row['source_url'] = previous_rows[rid]['source_url']
        if row['source_url'] is None:
            needs_calendar.add(rid)
    if needs_calendar:
        links = calendar_sources(day, needs_calendar, fetch_calendar)
        for row in rows:
            if row['source_url'] is None:
                row['source_url'] = links[row['race_id']]
    roster = {'schema': 'KEIRIN_PUBLIC_RESULT_ROSTER_V1', 'date': day,
              'generated_at': packet['generated_at'], 'forecast_asset_sha256': digest, 'races': rows}
    validate_roster(roster, consensus)
    if previous is not None:
        current_rows = {r['race_id']: r for r in rows}
        checked(previous['date'] == day and all(current_rows.get(rid) == old for rid, old in previous_rows.items()),
                'EXISTING_PUBLIC_ROSTER_CONFLICT')
        if same_asset:
            checked(previous_rows == current_rows and old_time == new_time, 'EXISTING_PUBLIC_ROSTER_CONFLICT')
            return previous
    return roster


def register(path, roster, previous=None):
    """Serialize create/replace, retaining the exact previous manifest on any revision."""
    raw = (json.dumps(roster, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        current_raw = path.read_bytes() if path.exists() else None
        current = json.loads(current_raw) if current_raw is not None else None
        if current == roster:
            return 'existing'
        checked(current == previous, 'CONCURRENT_PUBLIC_ROSTER_CHANGE')
        if previous is not None:
            archive = path.parent / 'revisions' / roster['date'] / (previous['forecast_asset_sha256'] + '.json')
            archive.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, archive)
            except FileExistsError:
                checked(archive.read_bytes() == current_raw, 'PUBLIC_ROSTER_REVISION_CONFLICT')
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            temp = Path(tmp.name)
            try:
                tmp.write(raw)
                tmp.flush()
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        return 'created' if previous is None else 'updated'
    finally:
        os.close(directory)


def discover(state_directory, *, site_fetch=fetch_site, calendar_fetch=fetch_once):
    report = {'created': [], 'updated': [], 'existing': [], 'errors': {}}
    directory = Path(state_directory) / 'rosters'
    # Only categorical errors are emitted; never include input page text or response bodies.
    def error_code(exc):
        if isinstance(exc, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{2,100}', str(exc)):
            return str(exc)
        return type(exc).__name__
    try:
        dates, has_invalid_path = published_paths(site_fetch(SITE + '/'))
        if has_invalid_path:
            report['errors']['site'] = 'INVALID_ADVERTISED_PUBLIC_PATH'
        directory.mkdir(parents=True, exist_ok=True)
    except (KeyError, TypeError, ValueError, OSError, EOFError, HTTPException) as exc:
        report['errors']['site'] = error_code(exc)
        return report
    for day, paths in sorted(dates.items(), reverse=True):
        try:
            checked(len(paths) == 1, 'AMBIGUOUS_PUBLIC_FORECAST_DATE')
            path = next(iter(paths))
            target = directory / (day + '.json')
            previous = json.loads(target.read_bytes()) if target.exists() else None
            roster = build_roster(site_fetch(SITE + path), path, day, previous, calendar_fetch)
            report[register(target, roster, previous)].append(day)
        except (AttributeError, KeyError, TypeError, ValueError, OSError, EOFError, HTTPException) as exc:
            report['errors'][day] = error_code(exc)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    report = discover(parser.parse_args().state_directory)
    print(json.dumps(report, sort_keys=True))
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
