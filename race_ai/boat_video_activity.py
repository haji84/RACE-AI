"""Pinned primary-water screen content, separate from boat/event authentication.

ADE semantic water geometry is a content hypothesis. A same-media declared
exhibition topic can condition its display label; it does not authenticate the
current activity, a boat identity, a start/lap phase or a forecast feature.
"""
from copy import deepcopy
from hashlib import file_digest,sha256
import math
import os
from pathlib import Path
import re
import stat
import time

from .boat_video_identity import _pixels,_box,PinnedBoatDetector


SCHEMA='RACE_AI_PRIMARY_WATER_CONTENT_CANDIDATE_V1'
MODEL_REVISION='876ffc56b819a829448f7e81e9f8606deef6fb65'
MODEL_FILES={
    'model.safetensors':'cd55b1d36c6602d34f8cd300d7f788ea0fa5c3ed928e9ac98f353ecb31c7fa1d',
    'config.json':'c7f6a85a6b69d57f363505d5019e0e34f8d7e272f238d3fc88b2fde202b0d279',
    'preprocessor_config.json':'6073ac6a37530ed2a19443d6a748f5579887b3ae48f6730073954b0b38cf3fd6',
    'README.md':'fcd6b589ee354422b80f8036c985f6874d7888fdca51a30bd12396b0c418bc53'}
WATER_CLASSES=(21,26,60,128)
BOAT_CLASSES=(76,103)
SCREEN_CLASSES=(89,130,143)


def _need(condition):
    if not condition:raise ValueError('BOAT_VIDEO_PRIMARY_WATER_REJECTED')


def _finite(value):
    try:return type(value) in (float,int) and math.isfinite(value)
    except OverflowError:return False


def _sha(value):return type(value) is str and re.fullmatch(r'[a-f0-9]{64}',value) is not None


def _context(value,media_sha256):
    _need(_sha(media_sha256))
    if value is None:return None
    _need(type(value) is dict and set(value)=={'schema_version','media_sha256','topic','provenance_sha256'}
        and value['schema_version']=='RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1'
        and value['media_sha256']==media_sha256 and _sha(value['provenance_sha256'])
        and value['topic'] in ('EXHIBITION_TUTORIAL','EXHIBITION_BROADCAST','UNKNOWN'))
    return deepcopy(value)


