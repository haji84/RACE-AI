"""Synthetic media only: scope, standard HLS, actual decode and honest quality gates."""
from copy import deepcopy
from datetime import datetime, timedelta
import io
import json
import os
import unittest
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.exhibition_video_source import SourceResponse
from tests.test_exhibition_video_source import run, program, MEDIA, SOURCE, NOW


def master():
    return ('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480\n'
            f'https://variants.streaks.jp/v5/cp-boatrace-prod/{MEDIA}/{SOURCE}/manifest_2.m3u8?vt=SYNTHETIC_CHILD\n')


def child(encrypted=False):
    key = (f'#EXT-X-KEY:METHOD=AES-128,URI="https://key.streaks.jp/{MEDIA}/{SOURCE}/'
           '11111111-2222-3333-4444-555555555555",IV=0x00000000000000000000000000000001,KEYFORMATVERSIONS="1"\n') if encrypted else ''
    return ('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-TARGETDURATION:2\n'
            '#EXT-X-MEDIA-SEQUENCE:17\n' + key + '#EXTINF:2.0,\n'
            f'https://live-cp-boatrace-prod.streaks.jp/{MEDIA}/{SOURCE}/manifest_2_17.ts\n#EXT-X-ENDLIST\n')


def synthetic_ts():
    import av
    import numpy as np
    target = io.BytesIO()
    with av.open(target, mode='w', format='mpegts') as output:
        stream = output.add_stream('mpeg2video', rate=12)
        stream.width, stream.height, stream.pix_fmt = 160, 96, 'yuv420p'
        for n in range(24):
            pixels = np.zeros((96, 160, 3), dtype=np.uint8)
            pixels[:] = [40, 60, 60]
            pixels[40:52, 20+n:44+n] = [255, 0, 0]
            frame = av.VideoFrame.from_ndarray(pixels, format='rgb24')
            for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(): output.mux(packet)
    return target.getvalue()


