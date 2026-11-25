"""Preserve the owner's Site JSON in a separate encrypted display capability.

This imports an existing analysis, not a model, a formal forecast receipt or
production state. Its new display key cannot decrypt RACE_AI_STATE_KEY history.
No network, model invocation, source retry, betting or root-key read occurs.
"""
from datetime import datetime, timezone
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import re

SCHEMA = 'RACE_AI_KEIRIN_NOTE_VIEW_V1'
OUTER = 'RACE_AI_SAVED_WEB_VIEW_V1'
SITE = 'https://keirin-20261119-race-note.chankuma.chatgpt.site/'
MAX_FILE = 12 * 1024 * 1024
MAX_VIEW = 64 * 1024 * 1024
BASE_FILES = {'races.json', 'forecasts.json', 'weather.json', 'banks.json',
              'build_metadata.json', 'display_check.json'}
DAY_FILES = {'races.json', 'forecasts.json', 'manifest.json', 'environment.json',
    'reference_AB.json', 'two_car_forecasts.json', 'two_car_manifest.json',
    'two_car_odds.json', 'stake_plans.json', 'flexible_forecasts.json',
    'flexible_stake_plans.json', 'odds_snapshot_flexible.json', 'rollover_routes.json',
    'three_car_rollover_forecasts.json', 'three_car_rollover_routes.json',
    'three_car_rollover_stake_plans.json', 'settlement.json', 'verification.json',
    'research_results.json', 'comparison_inputs.json', 'joint_forecasts.json',
    'comparison_baselines.json', 'comparison_joint_originals.json'}


def need(ok, code):
    if not ok:
        raise ValueError('KEIRIN_NOTE_' + code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _read(path):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE,
         'INPUT_FILE_UNSAFE')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    need(0 < len(raw) <= MAX_FILE, 'INPUT_FILE_BOUND')
    return raw


def import_site(site_root, *, source_commit, clock=None):
    """Retain exact original bytes and distinguish each date/revision/source."""
    root = Path(site_root)
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(), 'SOURCE_ROOT')
    need(type(source_commit) is str and re.fullmatch('[0-9a-f]{40}', source_commit),
         'SOURCE_COMMIT')
    folder = root / 'data'
    need(folder.is_dir() and not folder.is_symlink(), 'SOURCE_DATA_ROOT')
    files, days, size = {}, set(), 0
    paths = [folder / name for name in sorted(BASE_FILES) if (folder / name).exists()]
    for day in sorted(folder.iterdir()):
        if not day.is_dir():
            continue
        need(not day.is_symlink(), 'SOURCE_DIRECTORY_SYMLINK')
        if re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', day.name):
            try:
                datetime.strptime(day.name, '%Y-%m-%d')
            except ValueError:
                need(False, 'DAY_INVALID')
            days.add(day.name)
            paths.extend(day / name for name in sorted(DAY_FILES) if (day / name).exists())
    for path in paths:
        raw = _read(path)
        try:
            text = raw.decode('utf-8', 'strict')
            json.loads(text, object_pairs_hook=_pairs,
                parse_constant=lambda _: need(False, 'NONFINITE_JSON'))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            need(False, 'JSON_INVALID')
        size += len(raw)
        need(size <= MAX_VIEW, 'VIEW_BOUND')
        files[path.relative_to(root).as_posix()] = {
            'sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'text': text}
    need(files and days, 'NO_DATED_SOURCE_DATA')
    observed = (clock or (lambda: datetime.now(timezone.utc)))()
    need(isinstance(observed, datetime) and observed.utcoffset() is not None, 'CLOCK')
    note = dict(schema=SCHEMA, scope='OWNER_IMPORTED_ANALYSIS_AND_REFERENCE',
        source_site=SITE, source_commit=source_commit,
        imported_at=observed.astimezone(timezone.utc).isoformat(),
        dates=sorted(days), files=files, formal_model_admission=False,
        production_weight_switch=False, wagers_placed=False,
        original_files_preserved=True,
        interpretation='Original analysis, flexible revisions, reference A/B and results remain separate.')
    need(len(canonical(note)) <= MAX_VIEW, 'VIEW_BOUND')
    return note


def attach_archive(note, name, raw):
    """Retain compressed originals inside the private envelope, never public."""
    need(type(name) is str and re.fullmatch('[A-Za-z0-9_.-]+\\.(?:tar\\.gz|zip)',name),
         'ARCHIVE_NAME')
    need(type(raw) is bytes and 0 < len(raw) <= MAX_VIEW, 'ARCHIVE_BYTES')
    need(name not in note.get('preserved_archives',{}), 'ARCHIVE_ALREADY_PRESERVED')
    result=dict(note)
    result['preserved_archives']={**note.get('preserved_archives',{}),name:dict(
        bytes=len(raw),sha256=sha256(raw).hexdigest(),base64=base64.b64encode(raw).decode())}
    need(len(canonical(result))<=MAX_VIEW,'VIEW_BOUND')
    return result


def _private_root(path):
    path = Path(path)
    need(path.is_absolute(), 'ABSOLUTE_PRIVATE_PATH_REQUIRED')
    for parent in (path, *path.parents):
        need(not parent.is_symlink(), 'PRIVATE_PATH_SYMLINK')
        need(not (parent / '.git').exists(), 'PRIVATE_KEY_CANNOT_ENTER_CHECKOUT')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(path.is_dir() and not path.stat().st_mode & 0o077, 'PRIVATE_0700_REQUIRED')
    return path


def _create(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def seal_note(note, encrypted_dir, private_dir):
    """Use an independent fresh display key; never inspect a production key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    need(type(note) is dict and note.get('schema') == SCHEMA and
         note.get('formal_model_admission') is False and
         note.get('production_weight_switch') is False, 'NOTE_SCOPE')
    public = _private_root(encrypted_dir)
    private = _private_root(private_dir)
    need(public != private and public not in private.parents and private not in public.parents,
         'SEPARATE_OUTPUTS_REQUIRED')
    need(not (private / 'viewer.json').exists() and not (private / 'owner-url.txt').exists(),
         'EXISTING_OWNER_FILES_PRESERVED')
    plain = canonical(note)
    need(0 < len(plain) <= MAX_VIEW, 'VIEW_BOUND')
    header = dict(schema=OUTER, source_content_sha256=sha256(plain).hexdigest())
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plain, canonical(header))
    body = canonical(dict(header=header, nonce=base64.b64encode(nonce).decode(),
                          ciphertext=base64.b64encode(ciphertext).decode())) + b'\n'
    identity = sha256(body).hexdigest()
    cipher_path = public / (identity + '.json')
    keytext = base64.urlsafe_b64encode(key).decode().rstrip('=')
    viewer = dict(schema='RACE_AI_KEIRIN_NOTE_DISPLAY_CAPABILITY_V1',
                  key=keytext, cipher_sha256=identity,
                  source_content_sha256=header['source_content_sha256'])
    _create(cipher_path, body)
    _create(private / 'viewer.json', canonical(viewer) + b'\n')
    _create(private / 'owner-url.txt',
        ('https://haji84.github.io/RACE-AI/#note=' + identity + '.' + keytext + '\n').encode())
    return dict(cipher_file=str(cipher_path), cipher_sha256=identity,
        source_content_sha256=header['source_content_sha256'],
        private_viewer=str(private / 'viewer.json'), owner_url=str(private / 'owner-url.txt'),
        private_plaintext_uploaded=False, production_state_key_used=False)
