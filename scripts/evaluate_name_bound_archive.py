"""Copy and replay completed local name-bound archives without source I/O.

The index inventories immutable copies; it is not a completion marker.
Failed operations retain owned partial files and never repair or overwrite them.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).absolute().parents[1]))

from race_ai.name_bound_archive import (
    ARCHIVE_FILES, MAX_BYTES, MAX_INPUTS, MAX_TOTAL_BYTES, OPERATION,
    build_archived_name_bound_cohort, validate_archived_name_bound_cohort,
)
from web.evaluation_contract import _clock
from web.race_contract import canonical


STOPPED = 'NAME_BOUND_ARCHIVE_STOPPED'
ERRORS = (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError,
    OverflowError, UnicodeError, RecursionError)
INDEX_FIELDS = set('schema_version operation generated_at application_requests network_requests official_source_requests report_bytes report_sha256 inputs'.split())
INPUT_FIELDS = {'directory', 'race_id', 'forecast_request_id', 'archive_kind', 'files'}
DRY_RUN = dict(status='DRY_RUN', application_requests=0, network_requests=0, official_source_requests=0)


def utc_now():
    return datetime.now(timezone.utc)


def _require(condition):
    if not condition:
        raise ValueError(STOPPED)


def _regular(info, directory=False):
    # Windows junctions and other reparse points need not be symlinks.
    _require(not stat.S_ISLNK(info.st_mode)
        and not getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
        and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))


def _directory(path, *, new=False):
    """Check lexical ancestry before consuming '..' or normalizing any path."""
    path = Path(path)
    if not path.is_absolute():
        # Reject drive-relative and rooted-without-drive Windows spellings.
        _require(not path.drive and not path.root)
        path = Path.cwd() / path
    current = Path(path.anchor)
    _regular(current.lstat(), directory=True)
    parts = path.parts[1:]
    _require(not new or bool(parts))
    for position, part in enumerate(parts):
        if part == '..':
            current = current.parent
        else:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            _require(new and position == len(parts) - 1 and part != '..')
            return current
        _regular(info, directory=True)
    _require(not new)
    return current


def _identity(info):
    return info.st_dev, info.st_ino


def _read_bytes(path):
    """Bound reads, reject links, and bind the descriptor to the checked file."""
    _directory(path.parent)
    before = path.lstat()
    _regular(before)
    _require(0 < before.st_size <= MAX_BYTES)
    with path.open('rb') as handle:
        opened = os.fstat(handle.fileno())
        _regular(opened)
        _require(_identity(opened) == _identity(before) and opened.st_size == before.st_size)
        raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
        _regular(after)
        _require(_identity(after) == _identity(before) and after.st_size == len(raw) == before.st_size)
    _directory(path.parent)
    current = path.lstat()
    _regular(current)
    _require(_identity(current) == _identity(before) and current.st_size == len(raw)
        and 0 < len(raw) <= MAX_BYTES)
    return raw


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _bad_constant(_):
    raise ValueError(STOPPED)


def _read_json(path):
    raw = _read_bytes(path)
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    _require(canonical(value) == raw)
    return value, raw


def _archive(folder):
    folder = _directory(folder)
    names = {path.name for path in folder.iterdir()}
    kind = next((kind for kind, expected in ARCHIVE_FILES.items() if names == expected), None)
    _require(kind is not None)
    entry, files = dict(archive_kind=kind, request=None), {}
    for name in sorted(names):
        entry[name[:-5]], files[name] = _read_json(folder / name)
    return entry, files


def _meta(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _write(folder, name, raw):
    _require(0 < len(raw) <= MAX_BYTES)
    folder = _directory(folder)
    path = folder / name
    # 'x' refuses existing regular files, links, and foreign collisions.
    with path.open('xb') as handle:
        opened = os.fstat(handle.fileno())
        _regular(opened)
        current = path.lstat()
        _regular(current)
        _require(_identity(opened) == _identity(current))
        _require(handle.write(raw) == len(raw))
    _require(_read_bytes(path) == raw)


def _verify_output(folder, now):
    clock = _clock(now)
    folder = _directory(folder)
    index, _ = _read_json(folder / 'index.json')
    report, raw = _read_json(folder / 'report.json')
    _require(isinstance(index, dict) and set(index) == INDEX_FIELDS
        and type(index['schema_version']) is int and index['schema_version'] == 1
        and index['operation'] == OPERATION)
    for field in ('application_requests', 'network_requests', 'official_source_requests'):
        _require(type(index[field]) is int and index[field] == 0)
    _require(type(index['report_bytes']) is int and index['report_bytes'] == len(raw)
        and isinstance(index['report_sha256'], str) and index['report_sha256'] == _meta(raw)['sha256']
        and isinstance(report, dict) and index['generated_at'] == report['as_of'])
    rows = index['inputs']
    _require(isinstance(rows, list) and 1 <= len(rows) <= MAX_INPUTS)
    directories = [f'input-{sequence:03}' for sequence in range(1, len(rows) + 1)]
    _require({path.name for path in folder.iterdir()} == {'index.json', 'report.json', *directories})
    entries, race_ids, total = [], [], 0
    for directory, row in zip(directories, rows):
        _require(isinstance(row, dict) and set(row) == INPUT_FIELDS and row['directory'] == directory)
        entry, files = _archive(folder / directory)
        total += sum(len(raw) for raw in files.values())
        _require(total <= MAX_TOTAL_BYTES)
        _require(row['archive_kind'] == entry['archive_kind']
            and row['race_id'] == entry['program']['race_id']
            and row['forecast_request_id'] == entry['forecast']['receipt']['request_id'])
        metas = row['files']
        _require(isinstance(metas, dict) and set(metas) == set(files))
        for name, raw in files.items():
            meta = metas[name]
            _require(isinstance(meta, dict) and set(meta) == {'bytes', 'sha256'}
                and type(meta['bytes']) is int and meta['bytes'] == len(raw)
                and isinstance(meta['sha256'], str) and meta['sha256'] == _meta(raw)['sha256'])
        race_ids.append(row['race_id'])
        entries.append(entry)
    _require(race_ids == sorted(set(race_ids)))
    validate_archived_name_bound_cohort(report, entries, now=clock)
    return index


def verify_output(folder, *, now):
    """Read-only full restore: inventory, strict copied bytes, and report replay."""
    try:
        return _verify_output(folder, now)
    except ERRORS:
        raise ValueError(STOPPED) from None


def run(archive_dirs, output_dir, *, execute=False):
    """Return None without any I/O unless execute; otherwise return verified index."""
    if not execute:
        return None
    try:
        _require(isinstance(archive_dirs, (list, tuple)) and 1 <= len(archive_dirs) <= MAX_INPUTS)
        audit = _clock(utc_now())
        archives, total = [], 0
        for folder in archive_dirs:
            entry, files = _archive(folder)
            total += sum(len(raw) for raw in files.values())
            _require(total <= MAX_TOTAL_BYTES)
            archives.append((entry, files))
        # Every complete input, including exclusions, replays before any output.
        report = build_archived_name_bound_cohort([entry for entry, _ in archives], now=audit)
        archives.sort(key=lambda archive: archive[0]['program']['race_id'])
        index = dict(schema_version=1, operation=OPERATION, generated_at=report['as_of'],
            application_requests=0, network_requests=0, official_source_requests=0,
            report_bytes=len(canonical(report)), report_sha256=_meta(canonical(report))['sha256'], inputs=[])
        folder = _directory(output_dir, new=True)
        folder.mkdir(exist_ok=False)
        _directory(folder)
        for sequence, (entry, files) in enumerate(archives, 1):
            directory = f'input-{sequence:03}'
            child = _directory(folder / directory, new=True)
            child.mkdir(exist_ok=False)
            for name, raw in sorted(files.items()):
                _write(child, name, raw)
            index['inputs'].append(dict(directory=directory, race_id=entry['program']['race_id'],
                forecast_request_id=entry['forecast']['receipt']['request_id'],
                archive_kind=entry['archive_kind'], files={name: _meta(raw) for name, raw in files.items()}))
        _write(folder, 'report.json', canonical(report))
        _write(folder, 'index.json', canonical(index))
        fresh = _clock(utc_now())
        _require(fresh >= audit)
        return verify_output(folder, now=fresh)
    except ERRORS:
        raise ValueError(STOPPED) from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(STOPPED)


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('--archive', action='append', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--execute', action='store_true')
    try:
        args = parser.parse_args(argv)
        index = run(args.archive, args.output_dir, execute=args.execute)
        print(json.dumps(DRY_RUN if index is None else index, sort_keys=True))
        return 0
    except ERRORS:
        print(STOPPED)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
