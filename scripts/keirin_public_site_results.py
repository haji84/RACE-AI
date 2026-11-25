"""Compare the two paid-order tables for the public daily result view."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import time
from unicodedata import normalize

PAYOUT_TABLES = {'Kdreams': 'table.refund_table', 'netkeirin': 'table.Payout_Detail_Table'}
SOURCE_STOP_CODES = {
    'PROVIDER_DENIED_OR_RATE_LIMITED_STOP', 'PUBLIC_PROVIDER_HTTP_ERROR_STOP',
    'PUBLIC_PROVIDER_UNAVAILABLE_STOP', 'PROVIDER_NON_HTML_OR_REDIRECT',
    'PROVIDER_EMPTY_OR_OVERSIZED_HTML',
}


def checked(condition, code):
    if not condition:
        raise ValueError(code)


def text(node):
    return normalize('NFKC', node.get_text(' ', strip=True))


def payout(order, amount, places):
    label = r'\s*(?:>|-|－|→)\s*'.join([r'([1-9])'] * places)
    match = re.fullmatch(label, order)
    money = re.fullmatch(r'([1-9][0-9,]*)\s*円(?:\s*\([0-9]+\))?', amount)
    checked(match and money, 'PAYOUT_NOT_PUBLISHED')
    cars = list(map(int, match.groups()))
    yen = int(money[1].replace(',', ''))
    checked(len(set(cars)) == places and 100 <= yen <= 10**9, 'PAYOUT_INVALID')
    return cars, yen


def market_payouts(soup, provider):
    table = soup.select_one(PAYOUT_TABLES[provider])
    checked(table is not None, 'PAYOUT_NOT_PUBLISHED')
    if provider == 'Kdreams':
        rows = table.find_all('tr')
        checked(len(rows) == 2, 'PAYOUT_TABLE_LAYOUT_CHANGED')
        headings = [re.sub(r'\s+', '', text(th)) for th in rows[0].find_all('th', recursive=False)]
        checked(headings == ['2枠連', '2車連', '3連勝', 'ワイド'], 'PAYOUT_TABLE_HEADER_CHANGED')
        cells = [text(cell) for cell in rows[1].find_all('td', recursive=False)]
        checked(len(cells) == 6 and cells[::2] == ['単'] * 3, 'PAYOUT_TABLE_LAYOUT_CHANGED')
        result = {}
        for market, index, places in [('2t', 3, 2), ('3t', 5, 3)]:
            value = re.fullmatch(r'([1-9](?:\s*-\s*[1-9]){1,2})\s+(.+)', cells[index])
            checked(value is not None, 'PAYOUT_NOT_PUBLISHED')
            result[market] = payout(value[1], value[2], places)
        return result

    result = {}
    for label, market, places in [('2車単', '2t', 2), ('3連単', '3t', 3)]:
        matching = [row for row in table.find_all('tr')
                    if row.th and text(row.th) == label]
        checked(len(matching) == 1, 'PAYOUT_NOT_PUBLISHED')
        cells = matching[0].select('td.Result, td.Payout')
        checked(len(cells) == 2, 'PAYOUT_TABLE_LAYOUT_CHANGED')
        result[market] = payout(text(cells[0]), text(cells[1]), places)
    return result


def has_special_notice(soup, provider):
    table = soup.select_one(PAYOUT_TABLES[provider])
    if table is None:
        return False
    cells = table.select(':scope > tr > td, :scope > tbody > tr > td')
    notices = {'返還', '全返還', '同着', 'レース中止', '発売中止'}
    return any(cell.find('a') is None and text(cell).rstrip('。') in notices for cell in cells)


def observe(race, provider, url, fetch, consensus, evidence):
    from bs4 import BeautifulSoup
    consensus.check_race_url(provider=provider, url=url, race_id=race['race_id'])
    body = fetch(url)
    observed = datetime.now(timezone.utc).isoformat()
    soup = BeautifulSoup(body, 'html.parser')
    date = datetime.fromisoformat(race['date'])
    title = text(soup.title) if soup.title else ''
    checked(race['venue']+'競輪' in title
            and date.strftime('%Y年')+str(date.month)+'月'+str(date.day)+'日' in title
            and re.search(r'(?<!\d)'+str(race['race_no'])+r'\s*R(?!\d)', title), 'RACE_TITLE_NOT_CONFIRMED')
    try:
        triple = consensus.parse_observation(raw=body, provider=provider, source_url=url,
                                            race_id=race['race_id'], observed_at=observed)
    except consensus.ResultConsensusError as error:
        if str(error) == 'SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL' and not has_special_notice(soup, provider):
            raise ValueError('RESULT_SPECIAL_NOTICE_UNCONFIRMED') from None
        raise
    amounts = market_payouts(soup, provider)
    checked(amounts['3t'] == (triple['winning_triple'], triple['payout_per_100yen']), 'PAYOUT_TABLE_DISAGREES')
    checked(amounts['2t'][0] == amounts['3t'][0][:2], 'PAYOUT_MARKETS_DISAGREE')
    cars = {rider['number'] for rider in race['observed_riders']}
    checked(set(amounts['3t'][0]) <= cars, 'PAYOUT_ROSTER_CHANGED')
    evidence.append({'race_id':race['race_id'], 'provider':provider, 'checked_at':observed,
                     'sha256':triple['source_bytes_sha256']})
    return amounts, {'source_id':'kdreams' if provider == 'Kdreams' else 'netkeirin',
                     'url':url, 'checked_at':observed}


def validate_roster(published, consensus):
    checked(set(published)=={'schema','date','generated_at','forecast_asset_sha256','races'} and
            published['schema']=='KEIRIN_PUBLIC_RESULT_ROSTER_V1' and
            re.fullmatch(r'20\d\d-\d\d-\d\d',published['date']) and
            re.fullmatch(r'[a-f0-9]{64}',published['forecast_asset_sha256']) and
            0 < len(published['races']) <= 300,'INVALID_PUBLIC_RESULT_ROSTER')
    checked(datetime.fromisoformat(published['generated_at']).utcoffset() is not None,'FORECAST_CLOCK_MISSING')
    ids=set()
    for race in published['races']:
        checked(set(race)=={'race_id','date','venue','race_no','published_cutoff_at','source_url','observed_riders'},'INVALID_PUBLIC_ROSTER_ROW')
        rid=race['race_id']
        checked(re.fullmatch(published['date'].replace('-','')+r'\d{4}',rid) and rid not in ids and
                race['date']==published['date'] and type(race['race_no']) is int and 1<=race['race_no']<=12 and
                int(rid[-2:])==race['race_no'] and isinstance(race['venue'],str) and 0<len(race['venue'])<=100,
                'PUBLIC_RACE_ID_MISMATCH')
        checked(datetime.fromisoformat(race['published_cutoff_at']).utcoffset() is not None,'RESULT_CUTOFF_CLOCK_MISSING')
        consensus.check_race_url(provider='Kdreams',url=race['source_url']+'?pageType=result',race_id=rid)
        numbers=[rider['number'] for rider in race['observed_riders']]
        checked(all(set(rider)=={'number'} for rider in race['observed_riders']) and 3<=len(numbers)<=9 and
                len(set(numbers))==len(numbers) and all(type(n) is int and 1<=n<=9 for n in numbers), 'RESULT_ROSTER_MISMATCH')
        ids.add(rid)


def provider_pause(error, now):
    status = getattr(error, 'http_status', None)
    if status not in (401, 403, 429):
        return None
    retry_at = None
    if status == 429:
        value = getattr(error, 'retry_after', None) or ''
        retry_at = now + timedelta(hours=1)
        if re.fullmatch(r'[0-9]+', value):
            try:
                retry_at = now + timedelta(seconds=int(value))
            except (ValueError, OverflowError):
                retry_at = None
        elif value:
            try:
                reported = parsedate_to_datetime(value)
                if reported.utcoffset() is not None:
                    retry_at = max(now, reported)
            except (TypeError, ValueError, OverflowError):
                pass
    return {'status': status, 'retry_at': retry_at.astimezone(timezone.utc).isoformat() if retry_at else None}


def collect(published, fetch, consensus, *, previous=None, now=None, resume_after=None, can_poll=None):
    validate_roster(published,consensus)
    date = published['date']
    entries, evidence = [], []
    stopped = False
    poll_at = now or datetime.now(timezone.utc)
    old = {}
    if previous:
        checked(previous.get('schema')=='KEIRIN_PUBLISHED_RESULTS_V1' and previous.get('date')==date and
                datetime.fromisoformat(previous['checked_at'])<=poll_at,'INVALID_PREVIOUS_RESULTS')
        old={entry['race_id']:entry for entry in previous['races']}
        checked(len(old)==len(previous['races']) and set(old)<={r['race_id'] for r in published['races']},'PREVIOUS_RESULT_ROSTER_MISMATCH')
    attempted = False
    ordered = sorted(published['races'], key=lambda row: (
        datetime.fromisoformat(row['published_cutoff_at']), row['race_id']))
    order = {race['race_id']: index for index, race in enumerate(ordered)}
    start = order.get(resume_after, -1) + 1
    generated = datetime.fromisoformat(published['generated_at'])
    for race in ordered[start:] + ordered[:start]:
        rid = race['race_id']
        existing=old.get(rid)
        if existing and (existing['state']=='matched' or existing.get('reason')=='special_result'):
            entries.append(existing)
            continue
        if max(datetime.fromisoformat(race['published_cutoff_at']), generated) >= poll_at:
            continue
        if stopped:
            entries.append(existing or {'race_id':rid, 'state':'pending', 'reason':'source_unavailable'})
            continue
        if can_poll is not None and not can_poll():
            if existing:
                entries.append(existing)
            continue
        try:
            attempted=True
            evidence.append({'race_id': rid, 'attempted': True})
            kd, first = observe(race, 'Kdreams', race['source_url']+'?pageType=result', fetch, consensus, evidence)
            net, second = observe(race, 'netkeirin', 'https://keirin.netkeiba.com/race/result/?race_id='+rid,
                                  fetch, consensus, evidence)
            checked(kd == net, 'PAYOUT_SOURCES_DISAGREE')
            comparison = {'race_id':rid, 'observed_at':second['checked_at'], 'authority':'cross_source_reference',
                          'comparison_scope':'POST_CUTOFF_REFERENCE', 'winning_3t':kd['3t'][0],
                          'winning_2t':kd['2t'][0], 'payouts_100yen':{market:value[1] for market,value in kd.items()},
                          'sources':[first,second]}
            entries.append({'race_id':rid, 'state':'matched', 'comparison':comparison})
        except (ValueError, OSError) as error:
            code = str(error)
            if code == 'PUBLIC_PROVIDER_HTTP_ERROR_STOP' and getattr(error, 'http_status', None) == 404:
                code = 'RESULT_HTTP_NOT_FOUND'
            if code in SOURCE_STOP_CODES:
                stopped = True
                reason, state = 'source_unavailable', 'pending'
            elif code in ('PAYOUT_NOT_PUBLISHED','TRIFECTA_RESULT_NOT_PUBLISHED','SOURCE_HTML_NOT_FINAL_RESULT_PAGE','RESULT_HTTP_NOT_FOUND'):
                reason, state = 'result_unpublished', 'pending'
            elif code == 'SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL':
                reason, state = 'special_result', 'held'
            else:
                reason, state = 'source_disagreement', 'held'
            entries.append({'race_id':rid, 'state':state, 'reason':reason})
            evidence.append({'race_id':rid, 'state':state,
                             'code':code if re.fullmatch(r'[A-Z0-9_]{3,90}', code) else 'SOURCE_CHECK_FAILED'})
            pause = provider_pause(error, datetime.now(timezone.utc)) if stopped else None
            if pause is not None:
                evidence[-1]['provider_pause'] = pause
    if not attempted and previous is not None:
        return previous,evidence
    return {'schema':'KEIRIN_PUBLISHED_RESULTS_V1', 'date':date,
            'checked_at':datetime.now(timezone.utc).isoformat(),
            'races':sorted(entries, key=lambda entry: order[entry['race_id']])}, evidence


def pause_is_active(path, now):
    if not path.exists():
        return False
    pause = json.loads(path.read_bytes())
    checked(type(pause) is dict and set(pause) == {'status', 'retry_at'} and pause['status'] in (401,403,429),
            'INVALID_PUBLIC_PROVIDER_PAUSE')
    if pause['retry_at'] is None or datetime.fromisoformat(pause['retry_at']) > now:
        print(json.dumps({'provider_paused': pause}))
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    parser.add_argument('--stop-when-complete', action='store_true',
                        help='Return 10 when every published race is matched or has a special result.')
    args = parser.parse_args()
    from race_ai import keirin_secondary_result_consensus as consensus
    from scripts.keirin_capture_public_two_sources import fetch_once
    rosters=sorted((args.state_directory/'rosters').glob('20??-??-??.json'))
    checked(bool(rosters),'PUBLIC_RESULT_ROSTERS_MISSING')
    result_dir=args.state_directory/'results'
    result_dir.mkdir(exist_ok=True)
    pause_file = result_dir / 'provider-pause.json'
    if pause_is_active(pause_file, datetime.now(timezone.utc)):
        return 0

    position_file = result_dir / 'poll-positions.json'
    positions = json.loads(position_file.read_bytes()) if position_file.exists() else {}
    checked(type(positions) is dict and all(
        re.fullmatch(r'20\d\d-\d\d-\d\d', day) and type(rid) is str and
        re.fullmatch(day.replace('-', '') + r'\d{4}', rid)
        for day, rid in positions.items()), 'INVALID_PUBLIC_RESULT_POLL_POSITIONS')
    previous_positions = positions.copy()
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    day_packets = []
    catchup_needed = False
    for path in rosters:
        destination=result_dir/path.name
        previous=json.loads(destination.read_bytes()) if destination.exists() else None
        if path.stem < today and not catchup_needed:
            final_ids = {entry['race_id'] for entry in (previous or {}).get('races', [])
                         if entry['state'] == 'matched' or entry.get('reason') == 'special_result'}
            catchup_needed = (previous is None or any(race['race_id'] not in final_ids
                              for race in json.loads(path.read_bytes())['races']))
        day_packets.append((path.stem != today, previous['checked_at'] if previous else '',
                            path, destination))

    # Check today's due races first. Leave 90s of the existing 450s budget for prior
    # days when they still have work. Their saved timestamps and cursors rotate retries.
    deadline = time.monotonic() + 450

    complete = True
    status = 0
    for other_day, _, path, destination in sorted(day_packets):
        if time.monotonic() >= deadline:
            complete = False
            break
        day = path.stem
        published = json.loads(path.read_bytes())
        previous = json.loads(destination.read_bytes()) if destination.exists() else None
        checked(day == published['date'], 'PUBLIC_ROSTER_FILENAME_MISMATCH')
        day_deadline = deadline - 90 if not other_day and catchup_needed else deadline
        packet,evidence=collect(published,fetch_once,consensus,previous=previous,
                                resume_after=positions.get(day),can_poll=lambda: time.monotonic() < day_deadline)
        if packet!=previous:
            destination.write_text(json.dumps(packet,ensure_ascii=False,separators=(',', ':'))+'\n')
        resolved = sum(entry['state'] == 'matched' or entry.get('reason') == 'special_result'
                       for entry in packet['races'])
        if resolved < len(published['races']):
            complete = False
            last_attempt = next((row['race_id'] for row in reversed(evidence) if row.get('attempted')), None)
            if last_attempt is not None:
                positions[day] = last_attempt
        else:
            positions.pop(day, None)
        failure = next((row for row in evidence if row.get('code') in SOURCE_STOP_CODES), None)
        print(json.dumps({'date':packet['date'],'checked_at':packet['checked_at'],
                          'race_count':len(published['races']),'updated':packet!=previous,
                          'states':dict(Counter(entry['state'] for entry in packet['races'])),
                          'provider_failure':failure['code'] if failure else None}))
        if failure:
            if 'provider_pause' in failure:
                pause_file.write_text(json.dumps(failure['provider_pause'])+'\n')
            status = 75
            break
    if positions != previous_positions:
        position_file.write_text(json.dumps(positions, sort_keys=True)+'\n')
    return status or (10 if args.stop_when_complete and complete else 0)


if __name__ == '__main__':
    raise SystemExit(main())
