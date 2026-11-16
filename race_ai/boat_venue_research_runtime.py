"""Preload owner-private venue research before fresh forecast snapshots.

Only explicit pinned configuration enables this path. Failures are raised for
the caller's learning-only rejection path; no baseline, public forecast, owner
decision, or source permission is changed here.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile

from .boat_pdca_state import state_key
from .boat_venue_dataset import readback_dataset
from .boat_venue_learning import _pin
from .boat_venue_learning_context import context_from_encrypted_artifact
from .boat_venue_learning import read_candidate
from .boat_venue_learning_handoff import FILES, restore_learning_candidate
from .actions_contract import digest
from .github_freeze_receipt import BASE
from .observed_weight_learning import ts
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _read, _write
from scripts.boat_history_collect import private_root


SCHEMA = 'RACE_AI_BOAT_VENUE_LEARNING_CONTEXT_INPUT_V1'
CONFIG_FIELDS = {'schema', 'repository_id', 'artifact_id', 'training_sha256',
                 'head_sha', 'run_id'}
DATASET_FIELDS = {'schema', 'status', 'repository_id', 'source_commit',
                  'dataset_path', 'dataset_sha256'}
RECOVERY_TRAINING_SHA = '42117035d5e2ac4977308a2276e835a4d79daa14600fd3ee23c10944c0571c03'
RETAINED_POINTER = dict(schema='RACE_AI_BOAT_VENUE_LEARNING_INPUT_V1', status='READY',
    repository_id='1416489937', source_commit='1e839500361dd132efa4dc4b334a741a43835959',
    manifest_path='state/boat-venue-history/v1/learning/'
        '874e1e5aeb33455bf9a858b51261d26f440c32e88a35d3cf0429b1c7e675d006/learning.json',
    manifest_sha256='874e1e5aeb33455bf9a858b51261d26f440c32e88a35d3cf0429b1c7e675d006',
    training_sha256=RECOVERY_TRAINING_SHA)
RESTORE_DIRECTORY = 'boat-venue-candidate-restore'
RESTORE_SCHEMA = 'RACE_AI_SAME_VENUE_CANDIDATE_RESTORE_V1'
READY_SCHEMA = 'RACE_AI_SAME_VENUE_CANDIDATE_READY_V1'
DOMAIN = b'RACE_AI_PRIVATE_SAME_CANDIDATE_RUNTIME_V1\0'


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


def _context_config(path):
    config = _json_file(path, 'CONTEXT_INPUT_INVALID')
    _need(type(config) is dict and set(config) == CONFIG_FIELDS and
          config['schema'] == SCHEMA and config['repository_id'] == '1416489937' and
          all(type(config[name]) is int and config[name] > 0 for name in ('artifact_id', 'run_id')) and
          all(type(config[name]) is str and re.fullmatch(pattern, config[name])
              for name, pattern in (('training_sha256', '[a-f0-9]{64}'), ('head_sha', '[a-f0-9]{40}'))),
          'CONTEXT_INPUT_INVALID')
    return config


def _identity(env):
    _need(env.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI' and
          all(type(env.get(k)) is str and re.fullmatch('[1-9][0-9]{0,19}', env[k])
              for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')) and
          type(env.get('GITHUB_SHA')) is str and re.fullmatch('[a-f0-9]{40}', env['GITHUB_SHA']),
          'CURRENT_OWNER_IDENTITY_REQUIRED')
    return dict(run_id=int(env['GITHUB_RUN_ID']), attempt=int(env['GITHUB_RUN_ATTEMPT']), head_sha=env['GITHUB_SHA'])


def _recovery_inputs(context_input, retained_input):
    config = _context_config(context_input)
    _need(config['training_sha256'] == RECOVERY_TRAINING_SHA, 'INTENDED_CANDIDATE_REQUIRED')
    pointer = _json_file(retained_input, 'RETAINED_PIN_INVALID')
    _need(pointer == RETAINED_POINTER and pointer['training_sha256'] == config['training_sha256'],
          'RETAINED_PIN_MISMATCH')
    return config, pointer, hashlib.sha256(_read(Path(context_input), 8192)).hexdigest()


def _private_file(path):
    path = Path(path)
    _need(not any(p.is_symlink() for p in (path, *path.absolute().parents)), 'PRIVATE_PATH_REQUIRED')
    item = path.lstat()
    _need(stat.S_ISREG(item.st_mode) and stat.S_IMODE(item.st_mode) == 0o600 and item.st_uid == os.getuid(),
          'PRIVATE_FILE_REQUIRED')
    return path


def _private_folder(path):
    path = Path(path)
    _need('..' not in path.parts and
          not any(p.is_symlink() for p in (path.absolute(), *path.absolute().parents)), 'PRIVATE_PATH_REQUIRED')
    return private_root(path)


def _mac(document):
    return hmac.new(state_key('production'), DOMAIN+digest(document).encode(), hashlib.sha256).hexdigest()


def _save_signed(path, document):
    _write(path, (json.dumps(dict(state=document, mac=_mac(document)), sort_keys=True, separators=(',', ':'))+'\n').encode())


def _signed(path):
    value = read_json_bytes(_read(_private_file(path), 32768))
    _need(type(value) is dict and set(value) == {'state', 'mac'} and type(value['mac']) is str and
          hmac.compare_digest(value['mac'], _mac(value['state'])), 'PRIVATE_READY_AUTHENTICATION_FAILED')
    return value['state']


def _file_hashes(folder):
    folder = _private_folder(folder)
    _need({p.name for p in folder.iterdir()} == set(FILES), 'RESTORED_BYTES_MISMATCH')
    return {name:hashlib.sha256(_read(_private_file(folder/name), limit)).hexdigest() for name,limit in FILES.items()}


def restore_learning_context(context_input, retained_input, output, repo, *, env, now, transport=None):
    """Restore only the pinned existing candidate; never fit or issue a receipt."""
    state_key('production')
    identity = _identity(env); now = _aware(now)
    config, pointer, original_sha = _recovery_inputs(context_input, retained_input)
    output = Path(output)
    _need(not output.exists() or output.is_dir() and not any(output.iterdir()), 'OUTPUT_EXISTS_DO_NOT_RESET')
    root = _private_folder(output)
    restore_learning_candidate(pointer, root/'candidate', repo, transport=transport)
    training = read_candidate(root/'candidate')['training']
    _need(training['training_sha256'] == config['training_sha256'] and ts(training['created_at']) <= now,
          'INTENDED_CANDIDATE_REQUIRED')
    document = dict(schema=RESTORE_SCHEMA, identity=identity, retained_pointer=pointer,
                    original_config_sha256=original_sha, training_sha256=config['training_sha256'],
                    restore_started_at=now.isoformat(), files_sha256=_file_hashes(root/'candidate'))
    _save_signed(root/'restoration.json', document)
    return dict(state='SAME_CANDIDATE_RESTORED_PRIVATE_ONLY', training_sha256=config['training_sha256'],
                encrypted_readback_verified=True, external_receipt_verified=False,
                production_promoted=False, plaintext_published=False)


def readback_learning_context(context_input, retained_input, output, artifact_id, repo, *, env, gh, clock=None):
    """Independently download new server bytes before signing a private override."""
    state_key('production')
    identity = _identity(env)
    config, pointer, original_sha = _recovery_inputs(context_input, retained_input)
    root = _private_folder(output)
    original = _signed(root/'restoration.json')
    _need(original.get('schema') == RESTORE_SCHEMA and original.get('identity') == identity and
          original.get('retained_pointer') == pointer and original.get('original_config_sha256') == original_sha and
          original.get('training_sha256') == config['training_sha256'], 'RESTORED_BINDING_MISMATCH')
    _need(_file_hashes(root/'candidate') == original['files_sha256'], 'RESTORED_BYTES_MISMATCH')
    _need(type(artifact_id) is int and artifact_id > 0 and artifact_id != config['artifact_id'], 'NEW_ARTIFACT_REQUIRED')
    clock = clock or (lambda:datetime.now(timezone.utc))
    started = _aware(clock())
    _need(ts(original['restore_started_at']) <= started, 'RESTORE_CLOCK_INVALID')
    route = 'actions/artifacts/'+str(artifact_id)
    def github(path):
        try:return gh(path)
        except Exception as exc:raise ValueError('VENUE_RESEARCH_RUNTIME_ARTIFACT_UNAVAILABLE') from exc
    raw = github(route+'/zip')
    def metadata(url):
        _need(url == BASE+'/'+route, 'METADATA_ROUTE_INVALID')
        return read_json_bytes(github(route))
    context = context_from_encrypted_artifact(raw, artifact_id, now=started, _fetch=metadata)
    training = context['training']; receipt = context['receipt']; run = receipt['workflow_run']
    _need(training['training_sha256'] == config['training_sha256'], 'INTENDED_CANDIDATE_REQUIRED')
    _need(run.get('id') == identity['run_id'] and run.get('head_sha') == identity['head_sha'] and
          receipt['name'] == f'boat-venue-learning-{identity["run_id"]}-{identity["attempt"]}',
          'CURRENT_ARTIFACT_IDENTITY_REQUIRED')
    _need(ts(original['restore_started_at']) < ts(receipt['created_at'])+timedelta(seconds=1), 'NEW_ARTIFACT_CLOCK_REQUIRED')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        hashes = {name:hashlib.sha256(archive.read(name)).hexdigest() for name in FILES}
    _need(hashes == original['files_sha256'], 'ARTIFACT_BYTES_MISMATCH')
    verified = _aware(clock())
    _need(started <= verified < ts(receipt['expires_at']), 'READBACK_CLOCK_INVALID')
    renewed = dict(config, artifact_id=artifact_id, run_id=identity['run_id'], head_sha=identity['head_sha'])
    _write(root/'context-input.json', (json.dumps(renewed, sort_keys=True)+'\n').encode())
    ready = dict(schema=READY_SCHEMA, identity=identity, config=renewed, receipt=receipt,
                 original_config_sha256=original_sha, retained_pointer=pointer,
                 restoration_sha256=digest(original), files_sha256=hashes, verified_at=verified.isoformat())
    _save_signed(root/'ready.json', ready)  # Last create-only write is the READY gate.
    return dict(state='SAME_CANDIDATE_READY_VERIFIED', training_sha256=config['training_sha256'],
                external_receipt_verified=True, production_promoted=False, plaintext_published=False)


def select_learning_context(context_input, runner_temp, *, env, now=None):
    """A local MAC binds an independently read receipt to this worker and input."""
    root = Path(runner_temp)/RESTORE_DIRECTORY
    required = env.get('RACE_AI_CANDIDATE_RESTORE_REQUIRED') == 'true'
    if not required and not root.exists() and not root.is_symlink():return Path(context_input)
    state_key('production')
    _need(root.is_dir() and (root/'ready.json').is_file(), 'PRIVATE_READY_REQUIRED')
    root = _private_folder(root)
    ready = _signed(root/'ready.json'); current = _identity(env)
    original_sha = hashlib.sha256(_read(Path(context_input), 8192)).hexdigest()
    config = _context_config(_private_file(root/'context-input.json'))
    at = _aware(now or datetime.now(timezone.utc))
    _need(ready.get('schema') == READY_SCHEMA and ready.get('identity') == current and
          ready.get('original_config_sha256') == original_sha and ready.get('retained_pointer') == RETAINED_POINTER and
          ready.get('config') == config and config['training_sha256'] == RECOVERY_TRAINING_SHA and
          config['run_id'] == current['run_id'] and config['head_sha'] == current['head_sha'] and
          ts(ready['verified_at']) <= at < ts(ready['receipt']['expires_at']), 'PRIVATE_READY_BINDING_INVALID')
    return root/'context-input.json'


def preload_venue_research(context_input, dataset_input, runtime_folder, repo, *, gh, clock=None):
    """Return an authenticated private context and freshly verified venue grid.

    ``gh(path)`` is the existing caller's GitHub reader and returns bytes. Its
    actual metadata response is passed through the encrypted artifact verifier.
    ``runtime_folder`` must be new or empty, owner-private, and outside Git; its
    lifetime belongs to the caller. Invoke before collecting any new P1 input.
    """
    state_key('production')  # Before configuration reads, GitHub, or dataset Git.
    config = _context_config(context_input)
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
