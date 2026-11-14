"""Opt-in anonymous visible rider parts and separate declared print evidence.

PERSON proposals are never hulls. Actual pixel continuity is an image-space
hypothesis, not authenticated physical identity or field accuracy. Optional
number producers must explicitly declare a physical rider/print pairing;
containment, nearest marks, color and appearance predictions cannot label a
track. All defaults and existing boat/marker providers remain unchanged.
"""
from collections import Counter, defaultdict
from copy import copy, deepcopy
from fractions import Fraction
from hashlib import sha256
import json

from .boat_video_identity import _box, _finite, _intersects, _iou, _pixels
from .boat_video_marker_flow import MarkerPixelFollower, PARAMETERS


SCHEMA = 'RACE_AI_RIDER_PART_TRACKS_V1'
_DETECTIONS = 'RACE_AI_RIDER_PART_DETECTIONS_V1'
_PAIRS = 'RACE_AI_RIDER_NUMBER_PAIRS_V1'
_PHYSICAL = 'DECLARED_PHYSICAL_RIDER_PRINT_PAIR'
_BINDINGS = {_PHYSICAL, 'BBOX_CONTAINMENT', 'NEAREST_MARKER', 'UNBOUND'}


def _need(condition):
    if not condition:
        raise ValueError('BOAT_RIDER_TRACKING_REJECTED')


def _digest(frame):
    return sha256(frame.tobytes()).hexdigest()


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _age(now, then):
    return Fraction(str(now))-Fraction(str(then))


def _detections(packet, width, height, digest):
    _need(type(packet) is dict and set(packet) == {'schema_version','frame_sha256',
        'coordinate_space','semantic_type','detections','engine','identity_validated','model_eligible'})
    _need(packet['schema_version'] == _DETECTIONS and packet['frame_sha256'] == digest
        and packet['coordinate_space'] == 'IMAGE_PX' and packet['semantic_type'] == 'RIDER_PART_TYPED'
        and packet['model_eligible'] is False and packet['identity_validated'] is False
        and type(packet['engine']) is dict
        and type(packet['detections']) is list and len(packet['detections']) <= PARAMETERS['maximum_live_markers'])
    # Freeze JSON-safe provenance; a declared engine does not authenticate semantics.
    try:
        engine = json.loads(json.dumps(packet['engine'], allow_nan=False))
    except (TypeError,ValueError,OverflowError) as error:
        raise ValueError('BOAT_RIDER_TRACKING_REJECTED') from error
    checked, seen, unknown, raw = [], set(), [], []
    for raw_index,row in enumerate(packet['detections']):
        _need(type(row) is dict and set(row) == {'box','score','semantic_type','coco_class_id'}
            and row['semantic_type'] == 'RIDER_PART_TYPED' and type(row['coco_class_id']) is int
            and row['coco_class_id'] == 0 and _finite(row['score']) and 0 <= row['score'] <= 1)
        box = _box(row['box'], width, height)
        original = dict(box=box,score=float(row['score']),semantic_type='RIDER_PART_TYPED',
                        coco_class_id=0,source_detection_index=raw_index)
        raw.append(deepcopy(original))
        if row['score'] < .5:
            unknown.append(dict(original,reason='LOW_PERSON_DETECTOR_SCORE'))
        elif tuple(box) not in seen:
            seen.add(tuple(box)); checked.append(dict(box=box,score=float(row['score']),raw_index=raw_index))
        else:
            unknown.append(dict(original,reason='UNBOUND_DUPLICATE_CURRENT_BOX'))
    return checked, engine, unknown, raw


