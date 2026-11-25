"""Frozen-runtime checks use invented artifacts and never train a model."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCES = (
    'scripts/keirin_accuracy_study.py', 'scripts/keirin_boosted_choice_study.py',
    'scripts/keirin_ordered_ticket_study.py', 'scripts/keirin_line_event_study.py',
    'race_ai/keirin_archive_study.py', 'race_ai/keirin_joint_finish.py',
)
RUNTIME = (
    'race_ai/__init__.py', 'race_ai/keirin_nationwide_auto_generator.py',
    'race_ai/keirin_ranking_adjustment.py', 'race_ai/keirin_small_ticket_budget.py',
    'race_ai/keirin_public_two_source_normalizer.py', 'scripts/keirin_fit_ranking_weights.py',
    'scripts/keirin_line_version_study.py', 'scripts/keirin_generate_result_unread_analysis.py',
    'scripts/keirin_capture_public_two_sources.py', 'scripts/keirin_line_history_study.py',
    'scripts/keirin_rider_profile_study.py', 'scripts/keirin_rider_profile_history.py',
    'scripts/keirin_small_ticket_study.py',
)
BASE = 'docs/evidence/keirin-ordered-ticket-20261124/recent-config.json'
ARMS = {
    'saved': ((0, 0, 0), 0.), 'first_two_24': ((24, 24, 0), 1.),
    'first_two_56': ((56, 56, 0), 1.), 'third_56': ((0, 0, 56), 1.),
    'all_24': ((24, 24, 24), 1.), 'all_56': ((56, 56, 56), 1.),
    'all_96': ((96, 96, 96), 1.), 'all_96_half': ((96, 96, 96), .5),
}
PACKAGES = {'numpy': '2.2.6', 'scipy': '1.17.0', 'lightgbm': '4.6.0'}


class ComparisonSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_comparison_snapshot'),
                             'The separate frozen-runtime verifier is missing.')
        self.guard = importlib.import_module('race_ai.keirin_comparison_snapshot')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.top = Path(self.temp.name)
        self.root, self.source = self.top / 'private', self.top / 'source'
        self.root.mkdir(mode=0o700)
        self.source.mkdir()
        files = {name: b'# Invented inert dependency.\n' for name in SOURCES + RUNTIME}
        files[SOURCES[0]] = (
            "BASE = " + repr(BASE) + "\nTRAIN_END = '20260731'\nTUNE_END = '20260930'\n"
            "TEST_END = '20261122'\nSCHEMA = 'KEIRIN_FROZEN_RESIDUAL_COMPARISON_V1'\n"
            "raise AssertionError('VERIFIER_MUST_NOT_EXECUTE_ENGINE')\n").encode()
        files[SOURCES[1]] = ('ARMS = ' + repr(ARMS) + '\n').encode()
        for name, raw in files.items():
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.runtime = {name: sha256(files[name]).hexdigest() for name in RUNTIME}
        self.addCleanup(patch.stopall)
        patch.object(self.guard, 'RUNTIME_SOURCE_SHA256', self.runtime).start()
        baseline = {'baseline': [{'coefficient': .25}], 'method': 'saved_fixture'}
        base_path = self.source / BASE
        base_path.parent.mkdir(parents=True)
        base_path.write_text(json.dumps(baseline) + '\n')
        stages = []
        for number in range(3):
            raw = f'Invented stage {number}.\n'.encode()
            (self.root / f'stage-{number}.txt').write_bytes(raw)
            stages.append(sha256(raw).hexdigest())
        self.payload = {
            'schema': 'KEIRIN_FROZEN_RESIDUAL_COMPARISON_V1',
            'model_id': 'keirin-comparison-B-residual', 'frozen_at': '2026-11-25T12:54:00+00:00',
            'examples_sha256': sha256(b'invented examples').hexdigest(),
            'base_configuration': baseline,
            'base_configuration_sha256': sha256(base_path.read_bytes()).hexdigest(),
            'stage_sha256': stages, 'selected_arm': 'all_96',
            'fit_end': '20260731', 'tune_end': '20260930', 'test_end': '20261122',
            'tail_coefficients': [.1, .2],
            'source_files_sha256': {name: sha256(files[name]).hexdigest() for name in SOURCES},
        }
        self.expected = self.write_payload()

    def write_payload(self):
        raw = json.dumps(self.payload, sort_keys=True).encode()
        (self.root / 'model.json').write_bytes(raw)
        return sha256(raw).hexdigest()

    def verify(self, expected=None, **kwargs):
        return self.guard.verify_snapshot(self.root, expected or self.expected, self.source,
            package_version_getter=kwargs.pop('package_version_getter', PACKAGES.__getitem__), **kwargs)

    def change_source(self, name, before, after, *, repin=False):
        target = self.source / name
        target.write_text(target.read_text().replace(before, after))
        if repin:
            self.payload['source_files_sha256'][name] = sha256(target.read_bytes()).hexdigest()
            self.expected = self.write_payload()

    def test_authenticates_complete_snapshot_without_importing_or_changing_it(self):
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        payload, receipt = self.verify()
        self.assertEqual(payload, self.payload)
        self.assertEqual(receipt['frozen_model_sha256'], self.expected)
        self.assertEqual(receipt['selected_arm'], 'all_96')
        self.assertEqual(receipt['source_files_verified'], 6)
        self.assertEqual(receipt['runtime_files_verified'], 13)
        self.assertEqual(receipt['stages_verified'], 3)
        self.assertEqual(receipt['package_versions'], PACKAGES)
        self.assertEqual({path: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_model_digest_is_checked_before_json_or_other_files(self):
        (self.root / 'model.json').write_bytes(b'not json and not the trusted model')
        (self.root / 'stage-0.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_SHA_MISMATCH'):
            self.verify()

    def test_changed_coefficients_and_metadata_cannot_self_attest(self):
        for key, value in (('tail_coefficients', [99., 99.]), ('selected_arm', 'saved'),
                           ('fit_end', '20261101')):
            with self.subTest(key=key):
                original = deepcopy(self.payload)
                self.payload[key] = value
                self.write_payload()
                with self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_SHA_MISMATCH'):
                    self.verify()
                self.payload = original
                self.write_payload()

    def test_each_frozen_source_must_match_its_exact_bytes(self):
        target = self.source / SOURCES[2]
        target.write_bytes(target.read_bytes() + b'# changed feature calculation\n')
        with self.assertRaisesRegex(ValueError, 'FROZEN_SOURCE_SHA_MISMATCH'):
            self.verify()

    def test_source_allowlist_rejects_an_extra_or_missing_path(self):
        for mode in ('extra', 'missing'):
            original = deepcopy(self.payload)
            if mode == 'extra':
                self.payload['source_files_sha256']['../../untrusted.py'] = '0' * 64
            else:
                self.payload['source_files_sha256'].pop(SOURCES[-1])
            expected = self.write_payload()
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'FROZEN_SOURCE_LIST_INVALID'):
                self.verify(expected)
            self.payload = original

    def test_changed_transitive_feature_code_is_also_rejected(self):
        (self.source / 'scripts/keirin_small_ticket_study.py').write_bytes(b'raise RuntimeError("MUTATED")\n')
        with self.assertRaisesRegex(ValueError, 'FROZEN_RUNTIME_SOURCE_SHA_MISMATCH'):
            self.verify()

    def test_stage_mutation_and_wrong_stage_count_are_rejected(self):
        stage = self.root / 'stage-1.txt'
        old = stage.read_bytes()
        stage.write_bytes(old + b'changed')
        with self.assertRaisesRegex(ValueError, 'FROZEN_STAGE_SHA_MISMATCH'):
            self.verify()
        stage.write_bytes(old)
        self.payload['stage_sha256'] = self.payload['stage_sha256'][:2]
        with self.assertRaisesRegex(ValueError, 'FROZEN_STAGE_COUNT_INVALID'):
            self.verify(self.write_payload())

    def test_real_base_configuration_bytes_and_embedded_parameters_both_match(self):
        base = self.source / BASE
        old = base.read_bytes()
        base.write_bytes(old + b' ')
        with self.assertRaisesRegex(ValueError, 'FROZEN_BASE_CONFIGURATION_SHA_MISMATCH'):
            self.verify()
        base.write_bytes(old)
        self.payload['base_configuration']['baseline'][0]['coefficient'] = 42
        with self.assertRaisesRegex(ValueError, 'FROZEN_BASE_CONFIGURATION_PAYLOAD_MISMATCH'):
            self.verify(self.write_payload())

    def test_saved_boundaries_match_frozen_driver_constants(self):
        self.payload['test_end'] = '20261123'
        with self.assertRaisesRegex(ValueError, 'FROZEN_BOUNDARY_MISMATCH'):
            self.verify(self.write_payload())

    def test_repinning_changed_cutoff_code_cannot_change_this_v1_protocol(self):
        self.change_source(SOURCES[0], "TEST_END = '20261122'", "TEST_END = '20261123'", repin=True)
        self.payload['test_end'] = '20261123'
        with self.assertRaisesRegex(ValueError, 'FROZEN_DRIVER_METADATA_MISMATCH'):
            self.verify(self.write_payload())

    def test_arm_must_be_saved_and_its_iteration_semantics_cannot_change(self):
        self.payload['selected_arm'] = 'invented_arm'
        with self.assertRaisesRegex(ValueError, 'FROZEN_SELECTED_ARM_INVALID'):
            self.verify(self.write_payload())
        self.payload['selected_arm'] = 'all_96'
        self.change_source(SOURCES[1], '(96, 96, 96)', '(95, 95, 95)', repin=True)
        with self.assertRaisesRegex(ValueError, 'FROZEN_ARM_SEMANTICS_MISMATCH'):
            self.verify()

    def test_source_code_is_parsed_not_executed_and_base_path_is_fixed(self):
        self.change_source(SOURCES[0], repr(BASE), repr('../../outside-config.json'), repin=True)
        with self.assertRaisesRegex(ValueError, 'FROZEN_DRIVER_METADATA_MISMATCH'):
            self.verify()

    def test_wrong_installed_package_version_fails_before_engine_import(self):
        versions = {**PACKAGES, 'lightgbm': '0.0.0'}
        with self.assertRaisesRegex(ValueError, 'FROZEN_PACKAGE_VERSION_MISMATCH'):
            self.verify(package_version_getter=versions.__getitem__)

    def test_private_root_must_be_0700_outside_git_and_regular_files(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'FROZEN_PRIVATE_ROOT_INVALID'):
            self.verify()
        self.root.chmod(0o700)
        (self.top / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'FROZEN_PRIVATE_ROOT_INSIDE_GIT'):
            self.verify()
        (self.top / '.git').rmdir()
        stage = self.root / 'stage-0.txt'
        replacement = self.top / 'linked.txt'
        replacement.write_bytes(stage.read_bytes())
        stage.unlink()
        stage.symlink_to(replacement)
        with self.assertRaisesRegex(ValueError, 'FROZEN_FILE_NOT_REGULAR'):
            self.verify()

    def test_duplicate_json_keys_and_nonfinite_constants_are_invalid(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"coefficient":NaN}'):
            (self.root / 'model.json').write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_JSON_INVALID'):
                self.verify(sha256(raw).hexdigest())

    def test_supported_cli_rejects_changed_model_before_any_engine_import(self):
        (self.root / 'model.json').write_bytes(b'changed frozen bytes')
        code = '''
import sys
from scripts.keirin_frozen_accuracy_study import main
status = main(sys.argv[1:])
assert 'scripts.keirin_accuracy_study' not in sys.modules
assert 'lightgbm' not in sys.modules
assert 'numpy' not in sys.modules
raise SystemExit(status)
'''
        done = subprocess.run([sys.executable, '-B', '-c', code, 'evaluate',
            '--private-root', str(self.root), '--examples', str(self.root / 'not-read.json.gz'),
            '--expected-model-sha256', self.expected, '--source-root', str(self.source)],
            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=15)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn('FROZEN_MODEL_SHA_MISMATCH', done.stdout)
        self.assertNotIn('changed frozen bytes', done.stdout + done.stderr)

    def test_wrapper_dispatches_only_after_verifying_bytes_and_examples(self):
        engine = self.source / SOURCES[0]
        engine.write_text(engine.read_text().replace(
            "raise AssertionError('VERIFIER_MUST_NOT_EXECUTE_ENGINE')", """
