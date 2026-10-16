import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from race_ai.core import SourceError

def heads():
 c=[np.zeros((1,n,80),dtype=np.float32) for n in (2704,676,169)]
 b=[np.zeros((1,n,32),dtype=np.float32) for n in (2704,676,169)]
 c[0][0,26*52+26,8]=.95
 return c+b

class BoatRegionTests(unittest.TestCase):
 def module(self):
  try:from race_ai import local_boat_regions as m
  except ImportError:self.fail('offline boat region detector is not implemented')
  return m
 def test_real_pinned_model_runs_locally_on_synthetic_pixels(self):
  m=self.module();d=m.LocalBoatRegions();a=np.zeros((208,416,3),dtype=np.uint8)
  with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
   result=d(a)
  self.assertEqual(result['regions'],[])
  self.assertFalse(result['prediction_eligible']);self.assertEqual(result['boat_identity'],'UNVERIFIED')
 def test_model_hash_is_checked_before_engine_creation(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as folder,patch('cv2.dnn.readNetFromONNX') as read:
   f=Path(folder)/'wrong.onnx';f.write_bytes(b'wrong')
   with self.assertRaises(SourceError):m.LocalBoatRegions(model_path=f)
   read.assert_not_called()
 def test_verified_model_is_loaded_from_memory_without_native_path_io(self):
  m=self.module()
  with patch('cv2.dnn.readNet',side_effect=AssertionError('native file path forbidden')):
   self.assertIsNotNone(m.LocalBoatRegions().net)
 def test_untrusted_image_inputs_and_oversize_arrays_are_rejected(self):
  d=self.module().LocalBoatRegions()
  for a in ('file.png',b'pixels',np.zeros((0,1,3),np.uint8),np.zeros((2,2),np.uint8),np.zeros((2,2,3),float),np.zeros((721,1280,3),np.uint8)):
   with self.subTest(kind=type(a)),self.assertRaises(SourceError):d(a)
 def test_head_order_is_shape_paired_and_letterbox_mapping_is_exact(self):
  m=self.module();h=heads()
  a=m.decode_regions(h,width=416,height=208)
  b=m.decode_regions([h[5],h[1],h[3],h[2],h[0],h[4]],width=416,height=208)
  self.assertEqual(a,b);r=a['regions'][0]
  self.assertEqual(r['box'],[183.5,79.5,56.0,56.0]);self.assertAlmostEqual(r['confidence'],.95,6)
  self.assertFalse(a['prediction_eligible'])
 def test_other_highest_class_and_overlay_regions_are_not_boats(self):
  m=self.module();h=heads();h[0][0,26*52+26,0]=.99
  self.assertEqual(m.decode_regions(h,width=416,height=208)['regions'],[])
  h=heads()
  self.assertEqual(m.decode_regions(h,width=416,height=208,exclusions=[[180,75,65,65]])['regions'],[])
 def test_head_dimensions_duplicates_nonfinite_and_probability_bounds_fail(self):
  m=self.module()
  bad=[heads()[:-1],heads()+[heads()[0]],heads()]
  bad[2][0][0,0,0]=np.nan
  x=heads();x[3][0,0,0]=np.inf;bad.append(x)
  x=heads();x[0][0,0,0]=1.1;bad.append(x)
  x=heads();x[0]=x[0].astype(np.float64);bad.append(x)
  for x in bad:
   with self.subTest(shapes=[a.shape for a in x]),self.assertRaises(SourceError):m.decode_regions(x,width=416,height=208)
 def test_region_observer_maps_cropped_ocr_without_modifying_source(self):
  m=self.module();seen=[]
  def detector(a):return {'regions':[{'box':[10.,20.,30.,20.],'confidence':.9}],'prediction_eligible':False,'boat_identity':'UNVERIFIED'}
  def ocr(a):
   seen.append(a.shape);a[:]=0
   return [{'text':'3','score':.99,'box':[[2,2],[10,2],[10,10],[2,10]]}]
  observe=m.BoatRegionOCR(detector=detector,ocr=ocr)
  pixels=np.full((100,100,3),255,np.uint8);rows=observe(pixels)
  self.assertEqual(seen,[(40,60,3)]);self.assertTrue(np.all(pixels==255))
  self.assertEqual(rows,[{'text':'3','score':.99,'box':[[11.,21.],[15.,21.],[15.,25.],[11.,25.]]}])
  report=observe.last_observation;report['regions'].clear()
  self.assertEqual(len(observe.last_observation['regions']),1)
 def test_region_observer_rejects_bad_regions_and_ocr_rows(self):
  m=self.module();p=np.zeros((100,100,3),np.uint8)
  for region in ({'box':[-1.,0.,20.,20.],'confidence':.9},{'box':[0.,0.,0.,20.],'confidence':.9},{'box':[0.,0.,20.,20.],'confidence':float('nan')}):
   with self.subTest(region=region),self.assertRaises(SourceError):
    m.BoatRegionOCR(detector=lambda a:{'regions':[region]},ocr=lambda a:[])(p)
  with self.assertRaises(SourceError):
   m.BoatRegionOCR(detector=lambda a:{'regions':[{'box':[0.,0.,20.,20.],'confidence':.9}]},ocr=lambda a:[{'text':'1','score':1,'box':[[0,0],[99,0],[99,2],[0,2]]}])(p)
 def test_ocr_cannot_extend_detector_regions_after_validation(self):
  m=self.module();regions=[{'box':[10.,10.,20.,20.],'confidence':.9}];calls=[]
  def ocr(a):
   calls.append(a.shape)
   if len(regions)<13:regions.append({'box':[10.,10.,20.,20.],'confidence':.9})
   return []
  m.BoatRegionOCR(detector=lambda a:{'regions':regions},ocr=ocr)(np.zeros((100,100,3),np.uint8))
  self.assertEqual(len(calls),1)
 def test_ocr_cannot_rewrite_already_cropped_detector_evidence(self):
  m=self.module();regions=[{'box':[10.,10.,20.,20.],'confidence':.9}]
  def ocr(a):regions[0].update(box=[0.,0.,1.,1.],confidence=.5);return []
  observer=m.BoatRegionOCR(detector=lambda a:{'regions':regions},ocr=ocr)
  observer(np.zeros((100,100,3),np.uint8))
  self.assertEqual(observer.last_observation['regions'][0]['box'],[10.,10.,20.,20.])
  self.assertEqual(observer.last_observation['regions'][0]['confidence'],.9)
 def test_untrusted_callback_and_numeric_errors_are_sanitized(self):
  m=self.module();pixels=np.zeros((100,100,3),np.uint8)
  def error(a):raise RuntimeError('SYNTHETIC_SECRET_PATH')
  good=lambda a:{'regions':[{'box':[10.,10.,20.,20.],'confidence':.9}]}
  observers=[m.BoatRegionOCR(detector=error,ocr=lambda a:[]),m.BoatRegionOCR(detector=good,ocr=error),m.BoatRegionOCR(detector=lambda a:{'regions':[{'box':[10.,10.,20.,20.],'confidence':10**1000}]},ocr=lambda a:[])]
  for observer in observers:
   with self.subTest(observer=observer):
    with self.assertRaises(SourceError) as caught:observer(pixels)
    self.assertNotIn('SYNTHETIC_SECRET_PATH',str(caught.exception));self.assertIsNone(observer.last_observation)
 def test_model_io_errors_are_sanitized(self):
  m=self.module()
  with patch('pathlib.Path.read_bytes',side_effect=OSError('SYNTHETIC_SECRET_PATH')):
   with self.assertRaises(SourceError) as caught:m.LocalBoatRegions()
   self.assertNotIn('SYNTHETIC_SECRET_PATH',str(caught.exception))
 def test_region_number_count_distinguishes_crop_hits_from_filtered_output(self):
  m=self.module()
  observer=m.BoatRegionOCR(detector=lambda a:{'regions':[{'box':[10.25,20.25,20.,20.],'confidence':.9}]},ocr=lambda a:[{'text':'1','score':.99,'box':[[0,0],[2,0],[2,2],[0,2]]}])
  self.assertEqual(observer(np.zeros((100,100,3),np.uint8)),[])
  self.assertEqual(observer.last_observation['regions'][0]['number_candidates'],0)
  self.assertEqual(observer.last_observation['regions'][0]['crop_candidates_before_roi_filter'],1)

if __name__=='__main__':unittest.main()