def _point_correspondences(pixels, point_states, detections):
    """Current measured image-point ownership, never a person/number proof.

    Existing IoU geometry stays at .5. A separate exclusive measured support
    uses the follower's unchanged minimum4/.75 constants. Ambiguous owners and
    unassigned partial views remain explicit unbound proposals, not births.
    """
    import numpy as np
    edges = {key:[i for i,row in enumerate(detections) if _iou(pixel['box'],row['box']) >= .5]
             for key,pixel in pixels.items()}
    columns = Counter(index for choices in edges.values() for index in choices)
    matches = {choices[0]:key for key,choices in edges.items()
               if len(choices)==1 and columns[choices[0]]==1}
    ambiguous = {key for key,choices in edges.items()
                 if choices and (len(choices)!=1 or columns[choices[0]]!=1)}
    cloud,counts = {},{}
    for key,pixel in pixels.items():
        points = point_states[key]['points']
        _need(type(points) is np.ndarray and points.ndim==2 and points.shape[1]==2
              and len(points)==pixel['point_count'] and PARAMETERS['minimum_points'] <= len(points)
              <= PARAMETERS['maximum_points'] and np.isfinite(points).all())
        cloud[key] = points
        counts[key] = []
        for row in detections:
            x,y,w,h = row['box']
            counts[key].append(int(((points[:,0]>=x)&(points[:,0]<x+w)&
                                    (points[:,1]>=y)&(points[:,1]<y+h)).sum()))
    strong,point_edges = defaultdict(set),{}
    for key,values in counts.items():
        for index,count in enumerate(values):
            if count >= PARAMETERS['minimum_points'] and count/len(cloud[key]) >= PARAMETERS['minimum_affine_inlier_ratio']:
                strong[index].add(key)
        point_edges[key] = [index for index,count in enumerate(values)
            if key in strong[index] and all(counts[other][index]==0 for other in counts if other!=key)]
    unbound,hard_ambiguous = {},set()
    for index,owners in strong.items():
        if len(owners)>1:
            hard_ambiguous.update(owners)
            unbound[index] = dict(reason='UNBOUND_AMBIGUOUS_CURRENT_POINT_OWNERS',
                                 point_owner_track_ids=sorted(owners))
    matches = {index:key for index,key in matches.items() if key not in hard_ambiguous and index not in unbound}
    ambiguous.update(hard_ambiguous)
    methods = {index:'IOU_GEOMETRY' for index in matches}
    for key in sorted(pixels):
        if key in matches.values() or key in hard_ambiguous:
            continue
        options = [index for index in point_edges[key] if index not in unbound]
        if not options:
            continue
        index = min(options,key=lambda i:(-counts[key][i],-_iou(pixels[key]['box'],detections[i]['box']),
                                         tuple(detections[i]['box']),i))
        other = matches.get(index)
        if other is not None and other!=key:
            ambiguous.update((key,other)); hard_ambiguous.update((key,other))
            matches = {i:k for i,k in matches.items() if k not in (key,other)}
            unbound[index] = dict(reason='UNBOUND_CONFLICTING_POINT_AND_GEOMETRY_OWNERS',
                                 point_owner_track_ids=sorted((key,other)))
            continue
        matches[index]=key; methods[index]='CURRENT_LK_POINT_SUPPORT'; ambiguous.discard(key)
    # No detection that shares an existing current owner can silently become a
    # new person. Keep the entire typed raw proposal and its unresolved reason.
    # An unmatched old owner still has measured current pixels. A partial or
    # contested detection touching those pixels is unresolved, not a new person.
    owner_keys = set(pixels)
    for index,row in enumerate(detections):
        if index in matches or index in unbound:
            continue
        x,y,w,h = row['box']; center=(x+w/2,y+h/2)
        owners=[]
        for key in sorted(owner_keys):
            a,b,c,d=pixels[key]['box']
            if counts[key][index] > 0 or a<=center[0]<a+c and b<=center[1]<b+d:
                owners.append(key)
        if owners:
            unbound[index] = dict(reason='UNBOUND_EXISTING_CURRENT_POINT_OWNER',point_owner_track_ids=owners)
    evidence={}
    for index,key in matches.items():
        evidence[index] = dict(scope='CURRENT_LK_IMAGE_POINT_OWNER_HYPOTHESIS',method=methods[index],
            point_count=len(cloud[key]),points_in_detection=counts[key][index],
            support_fraction=counts[key][index]/len(cloud[key]),
            foreign_track_points_in_detection=sum(counts[other][index] for other in counts if other!=key),
            measured_box=list(pixels[key]['box']),detection_box=list(detections[index]['box']))
    return matches,ambiguous,unbound,evidence,edges


