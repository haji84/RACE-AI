"""Local synthetic archive copies: no retained operational archives are used."""
import contextlib
import copy
from datetime import timedelta
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from tests.test_name_bound_archive import archive_fixture, inventory
from web import race_contract as facts


INDEX_FIELDS = set('schema_version operation generated_at application_requests network_requests official_source_requests report_bytes report_sha256 inputs'.split())
ROW_FIELDS = {'directory', 'race_id', 'forecast_request_id', 'archive_kind', 'files'}
OLD_FILES = {'manifest.json', 'program.json', 'forecast.json', 'result.json', 'evaluation.json'}
NEW_FILES = OLD_FILES | {'request.json'}
STOPPED = 'NAME_BOUND_ARCHIVE_STOPPED'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def original_files(entry):
    names = NEW_FILES if entry['archive_kind'] == 'RESULT_PUBLICATION' else OLD_FILES
    return {name: facts.canonical(entry[name[:-5]]) for name in names}


def put_archive(folder, entry):
    folder.mkdir()
    for name, raw in original_files(entry).items():
        (folder / name).write_bytes(raw)
    return folder


def tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def replace_json(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(facts.canonical(value))


class ArchiveCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy, cls.now = archive_fixture()
        cls.publication, _ = archive_fixture(publication=True, race_no=2)

    def setUp(self):
        try:
            self.cli = importlib.import_module('scripts.evaluate_name_bound_archive')
        except ModuleNotFoundError:
            self.fail('exclusive offline archive CLI required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.one = put_archive(self.base / 'legacy', self.legacy)
        self.two = put_archive(self.base / 'publication', self.publication)
        self.output = self.base / 'output'

    def execute(self, archives=None, output=None, clocks=None):
        with patch.object(self.cli, 'utc_now', side_effect=clocks or [self.now, self.now + timedelta(seconds=1)]):
            return self.cli.run([self.two, self.one] if archives is None else archives,
                self.output if output is None else output, execute=True)

    def rejects(self, function, *args, **kwargs):
        with self.assertRaises(ValueError) as error:
            function(*args, **kwargs)
        self.assertEqual(str(error.exception), STOPPED)

    def test_dry_run_has_no_clock_filesystem_or_external_work(self):
        with contextlib.ExitStack() as stack:
            for target in ('utc_now',):
                stack.enter_context(patch.object(self.cli, target, side_effect=AssertionError('clock')))
            for target in ('open', 'lstat', 'mkdir', 'iterdir', 'cwd', 'resolve', 'exists'):
                stack.enter_context(patch.object(Path, target, side_effect=AssertionError('filesystem')))
            stack.enter_context(patch('builtins.open', side_effect=AssertionError('filesystem')))
            stack.enter_context(patch.object(os, 'open', side_effect=AssertionError('filesystem')))
            stack.enter_context(patch.object(os, 'getenv', side_effect=AssertionError('credentials')))
            stack.enter_context(patch.object(socket, 'socket', side_effect=AssertionError('network')))
            stack.enter_context(patch.object(urllib.request, 'urlopen', side_effect=AssertionError('network')))
            self.assertIsNone(self.cli.run(object(), object()))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(self.cli.main(['--archive', 'ignored', '--output-dir', 'ignored']), 0)
            self.assertEqual(json.loads(stdout.getvalue()), dict(status='DRY_RUN',
                application_requests=0, network_requests=0, official_source_requests=0))

    def test_two_archive_copy_restore_exact_schema_bytes_and_order(self):
        originals = {self.one: tree(self.one), self.two: tree(self.two)}
        with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
                patch.object(os, 'getenv', side_effect=AssertionError('credentials')):
            index = self.execute()
        self.assertEqual(set(index), INDEX_FIELDS)
        self.assertEqual(index['schema_version'], 1)
        self.assertEqual(index['operation'], 'OFFLINE_NAME_BOUND_ARCHIVE_COHORT')
        self.assertNotIn('status', index)
        for name in ('application_requests', 'network_requests', 'official_source_requests'):
            self.assertIs(type(index[name]), int)
            self.assertEqual(index[name], 0)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'input-001', 'input-002', 'index.json', 'report.json'})
        expected = {'input-001/' + name: raw for name, raw in originals[self.one].items()}
        expected.update({'input-002/' + name: raw for name, raw in originals[self.two].items()})
        actual = tree(self.output)
        self.assertEqual(len(actual), 13)
        self.assertEqual({name: raw for name, raw in actual.items() if name.startswith('input-')}, expected)
        for sequence, entry in enumerate((self.legacy, self.publication), 1):
            row = index['inputs'][sequence - 1]
            self.assertEqual(set(row), ROW_FIELDS)
            self.assertEqual(row['directory'], f'input-{sequence:03}')
            self.assertEqual(row['race_id'], f'20261015-18-{sequence:02}')
            self.assertEqual(row['forecast_request_id'], entry['forecast']['receipt']['request_id'])
            self.assertEqual(row['archive_kind'], entry['archive_kind'])
            self.assertEqual(row['files'], {name: dict(bytes=len(raw), sha256=digest(raw))
                for name, raw in original_files(entry).items()})
        report_raw = actual['report.json']
        report = json.loads(report_raw)
        self.assertEqual(index['report_bytes'], len(report_raw))
        self.assertEqual(index['report_sha256'], digest(report_raw))
        self.assertEqual(index['generated_at'], facts.stamp(self.now))
        self.assertEqual(report['as_of'], index['generated_at'])
        self.assertEqual((report['input_count'], report['race_count'], report['day_count']), (2, 2, 1))
        self.assertEqual([row['original_evaluation_as_of'] for row in report['observations']],
            [self.legacy['evaluation']['as_of'], self.publication['evaluation']['as_of']])
        self.assertEqual(json.loads(actual['input-002/manifest.json'])['official_source_requests'], 1)
        self.assertNotIn(str(self.base), actual['index.json'].decode())
        self.assertEqual(self.cli.verify_output(self.output, now=self.now + timedelta(days=1)), index)
        second = self.base / 'second'
        self.assertEqual(self.execute([self.one, self.two], second), index)
        self.assertEqual(tree(second), actual)
        for source, before in originals.items():
            self.assertEqual(tree(source), before)

    def test_all_invalid_inputs_fail_before_output_creation(self):
        mutations = [
            lambda p: (p / 'unexpected.json').write_bytes(b'{}'),
            lambda p: (p / 'result.json').unlink(),
            lambda p: (p / 'program.json').write_bytes(b'{' ),
            lambda p: (p / 'program.json').write_bytes(b' ' + (p / 'program.json').read_bytes()),
            lambda p: (p / 'program.json').write_bytes(b'{"a":1,"a":1}'),
            lambda p: (p / 'program.json').write_bytes(b'{}' + b' ' * 255999),
            lambda p: replace_json(p / 'manifest.json', lambda v: v.update(status='STOPPED')),
            lambda p: replace_json(p / 'manifest.json', lambda v: v.update(reads_used=True)),
            lambda p: replace_json(p / 'evaluation.json', lambda v: v.update(status='PENDING')),
        ]
        for i, mutation in enumerate(mutations):
            with self.subTest(i=i):
                bad = put_archive(self.base / f'bad-{i}', self.publication)
                mutation(bad)
                before = tree(bad)
                output = self.base / f'rejected-{i}'
                self.rejects(self.execute, [self.one, bad], output)
                self.assertFalse(output.exists())
                self.assertEqual(tree(bad), before)
        for values in ([], [self.one] * 25, [self.one, self.one]):
            self.rejects(self.execute, values)
            self.assertFalse(self.output.exists())

    def test_rehashed_original_report_tampering_is_not_repaired(self):
        bad = copy.deepcopy(self.publication)
        bad['evaluation']['models'][1]['log_loss'] += 0.1
        inventory(bad)
        path = put_archive(self.base / 'rehashed', bad)
        before = tree(path)
        self.rejects(self.execute, [self.one, path])
        self.assertFalse(self.output.exists())
        self.assertEqual(tree(path), before)

    def test_exact_perfile_ceiling_and_bounded_read_growth(self):
        entry = copy.deepcopy(self.legacy)
        entry['program']['padding'] = ''
        entry['program']['padding'] = 'x' * (256000 - len(facts.canonical(entry['program'])))
        inventory(entry)
        path = put_archive(self.base / 'maximum', entry)
        self.assertEqual((path / 'program.json').stat().st_size, 256000)
        self.assertEqual(self.execute([path])['inputs'][0]['files']['program.json']['bytes'], 256000)
        entry['program']['padding'] += 'x'
        inventory(entry)
        too_big = put_archive(self.base / 'overmaximum', entry)
        rejected = self.base / 'overmaximum-output'
        self.rejects(self.execute, [too_big], rejected)
        self.assertFalse(rejected.exists())
        # The read bound still applies if a file grows after initial lstat.
        real_open = Path.open
        target = self.one / 'program.json'
        class GrowingFile:
            def __init__(self, handle):
                self.handle = handle
            def __getattr__(self, key):
                return getattr(self.handle, key)
            def __enter__(self):
                self.handle.__enter__()
                return self
            def __exit__(self, *args):
                return self.handle.__exit__(*args)
            def read(self, limit):
                self_test.assertEqual(limit, 256001)
                return b'x' * limit
        self_test = self
        def opening(file, mode='r', *args, **kwargs):
            handle = real_open(file, mode, *args, **kwargs)
            return GrowingFile(handle) if file == target and mode == 'rb' else handle
        with patch.object(Path, 'open', opening):
            self.rejects(self.execute, [self.one], self.base / 'growing-output')
        self.assertFalse((self.base / 'growing-output').exists())

    def test_output_must_be_new_with_existing_regular_parents(self):
        foreign = self.base / 'foreign'
        foreign.mkdir()
        (foreign / 'keep').write_bytes(b'foreign')
        self.rejects(self.execute, output=foreign)
        self.assertEqual(tree(foreign), {'keep': b'foreign'})
        file = self.base / 'file'
        file.write_bytes(b'foreign')
        for path in (file, file / 'output', self.base / 'absent' / 'output'):
            self.rejects(self.execute, output=path)
        self.assertEqual(file.read_bytes(), b'foreign')
        self.assertFalse((self.base / 'absent').exists())

    def test_input_file_and_raw_ancestor_links_reject(self):
        link = self.base / 'link'
        originals = {self.one: tree(self.one), self.two: tree(self.two)}
        try:
            link.symlink_to(self.one, target_is_directory=True)
        except OSError:
            # Windows without symlink privilege still exercises all rejection
            # behavior against a metadata backend, with real untouched files.
            link.mkdir()
            linked_file = put_archive(self.base / 'file-link', self.legacy)
            dangling = self.base / 'dangling'
            dangling.mkdir()
            real_lstat = Path.lstat
            def symlink(path, *args, **kwargs):
                value = real_lstat(path, *args, **kwargs)
                if path in {link, linked_file / 'result.json', dangling}:
                    class Link:
                        st_mode = stat.S_IFLNK | 0o777
                        st_file_attributes = 0
                        def __getattr__(self, key):
                            return getattr(value, key)
                    return Link()
                return value
            with patch.object(Path, 'lstat', symlink):
                self.rejects(self.execute, [link])
                self.rejects(self.execute, [link / '..' / 'legacy'])
                self.rejects(self.execute, [self.one], output=link / '..' / 'linked-output')
                self.rejects(self.execute, [linked_file])
                self.rejects(self.execute, [self.one], output=dangling)
        else:
            self.rejects(self.execute, [link])
            self.rejects(self.execute, [link / '..' / 'legacy'])
            self.rejects(self.execute, output=link / '..' / 'linked-output')
            linked_file = put_archive(self.base / 'file-link', self.legacy)
            (linked_file / 'result.json').unlink()
            (linked_file / 'result.json').symlink_to(self.one / 'result.json')
            self.rejects(self.execute, [linked_file])
            dangling = self.base / 'dangling'
            dangling.symlink_to(self.base / 'missing', target_is_directory=True)
            self.rejects(self.execute, output=dangling)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.base / 'linked-output').exists())
        for source, before in originals.items():
            self.assertEqual(tree(source), before)

    def test_windows_reparse_ancestor_is_checked_before_dotdot(self):
        # lstat attributes model a junction without subprocess/privileged creation.
        real_lstat = Path.lstat
        def reparse(path, *args, **kwargs):
            value = real_lstat(path, *args, **kwargs)
            if path == self.one:
                class Junction:
                    st_file_attributes = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)
                    def __getattr__(self, key):
                        return getattr(value, key)
                return Junction()
            return value
        with patch.object(Path, 'lstat', reparse):
            self.rejects(self.execute, [self.one / '..' / 'publication'])
            self.rejects(self.execute, [self.two], output=self.one / '..' / 'output')
        self.assertFalse(self.output.exists())

    def test_restore_checks_index_types_bindings_and_inventory(self):
        self.execute()
        saved = (self.output / 'index.json').read_bytes()
        changes = [lambda v: v.update(schema_version=True), lambda v: v.update(operation='other'),
            lambda v: v.update(application_requests=False), lambda v: v.update(network_requests=1),
            lambda v: v.update(official_source_requests=1), lambda v: v.update(report_bytes=True),
            lambda v: v.update(report_sha256='0' * 64), lambda v: v.update(generated_at=facts.stamp(self.now + timedelta(seconds=1))),
            lambda v: v.update(extra=0), lambda v: v.update(inputs=[]),
            lambda v: v['inputs'].reverse(), lambda v: v['inputs'][0].update(directory='../legacy'),
            lambda v: v['inputs'][0].update(race_id='20261015-18-02'),
            lambda v: v['inputs'][0].update(forecast_request_id='9999-1'),
            lambda v: v['inputs'][0].update(archive_kind='RESULT_PUBLICATION'),
            lambda v: v['inputs'][0]['files']['program.json'].update(bytes=True),
            lambda v: v['inputs'][0]['files']['program.json'].update(sha256='0' * 64),
            lambda v: v['inputs'][0]['files'].update(extra={}),
            lambda v: v['inputs'][0].update(extra=0),
        ]
        for i, change in enumerate(changes):
            with self.subTest(i=i):
                (self.output / 'index.json').write_bytes(saved)
                replace_json(self.output / 'index.json', change)
                before = tree(self.output)
                self.rejects(self.cli.verify_output, self.output, now=self.now + timedelta(seconds=2))
                self.assertEqual(tree(self.output), before)
        (self.output / 'index.json').write_bytes(saved)
        self.assertEqual(self.cli.verify_output(self.output, now=self.now)['inputs'][0]['directory'], 'input-001')

    def test_restore_rejects_full_tree_and_rehashed_report_tampering(self):
        self.execute()
        saved_report = (self.output / 'report.json').read_bytes()
        saved_index = (self.output / 'index.json').read_bytes()
        for name in ('extra.json', 'input-001/extra.json'):
            path = self.output / name
            path.write_bytes(b'{}')
            self.rejects(self.cli.verify_output, self.output, now=self.now)
            path.unlink()
        (self.output / 'extra-directory').mkdir()
        self.rejects(self.cli.verify_output, self.output, now=self.now)

        (self.output / 'extra-directory').rmdir()
        for change in (lambda v: v.update(race_count=3),
                lambda v: v['models'][1].update(mean_log_loss=0.5),
                lambda v: v['observations'][0].update(original_evaluation_as_of=facts.stamp(self.now - timedelta(seconds=1)))):
            report = json.loads(saved_report)
            change(report)
            report['snapshot_id'] = digest(facts.canonical({k: v for k, v in report.items() if k != 'snapshot_id'}))
            raw = facts.canonical(report)
            (self.output / 'report.json').write_bytes(raw)
            index = json.loads(saved_index)
            index.update(report_bytes=len(raw), report_sha256=digest(raw))
            (self.output / 'index.json').write_bytes(facts.canonical(index))
            self.rejects(self.cli.verify_output, self.output, now=self.now)
        (self.output / 'report.json').write_bytes(saved_report)
        (self.output / 'index.json').write_bytes(saved_index)
        path = self.output / 'input-002' / 'evaluation.json'
        replace_json(path, lambda v: v['models'][1].update(log_loss=0.5))
        raw = path.read_bytes()
        manifest_path = path.with_name('manifest.json')
        replace_json(manifest_path, lambda v: v['backups']['evaluation.json'].update(bytes=len(raw), sha256=digest(raw)))
        index = json.loads(saved_index)
        for name in ('evaluation.json', 'manifest.json'):
            raw = path.with_name(name).read_bytes()
            index['inputs'][1]['files'][name] = dict(bytes=len(raw), sha256=digest(raw))
        (self.output / 'index.json').write_bytes(facts.canonical(index))
        self.rejects(self.cli.verify_output, self.output, now=self.now)

    def test_restore_rejects_missing_noncanonical_duplicate_truncated_and_oversize_files(self):
        self.execute()
        for name in ('index.json', 'report.json', 'input-001/manifest.json', 'input-002/request.json'):
            path = self.output / name
            saved = path.read_bytes()
            for raw in (b'{', b' ' + saved, b'{"schema_version":1,"schema_version":1}', b' ' * 256001):
                with self.subTest(name=name, raw_length=len(raw)):
                    path.write_bytes(raw)
                    before = tree(self.output)
                    self.rejects(self.cli.verify_output, self.output, now=self.now)
                    self.assertEqual(tree(self.output), before)
            path.unlink()
            self.rejects(self.cli.verify_output, self.output, now=self.now)
            path.write_bytes(saved)
        self.assertEqual(self.cli.verify_output(self.output, now=self.now)['report_sha256'],
            digest((self.output / 'report.json').read_bytes()))

    def test_restore_reparse_files_directories_and_ancestors_reject(self):
        self.execute()
        real_lstat = Path.lstat
        for target in (self.output, self.output / 'input-001', self.output / 'input-001' / 'program.json',
                self.output / 'index.json', self.output.parent):
            def reparse(path, *args, **kwargs):
                value = real_lstat(path, *args, **kwargs)
                if path == target:
                    class Link:
                        st_file_attributes = 1024
                        def __getattr__(self, key):
                            return getattr(value, key)
                    return Link()
                return value
            with self.subTest(target=target), patch.object(Path, 'lstat', reparse):
                self.rejects(self.cli.verify_output, self.output, now=self.now)

    def test_late_index_close_failure_keeps_complete_tree_but_cli_returns_two(self):
        real_open = Path.open
        target = self.output / 'index.json'
        class LateClose:
            def __init__(self, handle):
                self.handle = handle
            def __getattr__(self, key):
                return getattr(self.handle, key)
            def __enter__(self):
                self.handle.__enter__()
                return self
            def __exit__(self, *args):
                self.handle.__exit__(*args)
                raise OSError('private late close')
        def opening(path, mode='r', *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            return LateClose(handle) if path == target and mode == 'xb' else handle
        stdout = io.StringIO()
        with patch.object(Path, 'open', opening), patch.object(self.cli, 'utc_now', return_value=self.now), \
                contextlib.redirect_stdout(stdout):
            code = self.cli.main(['--archive', str(self.one), '--archive', str(self.two),
                '--output-dir', str(self.output), '--execute'])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), STOPPED + '\n')
        self.assertEqual(len(tree(self.output)), 13)
        # Integrity inventory is restorable evidence, never proof of invocation success.
        self.assertEqual(self.cli.verify_output(self.output, now=self.now)['schema_version'], 1)
        before = tree(self.output)
        self.rejects(self.execute)
        self.assertEqual(tree(self.output), before)
    def test_actual_audit_clock_is_aware_fresh_and_nondecreasing(self):
        for initial, final in ((self.now, self.now - timedelta(microseconds=1)),
                (self.now - timedelta(microseconds=1), self.now), (self.now.replace(tzinfo=None), self.now),
                (self.now, self.now.replace(tzinfo=None))):
            with self.subTest(initial=initial, final=final):
                output = self.base / f'clock-{len(list(self.base.iterdir()))}'
                self.rejects(self.execute, output=output, clocks=[initial, final])
        self.execute()
        self.rejects(self.cli.verify_output, self.output, now=self.now - timedelta(microseconds=1))
        self.rejects(self.cli.verify_output, self.output, now=self.now.replace(tzinfo=None))

    def test_failed_file_open_write_readback_close_never_succeeds_or_retries(self):
        real_open = Path.open
        for fault in ('open', 'write', 'short', 'readback', 'close'):
            with self.subTest(fault=fault):
                output = self.base / fault
                attempts = []
                target = output / 'input-001' / 'evaluation.json'
                class FaultHandle:
                    def __init__(self, handle):
                        self.handle = handle
                    def __getattr__(self, key):
                        return getattr(self.handle, key)
                    def __enter__(self):
                        self.handle.__enter__()
                        return self
                    def __exit__(self, *args):
                        self.handle.__exit__(*args)
                        if fault == 'close':
                            raise OSError('private provider path')
                    def write(self, raw):
                        if fault == 'write':
                            self.handle.write(raw[:5])
                            raise OSError('private provider path')
                        if fault == 'short':
                            return self.handle.write(raw[:5])
                        return self.handle.write(raw)
                    def read(self, *args):
                        if fault == 'readback':
                            raise OSError('private provider path')
                        return self.handle.read(*args)
                def opening(path, mode='r', *args, **kwargs):
                    if path == target:
                        attempts.append(mode)
                        if fault == 'open' and 'x' in mode:
                            raise OSError('private provider path')
                        handle = real_open(path, mode, *args, **kwargs)
                        if ('x' in mode and fault != 'readback') or ('r' in mode and fault == 'readback'):
                            return FaultHandle(handle)
                        return handle
                    return real_open(path, mode, *args, **kwargs)
                stdout = io.StringIO()
                with patch.object(Path, 'open', opening), contextlib.redirect_stdout(stdout):
                    self.rejects(self.execute, output=output)
                self.assertEqual(stdout.getvalue(), '')
                self.assertEqual(sum('x' in mode for mode in attempts), 1)
                before = tree(output)
                self.rejects(self.execute, output=output)
                self.assertEqual(tree(output), before)
                self.assertNotIn('index.json', before)

    def test_final_restore_failure_and_exclusive_child_collision_have_no_success(self):
        with patch.object(self.cli, 'verify_output', side_effect=ValueError('private path')):
            self.rejects(self.execute)
        before = tree(self.output)
        self.rejects(self.execute)
        self.assertEqual(tree(self.output), before)
        collision = self.base / 'collision'
        real_open = Path.open
        def opening(path, mode='r', *args, **kwargs):
            if path == collision / 'input-001' / 'evaluation.json' and 'x' in mode:
                path.write_bytes(b'foreign')
            return real_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', opening):
            self.rejects(self.execute, output=collision)
        self.assertEqual((collision / 'input-001' / 'evaluation.json').read_bytes(), b'foreign')

    def test_cli_error_is_fixed_exit_two_with_no_path_or_success(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.cli, 'run', side_effect=OSError(str(self.base))), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.cli.main(['--archive', str(self.one), '--output-dir', str(self.output), '--execute']), 2)
        self.assertEqual(stdout.getvalue(), STOPPED + '\n')
        self.assertEqual(stderr.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
