"""Primary clothing-colour candidates on independently tracked rider pixels.

No OCR, printed-number pairing, remaining-number assignment, or learned model.
The positional torso prior is explicitly NOT semantic garment segmentation.
Colour fractions and detector scores are raw evidence, never probabilities.
Image identities remain development hypotheses, not validated hull positions.
"""
from collections import Counter, defaultdict
from copy import copy, deepcopy
from hashlib import sha256

from .boat_video_identity import _box, _pixels


COLORS = {1:'WHITE',2:'BLACK',3:'RED',4:'BLUE',5:'YELLOW',6:'GREEN'}
PARAMETERS = dict(torso_x=(.2,.8),torso_y=(.35,.75),minimum_person_score=.6,
    minimum_color_fraction=.4,minimum_half_fraction=.2,competing_color_fraction=.15,
    neutral_saturation=55,minimum_neutral_fraction=.65,
    neutral_contrast=51.,neutral_extreme_tolerance=12.75,
    minimum_distinct_frames=3)


def _need(condition):
    if not condition:
        raise ValueError('BOAT_CLOTHING_IDENTITY_REJECTED')


def measure_clothing_colors(frame, riders):
    """Measure all current torso priors before contemporaneous neutral contrast.

    Neutral middle greys alone cannot distinguish shadowed white from black.
    Relative bright/dark candidates require actual neutral clothing priors in
    the same frame separated by >=20% luminance. This is an explicit shared
    illumination hypothesis, NOT a requirement to fill missing white/black IDs.
    """
    import cv2
    import numpy as np
    width,height=_pixels(frame)
    digest=sha256(frame.tobytes()).hexdigest()
    image=frame.copy()
    _need(sha256(image.tobytes()).hexdigest()==digest)
    _need(type(riders) is dict and riders.get('schema_version')=='RACE_AI_RIDER_PART_TRACKS_V1'
        and riders.get('frame_sha256')==digest and type(riders.get('tracks')) is list)
    result={};neutral=[]
    for row in riders['tracks']:
        key=row['track_id'];_need(type(key) is str and key not in result)
        x,y,w,h=_box(row['rider_box'],width,height)
        x0,x1=int(x+.2*w),int(x+.8*w)
        y0,y1=int(y+.35*h),int(y+.75*h)
        patch=image[y0:y1,x0:x1]
        item=dict(color=None,number=None,reason='INSUFFICIENT_VISIBLE_CLOTHING',
            region_kind='TORSO_POSITIONAL_PRIOR_NOT_SEGMENTATION',
            garment_semantics_validated=False,region_box=[x0,y0,x1-x0,y1-y0],
            frame_sha256=digest,patch_sha256=sha256(patch.tobytes()).hexdigest(),
            calibrated_probability=False,pixel_fractions={},neutral_reference_track_ids=[],
            limitations=['PERSON_PROPOSAL_CAN_BE_EQUIPMENT','HELMET_OR_BACKGROUND_MAY_ENTER_PRIOR',
                         'MIXED_GARMENTS_AND_UNEVEN_LIGHTING_CAN_BE_AMBIGUOUS'])
        result[key]=item
        if not row['detector_fresh']:
            item['reason']='NO_CURRENT_PERSON_OBSERVATION';continue
        if row['detector_score'] < PARAMETERS['minimum_person_score']:
            item['reason']='WEAK_PERSON_PROPOSAL';continue
        if min(patch.shape[:2],default=0)<4:
            continue
        H,S,V=np.moveaxis(cv2.cvtColor(patch,cv2.COLOR_BGR2HSV),-1,0)
        R,G,B=np.moveaxis(patch[:,:,::-1].astype(np.int16),-1,0)
        masks={
            3:((H<=12)|(H>=170))&(S>=60)&(V>=60),
            4:(H>=90)&(H<=135)&(S>=40)&(V>=60),
            5:(H>=18)&(H<38)&(S>=60)&(V>=60),
            # Signed channel evidence retains pale green, unlike S>=130.
            6:(H>=38)&(H<90)&(S>=20)&(G-np.maximum(R,B)>=5)&(V>=60)}
        fractions={n:float(mask.mean()) for n,mask in masks.items()}
        item['pixel_fractions']={COLORS[n]:v for n,v in fractions.items()}
        item['median_value']=float(np.median(V))
        item['median_green_advantage']=float(np.median(G-np.maximum(R,B)))
        item['neutral_fraction']=float((S<=PARAMETERS['neutral_saturation']).mean())
        order=sorted(fractions,key=lambda n:(-fractions[n],n));best,second=order[:2]
        if fractions[second]>=PARAMETERS['competing_color_fraction']:
            item['reason']='MIXED_CLOTHING_COLORS';continue
        if fractions[best]>=PARAMETERS['minimum_color_fraction']:
            mask=masks[best];middle=mask.shape[1]//2
            halves=[float(mask[:,:middle].mean()),float(mask[:,middle:].mean())]
            item['color_half_fractions']=halves
            if min(halves)>=PARAMETERS['minimum_half_fraction']:
                item.update(color=COLORS[best],number=best,reason='CURRENT_CHROMATIC_CLOTHING_PRIOR')
            continue
        if item['median_green_advantage']>0:
            item['reason']='PALE_CHROMA_UNRESOLVED'
        elif item['neutral_fraction']>=PARAMETERS['minimum_neutral_fraction']:
            neutral.append(key);item['reason']='ACHROMATIC_LIGHTING_AMBIGUOUS'
    if len(neutral)>=2:
        lo=min(result[key]['median_value'] for key in neutral)
        hi=max(result[key]['median_value'] for key in neutral)
        if hi-lo>=PARAMETERS['neutral_contrast']:
            for key in neutral:
                item=result[key];value=item['median_value']
                if value<=lo+PARAMETERS['neutral_extreme_tolerance']:
                    number=2
                elif value>=hi-PARAMETERS['neutral_extreme_tolerance']:
                    number=1
                else:
                    continue
                item.update(number=number,color=COLORS[number],
                    reason='RELATIVE_NEUTRAL_CLOTHING_PRIOR',
                    neutral_reference_track_ids=list(neutral),
                    neutral_reference_value_range=[lo,hi],
                    illumination_assumption='CONTEMPORANEOUS_SHARED_ILLUMINATION_UNVALIDATED')
    _need(sha256(frame.tobytes()).hexdigest()==digest
          and sha256(image.tobytes()).hexdigest()==digest)
    return result


