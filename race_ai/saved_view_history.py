"""Opt-in, bounded owner history. Pure encryption/routing; no Git or HTTP.

Each month index contains at most 31 dates and an immutable commit/hash locator
for the previous month. A publisher stages encrypted chunks, pins their Git
commit with ``bind_history_locators``, and then publishes the router. Historical
objects remain in Git ancestry; they need not accumulate in the current tree.
V1--V4 publication and acceptance are deliberately unchanged by this module.
"""
import base64
from copy import deepcopy
from datetime import date
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .actions_contract import digest
from .boat_history_store import wire
from .boat_pdca_recipient import _json
from .boat_pdca_state import need, sha
from .saved_pages import _hex
from . import saved_view_feed as F

HISTORY_FEED = 'RACE_AI_SAVED_WEB_HISTORY_V5'
HISTORY_INDEX = 'RACE_AI_SAVED_WEB_HISTORY_INDEX_V1'
HISTORY_CATALOG = 'RACE_AI_SAVED_WEB_HISTORY_CATALOG_V1'
HISTORY_DAY = 'RACE_AI_SAVED_WEB_HISTORY_DAY_V1'
MAX_CHUNK_PLAIN = 8 * 1024 * 1024
MAX_CHUNK_WIRE = 12 * 1024 * 1024
MAX_DAY_PLAIN = 64 * 1024 * 1024
MAX_DAY_RACES = 288
MAX_DAY_FORECASTS = 32768
MAX_DAY_CHUNKS = 64
MAX_INDEX_PLAIN = 512 * 1024
MAX_INDEX_WIRE = 768 * 1024
MAX_CATALOG_HOPS = 1200


def _day(value):
    need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'HISTORY_DAY_INVALID')
    try:
        need(date.fromisoformat(value).isoformat() == value, 'HISTORY_DAY_INVALID')
    except ValueError:
        raise ValueError('HISTORY_DAY_INVALID') from None
    return value


def _locator(value, *, unpinned=False):
    need(type(value) is dict and set(value) == {'commit', 'cipher_sha256'}, 'HISTORY_LOCATOR_INVALID')
    _hex(value['cipher_sha256'])
    need((unpinned and value['commit'] is None) or
         (type(value['commit']) is str and re.fullmatch('[a-f0-9]{40}', value['commit'])), 'HISTORY_COMMIT_REQUIRED')
    return value


def bind_history_locators(value, commit):
    """Return a copy with newly staged ciphertext locators pinned to one commit."""
    need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit), 'HISTORY_COMMIT_REQUIRED')
    if type(value) is list:
        return [bind_history_locators(item, commit) for item in value]
    if type(value) is dict:
        if set(value) == {'commit', 'cipher_sha256'}:
            _locator(value, unpinned=True)
            return dict(value, commit=commit if value['commit'] is None else value['commit'])
        return {key: bind_history_locators(item, commit) for key, item in value.items()}
    return deepcopy(value)


def validate_day_descriptor(value, *, unpinned=False):
    names = {'day', 'chunks', 'races', 'forecasts', 'plain_bytes', 'view_sha256', 'forecast_inventory_sha256'}
    need(type(value) is dict and set(value) == names, 'HISTORY_DAY_DESCRIPTOR_INVALID')
    _day(value['day'])
    need(type(value['races']) is int and 1 <= value['races'] <= MAX_DAY_RACES, 'HISTORY_DAY_RACE_BOUND')
    need(type(value['forecasts']) is int and 0 <= value['forecasts'] <= MAX_DAY_FORECASTS, 'HISTORY_DAY_FORECAST_BOUND')
    need(type(value['plain_bytes']) is int and 0 < value['plain_bytes'] <= MAX_DAY_PLAIN, 'HISTORY_DAY_PLAIN_BOUND')
    _hex(value['view_sha256']); _hex(value['forecast_inventory_sha256'])
    chunks = value['chunks']
    need(type(chunks) is list and 1 <= len(chunks) <= MAX_DAY_CHUNKS, 'HISTORY_DAY_CHUNK_BOUND')
    for locator in chunks:
        _locator(locator, unpinned=unpinned)
    need(len({row['cipher_sha256'] for row in chunks}) == len(chunks), 'HISTORY_DUPLICATE_CHUNK')
    return value