def _pairs(packet, riders, width, height, *, digest, t, frame_index, scene):
    _need(type(packet) is dict and set(packet) == {'schema_version','frame_sha256',
        'frame_index','t','scene','observations'})
    _need(packet['schema_version'] == _PAIRS and packet['frame_sha256'] == digest
        and type(packet['frame_index']) is int and packet['frame_index'] == frame_index
        and _finite(packet['t']) and packet['t'] == t and type(packet['scene']) is int
        and packet['scene'] == scene and type(packet['observations']) is list
        and len(packet['observations']) <= 20000)
    current = {row['track_id']: row for row in riders}
    result = defaultdict(list)
    for row in packet['observations']:
        _need(type(row) is dict and set(row) == {'rider_track_id','rider_box','marker_box',
            'number','binding_kind','evidence_sha256','producer_sha256','label_source'})
        key = row['rider_track_id']
        _need(type(key) is str and key in current and type(row['number']) is int
            and 1 <= row['number'] <= 6 and type(row['binding_kind']) is str
            and row['binding_kind'] in _BINDINGS
            and row['label_source'] == 'DIRECT_PRINTED_MARK'
            and _hex(row['evidence_sha256']) and _hex(row['producer_sha256']))
        box = _box(row['rider_box'],width,height)
        _need(box == current[key]['rider_box'])
        item = deepcopy(row); item['rider_box'] = box
        item['marker_box'] = _box(row['marker_box'],width,height)
        if item not in result[key]:
            result[key].append(item)
    return result


