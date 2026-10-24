import tempfile
import unittest
from unittest.mock import patch

from race_ai.core import SourceError


class LocalOCRTests(unittest.TestCase):
    def module(self):
        try:
            import race_ai.local_number_ocr as module
        except ModuleNotFoundError:
            self.fail('offline number OCR adapter is missing')
        return module

    def test_absent_models_cannot_trigger_a_download(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(SourceError,'LOCAL_OCR_MODEL_UNAVAILABLE'):
                self.module().LocalNumberOCR(model_dir=folder)

    def test_pinned_models_run_real_ocr_without_network_and_reject_nonpixels(self):
        import cv2
        import numpy as np
        with patch('requests.get',side_effect=AssertionError('network')):
            reader=self.module().LocalNumberOCR()
            pixels=np.full((120,240,3),255,dtype=np.uint8)
            cv2.putText(pixels,'3',(90,90),cv2.FONT_HERSHEY_SIMPLEX,2.5,(0,0,0),5)
            result=reader(pixels)
        self.assertTrue(any(row['text']=='3' and row['score']>.9 for row in result))
        self.assertEqual(len(reader.model_sha256),3)
        for bad in ('https://example.invalid/frame.jpg', b'original pixels', np.zeros((100,100))):
            with self.subTest(bad=type(bad)),self.assertRaises(SourceError): reader(bad)


if __name__=='__main__':unittest.main()