def validate_history(index):
    names = {'schema', 'current_month', 'days', 'previous_catalog', 'forecast_base_sha256'}
    need(type(index) is dict and set(index) == names and index['schema'] == HISTORY_INDEX, 'HISTORY_INDEX_INVALID')
    _hex(index['forecast_base_sha256'])
    month = index['current_month']
    need(type(month) is str and re.fullmatch(r'\d{4}-\d{2}', month), 'HISTORY_MONTH_INVALID')
    _day(month + '-01')
    days = index['days']
    need(type(days) is dict and 1 <= len(days) <= 31, 'HISTORY_MONTH_DAY_BOUND')
    for day, descriptor in days.items():
        _day(day)
        need(day[:7] == month and validate_day_descriptor(descriptor)['day'] == day, 'HISTORY_DATE_ROUTE_MISMATCH')
    if index['previous_catalog'] is not None:
        _locator(index['previous_catalog'])
    need(len(wire(index).encode()) <= MAX_INDEX_PLAIN, 'HISTORY_INDEX_BOUND')
    return index


def build_history(days, *, current_month, forecast_sha256, previous_catalog=None):
    """Build one bounded month index from already pinned day descriptors."""
    return validate_history(dict(schema=HISTORY_INDEX, current_month=current_month,
                                 days=deepcopy(days), previous_catalog=deepcopy(previous_catalog),
                                 forecast_base_sha256=_hex(forecast_sha256)))


def validate_header(header):
    common = {'schema', 'view_id', 'forecast_sha256'}
    need(type(header) is dict, 'HISTORY_HEADER_INVALID')
    schema = header.get('schema')
    if schema == HISTORY_FEED:
        names = common | {'source_content_sha256', 'generation', 'previous_cipher_sha256', 'history_index_sha256'}
        need(type(header.get('generation')) is int and 1 <= header['generation'] <= 999999, 'HISTORY_GENERATION_INVALID')
        for field in ('source_content_sha256', 'previous_cipher_sha256', 'history_index_sha256'):
            _hex(header.get(field))
    elif schema == HISTORY_CATALOG:
        names = common | {'history_index_sha256'}
        _hex(header.get('history_index_sha256'))
    else:
        need(schema == HISTORY_DAY, 'HISTORY_HEADER_INVALID')
        names = common | {'day', 'part', 'forecast_inventory_sha256'}
        _day(header.get('day'))
        need(type(header.get('part')) is int and 0 <= header['part'] < MAX_DAY_CHUNKS, 'HISTORY_PART_INVALID')
        _hex(header.get('forecast_inventory_sha256'))
    need(set(header) == names, 'HISTORY_HEADER_INVALID')
    _hex(header['view_id']); _hex(header['forecast_sha256'])
    return header


def _seal(value, key, header, plain_limit, wire_limit):
    need(type(key) is bytes and len(key) == 32, 'HISTORY_DISPLAY_KEY_REQUIRED')
    validate_header(header)
    plain = wire(value).encode()
    need(0 < len(plain) <= plain_limit, 'HISTORY_PLAIN_BOUND')
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plain, wire(header).encode())
    raw = (wire(dict(header=header, nonce=base64.b64encode(nonce).decode(),
                     ciphertext=base64.b64encode(ciphertext).decode())) + '\n').encode()
    need(len(raw) <= wire_limit, 'HISTORY_CIPHER_BOUND')
    return raw


def _open(raw, key, *, view_id, schema):
    plain_limit, wire_limit = (MAX_CHUNK_PLAIN, MAX_CHUNK_WIRE) if schema == HISTORY_DAY else (MAX_INDEX_PLAIN, MAX_INDEX_WIRE)
    need(type(raw) is bytes and 0 < len(raw) <= wire_limit, 'HISTORY_CIPHER_BOUND')
    doc = _json(raw, wire_limit)
    need(type(doc) is dict and set(doc) == {'header', 'nonce', 'ciphertext'} and
         (wire(doc) + '\n').encode() == raw, 'HISTORY_CIPHER_INVALID')
    header = validate_header(doc['header'])
    need(header['schema'] == schema and header['view_id'] == _hex(view_id), 'HISTORY_VIEW_ID_MISMATCH')
    need(type(key) is bytes and len(key) == 32, 'HISTORY_DISPLAY_KEY_REQUIRED')
    try:
        nonce = base64.b64decode(doc['nonce'], validate=True)
        cipher = base64.b64decode(doc['ciphertext'], validate=True)
        need(len(nonce) == 12 and 16 <= len(cipher) <= plain_limit + 16, 'HISTORY_CIPHER_BOUND')
        need(base64.b64encode(nonce).decode() == doc['nonce'] and base64.b64encode(cipher).decode() == doc['ciphertext'], 'HISTORY_CIPHER_INVALID')
        plain = AESGCM(key).decrypt(nonce, cipher, wire(header).encode())
    except Exception:
        raise ValueError('HISTORY_AUTH_FAILED') from None
    return header, _json(plain, plain_limit), len(plain)


