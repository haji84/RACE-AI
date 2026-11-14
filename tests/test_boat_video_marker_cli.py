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
import sys
import tempfile
from types import ModuleType
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
        # Bound encoding itself; muxer offset avoids dropping the final packet
        # through FFmpeg-version-dependent MP4 edit lists for filter offsets.
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc=size=96x64:rate=10', '-frames:v', '6', '-output_ts_offset', '2',
                        '-fps_mode', 'passthrough', '-c:v', 'mpeg4', '-bf', '0', '-threads', '1',
                        str(cls.original)], check=True, capture_output=True, timeout=20)
        frames = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-count_packets',
            '-show_entries', 'frame=best_effort_timestamp_time:stream=nb_read_packets',
            '-of', 'json', str(cls.original)], timeout=20))
        cls.encoded_frames = int(frames['streams'][0]['nb_read_packets'])
        cls.pts = [float(f['best_effort_timestamp_time']) for f in frames['frames']]
        raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
            '-i', str(cls.original), '-map', '0:v:0', '-an', '-fps_mode', 'passthrough',
            '-threads', '1', '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1'], timeout=20)
        size = 96 * 64 * 3
        cls.hashes = [sha256(raw[i:i+size]).hexdigest() for i in range(0, len(raw), size)]
        assert cls.encoded_frames == len(cls.pts) == len(cls.hashes) == 6 and len(set(cls.hashes)) == 6, \
            f'SYNTHETIC_FIXTURE_COUNTS encoded={cls.encoded_frames} probed={len(cls.pts)} decoded={len(cls.hashes)} unique={len(set(cls.hashes))}'
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

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_optional_rider_tracks_are_saved_separately_without_number_binding(self):
        from race_ai.boat_video_rider_detector import SCHEMA
        class Detector:
            def __init__(self, *, model_path, tiled):
                self.model_path = model_path
            def metadata(self):
                return {'engine': 'INJECTED_SYNTHETIC_PERSON_TEST', 'model_eligible': False}
            def __call__(self, frame):
                return dict(schema_version=SCHEMA, frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    coordinate_space='IMAGE_PX', semantic_type='RIDER_PART_TYPED',
                    detections=[dict(box=[10., 10., 20., 30.], score=.9,
                                     semantic_type='RIDER_PART_TYPED', coco_class_id=0)],
                    engine=self.metadata(), identity_validated=False, model_eligible=False)
        args = self.arguments() + ['--rider-model', str(self.models[0])]
        with patch('race_ai.boat_video_rider_detector.PinnedRiderPartDetector', Detector):
            code, _, err = self.invoke(args)
        self.assertEqual((code, err), (0, ''))
        rows = self.journal()
        self.assertEqual(len(rows), len(self.hashes))
        for row in rows:
            riders = row['pipeline_result']['rider_part_tracking']
            self.assertEqual(riders['frame_sha256'], row['decoded_bgr_sha256'])
            self.assertEqual(riders['frame_index'], row['frame_index'])
            self.assertTrue(riders['tracks'])
            self.assertTrue(all(r['number'] is None and r['hull_box'] is None for r in riders['tracks']))
            self.assertFalse(riders['model_eligible'])
        receipt = json.loads((self.output / 'receipt.json').read_text())
        self.assertFalse(receipt['pinned_models'])
        self.assertEqual(receipt['rider_part_tracking']['number_binding'], 'CLOTHING_COLOR_CURRENT_PIXEL_HYPOTHESIS')
        self.assertFalse(receipt['rider_part_tracking']['printed_numbers_required'])
        self.assertEqual(receipt['rider_part_tracking']['execution_scope'], 'INJECTED_SYNTHETIC_TEST')

    def test_clothing_only_requires_no_print_models_and_saves_actual_clothing_pipeline(self):
        from race_ai.boat_video_rider_detector import SCHEMA
        class Detector:
            def __init__(self,**kw): pass
            def metadata(self): return {'kind':'CONTROLLED_SYNTHETIC_PERSON'}
            def __call__(self,frame):
                return dict(schema_version=SCHEMA,frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    coordinate_space='IMAGE_PX',semantic_type='RIDER_PART_TYPED',
                    detections=[dict(box=[10,10,30,40],score=.9,coco_class_id=0,semantic_type='RIDER_PART_TYPED')],
                    engine=self.metadata(),identity_validated=False,model_eligible=False)
        args=['--media',str(self.original),'--output-dir',str(self.output),
              '--rider-model',str(self.models[0]),'--clothing-only',
              '--development','--single-continuous-shot','--source-role','SYNTHETIC_TEST']
        with patch('race_ai.boat_video_rider_detector.PinnedRiderPartDetector',Detector):
            code,out,err=self.invoke(args,injected=False)
        self.assertEqual(code,0,(out,err))
        rows=[json.loads(line) for line in (self.output/'frames.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),6)
        result=rows[-1]['pipeline_result']['rider_part_tracking']
        self.assertFalse(result['clothing_identity_policy']['printed_numbers_required'])
        self.assertFalse(result['identity_validated'])
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertEqual(receipt['execution_mode'],'PINNED_LOCAL_DEVELOPMENT_CLOTHING')

    def test_clothing_only_rejects_missing_person_model_before_processing(self):
        code,out,err=self.invoke(['--media',str(self.original),'--output-dir',str(self.output),
            '--clothing-only','--development','--single-continuous-shot'])
        self.assertNotEqual(code,0)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_source_bound_broadcast_context_uses_absolute_audio_pts(self):
        from race_ai.boat_video_rider_detector import SCHEMA
        class Detector:
            def __init__(self,**kw): pass
            def metadata(self): return {'kind':'CONTROLLED_SYNTHETIC_PERSON'}
            def __call__(self,frame):
                return dict(schema_version=SCHEMA,frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    coordinate_space='IMAGE_PX',semantic_type='RIDER_PART_TYPED',
                    detections=[dict(box=[10,10,30,40],score=.9,coco_class_id=0,semantic_type='RIDER_PART_TYPED')],
                    engine=self.metadata(),identity_validated=False,model_eligible=False)
        from tests.test_boat_video_broadcast_context import BroadcastContextTests
        fixture=BroadcastContextTests();fixture.setUp()
        fixture.media=sha256(self.media.read_bytes()).hexdigest()
        ctx=fixture.context(fixture.segment('2号艇の周回展示です。',phase='EXHIBITION_LAP',
            start_pts=2.,end_pts=2.1,available_from_pts=2.1,valid_until_pts=2.6))
        path=self.root/'broadcast.json';path.write_text(json.dumps(ctx));path.chmod(0o600)
        args=self.arguments()+['--rider-model',str(self.models[0]),'--broadcast-context',str(path)]
        with patch('race_ai.boat_video_rider_detector.PinnedRiderPartDetector',Detector):
            code,out,err=self.invoke(args)
        self.assertEqual(code,0,(out,err))
        rows=self.journal()
        self.assertEqual(rows[0]['pipeline_result']['rider_part_tracking']['broadcast_context']['active_cues'],[])
        self.assertTrue(rows[-1]['pipeline_result']['rider_part_tracking']['broadcast_context']['active_cues'])
        self.assertEqual(rows[-1]['pipeline_result']['rider_part_tracking']['tracks'][0]
                         ['broadcast_identity']['exhibition_number_candidate'],2)
        self.assertTrue((self.output/'broadcast-context.json').is_file())
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertEqual(receipt['broadcast_context']['time_basis'],'ABSOLUTE_MEDIA_PTS_SECONDS')

    def test_broadcast_options_require_color_rider_tracking(self):
        for options in [['--broadcast-context',str(self.models[0])],
                        ['--commentary-model',str(self.models[0])],
                        ['--rider-model',str(self.models[0]),'--anonymous-riders',
                         '--broadcast-context',str(self.models[0])]]:
            with self.subTest(options=options):
                code,out,err=self.invoke(self.arguments()+options)
                self.assertNotEqual(code,0)
                self.assertFalse(self.output.exists())

    def test_broadcast_context_and_local_asr_are_mutually_exclusive(self):
        code,out,err=self.invoke(self.arguments()+['--rider-model',str(self.models[0]),
            '--broadcast-context',str(self.models[0]),'--commentary-model',str(self.models[1])])
        self.assertNotEqual(code,0)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_local_audio_recognition_is_saved_but_not_available_before_chunk_end(self):
        from tests.test_boat_video_commentary import CommentaryTests
        fixture=CommentaryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        media=fixture.fixture()
        from race_ai.boat_video_rider_detector import SCHEMA
        class Detector:
            def __init__(self,**kw):pass
            def metadata(self):return {'kind':'SYNTHETIC_PERSON_TEST'}
            def __call__(self,frame):
                return dict(schema_version=SCHEMA,frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    coordinate_space='IMAGE_PX',semantic_type='RIDER_PART_TYPED',
                    detections=[dict(box=[10,10,30,40],score=.9,coco_class_id=0,semantic_type='RIDER_PART_TYPED')],
                    engine=self.metadata(),identity_validated=False,model_eligible=False)
        class Recognizer:
            def __init__(self,**kw):
                self.profile=kw.get('model_profile',
                    'reazon-k2-v2-int8-context' if kw.get('context_vocabulary') else 'reazon-k2-v2-int8')
            def metadata(self):return {'kind':'SYNTHETIC_RECOGNITION_TEST','profile':self.profile}
            def __call__(self,samples,*,sample_rate):
                return dict(text='先頭は3号艇。',quality_status='USABLE_UNVERIFIED',raw_token_ids=[1,2])
        module=ModuleType('race_ai.boat_video_reazon');module.PinnedReazonCommentaryRecognizer=Recognizer
        for profile in ['kotoba-v2','reazon-k2-v2-int8','reazon-k2-v2-int8-context']:
            with self.subTest(profile=profile):
                self.output=self.root/('output-'+profile)
                args=self.arguments(media=media)+['--rider-model',str(self.models[0]),
                    '--commentary-model',str(self.root),'--commentary-profile',profile,'--broadcast-phase','RACE']
                with patch('race_ai.boat_video_rider_detector.PinnedRiderPartDetector',Detector), \
                     patch('race_ai.boat_video_commentary.PinnedCommentaryRecognizer',Recognizer), \
                     patch.dict(sys.modules,{'race_ai.boat_video_reazon':module}):
                    code,out,err=self.invoke(args)
                self.assertEqual(code,0,(out,err))
                speech=json.loads((self.output/'commentary-receipt.json').read_text())
                self.assertEqual(speech['recognizer']['profile'],profile)
                self.assertEqual(speech['chunk_count'],1)
                self.assertEqual(speech['audio_timeline']['start_pts'],7.)
                self.assertEqual(len(self.journal()),10)
                for row in self.journal():
                    self.assertEqual(row['pipeline_result']['rider_part_tracking']['broadcast_context']['active_cues'],[])
                context=json.loads((self.output/'broadcast-context.json').read_text())
                self.assertEqual(context['segments'][0]['available_from_pts'],8.)

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_automatic_phase_only_needs_no_declared_phase_or_identity_models(self):
        from tests.test_boat_video_commentary import CommentaryTests
        fixture=CommentaryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        media=fixture.fixture(audio=False,duration=2.5)
        from race_ai.boat_video_phase import _make_packet
        class Reader:
            def __init__(self,**kw):pass
            def metadata(self):return {'kind':'CONTROLLED_SYNTHETIC_SCREEN_LABEL'}
            def __call__(self,frame):
                return _make_packet(frame,[dict(text='周回展示',confidence=90.,
                    box=[1,1,25,10],line_key=[1,1,1,1])],status='OCR_OBSERVATION',raw_tsv='')
        args=['--media',str(media),'--output-dir',str(self.output),
              '--phase-only','--phase-tesseract',str(self.models[0]),'--phase-tessdata',str(self.root),
              '--development','--source-role','SYNTHETIC_TEST']
        with patch('race_ai.boat_video_phase.LocalJapanesePhaseReader',Reader):
            code,out,err=self.invoke(args,injected=False)
        self.assertEqual(code,0,(out,err))
        rows=self.journal();self.assertEqual(len(rows),25)
        sampled=[r for r in rows if r['pipeline_result']['phase_detection']['fresh_observation']]
        self.assertEqual(len(sampled),3)
        self.assertEqual(sampled[0]['pipeline_result']['phase_detection']['observation']['phase'],'UNKNOWN')
        self.assertEqual(sampled[1]['pipeline_result']['phase_detection']['observation']['phase'],'EXHIBITION_LAP')
        for row in rows:
            phase=row['pipeline_result']['phase_detection']
            self.assertEqual(phase['frame_sha256'],row['decoded_bgr_sha256'])
            self.assertEqual(phase['source_pts'],row['source_pts'])
            if not phase['fresh_observation']:self.assertIsNone(phase['observation'])
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertEqual(receipt['phase_detection']['sampling_interval_seconds'],1.)
        self.assertFalse(receipt['model_eligible'])

    def test_phase_only_requires_explicit_phase_assets(self):
        for options in [['--phase-only'],['--phase-only','--clothing-only'],
                        ['--phase-tesseract',str(self.models[0])]]:
            with self.subTest(options=options):
                code,out,err=self.invoke(self.arguments()+options)
                self.assertNotEqual(code,0)
                self.assertFalse(self.output.exists())

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_primary_water_sampling_preserves_all_frames_and_source_topic_binding(self):
        from tests.test_boat_video_commentary import CommentaryTests
        fixture=CommentaryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        media=fixture.fixture(audio=False,duration=2.5)
        context=dict(schema_version='RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1',
            media_sha256=sha256(media.read_bytes()).hexdigest(),topic='EXHIBITION_TUTORIAL',
            provenance_sha256='a'*64)
        topic=self.root/'topic.json';topic.write_text(json.dumps(context));topic.chmod(0o600)
        module=ModuleType('race_ai.boat_video_activity')
        class Reader:
            def __init__(self,**kw):pass
            def metadata(self):return {'kind':'SYNTHETIC_PRIMARY_WATER_TEST'}
            def __call__(self,frame,*,media_sha256,source_context=None):
                return dict(frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    media_sha256=media_sha256,source_context=source_context,status='CONTENT_OBSERVATION',
                    primary_water_content_candidate=True,
                    depicted_exhibition_content_candidate=source_context is not None,
                    authenticated_current_exhibition=False,model_eligible=False)
        module.LocalPrimaryWaterReader=Reader
        args=['--media',str(media),'--output-dir',str(self.output),'--phase-only',
            '--activity-model',str(self.root),'--activity-boat-model',str(self.models[0]),
            '--exhibition-topic-context',str(topic),'--development','--source-role','SYNTHETIC_TEST']
        with patch.dict(sys.modules,{'race_ai.boat_video_activity':module}):
            code,out,err=self.invoke(args,injected=False)
        self.assertEqual(code,0,(out,err))
        rows=self.journal();self.assertEqual(len(rows),25)
        observations=[row['pipeline_result']['primary_water_detection'] for row in rows]
        self.assertEqual(sum(x['fresh_observation'] for x in observations),3)
        for row,observation in zip(rows,observations):
            self.assertEqual(observation['source_pts'],row['source_pts'])
            self.assertEqual(observation['frame_sha256'],row['decoded_bgr_sha256'])
            self.assertFalse(observation['usable_for_identity'])
            if observation['fresh_observation']:
                self.assertEqual(observation['observation']['source_context'],context)
                self.assertEqual(observation['observation']['media_sha256'],context['media_sha256'])
            else:self.assertIsNone(observation['observation'])
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertFalse(receipt['primary_water_detection']['authenticated_current_exhibition'])
        intervals=receipt['primary_water_detection']['observed_content_intervals']
        self.assertEqual(len(intervals['depicted_exhibition_content_candidate']),1)
        self.assertEqual(intervals['depicted_exhibition_content_candidate'][0]['distinct_positive_samples'],3)
        self.assertEqual(json.loads((self.output/'exhibition-topic-context.json').read_text()),context)

    def test_primary_water_options_reject_unpaired_assets_and_unbound_topic(self):
        options=[['--phase-only','--activity-model',str(self.root)],
                 ['--phase-only','--activity-boat-model',str(self.models[0])],
                 ['--phase-only','--exhibition-topic-context',str(self.models[0])]]
        for extra in options:
            with self.subTest(extra=extra):
                self.assertNotEqual(self.invoke(self.arguments()+extra)[0],0)
                self.assertFalse(self.output.exists())

    def test_exhibition_topic_context_requires_exact_media_sha(self):
        context=dict(schema_version='RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1',
            media_sha256='0'*64,topic='EXHIBITION_TUTORIAL',provenance_sha256='a'*64)
        topic=self.root/'topic.json';topic.write_text(json.dumps(context));topic.chmod(0o600)
        args=['--media',str(self.media),'--output-dir',str(self.output),'--phase-only',
            '--activity-model',str(self.root),'--activity-boat-model',str(self.models[0]),
            '--exhibition-topic-context',str(topic),'--development']
        code,out,err=self.invoke(args,injected=False)
        self.assertEqual(code,2)
        self.assertIn('EXHIBITION_CONTEXT_REJECTED',out)
        self.assertFalse((self.output/'receipt.json').exists())

    def test_content_intervals_require_distinct_samples_and_keep_boundary_uncertainty(self):
        self.assertTrue(hasattr(self.cli,'_SampledContentIntervals'),'sampled interval component missing')
        tracker=self.cli._SampledContentIntervals()
        def observe(stamp,positive,digest):
            tracker.update(t=stamp,scene=0,frame_sha256=digest*64,
                primary_water_content_candidate=positive,depicted_exhibition_content_candidate=False)
        observe(0.,False,'a');observe(1.,True,'b');observe(2.,True,'b')
        self.assertEqual(tracker.summary()['primary_water_content_candidate'],[])
        observe(3.,True,'c');observe(4.,False,'d')
        interval=tracker.summary()['primary_water_content_candidate'][0]
        self.assertEqual(interval['first_observed_t'],1.)
        self.assertEqual(interval['confirmed_from_t'],3.)
        self.assertEqual(interval['last_observed_t'],3.)
        self.assertEqual(interval['last_negative_before_t'],0.)
        self.assertEqual(interval['first_negative_after_t'],4.)
        self.assertEqual(interval['distinct_positive_samples'],2)
        self.assertTrue(interval['sampled_points_only'])
        self.assertEqual(tracker.summary()['depicted_exhibition_content_candidate'],[])

    def test_unknown_content_does_not_create_a_negative_interval_boundary(self):
        self.assertTrue(hasattr(self.cli,'_SampledContentIntervals'))
        tracker=self.cli._SampledContentIntervals()
        for stamp,value,digest in [(0.,True,'a'),(1.,True,'b'),(2.,None,'c')]:
            tracker.update(t=stamp,scene=0,frame_sha256=digest*64,
                primary_water_content_candidate=value,depicted_exhibition_content_candidate=value)
        interval=tracker.summary()['primary_water_content_candidate'][0]
        self.assertIsNone(interval['first_negative_after_t'])
        self.assertTrue(interval['right_boundary_censored'])
        self.assertEqual(interval['right_censor_reason'],'UNKNOWN_CONTENT_OBSERVATION')

    def test_content_interval_resets_on_time_gap_and_has_censored_eof(self):
        self.assertTrue(hasattr(self.cli,'_SampledContentIntervals'),'sampled interval component missing')
        tracker=self.cli._SampledContentIntervals()
        for stamp,scene,digest in [(0.,0,'a'),(1.,0,'b'),(3.,0,'c'),(4.,0,'d'),(5.,1,'e')]:
            tracker.update(t=stamp,scene=scene,frame_sha256=digest*64,
                primary_water_content_candidate=True,depicted_exhibition_content_candidate=True)
        groups=tracker.summary()['depicted_exhibition_content_candidate']
        self.assertEqual([(x['first_observed_t'],x['last_observed_t']) for x in groups],[(0.,1.),(3.,4.)])
        self.assertTrue(all(x['first_negative_after_t'] is None for x in groups))
        self.assertTrue(all(x['right_boundary_censored'] for x in groups))

    def test_repeated_display_content_extends_time_and_can_form_a_separate_later_run(self):
        tracker=self.cli._SampledContentIntervals()
        for stamp,positive,digest in [(0.,True,'a'),(1.,True,'b'),(2.,True,'b'),
                                     (3.,False,'n'),(4.,True,'a'),(5.,True,'b')]:
            tracker.update(t=stamp,scene=0,frame_sha256=digest*64,
                primary_water_content_candidate=positive,depicted_exhibition_content_candidate=False)
        rows=tracker.summary()['primary_water_content_candidate']
        self.assertEqual([(x['first_observed_t'],x['last_observed_t']) for x in rows],[(0.,2.),(4.,5.)])
        self.assertEqual([x['distinct_positive_samples'] for x in rows],[2,2])

    def test_primary_water_cadence_keeps_the_ffprobe_microsecond_clock_grid(self):
        import numpy as np
        def reader(frame,*,media_sha256,source_context):
            return dict(frame_sha256=sha256(frame.tobytes()).hexdigest(),media_sha256=media_sha256,
                status='CONTENT_OBSERVATION',primary_water_content_candidate=True,
                depicted_exhibition_content_candidate=False)
        pipeline=self.cli._PrimaryWaterPipeline(None,reader,media_sha256='a'*64,source_context=None)
        observed=[]
        for index,stamp in [(0,.036),(30,1.036),(60,2.036),(90,3.036),(120,4.036),(150,5.036)]:
            row=pipeline.update(np.full((8,8,3),index,dtype=np.uint8),
                t=stamp-.036,frame_index=index,scene=0)
            if row['primary_water_detection']['fresh_observation']:observed.append(index)
        self.assertEqual(observed,[0,30,60,90,120,150])

    def test_aquatic_content_intervals_are_separate_from_water_majority(self):
        tracker=self.cli._SampledContentIntervals()
        for stamp,digest in [(0.,'a'),(1.,'b')]:
            tracker.update(t=stamp,scene=0,frame_sha256=digest*64,
                primary_water_content_candidate=False,primary_aquatic_content_candidate=True,
                depicted_exhibition_content_candidate=False)
        rows=tracker.summary()
        self.assertIn('primary_aquatic_content_candidate',rows)
        self.assertEqual(len(rows['primary_aquatic_content_candidate']),1)
        self.assertEqual(rows['primary_water_content_candidate'],[])
        self.assertEqual(rows['depicted_exhibition_content_candidate'],[])

    def test_remote_rider_asset_rejected_before_native_execution(self):
        args = self.arguments() + ['--rider-model', 'https://owner-secret.invalid/model.onnx']
        self.assertEqual(self.invoke(args)[0], 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
    def test_rider_runtime_failure_preserves_partial_journal_without_success(self):
        from race_ai.boat_video_rider_detector import SCHEMA
        class Detector:
            def __init__(self, **kwargs):
                self.count = 0
            def metadata(self):
                return {'engine': 'INJECTED_SYNTHETIC_PERSON_TEST'}
            def __call__(self, frame):
                self.count += 1
                if self.count == 3:
                    raise RuntimeError('owner-secret should not escape')
                return dict(schema_version=SCHEMA, frame_sha256=sha256(frame.tobytes()).hexdigest(),
                    coordinate_space='IMAGE_PX', semantic_type='RIDER_PART_TYPED', detections=[],
                    engine=self.metadata(), identity_validated=False, model_eligible=False)
        with patch('race_ai.boat_video_rider_detector.PinnedRiderPartDetector', Detector):
            code, out, err = self.invoke(self.arguments() + ['--rider-model', str(self.models[0])])
        self.assertEqual(code, 2)
        self.assertEqual(len(self.journal()), 2)
        self.assertFalse((self.output / 'receipt.json').exists())
        self.assertEqual(json.loads((self.output / 'failure.json').read_text())['failure_code'], 'FRAME_ANALYSIS_FAILED')

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
