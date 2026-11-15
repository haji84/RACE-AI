"""Controlled native-pixel rider parts, never a real six-boat accuracy claim."""
import hashlib
import importlib
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None
try:
    module = importlib.import_module('race_ai.boat_video_rider_tracking')
except ModuleNotFoundError:
    module = None


@unittest.skipIf(np is None, 'optional OpenCV/NumPy required')
class RiderTrackingTests(unittest.TestCase):
    def setUp(self):
        if module is None:
            self.fail('Optional anonymous rider component not implemented')
        cv2.setNumThreads(1)
        self.count = 6
        self.visible = True
        self.binding = 'DECLARED_PHYSICAL_RIDER_PRINT_PAIR'
        self.numbers = None
        self.bad_hash = False
        self.duplicate_views = False
        self.texture = np.random.default_rng(631).integers(0, 256, (70, 60, 3), np.uint8)

    def frame(self, index, *, blank=False):
        image = np.zeros((200, 640, 3), np.uint8)
        image[0, 0] = index
        if not blank:
            for i in range(self.count):
                x = 12+i*100+2*index
                image[55:125, x:x+60] = self.texture
        return image

    def detector(self, frame):
        index = int(frame[0, 0, 0])
        boxes = [[12+i*100+2*index, 55, 60, 70] for i in range(self.count)] if self.visible else []
        return {'schema_version':'RACE_AI_RIDER_PART_DETECTIONS_V1',
                'frame_sha256':hashlib.sha256(frame.tobytes()).hexdigest(),
                'coordinate_space':'IMAGE_PX','semantic_type':'RIDER_PART_TYPED',
                'detections':[{'box':b,'score':.9,'semantic_type':'RIDER_PART_TYPED','coco_class_id':0} for b in boxes],
                'engine':{'kind':'CONTROLLED_TEXTURE_FIXTURE_NOT_REAL_DETECTOR'},
                'identity_validated':False,'model_eligible':False}

    def provider(self, frame, riders, *, t, frame_index, scene):
        observations = []
        for i, rider in enumerate(riders):
            number = i+1 if self.numbers is None else self.numbers[i]
            if number is None:
                continue
            row = {'rider_track_id':rider['track_id'],'rider_box':list(rider['rider_box']),
                   'marker_box':[rider['rider_box'][0], 130, 8, 10], 'number':number,
                   'binding_kind':self.binding,'evidence_sha256':hashlib.sha256((str(frame_index)+rider['track_id']).encode()).hexdigest(),
                   'producer_sha256':'a'*64,'label_source':'DIRECT_PRINTED_MARK'}
            observations.append(row)
            if self.duplicate_views:
                observations.extend([dict(row), dict(row)])
        return {'schema_version':'RACE_AI_RIDER_NUMBER_PAIRS_V1',
                'frame_sha256':'0'*64 if self.bad_hash else hashlib.sha256(frame.tobytes()).hexdigest(),
                'frame_index':frame_index,'t':t,'scene':scene,'observations':observations}

    def tracker(self, *, numbers=False, detector=None, provider=None):
        return module.RiderPartTracker(detector or self.detector,
            number_provider=(provider or self.provider) if numbers else None)

    def update(self, tracker, index, *, t=None, scene=0, frame=None):
        return tracker.update(self.frame(index) if frame is None else frame,
                              t=index/10 if t is None else t, frame_index=index, scene=scene)

    def test_six_anonymous_parts_follow_actual_pixels_without_number_or_hull_claim(self):
        tracker = self.tracker()
        first = self.update(tracker, 0)
        keys = [r['track_id'] for r in first['tracks']]
        for index in range(1,4):
            result = self.update(tracker,index)
            self.assertEqual([r['track_id'] for r in result['tracks']],keys)
            self.assertEqual(len(result['tracks']),6)
            for row in result['tracks']:
                self.assertIsNone(row['number'])
                self.assertIsNone(row['hull_box'])
                self.assertEqual(row['semantic_type'],'RIDER_PART_TYPED')
                self.assertEqual(row['visibility_status'],'DETECTION_AND_PIXEL_TRACK')
                self.assertGreaterEqual(row['pixel_support']['point_count'],4)
            self.assertFalse(result['model_eligible'])
            self.assertFalse(result['metric_positions_inferred'])

    def test_actual_pinned_detector_envelope_integrates_without_changing_semantics(self):
        # Exercise the actual wrapper/schema, with only costly raw NN inference replaced.
        from race_ai.boat_video_rider_detector import PinnedRiderPartDetector
        from types import SimpleNamespace
        detector=object.__new__(PinnedRiderPartDetector)
        detector._tiled=False
        detector._model=SimpleNamespace(metadata=lambda:{'engine':'CONTROLLED_INFERENCE_DEPENDENCY'})
        detector._infer=lambda frame:[{'box':row['box'],'score':row['score']}
                                      for row in self.detector(frame)['detections']]
        tracker=self.tracker(detector=detector)
        first=self.update(tracker,0)
        result=self.update(tracker,1)
        self.assertEqual(len(result['tracks']),6)
        self.assertEqual([r['track_id'] for r in result['tracks']],
                         [r['track_id'] for r in first['tracks']])
        self.assertFalse(result['identity_validated'])
        self.assertEqual(result['detector_engine']['class_scope'],'GENERIC_COCO_PERSON_PART_CANDIDATE')
        self.assertTrue(all(row['hull_box'] is None and row['number'] is None for row in result['tracks']))

    def test_zero_and_two_visible_detections_do_not_force_six(self):
        self.count = 2
        tracker = self.tracker()
        self.assertEqual(len(self.update(tracker,0)['tracks']),2)
        self.visible = False
        result = self.update(tracker,1,frame=self.frame(1,blank=True))
        self.assertEqual(result['tracks'],[])
        self.assertEqual(len(result['lost_track_ids']),2)

    def test_unread_number_holds_prior_label_only_with_current_pixel_and_detection_support(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
        key=result['tracks'][0]['track_id']
        self.assertEqual(result['tracks'][0]['number'],1)
        self.numbers=[None]
        result=self.update(tracker,3)
        self.assertEqual(result['tracks'][0]['track_id'],key)
        row=result['tracks'][0]
        self.assertEqual(row['number'],1)
        self.assertEqual(row['number_evidence_status'],'CURRENT_VISIBLE_TRACK_PRIOR_PRINT')
        self.assertFalse(row['printed_number_observed'])
        self.assertEqual(row['fresh_label_observations_added'],0)
        self.assertEqual(row['number_evidence']['observations'],3)
        self.assertEqual(row['number_evidence']['last_print_frame_index'],2)
        self.assertEqual(row['number_evidence']['last_print_t'],.2)

    def test_detector_absent_pixel_support_keeps_anonymous_track_without_prior_label(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
        key=result['tracks'][0]['track_id']
        self.visible=False
        self.numbers=[None]
        row=self.update(tracker,3)['tracks'][0]
        self.assertEqual(row['track_id'],key)
        self.assertIsNone(row['number'])
        self.assertFalse(row['detector_fresh'])

    def test_prior_print_age_is_reported_without_new_votes_during_supported_body_continuity(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            self.update(tracker,index)
        self.numbers=[None]
        for index in range(3,12):
            row=self.update(tracker,index)['tracks'][0]
            self.assertEqual(row['number'],1)
            self.assertFalse(row['printed_number_observed'])
            self.assertEqual(row['fresh_label_observations_added'],0)
            self.assertEqual(row['number_evidence']['observations'],3)
            self.assertEqual(row['number_evidence']['last_print_t'],.2)

    def test_same_current_point_owner_views_keep_one_representative_and_all_raw_proposals(self):
        self.count=1
        def detector(frame):
            packet=self.detector(frame)
            if int(frame[0,0,0])>0:
                packet['detections'].append(dict(packet['detections'][0],box=[16,55,60,70]))
            return packet
        tracker=self.tracker(detector=detector)
        key=self.update(tracker,0)['tracks'][0]['track_id']
        result=self.update(tracker,1)
        self.assertEqual([row['track_id'] for row in result['tracks']],[key])
        self.assertEqual(len(result['raw_detections']),2)
        self.assertEqual(len(result['unknown_detections']),1)
        self.assertTrue(all(row['number'] is None for row in result['tracks']))

    def test_one_detection_covering_two_old_point_owners_is_ambiguous_and_not_a_new_person(self):
        self.count=2
        def detector(frame):
            packet=self.detector(frame)
            if int(frame[0,0,0])>0:
                packet['detections']=[dict(packet['detections'][0],box=[14,55,160,70])]
            return packet
        tracker=self.tracker(detector=detector)
        keys=[row['track_id'] for row in self.update(tracker,0)['tracks']]
        result=self.update(tracker,1)
        self.assertEqual(result['tracks'],[])
        self.assertEqual(result['lost_track_ids'],keys)
        self.assertEqual(len(result['unknown_detections']),1)
        self.assertIn('AMBIGUOUS',result['unknown_detections'][0]['reason'])

    def test_current_reliable_points_preserve_identity_when_detection_grows_below_iou_half(self):
        self.count=1
        def detector(frame):
            packet=self.detector(frame)
            if int(frame[0,0,0])>=3:
                packet['detections'][0]['box'][2]=125
            return packet
        tracker=self.tracker(numbers=True,detector=detector)
        for index in range(3):
            result=self.update(tracker,index)
        key=result['tracks'][0]['track_id']
        self.numbers=[None]
        result=self.update(tracker,3)
        row=result['tracks'][0]
        self.assertEqual(row['track_id'],key)
        self.assertEqual(row['number'],1)
        self.assertEqual(row['number_evidence']['observations'],3)
        self.assertEqual(row['fresh_label_observations_added'],0)
        evidence=row['association_evidence']
        self.assertEqual(evidence['method'],'CURRENT_LK_POINT_SUPPORT')
        self.assertGreaterEqual(evidence['support_fraction'],.75)
        self.assertEqual(evidence['foreign_track_points_in_detection'],0)
        self.assertEqual(evidence['frame_sha256'],result['frame_sha256'])

    def test_partial_same_owner_proposal_is_preserved_unbound_without_new_rider(self):
        self.count=1
        def detector(frame):
            packet=self.detector(frame)
            if int(frame[0,0,0])>0:
                packet['detections'].append(dict(packet['detections'][0],box=[14,55,25,70],score=.999))
            return packet
        tracker=self.tracker(detector=detector)
        key=self.update(tracker,0)['tracks'][0]['track_id']
        result=self.update(tracker,1)
        self.assertEqual([row['track_id'] for row in result['tracks']],[key])
        self.assertEqual(len(result['raw_detections']),2)
        self.assertEqual(len(result['unknown_detections']),1)
        self.assertIn('UNBOUND',result['unknown_detections'][0]['reason'])
        self.assertEqual(result['unknown_detections'][0]['score'],.999)

    def test_disjoint_new_visible_person_still_gets_a_new_anonymous_key(self):
        self.count=2
        def detector(frame):
            packet=self.detector(frame)
            if int(frame[0,0,0])==0:
                packet['detections']=packet['detections'][:1]
            return packet
        tracker=self.tracker(detector=detector)
        key=self.update(tracker,0)['tracks'][0]['track_id']
        result=self.update(tracker,1)
        self.assertEqual(len(result['tracks']),2)
        self.assertEqual(result['tracks'][0]['track_id'],key)
        self.assertEqual(result['tracks'][1]['visibility_status'],'CURRENT_DETECTION_UNTRACKED')

    def test_point_fallback_rejects_partial_foreign_and_multiple_old_owners(self):
        associate=getattr(module,'_point_correspondences',None)
        self.assertIsNotNone(associate,'current measured point association is missing')
        if associate is None:
            return
        points=np.array([[10,10],[20,10],[10,20],[20,20]],np.float32)
        pixels={'R1':{'box':[0,0,40,40],'point_count':4}}
        states={'R1':{'points':points}}
        matched,_,_,_,_=associate(pixels,states,[{'box':[5,5,100,100],'score':.6}])
        self.assertEqual(matched,{0:'R1'})
        partial=[{'box':[5,5,10,10],'score':.99}]
        partial_result=associate(pixels,states,partial)
        self.assertEqual(partial_result[0],{})
        self.assertIn(0,partial_result[2])
        foreign=np.array([[12,12],[150,12],[12,150],[150,150]],np.float32)
        pixels['R2']={'box':[0,0,160,160],'point_count':4}
        states['R2']={'points':foreign}
        foreign_result=associate(pixels,states,[{'box':[5,5,100,100],'score':.6}])
        self.assertEqual(foreign_result[0],{})
        self.assertIn(0,foreign_result[2])
        pixels['R2']={'box':[5,5,40,40],'point_count':4}
        states['R2']={'points':points.copy()}
        matched,ambiguous,unbound,_,_=associate(pixels,states,[{'box':[5,5,100,100],'score':.6}])
        self.assertEqual(matched,{})
        self.assertEqual(ambiguous,{'R1','R2'})
        self.assertIn(0,unbound)

    def test_point_fraction_uses_existing_three_quarters_boundary_without_iou_lowering(self):
        points=np.array([[10,10],[20,10],[30,10],[10,20],[20,20],[25,20],[100,100],[110,110]],np.float32)
        pixels={'R1':{'box':[0,0,120,120],'point_count':8}}
        states={'R1':{'points':points}}
        matched,_,_,evidence,edges=module._point_correspondences(pixels,states,[{'box':[5,5,26,26],'score':.5}])
        self.assertEqual(edges['R1'],[])
        self.assertEqual(matched,{0:'R1'})
        self.assertEqual(evidence[0]['support_fraction'],.75)
        matched,_,unbound,_,_=module._point_correspondences(pixels,states,[{'box':[5,5,24,26],'score':.99}])
        self.assertEqual(matched,{})
        self.assertIn(0,unbound)

    def test_one_shared_current_point_blocks_new_birth_without_weakening_association(self):
        points=np.array([[10,10],[20,10],[10,20],[20,20]],np.float32)
        pixels={'R1':{'box':[0,0,40,40],'point_count':4}}
        states={'R1':{'points':points}}
        detections=[{'box':[0,0,40,40],'score':.6},{'box':[19,19,60,60],'score':.99}]
        matches,_,unbound,_,_=module._point_correspondences(pixels,states,detections)
        self.assertEqual(matches,{0:'R1'})
        self.assertIn(1,unbound)
        self.assertIn('R1',unbound[1]['point_owner_track_ids'])
        detections[1]['box']=[100,100,60,60]
        matches,_,unbound,_,_=module._point_correspondences(pixels,states,detections)
        self.assertEqual(matches,{0:'R1'})
        self.assertNotIn(1,unbound)

    def test_person_semantics_or_identity_cannot_be_promoted_by_detector_metadata(self):
        self.count=1
        for field,value in [('identity_validated',True),('model_eligible',True),('semantic_type','WHOLE_BOAT')]:
            def detector(frame):
                packet=self.detector(frame)
                packet[field]=value
                return packet
            tracker=self.tracker(detector=detector)
            with self.assertRaises(ValueError):
                self.update(tracker,0)

    def test_three_distinct_source_frames_are_needed_for_each_number(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            row=self.update(tracker,index)['tracks'][0]
            self.assertEqual(row['number'],1 if index==2 else None)
        evidence=row['number_evidence']['fresh_frames']
        self.assertEqual(len({r['frame_sha256'] for r in evidence}),3)
        self.assertEqual([r['frame_index'] for r in evidence],[0,1,2])
        self.assertEqual([r['t'] for r in evidence],[0.,.1,.2])

    def test_repeated_pixels_and_duplicate_views_cannot_create_three_votes(self):
        self.count=1
        self.duplicate_views=True
        tracker=self.tracker(numbers=True)
        original=self.frame(0)
        for index in range(3):
            result=self.update(tracker,index,frame=original)
            self.assertIsNone(result['tracks'][0]['number'])
        self.assertIn('REPEATED_NUMBER_FRAME_PIXELS',result['quality_flags'])

    def test_replayed_pixel_conflict_invalidates_prior_label_without_adding_new_vote(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            self.update(tracker,index)
        self.numbers=[2]
        row=self.update(tracker,3,frame=self.frame(0))['tracks'][0]
        self.assertIsNone(row['number'])
        self.assertEqual(row['fresh_label_observations_added'],0)
        self.numbers=[None]
        row=self.update(tracker,4)['tracks'][0]
        self.assertIsNone(row['number'])
        self.assertIsNone(row['number_evidence'])

    def test_containment_or_nearest_pair_is_not_a_physical_number_binding(self):
        self.count=1
        for binding in ('BBOX_CONTAINMENT','NEAREST_MARKER','UNBOUND'):
            self.binding=binding
            tracker=self.tracker(numbers=True)
            for index in range(3):
                result=self.update(tracker,index)
                self.assertIsNone(result['tracks'][0]['number'])
                self.assertEqual(result['tracks'][0]['number_status'],'UNSUPPORTED_BINDING')

    def test_conflicting_number_clears_label_evidence_but_not_anonymous_key(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
        key=result['tracks'][0]['track_id']
        self.numbers=[2]
        result=self.update(tracker,3)
        self.assertIsNone(result['tracks'][0]['number'])
        self.assertEqual(result['tracks'][0]['track_id'],key)
        for index in (4,5):
            result=self.update(tracker,index)
        self.assertEqual(result['tracks'][0]['number'],2)
        self.assertEqual(result['tracks'][0]['number_evidence']['observations'],3)

    def test_duplicate_number_on_separate_riders_is_unknown_on_both(self):
        self.count=2
        self.numbers=[1,1]
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
            self.assertEqual(len(result['tracks']),2)
            self.assertTrue(all(r['number'] is None for r in result['tracks']))
            self.assertTrue(all(r['number_status']=='DUPLICATE_NUMBER' for r in result['tracks']))

    def test_new_fresh_number_cannot_duplicate_another_riders_prior_print_label(self):
        self.count=2
        tracker=self.tracker(numbers=True)
        for index in range(3):
            self.update(tracker,index)
        self.numbers=[2,None]
        result=self.update(tracker,3)
        self.assertTrue(all(r['number'] is None for r in result['tracks']))
        self.assertTrue(all(r['number_status']=='DUPLICATE_NUMBER' for r in result['tracks']))

    def test_appearance_prediction_cannot_be_declared_as_current_print(self):
        self.count=1
        def provider(*args,**kwargs):
            packet=self.provider(*args,**kwargs)
            packet['observations'][0]['label_source']='RIDER_APPEARANCE_CANDIDATE'
            return packet
        tracker=self.tracker(numbers=True,provider=provider)
        with self.assertRaises(ValueError):
            self.update(tracker,0)
        tracker.number_provider=self.provider
        self.assertEqual(self.update(tracker,0)['tracks'][0]['track_id'],'R000001')

    def test_output_mutation_cannot_change_internal_number_or_pixel_history(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
        result['tracks'][0]['number_evidence']['fresh_frames'].clear()
        result['tracks'][0]['rider_box'][0]=500
        self.numbers=[None]
        row=self.update(tracker,3)['tracks'][0]
        self.assertEqual(row['number'],1)
        self.assertEqual(row['number_evidence']['observations'],3)
        self.assertLess(row['rider_box'][0],30)

    def test_actual_pixel_track_without_detector_expires_at_half_second(self):
        self.count=1
        tracker=self.tracker()
        key=self.update(tracker,0)['tracks'][0]['track_id']
        self.visible=False
        for index in (1,2,3,4):
            row=self.update(tracker,index)['tracks'][0]
            self.assertEqual(row['track_id'],key)
            self.assertEqual(row['visibility_status'],'PIXEL_TRACKED_RIDER_HYPOTHESIS')
        result=self.update(tracker,5)
        self.assertEqual(result['tracks'],[])
        self.assertIn(key,result['lost_track_ids'])

    def test_overlapping_pixel_only_riders_are_ambiguous_without_current_detections(self):
        self.count=1
        def detector(frame):
            packet=self.detector(frame)
            if self.visible:
                packet['detections'].append(dict(packet['detections'][0],box=[14,55,60,70]))
            return packet
        tracker=self.tracker(detector=detector)
        keys=[row['track_id'] for row in self.update(tracker,0)['tracks']]
        self.assertEqual(len(keys),2)
        self.visible=False
        result=self.update(tracker,1)
        self.assertEqual(result['tracks'],[])
        self.assertEqual(result['lost_track_ids'],keys)
        self.assertIn('AMBIGUOUS_PIXEL_ONLY_RIDER_OVERLAP',result['quality_flags'])

    def test_one_print_region_cannot_label_two_riders_with_conflicting_numbers(self):
        self.count=2
        def provider(*args,**kwargs):
            packet=self.provider(*args,**kwargs)
            packet['observations'][1]['marker_box']=list(packet['observations'][0]['marker_box'])
            return packet
        tracker=self.tracker(numbers=True,provider=provider)
        for index in range(3):
            result=self.update(tracker,index)
            self.assertTrue(all(row['number'] is None for row in result['tracks']))
            self.assertTrue(all(row['fresh_label_observations_added']==0 for row in result['tracks']))
            self.assertTrue(all(row['number_evidence'] is None for row in result['tracks']))
            self.assertTrue(all(row['number_status']=='CONFLICTING_SHARED_PRINT_MARKER' for row in result['tracks']))

    def test_shared_document_evidence_hash_does_not_merge_distinct_print_regions(self):
        self.count=2
        def provider(*args,**kwargs):
            packet=self.provider(*args,**kwargs)
            for row in packet['observations']:
                row['evidence_sha256']='b'*64
            return packet
        tracker=self.tracker(numbers=True,provider=provider)
        for index in range(3):
            result=self.update(tracker,index)
        self.assertEqual([row['number'] for row in result['tracks']],[1,2])

    def test_one_pixel_shift_of_conflicting_print_cannot_create_a_second_owner(self):
        self.count=2
        def provider(*args,**kwargs):
            packet=self.provider(*args,**kwargs)
            box=list(packet['observations'][0]['marker_box'])
            box[0]+=1
            packet['observations'][1]['marker_box']=box
            return packet
        tracker=self.tracker(numbers=True,provider=provider)
        for index in range(3):
            result=self.update(tracker,index)
            self.assertTrue(all(row['number'] is None for row in result['tracks']))
            self.assertTrue(all(row['fresh_label_observations_added']==0 for row in result['tracks']))
            self.assertTrue(all(row['number_status']=='CONFLICTING_SHARED_PRINT_MARKER' for row in result['tracks']))

    def test_loss_then_reacquisition_uses_new_anonymous_key_and_number_evidence(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        for index in range(3):
            result=self.update(tracker,index)
        old=result['tracks'][0]['track_id']
        self.visible=False
        self.assertEqual(self.update(tracker,3,frame=self.frame(3,blank=True))['tracks'],[])
        self.visible=True
        row=self.update(tracker,4)['tracks'][0]
        self.assertNotEqual(row['track_id'],old)
        self.assertIsNone(row['number'])

    def test_scene_shape_and_exact_half_second_gap_reset_objects(self):
        self.count=1
        for kind in ('scene','shape','gap'):
            tracker=self.tracker()
            old=self.update(tracker,0)['tracks'][0]['track_id']
            kwargs={'scene':1} if kind=='scene' else {'t':.5} if kind=='gap' else {'frame':np.pad(self.frame(1),((0,10),(0,0),(0,0)))}
            row=self.update(tracker,1,**kwargs)['tracks'][0]
            self.assertNotEqual(row['track_id'],old)
            self.assertIsNone(row['number'])

    def test_bad_pair_packet_is_atomic_and_same_frame_can_retry(self):
        self.count=1
        tracker=self.tracker(numbers=True)
        self.bad_hash=True
        with self.assertRaises(ValueError):
            self.update(tracker,0)
        self.bad_hash=False
        row=self.update(tracker,0)['tracks'][0]
        self.assertEqual(row['track_id'],'R000001')
        self.assertIsNone(row['number'])

    def test_invalid_detector_or_frame_does_not_publish_partial_state(self):
        self.count=1
        broken=True
        def detector(frame):
            packet=self.detector(frame)
            if broken:
                packet['detections'][0]['box']=[float('nan'),1,2,3]
            return packet
        tracker=self.tracker(detector=detector)
        with self.assertRaises(ValueError):
            self.update(tracker,0)
        broken=False
        self.assertEqual(self.update(tracker,0)['tracks'][0]['track_id'],'R000001')
        with self.assertRaises(ValueError):
            self.update(tracker,1,t=0)

    def test_callback_pixel_mutation_is_rejected_and_does_not_advance_clock(self):
        self.count=1
        mutate=True
        def detector(frame):
            packet=self.detector(frame)
            if mutate:
                frame[5,5]=255
            return packet
        tracker=self.tracker(detector=detector)
        with self.assertRaises(ValueError):
            self.update(tracker,0)
        mutate=False
        self.assertEqual(self.update(tracker,0)['tracks'][0]['track_id'],'R000001')


if __name__=='__main__':
    unittest.main()
