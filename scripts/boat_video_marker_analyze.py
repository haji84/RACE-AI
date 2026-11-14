"""Opt-in local all-frame marker diagnostics; no field, race or forecast claim.

Models are explicit pinned local assets. Nothing is downloaded. A single-shot
declaration is caller supplied, not authenticated by automatic shot detection.
"""
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256, file_digest
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai.boat_video_tracking import _options, _local_media, _metadata, _decode
from race_ai.private_cycle_capture import _parent_handle


ERROR = 'BOAT_VIDEO_MARKER_ANALYSIS_FAILED'
SCHEMA = 'RACE_AI_BOAT_MARKER_LOCAL_DIAGNOSTIC_V1'
POLICY = 'DEVELOPMENT_GLYPH_CLASSIFIER'


class _Failure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Never echo rejected input paths or argument values.
        raise _Failure('ARGUMENTS_REJECTED')


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _local_path(value):
    if (not isinstance(value, str) or not value or '\x00' in value
            or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value)
            or value.startswith('//') or '..' in Path(value).parts):
        raise _Failure('LOCAL_PATH_REQUIRED')
    return Path(value).absolute()


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


@contextmanager
def _new_directory(path):
    with _parent_handle(path.parent) as parent:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            os.fchmod(descriptor, 0o700)
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise _Failure('PRIVATE_OUTPUT_REQUIRED')
            os.fsync(parent)
            yield descriptor
        finally:
            os.close(descriptor)


def _terminal(directory, name, record):
    """Publish a complete create-only terminal record, never a partial SUCCESS."""
    raw, temporary = _bytes(record), '.' + name + '.pending'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    published = False
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        published = True
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    except BaseException:
        for remove in ([name, temporary] if published else [temporary]):
            try:
                os.unlink(remove, dir_fd=directory)
            except OSError:
                pass
        raise
    return sha256(raw).hexdigest()


