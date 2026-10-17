"""Synthetic TSV equivalents of a separately observed public original tab."""
from copy import deepcopy
import hashlib
import unittest

from race_ai.core import SourceError
from race_ai.boatcast_original import endpoint, parse_original, validate_original_observation
from web.race_contract import canonical

NOW = '2026-10-15T10:15:00+09:00'
CAPTURE = '2026-10-15T10:10:00+09:00'
SECOND_CAPTURE = '2026-10-15T10:11:00+09:00'


def program():
    return dict(race_id='20261015-14-05', closed_at='2026-10-15T10:30:00+09:00',
                boats=[dict(lane=n, racer_registration_id=str(4100+n), name='選手'+str(n))
                       for n in range(1, 7)])


def original():
    return ('data=\n1\t3\n一　周\tまわり足\t直　線\n' + '\n'.join(
        f'{n}\t選手{n}\t36.42\t5.94\t6.93' for n in range(1, 7)) + '\n').encode()


def companion():
    rows=[]
    for n in range(1, 7):
        row=['選手'+str(n), '6.81', '0', '000', '52.0', '0', '+ 0.0']+['']*22
        rows.append('\t'.join(row))
    starts='\t'.join(value for n in range(1, 7) for value in (str(n), '.03', ''))
    return ('data=\n1\n'+'\n'.join(rows)+'\n'+starts+'\n').encode()


def parse(first=None, second=None, **overrides):
    arguments=dict(race=program(), source_url=endpoint('20261015-14-05', 'original'),
                   captured_at=CAPTURE, companion_source_url=endpoint('20261015-14-05', 'standard'),
                   companion_captured_at=SECOND_CAPTURE, now=NOW)
    arguments.update(overrides)
    return parse_original(original() if first is None else first,
                          companion() if second is None else second, **arguments)


