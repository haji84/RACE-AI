"""Offline tests. Never fetch a live source during CI discovery."""
import hashlib,unittest
try:
 from scripts import boat_missing_result_capture as capture
except ImportError:
 capture=None

class CaptureTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(capture,'missing bounded official capture module')
 def test_exact_two_requested_results(self):
  self.assertEqual(capture.TARGETS,('20261104-10-10','20261104-19-10'))
  self.assertEqual(capture.result_url(capture.TARGETS[0]),'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=10&jcd=10&hd=20261104')
 def test_no_arbitrary_target_or_host(self):
  for target in ('20261104-19-11','http://localhost','20261105-10-10'):
   with self.assertRaises(ValueError):capture.result_url(target)
 def test_original_bytes_and_sha_are_preserved(self):
  raw=b'<html>official original</html>'
  row=capture.encode_evidence(capture.TARGETS[0],raw,'2026-11-04T15:00:00+00:00')
  import base64
  self.assertEqual(base64.b64decode(row['body_base64']),raw)
  self.assertEqual(row['source_sha256'],hashlib.sha256(raw).hexdigest())
  self.assertFalse(row['parsed_result_verified'])
 def test_empty_and_oversized_pages_rejected(self):
  for raw in (b'',b'x'*(capture.MAX_BYTES+1)):
   with self.assertRaises(ValueError):capture.encode_evidence(capture.TARGETS[0],raw,'2026-11-04T15:00:00+00:00')
 def test_no_forced_success_on_capture_failure(self):
  record=capture.empty_report()
  self.assertFalse(record['all_pages_captured'])
  self.assertFalse(record['predictions_generated'])
  self.assertEqual(record['source_get_limit'],2)
if __name__=='__main__':unittest.main()