def encrypt_day_chunks(view, key, *, view_id, forecast_sha256=None, chunk_plain_limit=MAX_CHUNK_PLAIN):
    """Return ``{files, days}``; locators remain unpinned until a staging commit.

    Only complete race records are split. All prediction dictionaries and
    separate saved_prediction_evidence are copied without modification. Each
    date is independently capped; adding dates never enlarges a day blob.
    ``chunk_plain_limit`` can lower the production cap for deterministic tests.
    """
    need(type(view) is dict and view.get('schema') == 'RACE_AI_PRIVATE_CYCLE_VIEW_V1' and
         type(view.get('records')) is list and view['records'], 'HISTORY_VIEW_REQUIRED')
    anchor = F.forecast_anchor(view)
    need(forecast_sha256 is None or _hex(forecast_sha256) == anchor, 'HISTORY_ANCHOR_CHANGED')
    need(type(chunk_plain_limit) is int and 0 < chunk_plain_limit <= MAX_CHUNK_PLAIN, 'HISTORY_CHUNK_LIMIT_INVALID')
    days, grouped, files, seen = {}, {}, {}, set()
    for row in view['records']:
        need(type(row) is dict and type(row.get('race_id')) is str and row['race_id'] not in seen, 'HISTORY_DUPLICATE_RACE')
        comparisons = row.get('comparison_predictions', [])
        need(type(comparisons) is list and len(comparisons) + (row.get('prediction') is not None) <= 128, 'HISTORY_PER_RACE_FORECAST_BOUND')
        seen.add(row['race_id'])
        grouped.setdefault(_day(row.get('event_date_jst')), []).append(row)
    for day, records in sorted(grouped.items()):
        need(len(records) <= MAX_DAY_RACES, 'HISTORY_DAY_RACE_BOUND')
        need(sum(len(row.get('comparison_predictions', [])) + (row.get('prediction') is not None) for row in records) <= MAX_DAY_FORECASTS,
             'HISTORY_DAY_FORECAST_BOUND')
        base = deepcopy({key: value for key, value in view.items() if key != 'records'})
        base.update(event_date_jst=day, forecast_base_sha256=anchor)
        full = dict(base, records=deepcopy(sorted(records, key=lambda row: row['race_id'])))
        inventory = F.forecast_inventory(full)
        need(len(inventory) <= MAX_DAY_FORECASTS, 'HISTORY_DAY_FORECAST_BOUND')
        empty_size = len(wire(dict(base, records=[])).encode())
        row_sizes = [len(wire(row).encode()) for row in full['records']]
        need(empty_size + sum(row_sizes) + len(records) - 1 <= MAX_DAY_PLAIN, 'HISTORY_DAY_PLAIN_BOUND')
        batches, batch, batch_size = [], [], empty_size
        for row, row_size in zip(full['records'], row_sizes):
            if batch and batch_size + 1 + row_size > chunk_plain_limit:
                batches.append((batch, batch_size));batch, batch_size = [], empty_size
            batch_size += row_size + (1 if batch else 0)
            batch.append(row)
            need(batch_size <= chunk_plain_limit, 'HISTORY_RACE_CHUNK_BOUND')
        if batch:
            batches.append((batch, batch_size))
        need(len(batches) <= MAX_DAY_CHUNKS, 'HISTORY_DAY_CHUNK_BOUND')
        chunks, plain_bytes = [], 0
        for part, (batch, batch_size) in enumerate(batches):
            chunk = dict(base, records=batch)
            header = dict(schema=HISTORY_DAY, view_id=view_id, forecast_sha256=anchor, day=day,
                          part=part, forecast_inventory_sha256=F.inventory_sha(chunk))
            raw = _seal(chunk, key, header, MAX_CHUNK_PLAIN, MAX_CHUNK_WIRE)
            ident = sha(raw);files['views/' + ident + '.json'] = raw
            chunks.append(dict(commit=None, cipher_sha256=ident));plain_bytes += batch_size
        descriptor = dict(day=day, chunks=chunks, races=len(records), forecasts=len(inventory),
                          plain_bytes=plain_bytes, view_sha256=digest(full), forecast_inventory_sha256=digest(inventory))
        validate_day_descriptor(descriptor, unpinned=True)
        days[day] = descriptor
    return dict(files=files, days=days)


