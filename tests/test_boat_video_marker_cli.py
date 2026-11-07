"""Real local transport with injected synthetic observations, not field accuracy."""
from contextlib import closing, redirect_stderr, redirect_stdout
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'boat_video_marker_analyze.py'
AVAILABLE = importlib.util.find_spec('numpy') is not None and shutil.which('ffmpeg') and shutil.which('ffprobe')


@unittest.skipUnless(AVAILABLE, 'local video fixtures require NumPy and FFmpeg/FFprobe')
class MarkerCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.original = Path(cls.fixture.name) / 'synthetic.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc=size=96x64:rate=10:duration=0.7', '-vf', 'setpts=PTS+2/TB',
                        '-fps_mode', 'passthrough', '-c:v', 'mpeg4', '-bf', '0', '-threads', '1',
                        str(cls.original)], check=True, capture_output=True, timeout=20)
        frames = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
            '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(cls.original)], timeout=20))
        cls.pts = [float(f['best_effort_timestamp_time']) for f in frames['frames']]
        raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
            '-i', str(cls.original), '-map', '0:v:0', '-an', '-fps_mode', 'passthrough',
            '-threads', '1', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1'], timeout=20)
        size = 96 * 64 * 3
        cls.hashes = [sha256(raw[i:i+size]).hexdigest() for i in range(0, len(raw), size)]
        assert len(cls.pts) == len(cls.hashes) == 6 and len(set(cls.hashes)) == 6
        assert cls.pts[0] == 2.0

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'local marker diagnostic entrypoint is missing')
        spec = importlib.util.spec_from_file_location('marker_cli_under_test', SCRIPT)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.media = self.root / 'owner-secret-video.mp4'
        shutil.copyfile(self.original, self.media)
        self.output = self.root / 'output'
        self.models = [self.root / f'owner-secret-{n}.asset' for n in ('recognizer', 'context', 'glyph')]
        for f in self.models:
            f.write_bytes(b'synthetic test metadata only; no pinned model')
        self.calls, self.factory_args = [], []
        self.fail_at = None
        self.mutate_at = None
        owner = self

        class Pipeline:
            def update(self, image, *, t, frame_index, scene):
                if frame_index == owner.fail_at:
                    raise RuntimeError('owner-secret path/token must not escape')
                digest = sha256(image.tobytes()).hexdigest()
                owner.calls.append((frame_index, t, digest, scene))
                if frame_index == owner.mutate_at:
                    info = owner.media.stat()
                    os.utime(owner.media, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
                return dict(schema_version='SYNTHETIC_TEST_PIPELINE_V1', frame_index=frame_index,
                            t=t, scene=scene, frame_sha256=digest, model_eligible=False,
                            identity_validated=False, injected_observations=True)

        def factory(**kwargs):
            self.factory_args.append(kwargs)
            return Pipeline()
        self.factory = factory

    def arguments(self, *, output=None, media=None, synthetic=True):
        args = ['--media', str(self.media if media is None else media),
                '--output-dir', str(self.output if output is None else output),
                '--recognizer-model', str(self.models[0]), '--context-model', str(self.models[1]),
                '--glyph-model', str(self.models[2]), '--development', '--single-continuous-shot']
        return args + (['--source-role', 'SYNTHETIC_TEST'] if synthetic else [])

    def invoke(self, args=None, *, injected=True):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.cli.main(self.arguments() if args is None else args,
                                 pipeline_factory=self.factory if injected else None)
        self.assertNotIn('owner-secret', out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def journal(self, output=None):
        return [json.loads(line) for line in ((output or self.output) / 'frames.jsonl').read_text().splitlines()]

    def test_all_native_frames_pts_hashes_order_and_private_outputs_are_preserved(self):
        original = {f: (f.read_bytes(), f.stat().st_mtime_ns) for f in [self.media, *self.models]}
        code, out, err = self.invoke()
        self.assertEqual((code, err), (0, ''))
        rows = self.journal()
        self.assertEqual([r['frame_index'] for r in rows], [0, 1, 2, 3, 4, 5])
        self.assertEqual([r['source_pts'] for r in rows], self.pts)
        self.assertEqual([r['t'] for r in rows], [p-self.pts[0] for p in self.pts])
        self.assertEqual([r['decoded_bgr_sha256'] for r in rows], self.hashes)
        self.assertEqual([r['pipeline_result']['frame_index'] for r in rows], [0, 1, 2, 3, 4, 5])
        self.assertEqual([r['media_sha256'] for r in rows], [sha256(self.media.read_bytes()).hexdigest()] * 6)
        self.assertEqual(self.factory_args, [dict(refresh_frames=1, label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')])
        receipt = json.loads((self.output / 'receipt.json').read_text())
        self.assertEqual((receipt['status'], receipt['decoded_frames'], receipt['probed_frames']), ('SUCCESS', 6, 6))
        self.assertEqual(receipt['execution_mode'], 'INJECTED_SYNTHETIC_TEST')
        self.assertFalse(receipt['pinned_models'])
        self.assertEqual(receipt['frame_sampling'], 'NONE_EVERY_DECODED_FRAME')
        self.assertEqual(receipt['resource_guards']['processing_timeout_seconds'], 7200.)
        self.assertEqual(receipt['shot_scope'], 'CALLER_DECLARED_SINGLE_CONTINUOUS_SHOT_NOT_AUTHENTICATED')
        self.assertEqual(receipt['journal_sha256'], sha256((self.output / 'frames.jsonl').read_bytes()).hexdigest())
        self.assertEqual(set(json.loads(out)), {'status', 'decoded_frames', 'receipt_sha256'})
        self.assertFalse((self.output / 'failure.json').exists())
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for f in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(original, {f: (f.read_bytes(), f.stat().st_mtime_ns) for f in original})

    def test_existing_output_symlink_and_git_output_cannot_be_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'frames.jsonl'; sentinel.write_bytes(b'original')
        code, _, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(sentinel.read_bytes(), b'original')
        target = self.root / 'target'; target.mkdir()
        link = self.root / 'link'; link.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.invoke(self.arguments(output=link / 'new'))[0], 2)
        self.assertEqual(list(target.iterdir()), [])
        repository = self.root / 'repository'; repository.mkdir(); (repository / '.git').mkdir()
        self.assertEqual(self.invoke(self.arguments(output=repository / 'new'))[0], 2)
        self.assertFalse((repository / 'new').exists())

    def test_remote_playlist_and_symlink_media_are_rejected_without_pipeline_execution(self):
        playlist = self.root / 'owner-secret.m3u8'; playlist.write_text('#EXTM3U\nhttps://example.invalid/private\n')
        link = self.root / 'media-link.mp4'; link.symlink_to(self.media)
        for i, source in enumerate(('https://user:owner-secret@example.invalid/x.m3u8', playlist, link)):
            output = self.root / f'rejected-{i}'
            self.assertEqual(self.invoke(self.arguments(output=output, media=source))[0], 2)
            self.assertFalse((output / 'receipt.json').exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.factory_args, [])

    def test_partial_pipeline_exception_keeps_flushed_journal_and_never_success(self):
        self.fail_at = 2
        code, out, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['status'], 'FAILED')
        self.assertEqual(err, 'BOAT_VIDEO_MARKER_ANALYSIS_FAILED\n')
        self.assertEqual([r['frame_index'] for r in self.journal()], [0, 1])
        self.assertFalse((self.output / 'receipt.json').exists())
        failure = json.loads((self.output / 'failure.json').read_text())
        self.assertEqual((failure['status'], failure['decoded_frames']), ('FAILED', 2))
        self.assertNotIn('owner-secret', json.dumps(failure))

    def test_fewer_or_extra_decoded_frames_never_receive_success_receipt(self):
        original_decode = self.cli._decode
        for kind, count in (('short', 5), ('extra', 6)):
            output = self.root / kind
            def changed(*args, **kwargs):
                with closing(original_decode(*args, **kwargs)) as decoded:
                    for i, image in enumerate(decoded):
                        if kind == 'short' and i == 5:
                            return
                        yield image
                    if kind == 'extra':
                        yield image.copy()
            with self.subTest(kind=kind), patch.object(self.cli, '_decode', changed):
                self.assertEqual(self.invoke(self.arguments(output=output))[0], 2)
            self.assertFalse((output / 'receipt.json').exists())
            failure = json.loads((output / 'failure.json').read_text())
            self.assertEqual(failure['failure_code'], 'FRAME_COUNT_MISMATCH')
            self.assertEqual(len(self.journal(output)), count)

    def test_source_immutable_exit_precedes_success_publication(self):
        self.mutate_at = 5
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(len(self.journal()), 6)
        self.assertFalse((self.output / 'receipt.json').exists())
        self.assertEqual(json.loads((self.output / 'failure.json').read_text())['failure_code'],
                         'MEDIA_IMMUTABILITY_FAILED')

    def test_declarations_positive_options_and_explicit_synthetic_injection_are_required(self):
        invalid = []
        for flag in ('--development', '--single-continuous-shot'):
            args = self.arguments(); args.remove(flag); invalid.append(args)
        invalid += [self.arguments() + ['--refresh-frames', '0'],
                    self.arguments() + ['--processing-timeout-seconds', 'nan'],
                    self.arguments(synthetic=False)]
        for args in invalid:
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args)[0], 2)
            self.assertFalse(self.output.exists())
        self.assertEqual(self.factory_args, [])

    def test_real_model_setup_is_not_replaced_by_injection_and_failure_is_sanitized(self):
        code, _, _ = self.invoke(self.arguments(synthetic=False), injected=False)
        self.assertEqual(code, 2)
        self.assertFalse((self.output / 'receipt.json').exists())
        failure = json.loads((self.output / 'failure.json').read_text())
        self.assertEqual(failure['failure_code'], 'MODEL_SETUP_FAILED')
        self.assertEqual(self.factory_args, [])

    def test_refresh_timeout_and_existing_per_clip_guards_are_explicit(self):
        args = self.arguments() + ['--refresh-frames', '2', '--processing-timeout-seconds', '12',
                                  '--max-decoded-frames', '8', '--max-duration-seconds', '3']
        self.assertEqual(self.invoke(args)[0], 0)
        receipt = json.loads((self.output / 'receipt.json').read_text())
        self.assertEqual(receipt['refresh_frames'], 2)
        self.assertEqual(receipt['resource_guards']['processing_timeout_seconds'], 12.)
        self.assertEqual(receipt['resource_guards']['max_decoded_frames'], 8)
        self.assertEqual(receipt['resource_guards']['max_duration_seconds'], 3.)
        self.assertEqual(len(self.journal()), 6)


    def change_own_fixture(self, *, restore_bytes):
        before = self.media.stat()
        raw = self.media.read_bytes()
        with self.media.open('r+b') as stream:
            offset = len(raw)//2
            stream.seek(offset)
            stream.write(bytes([raw[offset] ^ 1]))
            stream.flush()
            os.fsync(stream.fileno())
            if restore_bytes:
                stream.seek(offset)
                stream.write(raw[offset:offset+1])
                stream.flush()
                os.fsync(stream.fileno())
        os.utime(self.media, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = self.media.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(self.media.read_bytes() == raw, restore_bytes)


    def wrap_last_update(self, *, restore_bytes):
        original_factory = self.factory
        def factory(**kwargs):
            pipeline = original_factory(**kwargs)
            update = pipeline.update
            def mutate(image, **state):
                result = update(image, **state)
                if state['frame_index'] == 5:
                    self.change_own_fixture(restore_bytes=restore_bytes)
                return result
            pipeline.update = mutate
            return pipeline
        self.factory = factory


    def assert_integrity_failure(self):
        code, output, error = self.invoke()
        self.assertEqual(code, 2, 'same-size/mtime-restored source changes must never publish SUCCESS')
        self.assertEqual(error, 'BOAT_VIDEO_MARKER_ANALYSIS_FAILED\n')
        self.assertEqual(json.loads(output)['status'], 'FAILED')
        self.assertFalse((self.output/'receipt.json').exists())
        self.assertEqual(len(self.journal()), 6)
        failure = json.loads((self.output/'failure.json').read_text())
        self.assertEqual(failure['failure_code'], 'MEDIA_IMMUTABILITY_FAILED')


    def test_same_size_byte_change_and_restored_mtime_is_not_success(self):
        self.wrap_last_update(restore_bytes=False)
        self.assert_integrity_failure()


    def test_restored_bytes_and_mtime_still_fail_changed_fd_ctime(self):
        original_sha = sha256(self.media.read_bytes()).hexdigest()
        self.wrap_last_update(restore_bytes=True)
        self.assert_integrity_failure()
        self.assertEqual(sha256(self.media.read_bytes()).hexdigest(), original_sha)


    def test_fd_ctime_is_rechecked_after_end_hash_not_only_before_it(self):
        import hashlib
        calls, closed = [], []
        decode = self.cli._decode
        def decoded(*args, **kwargs):
            try:
                yield from decode(*args, **kwargs)
            finally:
                closed.append(True)
        def hash_then_change(source, algorithm):
            self.assertEqual(len(self.calls), 6)
            self.assertEqual(closed, [True])
            self.assertEqual(source.tell(), 0)
            value = hashlib.file_digest(source, algorithm)
            calls.append(source.fileno())
            self.change_own_fixture(restore_bytes=True)
            return value
        with patch.object(self.cli, '_decode', decoded), \
                patch.object(self.cli, 'file_digest', hash_then_change, create=True):
            self.assert_integrity_failure()
        self.assertEqual(len(calls), 1)


    def test_end_digest_mismatch_is_rejected_even_if_fd_ctime_is_unchanged(self):
        class Mismatch:
            def hexdigest(self):
                return 'f' * 64
        with patch.object(self.cli, 'file_digest', return_value=Mismatch(), create=True):
            self.assert_integrity_failure()


if __name__ == '__main__':
    unittest.main()