def measure_primary_water(labels,boats,*,media_sha256,frame_sha256,source_context=None):
    """Separate primary-water and border-connected current-boat hypotheses."""
    import cv2
    import numpy as np
    context=_context(source_context,media_sha256)
    _need(_sha(frame_sha256) and type(labels) is np.ndarray and labels.dtype==np.uint8
          and labels.ndim==2 and min(labels.shape)>0 and max(labels.shape)<=1920
          and labels.size<=2073600
          and type(boats) is list and len(boats)<=64)
    caller_labels=labels;label_digest=sha256(labels.tobytes()).hexdigest();labels=labels.copy()
    _need(sha256(labels.tobytes()).hexdigest()==label_digest and (labels<150).all())
    h,w=labels.shape;area=h*w;checked=[]
    for row in boats:
        _need(type(row) is dict and set(row)=={'box','score'} and _finite(row['score']) and 0<=row['score']<=1)
        checked.append(dict(box=_box(row['box'],w,h),score=float(row['score'])))
    water=np.isin(labels,WATER_CLASSES).astype(np.uint8)
    number,components,stats,centers=cv2.connectedComponentsWithStats(water,connectivity=8)
    fraction=float(water.mean());largest=0.;box=None;bbox_fraction=0.;margins=None
    if number>1:
        index=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))
        x,y,bw,bh,count=map(int,stats[index]);box=[x,y,bw,bh]
        largest=count/area;bbox_fraction=bw*bh/area
        margins=[x/w,y/h,(w-x-bw)/w,(h-y-bh)/h]
    cy,cx=h//2,w//2;center_id=int(labels[cy,cx]);center_water=bool(water[cy,cx])
    center_semantic=center_id in WATER_CLASSES+BOAT_CLASSES
    center_coco=any(q['box'][0]<=cx<q['box'][0]+q['box'][2]
                    and q['box'][1]<=cy<q['box'][1]+q['box'][3] for q in checked)
    primary=fraction>=.45 and largest>=.40 and (center_semantic or center_coco)
    embedded=box is not None and .02<=fraction<=.40 and bbox_fraction<=.50 and min(margins)>=.02
    semantic_boats=float(np.isin(labels,BOAT_CLASSES).mean())
    union=np.isin(labels,WATER_CLASSES+BOAT_CLASSES).astype(np.uint8)
    count,component_map,component_stats,component_centers=cv2.connectedComponentsWithStats(union,connectivity=8)
    border_ids={name:set(map(int,values))-{0} for name,values in
                [('top',component_map[0,:]),('bottom',component_map[-1,:]),
                 ('left',component_map[:,0]),('right',component_map[:,-1])]}
    water_counts=np.bincount(component_map.ravel(),weights=water.ravel(),minlength=count)
    boat_evidence=[];ambiguities=set()
    for index,row in enumerate(checked):
        x,y,bw,bh=row['box'];boat_x,boat_y=int(x+bw/2),int(y+bh/2)
        center_class=int(labels[boat_y,boat_x]);component=int(component_map[boat_y,boat_x])
        sides=[name for name,values in border_ids.items() if component in values] if component else []
        native_water=int(water_counts[component]) if component else 0
        supported=center_class in BOAT_CLASSES and native_water>0 and len(sides)>=2
        boat_evidence.append(dict(proposal_index=index,center_pixel=[boat_x,boat_y],
            center_ADE_class_id=center_class,component_native_water_class_pixels=native_water,
            component_borders=sides,distinct_border_count=len(sides),supported=bool(supported),
            scope='CURRENT_COCO_AND_NATIVE_SEMANTIC_PIXELS_NOT_AUTHENTICATED_BOAT_OR_WATER'))
        if supported and not ({'left','right'}<=set(sides) or {'top','bottom'}<=set(sides)):
            ambiguities.add('ADJACENT_BORDERS_ONLY_CANNOT_EXCLUDE_CORNER_INSET')
    border_boat=any(row['supported'] for row in boat_evidence)
    aquatic=bool(primary or border_boat)
    if embedded:ambiguities.add('EMBEDDED_WATER_GEOMETRY_OBSERVED')
    depicted=bool(aquatic and context is not None and context['topic'] in ('EXHIBITION_TUTORIAL','EXHIBITION_BROADCAST'))
    result=dict(schema_version=SCHEMA,status='CONTENT_OBSERVATION',media_sha256=media_sha256,
        frame_sha256=frame_sha256,coordinate_space='IMAGE_PX',width=w,height=h,
        water_fraction=fraction,largest_water_component_fraction=largest,largest_water_bbox=box,
        largest_water_bbox_fraction=bbox_fraction,water_bbox_edge_margins=margins,
        center_is_water=center_water,center_native_ADE_class_id=center_id,
        center_supported_by_semantic_water_boat_or_ship=center_semantic,
        center_supported_by_current_COCO_boat_box=center_coco,
        semantic_boat_ship_fraction=semantic_boats,
        semantic_screen_fraction=float(np.isin(labels,SCREEN_CLASSES).mean()),
        full_native_class_histogram={str(int(k)):int(v) for k,v in zip(*np.unique(labels,return_counts=True))},
        native_class_map_sha256=sha256(labels.tobytes()).hexdigest(),
        primary_water_content_candidate=bool(primary),embedded_water_geometry_candidate=bool(embedded),
        border_connected_boat_content_candidate=border_boat,border_connected_boat_evidence=boat_evidence,
        primary_aquatic_content_candidate=aquatic,composition_ambiguity_flags=sorted(ambiguities),
        COCO_boat_detections=checked,primary_boat_water_content_candidate=bool(primary and checked),
        current_boat_visual_support=dict(status='UNVERIFIED_CURRENT_VISUAL_PROPOSALS' if checked or semantic_boats>0
            else 'NOT_DETECTED_UNKNOWN',COCO_proposal_count=len(checked),ADE_boat_ship_pixel_fraction=semantic_boats),
        source_context=context,topic_context_scope='DECLARED_LOCAL_HASH_NOT_AUTHENTICATED_PROVIDER_OR_EVENT',
        depicted_exhibition_content_candidate=depicted,
        display_status=('EXHIBITION_TOPIC_PRIMARY_WATER_CONTENT_CANDIDATE' if depicted and primary
                        else 'EXHIBITION_TOPIC_PRIMARY_AQUATIC_CONTENT_CANDIDATE' if depicted
                        else 'PRIMARY_WATER_CONTENT_CANDIDATE' if primary
                        else 'BORDER_CONNECTED_BOAT_CONTENT_CANDIDATE' if border_boat else 'NO_PRIMARY_WATER_SUPPORT'),
        specific_phase='UNKNOWN',authenticated_current_exhibition=False,
        verified_boat_movement=False,scores_are_calibrated_probabilities=False,
        usable_for_identity=False,identity_validated=False,model_eligible=False,production_eligible=False)
    _need(sha256(caller_labels.tobytes()).hexdigest()==label_digest
          and sha256(labels.tobytes()).hexdigest()==label_digest)
    return result


