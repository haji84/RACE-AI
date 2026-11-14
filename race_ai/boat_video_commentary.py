"""Optional offline Japanese speech observations, not race identity/results.

Only local pinned weights and a held local media descriptor are used. Audio
chunks retain the actual media PTS clock and cannot be available before the
whole recognizer input has ended. Estimated word timestamps are not used.
"""
from copy import deepcopy
import fcntl
from hashlib import file_digest, sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess

from .boat_video_tracking import _options, _probe_json, _PROTOCOL_ARGS


MODEL_REVISION='169d4a4341b33bc18d8881c4b69c2e104e1cc0af'
MODEL_FILES={
    'model.safetensors':'7ebd0e69e78190ffe1438491fa05cc1f5c1aa3a4c4db3bc1723adbb551ea2395',
    'config.json':'ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98',
    'generation_config.json':'a5d5325911f16e74001a72fa13d6e208eee51548f994646de1f4b4cc8b35b512',
    'preprocessor_config.json':'9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666',
    'tokenizer_config.json':'2a4c4281cf9f51ac6ccc406fdc711a087afe6530f671fa7b80953edc498275ce',
    'tokenizer.json':'27fc476bfe7f17299480be2273fc0608e4d5a99aba2ab5dec5374b4482d1a566',
    'vocab.json':'8f680bba319e01a653d2e8a5dbc17a9157179e0576e6ce74ce0c06356c6e24f9',
    'merges.txt':'2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6',
    'normalizer.json':'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd',
    'added_tokens.json':'9715fd2243b6f06a5858b5e32950d2853f73dd5bc201aafcf76f5082a2d8acd1',
    'special_tokens_map.json':'e67ae3a0aaa99abcd9f187138e12db1f65c16a14761c50ef10eef2c174a7a691'}
KOTOBA_MODEL_REVISION='7eb575277d18909a4af8a24e3ae8cce2e99794ae'
KOTOBA_MODEL_FILES={
    'model.safetensors':'0a96a84e307bbb90128a9fd5a45b4f803be212aadef633e24c088fa1ba30f727',
    'config.json':'65d5e7e4c8bb84a04edeff0a04fa422de14d9d38c3152f6869d4275dec9cc60c',
    'generation_config.json':'748d850251411dc53679b1a01ecacd44d25b37a8498cc2ccc0457f4b0c06d82f',
    'preprocessor_config.json':'7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711',
    'tokenizer_config.json':'c86c7398ba7f81f784569ea0ae165e252c4a006acc56906f04e5ee3300cf043e',
    'tokenizer.json':'f70c9740a90657b489cf05b0fa0605c1d497db542f11a70a8cc80a025c94c7d8',
    'vocab.json':'6788c80b082e9b0d1393147d3a3e62ba19285ac0c82ace8e5ef00f37ead58971',
    'merges.txt':'2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6',
    'normalizer.json':'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd',
    'added_tokens.json':'3c51f66c4c21f9e126970078f11ae77a78c74aee8df606ee9daba86e467108e0',
    'special_tokens_map.json':'baea4ea09372eb4fca86b4e4346139fd73cb807d5087e9de0948e971739c3e74'}
_PHASES={'RACE','EXHIBITION_LAP','EXHIBITION_START','UNKNOWN'}
_SAMPLE_RATE=16000
_CHUNK_SAMPLES=30*_SAMPLE_RATE
_MINIMUM_CUE_AUDIO_RMS=.001


def _need(condition):
    if not condition:raise ValueError('BOAT_VIDEO_COMMENTARY_REJECTED')


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _quality(text,tokens):
    _need(type(text) is str and type(tokens) is list)
    if len(tokens)>=440:return 'NEEDS_REVIEW_LENGTH_LIMIT'
    normalized=re.sub(r'\s+','',text)
    if re.search(r'(.{2,20})\1{3,}',normalized):return 'NEEDS_REVIEW_REPETITION'
    if not normalized:return 'NO_SPEECH_TEXT'
    return 'USABLE_UNVERIFIED'


