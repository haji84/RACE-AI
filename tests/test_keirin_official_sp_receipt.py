"""Invented fixtures only. Boolean assertions never dump source bytes."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import importlib
import importlib.util
import json
import unittest

from tests.test_keirin_official_schedule import page, venue, meeting

MODULE = 'race_ai.keirin_official_sp_receipt'
DAY = '2030-01-15'
AT = datetime(2030, 1, 15, 2, tzinfo=timezone.utc)


def calendar_receipt():
    raw = page([venue(98, [meeting('2030-01-14', '2030-01-16')])])
    return dict(raw_bytes=raw, expected_sha256=sha256(raw).hexdigest(), observed_at=AT)


def header(day='2030/01/15'):
    return dict(joName='架空会場', txtEventDate=day, selRaceNo=1,
                aftBetDate='203001151247', aftBetTime='12:47',
                aftStartTime='12:50', bfrBetTime='12:45', bfrStartTime='12:48',
                flgRaceCancel=False)


def list_data():
    rows = [dict(strRaceNo=str(n), strSyumokuName='架空区分', strArrow='',
                 strArrowName='', strRaceLnk='/sp/race',
                 strRaceLnkPrm=chr(65+n)*43, strRaceLnkKbn='1', strColorClass='')
            for n in range(1, 4)]
    return {'SC0201': dict(resultCd=0, C0201data=header('2030/01/14')),
            'SJ0301': dict(resultCd=0, kaisaiDayList=[
                dict(strKaisaiNitijName='初日(1/14)', raceProgramList=deepcopy(rows)),
                dict(strKaisaiNitijName='2日目(1/15)', raceProgramList=rows)])}


def detail_data(count=7):
    riders = []
    for car in range(1, count+1):
        riders.append(dict(syaban=str(car), sensyuRegistNo=f'99{car:04d}',
            sensyuName=f'架空選手{car}', huKen='架空県', kyakusitu='架空脚質',
            kyuhan='架空級班', prevKyuhan='架空前級班', heikinTokuten='201.25',
            backCnt='3', nigeCnt='1', makuriCnt='2', sasiCnt='0', markCnt='1',
            syabanBgColorInfo='', syabanCharColorInfo=''))
    riders[1]['ketujyouTuikaHojyu'] = '補充'
    riders[1]['ketujyouTuikaHojyuColorInfo'] = 'invented'
    return {'SC0201': dict(resultCd=0, C0201data=header()),
            'SJ0315': dict(resultCd=0, syusouInfoExistFlg='1', sensyuTypeInfo=riders)}


def html(data):
    return ('<html><body><script>\nvar jsonData = {};\n' + ''.join(
        'jsonData[' + json.dumps(code) + '] = ' + json.dumps(value, ensure_ascii=False)
        + ';\n' for code, value in data.items()) + '</script></body></html>').encode()


class SPReceiptTests(unittest.TestCase):
    def api(self):
        present = importlib.util.find_spec(MODULE) is not None
        self.assertTrue(bool(present), 'SP_PARSER_API_MISSING')
        return importlib.import_module(MODULE)

    def parse(self, kind='detail', data=None, raw=None, **changes):
        api = self.api()
        if raw is None:
            raw = html(data if data is not None else
                       (detail_data() if kind == 'detail' else list_data()))
        args = dict(expected_day=DAY, expected_venue_code=98,
                    observed_at=AT+timedelta(seconds=1), expected_sha256=sha256(raw).hexdigest(),
                    calendar_receipt=calendar_receipt())
        if kind == 'detail':
            args['expected_race_number'] = 1
        args.update(changes)
        return getattr(api, 'parse_race_' + kind)(raw, **args)

    def rejected(self, **changes):
        self.api()
        failed = False
        try:
            self.parse(**changes)
        except ValueError:
            failed = True
        self.assertTrue(bool(failed), 'EXPECTED_FIXED_GUARD_REJECTION')

    def test_list_preserves_real_identities_and_never_uses_other_day_clocks(self):
        result = self.parse('list')
        manifest = result['day_roster_manifest']
        self.assertTrue(bool([row['race_id'] for row in manifest['races']] ==
                             ['203001159801', '203001159802', '203001159803']), 'EXPLICIT_LIST_IDENTITIES')
        self.assertTrue(bool(result['race_count'] == 3 and result['official_cutoffs_verified'] is False
                             and result['header_clocks_admitted'] is False), 'LIST_HAS_NO_CLOCK_ADMISSION')

    def test_detail_preserves_cutoff_start_roster_notes_and_open_scores(self):
        result = self.parse()
        self.assertTrue(bool(result['official_cutoff_at'] == '2030-01-15T12:47:00+09:00'
                             and result['start_at'] == '2030-01-15T12:50:00+09:00'), 'DISTINCT_OFFICIAL_CLOCKS')
        self.assertTrue(bool(len(result['riders']) == 7 and result['riders'][0]['score_raw'] == '201.25'), 'RAW_SCORE_NO_CEILING')
        self.assertTrue(bool(result['riders'][1]['entry_status'] == 'SUPPLEMENTAL'
                             and result['withdrawal_count'] == 0 and result['pr71_cardinality_supported']), 'SUPPLEMENT_IS_NOT_WITHDRAWAL')

    def test_all_outputs_keep_admission_and_execution_holds(self):
        for kind in ('list', 'detail'):
            result = self.parse(kind)
            self.assertTrue(bool(all(result[key] is False for key in
                ('source_admission', 'model_input_admission', 'full_pr71_admission',
                 'all_nationwide_coverage_verified', 'full_active_eligibility_verified'))
                 and result['model_generation'] == result['provider_http_requests'] == 0), 'EXPLICIT_ADMISSION_HOLDS')

    def test_cancelled_and_withdrawn_and_unknown_notes_do_not_establish_eligibility(self):
        for mode in ('cancelled', 'withdrawn', 'unknown'):
            data = detail_data()
            if mode == 'cancelled': data['SC0201']['C0201data']['flgRaceCancel'] = True
            else: data['SJ0315']['sensyuTypeInfo'][0]['ketujyouTuikaHojyu'] = '欠場' if mode == 'withdrawn' else '架空未知状態'
            result = self.parse(data=data)
            self.assertTrue(bool(result['no_published_roster_exclusion_observed'] is False
                                 and result['full_active_eligibility_verified'] is False), 'STATUS_CANNOT_PROMOTE_ELIGIBILITY')

    def test_unknown_score_stays_missing_and_counts_stay_raw(self):
        data = detail_data();data['SJ0315']['sensyuTypeInfo'][0]['heikinTokuten'] = '--'
        result = self.parse(data=data)
        self.assertTrue(bool(result['riders'][0]['score_raw'] is None
                             and result['riders'][0]['statistics_raw']['backCnt'] == '3'
                             and result['missing_model_origins_preserved']), 'NO_GUESSED_SCORE_OR_RATE')

    def test_wrong_day_venue_race_and_calendar_binding_reject(self):
        self.rejected(expected_day='2030-01-16')
        self.rejected(expected_venue_code=99)
        self.rejected(expected_race_number=2)
        data = detail_data();data['SC0201']['C0201data']['joName'] = '別の架空会場'
        self.rejected(data=data)

    def test_wrong_list_day_and_duplicate_day_group_reject(self):
        self.rejected(kind='list', expected_day='2030-01-16')
        data=list_data();data['SJ0301']['kaisaiDayList'].append(deepcopy(data['SJ0301']['kaisaiDayList'][1]))
        self.rejected(kind='list', data=data)

    def test_race_gaps_duplicates_unknown_reference_and_row_types_reject(self):
        for field,value in [('strRaceNo','5'),('strRaceLnk','/sp/login'),
                            ('strRaceLnkPrm','short'),('strRaceLnkKbn','9'),('strRaceNo',True)]:
            data=list_data();data['SJ0301']['kaisaiDayList'][1]['raceProgramList'][1][field]=value
            self.rejected(kind='list', data=data)
        data=list_data();data['SJ0301']['kaisaiDayList'][1]['raceProgramList'][1]['strRaceNo']='1'
        self.rejected(kind='list', data=data)

    def test_duplicate_and_invalid_rider_identity_reject(self):
        for field,value in [('syaban','1'),('sensyuRegistNo','990001'),
                            ('syaban','0'),('sensyuRegistNo','not-an-id'),('sensyuName','')]:
            data=detail_data();data['SJ0315']['sensyuTypeInfo'][1][field]=value
            self.rejected(data=data)

    def test_invalid_clock_date_cancellation_and_score_types_reject(self):
        for field,value in [('aftBetTime','25:47'),('aftStartTime','12:46'),
                            ('aftBetDate','203001141247'),('aftBetDate','203001151246'),
                            ('bfrBetTime','not-a-clock'),('flgRaceCancel','false'),
                            ('selRaceNo',True)]:
            data=detail_data();data['SC0201']['C0201data'][field]=value;self.rejected(data=data)
        for value in ('NaN','Infinity','-1',True):
            data=detail_data();data['SJ0315']['sensyuTypeInfo'][0]['heikinTokuten']=value;self.rejected(data=data)

    def test_roster_availability_and_unknown_row_schema_reject(self):
        for field,value in [('resultCd',1),('syusouInfoExistFlg','0'),('sensyuTypeInfo',[])]:
            data=detail_data();data['SJ0315'][field]=value;self.rejected(data=data)
        data=detail_data();data['SJ0315']['sensyuTypeInfo'][0]['unreviewedField']='invented'
        self.rejected(data=data)

    def test_changed_hash_aware_clock_and_calendar_chronology_reject(self):
        self.rejected(expected_sha256='0'*64)
        self.rejected(observed_at=AT.replace(tzinfo=None))
        self.rejected(observed_at=AT-timedelta(seconds=1))
        receipt=calendar_receipt();receipt['expected_sha256']='0'*64
        self.rejected(calendar_receipt=receipt)

    def test_duplicate_document_duplicate_keys_and_nonfinite_json_reject(self):
        raw=html(detail_data())
        self.rejected(raw=raw.replace(b'</script>', b'jsonData["SC0201"] = {};\n</script>'))
        self.rejected(raw=raw.replace(b'"resultCd": 0', b'"resultCd": 0, "resultCd": 0',1))
        self.rejected(raw=raw.replace(b'"resultCd": 0', b'"resultCd": NaN',1))

    def test_overflowing_json_number_cannot_hide_in_an_unused_field(self):
        raw=html(detail_data()).replace(b'"resultCd": 0', b'"resultCd": 0, "unusedNumeric": 1e999',1)
        self.rejected(raw=raw)

    def test_nested_member_mutation_cannot_override_extracted_json(self):
        raw=html(detail_data()).replace(b'</script>', b'jsonData.SC0201.C0201data = {};\n</script>')
        self.rejected(raw=raw)

    def test_script_with_src_does_not_supply_inline_provider_data(self):
        self.rejected(raw=html(detail_data()).replace(b'<script>',b'<script src="">'))

    def test_body_outside_closed_html_is_not_a_complete_receipt(self):
        raw=html(detail_data()).replace(b'<html><body>',b'<html></html><body>').replace(b'</body></html>',b'</body>')
        self.rejected(raw=raw)

    def test_compound_and_increment_mutations_cannot_change_scope(self):
        for suffix in (' += 1', ' -= 1', ' *= 2', ' /= 2', ' %= 2', ' **= 2',
                       ' <<= 1', ' >>= 1', ' >>>= 1', ' &= 1', ' |= 1', ' ^= 1',
                       ' &&= 1', ' ||= 1', ' ??= 1', '++', '--'):
            extra=('jsonData.SC0201.C0201data.selRaceNo'+suffix+';\n').encode()
            self.rejected(raw=html(detail_data()).replace(b'</script>',extra+b'</script>'))

    def test_second_script_cannot_reset_global_json_namespace(self):
        raw=html(detail_data()).replace(b'</body>',b'<script>jsonData = {};</script></body>')
        self.rejected(raw=raw)

    def test_data_script_after_closed_document_cannot_supply_a_receipt(self):
        original=html(detail_data());raw=b'<html><body></body></html>'+original[original.index(b'<script>'):original.index(b'</script>')+9]
        self.rejected(raw=raw)

    def test_only_literal_routing_declarations_and_comments_are_consumed(self):
        extra=(b'// invented routing literals\nvar currentPath = "";\n'
               b'var displayingId = "SJ0315"; /* invented comment */\n'
               b'var displayingSyoriKbn = 1; var parentFuncId = "FSJ0305";\n')
        raw=html(detail_data()).replace(b'var jsonData = {};',extra+b'var jsonData = [];')
        result=self.parse(raw=raw)
        self.assertTrue(bool(result['race_no']==1 and len(result['riders'])==7
                             and result['source_admission'] is False), 'LITERAL_ROUTING_DOES_NOT_CHANGE_DATA')

    def test_aliases_conditionals_and_unknown_statements_are_not_data(self):
        for extra in (b'var alias = jsonData;\n',b'if (true) {}\n',b'jsonData.push({});\n'):
            self.rejected(raw=html(detail_data()).replace(b'</script>',extra+b'</script>'))

    def test_routing_string_requires_matching_quote_delimiters(self):
        raw=html(detail_data()).replace(b'var jsonData = {};', b'var currentPath = \x27/sp\x22; var jsonData = {};')
        self.rejected(raw=raw)

    def test_every_javascript_line_terminator_ends_single_line_comments(self):
        for label,separator in [('CR','\r'),('LS','\u2028'),('PS','\u2029')]:
            with self.subTest(separator=label):
                extra=('// invented comment'+separator+'jsonData.SC0201.C0201data.selRaceNo += 1;\n').encode()
                self.rejected(raw=html(detail_data()).replace(b'</script>',extra+b'</script>'))

    def test_non_javascript_control_characters_are_not_grammar_whitespace(self):
        original=html(detail_data())
        for label,raw in [('between_statements',original.replace(b'{};',b'{};\x1c',1)),
                          ('namespace_declaration',original.replace(b'var jsonData',b'var\x1cjsonData',1)),
                          ('JSON_assignment',original.replace(b'jsonData[',b'jsonData\xc2\x85[',1))]:
            with self.subTest(position=label):
                self.rejected(raw=raw)

    def test_commented_quoted_dynamic_and_trailing_assignments_cannot_fake_json(self):
        raw=html(detail_data())
        for changed in (raw.replace(b'jsonData["SC0201"]', b'jsonData[documentCode]',1),
                        raw.replace(b'</script>', b'jsonData.SC0201 = {};\n</script>'),
                        raw.replace(b'<script>\n',b'<script>/*\n').replace(b'</script>',b'*/</script>'),
                        raw.replace(b'<script>\n',b'<script>`\n').replace(b'</script>',b'`</script>')):
            self.rejected(raw=changed)

    def test_oversize_truncated_utf8_and_deep_html_reject(self):
        api=self.api();raw=html(detail_data())
        for changed in (b'', b'x'*(api.MAX_HTML_BYTES+1),raw[:-7],raw.replace('架空'.encode(),b'\xff',1),
                        b'<div>'*65+raw+b'</div>'*65):
            self.rejected(raw=changed)

    def test_parser_is_parameterized_for_a_different_date_and_nine_riders(self):
        data=detail_data(9);h=data['SC0201']['C0201data'];h['txtEventDate']='2030/01/16';h['aftBetDate']='203001161247';h['selRaceNo']=3
        result=self.parse(data=data,expected_day='2030-01-16',expected_race_number=3)
        self.assertTrue(bool(result['race_id']=='203001169803' and len(result['riders'])==9
                             and result['pr71_cardinality_supported']), 'PARAMETERIZED_EXPECTATIONS')


if __name__ == '__main__':
    unittest.main()
