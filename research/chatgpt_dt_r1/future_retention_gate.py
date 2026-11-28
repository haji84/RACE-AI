"""Validate the existing first-accepted archive against the authenticated producer.

This is a read-only gate for later settlement, not a result or promotion proof.
Video availability is not a condition of this gate.
"""
from hashlib import sha256
import json
from pathlib import Path
import re


# The first real cohort predates the per-slot archive format.
FIRST_DAY = '2026-11-28'
FIRST_PRODUCER = '46082459814'
FIRST_READER = '46083220254'
FIRST_INSERTION = 'a0ea5db4eec5938c2716c5d7950a43df98723f35'
FIRST_ARCHIVE = 'ad17c6edccaa2dc05497fc99c7c653a08fd37cf2'
FIRST_PIN_SHA256 = '093c8d02779a33b46f516d475e3d5549654eadb18c3b62f208c4a865b8cc3c4a'
FIRST_SOURCE_PARENT = '15dd32600fbf5865df3eca340e41377e6f9caa19'



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


def read_legacy_first_retention(work, tip, verified, *, model_sha256):
    """Verify the protected initial batch against its original insertion and archive."""
    from race_ai import keirin_nationwide_cipher_history as archive
    from race_ai import keirin_official_nationwide_records as records

    _need(verified['manifest']['model']['model_sha256'] == model_sha256, 'MODEL_MISMATCH')
    records._check_archive_commit(work, FIRST_ARCHIVE)
    records._check_archive_commit(work, FIRST_SOURCE_PARENT)
    parents = archive._cmd(work, '--no-replace-objects', 'rev-list',
                           '--parents', '-n', '1', FIRST_INSERTION)[1].split()
    _need(parents == [FIRST_INSERTION, FIRST_SOURCE_PARENT] and
          archive._cmd(work, '--no-replace-objects', 'merge-base', '--is-ancestor',
                       FIRST_INSERTION, FIRST_ARCHIVE, okay=True)[0] == 0, 'RETENTION_LINEAGE')
    stem = 'research/chatgpt-dt-r1/future/20261128/' + model_sha256 + '/'
    pin_path = stem + 'first-accepted.json'
    _need(archive.read_blob_bytes(work, FIRST_SOURCE_PARENT, pin_path, max_bytes=200001) is None,
          'FIRST_PIN_ALREADY_EXISTED')

    def read_exact(name):
        path = stem + name
        raw = archive.read_blob_bytes(work, FIRST_ARCHIVE, path, max_bytes=8_000_000)
        current = archive.read_blob_bytes(work, tip, path, max_bytes=8_000_000)
        _need(raw is not None and current == raw, 'RETAINED_BYTES_CHANGED')
        return raw

    pin_raw = read_exact('first-accepted.json')
    _need(archive.read_blob_bytes(work, FIRST_INSERTION, pin_path, max_bytes=200001) == pin_raw,
          'FIRST_INSERTION_PIN_CHANGED')
    pin = json.loads(pin_raw)
    _need(pin.get('retention_parent_commit') == pin.get('source_archive_commit') == FIRST_SOURCE_PARENT,
          'RETENTION_PARENT_MISMATCH')
    return check_first_retention(verified, pin_raw=pin_raw, read_retained=read_exact,
                                 expected_pin_sha256=FIRST_PIN_SHA256)


def legacy_timely_slots(work, tip, day, *, model_sha256, client):
    """Reuse only the independently timed originals from the historical fixed format."""
    if day != FIRST_DAY:
        return set()
    from scripts import keirin_dt_r1_future_readback as reader

    with reader.verified_producer(FIRST_PRODUCER, client=client) as verified:
        read_legacy_first_retention(work, tip, verified, model_sha256=model_sha256)
        origin = reader.verify_readback(verified, FIRST_READER, client=client)
    return set(origin['eligible_slots'])


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