def _pipeline(args, factory, *, media_sha256=None, source_context=None):
    if args.phase_only:
        pipeline=None
        metadata=dict(execution_mode=('LOCAL_SCREEN_CONTENT_CANDIDATES' if args.activity_model is not None
                                     else 'LOCAL_SCREEN_PHASE_CANDIDATES'),pinned_models=True)
    elif args.clothing_only:
        pipeline = None
        metadata = dict(execution_mode='PINNED_LOCAL_DEVELOPMENT_CLOTHING',pinned_models=True)
    elif factory is not None:
        pipeline, metadata = factory(refresh_frames=args.refresh_frames, label_policy=POLICY), dict(
            execution_mode='INJECTED_SYNTHETIC_TEST', pinned_models=False,
            injected_metadata='SYNTHETIC_TEST_CALLBACKS_NOT_PINNED_MODELS')
    else:
        from race_ai.boat_video_ppocr import PinnedPPOCRRecognizer
        from race_ai.boat_video_marker_verifier import PinnedDevelopmentMarkerVerifier
        from race_ai.boat_video_marker_pipeline import MarkerIdentityPipeline, CLASSIFIER_POLICY
        recognizer = PinnedPPOCRRecognizer(model_path=args.recognizer_model)
        verifier = PinnedDevelopmentMarkerVerifier(context_model_path=args.context_model,
            glyph_model_path=args.glyph_model, development_opt_in=True)
        pipeline = MarkerIdentityPipeline(recognizer, verifier, refresh_frames=args.refresh_frames,
                                          label_policy=CLASSIFIER_POLICY)
        metadata = dict(execution_mode='PINNED_LOCAL_DEVELOPMENT_MODELS', pinned_models=True,
                        recognizer=recognizer.metadata(), verifier=verifier.metadata())
    if args.rider_model is not None:
        from race_ai.boat_video_rider_detector import PinnedRiderPartDetector
        from race_ai.boat_video_rider_tracking import RiderPartTracker
        detector = PinnedRiderPartDetector(model_path=args.rider_model, tiled=True)
        riders = RiderPartTracker(detector, number_provider=None)
        if not args.anonymous_riders:
            from race_ai.boat_video_clothing_identity import ClothingColorIdentityTracker
            riders = ClothingColorIdentityTracker(riders)
        pipeline = _MarkerAndRiderPipeline(pipeline, riders)
        metadata['rider_part_tracking'] = dict(
            execution_scope=metadata['execution_mode'], detector=detector.metadata(),
            number_binding=('NOT_IMPLEMENTED_NO_NUMBER_PRODUCER' if args.anonymous_riders
                            else 'CLOTHING_COLOR_CURRENT_PIXEL_HYPOTHESIS'),
            printed_numbers_required=False,
            garment_segmentation_validated=False,
            marker_numbers_assigned_to_riders=False, hull_positions_inferred=False,
            model_eligible=False)
    if args.phase_tessdata is not None:
        from race_ai.boat_video_phase import LocalJapanesePhaseReader, ExhibitionPhaseTracker
        reader=LocalJapanesePhaseReader(tesseract_path=args.phase_tesseract,tessdata_path=args.phase_tessdata)
        pipeline=_ScreenPhasePipeline(pipeline,ExhibitionPhaseTracker(reader))
        metadata['phase_detection']=dict(reader=reader.metadata(),sampling_interval_seconds=1.,
            sampling_scope='OCR_SAMPLING_ONLY_EVERY_VIDEO_FRAME_IS_JOURNALED',
            automatic_current_activity_validated=False,model_eligible=False)
    if args.activity_model is not None:
        from race_ai.boat_video_activity import LocalPrimaryWaterReader
        reader=LocalPrimaryWaterReader(model_path=args.activity_model,boat_model_path=args.activity_boat_model)
        pipeline=_PrimaryWaterPipeline(pipeline,reader,media_sha256=media_sha256,source_context=source_context)
        metadata['primary_water_detection']=dict(reader=reader.metadata(),sampling_interval_seconds=1.,
            sampling_scope='CONTENT_SAMPLES_ONLY_EVERY_VIDEO_FRAME_IS_JOURNALED',
            sampling_clock_resolution_seconds=.000001,sampling_schedule='ANCHORED_ONE_SECOND_GRID',
            context_scope='DECLARED_SOURCE_TOPIC_NOT_EVENT_AUTHENTICATION',
            authenticated_current_exhibition=False,model_eligible=False)
    return pipeline, metadata


class _MarkerAndRiderPipeline:
    """Keep two independent observations; proximity does not establish pairing."""
    def __init__(self, markers, riders):
        self.markers, self.riders = markers, riders

    def update(self, frame, **context):
        riders = self.riders.update(frame, **context)
        result = (dict(schema_version='RACE_AI_CLOTHING_COLOR_PIPELINE_V1',
            frame_index=riders['frame_index'],t=riders['t'],scene=riders['scene'],
            frame_sha256=riders['frame_sha256'],identity_validated=False,model_eligible=False)
            if self.markers is None else self.markers.update(frame, **context))
        result['rider_part_tracking'] = riders
        return result


class _ScreenPhasePipeline:
    """Sample OCR while preserving every decoded frame and its original clock."""
    def __init__(self,base,tracker):
        self.base,self.tracker=base,tracker
        self.next_sample=None;self.scene=None

    def update(self,frame,**context):
        digest=sha256(frame.tobytes()).hexdigest()
        result=(self.base.update(frame,**context) if self.base is not None else dict(
            schema_version='RACE_AI_SCREEN_PHASE_PIPELINE_V1',frame_sha256=digest,
            identity_validated=False,model_eligible=False,**context))
        fresh=(self.next_sample is None or context['scene']!=self.scene or context['t']>=self.next_sample)
        observation=None
        if fresh:
            observation=self.tracker.update(frame,**context)
            self.next_sample=context['t']+1.;self.scene=context['scene']
        result['phase_detection']=dict(frame_sha256=digest,frame_index=context['frame_index'],
            source_pts=None,fresh_observation=fresh,observation=observation,
            unobserved_frames_are_not_filled=True,usable_for_identity=False)
        return result


