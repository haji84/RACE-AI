import unittest
from datetime import datetime
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.exhibition_video_source import SourceResponse
from tests.test_exhibition_video_source import run, program, NOW
from tests.test_exhibition_video_decode import master, child, synthetic_ts
from tests.test_video_number_marks import row


class NumberMarkIntegrationTests(unittest.TestCase):
    def test_in_place_ocr_preprocessing_cannot_corrupt_camera_frames(self):
        from tests.test_exhibition_video_camera_integration import CameraDecodeIntegrationTests
        seen=[]
        def estimate(previous,current,**kwargs):
            seen.append((float(previous.mean()),float(current.mean())))
            return {'accepted':False,'status':'UNVERIFIED_INSUFFICIENT_FEATURES'}
        def ocr(pixels):
            pixels[:]=0
            return [row(x=60,y=40)]
        with patch('race_ai.video_camera_motion.estimate_camera_motion',side_effect=estimate):
            CameraDecodeIntegrationTests().analyze(camera_motion=True,number_mark_ocr=ocr,
                                                  number_mark_exclusions=[])
        self.assertTrue(seen)
        self.assertTrue(all(previous>1 and current>1 for previous,current in seen),seen)

    def test_camera_confirmed_cut_below_thumbnail_threshold_resets_number_track(self):
        from tests.test_exhibition_video_camera_integration import CameraDecodeIntegrationTests
        with patch('race_ai.video_camera_motion.estimate_camera_motion', return_value={
                'accepted':False,'status':'UNVERIFIED_SCENE_CHANGE'}):
            result=CameraDecodeIntegrationTests().analyze(camera_motion=True,
                    number_mark_ocr=lambda pixels:[row(x=60,y=40)],number_mark_exclusions=[])
        self.assertGreater(result['camera_motion']['rejection_counts']['UNVERIFIED_SCENE_CHANGE'],0)
        self.assertEqual(result['candidate_tracks'],[])
        self.assertEqual(result['number_marks']['tracks'],[])
        self.assertTrue(all(r['scene_cut'] for r in result['number_marks']['observations'][1:]))

    def test_opt_in_actual_decode_observes_pixels_and_keeps_forecast_gate_closed(self):
        from race_ai.exhibition_video_decode import analyze_exhibition
        descriptor, lease = run()
        raw = synthetic_ts()
        pixels_seen = []
        def ocr(pixels):
            pixels_seen.append(pixels.shape)
            return [row(x=60+len(pixels_seen), y=40)]
        def fetch(url, **kwargs):
            body,mime = (master().encode(),'application/x-mpegURL') if 'manifest.streaks.jp/' in url else (
                (child().encode(),'application/x-mpegURL') if 'variants.streaks.jp/' in url else (raw,'video/mp2t'))
            return SourceResponse(200,url,mime,body)
        result = analyze_exhibition(descriptor,lease,program(),fetch=fetch,
                    clock=lambda:datetime.fromisoformat(NOW),sample_interval=.5,
                    number_mark_ocr=ocr,number_mark_exclusions=[[0,0,160,20]])
        self.assertGreaterEqual(len(pixels_seen),3)
        self.assertEqual(result['analysis_version'],'transient-hls-number-marks/v5')
        self.assertTrue(result['number_marks']['tracks'])
        self.assertFalse(result['prediction_eligible'])
        self.assertFalse(result['number_marks']['prediction_eligible'])
        self.assertEqual(result['boat_features'],[])
        self.assertEqual(result['boat_identity'],'UNVERIFIED')

    def test_invalid_ocr_contract_stops_before_media(self):
        from race_ai.exhibition_video_decode import analyze_exhibition
        for ocr,masks in ((True,[]),(lambda pixels:[],None),(None,[])):
            descriptor,lease=run();calls=[]
            with self.subTest(ocr=ocr,masks=masks),self.assertRaises(SourceError):
                analyze_exhibition(descriptor,lease,program(),fetch=lambda *a,**k:calls.append(a),
                                   clock=lambda:datetime.fromisoformat(NOW),
                                   number_mark_ocr=ocr,number_mark_exclusions=masks)
            self.assertEqual(calls,[])


if __name__=='__main__': unittest.main()
