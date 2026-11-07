"""Native ASR boundary tests with real arrays/files and a controlled NN stub."""
from copy import deepcopy
from hashlib import sha256
import gc
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, 'optional NumPy required')
class ReazonRecognizerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module=importlib.import_module('race_ai.boat_video_reazon')
        except ModuleNotFoundError:
            self.fail('Pinned native Japanese ASR adapter is missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.directory=self.root/'model';self.directory.mkdir()
        payloads={'encoder-epoch-99-avg-1.int8.onnx':b'CONTROLLED_ENCODER',
                  'decoder-epoch-99-avg-1.int8.onnx':b'CONTROLLED_DECODER',
                  'joiner-epoch-99-avg-1.int8.onnx':b'CONTROLLED_JOINER',
                  'tokens.txt':'<blk> 0\n三\t1\n番  2\n手\t3\nは 4\n四\t5\n7 6\n号 7\n艇 8\n'.encode()}
        for name,data in payloads.items():(self.directory/name).write_bytes(data)
        self.pins={name:sha256(data).hexdigest() for name,data in payloads.items()}
        self.samples=np.linspace(-.2,.2,320,dtype=np.float32)
        self.calls=[];self.loads=[];self.load_hook=None;self.decode_hook=None
        self.tokens=['三','番','手','は','四','番'];self.text=''.join(self.tokens)
        self.times=[0.,.16,.32,.48,.64,.8]
        owner=self
        class Stream:
            def accept_waveform(self,rate,samples):
                self.samples=samples;self.rate=rate
        class Native:
            def create_stream(self):return Stream()
            def decode_stream(self,stream):
                owner.calls.append((stream.rate,stream.samples.copy()))
                if owner.decode_hook is not None:owner.decode_hook(stream)
                stream.result=SimpleNamespace(text=owner.text,tokens=list(owner.tokens),timestamps=list(owner.times))
        class Factory:
            @staticmethod
            def from_transducer(**kwargs):
                owner.loads.append(kwargs)
                if owner.load_hook is not None:owner.load_hook()
                return Native()
        backend=ModuleType('sherpa_onnx');backend.OfflineRecognizer=Factory
        self.addCleanup(patch.stopall)
        patch.dict(self.module.MODEL_FILES,self.pins,clear=True).start()
        patch.dict(sys.modules,{'sherpa_onnx':backend}).start()
        patch.object(self.module.metadata,'version',return_value='2.0.1').start()

    def recognizer(self,**kwargs):
        return self.module.PinnedReazonCommentaryRecognizer(self.directory,**kwargs)

    def test_official_padding_and_literal_tokens_preserve_source_clock_and_samples(self):
        recognizer=self.recognizer();before=self.samples.copy()
        result=recognizer(self.samples,sample_rate=16000)
        self.assertEqual(result['text'],'三番手は四番')
        self.assertEqual(result['raw_token_ids'],[1,2,3,4,5,2])
        self.assertEqual(len(self.calls),1);rate,padded=self.calls[0]
        self.assertEqual(rate,16000);self.assertEqual(len(padded),29120)
        self.assertTrue(np.array_equal(padded[14400:14720],before))
        self.assertTrue(np.all(padded[:14400]==0));self.assertTrue(np.all(padded[-14400:]==0))
        self.assertTrue(np.array_equal(self.samples,before))
        self.assertEqual(result['original_PCM_sha256'],sha256(before.tobytes()).hexdigest())
        self.assertEqual(result['padded_PCM_sha256'],sha256(padded.tobytes()).hexdigest())
        self.assertEqual(result['raw_model_token_emission_times_padded_seconds'],self.times)
        self.assertFalse(result['word_timestamps_used']);self.assertFalse(result['accuracy_validated'])
        self.assertEqual(result['quality_status'],'USABLE_UNVERIFIED')

    def test_default_is_official_greedy_without_hotwords_language_model_or_rules(self):
        recognizer=self.recognizer()
        config=self.loads[0]
        self.assertEqual(config['decoding_method'],'greedy_search')
        self.assertEqual(config['sample_rate'],16000);self.assertEqual(config['feature_dim'],80)
        self.assertEqual(config['dither'],0.);self.assertEqual(config['num_threads'],2)
        self.assertEqual(config['provider'],'cpu')
        for name in ('hotwords_file','lm','rule_fsts','rule_fars'):
            self.assertNotIn(name,config)
        meta=recognizer.metadata()
        self.assertEqual(meta['model_file_sha256'],self.pins)
        self.assertEqual(meta['model_revision'],'291488c8151be24d7da4bf7af26e533fad96e407')
        self.assertFalse(meta['context_vocabulary']);self.assertEqual(meta['network_requests'],0)
        self.assertFalse(meta['prediction_eligible']);self.assertFalse(meta['field_validated'])
        meta['model_file_sha256'].clear()
        self.assertEqual(recognizer.metadata()['model_file_sha256'],self.pins)

    def test_literal_out_of_race_range_text_is_not_repaired_into_a_boat_identity(self):
        self.text='7号艇';self.tokens=['7','号','艇'];self.times=[0.,.2,.4]
        result=self.recognizer()(self.samples)
        self.assertEqual(result['text'],'7号艇');self.assertEqual(result['raw_token_ids'],[6,7,8])
        self.assertFalse(result['accuracy_validated'])

    def test_non_boolean_context_flags_are_rejected(self):
        for flag in (1,None,'true'):
            with self.subTest(flag=flag),self.assertRaises(ValueError):self.recognizer(context_vocabulary=flag)
        self.assertEqual(self.loads,[])

    def add_generic_vocabulary_tokens(self):
        words=('展示','周回展示','展示航走','選手コメント','進入','進入コース','前付け','コース取り',
               '深い進入','起こし','前付けの強さ','前付けへの対応','スタート展示','スタート','踏み込み',
               'ターン','旋回','ターン出口','出足','行き足','加速','直線','伸び','モーター',
               'モーター性能','機力','舟足','調整','先頭','番手','追走','逃げ','差し','まくり','まくり差し','競り合い')
        path=self.directory/'tokens.txt';data=path.read_text()
        existing={line.rsplit(maxsplit=1)[0] for line in data.splitlines()}
        next_id=9
        for char in sorted(set(''.join(words))-existing):
            data+=f'{char} {next_id}\n';next_id+=1
        path.write_text(data);digest=sha256(path.read_bytes()).hexdigest()
        self.pins['tokens.txt']=digest;self.module.MODEL_FILES['tokens.txt']=digest
        return words

    def test_explicit_context_uses_frozen_generic_cjk_tokens_and_default_per_token_bias(self):
        words=self.add_generic_vocabulary_tokens();before=set(self.directory.iterdir())
        recognizer=self.recognizer(context_vocabulary=True);config=self.loads[0]
        self.assertEqual(config['decoding_method'],'modified_beam_search')
        self.assertEqual(config['max_active_paths'],4);self.assertEqual(config['modeling_unit'],'cjkchar')
        self.assertEqual(config['hotwords_score'],1.5)
        backend_path=Path(config['hotwords_file']);path=backend_path.resolve()
        self.assertTrue(str(backend_path).startswith('/proc/self/fd/'))
        expected=('\n'.join(' '.join(word) for word in words)+'\n').encode()
        self.assertEqual(path.read_bytes(),expected)
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(path.parent.stat().st_mode&0o777,0o700)
        self.assertNotEqual(path.parent,self.directory);self.assertEqual(before,set(self.directory.iterdir()))
        meta=recognizer.metadata();self.assertTrue(meta['context_vocabulary'])
        recipe=meta['recipe'];self.assertEqual(recipe['generic_vocabulary_count'],36)
        self.assertEqual(recipe['generic_vocabulary_source_sha256'],
                         '826161ff7eb3f73e26d11cbaa209debb2defa62d97c0f88c077a2c8d243e9994')
        self.assertEqual(recipe['generic_vocabulary_encoded_sha256'],
                         '76636e127716ff339026905d3fb72b9767ffb971e30891609522c2030478bfe7')
        self.assertEqual(recipe['hotwords_score_scope'],'DEFAULT_SCORE_PER_MODEL_TOKEN_NOT_PROBABILITY')
        self.assertFalse(meta['prediction_eligible']);self.assertFalse(recipe['text_repair'])
        self.assertEqual(recognizer(self.samples)['text'],self.text)
        del recognizer;gc.collect();self.assertFalse(path.exists());self.assertFalse(backend_path.exists())

    def test_context_missing_cjk_model_token_is_rejected_before_backend_load(self):
        with self.assertRaises(ValueError):self.recognizer(context_vocabulary=True)
        self.assertEqual(self.loads,[])

    def test_context_file_change_before_or_during_decode_is_rejected(self):
        self.add_generic_vocabulary_tokens();recognizer=self.recognizer(context_vocabulary=True)
        path=Path(self.loads[-1]['hotwords_file']);original=path.read_bytes()
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):recognizer(self.samples)
        self.assertEqual(self.calls,[])
        del recognizer
        recognizer=self.recognizer(context_vocabulary=True)
        path=Path(self.loads[-1]['hotwords_file'])
        self.decode_hook=lambda stream:path.write_bytes(original+b'changed')
        with self.assertRaises(ValueError):recognizer(self.samples)

    def test_context_write_restore_during_load_rejected_and_private_files_cleaned(self):
        self.add_generic_vocabulary_tokens();context_paths=[]
        def mutate():
            path=Path(self.loads[-1]['hotwords_file']);context_paths.append(path)
            before=path.stat();original=path.read_bytes()
            path.write_bytes(b'changed');path.write_bytes(original)
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.load_hook=mutate
        with self.assertRaises(ValueError):self.recognizer(context_vocabulary=True)
        self.assertTrue(context_paths);self.assertFalse(context_paths[0].exists())

    def test_native_loader_reads_pinned_bytes_during_restored_ancestor_redirection(self):
        mirror=tempfile.TemporaryDirectory();self.addCleanup(mirror.cleanup)
        mirror_root=Path(mirror.name);(mirror_root/'model').mkdir()
        for path in self.directory.iterdir():
            (mirror_root/'model'/path.name).write_bytes(b'UNPINNED_ANCESTOR_MIRROR')
        original=(self.directory/'encoder-epoch-99-avg-1.int8.onnx').read_bytes();observed=[]
        aside=self.root.with_name(self.root.name+'-held-original')
        def redirected_read():
            self.root.rename(aside);self.root.symlink_to(mirror_root,target_is_directory=True)
            try:observed.append(Path(self.loads[-1]['encoder']).read_bytes())
            finally:self.root.unlink();aside.rename(self.root)
        self.load_hook=redirected_read
        recognizer=self.recognizer()
        self.assertEqual(observed,[original])
        self.assertEqual(recognizer(self.samples)['text'],self.text)

    def test_loaded_asset_descriptors_are_held_for_lifetime_then_closed(self):
        recognizer=self.recognizer();paths=[Path(self.loads[-1][key])
            for key in ('encoder','decoder','joiner','tokens')]
        self.assertTrue(all(str(path).startswith('/proc/self/fd/') for path in paths))
        self.assertTrue(all(path.exists() for path in paths))
        self.assertEqual(paths[-1].read_bytes(),(self.directory/'tokens.txt').read_bytes())
        del recognizer;gc.collect()
        self.assertTrue(all(not path.exists() for path in paths))

    def test_native_loader_failure_closes_every_opened_asset_descriptor(self):
        descriptors=[];real_open=os.open
        def remember(*args,**kwargs):
            fd=real_open(*args,**kwargs);descriptors.append(fd);return fd
        def fail_load():raise RuntimeError('controlled native loader failure')
        self.load_hook=fail_load
        with patch.object(self.module.os,'open',side_effect=remember):
            with self.assertRaises(ValueError):self.recognizer()
        self.assertTrue(descriptors)
        for fd in descriptors:
            with self.subTest(fd=fd),self.assertRaises(OSError):os.fstat(fd)

    def test_interrupted_native_load_closes_descriptors_without_masking_interrupt(self):
        descriptors=[];real_open=os.open
        def remember(*args,**kwargs):
            fd=real_open(*args,**kwargs);descriptors.append(fd);return fd
        def interrupt():raise KeyboardInterrupt()
        self.load_hook=interrupt
        with patch.object(self.module.os,'open',side_effect=remember):
            with self.assertRaises(KeyboardInterrupt):self.recognizer()
        self.assertTrue(descriptors)
        for fd in descriptors:
            with self.subTest(fd=fd),self.assertRaises(OSError):os.fstat(fd)

    def test_wrong_asset_bytes_are_rejected_before_native_model_load(self):
        (self.directory/'encoder-epoch-99-avg-1.int8.onnx').write_bytes(b'OTHER')
        with self.assertRaises(ValueError):self.recognizer()
        self.assertEqual(self.loads,[])

    def test_extra_model_files_and_symlink_assets_are_rejected(self):
        extra=self.directory/'other.onnx';extra.write_bytes(b'EXTRA')
        with self.assertRaises(ValueError):self.recognizer()
        extra.unlink();asset=self.directory/'tokens.txt';target=self.root/'original-tokens.txt'
        asset.rename(target);asset.symlink_to(target)
        with self.assertRaises(ValueError):self.recognizer()
        self.assertEqual(self.loads,[])

    def test_remote_parent_traversal_and_symlink_directories_never_load_models(self):
        link=self.root/'link';link.symlink_to(self.directory,target_is_directory=True)
        for path in ('https://example.invalid/model','//example.invalid/model',self.root/'x'/'..'/'model',link):
            with self.subTest(path=str(path)),self.assertRaises(ValueError):
                self.module.PinnedReazonCommentaryRecognizer(path)
        self.assertEqual(self.loads,[])

    def test_asset_write_and_restore_during_load_invalidates_pinned_provenance(self):
        path=self.directory/'decoder-epoch-99-avg-1.int8.onnx';before=path.stat();data=path.read_bytes()
        def change_restore():
            path.write_bytes(b'TEMPORARY');path.write_bytes(data)
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.load_hook=change_restore
        with self.assertRaises(ValueError):self.recognizer()

    def test_asset_mutation_after_load_is_rejected_before_decode(self):
        recognizer=self.recognizer();(self.directory/'tokens.txt').write_text('changed')
        with self.assertRaises(ValueError):recognizer(self.samples)
        self.assertEqual(self.calls,[])

    def test_asset_mutation_during_decode_does_not_return_a_successful_receipt(self):
        recognizer=self.recognizer()
        self.decode_hook=lambda stream:(self.directory/'tokens.txt').write_text('changed')
        with self.assertRaises(ValueError):recognizer(self.samples)

    def test_persistent_caller_mutation_is_rejected_and_does_not_change_owned_model_input(self):
        recognizer=self.recognizer();original=self.samples.copy()
        self.decode_hook=lambda stream:self.samples.fill(.8)
        with self.assertRaises(ValueError):recognizer(self.samples)
        self.assertTrue(np.array_equal(self.calls[0][1][14400:14720],original))

    def test_temporary_caller_change_cannot_replace_the_owned_audio(self):
        recognizer=self.recognizer();original=self.samples.copy()
        def mutate_restore(stream):
            self.samples.fill(.8)
            self.assertTrue(np.array_equal(stream.samples[14400:14720],original))
            self.samples[:]=original
        self.decode_hook=mutate_restore
        self.assertEqual(recognizer(self.samples)['text'],'三番手は四番')

    def test_mutated_padding_buffer_is_rejected(self):
        recognizer=self.recognizer()
        self.decode_hook=lambda stream:stream.samples.fill(.9)
        with self.assertRaises(ValueError):recognizer(self.samples)

    def test_unmapped_model_tokens_or_text_without_matching_tokens_are_rejected(self):
        recognizer=self.recognizer();self.tokens.append('UNKNOWN');self.text=''.join(self.tokens);self.times.append(1.)
        with self.assertRaises(ValueError):recognizer(self.samples)
        self.tokens=self.tokens[:-1];self.times=self.times[:-1];self.text='unrelated text'
        with self.assertRaises(ValueError):recognizer(self.samples)

    def test_invalid_audio_types_shapes_lengths_rates_or_nonfinite_samples_never_decode(self):
        recognizer=self.recognizer()
        invalid=[[],self.samples.astype(np.float64),np.zeros((2,160),np.float32),
                 np.zeros(0,np.float32),np.zeros(480001,np.float32),
                 np.array([float('nan')],np.float32),np.array([float('inf')],np.float32)]
        for value in invalid:
            with self.subTest(kind=type(value).__name__),self.assertRaises(ValueError):recognizer(value)
        for rate in (8000,16000.,'16000',None,True):
            with self.subTest(rate=rate),self.assertRaises(ValueError):recognizer(self.samples,sample_rate=rate)
        self.assertEqual(self.calls,[])

    def test_exact_thirty_second_model_input_is_accepted_without_source_count_quota(self):
        result=self.recognizer()(np.zeros(480000,np.float32))
        self.assertEqual(result['source_samples'],480000)
        self.assertEqual(len(self.calls[0][1]),508800)

    def test_repetition_quality_is_retained_as_unverified_raw_without_repair(self):
        recognizer=self.recognizer();self.tokens=['三','番']*12;self.text=''.join(self.tokens)
        self.times=[i*.02 for i in range(len(self.tokens))]
        result=recognizer(self.samples)
        self.assertEqual(result['text'],self.text)
        self.assertEqual(result['quality_status'],'NEEDS_REVIEW_REPETITION')

    def test_runtime_version_drift_is_rejected(self):
        with patch.object(self.module.metadata,'version',return_value='9.0.0'):
            with self.assertRaises(ValueError):self.recognizer()
        self.assertEqual(self.loads,[])


if __name__=='__main__':unittest.main()
