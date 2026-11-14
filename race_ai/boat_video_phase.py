"""Local Japanese screen-label observations, not authenticated activity phases.

Full-frame sparse OCR with a fixed white-core fallback after a successful
unknown grayscale observation, and no truth-selected crop or homophone repair.
Explanatory mentions remain separate from candidate
current screen labels. Neither OCR nor repeated labels establish race identity.
"""
from collections import defaultdict
from copy import deepcopy
import csv
from fractions import Fraction
from hashlib import file_digest, sha256
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import unicodedata

from .boat_video_identity import _pixels


JPN_REVISION='87416418657359cb625c412a48b6e1d6d41c29bd'
JPN_SHA256='1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d'
SCHEMA='RACE_AI_JAPANESE_SCREEN_PHASE_OCR_V1'
TRACK_SCHEMA='RACE_AI_EXHIBITION_PHASE_CANDIDATES_V1'
_LABELS={'スタート展示':'EXHIBITION_START','周回展示':'EXHIBITION_LAP'}
_EXPLANATION=('とは','について','あります','行います','見せる','分か','わか',
              '解説','説明','ガイド','展示航走と','購入方法')
_MIN_CONFIDENCE=50.
_MAX_GAP=1.5


def _need(condition):
    if not condition:raise ValueError('BOAT_VIDEO_PHASE_REJECTED')


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _normalize(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))


def _word_box(value,width,height):
    _need(type(value) in (list,tuple) and len(value)==4 and all(_finite(x) for x in value))
    x,y,w,h=value
    _need(0<=x<x+w<=width and 0<=y<y+h<=height)
    return [float(x),float(y),float(w),float(h)]


def _classify(words):
    lines=defaultdict(list)
    for row in words:lines[tuple(row['line_key'])].append(row)
    found=set();supported=set();texts=[]
    for rows in lines.values():
        normalized='';support=[]
        for row in rows:
            text=_normalize(row['text']);normalized+=text
            support.extend([row['confidence']]*len(text))
        texts.append(normalized)
        for label,phase in _LABELS.items():
            for match in re.finditer(re.escape(label),normalized):
                found.add(phase)
                if min(support[match.start():match.end()])>=_MIN_CONFIDENCE:supported.add(phase)
    explanation=any(term in text for term in _EXPLANATION for text in texts)
    if len(found)>1:
        return dict(phase_candidate='UNKNOWN',mention_kind='AMBIGUOUS_PHASE_LABELS',
            detected_phase_labels=sorted(found),explanatory_context=explanation)
    if len(supported)==1:
        return dict(phase_candidate=next(iter(supported)),
            mention_kind='EXPLANATORY_MENTION' if explanation else 'SCREEN_LABEL_CANDIDATE',
            detected_phase_labels=sorted(found),explanatory_context=explanation)
    return dict(phase_candidate='UNKNOWN',mention_kind='LOW_OCR_SUPPORT' if found else 'NO_EXACT_PHASE_LABEL',
        detected_phase_labels=sorted(found),explanatory_context=explanation)


def _make_packet(frame,words,*,status,raw_tsv,reason=None,preprocessing=None,engine=None):
    width,height=_pixels(frame)
    _need(type(words) is list and len(words)<=40000)
    checked=[]
    for row in words:
        _need(type(row) is dict and set(row)=={'text','confidence','box','line_key'}
            and type(row['text']) is str and len(row['text'])<=20000
            and _finite(row['confidence']) and -1<=row['confidence']<=100
            and type(row['line_key']) is list and len(row['line_key'])==4
            and all(type(n) is int and n>=0 for n in row['line_key']))
        box=_word_box(row['box'],width,height)
        checked.append(dict(text=row['text'],confidence=float(row['confidence']),box=box,
                            line_key=list(row['line_key'])))
    _need(status in ('OCR_OBSERVATION','OCR_FAILED') and type(raw_tsv) is str and len(raw_tsv)<=4000000)
    classification=_classify(checked) if status=='OCR_OBSERVATION' else dict(
        phase_candidate='UNKNOWN',mention_kind='OCR_FAILURE',detected_phase_labels=[],explanatory_context=False)
    return dict(schema_version=SCHEMA,frame_sha256=sha256(frame.tobytes()).hexdigest(),
        coordinate_space='IMAGE_PX',width=width,height=height,status=status,failure_reason=reason,
        words=checked,raw_text='\n'.join(row['text'] for row in checked),raw_tsv=raw_tsv,
        preprocessing=deepcopy(preprocessing),engine=deepcopy(engine),**classification,
        scores_are_calibrated_probabilities=False,verified_current_activity=False,
        semantic_scene_verified=False,usable_for_identity=False,production_eligible=False)


