"""Pinned primary-water evidence and declared topic; no exhibition truth."""
from copy import deepcopy,copy
from hashlib import sha256
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import sys
import os
import pickle
from contextlib import nullcontext
from types import SimpleNamespace

try:
    import cv2
    import numpy as np
except ImportError:cv2=np=None


@unittest.skipIf(np is None,'optional OpenCV/NumPy needed')
class ActivityTests(unittest.TestCase):
    def setUp(self):
        try:from race_ai import boat_video_activity as module
        except ImportError:self.fail('Primary water content component missing')
        self.module=module;self.media='a'*64
        self.image=np.zeros((100,100,3),np.uint8)
        self.labels=np.zeros((100,100),np.uint8);self.labels[25:85,:]=21
        self.boats=[]

    def context(self):
        return dict(schema_version='RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1',media_sha256=self.media,
                    topic='EXHIBITION_TUTORIAL',provenance_sha256='b'*64)

    def measure(self,context=None):
        return self.module.measure_primary_water(self.labels,self.boats,media_sha256=self.media,
            frame_sha256=sha256(self.image.tobytes()).hexdigest(),source_context=context)

    def test_water_alone_is_not_a_boat_or_exhibition_claim(self):
        result=self.measure()
        self.assertTrue(result['primary_water_content_candidate'])
        self.assertFalse(result['depicted_exhibition_content_candidate'])
        self.assertEqual(result['display_status'],'PRIMARY_WATER_CONTENT_CANDIDATE')
        self.assertEqual(result['current_boat_visual_support']['status'],'NOT_DETECTED_UNKNOWN')
        self.assertFalse(result['authenticated_current_exhibition'])
        self.assertFalse(result['model_eligible'])

    def test_same_media_declared_topic_conditions_content_only(self):
        result=self.measure(self.context())
        self.assertTrue(result['depicted_exhibition_content_candidate'])
        self.assertEqual(result['display_status'],'EXHIBITION_TOPIC_PRIMARY_WATER_CONTENT_CANDIDATE')
        self.assertFalse(result['usable_for_identity'])
        self.assertEqual(result['specific_phase'],'UNKNOWN')
        self.assertEqual(result['topic_context_scope'],'DECLARED_LOCAL_HASH_NOT_AUTHENTICATED_PROVIDER_OR_EVENT')

    def test_wrong_media_topic_or_forged_authenticated_flag_is_rejected(self):
        for context in [dict(self.context(),media_sha256='c'*64),dict(self.context(),authenticated=True)]:
            with self.subTest(context=context):
                with self.assertRaises(ValueError):self.measure(context)

    def test_unknown_topic_does_not_promote_water_to_exhibition(self):
        context=self.context();context['topic']='UNKNOWN'
        self.assertFalse(self.measure(context)['depicted_exhibition_content_candidate'])

    def test_boat_foreground_at_center_is_consistent_with_primary_water_scene(self):
        self.labels[45:55,45:55]=76
        result=self.measure()
        self.assertFalse(result['center_is_water'])
        self.assertTrue(result['center_supported_by_semantic_water_boat_or_ship'])
        self.assertTrue(result['primary_water_content_candidate'])

    def test_current_coco_boat_can_support_occluded_center_without_filling_water(self):
        self.labels[45:55,45:55]=1
        self.boats=[dict(box=[40,40,20,20],score=.8)]
        result=self.measure()
        self.assertTrue(result['center_supported_by_current_COCO_boat_box'])
        self.assertTrue(result['primary_water_content_candidate'])
        self.labels[:]=1
        self.assertFalse(self.measure()['primary_water_content_candidate'])

    def test_small_real_boat_inset_is_not_primary_content(self):
        self.labels[:]=1;self.labels[25:75,25:75]=21
        self.boats=[dict(box=[40,40,20,20],score=.8)]
        result=self.measure(self.context())
        self.assertTrue(result['embedded_water_geometry_candidate'])
        self.assertFalse(result['primary_water_content_candidate'])
        self.assertFalse(result['depicted_exhibition_content_candidate'])

    def test_full_water_threshold_is_not_lowered_for_near_boundary_case(self):
        self.labels[:]=1;self.labels[20:64,:]=21
        self.assertFalse(self.measure()['primary_water_content_candidate'])

    def test_other_water_like_labels_do_not_replace_frozen_water_classes(self):
        for label in [31,56,109,113]:
            with self.subTest(label=label):
                self.labels[:]=label
                self.assertEqual(self.measure()['water_fraction'],0.)

    def test_pinned_ADE_lake128_is_a_natural_water_surface(self):
        self.labels[:]=128
        result=self.measure()
        self.assertEqual(result['water_fraction'],1.)
        self.assertTrue(result['center_is_water'])
        self.assertTrue(result['primary_water_content_candidate'])
        self.assertFalse(result['depicted_exhibition_content_candidate'])

    def test_invalid_labels_or_detector_boxes_cannot_be_used(self):
        for labels,boats in [(self.labels.astype(float),[]),
                             (np.full((100,100),255,np.uint8),[]),
                             (self.labels,[dict(box=[-1,0,50,50],score=.8)]),
                             (self.labels,[dict(box=[0,0,50,50],score=float('nan'))])]:
            with self.subTest(boats=boats):
                with self.assertRaises(ValueError):
                    self.module.measure_primary_water(labels,boats,media_sha256=self.media,
                        frame_sha256='d'*64,source_context=None)

    def reader(self):
        reader=object.__new__(self.module.LocalPrimaryWaterReader)
        reader._asset_paths={};reader._asset_pins={}
        reader._metadata={'scope':'CONTROLLED_SYNTHETIC_BACKENDS_NOT_PINNED_INFERENCE'}
        reader._processing_timeout_seconds=60.
        reader._check_assets=lambda:self.module._need(all(self.module._identity(path)==reader._asset_pins[name]
            for name,path in reader._asset_paths.items()))
        reader._infer=lambda frame:self.labels.copy()
        reader._boat=lambda frame:deepcopy(self.boats)
        return reader

    def test_reader_preserves_caller_frame_and_source_hashes(self):
        before=self.image.copy();result=self.reader()(self.image,media_sha256=self.media,source_context=self.context())
        self.assertTrue(np.array_equal(self.image,before))
        self.assertEqual(result['frame_sha256'],sha256(before.tobytes()).hexdigest())
        self.assertEqual(result['media_sha256'],self.media)
        self.assertFalse(result['scores_are_calibrated_probabilities'])

    def test_backend_failure_is_unknown_without_stale_content(self):
        reader=self.reader()
        def broken(frame):raise RuntimeError('CONTROLLED_FAILURE')
        reader._infer=broken
        result=reader(self.image,media_sha256=self.media,source_context=self.context())
        self.assertEqual(result['status'],'ANALYSIS_FAILED_UNKNOWN')
        self.assertFalse(result['primary_water_content_candidate'])
        self.assertFalse(result['depicted_exhibition_content_candidate'])

    def test_changed_private_backend_pixels_do_not_mutate_or_label_original(self):
        reader=self.reader()
        def mutate(frame):frame[:]=7;return self.labels.copy()
        reader._infer=mutate;before=self.image.copy()
        result=reader(self.image,media_sha256=self.media)
        self.assertTrue(np.array_equal(self.image,before))
        self.assertEqual(result['status'],'ANALYSIS_FAILED_UNKNOWN')

    def test_remote_or_missing_models_are_rejected_without_download(self):
        for path in ['https://invalid.example/model','/tmp/no-such-water-model']:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.module.LocalPrimaryWaterReader(path,'/tmp/missing.onnx')

    def controlled_ancestor_loader(self,reader_class=None):
        observed=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);parent=root/'original';model=parent/'model'
            mirror=root/'mirror';alternate=mirror/'model'
            model.mkdir(parents=True);alternate.mkdir(parents=True)
            contents={name:b'PINNED-'+name.encode() for name in self.module.MODEL_FILES}
            for name,value in contents.items():
                (model/name).write_bytes(value);(alternate/name).write_bytes(value)
            (alternate/'config.json').write_bytes(b'UNPINNED-CONFIG')
            pins={name:sha256(value).hexdigest() for name,value in contents.items()}
            def processor_loader(directory,**kwargs):
                parked=root/'original-parked'
                parent.rename(parked);parent.symlink_to(mirror,target_is_directory=True)
                try:observed.append((Path(directory)/'config.json').read_bytes())
                finally:parent.unlink();parked.rename(parent)
                return object()
            class Model:
                def to(self,*args):return self
                def eval(self):return self
            torch=SimpleNamespace(set_num_threads=lambda value:None)
            transformers=SimpleNamespace(
                SegformerImageProcessor=SimpleNamespace(from_pretrained=processor_loader),
                UperNetForSemanticSegmentation=SimpleNamespace(from_pretrained=lambda *a,**kw:Model()))
            boat=SimpleNamespace(metadata=lambda:{'controlled_test_backend':True})
            with patch.dict(sys.modules,{'torch':torch,'transformers':transformers}),\
                 patch.dict(self.module.MODEL_FILES,pins,clear=True),\
                 patch.object(self.module,'PinnedBoatDetector',return_value=boat):
                reader=(reader_class or self.module.LocalPrimaryWaterReader)(model,'controlled-unused.onnx')
            return observed,contents,reader

    def test_model_loader_cannot_follow_temporarily_replaced_ancestor(self):
        """The actual bytes read by the backend must be the pinned directory."""
        observed,contents,reader=self.controlled_ancestor_loader()
        self.assertEqual(observed,[contents['config.json']])
        self.assertTrue(reader.metadata()['local_files_only'])

    def test_owning_model_reader_cannot_copy_or_pickle_its_descriptor(self):
        reader=object.__new__(self.module.LocalPrimaryWaterReader)
        reader._directory_fd=os.open('/dev/null',os.O_RDONLY)
        try:
            for clone in (copy,deepcopy,pickle.dumps):
                with self.subTest(cloner=clone.__name__):
                    result=None
                    try:
                        with self.assertRaises(TypeError):result=clone(reader)
                    finally:
                        if isinstance(result,self.module.LocalPrimaryWaterReader):result._directory_fd=None
        finally:reader.__del__()

    def test_constructor_failure_before_descriptor_handoff_has_one_owner(self):
        retained=[]
        class AllocationFailure(self.module.LocalPrimaryWaterReader):
            def __new__(cls,*args,**kwargs):
                result=super().__new__(cls);retained.append(result);return result
            def __setattr__(self,name,value):
                if name=='_directory_pin':raise MemoryError('CONTROLLED_ATTRIBUTE_ALLOCATION_FAILURE')
                super().__setattr__(name,value)
        with self.assertRaises(MemoryError):self.controlled_ancestor_loader(AllocationFailure)
        self.assertIsNone(getattr(retained[0],'_directory_fd',None))

    def test_exceeded_analysis_deadline_rejects_result_honestly(self):
        reader=self.reader();reader._processing_timeout_seconds=.1
        with patch.object(self.module.time,'monotonic',side_effect=[0.,1.]):
            result=reader(self.image,media_sha256=self.media)
        self.assertEqual(result['status'],'ANALYSIS_FAILED_UNKNOWN')
        self.assertFalse(result['primary_water_content_candidate'])

    def test_wrong_native_label_shape_cannot_label_original_frame(self):
        reader=self.reader();reader._infer=lambda frame:self.labels[:50,:50].copy()
        result=reader(self.image,media_sha256=self.media)
        self.assertEqual(result['status'],'ANALYSIS_FAILED_UNKNOWN')

    def test_asset_changed_and_restored_during_inference_is_rejected(self):
        reader=self.reader()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'controlled-model';path.write_bytes(b'ORIGINAL')
            reader._asset_paths={'controlled':path};reader._asset_pins={'controlled':self.module._identity(path)}
            def changed(frame):
                path.write_bytes(b'CHANGED');path.write_bytes(b'ORIGINAL')
                return self.labels.copy()
            reader._infer=changed
            result=reader(self.image,media_sha256=self.media)
            self.assertEqual(path.read_bytes(),b'ORIGINAL')
            self.assertEqual(result['status'],'ANALYSIS_FAILED_UNKNOWN')

    def test_retained_inference_array_cannot_be_rewritten_by_other_backend(self):
        reader=self.reader();retained=[]
        def infer(frame):
            retained.append(frame)
            return frame[:,:,0]
        def boats(frame):
            retained[0][:,:,0]=21
            return []
        reader._infer=infer;reader._boat=boats
        result=reader(self.image,media_sha256=self.media)
        self.assertFalse(result['primary_water_content_candidate'])

    def test_public_geometry_uses_private_consistent_native_map(self):
        self.labels[:]=0;original=self.labels.copy();unique=np.unique
        def transient(value,*args,**kwargs):
            self.labels[:]=21
            try:return unique(value,*args,**kwargs)
            finally:self.labels[:]=original
        with patch.object(np,'unique',side_effect=transient):result=self.measure()
        self.assertEqual(result['full_native_class_histogram'],{'0':10000})
        self.assertEqual(result['water_fraction'],0.)

    def test_nonfinite_model_logits_cannot_become_water_argmax(self):
        class Tensor:
            def __init__(self,array):self.array=array;self.ndim=array.ndim;self.shape=array.shape
            def is_floating_point(self):return self.array.dtype.kind=='f'
            def all(self):return self.array.all()
            def argmax(self,axis):return Tensor(self.array.argmax(axis))
            def __getitem__(self,key):return Tensor(self.array[key])
            def cpu(self):return self
            def numpy(self):return self.array
        reader=self.reader();logits=np.zeros((1,150,2,2),np.float32);logits[:,21]=np.nan
        reader._processor=lambda **kw:{};reader._model=lambda **kw:SimpleNamespace(logits=Tensor(logits))
        reader._torch=SimpleNamespace(inference_mode=nullcontext,isfinite=lambda value:Tensor(np.isfinite(value.array)),
            nn=SimpleNamespace(functional=SimpleNamespace(interpolate=lambda value,**kw:value)))
        with self.assertRaises(ValueError):self.module.LocalPrimaryWaterReader._infer(reader,self.image)

    def shore_boat(self,label=76):
        self.labels[:]=0;self.labels[75:,:]=21;self.labels[65:80,45:55]=label
        self.boats=[dict(box=[45,65,10,15],score=.8)]

    def test_border_connected_current_boat_is_separate_from_water_majority(self):
        self.shore_boat();out=self.measure()
        self.assertFalse(out['primary_water_content_candidate'])
        self.assertTrue(out['border_connected_boat_content_candidate'])
        self.assertTrue(out['primary_aquatic_content_candidate'])
        self.assertFalse(out['depicted_exhibition_content_candidate'])
        self.assertFalse(out['verified_boat_movement'])
        evidence=out['border_connected_boat_evidence'][0]
        self.assertEqual(evidence['center_ADE_class_id'],76)
        self.assertEqual(evidence['component_borders'],['bottom','left','right'])
        self.assertGreater(evidence['component_native_water_class_pixels'],0)

    def test_shore_boat_topic_is_conditional_without_phase_or_identity_authentication(self):
        self.shore_boat();out=self.measure(self.context())
        self.assertTrue(out['depicted_exhibition_content_candidate'])
        self.assertEqual(out['specific_phase'],'UNKNOWN')
        self.assertFalse(out['authenticated_current_exhibition'])
        self.assertFalse(out['usable_for_identity'])

    def test_boat_pixels_without_connected_natural_water_are_not_aquatic(self):
        self.labels[:]=76;self.boats=[dict(box=[40,40,20,20],score=.8)]
        out=self.measure()
        self.assertFalse(out['border_connected_boat_content_candidate'])
        self.assertFalse(out['primary_aquatic_content_candidate'])

    def test_interor_boat_inset_does_not_touch_image_borders(self):
        self.labels[:]=0;self.labels[25:75,25:75]=21;self.labels[45:55,45:55]=76
        self.boats=[dict(box=[45,45,10,10],score=.8)];out=self.measure()
        self.assertFalse(out['border_connected_boat_content_candidate'])
        self.assertEqual(out['border_connected_boat_evidence'][0]['component_borders'],[])

    def test_corner_inset_limitation_is_explicit_and_does_not_claim_authentication(self):
        self.labels[:]=0;self.labels[:50,50:]=21;self.labels[20:30,70:80]=76
        self.boats=[dict(box=[70,20,10,10],score=.8)];out=self.measure()
        self.assertTrue(out['border_connected_boat_content_candidate'])
        self.assertTrue(out['primary_aquatic_content_candidate'])
        self.assertIn('ADJACENT_BORDERS_ONLY_CANNOT_EXCLUDE_CORNER_INSET',out['composition_ambiguity_flags'])
        self.assertFalse(out['authenticated_current_exhibition'])
        self.assertFalse(out['production_eligible'])

    def test_proposal_center_must_be_semantic_boat_or_ship_not_only_water(self):
        self.boats=[dict(box=[40,40,20,20],score=.8)]
        self.assertFalse(self.measure()['border_connected_boat_content_candidate'])
        self.shore_boat(label=103)
        self.assertTrue(self.measure()['border_connected_boat_content_candidate'])


if __name__=='__main__':unittest.main()
