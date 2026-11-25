"""Supported v1 frozen comparison evaluation with authenticated runtime files.

Use a fresh process and --expected-model-sha256 from the independent published
receipt. This wrapper only evaluates; the original keirin_accuracy_study fit
command remains the legacy producer of a new, separately frozen artifact.
Direct v1 load/evaluate functions are low-level legacy APIs; supported
evaluation uses this verified wrapper.
No original model, driver, race inputs or evaluation output is overwritten.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

from race_ai import keirin_comparison_snapshot as guard


class _PinnedLoader(importlib.abc.Loader):
    """Compile the verified source bytes directly, without accepting .pyc."""
    def __init__(self, path, expected):
        self.path, self.expected = path, expected

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raw = guard._read_regular(self.path, guard.MAX_SOURCE_BYTES)
        guard._need(sha256(raw).hexdigest() == self.expected, 'FROZEN_RUNTIME_SOURCE_CHANGED_BEFORE_IMPORT')
        module.__file__ = str(self.path)
        exec(compile(raw, str(self.path), 'exec', dont_inherit=True), module.__dict__)


class _PinnedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, root, hashes):
        self.files = {name[:-3].replace('/', '.'): (root / name, expected)
                      for name, expected in hashes.items() if not name.endswith('/__init__.py')}

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.files:
            source, expected = self.files[fullname]
            return importlib.util.spec_from_file_location(fullname, source,
                loader=_PinnedLoader(source, expected))
        if fullname.startswith(('scripts.', 'race_ai.')):
            raise guard.ComparisonSnapshotError('FROZEN_UNDECLARED_RUNTIME_IMPORT')
        return None


@contextmanager
def _engine(source_root, receipt):
    expected_root = Path(__file__).resolve().parents[1]
    guard._need(source_root == expected_root, 'FROZEN_RUNTIME_IMPORT_ROOT_MISMATCH')
    hashes = {**receipt['source_files_sha256'], **receipt['runtime_source_files_sha256']}
    finder = _PinnedFinder(source_root, hashes)
    guard._need(not any(name in sys.modules for name in finder.files),
                'FROZEN_RUNTIME_ALREADY_IMPORTED_USE_FRESH_PROCESS')
    package = sys.modules.get('race_ai')
    guard._need(package is not None and Path(package.__file__).resolve() == source_root / 'race_ai/__init__.py',
                'FROZEN_RUNTIME_PACKAGE_IDENTITY_MISMATCH')
    sys.meta_path.insert(0, finder)
    try:
        engine = importlib.import_module('scripts.keirin_accuracy_study')
        for name, (path, _) in finder.files.items():
            if name in sys.modules:
                guard._need(Path(sys.modules[name].__file__).resolve() == path,
                            'FROZEN_RUNTIME_IMPORT_IDENTITY_MISMATCH')
        yield engine
    finally:
        sys.meta_path.remove(finder)


def evaluate(examples_path, root, expected_model_sha256, *, source_root=None, package_version_getter=None):
    """Authenticate every frozen input before importing or invoking the engine."""
    source_root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[1]
    payload, receipt = guard.verify_snapshot(root, expected_model_sha256, source_root,
                                            package_version_getter=package_version_getter)
    root = Path(root)
    examples = guard._read_regular(Path(examples_path), 256 * 1024 * 1024)
    guard._need(sha256(examples).hexdigest() == payload['examples_sha256'], 'FROZEN_EXAMPLES_SHA_MISMATCH')
    guard._need(not (root / 'evaluation.json').exists(), 'FROZEN_EVALUATION_ALREADY_EXISTS')
    with _engine(source_root, receipt) as engine:
        report = engine.evaluate_comparison(Path(examples_path), root)
    return {**report, 'frozen_runtime_verification': receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('evaluate',))
    parser.add_argument('--examples', required=True, type=Path)
    parser.add_argument('--private-root', required=True, type=Path)
    parser.add_argument('--expected-model-sha256', required=True)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.examples, args.private_root, args.expected_model_sha256,
                          source_root=args.source_root)
    except guard.ComparisonSnapshotError as error:
        print(json.dumps({'state': str(error), 'model_refitted': False}))
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
