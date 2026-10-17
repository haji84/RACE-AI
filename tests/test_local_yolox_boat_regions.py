import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from race_ai.core import SourceError

def head():
 a=np.zeros((1,8400,85),np.float32)
 a[0,20*80+40,:5]=[.5,.5,math.log(2),math.log(2),.9]
 a[0,20*80+40,5+8]=.9
 return a

class YoloXBoatRegionTests(unittest.TestCase):
 def module(self):
  try:from race_ai import local_yolox_boat_regions as m
  except ImportError:self.fail('separate pinned YOLOX boat region adapter is absent')
  return m
 def test_real_model_blank_inference_is_local_and_unverified(self):
  m=self.module();d=m.LocalYoloXBoatRegions();a=np.zeros((208,416,3),np.uint8)
  with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
   r=d(a)
  self.assertEqual(r['regions'],[]);self.assertFalse(r['prediction_eligible']);self.assertEqual(r['boat_features'],[])
 def test_bad_model_rejected_before_engine_load(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as t,patch('cv2.dnn.readNetFromONNX') as load:
   p=Path(t)/'bad.onnx';p.write_bytes(b'bad')
   with self.assertRaises(SourceError):m.LocalYoloXBoatRegions(model_path=p)
   load.assert_not_called()
 def test_verified_model_loaded_from_bytes_without_native_path(self):
  m=self.module()
  with patch('cv2.dnn.readNet',side_effect=AssertionError('native path forbidden')):
   self.assertIsNotNone(m.LocalYoloXBoatRegions().net)
 def test_exact_anchor_decode_score_and_detached_output(self):
  m=self.module();a=head();old=a.copy();r=m.decode_yolox_regions(a,width=640,height=320)
  np.testing.assert_allclose(r['regions'][0]['box'],[316.,156.,16.,16.],rtol=0,atol=1e-6);self.assertAlmostEqual(r['regions'][0]['confidence'],.81,6)
  np.testing.assert_array_equal(a,old);self.assertEqual(r['boat_identity'],'UNVERIFIED')
 def test_product_score_and_highest_class_are_required(self):
  m=self.module();a=head();a[0,1640,4]=.5
  self.assertEqual(m.decode_yolox_regions(a,width=640,height=320)['regions'],[])
  a=head();a[0,1640,5]=1
  self.assertEqual(m.decode_yolox_regions(a,width=640,height=320)['regions'],[])
 def test_padding_only_detections_dropped(self):
  m=self.module();a=head();a[0,1640,1]=60
  self.assertEqual(m.decode_yolox_regions(a,width=640,height=320)['regions'],[])
 def test_subpixel_and_edge_clipped_regions_do_not_break_crop_observer(self):
  m=self.module()
  for field,value in [(2,math.log(.5/8)),(3,math.log(.5/8)),(0,40.9375)]:
   a=head();a[0,1640,field]=value
   with self.subTest(field=field):self.assertEqual(m.decode_yolox_regions(a,width=640,height=320)['regions'],[])
 def test_integer_resize_mapping_and_exclusions(self):
  m=self.module();a=head();r=m.decode_yolox_regions(a,width=854,height=480)
  x,y,w,h=r['regions'][0]['box'];self.assertAlmostEqual(x,316*854/640);self.assertAlmostEqual(y,156*480/359)
  self.assertAlmostEqual(w,16*854/640);self.assertAlmostEqual(h,16*480/359)
  self.assertEqual(m.decode_yolox_regions(a,width=854,height=480,exclusions=[[x,y,w,h]])['regions'],[])
 def test_invalid_shapes_probabilities_or_nonfinite_heads_rejected(self):
  m=self.module();cases=[np.zeros((1,8401,85),np.float32),head().astype(np.float64)]
  for index,value in [(0,float('nan')),(4,1.1),(13,-.1)]:
   a=head();a[0,0,index]=value;cases.append(a)
  for a in cases:
   with self.subTest(shape=a.shape),self.assertRaises(SourceError):m.decode_yolox_regions(a,width=640,height=320)
 def test_huge_selected_regression_is_rejected_safely(self):
  m=self.module();a=head();a[0,1640,2]=1000
  with self.assertRaises(SourceError):m.decode_yolox_regions(a,width=640,height=320)
 def test_nms_suppresses_duplicate_candidates_and_caps_output(self):
  m=self.module();a=head();a[0,1641]=a[0,1640];a[0,1641,0]=-.5
  self.assertEqual(len(m.decode_yolox_regions(a,width=640,height=320)['regions']),1)
  a=np.zeros((1,8400,85),np.float32)
  for i in range(20):a[0,i*3,:5]=[.5,.5,0,0,.9];a[0,i*3,13]=.9
  self.assertEqual(len(m.decode_yolox_regions(a,width=640,height=640)['regions']),12)
 def test_input_and_runtime_failures_are_sanitized(self):
  m=self.module();d=m.LocalYoloXBoatRegions()
  for a in ['x.png',b'raw',np.zeros((721,1280,3),np.uint8),np.zeros((1,1,3),float)]:
   with self.subTest(kind=type(a)),self.assertRaises(SourceError):d(a)
  with patch.object(d,'net') as net:
   net.forward.side_effect=RuntimeError('SYNTHETIC_SECRET_PATH')
   with self.assertRaises(SourceError) as e:d(np.zeros((20,20,3),np.uint8))
   self.assertNotIn('SECRET',str(e.exception))
 def test_preprocess_preserves_pixels_rgb_order_and_padding(self):
  m=self.module();d=m.LocalYoloXBoatRegions();a=np.full((320,640,3),[10,20,30],np.uint8);old=a.copy()
  with patch.object(d,'net') as net:
   net.forward.return_value=[head()];d(a)
   blob=net.setInput.call_args.args[0]
   self.assertEqual(blob.shape,(1,3,640,640));self.assertEqual(blob[0,:,0,0].tolist(),[30,20,10]);self.assertEqual(blob[0,:,639,639].tolist(),[114,114,114])
  np.testing.assert_array_equal(a,old)