def _model_directory(value):
    raw=os.fspath(value)
    _need(type(raw) is str and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',raw)
          and not raw.startswith('//') and '..' not in Path(raw).parts)
    path=Path(raw).absolute()
    _need(path.is_dir() and not any(p.is_symlink() for p in (path,*path.parents)))
    _need({p.name for p in path.iterdir()}==set(MODEL_FILES))
    return path


def _identity(path):
    info=path.lstat();_need(stat.S_ISREG(info.st_mode) and not path.is_symlink())
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _asset_pins(directory):
    paths={name:directory/name for name in MODEL_FILES};pins={}
    for name,path in paths.items():
        before=_identity(path)
        with path.open('rb') as source:actual=file_digest(source,'sha256').hexdigest()
        _need(actual==MODEL_FILES[name] and _identity(path)==before)
        pins[name]=before
    return paths,pins


def _held_model_directory(directory):
    """Resolve every directory component relative to an already held parent."""
    descriptor=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in directory.parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _directory_identity(descriptor):
    info=os.fstat(descriptor);_need(stat.S_ISDIR(info.st_mode))
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


class LocalPrimaryWaterReader:
    """Explicit offline pinned assets; generic content candidate only.

    Memory is bounded by the fixed 512x512 model input and <=2,073,600 native
    pixels/150 classes. The wall budget rejects late outputs after computation;
    it is not a preemptive process watchdog or an acquisition/runtime cap.
    """
    def __init__(self,model_path,boat_model_path,*,torch_threads=4,processing_timeout_seconds=60.):
        descriptor=None
        try:
            _need(type(torch_threads) is int and 1<=torch_threads<=64
                  and _finite(processing_timeout_seconds) and processing_timeout_seconds>0)
            directory=_model_directory(model_path);descriptor=_held_model_directory(directory)
            directory_pin=_directory_identity(descriptor)
            directory=Path(f'/proc/self/fd/{descriptor}')
            _need({p.name for p in directory.iterdir()}==set(MODEL_FILES))
            paths,pins=_asset_pins(directory)
            _need(_directory_identity(descriptor)==directory_pin)
            import torch
            from transformers import UperNetForSemanticSegmentation,SegformerImageProcessor
            torch.set_num_threads(torch_threads)
            processor=SegformerImageProcessor.from_pretrained(directory,local_files_only=True)
            model=UperNetForSemanticSegmentation.from_pretrained(directory,local_files_only=True,
                use_safetensors=True).to('cpu').eval()
            paths_after,pins_after=_asset_pins(directory)
            _need(paths_after==paths and pins_after==pins
                  and _directory_identity(descriptor)==directory_pin)
            boat=PinnedBoatDetector(model_path=boat_model_path,detector_kind='yolox')
            self._processor,self._model,self._torch,self._boat=processor,model,torch,boat
            self._asset_paths,self._asset_pins=paths,pins
            self._processing_timeout_seconds=float(processing_timeout_seconds)
            self._metadata=dict(engine='LOCAL_UPERNET_CONVNEXT_TINY_PRIMARY_WATER',
                model_id='openmmlab/upernet-convnext-tiny',model_revision=MODEL_REVISION,
                model_file_sha256=deepcopy(MODEL_FILES),license='MIT_OFFICIAL_HF_CARD',
                local_files_only=True,network_requests=0,torch_threads=torch_threads,
                model_loader_path_binding='HELD_NOFOLLOW_DIRECTORY_FD_WITH_PRE_POST_FILE_SHA_AND_DIRECTORY_IDENTITY',
                preprocessing='PINNED_RGB512x512_IMAGEPROCESSOR_NO_ROI_OR_MULTISCALE',
                native_postprocess='BILINEAR_LOGITS_ALIGN_CORNERS_FALSE_THEN_ARGMAX150',
                profile='V4_BORDER_CONNECTED_CURRENT_BOAT_NATURAL_WATER_CONTENT',water_classes=list(WATER_CLASSES),
                taxonomy_profile='V3_NATURAL_WATER_INCLUDING_LAKE',
                natural_water_class_labels={'21':'water','26':'sea','60':'river','128':'lake'},
                border_connected_boat_rule=dict(center_classes=list(BOAT_CLASSES),connectivity=8,
                    union_classes=list(WATER_CLASSES+BOAT_CLASSES),requires_native_water_pixels=True,
                    minimum_distinct_image_borders=2,adjacent_borders_allowed=True),
                border_contact_alone_does_not_certify_primary_camera=True,
                boat_ship_classes=list(BOAT_CLASSES),fullframe_water_threshold=.45,
                largest_component_threshold=.40,center_support='WATER_OR_SEMANTIC_BOAT_SHIP_OR_CURRENT_COCO_BOAT_BOX',
                boat_detector=boat.metadata(),resource_guards=dict(max_native_dimension=1920,
                    max_native_pixels=2073600,semantic_classes=150,fixed_model_input=[512,512],
                    maximum_native_float_logits_bytes=2073600*150*4,
                    processing_timeout_seconds=self._processing_timeout_seconds,
                    deadline_enforcement='POST_COMPUTATION_REJECTION_NOT_PREEMPTIVE'),
                scores_are_calibrated_probabilities=False,production_eligible=False)
            self._directory_pin=directory_pin
            self._directory_fd=descriptor
            descriptor=None
        except (OSError,ImportError,TypeError,ValueError):
            raise ValueError('BOAT_VIDEO_PRIMARY_WATER_MODEL_REJECTED') from None
        finally:
            if descriptor is not None:os.close(descriptor)

    def __del__(self):
        descriptor=getattr(self,'_directory_fd',None)
        if descriptor is not None:
            self._directory_fd=None
            try:os.close(descriptor)
            except OSError:pass

    def __reduce_ex__(self,protocol):
        raise TypeError('BOAT_VIDEO_PRIMARY_WATER_READER_OWNS_NONCOPYABLE_DESCRIPTOR')

    def metadata(self):return deepcopy(self._metadata)

    def _check_assets(self):
        _need(_directory_identity(self._directory_fd)==self._directory_pin
              and all(_identity(path)==self._asset_pins[name] for name,path in self._asset_paths.items()))

    def _infer(self,frame):
        import cv2
        import numpy as np
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        inputs=self._processor(images=rgb,return_tensors='pt',input_data_format='channels_last')
        with self._torch.inference_mode():
            logits=self._model(**inputs).logits
            _need(logits.ndim==4 and logits.shape[0]==1 and logits.shape[1]==150
                  and 0<logits.shape[2]<=512 and 0<logits.shape[3]<=512
                  and logits.is_floating_point() and bool(self._torch.isfinite(logits).all()))
            scores=self._torch.nn.functional.interpolate(logits,size=frame.shape[:2],
                mode='bilinear',align_corners=False)
            _need(scores.shape==(1,150,*frame.shape[:2]) and bool(self._torch.isfinite(scores).all()))
            return scores.argmax(1)[0].cpu().numpy().astype(np.uint8)

    def __call__(self,frame,*,media_sha256,source_context=None):
        import numpy as np
        _pixels(frame);context=_context(source_context,media_sha256)
        digest=sha256(frame.tobytes()).hexdigest();image=frame.copy()
        _need(sha256(image.tobytes()).hexdigest()==digest)
        started=time.monotonic()
        try:
            self._check_assets()
            callback=image.copy();labels=self._infer(callback)
            _need(sha256(callback.tobytes()).hexdigest()==digest and type(labels) is np.ndarray
                  and labels.dtype==np.uint8 and labels.shape==image.shape[:2])
            label_digest=sha256(labels.tobytes()).hexdigest();labels=labels.copy()
            _need(sha256(labels.tobytes()).hexdigest()==label_digest)
            callback=image.copy();boats=self._boat(callback)
            _need(sha256(callback.tobytes()).hexdigest()==digest)
            result=measure_primary_water(labels,boats,media_sha256=media_sha256,frame_sha256=digest,source_context=context)
            elapsed=time.monotonic()-started
            self._check_assets()
            _need(elapsed<=self._processing_timeout_seconds
                  and sha256(frame.tobytes()).hexdigest()==digest and sha256(image.tobytes()).hexdigest()==digest)
            result.update(engine=self.metadata(),elapsed_analysis_seconds=elapsed)
            return result
        except Exception:
            return dict(schema_version=SCHEMA,status='ANALYSIS_FAILED_UNKNOWN',media_sha256=media_sha256,
                frame_sha256=digest,source_context=context,primary_water_content_candidate=False,
                border_connected_boat_content_candidate=False,primary_aquatic_content_candidate=False,
                depicted_exhibition_content_candidate=False,display_status='ANALYSIS_FAILED_UNKNOWN',
                specific_phase='UNKNOWN',authenticated_current_exhibition=False,
                failure_reason='LOCAL_MODEL_SOURCE_INTEGRITY_OR_RESOURCE_BUDGET_FAILURE',
                engine=self.metadata(),scores_are_calibrated_probabilities=False,verified_boat_movement=False,
                usable_for_identity=False,identity_validated=False,model_eligible=False,production_eligible=False)
