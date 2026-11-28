"""Validate the existing first-accepted archive against the authenticated producer.

This is a read-only gate for later settlement, not a result or promotion proof.
Video availability is not a condition of this gate.
"""
from hashlib import sha256
import json
from pathlib import Path
import re


def _need(ok, code):
    if not ok:
        raise ValueError('DT_R1_FIRST_RETENTION_' + code)


def _hash(raw):
    return sha256(raw).hexdigest()


def check_first_retention(verified, *, pin_raw, read_retained, expected_pin_sha256):
    """Use verified_producer output, not an unauthenticated manifest or self pin."""
    _need(type(pin_raw) is bytes and 0 < len(pin_raw) <= 200000 and
          _hash(pin_raw) == expected_pin_sha256, 'PIN_SHA')
    pin = json.loads(pin_raw)
    manifest = verified['manifest']
    summary = manifest['summary']
    _need(set(pin) == {'schema', 'day_jst', 'model_sha256', 'producer_run_id',
          'manifest_sha256', 'registry', 'source_archive_commit',
          'retention_parent_commit', 'retained_files'} and
          pin['schema'] == 'DT_R1_FUTURE_FIRST_ACCEPTED_V1' and
          pin['day_jst'] == summary['day_jst'] and
          pin['producer_run_id'] == summary['reader_run_id'] == str(verified['producer']['run_id']) and
          pin['model_sha256'] == manifest['model']['model_sha256'] and
          pin['manifest_sha256'] == verified['manifest_sha256'] and
          pin['registry'] == manifest['registry'] and
          pin['source_archive_commit'] == summary['source_archive_commit'] and
          re.fullmatch(r'[0-9a-f]{40}', pin['retention_parent_commit']) is not None, 'PIN_BINDING')
    root = Path(verified['directory'])
    names = {'manifest.json'} | {e['cipher']['file'] for e in manifest['entries'] if e['cipher'] is not None}
    _need(all(n == 'manifest.json' or re.fullmatch(r'[0-9a-f]{64}\.sealed\.json', n) for n in names), 'MEMBER_NAME')
    _need({p.name for p in root.iterdir()} == names and
          len(pin['retained_files']) == len(names), 'INVENTORY')
    expected = []
    for name in sorted(names):
        path = root / name
        _need(path.is_file() and not path.is_symlink(), 'FILE_TYPE')
        raw = path.read_bytes()
        retained = read_retained(name)
        _need(type(retained) is bytes and retained == raw, 'RETAINED_BYTES_MISMATCH')
        expected.append(dict(file=name, bytes=len(raw), sha256=_hash(raw)))
    _need(sorted(pin['retained_files'], key=lambda e: e['file']) == expected and
          _hash((root / 'manifest.json').read_bytes()) == verified['manifest_sha256'], 'FILE_BINDING')
    return dict(pin_sha256=expected_pin_sha256, retained_files_verified=len(expected),
                retained_bytes=sum(e['bytes'] for e in expected), producer_run_id=pin['producer_run_id'],
                manifest_sha256=pin['manifest_sha256'])


def verify_retained_origin(*, producer_run_id, readback_run_id, pin_raw, read_retained,
                           expected_pin_sha256, client=None):
    """Combine byte equality and the existing independently timed server verifier."""
    from scripts.keirin_dt_r1_future_readback import verified_producer, verify_readback
    with verified_producer(producer_run_id, client=client) as verified:
        retention = check_first_retention(verified, pin_raw=pin_raw, read_retained=read_retained,
                                         expected_pin_sha256=expected_pin_sha256)
        origin = verify_readback(verified, readback_run_id, client=client)
    return dict(schema='DT_R1_RETAINED_FUTURE_ORIGIN_V1', retention=retention, server_origin=origin,
                official_result_verified=False, owner_decryption_verified=False,
                formal_three_way_races=0, production_promoted=False)
