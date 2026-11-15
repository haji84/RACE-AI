"""Preload owner-private venue research before fresh forecast snapshots.

Only explicit pinned configuration enables this path. Failures are raised for
the caller's learning-only rejection path; no baseline, public forecast, owner
decision, or source permission is changed here.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from .boat_pdca_state import state_key
from .boat_venue_dataset import readback_dataset
from .boat_venue_learning import _pin
from .boat_venue_learning_context import context_from_encrypted_artifact
from .github_freeze_receipt import BASE
from .observed_weight_learning import ts
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _read
from scripts.boat_history_collect import private_root


SCHEMA = 'RACE_AI_BOAT_VENUE_LEARNING_CONTEXT_INPUT_V1'
CONFIG_FIELDS = {'schema', 'repository_id', 'artifact_id', 'training_sha256',
                 'head_sha', 'run_id'}
DATASET_FIELDS = {'schema', 'status', 'repository_id', 'source_commit',
                  'dataset_path', 'dataset_sha256'}


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_RESEARCH_RUNTIME_'+reason)


def _json_file(path, reason):
    try:
        return read_json_bytes(_read(Path(path), 8192))
    except (OSError, ValueError) as exc:
        raise ValueError('VENUE_RESEARCH_RUNTIME_'+reason) from exc


def _aware(value):
    _need(type(value) is datetime and value.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return value


def preload_venue_research(context_input, dataset_input, runtime_folder, repo, *, gh, clock=None):
    """Return an authenticated private context and freshly verified venue grid.

    ``gh(path)`` is the existing caller's GitHub reader and returns bytes. Its
    actual metadata response is passed through the encrypted artifact verifier.
    ``runtime_folder`` must be new or empty, owner-private, and outside Git; its
    lifetime belongs to the caller. Invoke before collecting any new P1 input.
    """
    state_key('production')  # Before configuration reads, GitHub, or dataset Git.
    config = _json_file(context_input, 'CONTEXT_INPUT_INVALID')
    _need(type(config) is dict and set(config) == CONFIG_FIELDS and
          config['schema'] == SCHEMA and config['repository_id'] == '1416489937' and
          all(type(config[name]) is int and config[name] > 0 for name in ('artifact_id', 'run_id')) and
          all(type(config[name]) is str and re.fullmatch(pattern, config[name])
              for name, pattern in (('training_sha256', '[a-f0-9]{64}'), ('head_sha', '[a-f0-9]{40}'))),
          'CONTEXT_INPUT_INVALID')
    pointer = _json_file(dataset_input, 'DATASET_INPUT_INVALID')
    _need(type(pointer) is dict and set(pointer) == DATASET_FIELDS, 'DATASET_INPUT_INVALID')
    try:
        _pin(pointer)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('VENUE_RESEARCH_RUNTIME_DATASET_INPUT_INVALID') from exc
    root = private_root(runtime_folder)
    _need(not any(root.iterdir()), 'OUTPUT_EXISTS_DO_NOT_RESET')
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = _aware(clock())
    artifact = 'actions/artifacts/'+str(config['artifact_id'])

    def github(path):
        try:
            return gh(path)
        except Exception as exc:
            raise ValueError('VENUE_RESEARCH_RUNTIME_ARTIFACT_UNAVAILABLE') from exc

    raw = github(artifact+'/zip')

    def metadata(url):
        _need(url == BASE+'/'+artifact, 'METADATA_ROUTE_INVALID')
        return read_json_bytes(github(artifact))

    context = context_from_encrypted_artifact(raw, config['artifact_id'], now=started, _fetch=metadata)
    training = context['training']
    _need(training.get('training_sha256') == config['training_sha256'], 'TRAINING_PIN_MISMATCH')
    _need(training.get('venue_dataset_sha256') == pointer['dataset_sha256'], 'DATASET_PIN_MISMATCH')
    receipt = context['receipt']; run = receipt['workflow_run']
    _need(run.get('id') == config['run_id'] and run.get('head_sha') == config['head_sha'], 'RUN_PIN_MISMATCH')
    dataset = root/'dataset'
    try:
        report = readback_dataset(pointer, dataset, repo)
    except Exception as exc:
        raise ValueError('VENUE_RESEARCH_RUNTIME_DATASET_READBACK_REJECTED') from exc
    _need(type(report) is dict and report.get('status') == 'ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED' and
          report.get('plaintext_published') is False, 'DATASET_READBACK_REQUIRED')
    verified = _aware(clock())
    _need(verified >= started, 'CLOCK_REGRESSED')
    _need(verified < ts(receipt['expires_at']), 'ARTIFACT_EXPIRED_DURING_RESTORE')
    return dict(context=context, dataset_folder=dataset, dataset_pointer=pointer,
                dataset_verified_at=verified.isoformat())
