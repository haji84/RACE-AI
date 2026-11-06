"""Owner-private learning artifacts -> the existing shadow inference contract.

Actual GitHub artifact metadata authenticates the archive and its save clock.
Owner-key authentication neither grants source rights nor independently
witnesses the subsequently generated forecast. No legacy public forecast
artifact is read or written here.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import io
from pathlib import Path
import re
import stat
import tempfile
import time
import zipfile

from .boat_pdca_state import state_key
from .boat_venue_learning import read_candidate, seal_candidate
from .github_freeze_receipt import BASE, _github_json
from .observed_weight_learning import make_shadows, ts, verify_training
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write


MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MEMBER_LIMITS = {'learning.enc': 12 * 1024 * 1024,
                 'learning.json': 1024 * 1024, 'summary.json': 1024 * 1024}
REPOSITORY_ID = 1416489937


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_LEARNING_CONTEXT_' + reason)


def _clock(now):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return now


def _timestamp(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'TIMESTAMP_REQUIRED')
    try:
        return ts(value)
    except ValueError as exc:
        raise ValueError('VENUE_LEARNING_CONTEXT_TIMESTAMP_INVALID') from exc


def _candidate_from_zip(raw):
    """Bound every member before decompressing; never extract a ZIP path."""
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ZIP_SIZE_INVALID')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            _need(len(entries) == 3 and {i.filename for i in entries} == set(MEMBER_LIMITS),
                  'ZIP_MEMBERS_INVALID')
            for entry in entries:
                kind = stat.S_IFMT(entry.external_attr >> 16)
                _need(0 < entry.file_size <= MEMBER_LIMITS[entry.filename] and
                      not entry.flag_bits & 1 and kind in (0, stat.S_IFREG) and
                      entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                      'ZIP_MEMBER_INVALID')
            with tempfile.TemporaryDirectory(prefix='boat-venue-learning-context-') as temporary:
                root = Path(temporary)
                for entry in entries:
                    _write(root/entry.filename, archive.read(entry))
                # Decrypt before the first HTTP request: a well-formed but wrong
                # owner key cannot consume an external metadata request either.
                payload = read_candidate(root)
                public = read_json_bytes((root/'summary.json').read_bytes())
                _need(type(payload) is dict and type(payload.get('summary')) is dict and
                      public == dict(payload['summary'], encrypted_readback_verified=True,
                                     plaintext_published=False), 'SUMMARY_BINDING_INVALID')
                return payload
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, KeyError, TypeError) as exc:
        raise ValueError('VENUE_LEARNING_CONTEXT_ARCHIVE_REJECTED') from exc


def context_from_encrypted_artifact(raw_zip, artifact_id, *, now, _fetch=None):
    """Verify a private candidate against metadata fetched from its actual ID.

    The caller supplies ZIP bytes, never a purported receipt. Decrypted
    parameters stay in memory and temporary private storage outside Git.
    """
    state_key('production')
    now = _clock(now)
    _need(type(artifact_id) is int and artifact_id > 0, 'ARTIFACT_ID_INVALID')
    payload = _candidate_from_zip(raw_zip)
    training = payload.get('training')
    _need(type(training) is dict, 'FITTED_TRAINING_REQUIRED')
    verify_training(training)
    # Both the legacy complete pair and a verified registry fitted subset use
    # this clock boundary. A roster of missing members is never a live context.
    _need(training.get('state') == 'FITTED_SHADOW_ONLY' and
          type(training.get('models')) is dict and bool(training['models']),
          'FITTED_TRAINING_REQUIRED')
    created = _timestamp(training.get('created_at'))
    available = _timestamp(training.get('data_available_until'))
    _need(available <= created <= now, 'TRAINING_CLOCK_INVALID')
    receipt = (_fetch or _github_json)(BASE+'/actions/artifacts/'+str(artifact_id))
    _need(type(receipt) is dict and type(receipt.get('id')) is int and
          receipt['id'] == artifact_id and receipt.get('expired') is False,
          'ARTIFACT_IDENTITY_INVALID')
    name = receipt.get('name')
    registry_candidate = training.get('schema') == 'RACE_AI_ALL_EXISTING_MODEL_FIT_V1'
    prefixes = ('boat-venue-learning-', 'all-existing-model-learning-') if registry_candidate else ('boat-venue-learning-',)
    _need(type(name) is str and 0 < len(name) <= 200 and
          any(name.startswith(prefix) and len(name) > len(prefix) for prefix in prefixes),
          'ARTIFACT_NAME_INVALID')
    run = receipt.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] > 0 and
          type(run.get('repository_id')) is int and run['repository_id'] == REPOSITORY_ID and
          type(run.get('head_repository_id')) is int and run['head_repository_id'] == REPOSITORY_ID,
          'ARTIFACT_REPOSITORY_INVALID')
    if registry_candidate:
        _need(type(run.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}', run['head_sha']),
              'ARTIFACT_HEAD_INVALID')
    _need(type(receipt.get('size_in_bytes')) is int and
          receipt['size_in_bytes'] == len(raw_zip) and
          receipt.get('digest') == 'sha256:'+hashlib.sha256(raw_zip).hexdigest(),
          'ARTIFACT_BYTES_INVALID')
    saved = _timestamp(receipt.get('created_at'))
    expires = _timestamp(receipt.get('expires_at'))
    # GitHub reports whole seconds while training retains microseconds. Match
    # the shadow reader's one-second precision window, excluding a full second
    # of reversal and retaining strict current-time and expiry boundaries.
    _need(created < saved+timedelta(seconds=1) and saved <= now < expires,
          'ARTIFACT_CLOCK_INVALID')
    return dict(training=deepcopy(training), receipt=deepcopy(receipt))


def make_encrypted_shadows(snapshot, baseline_suite, context, output, *, now):
    """Seal future research forecasts; only an external witness can admit them.

    ``now`` is the trusted caller's aware start time. Monotonic elapsed time
    includes inference, encryption and readback so a slow seal cannot silently
    cross the sales cutoff. On late completion ciphertext is retained locally,
    the operation fails, and its summary still asserts no external proof.
    """
    started = time.monotonic()
    state_key('production')
    now = _clock(now); cutoff = ts(snapshot['sales_cutoff_at'])
    _need(ts(snapshot['as_of']) <= now < cutoff, 'PHYSICAL_CUTOFF_REQUIRED')
    shadows = make_shadows(snapshot, baseline_suite, context)
    _need(bool(shadows), 'FITTED_SHADOWS_REQUIRED')
    summary = dict(schema='RACE_AI_ENCRYPTED_VENUE_SHADOW_COUNTS_V1',
                   state='ENCRYPTED_SHADOWS_LOCAL_ONLY', learned_shadow_count=len(shadows),
                   training_sha256=context['training']['training_sha256'],
                   independent_pre_cutoff_receipt_verified=False,
                   provider_rights_confirmed=False, production_promoted=False,
                   baseline_coefficients_changed=False, actual_purchases=False,
                   plaintext_published=False)
    payload = dict(summary=summary, training=deepcopy(context['training']), excluded=[], shadows=shadows)
    result = seal_candidate(payload, output)
    elapsed = time.monotonic()-started
    _need(elapsed >= 0 and now+timedelta(seconds=elapsed) < cutoff,
          'CUTOFF_ELAPSED_DURING_SEAL')
    return result