def _read_topic_context(path, media_sha256):
    from race_ai.boat_video_capture import _read_private, _json
    context=_json(_read_private(path,maximum=4096))
    if (type(context) is not dict or set(context)!={'schema_version','media_sha256','topic','provenance_sha256'}
        or context['schema_version']!='RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1'
        or context['media_sha256']!=media_sha256
        or context['topic'] not in ('UNKNOWN','EXHIBITION_TUTORIAL','EXHIBITION_BROADCAST')
        or type(context['provenance_sha256']) is not str
        or re.fullmatch('[0-9a-f]{64}',context['provenance_sha256']) is None):
        raise _Failure('EXHIBITION_CONTEXT_REJECTED')
    return context


class _PrimaryWaterPipeline:
    """Observe current source pixels; source topic never authenticates an event."""
    def __init__(self,base,reader,*,media_sha256,source_context):
        self.base,self.reader=base,reader
        self.media_sha256,self.source_context=media_sha256,source_context
        self.next_sample=None;self.scene=None
        self.intervals=_SampledContentIntervals()

    def update(self,frame,**context):
        digest=sha256(frame.tobytes()).hexdigest()
        result=(self.base.update(frame,**context) if self.base is not None else dict(
            schema_version='RACE_AI_PRIMARY_WATER_PIPELINE_V1',frame_sha256=digest,
            identity_validated=False,model_eligible=False,**context))
        # ffprobe's pts_time clock is recorded to microseconds. Normalize only
        # the sampling comparison, never the recorded source/relative PTS, so
        # floating-point subtraction cannot skip an exact one-second point.
        clock=Fraction(str(round(context['t'],6)))
        reset=self.next_sample is None or context['scene']!=self.scene
        fresh=reset or clock>=self.next_sample
        observation=None
        if fresh:
            observation=self.reader(frame,media_sha256=self.media_sha256,source_context=self.source_context)
            if (type(observation) is not dict or observation.get('frame_sha256')!=digest
                or observation.get('media_sha256')!=self.media_sha256
                or sha256(frame.tobytes()).hexdigest()!=digest):
                raise _Failure('ACTIVITY_OBSERVATION_REJECTED')
            values={key:observation.get(key) if observation.get('status')=='CONTENT_OBSERVATION'
                    and type(observation.get(key)) is bool else None for key in self.intervals.KEYS}
            self.intervals.update(t=context['t'],scene=context['scene'],frame_sha256=digest,**values)
            self.next_sample=(clock+1 if reset else self.next_sample+int(clock-self.next_sample)+1)
            self.scene=context['scene']
        result['primary_water_detection']=dict(frame_sha256=digest,frame_index=context['frame_index'],
            source_pts=None,fresh_observation=fresh,observation=observation,
            unobserved_frames_are_not_filled=True,usable_for_identity=False)
        return result


