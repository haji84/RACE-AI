"""Compare the two paid-order tables for the public daily result view."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from subprocess import SubprocessError
import time
from unicodedata import category, normalize

PAYOUT_TABLES = {'Kdreams': 'table.refund_table', 'netkeirin': 'table.Payout_Detail_Table'}
RIDER_FINISH_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_REFERENCE_FINISHES_V1'
MAX_FINISH_REPLAYS = 4
MAX_FINISH_REPAIR_ATTEMPTS = 2
SOURCE_STOP_CODES = {
    'PROVIDER_DENIED_OR_RATE_LIMITED_STOP', 'PUBLIC_PROVIDER_HTTP_ERROR_STOP',
    'PUBLIC_PROVIDER_UNAVAILABLE_STOP', 'PROVIDER_NON_HTML_OR_REDIRECT',
    'PROVIDER_EMPTY_OR_OVERSIZED_HTML',
}
JST = timezone(timedelta(hours=9))
# The published race view uses these labels to bind a result to its forecast.
VENUE_NAMES = {
    '11':'函館', '12':'青森', '13':'いわき平', '21':'弥彦', '22':'前橋', '23':'取手', '24':'宇都宮', '25':'大宮',
    '26':'西武園', '27':'京王閣', '28':'立川', '31':'松戸', '32':'千葉', '34':'川崎', '35':'平塚', '36':'小田原',
    '37':'伊東温泉', '38':'静岡', '42':'名古屋', '43':'岐阜', '44':'大垣', '45':'豊橋', '46':'富山', '47':'松阪',
    '48':'四日市', '51':'福井', '53':'奈良', '54':'向日町', '55':'和歌山', '56':'岸和田', '61':'玉野',
    '62':'広島', '63':'防府', '71':'高松', '73':'小松島', '74':'高知', '75':'松山', '81':'小倉', '83':'久留米',
    '84':'武雄', '85':'佐世保', '86':'別府', '87':'熊本',
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


def _finish_name(name):
    key = ''.join(normalize('NFKC', name).split())
    checked(0 < len(key) <= 80 and not any(c in '<>' or category(c).startswith('C') for c in key),
            'RESULT_RIDER_NAME')
    return key


def _finish_place(value, provider):
    # The result tables distinguish withdrawal, disqualification and failure to finish.
    # The sidecar publishes an ordinal only when both sources actually show one.
    match = re.fullmatch(r'([1-9])' if provider == 'Kdreams' else r'([1-9])着', value)
    if match:
        return int(match[1])
    nonnumeric = {
        '失': 'disqualified', '失格': 'disqualified',
        '落': 'fall', '落棄': 'fall', '落車棄権': 'fall', '落車': 'fall',
        '棄': 'dnf', '棄権': 'dnf', '欠': 'withdrawal', '欠車': 'withdrawal',
    }
    checked(value in nonnumeric, 'RESULT_FINISH_STATUS')
    return nonnumeric[value]


def _provider_finishes(soup, provider):
    kd = provider == 'Kdreams'
    tables = soup.select('table.result_table' if kd else 'table#All_Result_Table')
    checked(len(tables) == 1, 'RESULT_FINISH_TABLE')
    head, *rows = tables[0].find_all('tr')
    headers = [''.join(text(cell).split()) for cell in head.find_all('th', recursive=False)]
    checked(headers[:4] == (['予想', '着順', '車番', '選手名'] if kd else ['着', '枠番', '車番', '選手名']) and
            3 <= len(rows) <= 9, 'RESULT_FINISH_TABLE_LAYOUT')
    results = {}
    registrations = set()
    for row in rows:
        cells = row.find_all('td', recursive=False)
        checked(len(cells) == len(headers), 'RESULT_FINISH_TABLE_LAYOUT')
        ordinal, number, name_cell = cells[1 if kd else 0], text(cells[2]), cells[3]
        checked(re.fullmatch(r'[1-9]', number) and int(number) not in results, 'RESULT_FINISH_NUMBER')
        registration = None
        if not kd:
            anchors = name_cell.find_all('a', href=True)
            checked(len(anchors) == 1, 'RESULT_FINISH_REGISTRATION')
            profile = re.fullmatch(r'(?:https://keirin\.netkeiba\.com)?/db/profile/\?id=([0-9]{5,6})',
                                   anchors[0]['href'])
            checked(profile and int(profile[1]) > 0, 'RESULT_FINISH_REGISTRATION')
            registration = profile[1].zfill(6)
            checked(registration not in registrations, 'RESULT_FINISH_REGISTRATION')
            registrations.add(registration)
            names = anchors[0].select('dt.PlayerName')
            checked(len(names) == 1, 'RESULT_RIDER_NAME')
            name_cell = names[0]
        results[int(number)] = (_finish_name(text(name_cell)), _finish_place(text(ordinal), provider), registration)
    return results


def _paired_rider_finish(race, winning_triple, sources, observations):
    if len(observations) != 2 or not all(row.get('finishers') for row in observations):
        return None
    first, second = (row['finishers'] for row in observations)
    expected = {rider['number'] for rider in race['observed_riders']}
    if first.keys() != second.keys() or second.keys() != expected or any(
            first[number][:2] != second[number][:2] for number in expected):
        return None
    classified = sorted((rider[1], number) for number, rider in second.items() if type(rider[1]) is int)
    if [place for place, _ in classified] != list(range(1, len(classified) + 1)) or \
            [number for _, number in classified[:3]] != winning_triple:
        return None
    times = [datetime.fromisoformat(source['checked_at']) for source in sources]
    if not datetime.fromisoformat(race['published_cutoff_at']) < times[0] <= times[1]:
        return None
    return dict(race_id=race['race_id'], observed_at=sources[1]['checked_at'],
                sources=[dict(source, source_sha256=observation['sha256'])
                         for source, observation in zip(sources, observations)],
                riders=[dict(number=number, name=name, registration=registration,
                             place=place if type(place) is int else None)
                        for number, (name, place, registration) in sorted(second.items())])


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
    try:
        finishers = _provider_finishes(soup, provider)
    except (ValueError, TypeError, KeyError):
        finishers = None
    evidence.append({'race_id':race['race_id'], 'provider':provider, 'checked_at':observed,
                     'sha256':triple['source_bytes_sha256'], 'finishers':finishers})
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


def discover_missing_links(day, missing, fetch):
    from scripts import keirin_discover_public_race_links as links

    date = datetime.fromisoformat(day).date()
    calendar = links.CALENDAR.format(year=date.year, month=date.month, day=date.day)
    meetings = links.linked_racecards(fetch(calendar), base_url=calendar, day=day)
    selected = {}
    for venue in sorted({rid[8:10] for rid in missing} & meetings.keys()):
        url = meetings[venue]
        details = links.linked_details(fetch(url), base_url=url, day=day, venue=venue)
        selected.update((rid, link) for rid, link in details.items() if rid in missing)
    return selected


def _reference_roster_inputs(raw, day, missing, fetch, now):
    """Confirm starter cars, detail link and closing clock from a linked meeting page."""
    from race_ai.keirin_public_meeting_roster import parse_meeting
    from scripts import keirin_discover_public_race_links as links
    from scripts.keirin_publish_meeting_rosters import checked_packet

    packet = checked_packet(json.loads(raw))
    checked(packet['day'] == day and datetime.fromisoformat(packet['published_at']) <= now,
            'PUBLIC_ROSTER_REFERENCE_DAY_MISMATCH')
    venues = {}
    for row in packet['races']:
        if row['race_id'] in missing:
            venues.setdefault(row['source_url'], []).append(row)
    for url, rows in sorted(venues.items()):
        venue = rows[0]['race_id'][8:10]
        html = fetch(url)
        try:
            fields = {row['race_id']: row['riders'] for row in
                      parse_meeting(html, day=day, url=url, observed_at=now)}
            details = links.linked_details(html, base_url=url, day=day, venue=venue)
            cutoffs = links.linked_cutoff_hints(html, base_url=url, day=day, venue=venue)
        except ValueError:
            continue
        for row in rows:
            rid = row['race_id']
            if rid not in fields or rid not in details or rid not in cutoffs:
                continue
            published = {rider['number']: _finish_name(rider['name']) for rider in row['riders']}
            observed = {rider['number']: _finish_name(rider['name']) for rider in fields[rid]}
            if published == observed and 3 <= len(observed) <= 9:
                yield row, details[rid], cutoffs[rid]


def build_public_roster(forecast_bytes, source_rows, official_rows, *, display_cutoffs=None, archived_links=None,
                        previous=None, results=None, fetch=None, dt_shortlists=None, allow_partial=False):
    from race_ai import keirin_public_forecasts as public
    from race_ai import keirin_secondary_result_consensus as consensus

    forecast = public.checked(json.loads(forecast_bytes))
    day = forecast['day']
    old = {}
    if previous is not None:
        validate_roster(previous, consensus)
        checked(previous['date'] == day, 'PUBLIC_ROSTER_INPUT_DAY_MISMATCH')
        old = {row['race_id']: row for row in previous['races']}
    registered = {row['race_id'] for row in forecast['races']}
    checked(old.keys() <= registered, 'PUBLIC_ROSTER_SHRANK')
    sources = {row['race_id']: row for row in source_rows}
    official = {row['race_id']: row for row in official_rows}
    dt_starters = {}
    if dt_shortlists is not None:
        from research.chatgpt_dt_r1 import public_shortlists as dt
        packet = dt.checked(dt_shortlists)
        dt_starters = {row['race_id']: row for row in packet['races']}
        checked(packet['day'] == day and dt_starters.keys() == registered, 'PUBLIC_ROSTER_DT_R1_PARTITION')
    saved_results = {row['race_id']: row for row in (results or {}).get('races', [])}
    display_cutoffs = display_cutoffs or {}
    archived_links = archived_links or {}
    rows, missing = {}, set()
    for item in forecast['races']:
        rid = item['race_id']
        prior, source = old.get(rid), sources.get(rid)
        cutoff = item['cutoff_at'] or display_cutoffs.get(rid)
        if prior is not None:
            row = prior
            if cutoff is not None and public.when(cutoff) != public.when(prior['published_cutoff_at']):
                result = saved_results.get(rid, {})
                observations = []
                if result.get('state') == 'matched':
                    comparison = result['comparison']
                    observations = [comparison['observed_at'], *(source['checked_at'] for source in comparison['sources'])]
                elif result.get('reason') == 'special_result':
                    observations = [results['checked_at']]
                checked(all(public.when(cutoff) <= public.when(at) for at in observations),
                        'PUBLIC_ROSTER_SETTLED_CLOCK_CONFLICT')
                row = dict(prior, published_cutoff_at=cutoff)
        else:
            cutoff = cutoff or (source or {}).get('cutoff_at')
            field = source if source is not None else official.get(rid)
            if field is None or cutoff is None:
                # Fill missing pre-race facts separately. Result publication
                # still requires the normal two distinct providers.
                dt_row = dt_starters.get(rid)
                if dt_row is None or public.when(dt_row['source_at']) >= public.when(cutoff or dt_row['cutoff_at']):
                    checked(allow_partial, 'PUBLIC_ROSTER_INPUT_INCOMPLETE')
                    continue
                cutoff = cutoff or dt_row['cutoff_at']
                if field is None:
                    field = dict(riders=[{'number': number} for number in dt_row['starter_cars']])
            venue = rid[8:10]
            link = source['source_url'] if source else archived_links.get(rid)
            row = dict(race_id=rid, date=day, venue=VENUE_NAMES.get(venue, '開催コード ' + venue),
                       race_no=int(rid[-2:]), published_cutoff_at=cutoff,
                       source_url=link,
                       observed_riders=[{'number': rider['number']} for rider in field['riders']])
            if link is None:
                missing.add(rid)
        rows[rid] = row

    if missing:
        resolved = discover_missing_links(day, missing, fetch)
        checked(allow_partial or resolved.keys() == missing, 'PUBLIC_ROSTER_PUBLISHED_LINK_MISSING')
        for rid in missing:
            if rid in resolved:
                rows[rid]['source_url'] = resolved[rid]
            else:
                del rows[rid]
    checked(bool(rows), 'PUBLIC_ROSTER_INPUT_INCOMPLETE')
    if previous is not None and rows == old:
        return previous
    roster = dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=day,
                  generated_at=previous['generated_at'] if previous else forecast['published_at'],
                  forecast_asset_sha256=sha256(forecast_bytes).hexdigest(),
                  races=[rows[rid] for rid in sorted(rows)])
    validate_roster(roster, consensus)
    return roster


def published_display_cutoffs(store, head, forecast):
    from race_ai import keirin_public_forecast_updates as updates
    from race_ai import keirin_public_forecasts as public

    day = forecast['day']
    registered = {row['race_id'] for row in forecast['races']}
    cutoffs = {}
    # Follow the existing public view's order for rows without an official clock.
    for family, validate in (('references', public.checked_reference),
                             ('research', public.checked_research), ('updates', updates.checked)):
        raw = store.read_previous(head, f'{family}/{day}.json')
        if raw is None:
            continue
        try:
            layer = validate(json.loads(raw))
            if layer['day'] != day or any(row['race_id'] not in registered for row in layer['races']):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        for row in layer['races']:
            cutoffs.setdefault(row['race_id'], row['cutoff_at'])
    return cutoffs


def refresh_public_rosters(state, store, fetch, *, now):
    from race_ai import keirin_dossier_secondary as secondary
    from race_ai import keirin_public_forecast_odds as odds
    from race_ai import keirin_public_forecasts as public
    from research.chatgpt_dt_r1 import public_shortlists as dt
    from scripts.keirin_public_rider_projection import _checked_starters

    head = store.head()
    checked(head is not None, 'PUBLIC_FORECAST_STATE_UNAVAILABLE')
    store.run(['fetch', '--no-tags', '--depth=1', store.remote, head])
    today = now.astimezone(JST).date()
    directory = state / 'rosters'
    directory.mkdir(exist_ok=True)
    ready = True
    for date in (today, today - timedelta(days=1)):
        day = date.isoformat()
        raw = store.read_previous(head, f'forecasts/{day}.json')
        if raw is None:
            continue
        target = directory / f'{day}.json'
        previous = json.loads(target.read_bytes()) if target.exists() else None
        result_path = state / 'results' / target.name
        results = json.loads(result_path.read_bytes()) if result_path.exists() else None
        try:
            snapshot = public.checked(json.loads(raw))
            checked(snapshot['day'] == day and public.when(snapshot['published_at']) <= now,
                    'PUBLIC_ROSTER_INPUT_DAY_MISMATCH')
            registered = {row['race_id'] for row in snapshot['races']}
            missing = registered - {r['race_id'] for r in (previous or {}).get('races', [])}
            display_cutoffs = published_display_cutoffs(store, head, snapshot) if any(
                row['cutoff_at'] is None for row in snapshot['races']) else {}
            context_rows, starter_rows = [], []
            dt_shortlists = None
            archived_links = {}
            if missing:
                context = store.read_previous(head, f'rider-context-secondary/{day}.json')
                if context is not None:
                    packet = secondary.checked_day(json.loads(context))
                    checked(packet['day'] == day, 'PUBLIC_ROSTER_INPUT_DAY_MISMATCH')
                    context_rows = packet['races']
                missing_context = missing - {r['race_id'] for r in context_rows}
                if missing_context:
                    starters = store.read_previous(head, f'starters/{day}.json')
                    if starters is not None:
                        packet = _checked_starters(json.loads(starters))
                        checked(packet['day'] == day, 'PUBLIC_ROSTER_INPUT_DAY_MISMATCH')
                        starter_rows = packet['races']
                    existing_links = store.read_previous(head, f'odds/{day}.json')
                    if existing_links is not None:
                        # The registered page URL is useful even when its racecard context is held.
                        packet = odds.checked(json.loads(existing_links))
                        checked(packet['day'] == day, 'PUBLIC_ROSTER_INPUT_DAY_MISMATCH')
                        archived_links = {row['race_id']: row['source_url'] for row in packet['races']}
                    known_cutoffs = {row['race_id'] for row in snapshot['races'] if row['cutoff_at'] is not None}
                    starter_ids = {row['race_id'] for row in starter_rows}
                    ready_inputs = starter_ids & (known_cutoffs | display_cutoffs.keys()) & archived_links.keys()
                    missing_inputs = missing_context - ready_inputs
                    if missing_inputs:
                        dt_raw = store.read_previous(head, f'dt-r1/{day}.json')
                        if dt_raw is not None:
                            try:
                                candidate = dt.checked(public._json(dt_raw))
                                if (candidate['day'] == day and public.when(candidate['published_at']) <= now and
                                        {row['race_id'] for row in candidate['races']} == registered):
                                    dt_shortlists = candidate
                            except (ValueError, TypeError, KeyError):
                                pass
                        if dt_shortlists is None:
                            reference = store.read_previous(head, f'reference-starters/{day}.json')
                            if reference is not None:
                                for row, link, cutoff in _reference_roster_inputs(reference, day, missing_inputs, fetch, now):
                                    rid = row['race_id']
                                    archived_links.setdefault(rid, link)
                                    display_cutoffs.setdefault(rid, cutoff)
                                    if rid not in starter_ids:
                                        starter_rows.append(row)
            roster = build_public_roster(raw, context_rows, starter_rows, display_cutoffs=display_cutoffs,
                                         archived_links=archived_links, previous=previous, results=results,
                                         fetch=fetch, dt_shortlists=dt_shortlists, allow_partial=True)
        except (ValueError, TypeError, KeyError) as error:
            if str(error) in SOURCE_STOP_CODES:
                raise
            print(json.dumps({'roster_day':day,'roster_state':'held', 'reason':str(error)
                              if re.fullmatch(r'[A-Z0-9_]{3,90}', str(error)) else 'PUBLIC_ROSTER_VALIDATION_FAILED'}))
            ready = False
            continue
        missing_count = len(snapshot['races']) - len(roster['races'])
        if missing_count:
            ready = False
        if roster != previous:
            target.write_text(json.dumps(roster, ensure_ascii=False, separators=(',', ':')) + '\n')
        if roster != previous or missing_count:
            print(json.dumps({'roster_day':day,'roster_state':'partial' if missing_count else 'registered',
                              'race_count':len(roster['races']),'missing_count':missing_count}))
    return ready


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


def _observe_pair(race, fetch, consensus, evidence):
    first_observation = len(evidence)
    rid = race['race_id']
    kd, first = observe(race, 'Kdreams', race['source_url']+'?pageType=result', fetch, consensus, evidence)
    net, second = observe(race, 'netkeirin', 'https://keirin.netkeiba.com/race/result/?race_id='+rid,
                          fetch, consensus, evidence)
    checked(kd == net, 'PAYOUT_SOURCES_DISAGREE')
    comparison = {'race_id':rid, 'observed_at':second['checked_at'], 'authority':'cross_source_reference',
                  'comparison_scope':'POST_CUTOFF_REFERENCE', 'winning_3t':kd['3t'][0],
                  'winning_2t':kd['2t'][0], 'payouts_100yen':{market:value[1] for market,value in kd.items()},
                  'sources':[first,second]}
    finish = _paired_rider_finish(race, comparison['winning_3t'], comparison['sources'], evidence[first_observation:])
    return comparison, finish


def collect(published, fetch, consensus, *, previous=None, now=None, resume_after=None, can_poll=None,
            rider_finishes=None):
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
            comparison, finish = _observe_pair(race, fetch, consensus, evidence)
            if rider_finishes is not None and finish is not None:
                rider_finishes[rid] = finish
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
    if not attempted and previous is not None and len(entries) == len(old) and all(old.get(row['race_id']) == row for row in entries):
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


def _read_rider_finishes(path, day, packet, now):
    if not path.exists():
        return {}
    current = json.loads(path.read_bytes())
    checked(type(current) is dict and set(current) == {'schema', 'day', 'published_at', 'races'} and
            current['schema'] == RIDER_FINISH_SCHEMA and current['day'] == day and
            datetime.fromisoformat(current['published_at']) <= now and type(current['races']) is list,
            'PUBLIC_RIDER_FINISH_PREVIOUS_SCHEMA')
    matched = {row['race_id'] for row in (packet or {}).get('races', []) if row['state'] == 'matched'}
    rows = current['races']
    ids = [row['race_id'] for row in rows]
    checked(ids == sorted(set(ids)) and set(ids) <= matched, 'PUBLIC_RIDER_FINISH_PREVIOUS_PARTITION')
    return dict(zip(ids, rows))


def _repair_rider_finishes(published, packet, finishes, fetch, consensus, *, attempts, limit, can_poll):
    """Backfill previously settled rows without changing their payout evidence."""
    old = {row['race_id']: row.get('comparison', {})
           for row in (packet or {}).get('races', []) if row['state'] == 'matched'}
    count = 0
    def priority(row):
        rid = row['race_id']
        return attempts.get(rid, 0), rid

    for race in sorted(published['races'], key=priority):
        rid = race['race_id']
        if attempts.get(rid, 0) >= MAX_FINISH_REPAIR_ATTEMPTS or rid in finishes or not all(
                field in old.get(rid, {}) for field in ('winning_3t', 'winning_2t', 'payouts_100yen')):
            continue
        if count == limit or not can_poll():
            break
        count += 1
        try:
            current, finish = _observe_pair(race, fetch, consensus, [])
            if finish is not None and all(current[key] == old[rid][key]
                                         for key in ('winning_3t', 'winning_2t', 'payouts_100yen')):
                finishes[rid] = finish
        except (ValueError, OSError) as error:
            if str(error) in SOURCE_STOP_CODES and getattr(error, 'http_status', None) != 404:
                return count, error
        attempts[rid] = attempts.get(rid, 0) + 1
    return count, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    parser.add_argument('--refresh-rosters', action='store_true', help='Register new days from the canonical public projections.')
    parser.add_argument('--stop-when-complete', action='store_true',
                        help='Return 10 when every published race is matched or has a special result.')
    args = parser.parse_args()
    from race_ai import keirin_secondary_result_consensus as consensus
    from scripts.keirin_capture_public_two_sources import fetch_once
    result_dir=args.state_directory/'results'
    result_dir.mkdir(exist_ok=True)
    pause_file = result_dir / 'provider-pause.json'
    now = datetime.now(timezone.utc)
    if pause_is_active(pause_file, now):
        return 0

    # Leave time for the last pair of requests and the Git write before the job times out.
    deadline = time.monotonic() + 450

    def can_poll():
        return time.monotonic() < deadline

    def fetch_roster_link(url):
        checked(can_poll(), 'PUBLIC_ROSTER_LOOKUP_BUDGET_PENDING')
        return fetch_once(url)

    complete = True
    if args.refresh_rosters:
        from race_ai.keirin_public_forecasts import PublicForecastGit

        try:
            complete = refresh_public_rosters(args.state_directory, PublicForecastGit(Path.cwd()), fetch_roster_link, now=now)
        except (ValueError, OSError, SubprocessError) as error:
            complete = False
            if str(error) in SOURCE_STOP_CODES:
                pause = provider_pause(error, datetime.now(timezone.utc))
                if pause is not None:
                    pause_file.write_text(json.dumps(pause) + '\n')
                print(json.dumps({'roster_state':'held','provider_failure':str(error)}))
                return 75
            print(json.dumps({'roster_state':'held','reason':'PUBLIC_ROSTER_STATE_READ_FAILED'}))
    rosters=sorted((args.state_directory/'rosters').glob('20??-??-??.json'))
    checked(bool(rosters),'PUBLIC_RESULT_ROSTERS_MISSING')

    position_file = result_dir / 'poll-positions.json'
    positions = json.loads(position_file.read_bytes()) if position_file.exists() else {}
    checked(type(positions) is dict and all(
        re.fullmatch(r'20\d\d-\d\d-\d\d', day) and type(rid) is str and
        re.fullmatch(day.replace('-', '') + r'\d{4}', rid)
        for day, rid in positions.items()), 'INVALID_PUBLIC_RESULT_POLL_POSITIONS')
    previous_positions = positions.copy()
    day_packets = []
    for path in rosters:
        destination=result_dir/path.name
        previous=json.loads(destination.read_bytes()) if destination.exists() else None
        day_packets.append((previous['checked_at'] if previous else '', path, destination, previous))

    status = 0
    finish_dir = result_dir / 'rider-finishes'
    repair_path = result_dir / 'rider-finish-repair.json'
    repair = json.loads(repair_path.read_bytes()) if repair_path.exists() else {}
    checked(type(repair) is dict and len(repair) <= 2 and all(
        re.fullmatch(r'20\d\d-\d\d-\d\d', day) and type(counts) is dict and len(counts) <= 300 and all(
            type(rid) is str and re.fullmatch(day.replace('-', '') + r'\d{4}', rid) and
            type(count) is int and 1 <= count <= MAX_FINISH_REPAIR_ATTEMPTS for rid, count in counts.items())
        for day, counts in repair.items()), 'INVALID_PUBLIC_RIDER_FINISH_REPAIR')
    eligible = {(now.astimezone(JST).date() - timedelta(days=offset)).isoformat() for offset in (0, 1)}
    repair_next = {day: rids for day, rids in repair.items() if day in eligible}
    backfill = []
    for _, path, destination, previous in sorted(day_packets):
        if not can_poll():
            complete = False
            break
        published=json.loads(path.read_bytes())
        day = path.stem
        checked(day==published['date'],'PUBLIC_ROSTER_FILENAME_MISMATCH')
        finish_path = finish_dir / path.name
        prior_finishes = _read_rider_finishes(finish_path, day, previous, now)
        finishes = prior_finishes.copy()
        packet,evidence=collect(published,fetch_once,consensus,previous=previous,
                                resume_after=positions.get(day),can_poll=can_poll,rider_finishes=finishes)
        if packet!=previous:
            destination.write_text(json.dumps(packet,ensure_ascii=False,separators=(',', ':'))+'\n')
        backfill.append((day, published, previous, prior_finishes, finishes, finish_path))
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
    # Live work has first use of the existing execution window. Bounded replay
    # then fills already settled races retained on their race day or the day after.
    budget = MAX_FINISH_REPLAYS
    for day, published, previous, prior, finishes, finish_path in sorted(backfill, reverse=True):
        if status == 0 and budget and day in eligible:
            attempts = dict(repair_next.get(day, {}))
            count, error = _repair_rider_finishes(published, previous, finishes, fetch_once, consensus,
                attempts=attempts, limit=budget, can_poll=can_poll)
            if attempts:
                repair_next[day] = attempts
            budget -= count
            if error is not None:
                pause = provider_pause(error, datetime.now(timezone.utc))
                if pause is not None:
                    pause_file.write_text(json.dumps(pause) + '\n')
                print(json.dumps({'rider_finish_repair_day': day, 'provider_failure': str(error)}))
                status = 75
        if finishes != prior:
            finish_dir.mkdir(exist_ok=True)
            finish_packet = dict(schema=RIDER_FINISH_SCHEMA, day=day, published_at=datetime.now(timezone.utc).isoformat(),
                                 races=[finishes[rid] for rid in sorted(finishes)])
            finish_path.write_text(json.dumps(finish_packet, ensure_ascii=False, separators=(',', ':')) + '\n')
            print(json.dumps({'rider_finish_day': day, 'race_count': len(finishes), 'races_added': len(finishes) - len(prior)}))
    if repair_next != repair:
        repair_path.write_text(json.dumps(repair_next, sort_keys=True)+'\n')
    if positions != previous_positions:
        position_file.write_text(json.dumps(positions, sort_keys=True)+'\n')
    return status or (10 if args.stop_when_complete and complete else 0)


if __name__ == '__main__':
    raise SystemExit(main())