class BoatcastOriginalTests(unittest.TestCase):
    def rehash(self, value):
        value['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in value.items() if k!='snapshot_id'})).hexdigest()
        return value

    def test_complete_timings_bind_program_without_fabricating_body_date_registration_or_save(self):
        result=parse()
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertFalse(result['body_date_verified'])
        self.assertEqual(result['identity_evidence'], 'EXACT_SOURCE_URLS_AND_SIX_PROGRAM_NAMES')
        self.assertTrue(result['capture_eligible_pre_race'])
        self.assertEqual(result['boats'][0]['original_times'], dict(lap_s=36.42, turn_s=5.94, straight_s=6.93))
        self.assertEqual(result['boats'][0]['display_time_s'], 6.81)
        self.assertEqual(result['boats'][0]['racer_registration_id'], '4101')
        self.assertEqual(result['boats'][0]['registration_source'], 'approved_program')
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(result['sources'][0]['source_sha256'], hashlib.sha256(original()).hexdigest())
        self.assertEqual(result['sources'][1]['source_sha256'], hashlib.sha256(companion()).hexdigest())
        for source in result['sources']:
            self.assertEqual(source['available_at'], source['captured_at'])
            self.assertIsNone(source['upstream_published_at'])
        for absent in ('saved_at','cloud_saved_at','actual_st','preview_course','rights_review'):
            self.assertNotIn(absent, result)
        self.assertIsNone(validate_original_observation(result, program(), NOW))

    def test_dash_is_null_with_reason_and_24_slot_coverage_controls_status(self):
        partial=parse(original().replace(b'36.42', b'-', 1))
        self.assertEqual(partial['status'], 'PARTIAL')
        self.assertIsNone(partial['boats'][0]['original_times']['lap_s'])
        self.assertEqual(partial['boats'][0]['missing_reasons'], {'lap_s':'SOURCE_NOT_PUBLISHED'})
        blank=original().replace(b'36.42',b'-').replace(b'5.94',b'-').replace(b'6.93',b'-')
        pending=parse(blank, companion().replace(b'6.81',b'-'))
        self.assertEqual(pending['status'], 'PENDING')
        self.assertFalse(any(b['display_time_s'] is not None for b in pending['boats']))

    def test_st_and_prior_results_in_companion_do_not_leak_into_original_feature_schema(self):
        rows=companion().decode().splitlines()
        cells=rows[2].split('\t');cells[7:10]=['1R','3','２着'];rows[2]='\t'.join(cells)
        tokens=rows[8].split('\t');tokens[2]='F';rows[8]='\t'.join(tokens)
        result=parse(second=('\n'.join(rows)+'\n').encode())
        self.assertNotIn('actual_st', result['boats'][0])
        self.assertNotIn('finish', result['boats'][0])
        self.assertNotIn('exhibition_st', result['boats'][0])

    def test_unicode_name_normalization_and_program_order_preserve_six_lane_join(self):
        race=program();race['boats'].reverse();race['boats'][-1]['name']=' 選 手１ '
        result=parse(race=race)
        self.assertEqual([boat['lane'] for boat in result['boats']],list(range(1,7)))
        self.assertEqual(result['boats'][0]['racer_registration_id'],'4101')

    def test_source_urls_require_exact_day_venue_race_host_and_padded_race_number(self):
        good=endpoint('20261015-14-05','original')
        self.assertTrue(good.endswith('bc_oriten_20261015_14_05.txt'))
        for url in (good.replace('20261015','20261014'),good.replace('/14/','/06/'),
                    good.replace('_05.txt','_5.txt'),good+'?cache=0',good+'#x',
                    good.replace('https://','http://'),good.replace('race.boatcast.jp','race.boatcast.jp.evil')):
            with self.subTest(url=url), self.assertRaises(SourceError): parse(source_url=url)
        for race in ('20261015-00-05','20261015-25-05','20260230-14-05','20261015-14-13'):
            with self.subTest(race=race), self.assertRaises(SourceError): endpoint(race,'original')

    def test_shape_labels_lane_and_both_name_sources_are_required(self):
        bad_firsts=(original().replace(b'1\t3',b'1\t2'), original().replace('一　周'.encode(),'未知'.encode()),
                    original().replace(b'6\t',b'5\t'), original().replace('選手1'.encode(),'別選手'.encode()),
                    original()+b'extra\n',original().replace(b'36.42\t5.94',b'36.42'))
        for raw in bad_firsts:
            with self.subTest(raw=raw[:40]), self.assertRaises(SourceError): parse(first=raw)
        for raw in (companion().replace('選手1'.encode(),'選手2'.encode(),1), companion()[:-20],
                    companion().replace(b'data=',b'unknown'),companion()+b'extra\n'):
            with self.subTest(raw=raw[:40]), self.assertRaises(SourceError): parse(second=raw)

    def test_byte_size_utf8_and_numeric_tokens_fail_closed(self):
        for raw in ('not bytes', b'', b'x'*(1024*1024+1), original().replace(b'36.42',b'NaN',1),
                    original().replace(b'36.42',b'inf',1),original().replace(b'36.42',b'0.00',1),
                    original().replace(b'36.42',b'',1),original().replace(b'36.42',b'-1.00',1),
                    original().replace(b'36.42',b'36.421',1),original()+b'\xff'):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(SourceError): parse(first=raw)

    def test_capture_asof_cutoff_and_invalid_offsets_are_explicit(self):
        for key,value in [('captured_at','2026-10-15T10:16:00+09:00'),
                          ('companion_captured_at','2026-10-14T10:10:00+09:00'),
                          ('captured_at','2026-10-15T10:10:00+09:99'),
                          ('captured_at','2026-10-15T10:10:00')]:
            with self.subTest(key=key,value=value),self.assertRaises(SourceError): parse(**{key:value})
        late=parse(captured_at='2026-10-15T10:30:00+09:00',
                   companion_captured_at='2026-10-15T10:30:00+09:00',now='2026-10-15T10:31:00+09:00')
        self.assertFalse(late['capture_eligible_pre_race'])
        historical=parse(captured_at='2026-10-16T10:30:00+09:00',
                         companion_captured_at='2026-10-16T10:30:00+09:00',now='2026-10-16T10:31:00+09:00')
        self.assertFalse(historical['capture_eligible_pre_race'])

    def test_strict_normalized_validator_rejects_rehashed_forgery_and_unsupported_fields(self):
        result=parse()
        mutations=[lambda r:r.update(body_date_verified=True), lambda r:r.update(status='PENDING'),
                   lambda r:r.update(capture_eligible_pre_race=False),lambda r:r.update(extra=True),
                   lambda r:r['boats'][0].update(display_time_s=True),
                   lambda r:r['boats'][0]['original_times'].update(turn_s=float('inf')),
                   lambda r:r['boats'][0].update(racer_registration_id='4999'),
                   lambda r:r['boats'][0].update(name='別選手'),
                   lambda r:r['boats'][0]['missing_reasons'].update(lap_s='SOURCE_NOT_PUBLISHED'),
                   lambda r:r['sources'][0].update(upstream_published_at=CAPTURE),
                   lambda r:r['sources'][0].update(available_at='2026-10-15T10:09:00+09:00'),
                   lambda r:r['measurement_scope'].update(venue_code='18'),
                   lambda r:r['measurement_scope'].update(definition_status='UNIVERSAL_CALIBRATED')]
        for mutation in mutations:
            bad=deepcopy(result);mutation(bad)
            with self.subTest(mutation=mutation), self.assertRaises((SourceError,ValueError)):
                self.rehash(bad);validate_original_observation(bad, program(), NOW)
        different=program();different['closed_at']='2026-10-15T10:31:00+09:00'
        with self.assertRaises(SourceError): validate_original_observation(result,different,NOW)
        bad=deepcopy(result);bad['boats'][0]['original_times']['lap_s']=37.00
        with self.assertRaises(SourceError):validate_original_observation(bad,program(),NOW)


if __name__=='__main__': unittest.main()
