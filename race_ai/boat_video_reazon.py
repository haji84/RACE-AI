"""Optional pinned native Japanese ASR, with no speech or race accuracy claim.

The official recipe adds synthetic zero padding. Its emission timestamps are
model-input diagnostics, never measured word times on the original audio.
Nothing here downloads assets, repairs words or assigns a boat/rank identity.
"""
from copy import deepcopy
from hashlib import file_digest, sha256
from importlib import metadata
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import weakref

from .boat_video_commentary import _quality


MODEL_ID='reazon-research/reazonspeech-k2-v2'
MODEL_REVISION='291488c8151be24d7da4bf7af26e533fad96e407'
OFFICIAL_RECIPE_REVISION='2d4d4762e7ee294ac8e47a177ac2e9b0e8d0d43f'
MODEL_FILES={
    'encoder-epoch-99-avg-1.int8.onnx':'2c7bd08a8a99f9ddd0d9e458456577b1f6279214e51426f114f9eced44c54e1d',
    'decoder-epoch-99-avg-1.int8.onnx':'8f0bff94d38797b03b762634ed03211a8e303d06cc4603cdd0cf4199d6eb1485',
    'joiner-epoch-99-avg-1.int8.onnx':'49cc7ea1d3d35a40a27442db5e89996da64bf0e683a903dce76e99e57a12e4de',
    'tokens.txt':'2c3ac659818a48a0c04010e0593bbc4d7c8a24a054340b01131499c05fd52def'}
_SAMPLE_RATE=16000
_PADDING_SAMPLES=14400
_MAX_SAMPLES=30*_SAMPLE_RATE
_RUNTIME_VERSION='2.0.1'
# Frozen from public boat terminology, independently of the evaluation speech.
# These phrases bias acoustic decoding only; there are no boat/rank assignments.
_CONTEXT_VOCABULARY=(
    '展示','周回展示','展示航走','選手コメント','進入','進入コース','前付け','コース取り',
    '深い進入','起こし','前付けの強さ','前付けへの対応','スタート展示','スタート','踏み込み',
    'ターン','旋回','ターン出口','出足','行き足','加速','直線','伸び','モーター',
    'モーター性能','機力','舟足','調整','先頭','番手','追走','逃げ','差し','まくり','まくり差し','競り合い')
_CONTEXT_SOURCE_SHA256='826161ff7eb3f73e26d11cbaa209debb2defa62d97c0f88c077a2c8d243e9994'
_CONTEXT_ENCODED_SHA256='76636e127716ff339026905d3fb72b9767ffb971e30891609522c2030478bfe7'


def _need(condition):
    if not condition:raise ValueError('BOAT_VIDEO_REAZON_REJECTED')


def _identity(value):
    return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns


def _snapshot(directory,expected):
    """Bind real files and ctimes before/after a held descriptor's SHA read."""
    _need(not any(p.is_symlink() for p in (directory,*directory.parents)))
    info=directory.lstat();_need(stat.S_ISDIR(info.st_mode))
    names={p.name for p in directory.iterdir()}
    _need(set(expected)<=names and names<=set(expected)|{'README.md'})
    pins={}
    for name in sorted(names):
        path=directory/name;before=path.lstat()
        maximum=2*1024*1024 if name=='README.md' else 256*1024*1024
        _need(stat.S_ISREG(before.st_mode) and not path.is_symlink()
              and 0<=before.st_size<=maximum)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as source:
            _need(_identity(os.fstat(source.fileno()))==_identity(before))
            digest=file_digest(source,'sha256').hexdigest()
            after_fd=os.fstat(source.fileno())
        after=path.lstat()
        _need(_identity(before)==_identity(after_fd)==_identity(after)
              and (name not in expected or digest==expected[name]))
        pins[name]=(digest,_identity(after))
    _need(_identity(directory.lstat())==_identity(info))
    return _identity(info),pins


def _close_descriptors(descriptors):
    for fd in reversed(descriptors):
        try:os.close(fd)
        except OSError:pass


def _hold_assets(directory,snapshot):
    """Open pinned files relative to a held directory, never a later pathname.

    The native loader receives these descriptors through procfs. Restoring an
    ancestor after redirecting its path cannot substitute the bytes it reads.
    """
    descriptors=[]
    try:
        directory_fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        descriptors.append(directory_fd)
        _need(_identity(os.fstat(directory_fd))==snapshot[0])
        held={}
        for name,(expected,identity) in snapshot[1].items():
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
            descriptors.append(fd)
            before=os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and _identity(before)==identity)
            with os.fdopen(os.dup(fd),'rb') as source:digest=file_digest(source,'sha256').hexdigest()
            os.lseek(fd,0,os.SEEK_SET)
            _need(_identity(os.fstat(fd))==identity and digest==expected)
            held[name]=fd
        _need(_identity(os.fstat(directory_fd))==snapshot[0])
        return descriptors,held
    except BaseException:
        _close_descriptors(descriptors)
        raise