def _with_ocr_views(frame,views):
    """Retain each raw observation and classify without joining views' lines."""
    _need(type(views) is list and 1<=len(views)<=2)
    checked=[];words=[];page_offset=0
    for view in views:
        _need(type(view) is dict)
        observation=_make_packet(frame,view['words'],status=view['status'],raw_tsv=view['raw_tsv'],
            reason=view.get('failure_reason'),preprocessing=view.get('preprocessing'),engine=view.get('engine'))
        _need(view==observation)
        checked.append(observation)
        if observation['status']!='OCR_OBSERVATION':continue
        for word in observation['words']:
            word=deepcopy(word)
            # The raw page/line keys remain untouched in ocr_views. Namespace
            # aggregate pages so unrelated OCR views cannot synthesize a label.
            word['line_key'][0]+=page_offset
            words.append(word)
        page_offset=max((word['line_key'][0] for word in words),default=-1)+1
    primary=checked[0]
    if len(checked)==2:
        _need(primary['status']=='OCR_OBSERVATION' and primary['phase_candidate']=='UNKNOWN')
    packet=_make_packet(frame,words,status=primary['status'],raw_tsv=primary['raw_tsv'],
        reason=primary['failure_reason'],preprocessing=primary['preprocessing'],engine=primary['engine'])
    packet['ocr_views']=checked
    return packet


def _path(value,*,directory=False,executable=False):
    raw=os.fspath(value)
    _need(type(raw) is str and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',raw)
          and not raw.startswith('//') and '..' not in Path(raw).parts)
    path=Path(raw).absolute()
    _need(not any(p.is_symlink() for p in (path,*path.parents)))
    info=path.lstat()
    _need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    if executable:_need(os.access(path,os.X_OK))
    return path


def _pin(path):
    before=path.lstat();_need(stat.S_ISREG(before.st_mode) and not path.is_symlink())
    with path.open('rb') as source:digest=file_digest(source,'sha256').hexdigest()
    after=path.lstat()
    identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    _need(identity(before)==identity(after))
    return dict(sha256=digest,identity=identity(after))


