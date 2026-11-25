"""Authenticate the v1 comparison snapshot before importing prediction code.

The caller supplies the model SHA from an independently retained receipt, such
as prospective-publication.json or retrospective-score.json. A model's own
metadata is never its trust anchor. This module uses only the standard library
and does not import the study engine, inspect race outcomes, or refit anything.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import stat


SCHEMA = 'KEIRIN_FROZEN_RESIDUAL_COMPARISON_V1'
BASE_CONFIGURATION_PATH = 'docs/evidence/keirin-ordered-ticket-20261124/recent-config.json'
SOURCE_FILES = (
    'scripts/keirin_accuracy_study.py', 'scripts/keirin_boosted_choice_study.py',
    'scripts/keirin_ordered_ticket_study.py', 'scripts/keirin_line_event_study.py',
    'race_ai/keirin_archive_study.py', 'race_ai/keirin_joint_finish.py',
)
BOUNDARIES = {'fit_end': '20260731', 'tune_end': '20260930', 'test_end': '20261122'}
ARMS = {
    'saved': ((0, 0, 0), 0.), 'first_two_24': ((24, 24, 0), 1.),
    'first_two_56': ((56, 56, 0), 1.), 'third_56': ((0, 0, 56), 1.),
    'all_24': ((24, 24, 24), 1.), 'all_56': ((56, 56, 56), 1.),
    'all_96': ((96, 96, 96), 1.), 'all_96_half': ((96, 96, 96), .5),
}
# Separately reviewed runtime pins. The v1 model records only SOURCE_FILES;
# its already-published bytes are preserved. A different runtime needs a new
# reviewed guard/receipt, rather than accepting replacement hashes from JSON.
RUNTIME_SOURCE_COMMIT = 'fb8773c82da3879a2148d4764dab18252d8bff97'
RUNTIME_SOURCE_SHA256 = {
    'race_ai/__init__.py': '6d3f14841225bcbaa0618873aaed26ece2fe4bf8583803147b8acc1bb478b773',
    'race_ai/keirin_nationwide_auto_generator.py': 'b30b7940cb054fc3225f109f1f35e70cab034c704e0d701937ded8309b8f5b47',
    'race_ai/keirin_ranking_adjustment.py': '29d01a9c43a7d2c72175f78f016652ad968cde71e6a3ce1a197524d15a123270',
    'race_ai/keirin_small_ticket_budget.py': '8b165ce66785861a15400c4cb234d88fdbb87618962acccca1582aa4212735ec',
    'race_ai/keirin_public_two_source_normalizer.py': 'b1f4adab625c9ee7a8547ba70a41a2b1bd613566c0fee1c38473bf55ddcdcd20',
    'scripts/keirin_fit_ranking_weights.py': 'a98f07ed226151524ef5b2950054d2a7371a1c74161871207a4c3bfbff4922d4',
    'scripts/keirin_line_version_study.py': 'a86b1666d5ab0a11d08cc579694aaf63e9ac826bc6453aade4554782be5a31bc',
    'scripts/keirin_generate_result_unread_analysis.py': '7f362dbbc8e89dae3aae28f8687c14aec3b9d5a7dec442b86cdb5ce5d27f20c9',
    'scripts/keirin_capture_public_two_sources.py': '4f10bf29a2e2275a638848d7f7cda8d64746bf0c5c00bcb80d67c19936b4645a',
    'scripts/keirin_line_history_study.py': 'eba455664a22739fadf8f4f99f8b4938e399600fc6ddae226704ba81345ce25b',
    'scripts/keirin_rider_profile_study.py': '34604b7eaa7bca7228d42bb16b645a96a41a09db17ae3fc0de494c8f5230fed8',
    'scripts/keirin_rider_profile_history.py': '91140b3835cfa67760839774316a3a849580b9bf5a62a9da2183646c44edd4b8',
    'scripts/keirin_small_ticket_study.py': '3b0327acd1ff593a91593c38a49eedb4b02bb63b34383a109f37062799ef4c0d',
}
PACKAGE_VERSIONS = {'numpy': '2.2.6', 'scipy': '1.17.0', 'lightgbm': '4.6.0'}
MAX_MODEL_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_STAGE_BYTES = 32 * 1024 * 1024


class ComparisonSnapshotError(ValueError):
    """Public errors contain fixed codes, never private model content."""


def _need(condition, code):
    if not condition:
        raise ComparisonSnapshotError(code)


def _digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _private(root):
    root = Path(root)
    _need(root.is_absolute() and root.is_dir() and not root.is_symlink()
          and root.resolve() == root and stat.S_IMODE(root.stat().st_mode) == 0o700,
          'FROZEN_PRIVATE_ROOT_INVALID')
    _need(not any((parent / '.git').exists() for parent in (root, *root.parents)),
          'FROZEN_PRIVATE_ROOT_INSIDE_GIT')
    return root


def _read_regular(path, limit):
    """Bounded file read; no symlink or changing inode is accepted."""
    path = Path(path)
    try:
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode), 'FROZEN_FILE_NOT_REGULAR')
        _need(0 < info.st_size <= limit, 'FROZEN_FILE_SIZE_INVALID')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            _need((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) ==
                  (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns),
                  'FROZEN_FILE_CHANGED_DURING_READ')
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        _need(len(raw) == info.st_size and
              (after.st_size, after.st_mtime_ns) == (info.st_size, info.st_mtime_ns),
              'FROZEN_FILE_CHANGED_DURING_READ')
        return raw
    except OSError:
        raise ComparisonSnapshotError('FROZEN_FILE_UNAVAILABLE') from None


def _source(source_root, relative):
    path = source_root / relative
    _need(path.resolve() == path, 'FROZEN_SOURCE_SYMLINK_REJECTED')
    return _read_regular(path, MAX_SOURCE_BYTES)


def _json(raw, code):
    def distinct(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError
            result[name] = value
        return result

    def reject_constant(_):
        raise ValueError

    try:
        return json.loads(raw, object_pairs_hook=distinct, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ComparisonSnapshotError(code) from None


def _literals(raw, names, code):
    """Extract fixed module metadata without importing or evaluating code."""
    try:
        tree = ast.parse(raw)
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        if target.id in found:
                            raise ValueError
                        found[target.id] = ast.literal_eval(node.value)
        _need(set(found) == set(names), code)
        return found
    except (ValueError, TypeError, SyntaxError, RecursionError):
        raise ComparisonSnapshotError(code) from None


def verify_snapshot(root, expected_model_sha256, source_root, *, package_version_getter=None):
    """Verify bytes/metadata and return (private payload, aggregate receipt).

    expected_model_sha256 must come from outside model.json. The optional
    version getter permits isolated tests; production defaults to installed
    package metadata and never imports those packages during verification.
    """
    root = _private(root)
    _need(_digest(expected_model_sha256), 'FROZEN_EXPECTED_MODEL_SHA_REQUIRED')
    model_raw = _read_regular(root / 'model.json', MAX_MODEL_BYTES)
    # Authenticate FIRST, before JSON parsing or any stage/source inspection.
    _need(sha256(model_raw).hexdigest() == expected_model_sha256, 'FROZEN_MODEL_SHA_MISMATCH')
    payload = _json(model_raw, 'FROZEN_MODEL_JSON_INVALID')
    _need(type(payload) is dict and payload.get('schema') == SCHEMA, 'FROZEN_MODEL_SCHEMA_INVALID')
    source_root = Path(source_root)
    _need(source_root.is_absolute() and source_root.is_dir() and source_root.resolve() == source_root,
          'FROZEN_SOURCE_ROOT_INVALID')
    pinned = payload.get('source_files_sha256')
    _need(type(pinned) is dict and set(pinned) == set(SOURCE_FILES)
          and all(_digest(value) for value in pinned.values()), 'FROZEN_SOURCE_LIST_INVALID')
    sources = {}
    for name in SOURCE_FILES:
        sources[name] = _source(source_root, name)
        _need(sha256(sources[name]).hexdigest() == pinned[name], 'FROZEN_SOURCE_SHA_MISMATCH')
    for name, expected in RUNTIME_SOURCE_SHA256.items():
        _need(sha256(_source(source_root, name)).hexdigest() == expected,
              'FROZEN_RUNTIME_SOURCE_SHA_MISMATCH')
    _need(not (source_root / 'scripts/__init__.py').exists(), 'FROZEN_UNDECLARED_PACKAGE_INITIALIZER')
    metadata = _literals(sources[SOURCE_FILES[0]],
        ('BASE', 'TRAIN_END', 'TUNE_END', 'TEST_END', 'SCHEMA'), 'FROZEN_DRIVER_METADATA_MISMATCH')
    _need(metadata == {'BASE': BASE_CONFIGURATION_PATH, 'TRAIN_END': BOUNDARIES['fit_end'],
          'TUNE_END': BOUNDARIES['tune_end'], 'TEST_END': BOUNDARIES['test_end'], 'SCHEMA': SCHEMA},
          'FROZEN_DRIVER_METADATA_MISMATCH')
    _need(all(payload.get(key) == expected for key, expected in BOUNDARIES.items()),
          'FROZEN_BOUNDARY_MISMATCH')
    arms = _literals(sources[SOURCE_FILES[1]], ('ARMS',), 'FROZEN_ARM_SEMANTICS_MISMATCH')['ARMS']
    _need(arms == ARMS, 'FROZEN_ARM_SEMANTICS_MISMATCH')
    _need(type(payload.get('selected_arm')) is str and payload['selected_arm'] in ARMS,
          'FROZEN_SELECTED_ARM_INVALID')
    base_raw = _source(source_root, BASE_CONFIGURATION_PATH)
    _need(_digest(payload.get('base_configuration_sha256')) and
          sha256(base_raw).hexdigest() == payload['base_configuration_sha256'],
          'FROZEN_BASE_CONFIGURATION_SHA_MISMATCH')
    _need(_json(base_raw, 'FROZEN_BASE_CONFIGURATION_JSON_INVALID') == payload.get('base_configuration'),
          'FROZEN_BASE_CONFIGURATION_PAYLOAD_MISMATCH')
    stages = payload.get('stage_sha256')
    _need(type(stages) is list and len(stages) == 3 and all(_digest(value) for value in stages),
          'FROZEN_STAGE_COUNT_INVALID')
    for number, expected in enumerate(stages):
        _need(sha256(_read_regular(root / f'stage-{number}.txt', MAX_STAGE_BYTES)).hexdigest() == expected,
              'FROZEN_STAGE_SHA_MISMATCH')
    getter = version if package_version_getter is None else package_version_getter
    try:
        packages = {name: getter(name) for name in PACKAGE_VERSIONS}
    except (PackageNotFoundError, KeyError, ValueError, TypeError):
        raise ComparisonSnapshotError('FROZEN_PACKAGE_VERSION_UNAVAILABLE') from None
    _need(packages == PACKAGE_VERSIONS, 'FROZEN_PACKAGE_VERSION_MISMATCH')
    _need(_digest(payload.get('examples_sha256')), 'FROZEN_EXAMPLES_SHA_INVALID')
    receipt = {
        'schema': 'KEIRIN_FROZEN_RUNTIME_VERIFICATION_V1', 'state': 'FROZEN_RUNTIME_VERIFIED',
        'verified_at': datetime.now(timezone.utc).isoformat(),
        'frozen_model_sha256': expected_model_sha256, 'source_files_verified': len(SOURCE_FILES),
        'runtime_files_verified': len(RUNTIME_SOURCE_SHA256), 'stages_verified': 3,
        'source_files_sha256': dict(pinned), 'runtime_source_files_sha256': dict(RUNTIME_SOURCE_SHA256),
        'runtime_source_commit': RUNTIME_SOURCE_COMMIT, 'package_versions': packages,
        'base_configuration_sha256': payload['base_configuration_sha256'],
        'stage_sha256': list(stages), 'selected_arm': payload['selected_arm'], **BOUNDARIES,
        'race_results_read': False, 'model_refitted': False,
    }
    return payload, receipt
