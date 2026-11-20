"""Compare official results with retained secondary-summary records, offline.

The older two-source collector retained normalized consensus plus URL, byte-SHA
and observation-time receipts, not the source HTML. These comparisons therefore
mean 保存資料との照合: the stored record's values agree/disagree. They are never
a fresh source reparse, provider authentication, official admission, or a score.
No provider request or state mutation exists in this module.
"""
from copy import deepcopy
from datetime import datetime, date, timezone, timedelta
from hashlib import sha256
import json
import re

from . import keirin_nationwide_cipher_history as archive
from . import keirin_secondary_result_consensus as consensus


ROOT = 'state/keirin/ab/secondary-results/v1'
MAX_RACE_ROWS = 300
MAX_REVISIONS_PER_RACE = 16
MAX_RECORDS = 256
MAX_RECORD_BYTES = 16 * 1024
MAX_TOTAL_BYTES = MAX_RECORDS * MAX_RECORD_BYTES
MAX_TREE_BYTES = 4096
JST = timezone(timedelta(hours=9))
SHA = re.compile('[a-f0-9]{64}')
RID = re.compile('20[0-9]{10}')
PROVIDERS = {'Kdreams', 'netkeirin'}
SECONDARY_IDS = {'kdreams', 'netkeirin'}


class SavedSourceError(ValueError):
    pass


def need(ok):
    if not ok:
        raise SavedSourceError('RETAINED_SOURCE_RECORD_UNVERIFIED')


def _race_id(rid):
    need(type(rid) is str and RID.fullmatch(rid) is not None)
    day = date.fromisoformat(rid[:4] + '-' + rid[4:6] + '-' + rid[6:8])
    need(1 <= int(rid[10:]) <= 12 and rid[8:10] != '00')
    return day.isoformat()


def _aware(value):
    need(type(value) is str and len(value) <= 40)
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(at.utcoffset() is not None)
    return at


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result)
        result[key] = value
    return result


def checked_record(item, race_id, now):
    """Validate exact retained bytes without fabricating missing source HTML."""
    need(type(item) is dict and set(item) == {'sha256', 'raw'} and
         type(item['sha256']) is str and SHA.fullmatch(item['sha256']) is not None and
         type(item['raw']) is bytes and 0 < len(item['raw']) < MAX_RECORD_BYTES and
         sha256(item['raw']).hexdigest() == item['sha256'])
    doc = json.loads(item['raw'], object_pairs_hook=_pairs)
    need(type(doc) is dict and set(doc) == {
        'schema', 'race_id', 'state', 'winning_triple', 'payout_per_100yen',
        'provider_receipts', 'official_primary_result_authenticated',
        'actual_organizer_cutoff_authenticated', 'qualifies_for_formal_settlement'})
    need(doc['schema'] == consensus.SCHEMA and doc['race_id'] == race_id and
         doc['state'] == 'SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL' and
         all(doc[name] is False for name in ('official_primary_result_authenticated',
             'actual_organizer_cutoff_authenticated', 'qualifies_for_formal_settlement')))
    triple = doc['winning_triple']
    need(type(triple) is list and len(triple) == 3 and
         all(type(car) is int and 1 <= car <= 9 for car in triple) and
         len(set(triple)) == 3 and type(doc['payout_per_100yen']) is int and
         100 <= doc['payout_per_100yen'] <= 10**9)
    receipts = doc['provider_receipts']
    need(type(receipts) is list and len(receipts) == 2)
    providers = set(); stamps = []
    day = date.fromisoformat(_race_id(race_id))
    for receipt in receipts:
        need(type(receipt) is dict and set(receipt) == {
            'provider', 'source_url', 'source_bytes_sha256', 'observed_at'})
        provider = receipt['provider']
        need(provider in PROVIDERS and provider not in providers and
             type(receipt['source_bytes_sha256']) is str and
             SHA.fullmatch(receipt['source_bytes_sha256']) is not None)
        consensus.check_race_url(provider=provider, url=receipt['source_url'], race_id=race_id)
        observed = _aware(receipt['observed_at'])
        need(day <= observed.astimezone(JST).date() and observed <= now)
        providers.add(provider); stamps.append(observed)
    need(providers == PROVIDERS)
    return dict(triple='-'.join(map(str, triple)), payout=doc['payout_per_100yen'],
                observed_at=max(stamps))


