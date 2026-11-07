"""Real local audio transport with declared synthetic recognition outputs."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch


AVAILABLE=importlib.util.find_spec('numpy') and shutil.which('ffmpeg') and shutil.which('ffprobe')


@unittest.skipUnless(AVAILABLE,'local NumPy and FFmpeg needed')
class CommentaryTests(unittest.TestCase):
    def setUp(self):
        try:
            from race_ai import boat_video_commentary as module
        except ImportError:
            self.fail('Offline commentary transport is not implemented')
        self.module=module
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def fixture(self,*,audio=True,duration=1.,offset=7.,audio_filter=None):
        target=self.root/('audio.mkv' if audio else 'silent.mkv')
        command=['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10']
        if audio:command+=['-f','lavfi','-i','sine=frequency=521:sample_rate=16000']
        command+=['-t',str(duration),'-output_ts_offset',str(offset),'-c:v','ffv1','-threads','1']
        if audio:
            command+=['-c:a','pcm_f32le']
            if audio_filter is not None:command+=['-af',audio_filter]
        command+=[str(target)]
        subprocess.run(command,check=True,capture_output=True,timeout=20)
        return target

    def recognize(self,samples,*,sample_rate):
        self.calls.append((len(samples),sample_rate))
        return dict(text='先頭は3号艇、2番手は1号艇。',quality_status='USABLE_UNVERIFIED',raw_token_ids=[10,20])

    def run_media(self,path,*,recognizer=None,options=None,phase='RACE',window_seconds=5.):
        from race_ai.boat_video_tracking import _options,_local_media
        settings=_options(dict(max_duration_seconds=90.,**(options or {})))
        self.calls=[]
        class Recognizer:
            def metadata(inner):return {'scope':'SYNTHETIC_TEST_RECOGNIZER','model_sha256':'b'*64}
            def __call__(inner,samples,*,sample_rate):
                return (recognizer or self.recognize)(samples,sample_rate=sample_rate)
        with _local_media(path,settings) as (source,local,digest,_):
            return self.module.transcribe_commentary(source,local,media_sha256=digest,
                options=settings,recognizer=Recognizer(),phase=phase,window_seconds=window_seconds)

    def test_actual_pcm_pts_and_source_bytes_are_preserved(self):
        path=self.fixture();before=path.read_bytes()
        context,metadata=self.run_media(path)
        self.assertEqual(context['media_sha256'],sha256(before).hexdigest())
        self.assertEqual(metadata['audio_status'],'TRANSCRIBED_UNVERIFIED')
        self.assertEqual(self.calls,[(16000,16000)])
        segment=context['segments'][0]
        self.assertEqual((segment['start_pts'],segment['end_pts']),(7.,8.))
        self.assertEqual(segment['available_from_pts'],8.)
        self.assertEqual(segment['valid_until_pts'],10.)
        self.assertEqual(segment['producer_kind'],'ASR_LOCAL_UNVERIFIED')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(metadata['prediction_eligible'])

    def test_large_absolute_source_pts_does_not_end_pcm_before_the_first_sample(self):
        context,metadata=self.run_media(self.fixture(offset=2700.))
        self.assertEqual(self.calls,[(16000,16000)])
        self.assertEqual(context['segments'][0]['start_pts'],2700.)
        self.assertEqual(context['segments'][0]['end_pts'],2701.)
        self.assertEqual(metadata['decoded_sample_count'],16000)

    def test_low_signal_audio_is_unresolved_instead_of_synthetic_boat_speech(self):
        context,metadata=self.run_media(self.fixture(duration=11.,audio_filter='volume=0.001'))
        self.assertEqual(self.calls,[])
        self.assertEqual(context['segments'],[])
        self.assertEqual(metadata['chunk_count'],3)
        self.assertEqual(metadata['audio_status'],'LOW_SIGNAL_AUDIO_UNRESOLVED')
        self.assertEqual(metadata['low_signal_chunks'],3)
        self.assertTrue(all(c['quality_status']=='NEEDS_REVIEW_LOW_SIGNAL' for c in metadata['chunks']))
        self.assertTrue(all(c['signal_rms']<.001 for c in metadata['chunks']))

    def test_silent_video_never_invokes_recognizer(self):
        context,metadata=self.run_media(self.fixture(audio=False))
        self.assertEqual(context['segments'],[])
        self.assertEqual(self.calls,[])
        self.assertEqual(metadata['audio_status'],'NO_AUDIO')

    def test_all_chunks_processed_without_an_acquisition_count_cap(self):
        context,metadata=self.run_media(self.fixture(duration=31.,offset=2.),window_seconds=30.)
        self.assertEqual(self.calls,[(480000,16000),(16000,16000)])
        self.assertEqual([s['start_pts'] for s in context['segments']],[2.,32.])
        self.assertEqual([s['available_from_pts'] for s in context['segments']],[32.,33.])
        self.assertEqual(metadata['chunk_count'],2)

    def test_default_five_second_windows_make_availability_follow_each_short_input(self):
        context,metadata=self.run_media(self.fixture(duration=6.,offset=2.))
        self.assertEqual(self.calls,[(80000,16000),(16000,16000)])
        self.assertEqual([s['available_from_pts'] for s in context['segments']],[7.,8.])
        self.assertEqual(metadata['window_seconds'],5.)

    def test_invalid_model_input_windows_reject_without_recognition(self):
        path=self.fixture()
        for value in (0,-1,30.1,True,float('nan'),float('inf'),.00000001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.run_media(path,window_seconds=value)
                self.assertEqual(self.calls,[])

    def test_repetitive_or_length_limited_recognition_stays_raw_without_cues(self):
        def recognizer(samples,*,sample_rate):
            return dict(text='お気持ちも'*30,quality_status='NEEDS_REVIEW_REPETITION',raw_token_ids=[10]*100)
        context,metadata=self.run_media(self.fixture(),recognizer=recognizer)
        self.assertEqual(context['segments'],[])
        self.assertEqual(metadata['chunks'][0]['raw_recognition']['text'],'お気持ちも'*30)
        self.assertEqual(metadata['chunks'][0]['quality_status'],'NEEDS_REVIEW_REPETITION')

    def test_probe_rejects_audio_pts_gap_instead_of_concatenating_timeline(self):
        with self.assertRaises(ValueError):
            self.module._audio_timeline({'streams':[{'sample_rate':'16000'}],
                'frames':[{'pts_time':'7','nb_samples':1600},{'pts_time':'7.2','nb_samples':1600}]},90.)

    def test_probe_rejects_missing_pts_invalid_sample_count_and_duration(self):
        for data in [dict(streams=[{'sample_rate':'16000'}],frames=[{'nb_samples':160}]),
                     dict(streams=[{'sample_rate':'16000'}],frames=[{'pts_time':'0','nb_samples':0}]),
                     dict(streams=[{'sample_rate':'16000'}],frames=[{'pts_time':'0','nb_samples':2000000}])]:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):self.module._audio_timeline(data,90.)

    def test_coarse_audio_timebase_cannot_hide_a_real_packet_gap(self):
        with self.assertRaises(ValueError):
            self.module._audio_timeline(dict(streams=[{'sample_rate':'16000','time_base':'1/1'}],
                frames=[{'pts_time':'0','nb_samples':1600},{'pts_time':'1','nb_samples':1600}]),90.)

    def test_wrong_media_hash_is_rejected_before_recognition(self):
        from race_ai.boat_video_tracking import _options,_local_media
        path=self.fixture();options=_options(None)
        with _local_media(path,options) as (source,local,digest,_):
            with self.assertRaises(ValueError):
                self.module.transcribe_commentary(source,local,media_sha256='0'*64,
                    options=options,recognizer=self.recognize,phase='RACE')

    def test_source_changed_by_recognizer_cannot_receive_context(self):
        path=self.fixture()
        def mutate(samples,*,sample_rate):
            with path.open('ab') as f:f.write(b'CHANGED')
            return dict(text='先頭は3号艇。',quality_status='USABLE_UNVERIFIED')
        with self.assertRaises(ValueError):self.run_media(path,recognizer=mutate)

    def test_recognizer_rejects_missing_or_remote_model_without_network(self):
        for value in ['https://invalid.example/model',self.root/'missing']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.module.PinnedCommentaryRecognizer(model_path=value)

    def test_pinned_assets_changed_during_backend_load_are_rejected(self):
        directory=self.root/'model';directory.mkdir();weight=directory/'model.safetensors'
        weight.write_bytes(b'CONTROLLED_MODEL_TEST_FIXTURE')
        expected=sha256(weight.read_bytes()).hexdigest()
        fake=ModuleType('transformers')
        model=SimpleNamespace(to=lambda value:model,eval=lambda:model)
        class Loader:
            @classmethod
            def from_pretrained(cls,*args,**kw):
                weight.write_bytes(b'CHANGED_WHILE_LOADING')
                return model
        fake.WhisperForConditionalGeneration=Loader
        fake.WhisperProcessor=SimpleNamespace(from_pretrained=lambda *a,**kw:object())
        with patch.dict(self.module.MODEL_FILES,{'model.safetensors':expected},clear=True), \
             patch.dict(sys.modules,{'torch':ModuleType('torch'),'transformers':fake}):
            with self.assertRaises(ValueError):
                self.module.PinnedCommentaryRecognizer(model_path=directory)

    def test_transport_requires_a_readonly_held_descriptor(self):
        path=self.fixture();digest=sha256(path.read_bytes()).hexdigest()
        with path.open('r+b') as source:
            with self.assertRaises(ValueError):
                self.module._source_pin(source,f'/proc/self/fd/{source.fileno()}',digest,1000000)

    def test_quality_gate_rejects_repetition_and_length_boundary(self):
        self.assertEqual(self.module._quality('お気持ちも'*30,[1]*100),'NEEDS_REVIEW_REPETITION')
        self.assertEqual(self.module._quality('先頭は1号艇。',list(range(440))),'NEEDS_REVIEW_LENGTH_LIMIT')
        self.assertEqual(self.module._quality('先頭は3号艇、2番手は1号艇。',[1,2,3]),'USABLE_UNVERIFIED')


if __name__=='__main__':unittest.main()