class _SampledContentIntervals:
    """Group measured positive samples, preserving unmeasured boundaries."""
    KEYS=('primary_water_content_candidate','primary_aquatic_content_candidate',
          'depicted_exhibition_content_candidate')

    def __init__(self):
        self.active={key:None for key in self.KEYS}
        self.closed={key:[] for key in self.KEYS}
        self.before={key:None for key in self.KEYS}
        self.distinct={key:set() for key in self.KEYS};self.time=None;self.scene=None

    def _close(self,key,*,negative=None,reason):
        state=self.active[key]
        if state is not None and state['distinct_positive_samples']>=2:
            row=deepcopy(state)
            row.update(first_negative_after_t=negative,right_boundary_censored=negative is None,
                       right_censor_reason=reason if negative is None else None)
            self.closed[key].append(row)
        self.active[key]=None
        self.distinct[key].clear()

    def update(self,*,t,scene,frame_sha256,**positive):
        if self.time is not None and t<=self.time:
            raise _Failure('ACTIVITY_SAMPLE_CLOCK_REJECTED')
        reset=(self.time is not None and (scene!=self.scene or
            Fraction(str(t))-Fraction(str(self.time))>=Fraction('1.5')))
        if reset:
            for key in self.KEYS:
                self._close(key,reason='SCENE_OR_TIME_GAP')
                self.before[key]=None
        for key in self.KEYS:
            if positive.get(key) is None:
                self._close(key,reason='UNKNOWN_CONTENT_OBSERVATION')
                self.before[key]=None
            elif not positive[key]:
                self._close(key,negative=float(t),reason='NEGATIVE_OBSERVATION')
                self.before[key]=float(t)
            else:
                row=self.active[key]
                if row is None:
                    row=dict(first_observed_t=float(t),last_observed_t=float(t),confirmed_from_t=None,
                        last_negative_before_t=self.before[key],first_negative_after_t=None,
                        distinct_positive_samples=0,sampled_points_only=True,
                        unobserved_frames_are_not_filled=True,time_basis='RELATIVE_VIDEO_PTS_SECONDS',
                        right_boundary_censored=True,right_censor_reason='INPUT_END_OR_NOT_YET_CLOSED',
                        authenticated_current_exhibition=False,usable_for_identity=False)
                    self.active[key]=row
                row['last_observed_t']=float(t)
                if frame_sha256 not in self.distinct[key]:
                    self.distinct[key].add(frame_sha256)
                    row['distinct_positive_samples']+=1
                    if row['distinct_positive_samples']==2:row['confirmed_from_t']=float(t)
        self.time=float(t);self.scene=scene

    def summary(self):
        result=deepcopy(self.closed)
        for key,row in self.active.items():
            if row is not None and row['distinct_positive_samples']>=2:
                result[key].append(deepcopy(row))
        return result


def _summary(status, count, **extra):
    print(json.dumps(dict(status=status, decoded_frames=count, **extra), sort_keys=True))