def decrypt_day_chunks(descriptor, read, key, *, view_id, forecast_sha256):
    validate_day_descriptor(descriptor)
    anchor = _hex(forecast_sha256)
    full, metadata, plain_bytes = None, None, 0
    for part, locator in enumerate(descriptor['chunks']):
        try:
            raw = read(locator)
        except Exception:
            raise ValueError('HISTORY_CHUNK_MISSING') from None
        need(type(raw) is bytes and sha(raw) == locator['cipher_sha256'], 'HISTORY_CHUNK_HASH')
        header, chunk, size = _open(raw, key, view_id=view_id, schema=HISTORY_DAY)
        need(header['forecast_sha256'] == anchor and header['day'] == descriptor['day'] and header['part'] == part,
             'HISTORY_CHUNK_ROUTE_MISMATCH')
        need(F.forecast_anchor(chunk) == anchor and F.inventory_sha(chunk) == header['forecast_inventory_sha256'], 'HISTORY_CHUNK_INVENTORY')
        need(all(row.get('event_date_jst') == descriptor['day'] for row in chunk['records']), 'HISTORY_CHUNK_DAY_MISMATCH')
        current_metadata = {name: value for name, value in chunk.items() if name != 'records'}
        if full is None:
            metadata = digest(current_metadata);full = dict(chunk, records=list(chunk['records']))
        else:
            need(digest(current_metadata) == metadata, 'HISTORY_CHUNK_METADATA_MISMATCH')
            full['records'].extend(chunk['records'])
        plain_bytes += size
        need(plain_bytes <= MAX_DAY_PLAIN, 'HISTORY_DAY_PLAIN_BOUND')
    inventory = F.forecast_inventory(full)
    need(len(full['records']) == descriptor['races'] and len(inventory) == descriptor['forecasts'] and
         plain_bytes == descriptor['plain_bytes'] and digest(full) == descriptor['view_sha256'] and
         digest(inventory) == descriptor['forecast_inventory_sha256'], 'HISTORY_DAY_INVENTORY_MISMATCH')
    return full


def encrypt_catalog(history, key, *, view_id):
    validate_history(history)
    header = dict(schema=HISTORY_CATALOG, view_id=view_id, forecast_sha256=history['forecast_base_sha256'], history_index_sha256=digest(history))
    raw = _seal(history, key, header, MAX_INDEX_PLAIN, MAX_INDEX_WIRE)
    ident = sha(raw)
    return dict(files={'views/' + ident + '.json': raw}, locator=dict(commit=None, cipher_sha256=ident))


def decrypt_catalog(raw, key, *, view_id):
    header, history, _ = _open(raw, key, view_id=view_id, schema=HISTORY_CATALOG)
    validate_history(history)
    need(history['forecast_base_sha256'] == header['forecast_sha256'] and digest(history) == header['history_index_sha256'], 'HISTORY_INDEX_MISMATCH')
    return history


def encrypt_history_router(history, key, *, view_id, source_sha, generation, previous):
    validate_history(history)
    header = dict(schema=HISTORY_FEED, view_id=view_id, forecast_sha256=history['forecast_base_sha256'],
                  source_content_sha256=source_sha, generation=generation, previous_cipher_sha256=previous,
                  history_index_sha256=digest(history))
    return _seal(history, key, header, MAX_INDEX_PLAIN, MAX_INDEX_WIRE)


def decrypt_history_router(raw, key, *, view_id):
    header, history, _ = _open(raw, key, view_id=view_id, schema=HISTORY_FEED)
    validate_history(history)
    need(history['forecast_base_sha256'] == header['forecast_sha256'] and digest(history) == header['history_index_sha256'], 'HISTORY_INDEX_MISMATCH')
    return header, history