class ClothingColorIdentityTracker:
    """Compose colour identity with actual rider LK; keep print evidence separate."""
    def __init__(self,rider_tracker):
        _need(callable(getattr(rider_tracker,'update',None))
              and getattr(rider_tracker,'number_provider',None) is None)
        self.riders=rider_tracker
        self._identities={};self._seen=set();self._last_result=None

    def update(self,frame,*,t,frame_index,scene):
        _pixels(frame)
        source_digest=sha256(frame.tobytes()).hexdigest()
        image=frame.copy()
        _need(sha256(image.tobytes()).hexdigest()==source_digest)
        probe=copy(self.riders)
        result=probe.update(image,t=t,frame_index=frame_index,scene=scene)
        observations=measure_clothing_colors(image,result)
        states={};flags=set(result['quality_flags']);claims=defaultdict(set)
        digest=result['frame_sha256'];fresh=digest not in self._seen
        for row in result['tracks']:
            key=row['track_id'];pixel=row['pixel_support']
            continuous=(pixel is not None and pixel['status']=='TRACKED')
            state=deepcopy(self._identities.get(key,{'number':None,'evidence':[]})) if continuous else {'number':None,'evidence':[]}
            states[key]=state
            item=observations[key]
            if item['number'] is not None:
                claims[item['number']].add(key)
            elif continuous and len(state['evidence'])>=PARAMETERS['minimum_distinct_frames']:
                claims[state['number']].add(key)
        blocked={key for keys in claims.values() if len(keys)>1 for key in keys}
        if blocked:
            flags.add('DUPLICATE_CLOTHING_COLOR')
        any_fresh=False
        for row in result['tracks']:
            key=row['track_id'];item=observations[key];state=states[key]
            row['clothing_color']=deepcopy(item)
            row['identity_source']='CLOTHING_COLOR'
            row['printed_number_observed']=False
            row['number_status']='UNKNOWN_CLOTHING_COLOR'
            if key in blocked or item['reason']=='MIXED_CLOTHING_COLORS':
                state={'number':None,'evidence':[]}
                row['number_status']='DUPLICATE_CLOTHING_COLOR' if key in blocked else 'MIXED_CLOTHING_COLORS'
            elif item['number'] is not None:
                if state['number'] is not None and state['number']!=item['number']:
                    flags.add('CONFLICTING_CLOTHING_COLOR')
                    state={'number':None,'evidence':[]}
                if fresh:
                    state['number']=item['number']
                    state['evidence']=(state['evidence']+[dict(frame_sha256=digest,
                        frame_index=frame_index,t=float(t),scene=scene,
                        color=item['color'],region_box=list(item['region_box']),
                        patch_sha256=item['patch_sha256'],reason=item['reason'])])[-20:]
                    row['fresh_label_observations_added']=1;any_fresh=True
                else:
                    flags.add('REPEATED_CLOTHING_FRAME_PIXELS')
                row['number_status']='INSUFFICIENT_DISTINCT_CLOTHING_OBSERVATIONS'
                if len(state['evidence'])>=PARAMETERS['minimum_distinct_frames']:
                    row.update(number=state['number'],number_status='CLOTHING_COLOR_CANDIDATE',
                               number_evidence_status='CURRENT_CLOTHING_COLOR')
            elif len(state['evidence'])>=PARAMETERS['minimum_distinct_frames']:
                # Base rider tracking already requires actual current points,
                # unambiguous ownership and a bounded age since detection.
                row.update(number=state['number'],number_status='PRIOR_CLOTHING_TRACK_CANDIDATE',
                    number_evidence_status='CURRENT_PIXEL_TRACK_PRIOR_CLOTHING_COLOR')
            row['clothing_identity']=dict(observations=len(state['evidence']),
                fresh_frames=deepcopy(state['evidence']),field_validated=False,
                scope='CLOTHING_COLOR_ON_CURRENT_RIDER_PIXEL_HYPOTHESIS')
            states[key]=state
        result['quality_flags']=sorted(flags)
        result['clothing_identity_policy']=dict(schema_version='RACE_AI_CLOTHING_COLOR_IDENTITY_V1',
            canonical_colors=dict(COLORS),parameters=deepcopy(PARAMETERS),
            printed_numbers_required=False,remaining_number_assignment=False,
            temporal_evidence='DISTINCT_SOURCE_BGR_FRAMES_AND_CURRENT_LK',
            region_semantics='POSITIONAL_PRIOR_NOT_GARMENT_SEGMENTATION')
        _need(source_digest==digest and sha256(frame.tobytes()).hexdigest()==digest
              and sha256(image.tobytes()).hexdigest()==digest)
        last_result=deepcopy(result)
        seen=set(self._seen)
        if any_fresh:
            seen.add(digest)
        self.riders,self._identities,self._seen,self._last_result=probe,states,seen,last_result
        return result