def evaluate_comparison(examples_path, root):
    (root / 'engine-called.txt').write_text('verified execution')
    return {'fixture_engine': 'VERIFIED_BYTES'}
"""))
        self.payload['source_files_sha256'][SOURCES[0]] = sha256(engine.read_bytes()).hexdigest()
        self.expected = self.write_payload()
        examples = self.root / 'examples.json.gz'
        examples.write_bytes(b'invented examples')
        repository = Path(__file__).resolve().parents[1]
        for name in ('race_ai/keirin_comparison_snapshot.py', 'scripts/keirin_frozen_accuracy_study.py'):
            shutil.copyfile(repository / name, self.source / name)
        code = '''
from hashlib import sha256
from pathlib import Path
import sys
from race_ai import keirin_comparison_snapshot as guard
from scripts.keirin_frozen_accuracy_study import evaluate
source = Path(sys.argv[1])
guard.RUNTIME_SOURCE_SHA256 = {name: sha256((source/name).read_bytes()).hexdigest()
                               for name in guard.RUNTIME_SOURCE_SHA256}
report = evaluate(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], source_root=source)
assert report['fixture_engine'] == 'VERIFIED_BYTES'
assert report['frozen_runtime_verification']['frozen_model_sha256'] == sys.argv[4]
'''
        args = [sys.executable, '-B', '-c', code, str(self.source), str(examples),
                str(self.root), self.expected]
        done = subprocess.run(args, cwd=self.source,
                              text=True, capture_output=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        marker = self.root / 'engine-called.txt'
        self.assertEqual(marker.read_text(), 'verified execution')
        marker.unlink()
        examples.write_bytes(b'changed untrusted evaluation data')
        done = subprocess.run(args, cwd=self.source,
                              text=True, capture_output=True, timeout=15)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('FROZEN_EXAMPLES_SHA_MISMATCH', done.stderr)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