class VideoDecodeTests(unittest.TestCase):
    def runtime(self):
        try:
            import av
        except (ImportError, OSError):
            if os.environ.get('RACE_AI_REQUIRE_VIDEO_RUNTIME') == '1':
                self.fail('required video runtime unavailable')
            self.skipTest('PyAV unavailable; local Windows Code Integrity blocks stream.pyd')

    def module(self):
        try:
            import race_ai.exhibition_video_decode as decode
        except ModuleNotFoundError:
            self.fail('bounded transient video decoder is not implemented')
        return decode

    def test_low_variant_validated_and_private_uri_repr_redacted(self):
        decoder = self.module()
        value = decoder.select_variant(master().encode(), MEDIA, SOURCE)
        self.assertEqual((value.width, value.height, value.number), (854, 480, 2))
        self.assertNotIn('SYNTHETIC_CHILD', repr(value))
        self.assertNotIn('https:', repr(value))

    def test_bad_variant_never_reaches_fetch(self):
        decoder = self.module()
        for bad in [master().replace('variants.streaks.jp', '127.0.0.1'),
                    master().replace(SOURCE, 'c'*32), master().replace('?vt=', '?vt=x&vt='),
                    master().replace('https:', 'http:'), master().replace('854x480', '8000x8000'),
                    master().replace('manifest_2', '../manifest_2'), master().replace('SYNTHETIC_CHILD', 'x%0a')]:
            with self.subTest(bad=bad), self.assertRaises(SourceError):
                decoder.select_variant(bad.encode(), MEDIA, SOURCE)

    def test_vod_requires_complete_bound_segments_and_identity_keys(self):
        decoder = self.module()
        variant = decoder.select_variant(master().encode(), MEDIA, SOURCE)
        segments = decoder.parse_vod(child(True).encode(), MEDIA, SOURCE, variant)
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0].sequence, segments[0].duration), (17, 2.0))
        self.assertEqual(len(segments[0].iv), 16)
        self.assertNotIn('https:', repr(segments[0]))
        bads = [child().replace('#EXT-X-ENDLIST', ''), child().replace('2.0,', 'nan,'),
                child().replace(SOURCE, 'c'*32), child().replace('manifest_2_17', 'manifest_2_18'),
                child().replace('.ts', '.ts?credential=SECRET'), child(True).replace('AES-128', 'SAMPLE-AES'),
                child(True).replace('key.streaks.jp', 'evil.example'),
                child(True).replace('KEYFORMATVERSIONS="1"', 'KEYFORMAT="com.widevine",KEYFORMATVERSIONS="1"'),
                child().replace('#EXTINF', '#EXT-X-BYTERANGE:10@0\n#EXTINF')]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(SourceError):
                decoder.parse_vod(bad.encode(), MEDIA, SOURCE, variant)

    def test_actual_synthetic_ts_decode_tracks_color_but_never_assigns_boats(self):
        self.runtime()
        decoder = self.module()
        descriptor, lease = run()
        calls = []
        raw = synthetic_ts()
        def fetch(url, **kwargs):
            calls.append(url)
            body, mime = (master().encode(), 'application/vnd.apple.mpegurl') if 'manifest.streaks.jp/' in url else (
                (child().encode(), 'application/x-mpegURL') if 'variants.streaks.jp/' in url else (raw, 'video/mp2t'))
            return SourceResponse(200, url, mime, body)
        result = decoder.analyze_exhibition(descriptor, lease, program(), fetch=fetch,
                  clock=lambda: datetime.fromisoformat(NOW), sample_interval=.5)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['segments_decoded'], 1)
        self.assertGreaterEqual(result['frames_decoded'], 23)
        self.assertGreaterEqual(result['frames_sampled'], 3)
        self.assertEqual(result['coverage'], 'COMPLETE_PLAYLIST')
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['boat_features'], [])
        tracks = [t for t in result['candidate_tracks'] if t['color'] == 'red' and t['samples'] >= 3]
        self.assertTrue(tracks)
        self.assertGreater(tracks[0]['dx_pixels'], 10)
        self.assertEqual(result['metric_units'], 'CAMERA_UNCORRECTED_PIXELS_NOT_BOAT_PERFORMANCE')
        self.assertNotIn('SYNTHETIC', json.dumps(result))
        self.assertNotIn('https:', json.dumps(result))
        with self.assertRaises(SourceError): lease.consume(lambda url: None)

    def test_standard_identity_aes_decode_and_secret_error_redaction(self):
        self.runtime()
        decoder = self.module()
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        raw = synthetic_ts(); key = b'0123456789abcdef'
        padding = PKCS7(128).padder(); padded = padding.update(raw) + padding.finalize()
        encrypt = Cipher(algorithms.AES(key), modes.CBC(bytes.fromhex('00'*15+'01'))).encryptor()
        encrypted = encrypt.update(padded) + encrypt.finalize()
        descriptor, lease = run(); calls=[]
        def fetch(url, **kwargs):
            calls.append(url)
            if 'manifest.streaks.jp/' in url: body,mime=master().encode(),'application/x-mpegURL'
            elif 'variants.streaks.jp/' in url: body,mime=child(True).encode(),'application/x-mpegURL'
            elif 'key.streaks.jp/' in url: body,mime=key,'application/octet-stream'
            else: body,mime=encrypted,'video/mp2t'
            return SourceResponse(200,url,mime,body)
        result=decoder.analyze_exhibition(descriptor,lease,program(),fetch=fetch,clock=lambda:datetime.fromisoformat(NOW))
        self.assertEqual(len(calls),4)
        self.assertEqual(result['encryption'],'STANDARD_IDENTITY_AES_128')
        self.assertGreater(result['frames_decoded'],0)
        self.assertNotIn(key.decode(),json.dumps(result))
        descriptor,lease=run()
        def fail(url,**kwargs): raise RuntimeError('secret='+url)
        with self.assertRaisesRegex(SourceError,'^VIDEO_TRANSIENT_PROCESSOR_FAILED$'):
            decoder.analyze_exhibition(descriptor,lease,program(),fetch=fail,clock=lambda:datetime.fromisoformat(NOW))

    def test_wrong_descriptor_and_post_close_capture_cannot_be_prediction_inputs(self):
        decoder=self.module();descriptor,lease=run()
        descriptor=deepcopy(descriptor);descriptor['race_id']='20261015-14-06'
        calls=[]
        with self.assertRaises(SourceError):
            decoder.analyze_exhibition(descriptor,lease,program(),fetch=lambda *a,**kw:calls.append(a),clock=lambda:datetime.fromisoformat(NOW))
        self.assertFalse(calls)

    def test_missing_runtime_fails_before_any_media_get(self):
        decoder=self.module();descriptor,lease=run();calls=[]
        with patch.dict('sys.modules', {'av': None}), self.assertRaisesRegex(SourceError,'VIDEO_DECODE_RUNTIME_UNAVAILABLE'):
            decoder.analyze_exhibition(descriptor,lease,program(),fetch=lambda *a,**kw:calls.append(a),clock=lambda:datetime.fromisoformat(NOW))
        self.assertFalse(calls)

    def test_final_frame_analysis_over_time_budget_is_rejected(self):
        self.runtime();decoder=self.module();descriptor,lease=run();elapsed=[0.0]
        import av
        import numpy as np
        class Frame:
            width=160;height=96;time=0.0
            def to_ndarray(self,**kwargs):return np.zeros((96,160,3),dtype=np.uint8)
        class Container:
            streams=type('Streams',(),{'video':[1]})()
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def decode(self,**kwargs):return [Frame()]
        raw=b'synthetic'
        def fetch(url,**kwargs):
            body,mime=(master().encode(),'application/x-mpegURL') if 'manifest.streaks.jp/' in url else ((child().encode(),'application/x-mpegURL') if 'variants.streaks.jp/' in url else (raw,'video/mp2t'))
            return SourceResponse(200,url,mime,body)
        def expensive(frame):elapsed[0]=2.0;return []
        with patch.object(av,'open',return_value=Container()),patch.object(decoder.time,'monotonic',side_effect=lambda:elapsed[0]),patch.object(decoder,'_candidates',side_effect=expensive),self.assertRaises(SourceError):
            decoder.analyze_exhibition(descriptor,lease,program(),fetch=fetch,clock=lambda:datetime.fromisoformat(NOW),elapsed_limit=1)

    def test_one_empty_segment_cannot_be_counted_as_complete_decode(self):
        self.runtime();decoder=self.module();descriptor,lease=run()
        import numpy as np
        class Frame:
            width=160;height=96;time=0.0
            def to_ndarray(self,**kwargs):return np.zeros((96,160,3),dtype=np.uint8)
        class Container:
            def __init__(self,frames):self.frames=frames;self.streams=type('Streams',(),{'video':[1]})()
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def decode(self,**kwargs):return self.frames
        vod=child().replace('#EXT-X-ENDLIST',f'#EXTINF:2.0,\nhttps://live-cp-boatrace-prod.streaks.jp/{MEDIA}/{SOURCE}/manifest_2_18.ts\n#EXT-X-ENDLIST')
        def fetch(url,**kwargs):
            body,mime=(master().encode(),'application/x-mpegURL') if 'manifest.streaks.jp/' in url else ((vod.encode(),'application/x-mpegURL') if 'variants.streaks.jp/' in url else (b'fake','video/mp2t'))
            return SourceResponse(200,url,mime,body)
        with patch.object(decoder.__dict__.get('av',__import__('av')),'open',side_effect=[Container([Frame()]),Container([])]),self.assertRaises(SourceError):
            decoder.analyze_exhibition(descriptor,lease,program(),fetch=fetch,clock=lambda:datetime.fromisoformat(NOW))


if __name__=='__main__': unittest.main()
