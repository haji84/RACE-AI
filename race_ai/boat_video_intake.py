"""Private consumer with per-file bounds for authorized, already local video.

``enqueue`` copies an owner-only local file without changing its original.
``process_ready`` is suitable for an existing runtime's polling loop; it never
fetches a source, starts a service, or writes forecasts. A terminal failure is
not retried implicitly. An interrupted attempt is retained as a failure, so a
restart cannot silently reanalyze a job or invent earlier availability.

Jobs and processing events are immutable, atomically published JSON. Media
and manifests stay below an existing 0700 directory outside Git. Source and
identity declarations retain the evaluation module's UNVALIDATED semantics.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import argparse
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
from uuid import uuid4

from .boat_video_evaluation import (
    _job, _time, _wire, analyze_video, save_evaluation,
    _directory as _report_directory, _read as _read_report, _decode as _decode_report,
)
from .private_cycle_capture import _parent_handle


SCHEMA = "RACE_AI_BOAT_VIDEO_INTAKE_JOB_V1"
STATE_SCHEMA = "RACE_AI_BOAT_VIDEO_INTAKE_STATE_V1"
_ERROR = "BOAT_VIDEO_INTAKE_REJECTED"
_STORAGE_ERROR = "BOAT_VIDEO_INTAKE_STORAGE_UNAVAILABLE"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_JOB_NAME = re.compile(r"([a-f0-9]{64})\.json\Z")
_STATE_NAME = re.compile(r"([a-f0-9]{64})\.(started|finished)\.json\Z")
_MAX_JSON = 2 * 1024 * 1024
_MAX_MEDIA = 256 * 1024 * 1024
_COUNTS = ("PENDING", "PROCESSING", "SUCCEEDED", "FAILED")
_CLASSES = {"PRIORITY_T_MINUS_15_TO_10", "PRE_CUTOFF_LATE_WINDOW", "LATE_HISTORICAL"}
_FAILURES = {"MEDIA_INTEGRITY_REJECTED", "ANALYSIS_FAILED", "REPORT_PERSIST_FAILED",
             "INTERRUPTED_PREVIOUS_ATTEMPT", "STORAGE_UNAVAILABLE"}
_MAX_CONNECTION = 32 * 1024 * 1024
_PUBLICATION_SCHEMA = 'RACE_AI_BOAT_VIDEO_INTAKE_PUBLICATION_V1'
_PUBLICATION_NAME = re.compile(r'([a-f0-9]{64})\.([a-f0-9]{64})\.(started|finished)\.json\Z')
_PUBLICATION_ACCEPTED = 'DISPATCH_REQUEST_ACCEPTED_NOT_ARTIFACT_RECEIPT'
_PUBLICATION_UNKNOWN = 'HOLD_PUBLICATION_OUTCOME_UNKNOWN'
_PREPOST_HOLDS = {'HOLD_OWNER_STATE_KEY_REQUIRED', 'HOLD_PLATFORM_ACTIVATION_UNVERIFIED',
    'HOLD_VIDEO_PUBLICATION_DEADLINE', 'HOLD_DISPATCH_PAYLOAD_TOO_LARGE',
    'HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE', 'HOLD_PUBLISHER_TRANSPORT_UNCONFIGURED',
    'HOLD_PUBLICATION_CLOCK_UNAVAILABLE'}


class IntakeStorageError(ValueError):
    """The OS could not store data; no collection quota is imposed here."""
    def __init__(self):
        super().__init__(_STORAGE_ERROR)


def _space_failure(error):
    return isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT)


def _reject(error):
    if isinstance(error, IntakeStorageError) or _space_failure(error):
        raise IntakeStorageError() from None
    raise ValueError(_ERROR) from None


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _path(value):
    raw = os.fspath(value)
    _need(type(raw) is str and raw and "\x00" not in raw and
          not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) and not raw.startswith("//") and
          ".." not in Path(raw).parts)
    result = Path(raw).absolute()
    _need(not any(item.is_symlink() for item in (result, *result.parents)))
    return result


def _private(info, *, directory=False):
    _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600))
    _need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _regular(parent, name, *, limit):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _private(before)
    _need(0 < before.st_size <= limit)
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        actual = os.fstat(stream.fileno())
        _private(actual)
        _need(_identity(actual) == _identity(before))
        yield stream
        after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _private(after); _private(current)
        _need(_identity(after) == _identity(current) == _identity(before))


@contextmanager
def _store(private_root, *, create):
    root = _path(private_root)
    with ExitStack() as stack:
        parent = stack.enter_context(_parent_handle(root))
        _private(os.fstat(parent), directory=True)
        descriptors = {}
        for name, above in (("video-intake", parent), ("jobs", None), ("states", None), ("media", None)):
            above = descriptors["video-intake"] if above is None else above
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=above)
                    os.fsync(above)
                except FileExistsError:
                    pass
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=above)
            stack.callback(os.close, descriptor)
            _private(os.fstat(descriptor), directory=True)
            descriptors[name] = descriptor
        yield root, descriptors


@contextmanager
def _lock(parent, name, *, nonblocking=False):
    descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=parent)
    try:
        _private(os.fstat(descriptor))
        fcntl.flock(descriptor, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        yield
    finally:
        os.close(descriptor)


def _rename_noreplace(parent, old, new):
    """Atomically move a private file on Linux, refusing every existing target."""
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise OSError(errno.ENOTSUP, "ATOMIC_PRIVATE_PUBLICATION_UNAVAILABLE")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(old), parent, os.fsencode(new), 1) != 0:
        raise OSError(ctypes.get_errno(), "ATOMIC_PRIVATE_PUBLICATION_FAILED")


def _atomic(parent, name, writer):
    """Publish complete bytes without ever replacing an existing target."""
    temporary = ".tmp-" + uuid4().hex
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
            _private(os.fstat(stream.fileno()))
        # A single no-replace move publishes the complete file and removes its
        # temporary name. SIGKILL cannot strand an extra hardlink that makes
        # a valid published job or event permanently unreadable on restart.
        _rename_noreplace(parent, temporary, name)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        else:
            os.fsync(parent)


def _read(parent, name):
    with _regular(parent, name, limit=_MAX_JSON) as source:
        raw = source.read(_MAX_JSON + 1)
    _need(0 < len(raw) <= _MAX_JSON)
    return raw


def _immutable(parent, name, raw):
    try:
        _atomic(parent, name, lambda target: target.write(raw))
    except FileExistsError:
        _need(_read(parent, name) == raw)


def _json(raw):
    def unique(pairs):
        value = {}
        for key, child in pairs:
            _need(key not in value)
            value[key] = child
        return value
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: _need(False))
    _need(type(value) is dict and _wire(value) == raw)
    return value


def _names(parent):
    with os.scandir(parent) as entries:
        for entry in entries:
            if not re.fullmatch(r"\.tmp-[a-f0-9]{32}", entry.name):
                yield entry.name


def _digest(source):
    digest, total = sha256(), 0
    source.seek(0)
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        _need(total <= _MAX_MEDIA)
        digest.update(chunk)
    _need(total > 0)
    return digest.hexdigest()


def _media_checked(parent, name, expected):
    with _regular(parent, name, limit=_MAX_MEDIA) as source:
        _need(_digest(source) == expected)


def enqueue(private_root, media_path, job):
    """Queue a complete JOB_V1 and private content-addressed local media copy.

    Both the existing input directory and private root must be owned 0700
    directories outside Git. The input must be an owned 0600 regular file,
    with no symlink or hardlink. Exact repeated jobs keep their existing ID.
    """
    try:
        specification = _job(job)
        source_path = _path(media_path)
        with _parent_handle(source_path.parent) as source_parent:
            _private(os.fstat(source_parent), directory=True)
            with _regular(source_parent, source_path.name, limit=_MAX_MEDIA) as source:
                source_identity = _identity(os.fstat(source.fileno()))
                expected = specification["source"]["media_sha256"]
                _need(_digest(source) == expected)
                manifest = {"schema_version": SCHEMA, "job": specification,
                            "media_reference": "media/" + expected + ".media"}
                raw = _wire(manifest)
                _need(len(raw) <= _MAX_JSON)
                ident = sha256(raw).hexdigest()
                with _store(private_root, create=True) as (_, directories):
                    with _lock(directories["video-intake"], "enqueue.lock"):
                        media_name = expected + ".media"
                        try:
                            os.stat(media_name, dir_fd=directories["media"], follow_symlinks=False)
                        except FileNotFoundError:
                            def copy(target):
                                source.seek(0)
                                digest, copied = sha256(), 0
                                while True:
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    copied += len(chunk)
                                    _need(copied <= _MAX_MEDIA)
                                    target.write(chunk)
                                    digest.update(chunk)
                                _need(digest.hexdigest() == expected)
                            _atomic(directories["media"], media_name, copy)
                        else:
                            _media_checked(directories["media"], media_name, expected)
                        current = os.stat(source_path.name, dir_fd=source_parent, follow_symlinks=False)
                        _private(current)
                        _need(_identity(current) == _identity(os.fstat(source.fileno())) == source_identity)
                        _immutable(directories["jobs"], ident + ".json", raw)
        return ident
    except (OSError, KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        _reject(error)


def _jobs(directories):
    names, jobs = _names(directories["jobs"]), {}
    for name in names:
        match = _JOB_NAME.fullmatch(name)
        _need(match is not None)
        raw = _read(directories["jobs"], name)
        value = _json(raw)
        _need(set(value) == {"schema_version", "job", "media_reference"} and
              value["schema_version"] == SCHEMA and sha256(raw).hexdigest() == match[1])
        job = _job(value["job"])
        _need(value["media_reference"] == "media/" + job["source"]["media_sha256"] + ".media")
        jobs[match[1]] = job
    return jobs


def _event(value, ident, phase):
    _need(set(value) == {"schema_version", "job_sha256", "state", "recorded_at", "schedule_class",
                         "availability", "report_sha256", "failure_code", "state_sha256"})
    _need(value["schema_version"] == STATE_SCHEMA and value["job_sha256"] == ident and
          type(value["state_sha256"]) is str and _SHA.fullmatch(value["state_sha256"]))
    _need(sha256(_wire({k: v for k, v in value.items() if k != "state_sha256"})).hexdigest() == value["state_sha256"])
    _time(value["recorded_at"])
    _need(value["schedule_class"] in _CLASSES)
    if phase == "started":
        _need(value["state"] == "PROCESSING" and value["availability"] is None and
              value["report_sha256"] is None and value["failure_code"] is None)
    elif value["state"] == "SUCCEEDED":
        _need(type(value["report_sha256"]) is str and _SHA.fullmatch(value["report_sha256"]) and
              value["availability"] in ("PRE_CUTOFF", "LATE_HISTORICAL") and value["failure_code"] is None)
    else:
        _need(value["state"] == "FAILED" and value["report_sha256"] is None and
              value["availability"] is None and value["failure_code"] in _FAILURES)
    return value


def _states(directories, jobs):
    events = {}
    for name in _names(directories["states"]):
        match = _STATE_NAME.fullmatch(name)
        _need(match is not None and match[1] in jobs)
        events[(match[1], match[2])] = _event(_json(_read(directories["states"], name)), match[1], match[2])
    states = {}
    for ident in jobs:
        started, finished = events.get((ident, "started")), events.get((ident, "finished"))
        if finished is not None:
            _need(started is not None and _time(started["recorded_at"]) <= _time(finished["recorded_at"]) and
                  started["schedule_class"] == finished["schedule_class"])
        states[ident] = finished or started
    return states


def _status(jobs, states):
    counts = dict.fromkeys(_COUNTS, 0)
    for ident in jobs:
        counts[states[ident]["state"] if states[ident] is not None else "PENDING"] += 1
    real_sources = sum(job["source"]["kind"] != "SYNTHETIC_TEST" for job in jobs.values())
    return {"status": "LOCAL_INTAKE_READY" if real_sources else "WAITING_FOR_AUTHORIZED_SOURCE",
            "counts": counts, "source_acquisition_complete": False, "automatic_official_fetch": False,
            "network_requests": 0, "forecast_originals_modified": False}


def _check_saved_reports(root, jobs, states):
    succeeded = {ident: state for ident, state in states.items()
                 if state is not None and state["state"] == "SUCCEEDED"}
    if not succeeded:
        return
    with _report_directory(root, create=False) as directory:
        for ident, state in succeeded.items():
            digest = state["report_sha256"]
            report = _decode_report(_read_report(directory, digest + ".json"), digest)
            specification = {"schema_version": jobs[ident]["schema_version"],
                             **{key: report[key] for key in ("race_id", "cutoff_at", "roster", "source")},
                             **report["analysis_parameters"]}
            _need(specification == jobs[ident] and state["availability"] ==
                  ("PRE_CUTOFF" if report["pre_cutoff_available"] else "LATE_HISTORICAL"))


def read_status(private_root):
    """Return aggregate health only; never decode media or touch forecasts."""
    try:
        try:
            with _store(private_root, create=False) as (root, directories):
                jobs = _jobs(directories)
                states = _states(directories, jobs)
                _check_saved_reports(root, jobs, states)
                return _status(jobs, states)
        except FileNotFoundError:
            # A missing root must not masquerade as an empty valid queue.
            with _parent_handle(_path(private_root)) as root:
                _private(os.fstat(root), directory=True)
                try:
                    os.stat("video-intake", dir_fd=root, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError(_ERROR)
            return _status({}, {})
    except (OSError, KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        _reject(error)


def _record(directories, ident, state, schedule_class, *, report=None, failure_code=None):
    value = {"schema_version": STATE_SCHEMA, "job_sha256": ident, "state": state,
             "recorded_at": datetime.now(timezone.utc).isoformat(), "schedule_class": schedule_class,
             "availability": ("PRE_CUTOFF" if report["pre_cutoff_available"] else "LATE_HISTORICAL")
                 if report is not None else None,
             "report_sha256": report["report_sha256"] if report is not None else None,
             "failure_code": failure_code}
    value["state_sha256"] = sha256(_wire(value)).hexdigest()
    phase = "started" if state == "PROCESSING" else "finished"
    _event(value, ident, phase)
    _immutable(directories["states"], ident + "." + phase + ".json", _wire(value))
    return value


def _priority(job, instant):
    cutoff = _time(job["cutoff_at"])
    remaining = cutoff - instant
    if timedelta(minutes=10) <= remaining <= timedelta(minutes=15):
        return 0, cutoff, "PRIORITY_T_MINUS_15_TO_10"
    if timedelta(0) < remaining < timedelta(minutes=10):
        return 1, cutoff, "PRE_CUTOFF_LATE_WINDOW"
    if remaining <= timedelta(0):
        return 2, cutoff, "LATE_HISTORICAL"
    return None


@contextmanager
def _connection_store(private_root):
    root = _path(private_root)
    with _parent_handle(root) as parent:
        _private(os.fstat(parent), directory=True)
        try:
            os.mkdir('video-connections', 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        directory = os.open('video-connections', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
        try:
            _private(os.fstat(directory), directory=True)
            yield root, directory
        finally:
            os.close(directory)


def _read_connection(directory, name):
    from .actions_contract import digest
    from .boat_video_connection import SCHEMA as connection_schema
    with _regular(directory, name, limit=_MAX_CONNECTION) as stream:
        raw = stream.read(_MAX_CONNECTION + 1)
    _need(0 < len(raw) <= _MAX_CONNECTION)
    value = _json(raw)
    _need(value['schema_version'] == connection_schema and
          value['connection_sha256'] + '.json' == name and
          digest({key: child for key, child in value.items() if key != 'connection_sha256'}) ==
              value['connection_sha256'] and
          _SHA.fullmatch(value['report_sha256']) and _SHA.fullmatch(value['input_sha256']) and
          value['status'] in {'BLOCKED', 'WAITING_FROZEN_TRAINING_AND_INPUTS',
              'WAITING_INDEPENDENT_CONTEXT_RECEIPT', 'CONNECTED_EXPERIMENTAL'} and
          value['production_eligible'] is False and value['forecast_originals_modified'] is False and
          value['training_performed'] is False and value['raw_report_validation_status'] == 'UNVALIDATED' and
          value['independent_human_heldout_verified'] is False and
          value['video_context']['report_sha256'] == value['report_sha256'] and
          _time(value['started_at']) <= _time(value['completed_at']))
    if value['status'] == 'CONNECTED_EXPERIMENTAL':
        _need(_time(value['completed_at']) < _time(value['cutoff_at']) and not value['missing_reasons'])
    else:
        _need(value['shadows'] == [] and bool(value['missing_reasons']))
    return value, raw


def _connection_reports(directory, selected):
    """Read a selected report directly; prioritize live cutoffs on a rescan."""
    if selected is not None and len(selected) <= 1:
        for ident in selected:
            yield _decode_report(_read_report(directory, ident + '.json'), ident)
        return
    names = (ident + '.json' for ident in selected) if selected is not None else _names(directory)
    pending, instant = [], datetime.now(timezone.utc)
    for name in names:
        match = _JOB_NAME.fullmatch(name)
        _need(match is not None)
        report = _decode_report(_read_report(directory, name), match[1])
        cutoff = _time(report['cutoff_at'])
        pending.append((0 if cutoff > instant else 1, cutoff, match[1]))
    # Keep only small scheduling metadata, never all archived report bodies.
    for _, _, ident in sorted(pending):
        yield _decode_report(_read_report(directory, ident + '.json'), ident)


@contextmanager
def _publication_store(private_root):
    with _parent_handle(_path(private_root)) as parent:
        _private(os.fstat(parent), directory=True)
        try:
            os.mkdir('video-publications', 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        directory = os.open('video-publications', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
        try:
            _private(os.fstat(directory), directory=True)
            yield directory
        finally:
            os.close(directory)


def _publication_view(value, *, outcome=None, status=None):
    return dict(context_sha256=value['context_sha256'], report_sha256=value['report_sha256'],
        publisher_configuration_sha256=value['publisher_configuration_sha256'],
        outcome=value['outcome'] if outcome is None else outcome,
        status=value['status'] if status is None else status,
        artifact_receipt_verified=False, production_eligible=False)


def _publication_event(context, configuration, phase, outcome, status, *, response=None):
    from .actions_contract import digest
    value = dict(schema_version=_PUBLICATION_SCHEMA, context_sha256=context['context_sha256'],
        report_sha256=context['report_sha256'], publisher_configuration_sha256=configuration,
        recorded_at=datetime.now(timezone.utc).isoformat(), phase=phase, outcome=outcome, status=status,
        artifact_receipt_verified=False, production_eligible=False)
    if outcome == 'ACCEPTED':
        value.update(context_count=1, cipher_sha256=response['cipher_sha256'],
                     dispatch_sha256=response['dispatch_sha256'])
    value['state_sha256'] = digest(value)
    return value


def _publication_events(directory, context):
    from .actions_contract import digest
    events = {}
    for name in _names(directory):
        if name == 'process.lock':
            continue
        match = _PUBLICATION_NAME.fullmatch(name)
        _need(match is not None)
        if match[1] != context['context_sha256']:
            continue
        value = _json(_read(directory, name))
        fields = {'schema_version', 'context_sha256', 'report_sha256', 'publisher_configuration_sha256',
            'recorded_at', 'phase', 'outcome', 'status', 'artifact_receipt_verified',
            'production_eligible', 'state_sha256'}
        if value.get('outcome') == 'ACCEPTED':
            fields |= {'context_count', 'cipher_sha256', 'dispatch_sha256'}
            _need(type(value.get('context_count')) is int and value['context_count'] == 1 and all(type(value.get(key)) is str and
                _SHA.fullmatch(value[key]) for key in ('cipher_sha256', 'dispatch_sha256')))
        _need(set(value) == fields and value['schema_version'] == _PUBLICATION_SCHEMA and
            value['context_sha256'] == context['context_sha256'] and
            value['report_sha256'] == context['report_sha256'] and
            value['publisher_configuration_sha256'] == match[2] and value['phase'] == match[3] and
            value['artifact_receipt_verified'] is False and value['production_eligible'] is False and
            digest({key: child for key, child in value.items() if key != 'state_sha256'}) == value['state_sha256'])
        _time(value['recorded_at'])
        _need((value['phase'] == 'started' and value['outcome'] == 'STARTED' and
               value['status'] == 'PUBLICATION_ATTEMPT_STARTED') or
              (value['phase'] == 'finished' and
               ((value['outcome'] == 'HOLD' and value['status'] in _PREPOST_HOLDS) or
                (value['outcome'] == 'ACCEPTED' and value['status'] == _PUBLICATION_ACCEPTED) or
                (value['outcome'] == 'UNKNOWN' and value['status'] == _PUBLICATION_UNKNOWN))))
        events[match[2], match[3]] = value
    return events


def _publication_binding(root, report, bundle, evidence, inputs):
    from .boat_video_model_context import validate_video_context
    context = bundle['video_context']
    _need(validate_video_context(context, race_id=report['race_id'], cutoff_at=report['cutoff_at'],
        as_of=context['as_of'], roster=report['roster']) == context and
        context['eligible_for_research'] is True and context['report_sha256'] == report['report_sha256'])
    with _report_directory(root, create=False) as reports:
        _need(_decode_report(_read_report(reports, report['report_sha256']+'.json'), report['report_sha256']) == report)
    media_name = report['source']['media_sha256'] + '.media'
    with _store(root, create=False) as (_, directories):
        _media_checked(directories['media'], media_name, report['source']['media_sha256'])
    return dict(report=deepcopy(report), identity_evidence=deepcopy(evidence), model_inputs=deepcopy(inputs),
        connection_bundle=deepcopy(bundle), video_context=deepcopy(context),
        report_path=root/'video-evaluations'/(report['report_sha256']+'.json'),
        media_path=root/'video-intake'/'media'/media_name)


def _publish_context(root, report, bundle, evidence, inputs, publisher, clock):
    """Journal one trusted callback; UNKNOWN/accepted contexts never auto-retry."""
    context = bundle['video_context']
    configuration = None
    fallback = dict(context_sha256=context['context_sha256'], report_sha256=report['report_sha256'],
        publisher_configuration_sha256=None, outcome='HOLD', status='HOLD_PUBLISHER_CONFIGURATION_REQUIRED',
        artifact_receipt_verified=False, production_eligible=False)
    started = False
    try:
        try:
            configuration = getattr(publisher, 'configuration_sha256', None)
        except Exception:
            return fallback, None
        if not (callable(publisher) and type(configuration) is str and _SHA.fullmatch(configuration)):
            return fallback, None
        fallback['publisher_configuration_sha256'] = configuration
        with _publication_store(root) as directory:
            with _lock(directory, 'process.lock', nonblocking=True):
                events = _publication_events(directory, context)
                for (config, phase), event in events.items():
                    if phase == 'finished' and event['outcome'] in ('ACCEPTED', 'UNKNOWN'):
                        return _publication_view(event), False
                    if phase == 'started' and (config, 'finished') not in events:
                        return _publication_view(event, outcome='UNKNOWN', status=_PUBLICATION_UNKNOWN), False
                if (configuration, 'finished') in events:
                    return _publication_view(events[configuration, 'finished']), False
                prefix = context['context_sha256']+'.'+configuration
                event = _publication_event(context, configuration, 'started', 'STARTED', 'PUBLICATION_ATTEMPT_STARTED')
                _immutable(directory, prefix+'.started.json', _wire(event))
                started = True
                try:
                    from .boat_video_connection import _instant
                    instant = _instant(clock)
                except Exception:
                    response = dict(status='HOLD_PUBLICATION_CLOCK_UNAVAILABLE')
                else:
                    if instant >= _time(context['cutoff_at']):
                        response = dict(status='HOLD_VIDEO_PUBLICATION_DEADLINE')
                    else:
                        try:
                            binding = _publication_binding(root, report, bundle, evidence, inputs)
                        except Exception:
                            response = dict(status='HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE')
                        else:
                            try:
                                response = publisher(binding)
                            except Exception:
                                response = None
                status = (response.get('status') if type(response) is dict and
                          type(response.get('status')) is str else None)
                accepted = (status == _PUBLICATION_ACCEPTED and type(response.get('context_count')) is int and
                    response['context_count'] == 1 and
                    all(type(response.get(key)) is str and _SHA.fullmatch(response[key])
                        for key in ('cipher_sha256', 'dispatch_sha256')))
                outcome = 'ACCEPTED' if accepted else 'HOLD' if status in _PREPOST_HOLDS else 'UNKNOWN'
                status = status if outcome != 'UNKNOWN' else _PUBLICATION_UNKNOWN
                final = _publication_event(context, configuration, 'finished', outcome, status, response=response)
                _immutable(directory, prefix+'.finished.json', _wire(final))
                return _publication_view(final), True
    except Exception:
        fallback.update(outcome='UNKNOWN' if started else 'HOLD',
                        status=_PUBLICATION_UNKNOWN if started else 'HOLD_PUBLICATION_STORAGE_UNAVAILABLE')
        return fallback, True if started else None


def _publication_summary(states, created, reused=()):
    unique = {(state['context_sha256'], state['publisher_configuration_sha256']): state for state in states}
    return dict(status='PUBLICATION_ATTEMPTS_RECORDED' if unique else 'WAITING_FOR_QUALIFIED_CONTEXTS',
        processed=sum(key in created for key in unique),
        reused=sum(key in reused and key not in created for key in unique),
        states=list(unique.values()), counts={outcome: sum(row['outcome'] == outcome for row in unique.values())
            for outcome in sorted({row['outcome'] for row in unique.values()})},
        artifact_receipt_verified=False, production_eligible=False)


def make_context_publisher(*, configuration_sha256, expected_head_sha, key_provider=None,
                           platform_ready=False, send=None, clock=None):
    """Configure a trusted Python adapter; construction performs no external I/O.

    ``configuration_sha256`` is an opaque NONSECRET revision, never a key hash.
    Change it when a known pre-POST HOLD is configured. A sender is mandatory;
    this adapter never falls back to gh, activates a platform, or creates keys.
    The intake journal records dispatch acceptance, never an artifact receipt.
    """
    _need(type(configuration_sha256) is str and _SHA.fullmatch(configuration_sha256) and
        type(expected_head_sha) is str and re.fullmatch(r'[a-f0-9]{40}', expected_head_sha) and
        type(platform_ready) is bool and (key_provider is None or callable(key_provider)) and
        (send is None or callable(send)))

    def publish(binding):
        from .boat_video_publication import prepare_publication, dispatch_publication
        try:
            key = None if key_provider is None else key_provider()
        except Exception:
            return dict(status='HOLD_OWNER_STATE_KEY_REQUIRED')
        item = {name: binding[name] for name in ('report_path', 'media_path', 'identity_evidence', 'video_context')}
        inputs = binding['model_inputs']
        if type(inputs) is dict and 'calibration_manifest' in inputs:
            item['calibration_manifest'] = inputs['calibration_manifest']
        summary, request = prepare_publication([item], expected_head_sha=expected_head_sha, key=key, clock=clock)
        if request is None:
            return summary
        if not platform_ready:
            return dict(status='HOLD_PLATFORM_ACTIVATION_UNVERIFIED')
        if send is None:
            return dict(status='HOLD_PUBLISHER_TRANSPORT_UNCONFIGURED')
        return dispatch_publication(summary, request, key=key, clock=clock, platform_ready=True, send=send)

    publish.configuration_sha256 = configuration_sha256
    return publish


def process_connections(private_root, *, identity_evidence_provider=None, model_inputs_provider=None,
                        receipt_verifier=None, clock=None, report_sha256s=None, _session=None,
                        context_publisher=None):
    """Connect completed private reports without a second job/state schema.

    Providers are optional trusted Python dependencies accepting a detached
    report. The CLI never loads model/evidence providers or receipt claims.
    Every attempt is an immutable content-addressed bundle; its input hash
    excludes polling clocks. Changed evidence or model inputs permit a new
    attempt, while restart and repeated polls reuse the existing attempt.
    Reports are read one at a time, with no aggregate archive quota. A supplied
    ``report_sha256s`` selection reads only those reports; an unfiltered rescan
    considers upcoming cutoffs first. ``_session`` is an internal per-poll
    cache, never persistent state or an independent authentication source.

    An optional trusted ``context_publisher(binding)`` has a NONSECRET
    ``configuration_sha256`` revision. Eligible frozen contexts and protected
    local originals are bound before invocation. Its separate immutable
    journal permits a new configuration after an explicit pre-POST HOLD;
    accepted or unknown/interrupted POST outcomes never auto-retry. No CLI or
    JSON field supplies this callback, and acceptance is not a saved receipt.
    """
    from .boat_video_connection import connect_report, input_fingerprint
    try:
        _need(identity_evidence_provider is None or callable(identity_evidence_provider))
        _need(model_inputs_provider is None or callable(model_inputs_provider))
        _need(report_sha256s is None or type(report_sha256s) in (list, tuple, set, frozenset))
        selected = None if report_sha256s is None else set(report_sha256s)
        _need(selected is None or all(type(ident) is str and _SHA.fullmatch(ident) for ident in selected))
        session = {} if _session is None else _session
        attempts = session.setdefault('attempts', {})
        known_files = session.setdefault('known_files', set())
        failures = session.setdefault('failures', {})
        created = session.setdefault('created', set())
        summary = dict(status='WAITING_FOR_COMPLETED_REPORTS', processed=0, reused=0, failed=0,
            counts={}, states=[], production_eligible=False, forecast_originals_modified=False)
        publication_states = []
        publication_created = session.setdefault('publication_created', set()) if context_publisher is not None else set()
        publication_reused = session.setdefault('publication_reused', set()) if context_publisher is not None else set()
        if context_publisher is not None:
            summary['context_publications'] = _publication_summary([], publication_created)
        with _connection_store(private_root) as (root, directory):
            try:
                with _lock(directory, 'process.lock', nonblocking=True):
                    for name in _names(directory):
                        if name == 'process.lock' or name in known_files:
                            continue
                        _need(_JOB_NAME.fullmatch(name) is not None)
                        bundle, _ = _read_connection(directory, name)
                        key = bundle['report_sha256'], bundle['input_sha256']
                        _need(key not in attempts)
                        attempts[key] = bundle
                        known_files.add(name)
                    with ExitStack() as stack:
                        try:
                            reports = stack.enter_context(_report_directory(root, create=False))
                        except FileNotFoundError:
                            return summary
                        for report in _connection_reports(reports, selected):
                            fingerprint = None
                            try:
                                evidence = (None if identity_evidence_provider is None else
                                            identity_evidence_provider(deepcopy(report)))
                                inputs = (None if model_inputs_provider is None else
                                          model_inputs_provider(deepcopy(report)))
                                fingerprint = input_fingerprint(report, evidence, inputs,
                                                                receipt_verifier=receipt_verifier)
                                key = report['report_sha256'], fingerprint
                                bundle = attempts.get(key)
                                if bundle is None and key in failures:
                                    summary['states'].append(failures[key])
                                    summary['failed'] += 1
                                    summary['counts']['CONNECTION_ATTEMPT_FAILED'] = summary['counts'].get('CONNECTION_ATTEMPT_FAILED', 0) + 1
                                    continue
                                if bundle is None:
                                    bundle = connect_report(report, identity_evidence=evidence,
                                        model_inputs=inputs, receipt_verifier=receipt_verifier, clock=clock)
                                    _need(bundle['input_sha256'] == fingerprint)
                                    raw, filename = _wire(bundle), bundle['connection_sha256'] + '.json'
                                    _need(0 < len(raw) <= _MAX_CONNECTION)
                                    try:
                                        _atomic(directory, filename, lambda target: target.write(raw))
                                    except FileExistsError:
                                        _need(_read_connection(directory, filename)[1] == raw)
                                    attempts[key] = bundle
                                    known_files.add(filename)
                                    created.add(key)
                                    summary['processed'] += 1
                                else:
                                    summary['reused'] += 1
                                state = {key: bundle[key] for key in ('report_sha256', 'input_sha256',
                                    'connection_sha256', 'status', 'missing_reasons')}
                                summary['states'].append(state)
                                summary['counts'][bundle['status']] = summary['counts'].get(bundle['status'], 0) + 1
                                if context_publisher is not None and bundle['video_context']['eligible_for_research']:
                                    publication, fresh = _publish_context(root, report, bundle, evidence, inputs,
                                                                         context_publisher, clock)
                                    publication_states.append(publication)
                                    if fresh:
                                        publication_created.add((publication['context_sha256'],
                                                                 publication['publisher_configuration_sha256']))
                                    elif fresh is False:
                                        publication_reused.add((publication['context_sha256'],
                                                                publication['publisher_configuration_sha256']))
                                    summary['context_publications'] = _publication_summary(publication_states,
                                                                                          publication_created,
                                                                                          publication_reused)
                            except Exception:
                                # A provider/model/storage failure never changes
                                # the successful report or intake state files.
                                summary['failed'] += 1
                                failure = dict(report_sha256=report['report_sha256'], input_sha256=fingerprint,
                                    connection_sha256=None, status='CONNECTION_ATTEMPT_FAILED',
                                    missing_reasons=['MODEL_CONNECTION_FAILED'])
                                summary['states'].append(failure)
                                summary['counts']['CONNECTION_ATTEMPT_FAILED'] = summary['counts'].get('CONNECTION_ATTEMPT_FAILED', 0) + 1
                                if fingerprint is not None:
                                    failures[(report['report_sha256'], fingerprint)] = failure
                    if summary['states'] or summary['failed']:
                        summary['status'] = 'CONNECTION_ATTEMPTS_RECORDED' if not summary['failed'] else 'CONNECTION_ATTEMPTS_INCOMPLETE'
                    return summary
            except BlockingIOError:
                summary['status'] = 'BUSY'
                return summary
    except (OSError, KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        _reject(error)


def _merge_connection_results(results, session):
    """Count each report/input once across immediate attempts and final rescan."""
    states = {}
    for result in results:
        for state in result['states']:
            states[(state['report_sha256'], state['input_sha256'])] = state
    created = session.get('created', set())
    failures = sum(state['status'] == 'CONNECTION_ATTEMPT_FAILED' for state in states.values())
    failures += int(any(result['failed'] and not result['states'] for result in results))
    summary = dict(status='WAITING_FOR_COMPLETED_REPORTS',
        processed=sum(key in created for key in states),
        reused=sum(state['connection_sha256'] is not None and key not in created for key, state in states.items()),
        failed=failures, counts={}, states=list(states.values()),
        production_eligible=False, forecast_originals_modified=False)
    for state in states.values():
        summary['counts'][state['status']] = summary['counts'].get(state['status'], 0) + 1
    if states or failures:
        summary['status'] = 'CONNECTION_ATTEMPTS_INCOMPLETE' if failures else 'CONNECTION_ATTEMPTS_RECORDED'
    elif any(result['status'] == 'BUSY' for result in results):
        summary['status'] = 'BUSY'
    if any('context_publications' in result for result in results):
        publication_states = [state for result in results
            for state in result.get('context_publications', {}).get('states', [])]
        summary['context_publications'] = _publication_summary(publication_states,
            session.get('publication_created', set()), session.get('publication_reused', set()))
    return summary


def process_ready(private_root, *, now=None, extractor=None, connect_models=False,
                  identity_evidence_provider=None, model_inputs_provider=None,
                  receipt_verifier=None, connection_clock=None, context_publisher=None):
    """Consume ready jobs once, giving T-15..T-10 priority in cutoff order.

    ``now`` affects scheduling only. Evaluation start/completion always use the
    actual clock. The optional extractor is the same integration boundary as
    ``analyze_video``; callers can supply the local identity extractor factory.
    A nonblocking flock lets an existing runtime skip a concurrent consumer.
    ``connect_models`` optionally connects saved reports using independent
    Python providers. It never changes the original job/state/report schemas.
    ``context_publisher`` is used only by that explicitly enabled connection
    loop; the default creates no publication directory or result fields.
    """
    try:
        instant = datetime.now(timezone.utc) if now is None else now
        _need(type(instant) is datetime and instant.utcoffset() is not None)
        with _store(private_root, create=True) as (root, directories):
            try:
                with _lock(directories["video-intake"], "process.lock", nonblocking=True):
                    jobs = _jobs(directories)
                    states = _states(directories, jobs)
                    _check_saved_reports(root, jobs, states)
                    results, connection_results, connection_session = [], [], {}
                    def connect_saved(selected=None):
                        try:
                            publication_options = ({'context_publisher': context_publisher}
                                                   if context_publisher is not None else {})
                            outcome = process_connections(root,
                                identity_evidence_provider=identity_evidence_provider,
                                model_inputs_provider=model_inputs_provider, receipt_verifier=receipt_verifier,
                                clock=connection_clock, report_sha256s=selected, _session=connection_session,
                                **publication_options)
                        except Exception:
                            outcome = dict(status='CONNECTION_STORAGE_UNAVAILABLE', processed=0, reused=0,
                                failed=1, counts={}, states=[])
                        connection_results.append(outcome)
                    def connect_live_saved():
                        # A report may have waited for its independent receipt
                        # on the previous poll, or acquire it during this batch.
                        # Use known state/job metadata to revisit only live
                        # reports before any slower historical analysis.
                        saved = [(_time(jobs[ident]['cutoff_at']), state['report_sha256'])
                            for ident, state in states.items() if state is not None and state['state'] == 'SUCCEEDED']
                        if not saved:
                            return
                        from .boat_video_connection import _instant as connection_instant
                        try:
                            current = connection_instant(connection_clock)
                        except Exception:
                            connection_results.append(dict(status='CONNECTION_CLOCK_UNAVAILABLE',
                                processed=0, reused=0, failed=1, counts={}, states=[]))
                            return
                        live = sorted(item for item in saved if item[0] > current)
                        for _, report_sha256 in live:
                            connect_saved((report_sha256,))
                    for ident, job in jobs.items():
                        state = states[ident]
                        if state is not None and state["state"] == "PROCESSING":
                            finished = _record(directories, ident, "FAILED", state["schedule_class"],
                                               failure_code="INTERRUPTED_PREVIOUS_ATTEMPT")
                            states[ident] = finished
                            results.append(finished)
                    while True:
                        # Delivery uses its own short enqueue lock, so urgent
                        # arrivals can preempt the remaining historical queue
                        # between analyses. Retained jobs impose no lifetime
                        # count or byte quota and are never silently removed.
                        delivered = _jobs(directories)
                        _need(all(delivered.get(ident) == job for ident, job in jobs.items()))
                        for ident in delivered.keys() - jobs.keys():
                            states[ident] = None
                        jobs = delivered
                        if connect_models:
                            connect_live_saved()
                        instant = datetime.now(timezone.utc) if now is None else now
                        ready, deferred = [], 0
                        for ident, job in jobs.items():
                            if states[ident] is not None:
                                continue
                            priority = _priority(job, instant)
                            if priority is None:
                                deferred += 1
                            else:
                                ready.append((*priority[:2], ident, priority[2]))
                        if not ready:
                            break
                        _, _, ident, schedule_class = min(ready)
                        job = jobs[ident]
                        _record(directories, ident, "PROCESSING", schedule_class)
                        digest = job["source"]["media_sha256"]
                        name = digest + ".media"
                        report, failure = None, "MEDIA_INTEGRITY_REJECTED"
                        try:
                            with _regular(directories["media"], name, limit=_MAX_MEDIA) as media:
                                _need(_digest(media) == digest)
                                failure = "ANALYSIS_FAILED"
                                report = analyze_video(root / "video-intake" / "media" / name,
                                                       job, extractor=extractor)
                                failure = "MEDIA_INTEGRITY_REJECTED"
                                _need(_digest(media) == digest)
                            failure = "REPORT_PERSIST_FAILED"
                            save_evaluation(root, report)
                        except Exception as error:
                            # Native decoders and injected local model adapters
                            # can have their own exception types. Preserve a
                            # terminal safe error for every ordinary failure;
                            # process interruptions remain restart evidence.
                            finished = _record(directories, ident, "FAILED", schedule_class,
                                failure_code="STORAGE_UNAVAILABLE" if _space_failure(error) else failure)
                        else:
                            finished = _record(directories, ident, "SUCCEEDED", schedule_class, report=report)
                        states[ident] = finished
                        results.append(finished)
                        if connect_models and finished['state'] == 'SUCCEEDED':
                            # Finish the urgent report's model path before a
                            # slower historical analysis can consume its cutoff.
                            connect_saved((finished['report_sha256'],))
                    result = _status(jobs, states)
                    result.update(processed=len(results), succeeded=sum(row["state"] == "SUCCEEDED" for row in results),
                                  failed=sum(row["state"] == "FAILED" for row in results), deferred=deferred,
                                  states=[{key: row[key] for key in ("job_sha256", "state", "availability",
                                      "report_sha256", "failure_code")} for row in results])
                    if connect_models:
                        connect_saved()
                        result['model_connections'] = _merge_connection_results(connection_results, connection_session)
                    return result
            except BlockingIOError:
                return {**read_status(root), "status": "BUSY", "processed": 0, "succeeded": 0,
                        "failed": 0, "deferred": 0, "states": []}
    except (OSError, KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        _reject(error)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, _ERROR + ": invalid command arguments\n")


def _system_tessdata():
    for directory in ("/usr/share/tesseract-ocr/5/tessdata",
                      "/usr/share/tesseract-ocr/4.00/tessdata",
                      "/usr/share/tessdata", "/usr/local/share/tessdata"):
        candidate = Path(directory)
        if (candidate / "eng.traineddata").is_file():
            return candidate
    raise ValueError(_ERROR)


def _identity_extractor(args):
    """Keep asset paths in a callable; every media gets new temporal state."""
    options = {"model_path": _path(args.hull_model), "detector_kind": args.detector_kind or "yolox"}
    if args.tiled_hulls:
        options["tiled_hulls"] = True
    if args.crnn_model is not None:
        from .boat_video_crnn import make_crnn_identity_extractor
        return make_crnn_identity_extractor(crnn_model_path=_path(args.crnn_model), **options)
    from .boat_video_identity import make_local_identity_extractor
    return make_local_identity_extractor(**options,
        tesseract_path=_path(args.tesseract or shutil.which("tesseract")),
        tessdata_path=_path(args.tessdata) if args.tessdata else _system_tessdata())


def main(argv=None, *, extractor=None, identity_evidence_provider=None, model_inputs_provider=None,
         receipt_verifier=None, connection_clock=None, context_publisher=None):
    """Poll the existing loop; optional providers are trusted Python args only.

    Connection callbacks require explicit ``--connect-models``. No CLI option
    loads callbacks, keys or receipt authentication from JSON or module names.
    """
    parser = _Parser(description=__doc__)
    parser.add_argument("--private-root", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--follow", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--connect-models", action="store_true",
                        help="persist private model connection attempts; requires independently supplied Python evidence for research predictions")
    parser.add_argument("--hull-model", help="existing hash-pinned local hull ONNX model; enables unverified number/temporal candidates")
    parser.add_argument("--detector-kind", choices=("yolox", "nanodet"), help="local hull detector (default: yolox)")
    parser.add_argument("--tiled-hulls", action="store_true", help="optional native hull tiles using the same local detector; increases inference time")
    parser.add_argument("--crnn-model", help="optional hash-pinned local CRNN asset for uncalibrated raw temporal candidates; replaces local Tesseract")
    parser.add_argument("--tesseract", help="local OCR executable (default: system tesseract)")
    parser.add_argument("--tessdata", help="local directory containing eng.traineddata (default: standard system data)")
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 60:
        parser.error("poll interval out of bounds")
    identity_flags = args.tiled_hulls or any(value is not None for value in
                         (args.hull_model, args.detector_kind, args.crnn_model, args.tesseract, args.tessdata))
    if identity_flags and (args.hull_model is None or extractor is not None):
        parser.error("identity options require a hull model and the real local extractor")
    if args.crnn_model is not None and (args.tesseract is not None or args.tessdata is not None):
        parser.error("CRNN and Tesseract assets cannot be combined")
    connection_options = {key: value for key, value in dict(
        identity_evidence_provider=identity_evidence_provider, model_inputs_provider=model_inputs_provider,
        receipt_verifier=receipt_verifier, connection_clock=connection_clock,
        context_publisher=context_publisher).items() if value is not None}
    if connection_options and (not args.connect_models or not all(callable(value) for value in connection_options.values())):
        parser.error("trusted callbacks require explicit connection mode")
    try:
        if args.hull_model is not None:
            extractor = _identity_extractor(args)
        while True:
            print(json.dumps(process_ready(args.private_root, extractor=extractor,
                                           connect_models=args.connect_models,
                                           **connection_options), sort_keys=True), flush=True)
            if not args.follow:
                return 0
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except IntakeStorageError:
        print(_STORAGE_ERROR, file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, ImportError, RuntimeError):
        print(_ERROR, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
