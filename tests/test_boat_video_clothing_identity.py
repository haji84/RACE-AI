"""Clothing observations and real pixel continuity; no printed digit fixture."""
from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None


@unittest.skipIf(np is None, 'optional OpenCV/NumPy required')
class ClothingIdentityTests(unittest.TestCase):
    def setUp(self):
        from race_ai import boat_video_clothing_identity as module
        from race_ai.boat_video_rider_tracking import RiderPartTracker
        self.module = module
        self.colors = [(225,225,225),(55,55,55),(70,70,210),
                       (210,130,70),(50,215,225),(175,204,193)]
        self.visible = True
        self.score = .9
        self.boxes = [[10+i*100,40,70,100] for i in range(6)]
        self.tracker = module.ClothingColorIdentityTracker(RiderPartTracker(self.detector))
        self.noise = np.random.default_rng(1927).integers(-8,9,(100,70,1))
        self.texture = np.random.default_rng(1928).integers(0,256,(25,24,3),np.uint8)
        cv2.setNumThreads(1)

    def frame(self, index):
        frame = np.full((180,640,3),120,np.uint8)
        frame[0,0] = index
        for box,color in zip(self.boxes,self.colors):
            x,y,w,h=box
            frame[y:y+h,x:x+w]=np.clip(np.array(color)+self.noise,0,255).astype(np.uint8)
            # Incompatible helmet and white hull are outside the torso prior.
            frame[y:y+25,x:x+w]=(220,50,220)
            frame[y:y+25,x+2:x+26]=self.texture
            frame[y+85:y+h,x:x+w]=(245,245,245)
        return frame

    def detector(self, frame):
        return dict(schema_version='RACE_AI_RIDER_PART_DETECTIONS_V1',
            frame_sha256=sha256(frame.tobytes()).hexdigest(),coordinate_space='IMAGE_PX',
            semantic_type='RIDER_PART_TYPED',detections=[dict(box=b,score=self.score,
            semantic_type='RIDER_PART_TYPED',coco_class_id=0) for b in self.boxes] if self.visible else [],
            engine={'kind':'CONTROLLED_PERSON_FIXTURE'},identity_validated=False,model_eligible=False)

    def update(self,index,**kw):
        frame=kw.pop('frame',self.frame(index))
        return self.tracker.update(frame,t=index/10,frame_index=index,scene=kw.pop('scene',0),**kw)

    def establish(self):
        for i in range(3):
            result=self.update(i)
        return result

    def test_six_clothing_colors_without_any_printed_numbers(self):
        result=self.establish()
        self.assertEqual([r['number'] for r in result['tracks']],[1,2,3,4,5,6])
        for row in result['tracks']:
            self.assertEqual(row['number_evidence_status'],'CURRENT_CLOTHING_COLOR')
            self.assertFalse(row['printed_number_observed'])
            self.assertEqual(row['fresh_label_observations_added'],1)
            self.assertEqual(row['clothing_identity']['observations'],3)
            self.assertEqual(row['clothing_color']['region_kind'],'TORSO_POSITIONAL_PRIOR_NOT_SEGMENTATION')
        self.assertFalse(result['identity_validated'])
        self.assertFalse(result['model_eligible'])

    def test_pale_green_is_not_white_and_helmet_color_is_not_used(self):
        result=self.establish()
        self.assertEqual(result['tracks'][5]['clothing_color']['color'],'GREEN')
        self.assertEqual(result['tracks'][0]['clothing_color']['color'],'WHITE')

    def test_almost_neutral_green_is_unknown_instead_of_using_white_contrast(self):
        self.colors[5]=(190,205,200)
        row=self.establish()['tracks'][5]
        self.assertIsNone(row['clothing_color']['number'])
        self.assertEqual(row['clothing_color']['reason'],'PALE_CHROMA_UNRESOLVED')
        self.assertIsNone(row['number'])

    def test_single_shadowed_neutral_garment_is_unknown_without_reference(self):
        self.boxes=self.boxes[:1];self.colors=[(124,124,124)]
        row=self.establish()['tracks'][0]
        self.assertIsNone(row['number'])
        self.assertEqual(row['clothing_color']['reason'],'ACHROMATIC_LIGHTING_AMBIGUOUS')

    def test_mixed_red_green_garment_does_not_select_one_color(self):
        self.boxes=self.boxes[:1]
        for i in range(3):
            frame=self.frame(i)
            frame[75:115,24:45]=(40,40,220)
            frame[75:115,45:66]=(40,220,40)
            result=self.update(i,frame=frame)
        self.assertIsNone(result['tracks'][0]['number'])
        self.assertEqual(result['tracks'][0]['clothing_color']['reason'],'MIXED_CLOTHING_COLORS')

    def test_small_colored_stripe_cannot_override_unknown_neutral(self):
        self.boxes=self.boxes[:1];self.colors=[(115,115,115)]
        for i in range(3):
            frame=self.frame(i);frame[75:115,24:28]=(40,220,40)
            result=self.update(i,frame=frame)
        self.assertIsNone(result['tracks'][0]['number'])

    def test_weak_person_proposal_cannot_label_motor_or_water(self):
        self.score=.55
        result=self.establish()
        self.assertTrue(all(r['number'] is None for r in result['tracks']))
        self.assertTrue(all(r['clothing_color']['reason']=='WEAK_PERSON_PROPOSAL' for r in result['tracks']))

    def test_no_person_proposal_does_not_label_green_water(self):
        self.visible=False
        result=self.update(0,frame=np.full((180,640,3),(70,200,80),np.uint8))
        self.assertEqual(result['tracks'],[])

    def test_duplicate_color_clears_both_current_and_prior_claims(self):
        self.establish()
        self.colors[3]=self.colors[2]
        result=self.update(3)
        for i in (2,3):
            self.assertIsNone(result['tracks'][i]['number'])
            self.assertEqual(result['tracks'][i]['number_status'],'DUPLICATE_CLOTHING_COLOR')

    def test_invisible_color_retains_prior_only_on_actual_pixel_lineage(self):
        self.establish()
        # The person detector no longer supplies a usable semantic observation;
        # independently measured current pixels still support the same rider.
        self.score=.55
        row=self.update(3)['tracks'][3]
        self.assertEqual(row['number'],4)
        self.assertEqual(row['number_evidence_status'],'CURRENT_PIXEL_TRACK_PRIOR_CLOTHING_COLOR')
        self.assertEqual(row['fresh_label_observations_added'],0)
        self.assertEqual(row['clothing_identity']['observations'],3)

    def test_conflicting_current_color_invalidates_prior_and_restarts(self):
        self.boxes=self.boxes[:5];self.colors=self.colors[:5]
        self.establish()
        # Similar greyscale luminance, conflicting chroma; LK must really pass.
        self.colors[3]=(60,155,60)
        row=self.update(3)['tracks'][3]
        self.assertIsNone(row['number'])
        self.assertEqual(row['number_status'],'INSUFFICIENT_DISTINCT_CLOTHING_OBSERVATIONS')
        self.assertEqual(row['clothing_identity']['observations'],1)

    def test_identical_pixels_at_new_pts_cannot_supply_three_observations(self):
        frame=self.frame(0)
        for i in range(3):
            result=self.update(i,frame=frame)
        self.assertTrue(all(r['number'] is None for r in result['tracks']))
        self.assertTrue(all(r['clothing_identity']['observations']==1 for r in result['tracks']))

    def test_cut_resets_clothing_identity_without_transferring_ids(self):
        old=self.establish()
        result=self.update(3,scene=1)
        self.assertTrue(all(r['number'] is None for r in result['tracks']))
        self.assertFalse(set(r['track_id'] for r in old['tracks']) & set(r['track_id'] for r in result['tracks']))

    def test_caller_frame_and_source_evidence_are_preserved(self):
        frame=self.frame(0);before=frame.copy();result=self.update(0,frame=frame)
        self.assertTrue(np.array_equal(frame,before))
        for row in result['tracks']:
            self.assertEqual(row['clothing_color']['frame_sha256'],sha256(frame.tobytes()).hexdigest())
            self.assertFalse(row['clothing_color']['calibrated_probability'])

    def test_invalid_rider_packet_is_rejected_without_committing_identity(self):
        self.establish();before=deepcopy(self.tracker._identities)
        # The public measurement stage validates context before accessing pixels.
        packet=deepcopy(self.tracker._last_result);packet['frame_sha256']='0'*64
        with self.assertRaises(ValueError):
            self.module.measure_clothing_colors(self.frame(3),packet)
        self.assertEqual(self.tracker._identities,before)

    def test_final_allocation_failure_does_not_advance_rider_or_color_state(self):
        self.establish()
        before=deepcopy((self.tracker._identities,self.tracker._seen,self.tracker._last_result))
        time=self.tracker.riders._time
        def fail_final_copy(value):
            if isinstance(value,dict) and 'clothing_identity_policy' in value:
                raise MemoryError('CONTROLLED_FINAL_ALLOCATION_FAILURE')
            return deepcopy(value)
        with patch.object(self.module,'deepcopy',side_effect=fail_final_copy):
            with self.assertRaises(MemoryError):
                self.update(3)
        self.assertEqual(self.tracker.riders._time,time)
        self.assertEqual((self.tracker._identities,self.tracker._seen,self.tracker._last_result),before)
        self.assertEqual(self.update(3)['frame_index'],3)

    def test_measurement_uses_private_pixels_when_caller_temporarily_changes_and_restores(self):
        self.boxes=self.boxes[:1];self.colors=[(210,130,70)]
        convert=cv2.cvtColor
        for i in range(3):
            frame=self.frame(i);original=frame.copy()
            def temporary_change(image,code,*args,**kwargs):
                frame[75:115,24:66]=(40,40,220)
                try:
                    return convert(image,code,*args,**kwargs)
                finally:
                    frame[:]=original
            with patch.object(cv2,'cvtColor',side_effect=temporary_change):
                result=self.update(i,frame=frame)
            self.assertTrue(np.array_equal(frame,original))
        self.assertEqual(result['tracks'][0]['number'],4)


if __name__=='__main__':
    unittest.main()
