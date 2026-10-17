"""Synthetic chapter seek points, not evidence of the actual video content."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import unittest

from race_ai.core import SourceError
from race_ai.exhibition_video_source import PLAYER, SourceResponse
from race_ai.live_video_source import resolve_live_schedule
from race_ai.live_video_chapters import resolve_live_chapters
from tests.test_live_video_source import setting, Fetch
from web.race_contract import canonical

NOW = datetime.fromisoformat('2026-10-16T17:10:00+09:00')


def parent():
    return resolve_live_schedule('24', fetch=Fetch(setting()), clock=lambda: NOW)


def index():
    rows = [{f'position_{p}': '' for p in range(1, 6)} for _ in range(12)]
    rows[0] = dict(position_1=18618, position_2=18753, position_3=19648,
                   position_4=19744, position_5=19761)
    rows[1].update(position_1=19947, position_2=20082)
    return dict(race=rows, update_from='chapter operator', last_update='2026-10-16T17:00:00+09:00')


class ChapterFetch:
    def __init__(self, value=None):
        self.value = index() if value is None else value
        self.calls = []
        self.override = None

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.override or SourceResponse(200, url, 'application/json', canonical(self.value))


def run(fetch=None, **kwargs):
    return resolve_live_chapters(kwargs.pop('schedule', parent()), fetch=fetch or ChapterFetch(),
                                 clock=kwargs.pop('clock', lambda: NOW), **kwargs)


class LiveVideoChapterTests(unittest.TestCase):
    def test_two_exhibition_and_three_race_seek_labels_never_become_intervals_or_features(self):
        fetch = ChapterFetch(); result = run(fetch)
        self.assertEqual(len(fetch.calls), 1)
        url, args = fetch.calls[0]
        self.assertEqual(url, PLAYER + '/setting/chapter/24omura/mix/chapter.json')
        self.assertEqual(args['max_bytes'], 65536); self.assertEqual(args['timeout'], 10)
        self.assertEqual(result['schedule_snapshot_id'], parent()['snapshot_id'])
        self.assertEqual(result['indexed_race_slots'], 12)
        self.assertEqual(result['published_seek_points'], 7)
        self.assertEqual([a['publisher_label'] for a in result['races'][0]['anchors']],
                         ['展示ピットアウト', '周回展示', '本番ピットアウト', 'スタート直前', '1マーク'])
        self.assertEqual(result['races'][0]['anchors'][1]['seek_seconds'], 18753)
        self.assertEqual(result['races'][0]['anchors'][1]['publisher_phase'], 'EXHIBITION')
        self.assertEqual(result['races'][0]['anchors'][2]['publisher_phase'], 'RACE')
        self.assertIsNone(result['races'][1]['anchors'][2]['seek_seconds'])
        self.assertEqual(result['races'][0]['indexed_race_number'], 1)
        self.assertFalse(result['prediction_input_eligible'])
        self.assertEqual(result['boat_features'], [])
        self.assertEqual(result['frame_race_phase_verification'], 'UNVERIFIED')
        self.assertEqual(result['player_time_origin'], 'UNVERIFIED')
        self.assertEqual(result['physical_exhibition_timing'], 'UNVERIFIED')
        self.assertEqual(result['model_validation_status'], 'UNVALIDATED')
        self.assertNotIn('race_id', result)
        self.assertNotIn('exhibition_interval', result['races'][0])
        self.assertEqual(result['snapshot_id'], hashlib.sha256(canonical({k:v for k,v in result.items() if k!='snapshot_id'})).hexdigest())

    def test_all_blank_is_pending_and_zero_is_never_an_anchor(self):
        value = index()
        for row in value['race']:
            for key in row: row[key] = ''
        result = run(ChapterFetch(value))
        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(result['published_seek_points'], 0)
        value['race'][0]['position_1'] = 0
        with self.assertRaises(SourceError): run(ChapterFetch(value))

    def test_stale_future_naive_or_other_day_parent_makes_zero_gets(self):
        for at in (NOW + timedelta(seconds=91), NOW - timedelta(microseconds=1),
                   NOW.replace(tzinfo=None), NOW + timedelta(days=1)):
            fetch = ChapterFetch()
            with self.subTest(at=at), self.assertRaises(SourceError): run(fetch, clock=lambda: at)
            self.assertFalse(fetch.calls)

    def test_exact_parent_age_boundary_and_post_fetch_revalidation(self):
        self.assertEqual(run(clock=lambda: NOW + timedelta(seconds=90))['status'], 'INDEXED_SEEK_POINTS')
        ticks = iter((NOW + timedelta(seconds=89), NOW + timedelta(seconds=91)))
        fetch = ChapterFetch()
        with self.assertRaises(SourceError): run(fetch, clock=lambda: next(ticks))
        self.assertEqual(len(fetch.calls), 1)

    def test_parent_hash_and_scope_cannot_be_changed_even_after_rehash(self):
        changes = [('stadium','02toda'), ('venue_code','02'), ('channel_ref','lm-mix-02toda-tokyo'),
                   ('schema_version','normal-live-schedule/v2'), ('source_url',PLAYER+'/setting/chapter/24omura/mix/chapter.json'),
                   ('player_url','https://evil.invalid'), ('prediction_input_eligible',True),
                   ('boat_features',[{'boat':1}]), ('race_binding_status','VERIFIED'),
                   ('model_validation_status','VALIDATED'), ('schedule_status','VIDEO_AVAILABLE')]
        for key,value in changes:
            s=parent();s[key]=value;s['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in s.items() if k!='snapshot_id'})).hexdigest()
            fetch=ChapterFetch()
            with self.subTest(key=key), self.assertRaises(SourceError): run(fetch,schedule=s)
            self.assertFalse(fetch.calls)
        s=parent();s['snapshot_id']='a'*64
        with self.assertRaises(SourceError):run(schedule=s)

    def test_parent_exact_fields_digests_and_time_relations(self):
        for mutate in (lambda s:s.update(token='x'), lambda s:s.pop('captured_at'),
                       lambda s:s.update(source_sha256='bad'), lambda s:s.update(requested_at='2026-10-16T17:10:01+09:00'),
                       lambda s:s.update(setting_updated_at='2026-10-16T17:10:01+09:00'),
                       lambda s:s.update(scheduled_end_at=s['scheduled_start_at'])):
            s=parent();mutate(s);s['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in s.items() if k!='snapshot_id'})).hexdigest()
            fetch=ChapterFetch()
            with self.assertRaises(SourceError):run(fetch,schedule=s)
            self.assertFalse(fetch.calls)

    def test_row_count_exact_keys_and_top_fields(self):
        for mutate in (lambda v:v['race'].pop(), lambda v:v['race'].append(deepcopy(v['race'][0])),
                       lambda v:v.update(media_url='x'), lambda v:v['race'][0].update(position_6=10),
                       lambda v:v['race'][0].pop('position_5'), lambda v:v.update(race={})):
            v=index();mutate(v)
            with self.assertRaises(SourceError):run(ChapterFetch(v))

    def test_only_positive_bounded_integer_or_exact_empty_string(self):
        for value in (False,True,None,0,-1,1.0,'18618',' ','NaN',86401,[],{}):
            v=index();v['race'][0]['position_1']=value
            with self.subTest(value=value),self.assertRaises(SourceError):run(ChapterFetch(v))

    def test_reversed_duplicate_or_gapped_positions_are_rejected(self):
        for mutate in (lambda v:v['race'][0].update(position_2=18618),
                       lambda v:v['race'][0].update(position_2=18000),
                       lambda v:v['race'][0].update(position_1=''),
                       lambda v:v['race'][1].update(position_1=19761),
                       lambda v:v['race'][1].update(position_1='',position_2='') or v['race'][2].update(position_1=21000)):
            v=index();mutate(v)
            with self.assertRaises(SourceError):run(ChapterFetch(v))

    def test_child_update_is_current_day_not_future_and_not_a_physical_clock(self):
        for at in ('2026-10-15T17:00:00+09:00','2026-10-16T17:10:01+09:00','2026-10-16T17:00:00'):
            v=index();v['last_update']=at
            with self.subTest(at=at),self.assertRaises(SourceError):run(ChapterFetch(v))
        v=index();v['update_from']=''
        with self.assertRaises(SourceError):run(ChapterFetch(v))

    def test_child_fetch_clock_bounds_and_date(self):
        for end in (NOW-timedelta(microseconds=1),NOW+timedelta(seconds=10,microseconds=1),NOW+timedelta(days=1)):
            ticks=iter((NOW,end));fetch=ChapterFetch()
            with self.assertRaises(SourceError):run(fetch,clock=lambda:next(ticks))
            self.assertEqual(len(fetch.calls),1)

    def test_response_redirect_mime_status_size_and_duplicate_json(self):
        url=PLAYER+'/setting/chapter/24omura/mix/chapter.json'
        for response in (SourceResponse(200,url+'?x=1','application/json',canonical(index())),
                         SourceResponse(302,url,'application/json',canonical(index())),
                         SourceResponse(200,url,'text/html',canonical(index())),
                         SourceResponse(200,url,'application/json',b' ' * 65537),
                         SourceResponse(200,url,'application/json',b'{"race":[],"race":[]}'),
                         SourceResponse(200,url,'application/json',b'{"x":NaN}'),
                         SourceResponse(200,url,'application/json',b'\xff')):
            fetch=ChapterFetch();fetch.override=response
            with self.subTest(response=response),self.assertRaises(SourceError):run(fetch)
            self.assertEqual(len(fetch.calls),1)

    def test_transport_exception_is_sanitized_without_retry(self):
        calls=[]
        def fetch(url,**kwargs):
            calls.append(url);raise ValueError('https://evil.invalid?token=LEAK')
        with self.assertRaisesRegex(SourceError,'^LIVE_CHAPTER_UNAVAILABLE$'):run(fetch)
        self.assertEqual(len(calls),1)

    def test_parent_is_frozen_before_fetch_callback_can_change_venue(self):
        schedule=parent();original_id=schedule['snapshot_id'];calls=[]
        def fetch(url,**kwargs):
            calls.append(url)
            replacement=resolve_live_schedule('02',fetch=Fetch(setting('02toda')),clock=lambda:NOW)
            schedule.clear();schedule.update(replacement)
            return SourceResponse(200,url,'application/json',canonical(index()))
        result=run(fetch,schedule=schedule)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['venue_code'],'24')
        self.assertEqual(result['channel_ref'],'lm-mix-24omura-tokyo')
        self.assertEqual(result['schedule_snapshot_id'],original_id)


if __name__=='__main__':unittest.main()
