"""Summarize validated past keirin video checkpoints. This module only accepts review inputs.

Digests must come from independently verified review, identity and result receipts.
A matching digest binds the supplied bytes. It does not authenticate an operator's
original source on its own.
"""
import argparse
from collections import Counter
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit

from race_ai.keirin_secondary_result_consensus import check_race_url
from scripts.keirin_rider_profile_history import is_registration


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def checked_json(path, digest):
    raw = Path(path).read_bytes()
    require(is_digest(digest) and sha256(raw).hexdigest() == digest, 'Input digest mismatch.')
    return json.loads(raw)


def indexed(rows, *, dashed=False):
    result = {}
    for row in rows:
        key = row['race_id']
        pattern = r'[0-9]{8}-[0-9]{2}-[0-9]{2}' if dashed else r'[0-9]{12}'
        require(isinstance(key, str) and re.fullmatch(pattern, key), 'Invalid race ID.')
        key = key.replace('-', '')
        date.fromisoformat(key[:8])
        require(key not in result, 'Duplicate race ID.')
        result[key] = row
    return result


def trio(value):
    return (isinstance(value, list) and len(value) == 3 and
            all(type(car) is int and 1 <= car <= 9 for car in value) and len(set(value)) == 3)


def instant(value):
    time = datetime.fromisoformat(value)
    require(time.utcoffset() is not None, 'Observation needs a timezone.')
    return time


def review_url(value, race_id):
    url = urlsplit(value)
    if url.path.startswith('/yenjoy/'):
        match = re.fullmatch(r'/yenjoy/keirin-kaisai/race-card/result/([0-9]{10})/([0-9]{14})/([0-9]{1,2})/',
                             url.path)
        require(url.scheme == 'https' and url.netloc == 'keirin.kdreams.jp'
                and not url.query and not url.fragment and match, 'Invalid review page.')
        day, meeting, number = match.groups()
        require(day == meeting[:10] and int(number) == int(race_id[-2:]),
                'Review page does not describe this race.')
        check_race_url(provider='Kdreams',
                       url=f'https://keirin.kdreams.jp/review/racedetail/{meeting}{int(number):02d}/',
                       race_id=race_id)
        return
    cleaned = urlunsplit(url._replace(query=''))
    require(url.query in ('', 'pageType=result', 'pageType=showResult'), 'Invalid review page variant.')
    check_race_url(provider='Kdreams', url=cleaned, race_id=race_id)


def checked_registration(order, registration, known):
    require(isinstance(registration, list) and len(registration) == 3, 'Missing rider registrations.')
    for car, rider in zip(order, registration, strict=True):
        require(isinstance(rider, str) and is_registration(rider) and rider != '000000',
                'Invalid rider registration.')
        require(known.setdefault(car, rider) == rider, 'Car number resolves to different riders.')
    require(len(set(known.values())) == len(known), 'Duplicate rider registration.')


def matches_checkpoint(witness, phase, pair, elapsed):
    checkpoint_times = (point.get('seconds_in_digest') for point in witness['checkpoints']
                        if point['phase'] == phase and [point['first_car'], point['second_car']] == pair)
    return any(type(t) in (int, float) and abs(elapsed - t) <= .5 for t in checkpoint_times)