def main(argv=None, *, pipeline_factory=None):
    """Injection is an explicit synthetic transport test, never pinned inference."""
    parser = _Parser(description=__doc__)
    parser.add_argument('--media', required=True)
    parser.add_argument('--output-dir', required=True, help='new private directory outside Git')
    parser.add_argument('--recognizer-model')
    parser.add_argument('--context-model')
    parser.add_argument('--glyph-model')
    parser.add_argument('--rider-model', help='pinned local YOLOX; person parts with primary clothing-colour candidates')
    parser.add_argument('--clothing-only',action='store_true',
                        help='track clothing colours without OCR or printed-number models')
    parser.add_argument('--anonymous-riders',action='store_true',
                        help='retain anonymous rider output without colour identity')
    parser.add_argument('--phase-only',action='store_true',help='automatic screen-phase candidates without identity models')
    parser.add_argument('--phase-tesseract',help='explicit local Tesseract executable for screen phase')
    parser.add_argument('--phase-tessdata',help='private directory with pinned jpn.traineddata')
    parser.add_argument('--activity-model',help='explicit pinned local primary-water semantic model directory')
    parser.add_argument('--activity-boat-model',help='explicit pinned local YOLOX boat model for content observations')
    parser.add_argument('--exhibition-topic-context',help='private same-media declared topic JSON; not event authentication')
    broadcast=parser.add_mutually_exclusive_group()
    broadcast.add_argument('--broadcast-context',help='private source-bound exhibition/commentary context JSON')
    broadcast.add_argument('--commentary-model',help='optional pinned local speech model directory; no download')
    parser.add_argument('--commentary-profile',choices=('whisper-tiny','kotoba-v2',
                        'reazon-k2-v2-int8','reazon-k2-v2-int8-context'),default='whisper-tiny',
                        help='explicit pinned local speech profile; no production forecast switch')
    parser.add_argument('--broadcast-phase',choices=('UNKNOWN','EXHIBITION_LAP','EXHIBITION_START','RACE'),
                        default='UNKNOWN',help='declared speech phase; unknown does not assign identity cues')
    parser.add_argument('--commentary-window-seconds',type=float,default=5.,
                        help='local speech input window, at most30seconds; every audio chunk is processed')
    parser.add_argument('--development', action='store_true', required=True)
    parser.add_argument('--single-continuous-shot', action='store_true',
                        help='caller declaration; no automatic shot authentication')
    parser.add_argument('--refresh-frames', type=int, default=1,
                        help='discovery refresh interval; every frame is still processed')
    parser.add_argument('--processing-timeout-seconds', type=float, default=7200.)
    parser.add_argument('--max-duration-seconds', type=float, default=120.)
    parser.add_argument('--max-decoded-frames', type=int, default=3600)
    parser.add_argument('--max-bytes', type=int, default=268435456)
    parser.add_argument('--max-pixels', type=int, default=2073600)
    parser.add_argument('--max-dimension', type=int, default=1920)
    parser.add_argument('--source-role', choices=('LOCAL_DEVELOPMENT_VIDEO', 'SYNTHETIC_TEST'),
                        default='LOCAL_DEVELOPMENT_VIDEO')
    count, started = 0, _utc()
    try:
        args = parser.parse_args(argv)
        if args.refresh_frames <= 0 or (pipeline_factory is not None and
                                        args.source_role != 'SYNTHETIC_TEST'):
            raise _Failure('ARGUMENTS_REJECTED')
        if not args.phase_only and not args.single_continuous_shot:
            raise _Failure('ARGUMENTS_REJECTED')
        if (args.phase_only and (args.clothing_only or args.rider_model is not None
                               or (args.phase_tessdata is None and args.activity_model is None) or args.broadcast_context is not None
                               or args.commentary_model is not None)
            or args.clothing_only and (args.rider_model is None or args.anonymous_riders)
            or not (args.clothing_only or args.phase_only) and any(getattr(args,key) is None for key in
                                             ('recognizer_model','context_model','glyph_model'))):
            raise _Failure('ARGUMENTS_REJECTED')
        if (args.phase_tesseract is None)!=(args.phase_tessdata is None):
            raise _Failure('ARGUMENTS_REJECTED')
        if ((args.activity_model is None)!=(args.activity_boat_model is None)
            or args.exhibition_topic_context is not None and args.activity_model is None):
            raise _Failure('ARGUMENTS_REJECTED')
        if (args.broadcast_context is not None or args.commentary_model is not None) and (
            args.rider_model is None or args.anonymous_riders):
            raise _Failure('ARGUMENTS_REJECTED')
        if args.commentary_profile!='whisper-tiny' and args.commentary_model is None:
            raise _Failure('ARGUMENTS_REJECTED')
        for field in ('media', 'output_dir', 'recognizer_model', 'context_model', 'glyph_model'):
            if getattr(args,field) is not None:
                setattr(args, field, _local_path(getattr(args, field)))
        if args.rider_model is not None:
            args.rider_model = _local_path(args.rider_model)
        for field in ('broadcast_context','commentary_model','phase_tesseract','phase_tessdata',
                      'activity_model','activity_boat_model','exhibition_topic_context'):
            if getattr(args,field) is not None:
                setattr(args,field,_local_path(getattr(args,field)))
        guards = {key: getattr(args, key) for key in ('processing_timeout_seconds',
                  'max_duration_seconds', 'max_decoded_frames', 'max_bytes', 'max_pixels', 'max_dimension')}
        options = _options(guards)
        with _new_directory(args.output_dir) as directory:
            digest, probed, journal_digest = None, None, sha256()
            stage = 'MEDIA_VALIDATION_FAILED'
            try:
                import numpy as np
                descriptor = os.open('frames.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory)
                with os.fdopen(descriptor, 'wb') as journal:
                    os.fchmod(journal.fileno(), 0o600)
                    with _local_media(args.media, options) as (source, source_path, digest, container):
                        initial_ctime_ns = os.fstat(source.fileno()).st_ctime_ns
                        width, height, duration, pts = _metadata(source, source_path, options)
                        probed = len(pts)
                        stage = 'MODEL_SETUP_FAILED'
                        topic_context=None;topic_sha=None
                        if args.exhibition_topic_context is not None:
                            topic_context=_read_topic_context(args.exhibition_topic_context,digest)
                            topic_sha=_terminal(directory,'exhibition-topic-context.json',topic_context)
                        pipeline, metadata = _pipeline(args, pipeline_factory,
                            media_sha256=digest,source_context=topic_context)
                        if args.activity_model is not None:
                            metadata['primary_water_detection']['source_context_file_sha256']=topic_sha
                        broadcast_context=None
                        if args.broadcast_context is not None or args.commentary_model is not None:
                            stage='BROADCAST_CONTEXT_SETUP_FAILED'
                            from race_ai.boat_video_broadcast_context import BroadcastIdentityContext
                            if args.broadcast_context is not None:
                                from race_ai.boat_video_capture import _read_private, _json
                                context=_json(_read_private(args.broadcast_context,maximum=2*1024*1024))
                                producer='LOCAL_DECLARED_CONTEXT'
                            else:
                                from race_ai.boat_video_commentary import PinnedCommentaryRecognizer, transcribe_commentary
                                if args.commentary_profile.startswith('reazon-'):
                                    from race_ai.boat_video_reazon import PinnedReazonCommentaryRecognizer
                                    recognizer=PinnedReazonCommentaryRecognizer(model_path=args.commentary_model,
                                        context_vocabulary=args.commentary_profile.endswith('-context'))
                                else:
                                    recognizer=PinnedCommentaryRecognizer(model_path=args.commentary_model,
                                        model_profile=args.commentary_profile)
                                context,speech=transcribe_commentary(source,source_path,media_sha256=digest,
                                    options=options,recognizer=recognizer,phase=args.broadcast_phase,
                                    window_seconds=args.commentary_window_seconds)
                                _terminal(directory,'commentary-receipt.json',speech)
                                producer='LOCAL_PINNED_ASR_UNVERIFIED'
                            broadcast_context=BroadcastIdentityContext(context,media_sha256=digest)
                            context_sha=_terminal(directory,'broadcast-context.json',context)
                            metadata['broadcast_context']=dict(file_sha256=context_sha,source=producer,
                                time_basis='ABSOLUTE_MEDIA_PTS_SECONDS',prediction_eligible=False,
                                official_results=False)
                        stage = 'FRAME_ANALYSIS_FAILED'
                        with closing(_decode(source, source_path, width, height, options, np)) as decoded:
                            for index, image in enumerate(decoded):
                                if index >= probed:
                                    raise _Failure('FRAME_COUNT_MISMATCH')
                                original_sha = sha256(image.tobytes()).hexdigest()
                                relative = pts[index] - pts[0]
                                result = pipeline.update(image, t=relative, frame_index=index, scene=0)
                                if 'phase_detection' in result:
                                    result['phase_detection']['source_pts']=pts[index]
                                if 'primary_water_detection' in result:
                                    result['primary_water_detection']['source_pts']=pts[index]
                                if broadcast_context is not None:
                                    result['rider_part_tracking']=broadcast_context.annotate(
                                        result['rider_part_tracking'],source_pts=pts[index])
                                if (type(result) is not dict or result.get('frame_index') != index
                                        or result.get('t') != relative
                                        or result.get('frame_sha256') != original_sha
                                        or sha256(image.tobytes()).hexdigest() != original_sha):
                                    raise _Failure('PIPELINE_RESULT_REJECTED')
                                raw = _bytes(dict(schema_version='RACE_AI_BOAT_MARKER_FRAME_JOURNAL_V1',
                                    media_sha256=digest, frame_index=index, source_pts=pts[index],
                                    t=relative, decoded_bgr_sha256=original_sha, pipeline_result=result))
                                journal.write(raw)
                                journal.flush()
                                journal_digest.update(raw)
                                count += 1
                        if count != probed:
                            raise _Failure('FRAME_COUNT_MISMATCH')
                        if isinstance(pipeline,_PrimaryWaterPipeline):
                            metadata['primary_water_detection']['observed_content_intervals']=pipeline.intervals.summary()
                        stage = 'MEDIA_IMMUTABILITY_FAILED'
                        before_hash_ctime_ns = os.fstat(source.fileno()).st_ctime_ns
                        source.seek(0)
                        final_digest = file_digest(source, 'sha256').hexdigest()
                        after_hash_ctime_ns = os.fstat(source.fileno()).st_ctime_ns
                        if (final_digest != digest or before_hash_ctime_ns != initial_ctime_ns
                                or after_hash_ctime_ns != initial_ctime_ns):
                            raise _Failure('MEDIA_IMMUTABILITY_FAILED')
                    # A SUCCESS can only follow the held-source immutable exit.
                    journal.flush()
                    os.fsync(journal.fileno())
                stage = 'RECEIPT_PERSIST_FAILED'
                receipt = dict(schema_version=SCHEMA, status='SUCCESS', started_at_real_utc=started,
                    completed_at_real_utc=_utc(), media_sha256=digest, source_role=args.source_role,
                    decoded_frames=count, probed_frames=probed, width=width, height=height,
                    source_first_pts=pts[0], source_last_pts=pts[-1], relative_last_t=pts[-1]-pts[0],
                    displayed_duration_seconds=duration, journal_sha256=journal_digest.hexdigest(),
                    frame_sampling='NONE_EVERY_DECODED_FRAME', refresh_frames=args.refresh_frames,
                    resource_guards=guards, development_opt_in=True,
                    label_policy=('SAMPLED_SCREEN_CONTENT_CANDIDATES' if args.phase_only and args.activity_model is not None
                                  else 'SCREEN_PHASE_TEXT_CANDIDATE' if args.phase_only
                                  else 'CLOTHING_COLOR' if args.clothing_only else POLICY),
                    shot_scope=('MULTI_SHOT_SCREEN_PHASE_ONLY_NO_IDENTITY_CONTINUITY' if args.phase_only
                                else 'CALLER_DECLARED_SINGLE_CONTINUOUS_SHOT_NOT_AUTHENTICATED'),
                    classifier_label_scope='DISCRETE_DEVELOPMENT_CLASSIFICATION_NOT_PROBABILITY',
                    field_validation='NOT_ESTABLISHED', identity_validated=False, model_eligible=False,
                    network_requests=0, **metadata)
                receipt_sha = _terminal(directory, 'receipt.json', receipt)
            except (Exception, KeyboardInterrupt) as failure:
                code = failure.code if isinstance(failure, _Failure) else stage
                record = dict(schema_version=SCHEMA, status='FAILED', failure_code=code,
                    started_at_real_utc=started, completed_at_real_utc=_utc(),
                    media_sha256=digest, decoded_frames=count, probed_frames=probed,
                    partial_journal=True, model_eligible=False, identity_validated=False)
                try:
                    _terminal(directory, 'failure.json', record)
                except (Exception, KeyboardInterrupt):
                    pass
                _summary('FAILED', count, failure_code=code)
                print(ERROR, file=sys.stderr)
                return 2
        _summary('SUCCESS', count, receipt_sha256=receipt_sha)
        return 0
    except (Exception, KeyboardInterrupt) as failure:
        code = failure.code if isinstance(failure, _Failure) else 'OUTPUT_OR_ARGUMENTS_REJECTED'
        _summary('FAILED', count, failure_code=code)
        print(ERROR, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