def read_retained_records(repo, race_ids):
    """Read only requested race directories at one pinned existing Git head.

    An absent directory returns []; an invalid/over-budget one returns None.
    Directory size is checked before listing. At most 16 revisions per race,
    256 blobs per call and less than 4 MiB of record bytes can be read. Older
    history outside the requested race IDs is never scanned.
    """
    need(type(race_ids) is list and len(race_ids) <= MAX_RACE_ROWS and
         len(set(race_ids)) == len(race_ids))
    for rid in race_ids:
        _race_id(rid)
    if not race_ids:
        return {}
    repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(repo)
    result = {}
    read_count = 0
    total_bytes = 0
    for rid in race_ids:
        directory = ROOT + '/' + _race_id(rid) + '/' + rid
        try:
            code, kind = archive._cmd(repo, '--no-replace-objects', 'cat-file', '-t',
                                      head + ':' + directory, okay=True)
            if code != 0:
                result[rid] = []
                continue
            need(kind == 'tree')
            _, length = archive._cmd(repo, '--no-replace-objects', 'cat-file', '-s',
                                     head + ':' + directory)
            need(length.isascii() and length.isdecimal() and
                 0 <= int(length) <= MAX_TREE_BYTES)
            # Inspect the already size-checked tree itself. Recursive expansion
            # would let a small parent conceal an unbounded nested directory.
            _, listing = archive._cmd(repo, '--no-replace-objects', 'ls-tree', '-z',
                head + ':' + directory)
            need(not listing or listing.endswith('\0'))
            entries = listing[:-1].split('\0') if listing else []
            need(len(entries) <= MAX_REVISIONS_PER_RACE)
            saved = []
            for entry in entries:
                match = re.fullmatch(r'100644 blob [a-f0-9]{40}\t([a-f0-9]{64})\.json', entry)
                need(match is not None and read_count < MAX_RECORDS and
                     total_bytes < MAX_TOTAL_BYTES)
                path = directory + '/' + match[1] + '.json'
                limit = min(MAX_RECORD_BYTES, MAX_TOTAL_BYTES - total_bytes + 1)
                # Failed or corrupt reads still consume the bounded attempt
                # count; returned bytes count before content verification.
                read_count += 1
                raw = archive.read_blob_bytes(repo, head, path, max_bytes=limit)
                need(type(raw) is bytes)
                total_bytes += len(raw)
                need(0 < len(raw) < limit and total_bytes <= MAX_TOTAL_BYTES and
                     sha256(raw).hexdigest() == match[1])
                saved.append(dict(sha256=match[1], raw=raw))
            result[rid] = saved
        except Exception:
            # A secondary history failure never changes the official result.
            result[rid] = None
    return result


def retained_source_comparisons(repo, rows, *, clock=None, reader=None):
    """Return replacement comparison lists without modifying admitted rows.

    Only existing official rows are considered. A stored two-source agreement
    supplies corroboration of recorded values; it never supplies an official
    outcome. Monetary comparison is skipped while the official unit is pending.
    """
    need(type(rows) is list and len(rows) <= MAX_RACE_ROWS)
    chosen = {}
    for row in rows:
        need(type(row) is dict)
        if row.get('authority') != 'official':
            continue
        rid = row['race_id']; _race_id(rid)
        need(rid not in chosen and type(row.get('source_comparison')) is list)
        chosen[rid] = row
    if not chosen:
        return {}
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    need(isinstance(now, datetime) and now.utcoffset() is not None)
    try:
        records = (reader or read_retained_records)(repo, list(chosen))
        need(type(records) is dict)
    except Exception:
        records = {}
    result = {}
    for rid, row in chosen.items():
        state = 'unverified'
        items = records.get(rid)
        try:
            need(type(items) is list and len(items) <= MAX_REVISIONS_PER_RACE)
            if not items:
                state = 'unavailable'
            elif row.get('order_status') == 'confirmed':
                parsed = [checked_record(item, rid, now) for item in items]
                latest = max(item['observed_at'] for item in parsed)
                values = {(item['triple'], item['payout']) for item in parsed
                          if item['observed_at'] == latest}
                need(len(values) == 1)
                triple, payout = values.pop()
                matches = triple in row['winning_triples']
                if row.get('payout_status') == 'confirmed':
                    matches = matches and row['payouts_100yen'].get(triple) == payout
                state = 'matched' if matches else 'different'
        except Exception:
            state = 'unverified'
        existing = [deepcopy(item) for item in row['source_comparison']
                    if item.get('source_id') not in SECONDARY_IDS]
        result[rid] = existing + [dict(source_id=source, state=state)
                                 for source in ('kdreams', 'netkeirin')]
    return result
