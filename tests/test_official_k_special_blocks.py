"""Invented K text: explicit missing-course late starts and cancellation blocks."""
import hashlib
import unittest

from race_ai.teiai_official_reconciliation import official_day


def packet(*, late=False, extra=''):
    lines=['STARTK','01KBGN','2030/01/01',' 1R TEST H1800m',' 逃げ']
    for lane in range(1,7):
        if late and lane==6:
            lines.append(' L0 6 4006 TEST 11 22 6.80 L . . .')
        else:
            lines.append(f' {lane:02} {lane} {4000+lane} TEST 11 22 6.80 {lane} 0.12 1.50.0')
    lines.extend(['01KEND',extra,'ENDK'])
    return '\n'.join(lines).encode('cp932')


class OfficialSpecialBlocksTests(unittest.TestCase):
    def test_daily_date_is_not_invented_as_actual_race_start_time(self):
        rows=official_day(packet(),day='2030-01-01')['rows']
        self.assertTrue(all(row['race_at'] is None for row in rows))

    def test_four_digit_payout_is_not_misread_as_result_registration(self):
        raw=packet().replace(b'01KEND','単勝 1 1200\n複勝 2 1400\n01KEND'.encode('cp932'))
        rows=official_day(raw,day='2030-01-01')['rows']
        self.assertEqual([r['result_code'] for r in rows],['01','02','03','04','05','06'])

    def test_full_daily_document_requires_exact_end_marker(self):
        for raw in (packet().replace(b'ENDK',b''),packet()+b'\nTRAILING',packet().replace(b'01KEND',b'02KEND')):
            with self.assertRaises(ValueError):official_day(raw,day='2030-01-01')

    def test_duplicate_or_invalid_empty_venue_is_not_silently_ignored(self):
        for venue in ('01','25'):
            extra=venue+'KBGN\n2030/01/01\n[払戻金]\n'+'\n'.join(f'{n}R' for n in range(1,13))+'\n'+venue+'KEND'
            with self.assertRaises(ValueError):official_day(packet(extra=extra),day='2030-01-01')

    def test_explicit_blank_twelve_race_payout_table_is_unreported_not_cancelled(self):
        extra='02KBGN\n2030/01/01\n[払戻金]\n'+'\n'.join(f'{n}R   ' for n in range(1,13))+'\n02KEND'
        result=official_day(packet(extra=extra),day='2030-01-01')
        self.assertEqual(result['unreported_venues'],['02'])
        self.assertEqual(result['cancelled_races'],[])
        self.assertEqual(len(result['rows']),6)

    def test_printed_s_timing_is_preserved_without_treating_it_as_ok(self):
        raw=packet(late=True).replace(b'L0 6 4006 TEST 11 22 6.80 L . . .',b'S1 6 4006 TEST 11 22 6.80 6 S0.20 . .')
        row=next(r for r in official_day(raw,day='2030-01-01')['rows'] if r['lane']==6)
        self.assertEqual((row['course'],row['st_status'],row['st_raw'],row['result_code']),(6,'S','S0.20','S1'))
        self.assertIsNone(row['st']);self.assertIsNone(row['finish'])

    def test_printed_zero_course_is_unknown_not_lane_or_course_zero(self):
        raw=packet(late=True).replace(b'L0 6 4006 TEST 11 22 6.80 L . . .',b'L0 6 4006 TEST 11 22 6.80 0 L0.00 . .')
        row=next(r for r in official_day(raw,day='2030-01-01')['rows'] if r['lane']==6)
        self.assertIsNone(row['course']);self.assertEqual(row['st_raw'],'L0.00')

    def test_explicit_not_yet_published_venue_is_not_a_no_race_claim(self):
        extra='02KBGN\nボートレース戸田\nデータは、この場の全レース終了後に登録されます。\n02KEND'
        result=official_day(packet(extra=extra),day='2030-01-01')
        self.assertEqual(len(result['rows']),6)
        self.assertEqual(result['unpublished_venues'],['02'])
        self.assertEqual(result['cancelled_races'],[])

    def test_large_flying_timing_is_preserved_raw_and_excluded_from_ok_st(self):
        raw=packet(late=True).replace(b'L0 6 4006 TEST 11 22 6.80 L . . .',b'F 6 4006 TEST 11 22 6.80 6 F1.23 . .')
        row=next(r for r in official_day(raw,day='2030-01-01')['rows'] if r['lane']==6)
        self.assertEqual((row['course'],row['st_status'],row['st_raw']),(6,'F','F1.23'))
        self.assertIsNone(row['st']);self.assertIsNone(row['finish'])

    def test_late_numeric_over_one_second_and_l1_preserve_actual_course(self):
        for code,timing in (('L0','L1.34'),('L1','L9.99')):
            raw=packet(late=True).replace(b'L0 6 4006 TEST 11 22 6.80 L . . .',f'{code} 6 4006 TEST 11 22 6.80 6 {timing} . .'.encode())
            with self.subTest(code=code):
                row=next(r for r in official_day(raw,day='2030-01-01')['rows'] if r['lane']==6)
                self.assertEqual((row['course'],row['st_status'],row['st_raw'],row['result_code']),(6,'L',timing,code))
                self.assertIsNone(row['st']);self.assertIsNone(row['finish'])

    def test_l1_without_course_is_not_assigned_its_lane(self):
        raw=packet(late=True).replace(b'L0 6',b'L1 6')
        row=next(r for r in official_day(raw,day='2030-01-01')['rows'] if r['lane']==6)
        self.assertEqual(row['result_code'],'L1');self.assertIsNone(row['course'])

    def test_explicit_l0_without_course_stays_unknown_and_preserves_raw_hash(self):
        raw=packet(late=True)
        result=official_day(raw,day='2030-01-01')
        self.assertEqual(result['source_sha256'],hashlib.sha256(raw).hexdigest())
        row=next(r for r in result['rows'] if r['lane']==6)
        self.assertEqual(len(result['rows']),6)
        self.assertEqual((row['racer_id'],row['result_code'],row['st_status']),('4006','L0','L'))
        self.assertIsNone(row['course']);self.assertIsNone(row['st']);self.assertIsNone(row['finish'])

    def test_explicit_cancelled_venue_is_counted_without_inventing_entrants(self):
        extra='02KBGN\n2030/01/01\n 1R 中 止\n 2R 中 止\n02KEND'
        result=official_day(packet(extra=extra),day='2030-01-01')
        self.assertEqual(len(result['rows']),6)
        self.assertEqual(result['cancelled_races'],['20300101-02-01','20300101-02-02'])

    def test_unmarked_empty_or_conflicting_cancellation_is_rejected(self):
        for body in ('2030/01/01','2030/01/01\n 1R 中 止\n 1R 中 止',
                     '2030/01/02\n 1R 中 止','2030/01/01\n 1R 中 止\n 2R 不明',
                     '2030/01/01\n 1R 中 止\n 01 1 4001 TEST 11 22 6.80 1 0.12 1.50.0'):
            with self.subTest(body=body),self.assertRaises(ValueError):
                official_day(packet(extra='02KBGN\n'+body+'\n02KEND'),day='2030-01-01')

    def test_unknown_missing_course_disposition_does_not_get_coerced(self):
        raw=packet(late=True).replace(b'L0 6',b'F 6')
        with self.assertRaises(ValueError):official_day(raw,day='2030-01-01')