class RiderPartTracker:
    """Track current image evidence independently of optional numeric labels."""
    def __init__(self, detector, *, number_provider=None, max_gap_seconds=.5):
        _need(callable(detector) and (number_provider is None or callable(number_provider))
            and _finite(max_gap_seconds) and 0 < max_gap_seconds <= .5)
        self.detector, self.number_provider = detector, number_provider
        self.max_gap = float(max_gap_seconds)
        self._flow = MarkerPixelFollower(max_gap_seconds=max_gap_seconds)
        self._objects = {}
        self._time = self._index = self._scene = self._shape = None
        self._next_id = 1
        self._number_seen_pixels = set()

    def update(self, frame, *, t, frame_index, scene):
        width,height = _pixels(frame)
        _need(_finite(t) and t >= 0 and type(frame_index) is int and 0 <= frame_index < 2**63
            and type(scene) is int and 0 <= scene < 2**63)
        _need(self._time is None or t > self._time and frame_index > self._index)
        _need(self._scene is None or scene >= self._scene)
        image = frame.copy(); digest = _digest(image)
        callback_image = image.copy()
        packet = self.detector(callback_image)
        _need(_digest(callback_image) == digest and _digest(frame) == digest)
        detections,engine,unknown,raw_detections = _detections(packet,width,height,digest)
        reset = (self._time is None or self._scene != scene or self._shape != (width,height)
            or _age(t,self._time) >= Fraction(str(self.max_gap)))
        old = {} if reset else deepcopy(self._objects)
        probe = copy(self._flow)
        measured = probe.update(image,[],t=t,frame_index=frame_index,scene=scene)
        _need(probe._sha==digest and probe._index==frame_index and probe._time==t
              and probe._scene==scene and probe._shape==(width,height)
              and measured['frame_sha256']==digest)
        pixels = {row['key']:row for row in measured['tracked'] if row['status']=='TRACKED' and row['key'] in old}
        matches,ambiguous,unbound,association,edges = _point_correspondences(pixels,probe._tracks,detections)
        flags = set()
        if reset:
            flags.add('SCENE_SHAPE_OR_TIME_RESET')
        if ambiguous:
            flags.add('AMBIGUOUS_RIDER_ASSOCIATION')
        candidates, seeds, allowed, next_id = {}, [], set(), self._next_id
        for index,row in enumerate(detections):
            if index in unbound:
                original = raw_detections[row['raw_index']]
                unknown.append(dict(deepcopy(original),**unbound[index]))
                continue
            key = matches.get(index)
            if key is None:
                _need(next_id < 2**63)
                key = f'R{next_id:06d}'; next_id += 1
                state = {'number':None,'evidence':[]}
                seeds.append(dict(key=key,box=list(row['box'])))
            else:
                allowed.add(key); state = deepcopy(old[key]['number_state'])
            candidates[key] = dict(box=list(row['box']),score=row['score'],detector_fresh=True,
                last_detection_t=float(t),last_detection_frame_index=frame_index,last_detection_sha256=digest,
                number_state=state,association_evidence=deepcopy(association.get(index)))
        for key,pixel in pixels.items():
            if key in candidates or key in ambiguous:
                continue
            # Without a fresh detector there is no semantic observation to
            # distinguish overlapping old image supports from one aliased part.
            if any(_intersects(pixel['box'],other['box']) for other_key,other in pixels.items()
                   if other_key != key):
                flags.add('AMBIGUOUS_PIXEL_ONLY_RIDER_OVERLAP')
                unknown.append(dict(box=list(pixel['box']),reason='AMBIGUOUS_PIXEL_ONLY_RIDER_OVERLAP'))
                continue
            if (_age(t,old[key]['last_detection_t']) >= Fraction(str(self.max_gap))
                or any(_intersects(pixel['box'],row['box']) for row in detections)):
                continue
            allowed.add(key)
            candidates[key] = dict(old[key],box=list(pixel['box']),detector_fresh=False,association_evidence=None)
        flow = copy(self._flow)
        flow._tracks = {key:value for key,value in self._flow._tracks.items() if key in allowed}
        flowed = flow.update(image,seeds,t=t,frame_index=frame_index,scene=scene)
        final_pixels = {row['key']:row for row in flowed['tracked']}
        rows, current = [], {}
        for key,item in sorted(candidates.items()):
            pixel = final_pixels.get(key)
            if not item['detector_fresh'] and (pixel is None or pixel['status'] != 'TRACKED'):
                continue
            if item['detector_fresh']:
                visibility = ('DETECTION_AND_PIXEL_TRACK' if key in old and pixel is not None
                              and pixel['status']=='TRACKED' else 'CURRENT_DETECTION_UNTRACKED')
            else:
                visibility = 'PIXEL_TRACKED_RIDER_HYPOTHESIS'
            current[key] = deepcopy(item)
            relationship = deepcopy(item['association_evidence'])
            if relationship is not None:
                relationship.update(frame_sha256=digest,frame_index=frame_index,t=float(t),scene=scene,
                                    previous_frame_sha256=pixel['previous_frame_sha256'] if pixel else None)
            rows.append(dict(track_id=key,semantic_type='RIDER_PART_TYPED',rider_box=list(item['box']),
                hull_box=None,visibility_status=visibility,detector_fresh=item['detector_fresh'],
                detector_score=item['score'],last_detection_t=item['last_detection_t'],
                last_detection_frame_index=item['last_detection_frame_index'],
                last_detection_frame_sha256=item['last_detection_sha256'],pixel_support=deepcopy(pixel),
                association_evidence=relationship,
                number=None,number_status='UNREAD_NUMBER',number_evidence_status=None,
                printed_number_observed=False,fresh_label_observations_added=0,number_evidence=None))
        by_key = {row['track_id']:row for row in rows}
        observations = {}
        if self.number_provider is not None:
            callback_image = image.copy()
            packet = self.number_provider(callback_image,deepcopy(rows),t=float(t),frame_index=frame_index,scene=scene)
            _need(_digest(callback_image) == digest and _digest(frame) == digest)
            observations = _pairs(packet,rows,width,height,digest=digest,t=float(t),frame_index=frame_index,scene=scene)
        choices, blocked = {}, {}
        for key,items in observations.items():
            if len(items) != 1:
                blocked[key] = 'CONFLICTING_NUMBER_PAIRS'
            elif items[0]['binding_kind'] != _PHYSICAL:
                blocked[key] = 'UNSUPPORTED_BINDING'
            else:
                choices[key] = items[0]
        owners = defaultdict(list)
        for key,item in choices.items():
            owners[tuple(item['marker_box'])].append(key)
        for keys in owners.values():
            if len(keys)>1:
                # One current printed region cannot simultaneously belong to
                # separate rider labels. A common document SHA alone is fine.
                flags.add('CONFLICTING_SHARED_PRINT_MARKER')
                for key in keys:
                    blocked[key] = 'CONFLICTING_SHARED_PRINT_MARKER'
        physical = list(choices.items())
        for index,(key,item) in enumerate(physical):
            for other_key,other in physical[:index]:
                # Same conservative conflicting-print geometry as the marker
                # tracker: a one-pixel alternate crop is not independent print.
                if item['number'] != other['number'] and _iou(item['marker_box'],other['marker_box']) >= .2:
                    flags.add('CONFLICTING_SHARED_PRINT_MARKER')
                    blocked[key] = blocked[other_key] = 'CONFLICTING_SHARED_PRINT_MARKER'
        repeated = {number for number,count in Counter(item['number'] for item in choices.values()).items() if count>1}
        # A current new print must not coexist with another rider's prior label,
        # even while the newcomer is still warming up its three observations.
        claims = defaultdict(set)
        for key,row in by_key.items():
            if key in blocked:
                continue
            if key in choices:
                claims[choices[key]['number']].add(key)
            else:
                state = current[key]['number_state']
                if len(state['evidence']) >= 3 and row['visibility_status']=='DETECTION_AND_PIXEL_TRACK':
                    claims[state['number']].add(key)
        repeated.update(number for number,keys in claims.items() if len(keys)>1)
        for key,item in choices.items():
            if item['number'] in repeated:
                blocked[key] = 'DUPLICATE_NUMBER'
        for number in repeated:
            for key in claims[number]:
                blocked[key] = 'DUPLICATE_NUMBER'
        if repeated:
            flags.add('DUPLICATE_NUMBER')
        new_pixels = (width,height,digest) not in self._number_seen_pixels
        seen = set(self._number_seen_pixels)
        any_fresh = False
        for key,row in by_key.items():
            state = current[key]['number_state']
            item = choices.get(key)
            if key in blocked:
                state = {'number':None,'evidence':[]}
                row['number_status'] = blocked[key]
            elif item is not None:
                # Replayed pixels cannot add a vote, but a declared current
                # contradiction still invalidates any old label immediately.
                if state['number'] is not None and state['number'] != item['number']:
                    flags.add('CONFLICTING_NUMBER_EVIDENCE')
                    state = {'number':None,'evidence':[]}
                if not new_pixels:
                    flags.add('REPEATED_NUMBER_FRAME_PIXELS')
                    row['number_status'] = 'REPEATED_NUMBER_FRAME_PIXELS'
                else:
                    if state['number'] != item['number']:
                        state = {'number':item['number'],'evidence':[]}
                    reading = dict(frame_index=frame_index,t=float(t),scene=scene,frame_sha256=digest,
                        marker_box=list(item['marker_box']),binding_kind=item['binding_kind'],
                        evidence_sha256=item['evidence_sha256'],producer_sha256=item['producer_sha256'],
                        label_source='DIRECT_PRINTED_MARK')
                    state['evidence'] = (state['evidence']+[reading])[-20:]
                    row['fresh_label_observations_added'] = 1; any_fresh = True
                    row['number_status'] = 'INSUFFICIENT_DISTINCT_PRINT_OBSERVATIONS'
                    if len(state['evidence']) >= 3:
                        row.update(number=state['number'],number_status='NUMBER_CANDIDATE',
                            number_evidence_status='DIRECT_PRINTED_MARK_CURRENT',printed_number_observed=True)
            elif len(state['evidence']) >= 3 and row['visibility_status']=='DETECTION_AND_PIXEL_TRACK':
                row.update(number=state['number'],number_status='PRIOR_PRINT_TRACK_CANDIDATE',
                    number_evidence_status='CURRENT_VISIBLE_TRACK_PRIOR_PRINT')
            if state['evidence']:
                last = state['evidence'][-1]
                row['number_evidence'] = dict(observations=len(state['evidence']),
                    fresh_frames=deepcopy(state['evidence']),last_print_frame_index=last['frame_index'],
                    last_print_frame_sha256=last['frame_sha256'],last_print_t=last['t'],
                    scope='DECLARED_PHYSICAL_PRINT_PAIR_NOT_AUTHENTICATED',field_validated=False)
            current[key]['number_state'] = state
        if any_fresh:
            seen.add((width,height,digest))
        # All fallible validation/allocation must finish before publishing state.
        _need(_digest(frame) == digest and _digest(image) == digest)
        result = dict(schema_version=SCHEMA,coordinate_space='IMAGE_PX',semantic_type='RIDER_PART_TYPED',
            t=float(t),frame_index=frame_index,scene=scene,frame_sha256=digest,tracks=deepcopy(rows),
            lost_track_ids=sorted(set(self._objects)-set(current)),unknown_detections=unknown,
            detector_engine=engine,raw_detections=raw_detections,flow=flowed,quality_flags=sorted(flags),
            model_eligible=False,field_validation='NOT_ESTABLISHED',identity_validated=False,
            metric_positions_inferred=False,hull_positions_inferred=False,forced_six=False)
        self._flow,self._objects,self._next_id = flow,current,next_id
        self._time,self._index,self._scene,self._shape = float(t),frame_index,scene,(width,height)
        self._number_seen_pixels = seen
        return result