def _indexes(current, load_catalog, *, stop=None):
    index, seen = validate_history(current), set()
    yield index
    for _ in range(MAX_CATALOG_HOPS):
        locator = index['previous_catalog']
        if locator == stop or locator is None:
            need(locator == stop, 'HISTORY_ARCHIVE_PREFIX_REMOVED')
            return
        marker = (locator['commit'], locator['cipher_sha256'])
        need(marker not in seen, 'HISTORY_CATALOG_CYCLE');seen.add(marker)
        try:
            older = validate_history(load_catalog(locator))
        except Exception:
            raise ValueError('HISTORY_CATALOG_UNAVAILABLE') from None
        need(older['current_month'] < index['current_month'] and older['forecast_base_sha256'] == current['forecast_base_sha256'], 'HISTORY_CATALOG_ROUTE_MISMATCH')
        index = older
        yield index
    raise ValueError('HISTORY_CATALOG_HOP_BOUND')


def _changed_indexes(previous, current, load_catalog):
    """Walk only divergent archive segments, including late result revisions."""
    before, after = previous, current
    old, new = [before], [after]
    seen = [set(), set()]

    def older(index, side):
        locator = index['previous_catalog']
        need(locator is not None, 'HISTORY_ARCHIVE_PREFIX_REMOVED')
        marker = (locator['commit'], locator['cipher_sha256'])
        need(marker not in seen[side] and len(seen[side]) < MAX_CATALOG_HOPS, 'HISTORY_CATALOG_HOP_BOUND')
        seen[side].add(marker)
        try:
            value = validate_history(load_catalog(locator))
        except Exception:
            raise ValueError('HISTORY_CATALOG_UNAVAILABLE') from None
        need(value['current_month'] < index['current_month'] and
             value['forecast_base_sha256'] == current['forecast_base_sha256'], 'HISTORY_CATALOG_ROUTE_MISMATCH')
        return value

    while before['previous_catalog'] != after['previous_catalog']:
        if before['previous_catalog'] is None:
            after = older(after, 1);new.append(after)
        elif after['previous_catalog'] is None:
            raise ValueError('HISTORY_ARCHIVE_PREFIX_REMOVED')
        elif before['current_month'] < after['current_month']:
            after = older(after, 1);new.append(after)
        elif before['current_month'] > after['current_month']:
            before = older(before, 0);old.append(before)
        else:
            before = older(before, 0);old.append(before)
            after = older(after, 1);new.append(after)
    return old, new


def validate_history_transition(previous, current, *, load_day, load_catalog):
    """Prove conservation across a legacy view or a previous bounded router.

    Unchanged archive prefix locators are authenticated commitments. Changed
    date descriptors require independent old/new day inventory comparison.
    ``load_day``/``load_catalog`` are supplied by the existing Git publisher.
    """
    validate_history(current)
    old_index = previous.get('schema') == HISTORY_INDEX
    anchor = previous['forecast_base_sha256'] if old_index else F.forecast_anchor(previous)
    need(anchor == current['forecast_base_sha256'], 'HISTORY_ANCHOR_CHANGED')
    if old_index:
        validate_history(previous)
        need(current['current_month'] >= previous['current_month'], 'HISTORY_MONTH_ROLLBACK')
        old_indexes, indexes = _changed_indexes(previous, current, load_catalog)
        old_days = {day: descriptor for index in old_indexes for day, descriptor in index['days'].items()}
    else:
        old_days = {}
        for row in previous['records']:
            old_days.setdefault(_day(row.get('event_date_jst')), []).append(row)
        indexes = []
        for index in _indexes(current, load_catalog):
            indexes.append(index)
            if all(any(day in item['days'] for item in indexes) for day in old_days):
                break
    for day, old in old_days.items():
        descriptor = next((index['days'][day] for index in indexes if day in index['days']), None)
        need(descriptor is not None, 'HISTORY_OLD_DATE_REMOVED')
        if old_index and descriptor == old:
            continue
        before = load_day(old) if old_index else dict(previous, event_date_jst=day, records=old, forecast_base_sha256=anchor)
        after = load_day(descriptor)
        need(F.forecast_anchor(before) == anchor and F.forecast_anchor(after) == anchor, 'HISTORY_ANCHOR_CHANGED')
        old_inventory, new_inventory = F.forecast_inventory(before), F.forecast_inventory(after)
        need(all(new_inventory.get(ident) == content for ident, content in old_inventory.items()), 'HISTORY_ORIGINAL_REMOVED_OR_CHANGED')
    return True
