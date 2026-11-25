"""Owner display contract for a scored, independently retained Mac shadow."""

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from .keirin_note_view import SCHEMA as NOTE_SCHEMA, _pairs


KIND = 'shadow-verification'
SCHEMA = 'RACE_AI_KEIRIN_SHADOW_VERIFICATION_V1'
SCOPE = 'OWNER_MAC_SHADOW_VERIFICATION'
RESULT_SCOPES = {'TWO_SOURCE_MATCHED_PODIUM_ONLY', 'OFFICIAL_COMPLETE_FINISH_RESEARCH'}
JST = timezone(timedelta(hours=9))
HASH = re.compile('[0-9a-f]{64}')
CLOCK = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                   r'(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])')
MAX_BYTES = 8192
SEALED_PLAINTEXT_BYTES = 2048


def _need(valid):
    if not valid:
        raise ValueError('KEIRIN_SHADOW_VERIFICATION_INVALID')


def _time(value):
    _need(type(value) is str and CLOCK.fullmatch(value))
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('KEIRIN_SHADOW_VERIFICATION_INVALID') from None


def _fields(value, names):
    _need(type(value) is dict and set(value) == names)


def checked_record(record, day):
    """Bind the named race, clocks, two evidence identities and fixed budgets."""
    _fields(record, {'schema', 'day_jst', 'race_id', 'verified_at', 'start_at', 'original',
                     'result', 'scores', 'tracking_learning', 'production_weights_promoted'})
    _need(type(day) is str and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', day))
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError('KEIRIN_SHADOW_VERIFICATION_INVALID') from None
    _need(record['schema'] == SCHEMA and record['day_jst'] == day and
          type(record['race_id']) is str and re.fullmatch(
              day.replace('-', '') + r'[0-9]{2}(?:0[1-9]|1[0-2])', record['race_id']) and
          record['tracking_learning'] == 'HELD' and record['production_weights_promoted'] is False)
    original, result = record['original'], record['result']
    _fields(original, {'sha256', 'archive_cipher_sha256', 'generated_at', 'cutoff_at'})
    _fields(result, {'evidence_sha256', 'observed_at', 'scope'})
    hashes = (original['sha256'], original['archive_cipher_sha256'], result['evidence_sha256'])
    _need(all(type(value) is str and HASH.fullmatch(value) and value != '0' * 64 for value in hashes)
          and len(set(hashes)) == len(hashes)
          and type(result['scope']) is str and result['scope'] in RESULT_SCOPES)
    generated, cutoff = _time(original['generated_at']), _time(original['cutoff_at'])
    start, observed, verified = map(_time, (record['start_at'], result['observed_at'], record['verified_at']))
    _need(start.astimezone(JST).date().isoformat() == cutoff.astimezone(JST).date().isoformat() == day
          and generated < cutoff < start <= observed <= verified)

    scores = record['scores']
    _fields(scores, {'trifecta', 'exacta'})
    for market, points in (('trifecta', 4), ('exacta', 2)):
        score = scores[market]
        _fields(score, {'points', 'saved_hit', 'challenger_hit'})
        _need(type(score['points']) is int and score['points'] == points and
              type(score['saved_hit']) is bool and type(score['challenger_hit']) is bool)
    return record


def checked_archive_binding(record, archive_entry, published_at):
    """Verify the earlier same-day archive commitment without opening its body."""
    checked_record(record, record.get('day_jst') if type(record) is dict else None)
    original = record['original']
    _need(type(archive_entry) is dict and archive_entry.get('kind') == 'archive' and
          archive_entry.get('days') == [record['day_jst']] and
          archive_entry.get('captured_race_ids') == archive_entry.get('priority_window_race_ids') == [] and
          archive_entry.get('cipher_sha256') == original['archive_cipher_sha256'])
    created = _time(archive_entry.get('created_at'))
    _need(_time(original['generated_at']) <= created < _time(original['cutoff_at'])
          and _time(record['verified_at']) <= _time(published_at))
    return record


def checked_note(note):
    """Validate the sole attachment and exclude source bytes or other packet content."""
    _fields(note, {'schema', 'scope', 'source_site', 'source_commit', 'imported_at', 'dates', 'files',
                   'formal_model_admission', 'production_weight_switch', 'wagers_placed'})
    _need(note['schema'] == NOTE_SCHEMA and note['scope'] == SCOPE and note['source_site'] is None and
          type(note['source_commit']) is str and re.fullmatch('[0-9a-f]{40}', note['source_commit']) and
          type(note['dates']) is list and len(note['dates']) == 1 and type(note['dates'][0]) is str and
          all(note[key] is False for key in ('formal_model_admission', 'production_weight_switch', 'wagers_placed')))
    day, = note['dates']
    path = f'data/{day}/shadow_verification.json'
    _fields(note['files'], {path})
    entry = note['files'][path]
    _fields(entry, {'text', 'bytes', 'sha256'})
    _need(type(entry['text']) is str and len(entry['text']) <= MAX_BYTES)
    raw = entry['text'].encode('utf-8')
    _need(type(entry['bytes']) is int and 0 < len(raw) == entry['bytes'] <= MAX_BYTES and
          sha256(raw).hexdigest() == entry['sha256'])
    record = checked_record(json.loads(raw, object_pairs_hook=_pairs), day)
    imported = _time(note['imported_at'])
    _need(_time(record['verified_at']) <= imported)
    return record, imported
