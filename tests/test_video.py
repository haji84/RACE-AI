import tempfile
import unittest
from pathlib import Path
from race_ai.core import SourceError
from race_ai.video import index_video

class VideoIndexTests(unittest.TestCase):
    def test_rights_gate(self):
        with self.assertRaises(SourceError):
            index_video('not-present.mp4',rights_confirmed=False)
    def test_bad_rate(self):
        with self.assertRaises(SourceError):
            index_video('not-present.mp4',rights_confirmed=True,sample_seconds=0)
    def test_fixture_video_if_opencv_available(self):
        try:
            import cv2, numpy as np
        except ImportError:
            self.skipTest('opencv not installed')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'sample.avi'
            writer=cv2.VideoWriter(str(target),cv2.VideoWriter_fourcc(*'MJPG'),5.0,(64,64))
            if not writer.isOpened():self.skipTest('video encoder unavailable')
            for i in range(10):
                img=np.zeros((64,64,3),dtype=np.uint8);img[:,:,1]=i*10
                writer.write(img)
            writer.release()
            got=index_video(target,rights_confirmed=True,sample_seconds=1.0)
            self.assertEqual(len(got['samples']),2)
            self.assertEqual(got['analysis_status'],'FRAME_INDEX_ONLY_REQUIRES_MANUAL_REVIEW')
            self.assertEqual(got['boat_identity'],'UNKNOWN')

if __name__=='__main__':unittest.main()
