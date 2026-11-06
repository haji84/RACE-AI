"""Compact final handoffs retain sealed JSON without recursively packing ZIPs."""
import hashlib
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

try:
    from race_ai.continuity_checkpoint import build_checkpoint
except ImportError:
    build_checkpoint = None

from race_ai.cycle_recovery import authenticated_source_control


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/boat-nationwide-ab-one-shot.yml'


def sealed(value, key):
    body = dict(value)
    body[key] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    # Noncanonical whitespace and Unicode expose any reserialization by the packer.
    return (json.dumps(body, ensure_ascii=False, indent=2) + '\n').encode()


def session(**changes):
    value = dict(schema='RACE_AI_BOUNDED_REPEAT_V1', day_jst='2030-04-01', run_id=7,
                 requests_used=300, completed_round=25, prepared_round=26,
                 lifetime_requests_base=400, lifetime_requests=700,
                 lifetime_completed_rounds_base=55, lifetime_completed_rounds=80,
                 halted_reason=None, source_wait=dict(state='RATE_LIMIT_WAIT',
                 reason='HTTP_RATE_LIMIT', retry_at='2030-04-02T01:00:00Z',
                 http_status=429, attempts=2))
    value.update(changes)
    return sealed(value, 'session_sha256')


def continuity(**changes):
    value = dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1', day_jst='2030-04-01',
                 rows=[], observations=[], receipts=[dict(id=5, digest='sha256:' + 'a' * 64)],
                 excluded_repeats=[], scanned_runs=[6], index_entries=[dict(artifact_id=5)],
                 complete=True, training_proofs={'5': {'proof': '保存済み'}},
                 history_proofs={'5': {'proof': 'original'}},
                 history_context={'observations': [{'version': 3}]})
    value.update(changes)
    return sealed(value, 'state_sha256')


def archive_from(folder, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=compression) as archive:
        for path in sorted(folder.iterdir()):
            archive.write(path, path.name)
    raw = stream.getvalue()
    meta = dict(id=70, name='race-cycle-continuity-7', expired=False,
                created_at='2030-04-01T02:00:00Z',
                digest='sha256:' + hashlib.sha256(raw).hexdigest(),
                workflow_run=dict(id=7, head_repository_id=1416489937))
    return raw, meta


class ContinuityCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(build_checkpoint, 'compact checkpoint builder is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'cycle_recovery_output'
        self.source.mkdir()
        self.output = self.root / 'cycle_checkpoint_output'

    def write(self, name, raw):
        (self.source / name).write_bytes(raw)

    def test_exact_sealed_bytes_and_all_proofs_survive_without_nested_original_archives(self):
        control = session()
        state = continuity(history_proofs={'5': {'proof': 'x' * (16 * 1024 * 1024)}})
        self.write('repeat-session.json', control)
        self.write('bootstrap-source-control.json', b'older bootstrap, superseded by session')
        self.write('continuity.json', state)
        self.write('source-control-13395880555.zip', b'z' * (17 * 1024 * 1024))
        nested = self.source / 'prior-checkpoints'
        nested.mkdir()
        (nested / 'original-5.zip').write_bytes(b'original bytes')
        before = {p.relative_to(self.source): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.source.rglob('*') if p.is_file()}

        result = build_checkpoint(self.source, self.output, expected_run=7)

        self.assertEqual(result, self.output)
        self.assertEqual({p.name for p in result.iterdir()},
                         {'repeat-session.json', 'continuity.json'})
        self.assertEqual((result / 'repeat-session.json').read_bytes(), control)
        self.assertEqual((result / 'continuity.json').read_bytes(), state)
        self.assertEqual(before, {p.relative_to(self.source): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.source.rglob('*') if p.is_file()})
        self.assertEqual(result.stat().st_mode & 0o077, 0)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in result.iterdir()))
        raw, meta = archive_from(result)
        self.assertLess(len(raw), 32 * 1024 * 1024)
        recovered = authenticated_source_control(raw, meta, expected_run=7)
        self.assertEqual(recovered['lifetime_requests'], 700)
        self.assertEqual(recovered['lifetime_completed_rounds'], 80)
        self.assertEqual(recovered['completed_round'], 25)
        self.assertEqual(recovered['prepared_round'], 26)
        self.assertEqual(recovered['source_wait']['state'], 'RATE_LIMIT_WAIT')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            authenticated_source_control(raw + b'tampered', meta, expected_run=7)

    def test_bootstrap_only_preserves_authorization_wait_and_incomplete_continuity(self):
        control = sealed(dict(schema='RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1',
            day_jst='2030-04-01', run_id=7, requests_used=1, completed_round=0,
            lifetime_requests_base=900, lifetime_requests=901, lifetime_completed_rounds=80,
            source_wait=dict(state='AUTHORIZATION_WAIT', reason='SOURCE_AUTHORIZATION_REQUIRED',
                             retry_at=None, http_status=403, attempts=1),
            halted_reason='SOURCE_HTTP_403_NO_RETRY'), 'source_control_sha256')
        self.write('bootstrap-source-control.json', control)
        state = continuity(complete=False)
        self.write('continuity.json', state)
        build_checkpoint(self.source, self.output, expected_run=7)
        self.assertEqual((self.output / 'bootstrap-source-control.json').read_bytes(), control)
        self.assertEqual((self.output / 'continuity.json').read_bytes(), state)
        raw, meta = archive_from(self.output)
        result = authenticated_source_control(raw, meta, expected_run=7)
        self.assertEqual(result['previous_halted_reason'], 'SOURCE_HTTP_403_NO_RETRY')
        self.assertEqual(result['source_wait']['state'], 'AUTHORIZATION_WAIT')
        self.assertIsNone(result['source_wait']['retry_at'])

    def test_missing_controls_create_no_checkpoint_and_leave_source_untouched(self):
        self.write('continuity.json', b'not a final control')
        self.assertIsNone(build_checkpoint(self.source, self.output, expected_run=7))
        self.assertFalse(self.output.exists())
        self.assertEqual((self.source / 'continuity.json').read_bytes(), b'not a final control')
        self.assertIsNone(build_checkpoint(self.root / 'absent', self.output, expected_run=7))
        self.assertFalse(self.output.exists())

    def test_bad_seal_schema_run_counters_prepared_round_and_wait_fail_closed(self):
        cases = [b'not json', b'[]', session(run_id=8), session(run_id=True),
                 session(schema='UNKNOWN'), session(schema=[]), session(requests_used=-1),
                 session(requests_used=True), session(completed_round=-1),
                 session(prepared_round=27), session(lifetime_requests=699),
                 session(source_wait={'state': 'READY'}),
                 session(source_wait=dict(state=[], reason='HTTP_RATE_LIMIT', retry_at=None,
                                          http_status=429, attempts=1)),
                 session(halted_reason='unreviewed free text')]
        bad_seal = json.loads(session())
        bad_seal['requests_used'] = 301
        cases.append(json.dumps(bad_seal).encode())
        cases.append(session().replace(b'"run_id": 7', b'"run_id": 8, "run_id": 7'))
        for raw in cases:
            with self.subTest(raw_length=len(raw)):
                self.write('repeat-session.json', raw)
                with self.assertRaises(ValueError):
                    build_checkpoint(self.source, self.output, expected_run=7)
                self.assertFalse(self.output.exists())
                self.assertEqual((self.source / 'repeat-session.json').read_bytes(), raw)

    def test_malformed_continuity_never_publishes_a_partial_checkpoint(self):
        self.write('repeat-session.json', session())
        cases = [b'{}', b'NaN', continuity(schema='UNKNOWN'),
                 continuity(day_jst='2030-04-02'), continuity(rows={}),
                 continuity(complete='true')]
        broken = json.loads(continuity())
        broken['history_proofs'] = {}
        cases.append(json.dumps(broken).encode())
        for raw in cases:
            with self.subTest(raw_length=len(raw)):
                self.write('continuity.json', raw)
                with self.assertRaises(ValueError):
                    build_checkpoint(self.source, self.output, expected_run=7)
                self.assertFalse(self.output.exists())
                self.assertFalse(list(self.root.glob('.cycle_checkpoint_output.*')))

    def test_control_and_continuity_must_be_regular_files_without_symlinks(self):
        target = self.root / 'original.json'
        target.write_bytes(session())
        control = self.source / 'repeat-session.json'
        control.symlink_to(target)
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        control.unlink()
        control.mkdir()
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        control.rmdir()
        os.mkfifo(control)
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        control.unlink()
        self.write('repeat-session.json', session())
        (self.source / 'continuity.json').symlink_to(target)
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        self.assertFalse(self.output.exists())

    def test_source_symlinks_output_aliases_and_existing_output_are_rejected(self):
        self.write('repeat-session.json', session())
        alias = self.root / 'source-alias'
        alias.symlink_to(self.source, target_is_directory=True)
        for source, output in [(alias, self.output), (self.source, self.source / 'checkpoint')]:
            with self.subTest(source=source, output=output), self.assertRaises(ValueError):
                build_checkpoint(source, output, expected_run=7)
        self.output.mkdir()
        sentinel = self.output / 'retained'
        sentinel.write_bytes(b'keep this')
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        self.assertEqual(sentinel.read_bytes(), b'keep this')

    def test_large_compressible_state_is_preserved_and_fits_legacy_zip_reader(self):
        self.write('repeat-session.json', session())
        raw = continuity(history_proofs={'5': {'proof': 'x' * (32 * 1024 * 1024)}})
        self.write('continuity.json', raw)
        build_checkpoint(self.source, self.output, expected_run=7)
        self.assertEqual((self.output / 'continuity.json').read_bytes(), raw)
        packed, meta = archive_from(self.output, compression=zipfile.ZIP_DEFLATED)
        self.assertLess(len(packed), 32 * 1024 * 1024)
        self.assertEqual(authenticated_source_control(packed, meta, expected_run=7)['prepared_round'], 26)

    def test_expanded_member_limit_rejects_oversize_without_reading_or_changing_source(self):
        self.write('repeat-session.json', session())
        path = self.source / 'continuity.json'
        with path.open('wb') as stream:
            stream.truncate(512 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            build_checkpoint(self.source, self.output, expected_run=7)
        self.assertFalse(self.output.exists())
        self.assertEqual(path.stat().st_size, 512 * 1024 * 1024 + 1)

    def test_cli_reports_absence_without_fabricating_a_healthy_checkpoint(self):
        result = subprocess.run([sys.executable, '-m', 'race_ai.continuity_checkpoint',
            '--source-dir', str(self.source), '--out-dir', str(self.output), '--expected-run', '7'],
            cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'checkpoint_created': False})
        self.assertFalse(self.output.exists())

    def test_workflow_pack_command_executes_before_existing_artifact_upload(self):
        steps = re.split(r'^      - name: ', WORKFLOW.read_text(), flags=re.MULTILINE)[1:]
        upload = next(step for step in steps if 'name: race-cycle-continuity-' in step)
        before = steps[steps.index(upload) - 1]
        build = steps[steps.index(upload) - 2]
        self.assertIn('if: always()', before)
        self.assertIn("steps.checkpoint_private.outcome == 'success'",upload)
        command = build.split('        run: ', 1)[1].strip()
        self.assertIn('race_ai.continuity_checkpoint', command)
        command = command.replace('${{ github.run_id }}', '7')
        self.write('repeat-session.json', session())
        result = subprocess.run(['bash', '-e', '-c', command], cwd=self.root,
            env=dict(os.environ, GITHUB_RUN_ID='7', PYTHONPATH=str(ROOT)),
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        private=self.root/'runner-private';private.mkdir(mode=0o700)
        key=bytes(range(32))
        env=dict(os.environ,GITHUB_RUN_ID='7',GITHUB_SHA='a'*40,
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_ACTIONS='true',
            RUNNER_TEMP=str(private),PYTHONPATH=str(ROOT),RACE_AI_STATE_KEY=base64.b64encode(key).decode())
        protect=before.split('        run: ',1)[1].strip().replace('${{ runner.temp }}',str(private))
        self.assertIn('boat_private_original_archive pack --kind CONTINUITY',protect)
        result=subprocess.run(['bash','-e','-c',protect],cwd=self.root,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        path = re.search(r'^          path: (.+)$', upload, re.MULTILINE).group(1).strip()
        self.assertEqual(path,'${{ runner.temp }}/boat-private-originals/continuity/private-original.enc')
        cipher=Path(path.replace('${{ runner.temp }}',str(private))).read_bytes()
        packed=io.BytesIO()
        with zipfile.ZipFile(packed,'w') as outer:outer.writestr('private-original.enc',cipher)
        raw=packed.getvalue();receipt=dict(id=71,name='race-cycle-continuity-7',expired=False,
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),created_at='2030-04-01T01:00:00Z',
            workflow_run=dict(id=7,repository_id=1416489937,head_repository_id=1416489937,head_sha='a'*40))
        from race_ai.boat_private_original_archive import open_original_zip
        with open_original_zip(raw,receipt,expected_kind='CONTINUITY',key=key) as original:
            self.assertEqual(original.read('repeat-session.json'),session())
        self.assertIn('name: race-cycle-continuity-${{ github.run_id }}', upload)
        self.assertIn('if: always()', upload)
        self.assertIn('if-no-files-found: error', upload)
        control=next(step for step in steps if step.startswith('Derive count-only handoff control'))
        command=control.split('        run: ',1)[1].strip().replace('${{ runner.temp }}',str(private))
        result=subprocess.run(['bash','-e','-c',command],cwd=self.root,env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        public=(private/'boat-source-control/source-control.json').read_bytes()
        outer=io.BytesIO()
        with zipfile.ZipFile(outer,'w') as artifact:artifact.writestr('source-control.json',public)
        public_zip=outer.getvalue()
        public_receipt=dict(receipt,id=72,name='race-source-control-7',size_in_bytes=len(public_zip),
            digest='sha256:'+hashlib.sha256(public_zip).hexdigest())
        receipt['size_in_bytes']=len(raw)
        from race_ai.boat_source_control import read_summary
        with patch.dict(os.environ,{},clear=True):
            restored=read_summary(public_zip,public_receipt,raw,receipt,run_id=7,head_sha='a'*40)
        self.assertEqual(restored['previous_session_requests'],json.loads(session())['requests_used'])
        self.assertEqual(restored['previous_run_id'],7)


if __name__ == '__main__':
    unittest.main()