class LocalJapanesePhaseReader:
    """Explicit local Tesseract+jpn assets; never downloads or selects an ROI."""
    def __init__(self,tesseract_path,tessdata_path):
        try:
            binary=_path(tesseract_path,executable=True)
            directory=_path(tessdata_path,directory=True)
            asset=_path(directory/'jpn.traineddata')
            binary_pin,asset_pin=_pin(binary),_pin(asset)
            _need(asset_pin['sha256']==JPN_SHA256)
            result=subprocess.run([str(binary),'--version'],capture_output=True,check=True,timeout=20)
            version=result.stdout.decode('utf-8',errors='strict').splitlines()[0]
            _need(version.startswith('tesseract ') and _pin(binary)==binary_pin and _pin(asset)==asset_pin)
            self._binary,self._directory,self._asset=binary,directory,asset
            self._binary_pin,self._asset_pin=binary_pin,asset_pin
            self._metadata=dict(engine='LOCAL_TESSERACT_JAPANESE',version=version,
                binary_sha256=binary_pin['sha256'],jpn_revision=JPN_REVISION,
                jpn_sha256=asset_pin['sha256'],psm=11,language='jpn',full_frame=True,
                preprocessing='GRAYSCALE_SCALE_MIN_2_AND_1920_OVER_MAX_DIM_LINEAR',
                fallback_preprocessing='FULL_FRAME_SCALED_GRAY_GT200_BINARY_INVERSE_IF_SUCCESSFUL_GRAY_UNKNOWN',
                minimum_word_confidence=_MIN_CONFIDENCE,
                confidence_scope='RAW_TESSERACT_WORD_SCORE_NOT_PROBABILITY',
                source_scope='SCREEN_TEXT_NOT_AUTHENTICATED_CURRENT_ACTIVITY',network_requests=0)
        except (OSError,ValueError,TypeError,subprocess.SubprocessError,UnicodeError,IndexError):
            raise ValueError('BOAT_VIDEO_PHASE_READER_SETUP_REJECTED') from None

    def metadata(self):return deepcopy(self._metadata)

    def __call__(self,frame):
        _pixels(frame);digest=sha256(frame.tobytes()).hexdigest()
        image=frame.copy();_need(sha256(image.tobytes()).hexdigest()==digest)
        primary=self._read_view(image,frame,digest,white_core=False)
        views=[primary]
        if primary['status']=='OCR_OBSERVATION' and primary['phase_candidate']=='UNKNOWN':
            views.append(self._read_view(image,frame,digest,white_core=True))
        return _with_ocr_views(image,views)

    def _read_view(self,image,source,digest,*,white_core):
        import cv2
        width,height=_pixels(image)
        words=[];raw='';prep=None
        try:
            _need(_pin(self._binary)==self._binary_pin and _pin(self._asset)==self._asset_pin
                and sha256(source.tobytes()).hexdigest()==digest and sha256(image.tobytes()).hexdigest()==digest)
            scale=min(2.,1920/max(width,height))
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            target=(round(width*scale),round(height*scale))
            if target!=(width,height):gray=cv2.resize(gray,target,interpolation=cv2.INTER_LINEAR)
            if white_core:gray=cv2.threshold(gray,200,255,cv2.THRESH_BINARY_INV)[1]
            encoded,png=cv2.imencode('.png',gray);_need(encoded)
            prep=dict(kind='FULL_FRAME_INVERTED_WHITE_CORE' if white_core else 'FULL_FRAME_GRAYSCALE',
                scale=scale,width=gray.shape[1],height=gray.shape[0],
                scale_x=gray.shape[1]/width,scale_y=gray.shape[0]/height,
                interpolation='LINEAR',processed_png_sha256=sha256(png.tobytes()).hexdigest())
            if white_core:prep.update(gray_threshold=200,comparison='GREATER_THAN',binary_inverse=True)
            environment=os.environ.copy();environment['OMP_THREAD_LIMIT']='1'
            result=subprocess.run([str(self._binary),'stdin','stdout','--tessdata-dir',str(self._directory),
                '-l','jpn','--psm','11','-c','tessedit_create_tsv=1'],input=png.tobytes(),capture_output=True,check=True,timeout=20,
                env=environment)
            _need(len(result.stdout)<=4000000)
            raw=result.stdout.decode('utf-8',errors='strict')
            rows=csv.DictReader(io.StringIO(raw),delimiter='\t')
            _need(rows.fieldnames==['level','page_num','block_num','par_num','line_num','word_num',
                                   'left','top','width','height','conf','text'])
            for row in rows:
                if row['level']!='5' or not row['text']:continue
                x,y,w,h=[int(row[key]) for key in ('left','top','width','height')]
                _need(x>=0 and y>=0 and w>0 and h>0 and x+w<=target[0] and y+h<=target[1])
                left,top=x/prep['scale_x'],y/prep['scale_y']
                right,bottom=(x+w)/prep['scale_x'],(y+h)/prep['scale_y']
                words.append(dict(text=row['text'],confidence=float(row['conf']),
                    box=[left,top,right-left,bottom-top],
                    line_key=[int(row[k]) for k in ('page_num','block_num','par_num','line_num')]))
            _need(_pin(self._binary)==self._binary_pin and _pin(self._asset)==self._asset_pin
                and sha256(source.tobytes()).hexdigest()==digest and sha256(image.tobytes()).hexdigest()==digest)
            return _make_packet(image,words,status='OCR_OBSERVATION',raw_tsv=raw,
                preprocessing=prep,engine=self._metadata)
        except (OSError,ValueError,TypeError,KeyError,UnicodeError,subprocess.SubprocessError,cv2.error):
            return _make_packet(image,[],status='OCR_FAILED',raw_tsv=raw,
                reason='LOCAL_PHASE_OCR_OR_SOURCE_INTEGRITY_FAILURE',preprocessing=prep,engine=self._metadata)


