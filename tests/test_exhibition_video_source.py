"""No-network boundary tests; all client metadata and token strings are synthetic."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import pickle
import unittest

from race_ai.core import SourceError
import race_ai.exhibition_video_source as video_source
from race_ai.exhibition_video_source import (SourceResponse, resolve_exhibition_source,
                                             validate_descriptor)
from web.race_contract import canonical

TOKEN='SYNTHETIC_ONLY_DO_NOT_USE'
MEDIA='a'*32
SOURCE='b'*32
NOW='2026-10-15T10:20:00+09:00'


def program():
    return dict(race_id='20261015-14-05',closed_at='2026-10-15T10:21:00+09:00',
                boats=[dict(lane=n,racer_registration_id=str(4100+n),name='選手'+str(n)) for n in range(1,7)])


def recording():
    return dict(races={f'{n:02d}':dict(race_number=f'{n:02d}',
                    ref_id=f'mix-14naruto-exhibition-20261015-{n:02d}' if n<=5 else '',
                    source_type='mix' if n<=5 else '') for n in range(1,13)},
                update_from='録画終了',last_update='2026-10-15T10:05:20+09:00')


def metadata():
    url=f'https://manifest.streaks.jp/v6/cp-boatrace-prod/{MEDIA}/{SOURCE}/hls/v3/manifest.m3u8?token={TOKEN}'
    return dict(project_id='cp-boatrace-prod',id=MEDIA,ref_id='mix-14naruto-exhibition-20261015-05',
                type='clip',duration=344,offline_enabled=True,
                sources=[dict(id=SOURCE,type='application/x-mpegURL',src=url)])


class FakeFetch:
    def __init__(self,index=None,media=None):
        self.index=recording() if index is None else index
        self.media=metadata() if media is None else media
        self.calls=[];self.override=None
    def __call__(self,url,*,headers,max_bytes,timeout):
        self.calls.append(dict(url=url,headers=headers,max_bytes=max_bytes,timeout=timeout))
        if self.override is not None:return self.override(url)
        value=self.index if '/setting/vod/' in url else self.media
        return SourceResponse(200,url,'application/json',json.dumps(value,ensure_ascii=False).encode())


def run(fetch=None,**kwargs):
    return resolve_exhibition_source(program(),fetch=fetch or FakeFetch(),
            clock=kwargs.pop('clock',lambda:datetime.fromisoformat(NOW)),**kwargs)


class ExhibitionVideoSourceTests(unittest.TestCase):
    def rehash(self,value):
        value['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in value.items() if k!='snapshot_id'})).hexdigest()

    def test_all24_stadium_identifiers_are_pinned_to_observed_official_mapping(self):
        expected={
            '01':'01kiryu','02':'02toda','03':'03edogawa','04':'04heiwajima',
            '05':'05tamagawa','06':'06hamanako','07':'07gamagori','08':'08tokoname',
            '09':'09tsu','10':'10mikuni','11':'11biwako','12':'12suminoe',
            '13':'13amagasaki','14':'14naruto','15':'15marugame','16':'16kojima',
            '17':'17miyajima','18':'18tokuyama','19':'19shimonoseki','20':'20wakamatsu',
            '21':'21ashiya','22':'22fukuoka','23':'23karatsu','24':'24omura'}
        self.assertEqual(dict(video_source.STADIUMS),expected)
        proof=getattr(video_source,'STADIUM_MAPPING_EVIDENCE',None)
        self.assertIsInstance(proof,dict)
        self.assertEqual(proof['source_url'],'https://race.boatcast.jp/assets/js/main.js')
        self.assertRegex(proof['source_sha256'],r'^[0-9a-f]{64}$')
        self.assertEqual(proof['source_sha256'],'83f1bf539388ee9ca3a652d90b42b89ff4657b40f72d010a3a0cf77aa2a9fe51')
        self.assertEqual(proof['captured_at'],'2026-10-15T01:58:56.015670+00:00')
        self.assertEqual(proof['coverage'],'IDENTIFIERS_ONLY_MEDIA_AVAILABILITY_UNVERIFIED')

    def test_default_verified_mapping_selects_each_stadium_with_only_a_fake_pending_index(self):
        expected=['01kiryu','02toda','03edogawa','04heiwajima','05tamagawa','06hamanako',
                  '07gamagori','08tokoname','09tsu','10mikuni','11biwako','12suminoe',
                  '13amagasaki','14naruto','15marugame','16kojima','17miyajima','18tokuyama',
                  '19shimonoseki','20wakamatsu','21ashiya','22fukuoka','23karatsu','24omura']
        for venue,stadium in enumerate(expected,1):
            with self.subTest(venue=venue):
                race=program();race['race_id']=f'20261015-{venue:02d}-05'
                index=recording()
                for row in index['races'].values():row.update(ref_id='',source_type='')
                fetch=FakeFetch(index=index)
                descriptor,lease=resolve_exhibition_source(race,fetch=fetch,
                    clock=lambda:datetime.fromisoformat(NOW))
                self.assertEqual(descriptor['stadium'],stadium)
                self.assertEqual(descriptor['status'],'PENDING');self.assertIsNone(lease)
                self.assertEqual(len(fetch.calls),1)
                self.assertIn(f'/20261015/{stadium}/exhibition/setting.json',fetch.calls[0]['url'])
                self.assertIn(f'stadium={stadium}&raceType=exhibition',fetch.calls[0]['headers']['Referer'])

    def test_known_mapping_never_accepts_another_venues_explicit_stadium(self):
        fetch=FakeFetch()
        with self.assertRaises(SourceError):run(fetch,stadium='06hamanako')
        self.assertFalse(fetch.calls)

    def test_normal_public_resolution_is_two_bounded_gets_without_api_key_or_video_get(self):
        fetch=FakeFetch();descriptor,lease=run(fetch,player_duration_seconds=348)
        self.assertEqual(len(fetch.calls),2)
        self.assertEqual(descriptor['status'],'AVAILABLE')
        self.assertTrue(descriptor['capture_eligible_pre_race'])
        self.assertEqual(descriptor['media']['duration_metadata_raw'],344)
        self.assertEqual(descriptor['media']['duration_player_observed_seconds'],348)
        self.assertEqual(descriptor['media']['duration_comparison'],'DISTINCT_SOURCE_OBSERVATIONS')
        self.assertEqual(descriptor['model_validation_status'],'UNVALIDATED')
        self.assertEqual(descriptor['boat_features'],'NONE')
        self.assertNotIn(TOKEN,json.dumps(descriptor))
        for call in fetch.calls:
            self.assertLessEqual(call['max_bytes'],1024*1024)
            self.assertEqual(call['timeout'],10)
            self.assertNotIn('X-Streaks-Api-Key',call['headers'])
            self.assertEqual(call['headers']['Origin'],'https://front.player.boatrace-cdn.jp')
            self.assertIn('raceType=exhibition',call['headers']['Referer'])
            self.assertNotIn('manifest.streaks.jp',call['url'])
        self.assertIsNone(validate_descriptor(descriptor,program(),NOW))
        self.assertTrue(lease.consume(lambda url: url.startswith('https://manifest.streaks.jp/')))
        with self.assertRaises(SourceError):lease.consume(lambda url:True)

    def test_empty_recording_is_pending_without_metadata_call(self):
        index=recording();index['races']['05'].update(ref_id='',source_type='')
        fetch=FakeFetch(index=index);descriptor,lease=run(fetch)
        self.assertEqual(len(fetch.calls),1)
        self.assertEqual(descriptor['status'],'PENDING');self.assertIsNone(descriptor['media'])
        self.assertIsNone(lease)

    def test_unknown_stadium_or_noncurrent_identity_rejected_before_network(self):
        for race,stadium,clock in [(program(),'06hamanako',NOW),
                ({**program(),'race_id':'20261015-06-05'},'14naruto',NOW),
                (program(),'14naruto','2026-10-16T00:01:00+09:00')]:
            fetch=FakeFetch()
            with self.subTest(stadium=stadium,clock=clock),self.assertRaises(SourceError):
                resolve_exhibition_source(race,stadium=stadium,fetch=fetch,clock=lambda:datetime.fromisoformat(clock))
            self.assertFalse(fetch.calls)

    def test_recording_identity_coverage_source_type_and_update_time_rejected(self):
        mutations=[lambda x:x['races']['05'].update(ref_id='mix-14naruto-race-20261015-05'),
                   lambda x:x['races']['05'].update(race_number='06'),
                   lambda x:x['races']['05'].update(source_type='other'),
                   lambda x:x['races'].pop('12'),
                   lambda x:x.update(last_update='2026-10-15T10:22:00+09:00'),
                   lambda x:x.update(last_update='2026-10-15T10:00:00+09:99')]
        for mutation in mutations:
            index=recording();mutation(index);fetch=FakeFetch(index=index)
            with self.subTest(mutation=mutation),self.assertRaises(SourceError):run(fetch)
            self.assertEqual(len(fetch.calls),1)

    def test_metadata_ref_project_type_media_id_and_drm_are_required(self):
        mutations=[lambda x:x.update(project_id='another-project'),lambda x:x.update(ref_id='different'),
                   lambda x:x.update(type='live'),lambda x:x.update(id='not-a-media-id'),
                   lambda x:x['sources'][0].update(key_systems={'widevine':{}}),
                   lambda x:x['sources'][0].update(type='video/mp4'),
                   lambda x:x['sources'].append(deepcopy(x['sources'][0]))]
        for mutation in mutations:
            media=metadata();mutation(media)
            with self.subTest(mutation=mutation),self.assertRaises(SourceError):run(FakeFetch(media=media))

    def test_signed_resource_url_rejects_ssrf_path_identity_and_query_changes(self):
        original=metadata()['sources'][0]['src']
        bads=[original.replace('https://','http://'),original.replace('manifest.streaks.jp','127.0.0.1'),
              original.replace('manifest.streaks.jp','manifest.streaks.jp.evil'),
              original.replace('/cp-boatrace-prod/','/other/'),original.replace(MEDIA,'c'*32),
              original.replace(SOURCE,'d'*32),original.replace('/v6/','/v5/'),
              original.replace('?token=', '?secret='),original+'&token=duplicate',original+'#fragment',
              original.replace(TOKEN,'bad%0Avalue'),original.replace(TOKEN,'bad%22value'),
              original.replace('manifest.streaks.jp','user:pass@manifest.streaks.jp'),
              original.replace('manifest.streaks.jp','manifest.streaks.jp:443')]
        for url in bads:
            media=metadata();media['sources'][0]['src']=url
            with self.subTest(url=url.split('?')[0]),self.assertRaises(SourceError):run(FakeFetch(media=media))

    def test_http_body_mime_size_duplicate_json_and_exception_errors_are_sanitized(self):
        for make in [lambda url:SourceResponse(302,url,'application/json',b'{}'),
                     lambda url:SourceResponse(200,url+'?wrong=1','application/json',b'{}'),
                     lambda url:SourceResponse(200,url,'text/html',b'{}'),
                     lambda url:SourceResponse(200,url,'application/json',b'x'*(1024*1024+1)),
                     lambda url:SourceResponse(200,url,'application/json',b'{"races":{},"races":{}}')]:
            fetch=FakeFetch();fetch.override=make
            with self.subTest(make=make),self.assertRaises(SourceError):run(fetch)
        fetch=FakeFetch()
        def error(url):raise RuntimeError('secret signed token='+TOKEN)
        fetch.override=error
        with self.assertRaises(SourceError) as caught:run(fetch)
        self.assertNotIn(TOKEN,str(caught.exception))

    def test_nonfinite_bool_durations_and_future_or_naive_clock_rejected(self):
        for value in [True,-1,0,1201,float('nan'),float('inf'),'344']:
            media=metadata();media['duration']=value
            with self.subTest(value=value),self.assertRaises(SourceError):run(FakeFetch(media=media))
        for value in [True,-1,float('nan'),1201]:
            with self.subTest(player=value),self.assertRaises(SourceError):run(player_duration_seconds=value)
        with self.assertRaises(SourceError):run(clock=lambda:datetime(2026,10,15,10,20))
        times=iter([datetime.fromisoformat(NOW),datetime.fromisoformat('2026-10-15T10:22:00+09:00'),
                    datetime.fromisoformat(NOW),datetime.fromisoformat(NOW)])
        with self.assertRaises(SourceError):run(clock=lambda:next(times))

    def test_at_or_after_close_remains_research_only(self):
        descriptor,_=run(clock=lambda:datetime.fromisoformat('2026-10-15T10:21:00+09:00'))
        self.assertFalse(descriptor['capture_eligible_pre_race'])

    def test_lease_repr_serialization_and_processor_failure_never_return_signed_token(self):
        descriptor,lease=run()
        self.assertNotIn(TOKEN,repr(lease));self.assertNotIn(TOKEN,str(lease))
        for encode in (json.dumps,pickle.dumps,vars):
            with self.subTest(encoder=encode),self.assertRaises(TypeError):encode(lease)
        with self.assertRaises(SourceError) as caught:lease.consume(lambda url:url)
        self.assertNotIn(TOKEN,str(caught.exception))
        _,lease=run()
        def fail(url):raise ValueError(url)
        with self.assertRaises(SourceError) as caught:lease.consume(fail)
        self.assertNotIn(TOKEN,str(caught.exception))

    def test_derived_output_has_fixed_utf8_byte_bound(self):
        limit=256000
        _,lease=run()
        exact='x'*(limit-2)
        self.assertEqual(len(canonical(exact)),limit)
        self.assertEqual(lease.consume(lambda url:exact),exact)
        for output in ('x'*(limit-1),'界'*((limit-2)//3+1)):
            self.assertEqual(len(canonical(output)),limit+1)
            _,lease=run()
            with self.subTest(multibyte='界' in output):
                with self.assertRaises(SourceError) as caught:
                    lease.consume(lambda url:output)
                self.assertNotIn(TOKEN,str(caught.exception))
                self.assertEqual(str(caught.exception),'VIDEO_TRANSIENT_PROCESSOR_FAILED')

    def test_raw_resource_controls_and_nonascii_are_rejected_before_url_normalization(self):
        original=metadata()['sources'][0]['src']
        for url in (original.replace('manifest.streaks.jp','manifest.strea\nks.jp'),
                    original.replace('manifest.streaks.jp','manifest.strea\tks.jp'),
                    '\n'+original,original+'\r',original.replace('manifest.streaks.jp','manifest.streaks.jp\u00a0')):
            media=metadata();media['sources'][0]['src']=url
            with self.subTest(raw_control=repr(url.split('?')[0])),self.assertRaises(SourceError):
                run(FakeFetch(media=media))
    def test_descriptor_rehashed_type_source_time_phase_and_token_forgery_rejected(self):
        descriptor,_=run()
        mutations=[lambda x:x.update(capture_eligible_pre_race=False),lambda x:x.update(boat_features='TRACKED'),
                   lambda x:x.update(model_validation_status='VALIDATED'),lambda x:x.update(signed_url=TOKEN),
                   lambda x:x['media'].update(source_url_without_query=x['media']['source_url_without_query']+'?token='+TOKEN),
                   lambda x:x['media'].update(duration_metadata_raw=True),
                   lambda x:x['sources'][0].update(captured_at='2026-10-15T10:22:00+09:00'),
                   lambda x:x.update(recording_ref='wrong')]
        for mutation in mutations:
            bad=deepcopy(descriptor);mutation(bad);self.rehash(bad)
            with self.subTest(mutation=mutation),self.assertRaises(SourceError):validate_descriptor(bad,program(),NOW)


if __name__=='__main__':unittest.main()