class PinnedCommentaryRecognizer:
    """Explicit local pinned ASR profiles; no download or model training."""
    def __init__(self,*,model_path,model_profile='whisper-tiny'):
        try:
            _need(type(model_profile) is str and model_profile in ('whisper-tiny','kotoba-v2'))
            kotoba=model_profile=='kotoba-v2'
            files=dict(KOTOBA_MODEL_FILES if kotoba else MODEL_FILES)
            raw=os.fspath(model_path)
            _need(type(raw) is str and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',raw)
                  and not raw.startswith('//') and '..' not in Path(raw).parts)
            directory=Path(raw).absolute()
            _need(directory.is_dir() and not any(p.is_symlink() for p in (directory,*directory.parents)))
            _need({p.name for p in directory.iterdir()} <= set(files)|{'README.md'})
            pins={};identities={}
            for name,expected in files.items():
                path=directory/name;before=path.lstat()
                _need(stat.S_ISREG(before.st_mode) and not path.is_symlink())
                with path.open('rb') as source:actual=file_digest(source,'sha256').hexdigest()
                after=path.lstat()
                _need(actual==expected and (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                      (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns))
                pins[name]=actual
                identities[name]=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            processor=WhisperProcessor.from_pretrained(directory,local_files_only=True)
            attention='sdpa' if kotoba else 'eager'
            load_options=dict(local_files_only=True,use_safetensors=True,attn_implementation=attention)
            if kotoba:load_options['dtype']=torch.float32
            model=WhisperForConditionalGeneration.from_pretrained(directory,**load_options).to('cpu').eval()
            # Loading must not race a writer after the initial pin check. ctime
            # also catches a write/restore of the same bytes during loading.
            for name,expected in files.items():
                path=directory/name;before=path.lstat()
                _need(stat.S_ISREG(before.st_mode) and not path.is_symlink())
                with path.open('rb') as source:actual=file_digest(source,'sha256').hexdigest()
                after=path.lstat()
                current=lambda value:(value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
                _need(actual==expected and current(before)==current(after)==identities[name])
            self._processor,self._model,self._torch=processor,model,torch
            self._generation=dict(language='ja',task='transcribe',do_sample=False,return_timestamps=False)
            if kotoba:
                # Match the frozen Japanese-profile decoder without prompts,
                # answer repair, or forcing expected boat names/numbers.
                self._generation.update(num_beams=1,temperature=0.,condition_on_prev_tokens=False,prompt_ids=None)
            else:
                self._generation['max_new_tokens']=440
            self._metadata=dict(model_profile=model_profile,
                model_id='kotoba-tech/kotoba-whisper-v2.0' if kotoba else 'openai/whisper-tiny',
                model_revision=KOTOBA_MODEL_REVISION if kotoba else MODEL_REVISION,
                model_file_sha256=pins,local_files_only=True,network_requests=0,language='ja',
                task='transcribe',do_sample=False,attention_mask_supplied=True,
                attention_implementation=attention,
                dtype_policy='EXPLICIT_CPU_FLOAT32' if kotoba else 'EXISTING_BACKEND_DEFAULT',
                generation_options=deepcopy(self._generation),
                estimated_word_timestamps_used=False,field_validated=False,
                raw_scores_are_calibrated_probabilities=False)
        except (OSError,ImportError,TypeError,ValueError):
            raise ValueError('BOAT_VIDEO_COMMENTARY_MODEL_REJECTED') from None

    def metadata(self):return deepcopy(self._metadata)

    def __call__(self,samples,*,sample_rate=_SAMPLE_RATE):
        import numpy as np
        _need(type(samples) is np.ndarray and samples.ndim==1 and samples.dtype==np.float32
              and 0<len(samples)<=_CHUNK_SAMPLES and sample_rate==_SAMPLE_RATE
              and np.isfinite(samples).all())
        original=sha256(samples.tobytes()).hexdigest();image=samples.copy()
        _need(sha256(image.tobytes()).hexdigest()==original)
        features=self._processor(image,sampling_rate=sample_rate,return_tensors='pt',return_attention_mask=True)
        with self._torch.inference_mode():
            result=self._model.generate(**features,**self._generation)
        tokens=result[0].tolist()
        text=self._processor.batch_decode(result,skip_special_tokens=True)[0]
        _need(sha256(samples.tobytes()).hexdigest()==original)
        return dict(text=text,raw_token_ids=tokens,quality_status=_quality(text,tokens),
                    word_timestamps_used=False,accuracy_validated=False)


def _audio_timeline(data,maximum_duration):
    """Validate actual decoded frame PTS/sample counts, not advertised duration."""
    try:
        streams=data['streams'];frames=data.get('frames',[])
        _need(type(streams) is list and len(streams)<=1)
        if not streams:return None
        rate=int(streams[0]['sample_rate']);_need(1<=rate<=384000 and frames)
        numerator,denominator=map(int,streams[0]['time_base'].split('/'))
        _need(numerator>0 and denominator>0);quantum=numerator/denominator
        # A whole-second or otherwise coarse clock cannot justify subsecond
        # PCM concatenation. Millisecond Matroska and normal sample clocks fit.
        _need(quantum<=.001)
        tolerance=max(2/rate,quantum)+.000001
        first=None;last=None;total=0
        for row in frames:
            stamp=float(row['pts_time']);count=row['nb_samples']
            _need(math.isfinite(stamp) and type(count) is int and count>0)
            if first is None:first=stamp
            if last is not None:_need(abs(stamp-last)<=tolerance)
            last=stamp+count/rate;total+=count
        duration=total/rate
        _need(0<duration<=maximum_duration and abs(last-first-duration)<=tolerance)
        return dict(start_pts=first,duration_seconds=duration,input_sample_rate=rate,
            input_sample_count=total,decoded_audio_frames=len(frames),
            PTS_continuity_tolerance_seconds=tolerance)
    except (KeyError,TypeError,ZeroDivisionError,OverflowError,ValueError):
        raise ValueError('BOAT_VIDEO_COMMENTARY_AUDIO_TIMELINE_REJECTED') from None


def _source_pin(source,path,expected,maximum_bytes):
    _need(path==f'/proc/self/fd/{source.fileno()}' and type(expected) is str
          and re.fullmatch(r'[0-9a-f]{64}',expected))
    before=os.fstat(source.fileno())
    _need(stat.S_ISREG(before.st_mode) and 0<before.st_size<=maximum_bytes)
    _need(fcntl.fcntl(source.fileno(),fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY)
    offset=source.tell();source.seek(0)
    try:actual=file_digest(source,'sha256').hexdigest()
    finally:source.seek(offset)
    after=os.fstat(source.fileno())
    pin=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    _need(actual==expected and pin(before)==pin(after))
    return pin(after)


def transcribe_commentary(source,path,*,media_sha256,options,recognizer,phase,window_seconds=5.):
    """Return source-bound context and raw private diagnostics for all chunks.

    Short five-second windows reduce stale running-order cues. Thirty seconds
    is the maximum model input size, not an acquisition count/GET/runtime cap.
    All chunks are processed. Per-input media bounds reject the entire analysis.
    No estimated word timestamps are promoted to measured source timing.
    """
    import numpy as np
    settings=_options(options)
    _need(type(phase) is str and phase in _PHASES)
    _need(_finite(window_seconds) and 0<window_seconds<=30)
    chunk_samples=round(window_seconds*_SAMPLE_RATE)
    _need(1<=chunk_samples<=_CHUNK_SAMPLES)
    pin=_source_pin(source,path,media_sha256,settings['max_bytes'])
    data=_probe_json(source,path,['-select_streams','a:0','-show_streams','-show_frames',
        '-show_entries','stream=sample_rate,time_base:frame=pts_time,nb_samples'],
        settings['processing_timeout_seconds'],settings['max_pixels'])
    timeline=_audio_timeline(data,settings['max_duration_seconds'])
    context=dict(schema_version='RACE_AI_BOAT_BROADCAST_CONTEXT_V1',media_sha256=media_sha256,
                 exhibition_order=None,segments=[])
    metadata=dict(audio_status='NO_AUDIO',media_sha256=media_sha256,chunks=[],chunk_count=0,
        audio_timeline=timeline,prediction_eligible=False,production_eligible=False,
        estimated_word_timestamps_used=False,latency_calibrated=False,
        cue_validity_seconds=2.,sample_rate=_SAMPLE_RATE,network_requests=0)
    metadata.update(window_seconds=chunk_samples/_SAMPLE_RATE,
                    requested_window_seconds=float(window_seconds),maximum_model_input_seconds=30.,
                    recognizer_calls=0,low_signal_chunks=0,
                    signal_policy=dict(minimum_cue_audio_RMS=_MINIMUM_CUE_AUDIO_RMS,
                        scope='LOW_SIGNAL_ABSTENTION_NOT_VALIDATED_SPEECH_ABSENCE'))
    if timeline is not None:
        _need(callable(recognizer) and callable(getattr(recognizer,'metadata',None)))
        producer=recognizer.metadata()
        producer_raw=json.dumps(producer,sort_keys=True,allow_nan=False).encode()
        producer_sha=sha256(producer_raw).hexdigest()
        metadata['recognizer']=json.loads(producer_raw)
        command=['ffmpeg','-nostdin','-v','error','-xerror','-threads','1',*_PROTOCOL_ARGS,
            # Raw PCM has no timestamps. Its source clock is independently
            # bound by the validated decoded-frame timeline above. copyts
            # would make output -t end before a large absolute starting PTS.
            '-i',path,'-map','0:a:0','-vn','-sn','-dn','-ac','1','-ar',str(_SAMPLE_RATE),
            '-t',str(settings['max_duration_seconds']+1/_SAMPLE_RATE),'-f','f32le','pipe:1']
        try:
            decoded=subprocess.run(command,capture_output=True,check=True,
                timeout=settings['processing_timeout_seconds'],pass_fds=(source.fileno(),))
            _need(not decoded.stderr.strip())
        except (OSError,subprocess.SubprocessError):
            raise ValueError('BOAT_VIDEO_COMMENTARY_AUDIO_DECODE_FAILED') from None
        _need(len(decoded.stdout)%4==0)
        audio=np.frombuffer(decoded.stdout,dtype='<f4').copy()
        expected=round(timeline['input_sample_count']*_SAMPLE_RATE/timeline['input_sample_rate'])
        _need(0<len(audio)<=math.ceil(settings['max_duration_seconds']*_SAMPLE_RATE)
              and abs(len(audio)-expected)<=2 and np.isfinite(audio).all())
        metadata.update(audio_status='TRANSCRIBED_UNVERIFIED',decoded_sample_count=len(audio),
            audio_pcm_sha256=sha256(decoded.stdout).hexdigest(),resample_count_tolerance_samples=2)
        for position in range(0,len(audio),chunk_samples):
            samples=audio[position:position+chunk_samples].copy()
            pcm_sha=sha256(samples.tobytes()).hexdigest()
            signal_rms=float(np.sqrt(np.mean(samples.astype(np.float64)**2)))
            signal_peak=float(np.max(np.abs(samples)))
            if signal_rms<_MINIMUM_CUE_AUDIO_RMS:
                raw=dict(text='',raw_token_ids=[],quality_status='NEEDS_REVIEW_LOW_SIGNAL',recognizer_invoked=False)
                metadata['low_signal_chunks']+=1
            else:
                raw=recognizer(samples,sample_rate=_SAMPLE_RATE)
                metadata['recognizer_calls']+=1
            _need(sha256(samples.tobytes()).hexdigest()==pcm_sha and type(raw) is dict
                  and type(raw.get('text')) is str and len(raw['text'])<=20000
                  and type(raw.get('quality_status')) is str)
            raw=json.loads(json.dumps(raw,allow_nan=False))
            start=timeline['start_pts']+position/_SAMPLE_RATE
            end=start+len(samples)/_SAMPLE_RATE
            quality=raw['quality_status']
            if quality=='USABLE_UNVERIFIED':
                quality=_quality(raw['text'],raw.get('raw_token_ids',[]))
            metadata['chunks'].append(dict(start_pts=start,end_pts=end,
                audio_pcm_sha256=pcm_sha,quality_status=quality,raw_recognition=raw,
                signal_rms=signal_rms,signal_peak=signal_peak))
            if quality=='USABLE_UNVERIFIED':
                context['segments'].append(dict(text=raw['text'],phase=phase,start_pts=start,end_pts=end,
                    available_from_pts=end,valid_until_pts=end+2.,audio_pcm_sha256=pcm_sha,
                    producer_sha256=producer_sha,producer_kind='ASR_LOCAL_UNVERIFIED',exhibition_pass_index=None))
        metadata['chunk_count']=len(metadata['chunks'])
        if metadata['recognizer_calls']==0:
            metadata['audio_status']='LOW_SIGNAL_AUDIO_UNRESOLVED'
    _need(_source_pin(source,path,media_sha256,settings['max_bytes'])==pin)
    return context,metadata