class ExhibitionPhaseTracker:
    """Confirm repeated screen labels causally, never certify current activity."""
    def __init__(self,reader):
        _need(callable(reader));self.reader=reader
        self._state=None;self._seen=set();self._time=self._index=self._scene=self._shape=None

    def update(self,frame,*,t,frame_index,scene):
        width,height=_pixels(frame)
        _need(_finite(t) and t>=0 and type(frame_index) is int and frame_index>=0
              and type(scene) is int and scene>=0 and (self._time is None or t>self._time and frame_index>self._index)
              and (self._scene is None or scene>=self._scene))
        digest=sha256(frame.tobytes()).hexdigest();image=frame.copy()
        _need(sha256(image.tobytes()).hexdigest()==digest)
        flags=set()
        try:
            callback=image.copy();packet=self.reader(callback)
            _need(type(packet) is dict and packet.get('schema_version')==SCHEMA
                and packet.get('frame_sha256')==digest and sha256(callback.tobytes()).hexdigest()==digest)
            if 'ocr_views' in packet:
                checked=_with_ocr_views(image,packet['ocr_views'])
                _need(packet==checked)
            else:
                checked=_make_packet(image,packet['words'],status=packet['status'],raw_tsv=packet['raw_tsv'],
                    reason=packet.get('failure_reason'),preprocessing=packet.get('preprocessing'),engine=packet.get('engine'))
            _need(all(packet[k]==checked[k] for k in ('phase_candidate','mention_kind','detected_phase_labels','explanatory_context')))
            packet=checked
        except (Exception,):
            flags.add('INVALID_READER_PACKET')
            packet=_make_packet(image,[],status='OCR_FAILED',raw_tsv='',reason='INVALID_READER_PACKET')
        reset=(self._time is None or self._scene!=scene or self._shape!=(width,height)
               or Fraction(str(t))-Fraction(str(self._time))>=Fraction(str(_MAX_GAP)))
        state=deepcopy(self._state);closed=[]
        candidate=packet['phase_candidate'] if packet['mention_kind']=='SCREEN_LABEL_CANDIDATE' else 'UNKNOWN'
        if reset or candidate=='UNKNOWN' or state is not None and state['phase_label']!=candidate:
            if state is not None and len(state['observations'])>=2:
                closed.append(deepcopy(state['interval']))
            state=None
        if reset:flags.add('CALLER_SCENE_SHAPE_OR_TIME_RESET')
        fresh=digest not in self._seen
        if candidate!='UNKNOWN':
            if state is None:state=dict(phase_label=candidate,observations=[],interval=None,distinct_count=0)
            if fresh:
                state['observations']=(state['observations']+[dict(frame_index=frame_index,t=float(t),frame_sha256=digest)])[-20:]
                state['distinct_count']+=1
            else:flags.add('REPEATED_FRAME_PIXELS')
        phase='UNKNOWN';interval=None
        if state is not None and len(state['observations'])>=2:
            phase=candidate
            interval=dict(phase_label=candidate,source_scene=scene,
                first_observed_t=(state['interval']['first_observed_t'] if state['interval'] else state['observations'][0]['t']),confirmed_from_t=(state['interval']['confirmed_from_t']
                    if state['interval'] else state['observations'][1]['t']),last_observed_t=float(t),
                first_frame_index=(state['interval']['first_frame_index'] if state['interval'] else state['observations'][0]['frame_index']),last_frame_index=frame_index,
                distinct_frame_observations=state['distinct_count'],
                scope='REPEATED_SCREEN_LABEL_CANDIDATE_NOT_ACTIVITY_GROUND_TRUTH')
            state['interval']=deepcopy(interval)
        out=dict(schema_version=TRACK_SCHEMA,frame_sha256=digest,t=float(t),frame_index=frame_index,scene=scene,
            phase=phase,phase_candidate=packet['phase_candidate'],ocr=packet,observed_interval=interval,
            closed_intervals=closed,distinct_observations=state['distinct_count'] if state else 0,
            fresh_observation_added=bool(candidate!='UNKNOWN' and fresh),quality_flags=sorted(flags),
            source_scene_scope='CALLER_DECLARED_NOT_SEMANTIC_SCENE_DETECTION',
            verified_current_activity=False,semantic_scene_verified=False,
            usable_for_identity=False,model_eligible=False,production_eligible=False)
        _need(sha256(frame.tobytes()).hexdigest()==digest and sha256(image.tobytes()).hexdigest()==digest)
        seen=set(self._seen)
        seen.add(digest)
        result=deepcopy(out)
        next_time=float(t);next_shape=(width,height)
        self._state,self._seen,self._time,self._index,self._scene,self._shape=state,seen,next_time,frame_index,scene,next_shape
        return result
