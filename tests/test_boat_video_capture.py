"""Offline HLS acquisition contracts; fixtures are fictional, never official races."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    capture = importlib.import_module('race_ai.boat_video_capture')
except ModuleNotFoundError:
    capture = None


ORIGIN = 'https://media.example'
URL = ORIGIN + '/live.m3u8'


def manifest(url=URL, role='SYNTHETIC_TEST', origins=None):
    return dict(schema='RACE_AI_AUTHORIZED_HLS_SOURCE_V1', source_id='fictional-development',
                playlist_url=url, allowed_origins=origins or [ORIGIN], source_role=role,
                source_evidence_sha256='a' * 64)


def playlist(numbers, *, end=False, extra='', duration=1):
    numbers = list(numbers)
    body = '#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:' + str(numbers[0] if numbers else 0) + '\n'
    body += extra
    body += ''.join(f'#EXTINF:{duration},\ns{n}.m4s\n' for n in numbers)
    return (body + ('#EXT-X-ENDLIST\n' if end else '')).encode()


class Clock:
    def __init__(self):
        self.value = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=3):
        self.value += timedelta(seconds=seconds)


class Transport:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        value = self.routes[url]
        if callable(value):
            return value(url, headers)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, bytes):
            return capture.HTTPResult(200, {}, io.BytesIO(value))
        status, response_headers, raw = value
        return capture.HTTPResult(status, response_headers, io.BytesIO(raw))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(capture, 'continuous HLS collector is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.collectors = []
        self.addCleanup(lambda: [c.close() for c in self.collectors])

    def collector(self, transport, source=None, root=None):
        c = capture.Collector(root or self.root, source or manifest(), fetch=transport, clock=self.clock)
        self.collectors.append(c)
        return c

    def test_37_arriving_segments_continue_and_restart_does_not_get_saved_media(self):
        routes = {URL: playlist([0])}
        routes.update({ORIGIN + f'/s{i}.m4s': f'fictional-{i}'.encode() for i in range(37)})
        transport = Transport(routes)
        c = self.collector(transport)
        self.assertEqual(c.tick()['segments_saved'], 1)
        routes[URL] = playlist(range(1, 37), end=True)
        self.clock.advance()
        done = c.tick()
        self.assertEqual(done['segments_saved'], 37)
        self.assertEqual(done['requests_attempted'], 39)
        self.assertEqual(done['status'], 'ENDED')
        self.assertEqual(len(done['ready_windows']), 2)
        c.close()
        restarted = self.collector(transport)
        before = len(transport.calls)
        self.assertEqual(restarted.tick()['segments_saved'], 37)
        self.assertEqual(len(transport.calls), before)
        self.assertEqual([r['segment_count'] for r in restarted.list_windows()], [30, 7])

    def test_301_media_segments_are_not_stopped_at_old_240_get_limit(self):
        routes = {URL: playlist(range(301), end=True, duration=.1)}
        routes.update({ORIGIN + f'/s{i}.m4s': b'fictional-small-media' for i in range(301)})
        result = self.collector(Transport(routes)).tick()
        self.assertEqual(result['segments_saved'], 301)
        self.assertEqual(result['requests_completed'], 302)
        self.assertIsNone(result['source_wait'])

    def test_crash_during_get_preserves_unknown_attempt_on_restart(self):
        transport = Transport({URL: KeyboardInterrupt()})
        c = self.collector(transport)
        with self.assertRaises(KeyboardInterrupt):
            c.tick()
        c.close()
        transport.routes = {URL: playlist([0], end=True), ORIGIN + '/s0.m4s': b'fictional'}
        result = self.collector(transport).tick()
        self.assertEqual(result['requests_attempted'], 3)
        self.assertEqual(result['requests_completed'], 2)
        self.assertEqual(result['requests_unknown'], 1)

    def test_committed_segment_corruption_is_not_refetched_or_accepted(self):
        transport = Transport({URL: playlist([0]), ORIGIN + '/s0.m4s': b'original'})
        c = self.collector(transport)
        c.tick()
        blob = self.root / 'blobs' / (sha256(b'original').hexdigest() + '.blob')
        blob.write_bytes(b'corrupted')
        self.clock.advance()
        result = c.tick()
        self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
        self.assertEqual(result['segments_saved'], 1)
        self.assertEqual(sum(u.endswith('s0.m4s') for u, _ in transport.calls), 1)

    def test_sliding_gap_closes_window_and_is_recorded_without_bridging(self):
        routes = {URL: playlist([0]), ORIGIN + '/s0.m4s': b'zero', ORIGIN + '/s2.m4s': b'two'}
        c = self.collector(Transport(routes))
        c.tick()
        routes[URL] = playlist([2], end=True)
        self.clock.advance()
        result = c.tick()
        self.assertEqual(result['gaps_recorded'], 1)
        rows = c.list_windows()
        self.assertEqual([r['closure_reason'] for r in rows], ['SLIDING_GAP', 'ENDLIST'])
        self.assertEqual([r['segment_count'] for r in rows], [1, 1])

    def test_map_change_and_discontinuity_create_distinct_windows(self):
        raw = (b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MAP:URI="a.mp4"\n'
               b'#EXTINF:1,\ns0.m4s\n#EXT-X-MAP:URI="b.mp4"\n#EXTINF:1,\ns1.m4s\n'
               b'#EXT-X-DISCONTINUITY\n#EXTINF:1,\ns2.m4s\n#EXT-X-ENDLIST\n')
        routes = {URL: raw, ORIGIN + '/a.mp4': b'initA', ORIGIN + '/b.mp4': b'initB'}
        routes.update({ORIGIN + f'/s{i}.m4s': bytes([i]) for i in range(3)})
        transport = Transport(routes)
        c = self.collector(transport)
        result = c.tick()
        self.assertEqual(len(result['ready_windows']), 3)
        self.assertEqual([r['closure_reason'] for r in c.list_windows()], ['MAP_CHANGE', 'DISCONTINUITY', 'ENDLIST'])
        # An initialization URI is only reusable inside its discontinuity context.
        self.assertEqual(sum(u.endswith('b.mp4') for u, _ in transport.calls), 2)

    def test_whole_playlist_rejects_late_keys_and_unsupported_parts_before_media_get(self):
        for extra in ('#EXT-X-KEY:METHOD=AES-128,URI="key.bin"', '#EXT-X-PART:DURATION=1,URI="part.m4s"',
                      '#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="key.bin"'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as d:
                raw = playlist([0]).decode() + extra + '\n#EXTINF:1,\ns1.m4s\n'
                transport = Transport({URL: raw.encode()})
                result = self.collector(transport, root=Path(d)).tick()
                self.assertEqual(result['segments_saved'], 0)
                self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
                self.assertEqual(len(transport.calls), 1)

    def test_unapproved_segment_origin_is_rejected_before_any_media_request(self):
        raw = b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:1,\nhttps://outside.example/media.ts\n'
        transport = Transport({URL: raw})
        result = self.collector(transport).tick()
        self.assertEqual(result['segments_saved'], 0)
        self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
        self.assertEqual(len(transport.calls), 1)

    def test_unapproved_redirect_is_not_followed(self):
        transport = Transport({URL: (302, {'Location': 'https://outside.example/live.m3u8'}, b'')})
        result = self.collector(transport).tick()
        self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
        self.assertEqual(result['requests_completed'], 1)
        self.assertEqual(len(transport.calls), 1)

    def test_authorization_latch_survives_restart_and_never_changes_variant(self):
        for status in (401, 403):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                transport = Transport({URL: (status, {'Retry-After': '1'}, b'denied')})
                c = self.collector(transport, root=Path(d))
                first = c.tick()
                self.assertEqual(first['source_wait']['state'], 'AUTHORIZATION_WAIT')
                c.close(); self.clock.advance(100000)
                result = self.collector(transport, root=Path(d)).tick()
                self.assertEqual(result['requests_attempted'], 1)
                self.assertIsNone(result['source_wait']['retry_at'])
                self.assertEqual(len(transport.calls), 1)

    def test_rate_limit_retry_after_survives_restart_without_early_get(self):
        transport = Transport({URL: (429, {'Retry-After': '7200'}, b'limited')})
        c = self.collector(transport)
        first = c.tick(); c.close()
        transport.routes = {URL: playlist([0], end=True), ORIGIN + '/s0.m4s': b'fictional'}
        c = self.collector(transport)
        self.clock.advance(7199)
        self.assertEqual(c.tick()['source_wait'], first['source_wait'])
        self.assertEqual(len(transport.calls), 1)
        self.clock.advance(1)
        result = c.tick()
        self.assertEqual(result['segments_saved'], 1)
        self.assertEqual(result['requests_attempted'], 3)

    def test_master_pins_first_variant_and_does_not_fallback_after_denial(self):
        master = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\none/media.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=200\ntwo/media.m3u8\n'
        transport = Transport({URL: master, ORIGIN + '/one/media.m3u8': (403, {}, b'denied')})
        result = self.collector(transport).tick()
        self.assertEqual(result['source_wait']['state'], 'AUTHORIZATION_WAIT')
        self.assertEqual(result['requests_attempted'], 2)
        self.assertEqual([u for u, _ in transport.calls], [URL, ORIGIN + '/one/media.m3u8'])

    def test_master_variant_is_pinned_before_429_including_nested_masters(self):
        for nested in (False,True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as d:
                chosen=ORIGIN+'/one/media.m3u8';other=ORIGIN+'/two/media.m3u8'
                first=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\n'+chosen.encode()+b'\n'
                alternate=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=200\n'+other.encode()+b'\n'
                routes={URL:first,chosen:(429,{'Retry-After':'180'},b'wait')}
                if nested:
                    routes[URL]=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nnested.m3u8\n'
                    routes[ORIGIN+'/nested.m3u8']=first
                transport=Transport(routes);c=self.collector(transport,root=Path(d));c.tick();c.close()
                routes[URL]=alternate;routes[ORIGIN+'/nested.m3u8']=alternate
                routes[chosen]=playlist([0],end=True);routes[ORIGIN+'/one/s0.m4s']=b'original-variant'
                routes[other]=playlist([0],end=True);routes[ORIGIN+'/two/s0.m4s']=b'wrong-variant'
                self.clock.advance(181);c=self.collector(transport,root=Path(d));result=c.tick()
                self.assertEqual(result['segments_saved'],1)
                self.assertEqual(sum(url==URL for url,_ in transport.calls),1)
                self.assertFalse(any(url==other for url,_ in transport.calls))
                self.assertEqual(sum(url==chosen for url,_ in transport.calls),2)

    def test_short_actual_http_response_body_cannot_be_completed_as_full_segment(self):
        class Socket:
            def makefile(self,*args):
                return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc')
        def short(url,headers):
            response=http.client.HTTPResponse(Socket());response.begin()
            return capture.HTTPResult(response.status,response.headers,response)
        result=self.collector(Transport({URL:playlist([0],end=True),ORIGIN+'/s0.m4s':short})).tick()
        self.assertEqual(result['segments_saved'],0)
        self.assertEqual(result['source_wait']['state'],'TRANSIENT_SOURCE_WAIT')

    def test_chunked_incomplete_read_waits_and_retries_only_after_source_delay(self):
        class Socket:
            def makefile(self,*args):
                return io.BytesIO(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nabc')
        def incomplete(url,headers):
            response=http.client.HTTPResponse(Socket());response.begin()
            return capture.HTTPResult(response.status,response.headers,response)
        routes={URL:playlist([0],end=True),ORIGIN+'/s0.m4s':incomplete}
        transport=Transport(routes);c=self.collector(transport);result=c.tick()
        self.assertEqual(result['segments_saved'],0)
        self.assertEqual(result['source_wait']['state'],'TRANSIENT_SOURCE_WAIT')
        self.assertIsNotNone(result['source_wait']['retry_at'])
        c.tick();self.assertEqual(len(transport.calls),2)
        routes[ORIGIN+'/s0.m4s']=b'complete';self.clock.advance(180)
        self.assertEqual(c.tick()['segments_saved'],1)

    def test_sliding_pdt_enrichment_preserves_media_identity_and_legacy_metadata(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy),tempfile.TemporaryDirectory() as d:
                raw=playlist([0,1],extra='#EXT-X-PROGRAM-DATE-TIME:2020-01-01T00:00:00Z\n')
                routes={URL:raw,ORIGIN+'/s0.m4s':b'zero',ORIGIN+'/s1.m4s':b'one',ORIGIN+'/s2.m4s':b'two'}
                transport=Transport(routes);c=self.collector(transport,root=Path(d));c.tick()
                original_metadata=c.db.execute('SELECT metadata FROM segments WHERE sequence=1').fetchone()[0]
                if legacy:
                    old_item={'sequence':1,'discontinuity_sequence':0,'uri':ORIGIN+'/s1.m4s',
                              'byte_range':None,'map':None,'duration_seconds':1.0,'program_date_time':None}
                    old_sha=sha256((json.dumps(old_item,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
                    c.db.execute('UPDATE segments SET fingerprint=? WHERE sequence=1',(old_sha,))
                c.close()
                routes[URL]=playlist([1,2],end=True,extra='#EXT-X-PROGRAM-DATE-TIME:2020-01-01T00:00:01Z\n')
                self.clock.advance();c=self.collector(transport,root=Path(d));result=c.tick()
                self.assertEqual(result['segments_saved'],3)
                self.assertIsNone(result['source_wait'])
                self.assertEqual(sum(u.endswith('s1.m4s') for u,_ in transport.calls),1)
                self.assertEqual(c.db.execute('SELECT metadata FROM segments WHERE sequence=1').fetchone()[0],original_metadata)
                claims=c.db.execute('SELECT claim FROM pdt_claims WHERE sequence=1').fetchall()
                self.assertEqual([r[0] for r in claims],['2020-01-01T00:00:01Z'])

    def test_contradictory_explicit_pdt_is_held_without_new_media_get(self):
        routes={URL:playlist([0],extra='#EXT-X-PROGRAM-DATE-TIME:2020-01-01T00:00:00Z\n'),ORIGIN+'/s0.m4s':b'zero'}
        transport=Transport(routes);c=self.collector(transport);c.tick()
        routes[URL]=playlist([0,1],extra='#EXT-X-PROGRAM-DATE-TIME:2020-01-01T00:00:01Z\n')
        self.clock.advance();result=c.tick()
        self.assertEqual(result['source_wait']['state'],'SOURCE_REVIEW_WAIT')
        self.assertEqual(result['segments_saved'],1)
        self.assertEqual(len(transport.calls),3)

    def test_content_length_is_validated_for_200_and_matches_206_range_length(self):
        for length in ('x','-1','0','1073741825'):
            with self.subTest(length=length),tempfile.TemporaryDirectory() as d:
                result=self.collector(Transport({URL:playlist([0],end=True),
                    ORIGIN+'/s0.m4s':(200,{'Content-Length':length},b'abc')}),root=Path(d)).tick()
                self.assertEqual(result['segments_saved'],0)
                self.assertEqual(result['source_wait']['state'],'SOURCE_REVIEW_WAIT')
        with tempfile.TemporaryDirectory() as d:
            raw=b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-BYTERANGE:2@0\n#EXTINF:1,\nrange.m4s\n'
            result=self.collector(Transport({URL:raw,ORIGIN+'/range.m4s':
                (206,{'Content-Range':'bytes 0-1/10','Content-Length':'3'},b'ab')}),root=Path(d)).tick()
            self.assertEqual(result['segments_saved'],0)
            self.assertEqual(result['source_wait']['state'],'SOURCE_REVIEW_WAIT')

    def test_byte_range_206_and_implicit_offsets_save_exact_bytes(self):
        raw = (b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-BYTERANGE:3@2\n#EXTINF:1,\ncombined.m4s\n'
               b'#EXT-X-BYTERANGE:2\n#EXTINF:1,\ncombined.m4s\n#EXT-X-ENDLIST\n')
        def ranged(url, headers):
            value = {'bytes=2-4': (b'cde', 'bytes 2-4/10'), 'bytes=5-6': (b'fg', 'bytes 5-6/10')}[headers['Range']]
            return capture.HTTPResult(206, {'Content-Range': value[1]}, io.BytesIO(value[0]))
        result = self.collector(Transport({URL: raw, ORIGIN + '/combined.m4s': ranged})).tick()
        self.assertEqual(result['segments_saved'], 2)
        for body in (b'cde', b'fg'):
            self.assertEqual((self.root/'blobs'/(sha256(body).hexdigest()+'.blob')).read_bytes(), body)

    def test_byte_range_full_200_response_cannot_be_admitted(self):
        raw = b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-BYTERANGE:2@0\n#EXTINF:1,\ncombined.m4s\n'
        result = self.collector(Transport({URL: raw, ORIGIN + '/combined.m4s': b'full'})).tick()
        self.assertEqual(result['segments_saved'], 0)
        self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')

    def test_same_sequence_metadata_change_is_held_without_getting_changed_media(self):
        routes = {URL: playlist([0]), ORIGIN + '/s0.m4s': b'zero'}
        transport = Transport(routes); c = self.collector(transport); c.tick()
        routes[URL] = playlist([0]).replace(b's0.m4s', b'changed.m4s')
        self.clock.advance()
        result = c.tick()
        self.assertEqual(result['segments_saved'], 1)
        self.assertEqual(result['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
        self.assertEqual(len(transport.calls), 3)

    def test_queries_and_transport_error_text_never_leak_into_status(self):
        url = URL + '?sig=SECRET_SENTINEL'
        transport = Transport({url: ValueError('SECRET_SENTINEL upstream private detail')})
        result = self.collector(transport, manifest(url=url)).tick()
        self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
        self.assertEqual(result['source_wait']['state'], 'TRANSIENT_SOURCE_WAIT')

    def test_source_manifest_replacement_and_private_symlink_are_rejected(self):
        transport = Transport({URL: playlist([0])})
        c = self.collector(transport); c.close()
        changed = manifest(); changed['source_evidence_sha256'] = 'b' * 64
        with self.assertRaises(ValueError):
            capture.Collector(self.root, changed, fetch=transport, clock=self.clock)
        link = self.root/'linked'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            capture.Collector(link, manifest(), fetch=transport, clock=self.clock)

    def test_http_is_only_allowed_for_synthetic_numeric_loopback(self):
        for url, role, accepted in [('http://127.0.0.1:12345/live.m3u8','SYNTHETIC_TEST',True),
                                    ('http://[::1]:12345/live.m3u8','SYNTHETIC_TEST',True),
                                    ('http://localhost/live.m3u8','SYNTHETIC_TEST',False),
                                    ('http://127.0.0.1/live.m3u8','OWNER_AUTHORIZED',False),
                                    ('http://outside.example/live.m3u8','SYNTHETIC_TEST',False)]:
            with self.subTest(url=url,role=role), tempfile.TemporaryDirectory() as d:
                origin = url.rsplit('/',1)[0]
                source = manifest(url=url,role=role,origins=[origin])
                if accepted:
                    c = self.collector(Transport({url: playlist([])}),source,Path(d))
                    self.assertEqual(c.tick()['segments_saved'],0)
                else:
                    with self.assertRaises(ValueError):
                        capture.Collector(Path(d),source,fetch=Transport({}),clock=self.clock)

    def test_same_uri_at_new_sequence_requires_new_media_bytes(self):
        raw=playlist([0]).replace(b's0.m4s',b'reused.m4s')
        routes={URL:raw,ORIGIN+'/reused.m4s':b'first-generation'}
        transport=Transport(routes);c=self.collector(transport);c.tick()
        routes[URL]=playlist([1],end=True).replace(b's1.m4s',b'reused.m4s')
        routes[ORIGIN+'/reused.m4s']=b'second-generation';self.clock.advance()
        self.assertEqual(c.tick()['segments_saved'],2)
        self.assertEqual(sum(u.endswith('reused.m4s') for u,_ in transport.calls),2)
        self.assertTrue((self.root/'blobs'/(sha256(b'second-generation').hexdigest()+'.blob')).exists())

    def test_same_map_uri_is_refetched_at_discontinuity(self):
        raw=b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\ns0.m4s\n'
        routes={URL:raw,ORIGIN+'/init.mp4':b'first-init',ORIGIN+'/s0.m4s':b'zero'}
        transport=Transport(routes);c=self.collector(transport);c.tick()
        routes[URL]=(b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1\n'
                     b'#EXT-X-DISCONTINUITY-SEQUENCE:1\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\ns1.m4s\n#EXT-X-ENDLIST\n')
        routes[ORIGIN+'/init.mp4']=b'second-init';routes[ORIGIN+'/s1.m4s']=b'one';self.clock.advance()
        c.tick()
        self.assertEqual(sum(u.endswith('init.mp4') for u,_ in transport.calls),2)
        self.assertEqual(len(c.list_windows()),2)

    def test_storage_failure_rolls_back_window_segment_duration_together(self):
        c=self.collector(Transport({URL:playlist([0]),ORIGIN+'/s0.m4s':b'zero'}))
        c.db.execute("CREATE TRIGGER fail_duration BEFORE UPDATE OF duration ON windows BEGIN SELECT RAISE(ABORT,'fictional-storage-fault'); END")
        result=c.tick()
        self.assertEqual(result['segments_saved'],0)
        self.assertEqual(c.list_windows(),[])
        self.assertEqual(result['source_wait']['state'],'SOURCE_REVIEW_WAIT')

    def test_known_denial_response_reconstructs_missing_legacy_wait_without_get(self):
        for status in (401,403,429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                transport=Transport({URL:(status,{'Retry-After':'7200'},b'denied')})
                c=self.collector(transport,root=Path(d));first=c.tick()
                # Replay an older crash boundary: completed HTTP metadata exists,
                # but the separate source_wait metadata write was not durable.
                c.db.execute("DELETE FROM meta WHERE key='source_wait'");c.close()
                transport.routes={URL:playlist([0]),ORIGIN+'/s0.m4s':b'zero'}
                result=self.collector(transport,root=Path(d)).tick()
                self.assertEqual(len(transport.calls),1)
                self.assertEqual(result['source_wait'],first['source_wait'])

    def test_media_publication_does_not_use_crash_sensitive_hardlinks(self):
        c=self.collector(Transport({URL:playlist([0],end=True),ORIGIN+'/s0.m4s':b'zero'}))
        with patch('os.link',side_effect=AssertionError('hardlink publication can strand nlink=2')):
            self.assertEqual(c.tick()['segments_saved'],1)

    def test_failed_remux_removes_uncommitted_partial_stage_files(self):
        c=self.collector(Transport({URL:playlist([0],end=True),ORIGIN+'/s0.m4s':b'fictional'}))
        wid=c.tick()['ready_windows'][0]
        for _ in range(2):
            with patch('subprocess.run',side_effect=subprocess.CalledProcessError(1,['ffmpeg'],stderr=b'private failure')):
                with self.assertRaises(ValueError):c.export_window(wid)
            self.assertEqual(list((self.root/'exports').glob('.tmp-export-*.mp4')),[])
        self.assertEqual(c.db.execute('SELECT COUNT(*) FROM export_intents').fetchone()[0],0)

    def test_analysis_ineligible_long_segment_does_not_stop_later_acquisition(self):
        routes={URL:playlist([0],duration=121),ORIGIN+'/s0.m4s':b'archive-only'}
        c=self.collector(Transport(routes));c.tick()
        row=c.list_windows()[0]
        self.assertFalse(row['analysis_exportable'])
        self.assertEqual(row['analysis_hold_reason'],'CLIP_DURATION_EXCEEDS_ANALYSIS_BOUND')
        with self.assertRaises(ValueError):c.export_window(row['window_id'])
        routes[URL]=playlist([1],end=True);routes[ORIGIN+'/s1.m4s']=b'valid-next';self.clock.advance()
        self.assertEqual(c.tick()['segments_saved'],2)
        self.assertTrue(c.list_windows()[1]['analysis_exportable'])

    def test_analysis_ineligible_bytes_are_archived_and_next_window_still_progresses(self):
        routes={URL:playlist([0],duration=30),ORIGIN+'/s0.m4s':b'ARCHIVE'}
        c=self.collector(Transport(routes))
        with patch.object(capture,'_MAX_ANALYSIS_BYTES',6):
            self.assertEqual(c.tick()['segments_saved'],1)
            self.assertEqual(c.list_windows()[0]['analysis_hold_reason'],'CLIP_BYTES_EXCEED_ANALYSIS_BOUND')
            with self.assertRaises(ValueError):c.export_window(1)
            routes[URL]=playlist([1],end=True);routes[ORIGIN+'/s1.m4s']=b'V';self.clock.advance()
            self.assertEqual(c.tick()['segments_saved'],2)
            self.assertTrue(c.list_windows()[1]['analysis_exportable'])

    @unittest.skipUnless(shutil.which('ffmpeg'),'local FFmpeg unavailable')
    def test_published_export_recovers_after_database_commit_failure_without_remux(self):
        sample=self.root/'sample.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=32x32:rate=2',
                        '-t','1','-an','-c:v','mpeg4','-threads','1',str(sample)],check=True,capture_output=True)
        c=self.collector(Transport({URL:playlist([0],end=True),ORIGIN+'/s0.m4s':sample.read_bytes()}))
        wid=c.tick()['ready_windows'][0]
        c.db.execute("CREATE TRIGGER fail_export BEFORE UPDATE OF export_json ON windows WHEN NEW.export_json IS NOT NULL BEGIN SELECT RAISE(ABORT,'fictional-final-commit-fault'); END")
        with self.assertRaises(sqlite3.DatabaseError):c.export_window(wid)
        old_receipt=(self.root/'exports'/f'{wid}.json').read_bytes()
        c.db.execute('DROP TRIGGER fail_export');c.close();self.clock.advance(120)
        c=self.collector(Transport({}))
        with patch('subprocess.run',side_effect=AssertionError('complete pending export must not remux')):
            result=c.export_window(wid)
        self.assertEqual((self.root/'exports'/f'{wid}.json').read_bytes(),old_receipt)
        self.assertEqual(capture.verify_export(result),result)

    @unittest.skipUnless(shutil.which('ffmpeg'),'local FFmpeg unavailable')
    def test_staged_export_directory_is_durable_before_intent_commit(self):
        sample=self.root/'sample.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=32x32:rate=2',
                        '-t','1','-an','-c:v','mpeg4','-threads','1',str(sample)],check=True,capture_output=True)
        c=self.collector(Transport({URL:playlist([0],end=True),ORIGIN+'/s0.m4s':sample.read_bytes()}))
        wid=c.tick()['ready_windows'][0]
        observed=[];real_fsync=os.fsync;exports_inode=(self.root/'exports').stat().st_ino
        def fsync(fd):
            info=os.fstat(fd)
            if stat.S_ISDIR(info.st_mode) and info.st_ino==exports_inode:observed.append('exports_fsync')
            return real_fsync(fd)
        c.db.set_trace_callback(lambda sql: observed.append('intent_insert') if sql.startswith('INSERT INTO export_intents') else None)
        with patch('os.fsync',side_effect=fsync):c.export_window(wid)
        self.assertLess(observed.index('exports_fsync'),observed.index('intent_insert'))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local FFmpeg unavailable')
    def test_real_fragment_export_is_local_idempotent_and_media_integrity_checked(self):
        sample = self.root/'fixture.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=160x96:rate=6',
                        '-t','2','-an','-c:v','mpeg4','-threads','1','-g','6','-movflags','frag_keyframe+empty_moov',
                        str(sample)],check=True,capture_output=True)
        raw = sample.read_bytes(); at = 0; boxes=[]
        while at < len(raw):
            length=int.from_bytes(raw[at:at+4],'big');self.assertGreaterEqual(length,8)
            boxes.append((raw[at+4:at+8],raw[at:at+length]));at+=length
        init=b''; parts=[]
        for kind,body in boxes:
            if kind==b'moof':parts.append(body)
            elif parts:parts[-1]+=body
            else:init+=body
        self.assertEqual(len(parts),2)
        body=(b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MAP:URI="init.mp4"\n'
              b'#EXT-X-PROGRAM-DATE-TIME:2020-01-01T00:00:00Z\n#EXTINF:1,\ns0.m4s\n'
              b'#EXTINF:1,\ns1.m4s\n#EXT-X-ENDLIST\n')
        transport=Transport({URL:body,ORIGIN+'/init.mp4':init,ORIGIN+'/s0.m4s':parts[0],ORIGIN+'/s1.m4s':parts[1]})
        c=self.collector(transport);result=c.tick();window=result['ready_windows'][0]
        exported=c.export_window(window)
        self.assertEqual(capture.verify_export(exported),exported)
        self.assertEqual(c.export_window(window),exported)
        self.assertTrue(c.list_windows()[0]['exported'])
        probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries',
                              'stream=nb_read_frames','-of','json',exported['media_path']],check=True,capture_output=True)
        self.assertEqual(json.loads(probe.stdout)['streams'][0]['nb_read_frames'],'12')
        receipt=json.loads(Path(exported['receipt_path']).read_bytes())
        self.assertEqual(receipt['segments'][0]['program_date_time'],'2020-01-01T00:00:00Z')
        self.assertEqual(receipt['captured_at'],exported['captured_at'])
        self.assertNotEqual(receipt['captured_at'],'2020-01-01T00:00:00Z')
        self.assertNotIn(URL,json.dumps(receipt))
        Path(exported['media_path']).write_bytes(b'corrupted')
        with self.assertRaises(ValueError):capture.verify_export(exported)


if __name__ == '__main__':
    unittest.main()
