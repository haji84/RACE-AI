"""Controlled feature/pinning tests; no private trained asset is required."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    verifier = importlib.import_module('race_ai.boat_video_marker_verifier')
except ModuleNotFoundError:
    verifier = None

CV = importlib.util.find_spec('cv2') is not None and importlib.util.find_spec('numpy') is not None


class MarkerVerifierAssetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(verifier, 'optional development marker verifier is missing')

    def test_explicit_true_opt_in_is_required_before_reading_assets(self):
        for opt_in in (False, None, 1, 'true'):
            with self.subTest(opt_in=opt_in), mock.patch.object(verifier, '_verified_bytes', side_effect=AssertionError('must not read')):
                with self.assertRaises(ValueError):
                    verifier.PinnedDevelopmentMarkerVerifier(context_model_path='missing', glyph_model_path='missing', development_opt_in=opt_in)
        with self.assertRaises(ValueError):
            verifier.PinnedDevelopmentMarkerVerifier(context_model_path='missing', glyph_model_path='missing')

    def test_fixed_asset_bytes_and_hashes_match_declared_development_models(self):
        self.assertEqual(verifier.CONTEXT_MODEL_BYTES, 10395288)
        self.assertEqual(verifier.CONTEXT_MODEL_SHA256, 'c60df21c802422ec35930f50d5fc60ed27808e4ed1073436c6007399eeafd6d4')
        self.assertEqual(verifier.GLYPH_MODEL_BYTES, 7715667)
        self.assertEqual(verifier.GLYPH_MODEL_SHA256, '4f8f9e9435bf92157b7b77524ec90106dbb18663bad0aa15e03422ac158e2fca')

    def test_wrong_or_remote_assets_fail_before_optional_cv_runtime(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(verifier, '_cv', side_effect=AssertionError('must not load runtime')):
            path = Path(folder) / 'wrong.xml'; path.write_bytes(b'wrong')
            for asset in (path, 'https://example.invalid/model.xml', Path(folder) / 'missing', Path(folder)):
                with self.subTest(asset=str(asset)), self.assertRaises(ValueError):
                    verifier.PinnedDevelopmentMarkerVerifier(context_model_path=asset, glyph_model_path=asset, development_opt_in=True)

    def test_verified_bytes_rejects_wrong_hash_size_and_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'asset'; path.write_bytes(b'payload')
            self.assertEqual(verifier._verified_bytes(path, size=7, digest=sha256(b'payload').hexdigest()), b'payload')
            for size, digest in ((6, sha256(b'payload').hexdigest()), (8, sha256(b'payload').hexdigest()), (7, '0'*64)):
                with self.subTest(size=size), self.assertRaises(ValueError):
                    verifier._verified_bytes(path, size=size, digest=digest)
            link = Path(folder) / 'link'; link.symlink_to(path)
            with self.assertRaises(ValueError):
                verifier._verified_bytes(link, size=7, digest=sha256(b'payload').hexdigest())


@unittest.skipUnless(CV, 'optional OpenCV/NumPy unavailable')
class MarkerVerifierFeatureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(verifier, 'optional development marker verifier is missing')
        import cv2
        import numpy as np
        self.cv, self.np = cv2, np
        self.frame = np.random.default_rng(83).integers(0, 256, (75, 119, 3), dtype=np.uint8)

    def reference_glyph_feature(self, gray):
        np, cv = self.np, self.cv
        h,w=gray.shape; scale=min(24/w,40/h); nw,nh=max(1,round(w*scale)),max(1,round(h*scale))
        a=cv.resize(gray,(nw,nh),interpolation=cv.INTER_AREA if scale<1 else cv.INTER_LINEAR)
        edge=np.concatenate([gray[0],gray[-1],gray[:,0],gray[:,-1]])
        out=np.full((48,32),float(np.median(edge)),np.uint8)
        out[(48-nh)//2:(48-nh)//2+nh,(32-nw)//2:(32-nw)//2+nw]=a
        lo,hi=np.percentile(out,[2,98]); out=np.clip((out.astype(np.float32)-lo)*255/max(hi-lo,1),0,255).astype(np.uint8)
        hog=cv.HOGDescriptor((32,48),(16,16),(8,8),(8,8),9)
        return np.r_[hog.compute(out).reshape(-1),np.float32(np.clip(np.log(w/h),-3,3))].astype(np.float32)

    def reference_context_feature(self, frame, box):
        x,y,u,v=box;h=v-y;H,W=frame.shape[:2]
        crop=frame[max(0,int(y-.5*h)):min(H,int(v+.5*h)),max(0,int(x-h)):min(W,int(u+h))].copy()
        gray=self.cv.cvtColor(crop,self.cv.COLOR_BGR2GRAY)
        return self.cv.HOGDescriptor((96,64),(16,16),(8,8),(8,8),9).compute(self.cv.resize(gray,(96,64))).reshape(-1)

    def test_glyph_features_are_exact_training_formula_for_contrast_aspect_and_scale(self):
        np=self.np
        patches=[np.zeros((1,1),np.uint8),np.full((40,15),127,np.uint8),np.arange(63,dtype=np.uint8).reshape(7,9),np.random.default_rng(7).integers(0,256,(93,61),dtype=np.uint8),np.tile(np.arange(180,dtype=np.uint8),(2,1))]
        for patch in patches:
            before=patch.copy();patch.setflags(write=False)
            with self.subTest(shape=patch.shape):
                actual=verifier._glyph_feature(patch)
                self.assertEqual(actual.shape,(541,));self.assertEqual(actual.dtype,np.float32)
                np.testing.assert_array_equal(actual,self.reference_glyph_feature(patch))
                np.testing.assert_array_equal(patch,before)

    def test_context_features_match_training_crop_with_odd_height_and_all_edges(self):
        for box in ([30,20,44,35],[0,0,1,1],[110,65,119,75],[0,30,8,47],[40,0,52,9]):
            with self.subTest(box=box):
                actual=verifier._context_feature(self.frame,box)
                self.assertEqual(actual.shape,(2772,));self.assertEqual(actual.dtype,self.np.float32)
                self.np.testing.assert_array_equal(actual,self.reference_context_feature(self.frame,box))

    def small_model(self, path, dim, labels):
        np,cv=self.np,self.cv
        x=np.random.default_rng(dim).normal(size=(len(labels)*3,dim)).astype(np.float32);y=np.repeat(labels,3).astype(np.int32)
        model=cv.ml.SVM_create();model.setType(cv.ml.SVM_C_SVC);model.setKernel(cv.ml.SVM_LINEAR);model.setC(1);self.assertTrue(model.train(x,cv.ml.ROW_SAMPLE,y));model.save(str(path))
        return model,path.read_bytes()

    def loaded_control(self, folder, mutate_paths_after_read=False):
        cp,gp=Path(folder)/'context.xml',Path(folder)/'glyph.xml'
        context,cb=self.small_model(cp,2772,[0,1]);glyph,gb=self.small_model(gp,541,[1,6])
        constants={'CONTEXT_MODEL_BYTES':len(cb),'CONTEXT_MODEL_SHA256':sha256(cb).hexdigest(),'GLYPH_MODEL_BYTES':len(gb),'GLYPH_MODEL_SHA256':sha256(gb).hexdigest()}
        stack=[]
        for key,value in constants.items():
            patch=mock.patch.object(verifier,key,value);patch.start();stack.append(patch)
        original=verifier._verified_bytes
        def verify_then_mutate(path,**kwargs):
            raw=original(path,**kwargs);Path(path).write_bytes(b'replaced after verification');return raw
        try:
            with mock.patch.object(verifier,'_verified_bytes',side_effect=verify_then_mutate if mutate_paths_after_read else original):
                control=verifier.PinnedDevelopmentMarkerVerifier(context_model_path=cp,glyph_model_path=gp,development_opt_in=True)
        finally:
            for patch in reversed(stack):patch.stop()
        return control,context,glyph

    def test_memory_loaded_models_preserve_predictions_after_asset_paths_are_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            control,context,glyph=self.loaded_control(folder,mutate_paths_after_read=True)
            boxes=[[30,20,44,35],[0,0,5,7],[90,60,110,75]];original=deepcopy(boxes);before=self.frame.copy();self.frame.setflags(write=False)
            result=control(self.frame,boxes)
            cx=self.np.asarray([self.reference_context_feature(self.frame,b) for b in boxes],self.np.float32)
            gx=self.np.asarray([self.reference_glyph_feature(self.cv.cvtColor(self.frame[b[1]:b[3],b[0]:b[2]],self.cv.COLOR_BGR2GRAY)) for b in boxes],self.np.float32)
            _,cp=context.predict(cx);_,gp=glyph.predict(gx)
            self.assertEqual(result,[dict(context_class=int(c),glyph_class=int(g)) for c,g in zip(cp.ravel(),gp.ravel())])
            self.assertEqual(boxes,original);self.np.testing.assert_array_equal(self.frame,before)
            meta=control.metadata();self.assertIs(meta.get('development_opt_in'),True);self.assertFalse(meta['field_eligible']);self.assertFalse(meta['model_eligible']);self.assertEqual(meta['training_scope'],'DEVELOPMENT_TRAIN_OVERLAP')
            self.assertIn('CC-BY-SA-4.0',meta['license']);self.assertFalse(meta['calibrated_identification_probability'])

    def test_empty_call_has_empty_ordered_result_and_invalid_boxes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            control,_,_=self.loaded_control(folder)
            self.assertEqual(control(self.frame,[]),[])
            invalid=[None,{},[[0,0,0,4]],[[0,0,120,5]],[[1,3,2,2]],[[True,0,3,4]],[[0.,0,3,4]],[[0,0,3]],[[0,0,3,4],[0,0,200,200]]]
            for boxes in invalid:
                with self.subTest(boxes=boxes),self.assertRaises(ValueError):control(self.frame,boxes)
            for image in (self.frame.astype(self.np.int16),self.frame[:,:,0],self.np.zeros((0,2,3),self.np.uint8)):
                with self.subTest(shape=image.shape),self.assertRaises(ValueError):control(image,[])

    def test_entire_box_list_validated_before_any_model_prediction(self):
        with tempfile.TemporaryDirectory() as folder:
            control,_,_=self.loaded_control(folder)
            class Forbidden:
                def predict(self,rows):raise AssertionError('prediction before whole-call validation')
            control._context_model=control._glyph_model=Forbidden()
            with self.assertRaises(ValueError):control(self.frame,[[0,0,3,4],[0,0,500,4]])

    def test_invalid_model_class_outputs_are_rejected_without_number_claim(self):
        np=self.np
        with tempfile.TemporaryDirectory() as folder:
            control,_,_=self.loaded_control(folder)
            class Output:
                def __init__(self,value):self.value=value
                def predict(self,rows):return 0.,self.value
            good_context=Output(np.array([[1]],np.float32));good_glyph=Output(np.array([[3]],np.float32))
            for bad in (np.array([[2]],np.float32),np.array([[.5]],np.float32),np.array([[np.nan]],np.float32),np.zeros((0,1),np.float32),np.array([[True]],np.bool_),np.array([[1]],np.float64)):
                control._context_model,control._glyph_model=Output(bad),good_glyph
                with self.subTest(bad=bad.tolist()),self.assertRaises(ValueError):control(self.frame,[[1,1,5,8]])
            control._context_model=good_context
            for bad in (np.array([[7]],np.float32),np.array([[-1]],np.float32),np.array([[1.5]],np.float32)):
                control._glyph_model=Output(bad)
                with self.subTest(bad=bad.tolist()),self.assertRaises(ValueError):control(self.frame,[[1,1,5,8]])


if __name__=='__main__':unittest.main()
