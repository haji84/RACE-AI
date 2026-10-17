"""Synthetic equivalents of pre-exhibition pages with printed non-exhibition facts."""
from copy import deepcopy
import hashlib
import unittest

from race_ai.core import SourceError
from race_ai.official_race_updates import parse_update,endpoint
from tests.test_official_race_updates import DAY,CAPTURE,page,preview,starts
from web.race_contract import canonical,validate_record


def empty_grid():
    return '<table><thead><tr><th>スタート展示</th></tr></thead><tbody>'+''.join(
        '<tr><td></td></tr>' for _ in range(6))+'</tbody></table>'


def missing_preview(*,blank_grid=True):
    body=preview().replace('6.92','--')
    if blank_grid:return body.replace(starts(),empty_grid())
    for n in range(1,7):body=body.replace(f'.1{n}','--')
    return body


def program():
    return dict(race_id='20261015-18-01',closed_at='2026-10-15T08:43:00+09:00',
                boats=[dict(lane=n,racer_registration_id=str(4000+n),name='選手'+str(n)) for n in range(1,7)])


def parse(body,entries=None):
    return parse_update(page('beforeinfo',body),kind='beforeinfo',day=DAY,venue='18',race_no=1,
        source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at=CAPTURE,entries=entries)


def stored(observation):
    value=deepcopy(observation)
    value['snapshot_id']=hashlib.sha256(canonical(value)).hexdigest()
    value.update(saved_at='2026-10-15T07:01:00+09:00',storage_eligible_pre_race=True)
    return value


class OfficialPreviewPendingTests(unittest.TestCase):
    def test_empty_display_and_start_grid_ignore_printed_tilt_weight_and_weather(self):
        body=missing_preview()
        self.assertIn('52.0kg',body);self.assertIn('<td>0.0</td>',body);self.assertIn('weather1',body)
        observation=parse(body,program()['boats'])
        self.assertEqual(observation['status'],'PENDING')
        self.assertIsNone(observation['data'])
        self.assertEqual(observation['missing_reason'],'OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID')
        self.assertEqual(observation['observed_racers'],program()['boats'])
        self.assertTrue(observation['body_identity_verified'])
        record=stored(observation)
        self.assertEqual(validate_record(record,program(),'2026-10-15T07:02:00+09:00'),record)

    def test_six_identified_missing_start_tokens_also_normalize_without_zero_measurements(self):
        observation=parse(missing_preview(blank_grid=False),program()['boats'])
        self.assertEqual(observation['status'],'PENDING')
        self.assertIsNone(observation['data'])
        self.assertEqual(len(observation['observed_racers']),6)

    def test_published_display_with_empty_grid_or_broken_identity_still_rejects(self):
        body=missing_preview()
        for bad in (body.replace('<td>--</td>','<td>6.92</td>',1),
                    body.replace('toban=4001','toban=4002'),
                    body.replace('<tr><td></td></tr>','',1)):
            with self.subTest(bad=bad[:40]),self.assertRaises(SourceError):parse(bad,program()['boats'])
        for key,value in [('name','別選手'),('racer_registration_id','4999')]:
            entries=deepcopy(program()['boats']);entries[0][key]=value
            with self.subTest(key=key),self.assertRaises(SourceError):parse(body,entries)

    def test_any_normal_or_flying_late_exhibition_st_is_not_discarded_as_missing(self):
        body=missing_preview(blank_grid=False)
        for token in ('.11','F.11','L.11'):
            observation=parse(body.replace('>--</span>',f'>{token}</span>',1))
            self.assertIsNotNone(observation['data'])
            first=observation['data']['boats'][0]
            self.assertEqual(first['preview_raw_st'],token)
            self.assertEqual(first['preview_st_status'],'OK' if token=='.11' else token[0])
            self.assertNotIn('observed_racers',observation)

    def test_common_contract_still_rejects_rehashed_pending_plus_published_metrics(self):
        observation=stored(parse(missing_preview(),program()['boats']))
        published=parse(preview())
        observation['data']=published['data']
        observation['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in observation.items()
            if k not in {'snapshot_id','saved_at','storage_eligible_pre_race'}})).hexdigest()
        with self.assertRaises(ValueError):validate_record(observation,program(),'2026-10-15T07:02:00+09:00')

    def test_legacy_saved_all_missing_preview_data_still_validates_without_contract_change(self):
        legacy=parse(preview());legacy['status']='PENDING'
        for boat in legacy['data']['boats']:
            boat.update(display_time=None,preview_st=None,preview_st_status='PENDING',preview_raw_st='--')
        record=stored(legacy)
        self.assertEqual(validate_record(record,program(),'2026-10-15T07:02:00+09:00'),record)


if __name__=='__main__':unittest.main()