def _descriptor_path(fd):
    return f'/proc/self/fd/{fd}'


def _vocabulary(text):
    result={};ids=set()
    for line in text.splitlines():
        token,number=line.rsplit(maxsplit=1)
        index=int(number)
        _need(token and token not in result and index>=0 and index not in ids)
        result[token]=index;ids.add(index)
    _need(result)
    return result


class PinnedReazonCommentaryRecognizer:
    """Local official greedy default, or explicit generic-vocabulary decoding."""
    def __init__(self,model_path,*,context_vocabulary=False):
        context_directory=None;descriptors=[]
        try:
            _need(type(context_vocabulary) is bool)
            raw=os.fspath(model_path)
            _need(type(raw) is str and raw and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',raw)
                  and not raw.startswith('//') and '..' not in Path(raw).parts)
            directory=Path(raw).absolute();files=dict(MODEL_FILES)
            snapshot=_snapshot(directory,files)
            asset_descriptors,held_assets=_hold_assets(directory,snapshot)
            descriptors.extend(asset_descriptors)
            tokens_fd=held_assets['tokens.txt']
            vocabulary=_vocabulary(os.pread(tokens_fd,os.fstat(tokens_fd).st_size,0).decode('utf-8'))
            import numpy as np
            import sherpa_onnx
            versions={name:metadata.version(name) for name in ('sherpa-onnx','sherpa-onnx-core')}
            _need(all(version==_RUNTIME_VERSION for version in versions.values()))
            versions['numpy']=np.__version__
            context_args={};context_snapshot=None
            if context_vocabulary:
                source=('\n'.join(_CONTEXT_VOCABULARY)+'\n').encode('utf-8')
                encoded=('\n'.join(' '.join(word) for word in _CONTEXT_VOCABULARY)+'\n').encode('utf-8')
                _need(sha256(source).hexdigest()==_CONTEXT_SOURCE_SHA256
                      and sha256(encoded).hexdigest()==_CONTEXT_ENCODED_SHA256
                      and all(char in vocabulary for word in _CONTEXT_VOCABULARY for char in word))
                context_directory=Path(tempfile.mkdtemp(prefix='race-ai-reazon-context-'))
                os.chmod(context_directory,0o700)
                context_path=context_directory/'context.txt'
                fd=os.open(context_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as output:output.write(encoded)
                context_snapshot=_snapshot(context_directory,{'context.txt':_CONTEXT_ENCODED_SHA256})
                context_descriptors,held_context=_hold_assets(context_directory,context_snapshot)
                descriptors.extend(context_descriptors)
                context_args=dict(hotwords_file=_descriptor_path(held_context['context.txt']),hotwords_score=1.5,
                    modeling_unit='cjkchar',max_active_paths=4)
            decoder='modified_beam_search' if context_vocabulary else 'greedy_search'
            recognizer=sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=_descriptor_path(held_assets['encoder-epoch-99-avg-1.int8.onnx']),
                decoder=_descriptor_path(held_assets['decoder-epoch-99-avg-1.int8.onnx']),
                joiner=_descriptor_path(held_assets['joiner-epoch-99-avg-1.int8.onnx']),
                tokens=_descriptor_path(tokens_fd),num_threads=2,sample_rate=16000,
                feature_dim=80,dither=0.,decoding_method=decoder,provider='cpu',**context_args)
            _need(_snapshot(directory,files)==snapshot)
            if context_directory is not None:
                _need(_snapshot(context_directory,{'context.txt':_CONTEXT_ENCODED_SHA256})==context_snapshot)
            recipe=dict(official_recipe_revision=OFFICIAL_RECIPE_REVISION,
                sample_rate=16000,feature_dim=80,dither=0.,decoder=decoder,
                provider='cpu',num_threads=2,synthetic_zero_padding_per_side_samples=14400,
                padding_is_observed_future_audio=False,amplitude_normalization=False,
                context_vocabulary=context_vocabulary,hotwords=context_vocabulary,external_language_model=False,
                text_repair=False,native_asset_reads='PINNED_HELD_REGULAR_FILE_DESCRIPTORS')
            if context_vocabulary:
                recipe.update(generic_vocabulary_count=len(_CONTEXT_VOCABULARY),
                    generic_vocabulary_source_sha256=_CONTEXT_SOURCE_SHA256,
                    generic_vocabulary_encoded_sha256=_CONTEXT_ENCODED_SHA256,
                    hotwords_score=1.5,
                    hotwords_score_scope='DEFAULT_SCORE_PER_MODEL_TOKEN_NOT_PROBABILITY',
                    modeling_unit='cjkchar',max_active_paths=4,
                    generic_vocabulary_contains_rank_boat_assignments=False)
            self._directory,self._files,self._snapshot=directory,files,snapshot
            self._held_assets=held_assets
            self._descriptors=tuple(descriptors)
            self._context_directory,self._context_snapshot=context_directory,context_snapshot
            if context_directory is not None:
                self._context_cleanup=weakref.finalize(self,shutil.rmtree,context_directory,ignore_errors=True)
            self._vocabulary,self._recognizer=vocabulary,recognizer
            self._recipe=recipe
            self._metadata=dict(model_profile='reazon-k2-v2-int8',model_id=MODEL_ID,
                model_revision=MODEL_REVISION,model_file_sha256=files,
                license='Apache-2.0',runtime_versions=versions,recipe=deepcopy(recipe),
                context_vocabulary=context_vocabulary,local_files_only=True,network_requests=0,
                word_timestamps_used=False,estimated_word_timestamps_used=False,
                field_validated=False,prediction_eligible=False,production_eligible=False,
                raw_scores_are_calibrated_probabilities=False)
            self._descriptor_cleanup=weakref.finalize(self,_close_descriptors,self._descriptors)
        except BaseException as error:
            _close_descriptors(descriptors)
            if context_directory is not None:shutil.rmtree(context_directory,ignore_errors=True)
            if isinstance(error,(OSError,ImportError,TypeError,ValueError,RuntimeError,AttributeError,OverflowError)):
                raise ValueError('BOAT_VIDEO_REAZON_MODEL_REJECTED') from None
            raise

    def _guard(self):
        _need(_snapshot(self._directory,self._files)==self._snapshot)
        _need(all(_identity(os.fstat(fd))==self._snapshot[1][name][1]
                  for name,fd in self._held_assets.items()))
        if self._context_directory is not None:
            _need(_snapshot(self._context_directory,{'context.txt':_CONTEXT_ENCODED_SHA256})==self._context_snapshot
                  and stat.S_IMODE(self._context_directory.stat().st_mode)==0o700
                  and stat.S_IMODE((self._context_directory/'context.txt').stat().st_mode)==0o600)

    def metadata(self):
        self._guard()
        return deepcopy(self._metadata)

    def __call__(self,samples,*,sample_rate=_SAMPLE_RATE):
        try:
            import numpy as np
            _need(type(samples) is np.ndarray and samples.dtype==np.float32 and samples.ndim==1
                  and 0<len(samples)<=_MAX_SAMPLES and type(sample_rate) is int
                  and sample_rate==_SAMPLE_RATE and np.isfinite(samples).all())
            digest=sha256(samples.tobytes()).hexdigest();owned=samples.copy()
            _need(sha256(owned.tobytes()).hexdigest()==digest)
            self._guard()
            padded=np.pad(owned,_PADDING_SAMPLES,mode='constant')
            padded_digest=sha256(padded.tobytes()).hexdigest()
            stream=self._recognizer.create_stream()
            stream.accept_waveform(_SAMPLE_RATE,padded)
            self._recognizer.decode_stream(stream)
            result=stream.result
            text=result.text;tokens=list(result.tokens);times=list(result.timestamps)
            _need(type(text) is str and len(text)<=20000 and all(type(t) is str for t in tokens)
                  and ''.join(tokens)==text and len(times)==len(tokens)
                  and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in times)
                  and all(t in self._vocabulary for t in tokens))
            ids=[self._vocabulary[t] for t in tokens]
            self._guard()
            _need(sha256(samples.tobytes()).hexdigest()==digest
                  and sha256(owned.tobytes()).hexdigest()==digest
                  and sha256(padded.tobytes()).hexdigest()==padded_digest)
            return dict(text=text,raw_token_ids=ids,raw_model_tokens=tokens,
                quality_status=_quality(text,ids),word_timestamps_used=False,
                accuracy_validated=False,original_PCM_sha256=digest,
                padded_PCM_sha256=padded_digest,source_samples=len(owned),sample_rate=_SAMPLE_RATE,
                synthetic_zero_padding_per_side_samples=_PADDING_SAMPLES,
                raw_model_token_emission_times_padded_seconds=[float(t) for t in times],
                emission_timestamp_scope='PADDED_MODEL_INPUT_DIAGNOSTIC_NOT_SOURCE_WORD_TIMES',
                raw_token_ids_scope='LOOKUP_OF_RAW_MODEL_TOKEN_STRINGS_IN_PINNED_VOCABULARY',
                recipe=deepcopy(self._recipe))
        except (OSError,ImportError,TypeError,ValueError,RuntimeError,AttributeError,KeyError,OverflowError):
            raise ValueError('BOAT_VIDEO_REAZON_AUDIO_REJECTED') from None