def for_history(reviews, bound_outcomes, settlements, *, before, available_before=None,
                review_frozen_at=None, back=(), witnesses=()):
    """Return confirmed transitions for race days preceding the boundary.

    Supply available_before for chronological training. Otherwise, earlier race
    days can use labels recovered later for retrospective analysis.
    """
    boundary = date.fromisoformat(before)
    available = instant(available_before) if available_before is not None else None
    reviewed = indexed(reviews)
    bound = indexed(bound_outcomes)
    backs = indexed(back)
    witness = indexed(witnesses, dashed=True)
    require(bound.keys() <= reviewed.keys() and backs.keys() <= reviewed.keys(), 'Unreviewed race.')
    rows, status = [], Counter()
    for race_id, review in sorted(reviewed.items()):
        if date.fromisoformat(race_id[:8]) >= boundary:
            status['at_or_after_boundary'] += 1
            continue
        require(review['phase'] == '4C_nearby_visual_sample', 'Unexpected checkpoint.')
        if review['ambiguity'] is True or review['ordered_4C'][-1:] == [None]:
            status['ambiguous_corner'] += 1
            continue
        corner = review['ordered_4C']
        require(review['ambiguity'] is False and trio(corner), 'Malformed corner trio.')
        elapsed = review['time_from_digest_start_seconds']
        require(type(elapsed) in (float, int) and isfinite(elapsed) and elapsed > 0,
                'Invalid checkpoint time.')
        frame = review['observation_frame_sha256']
        proof = review['capture_receipt_sha256']
        visual = review['visual_sha256']
        require(isinstance(visual, list) and all(map(is_digest, visual))
                and is_digest(frame) and is_digest(proof) and frame in visual,
                'Missing or mismatched visual evidence.')
        review_url(review['source_url'], race_id)
        program = witness.get(race_id)
        if witness:
            require(program and matches_checkpoint(program, 'corner', corner[:2], elapsed),
                    'Corner frame does not match checkpoint time or first two cars.')
        joined, result = bound.get(race_id), settlements.get(race_id)
        if not joined or not result or result['state'] != 'SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL':
            status['no_matched_outcome'] += 1
            continue
        goal = joined['ordered_goal']
        require(trio(goal) and result['race_id'] == race_id and goal == result['winning_triple'],
                'Settled order mismatch.')
        require(all(joined[key] == review[key] for key in ('ordered_4C', 'source_url',
                'time_from_digest_start_seconds', 'observation_frame_sha256', 'capture_receipt_sha256')),
                'Bound transition does not match visual review.')
        sources = result['provider_receipts']
        require(sources == joined['provider_receipts'] and len(sources) == 2
                and {source['provider'] for source in sources} == {'Kdreams', 'netkeirin'},
                'Expected two distinct matching result sources.')
        for source in sources:
            require(is_digest(source['source_bytes_sha256']), 'Missing source digest.')
            seen = instant(source['observed_at'])
            require(seen.astimezone(ZoneInfo('Asia/Tokyo')).date() >= date.fromisoformat(race_id[:8]), 'Result source predates race.')
            check_race_url(provider=source['provider'], url=source['source_url'], race_id=race_id)
        if available is not None:
            stamped = joined.get('labelled_at_4C')
            recorded = review_frozen_at or (stamped if isinstance(stamped, str) else None)
            if (not recorded or instant(recorded) >= available or
                    any(instant(source['observed_at']) >= available for source in sources)):
                status['not_available_before'] += 1
                continue
        known = {}
        checked_registration(corner, joined['ordered_4C_registration'], known)
        checked_registration(goal, joined['ordered_goal_registration'], known)
        row = dict(race_id=race_id, corner=tuple(corner), goal=tuple(goal))
        if race_id in backs:
            b = backs[race_id]
            require(program and trio(b['order']) and program['published_B_car'] == b['order'][0]
                    and [program['B_car'], program['B_second']] == b['order'][:2],
                    'Back observation does not match race witness.')
            require(is_digest(b['sha256']) and is_digest(b['proof']) and
                    type(b['seconds']) in (float, int) and isfinite(b['seconds']) and
                    0 < b['seconds'] < elapsed, 'Missing evidence or invalid back-to-corner time.')
            require(matches_checkpoint(program, 'back', b['order'][:2], b['seconds']),
                    'Back frame does not match checkpoint time.')
            seen_back = instant(b['obs_at_utc'])
            review_url(b['source'], race_id)
            back_labelled = b.get('labelled_at')
            available_back = (isinstance(back_labelled, str) and
                              max(seen_back, instant(back_labelled)) < available) if available is not None else True
            if available_back:
                row['back'] = tuple(b['order'])
            else:
                status['back_not_available_before'] += 1
        rows.append(row)
    return rows, dict(status)


def summarize(rows):
    counts = Counter()
    for row in rows:
        c, g = row['corner'], row['goal']
        counts['observed'] += 1
        counts['same_corner_goal_order'] += c == g
        counts['same_corner_goal_trio'] += set(c) == set(g)
        counts['corner_third_at_goal_third'] += c[2] == g[2]
        counts['corner_third_in_goal_trio'] += c[2] in g
        counts['same_ordered_corner_goal_pair'] += c[:2] == g[:2]
        counts['same_corner_goal_pair'] += set(c[:2]) == set(g[:2])
        counts['same_corner_goal_pair_and_third'] += set(c[:2]) == set(g[:2]) and c[2] == g[2]
        if 'back' in row:
            b = row['back']
            counts['both_checkpoints'] += 1
            counts['same_back_corner_order'] += b == c
            counts['same_back_corner_trio'] += set(b) == set(c)
            counts['same_ordered_back_corner_pair'] += b[:2] == c[:2]
            counts['same_ordered_back_corner_pair_changed_third'] += b[:2] == c[:2] and b[2] != c[2]
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('review', 'bound-outcomes', 'settlements'):
        parser.add_argument('--' + name, required=True, nargs=2, metavar=('PATH', 'SHA256'))
    for name in ('back', 'witnesses'):
        parser.add_argument('--' + name, nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--before', required=True, help='Exclusive Japanese race day YYYY-MM-DD.')
    parser.add_argument('--review-freeze', nargs=2, metavar=('PATH', 'SHA256'),
                        help='Immutable digest and original freeze time for the supplied review file.')
    parser.add_argument('--available-before', help='Exclusive availability time with timezone for past training.')
    args = parser.parse_args()
    if bool(args.back) != bool(args.witnesses):
        parser.error('Supply --back and --witnesses together.')
    try:
        back = checked_json(*args.back) if args.back else ()
        witness = checked_json(*args.witnesses)['races'] if args.witnesses else ()
        frozen = None
        if args.review_freeze:
            receipt = checked_json(*args.review_freeze)
            require(receipt['label_sha256'] == args.review[1], 'Freeze receipt does not bind review file.')
            frozen = receipt['frozen_at']
        rows, states = for_history(checked_json(*args.review), checked_json(*args.bound_outcomes),
                                   checked_json(*args.settlements), before=args.before,
                                   available_before=args.available_before, review_frozen_at=frozen, back=back, witnesses=witness)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Checkpoint study failed: {exc}\n')
    report = {'exclusive_race_day': args.before, 'scope': 'historical_video_observations',
              'counts': summarize(rows), 'excluded': states}
    if args.available_before is not None:
        report['exclusive_availability'] = args.available_before
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
