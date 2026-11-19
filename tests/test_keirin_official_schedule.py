"""Invented official-calendar-shaped markup; no live values or requests."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import importlib
import importlib.util
import json
import unittest
from unittest.mock import patch


schedule = (importlib.import_module('race_ai.keirin_official_schedule')
            if importlib.util.find_spec('race_ai.keirin_official_schedule') else None)
URL = 'https://keirin.jp/sp/raceschedule'
NOW = datetime(2030, 1, 15, 2, tzinfo=timezone.utc)
DAY = '2030-01-15'


def period(start, end):
    weekdays = '月火水木金土日'
    def side(value):
        value = date.fromisoformat(value)
        return value.strftime('%m/%d') + '(' + weekdays[value.weekday()] + ')'
    return side(start) + '～' + side(end)


def meeting(start, end, token='A' * 43):
    return ('<table class="race_tbl white_bg_color chgcolor" '
            'onclick="lnk.formlnk(\'/sp/racelist\',\'' + token + '\')">'
            '<tr><td class="grade pd_l5"><img alt="架空等級"></td>'
            '<td class="kikan">' + period(start, end) + '</td></tr>'
            '<tr><td>INVENTED_PRIVATE_SOURCE_VALUE</td></tr></table>')


def venue(code, rows):
    return ('<div class="btn100p clear-fix"><table class="btn100p"><tbody><tr><td>'
            '<button class="btn linkbtn forceBr" type="button" '
            'onclick="location.href=\'/sp/jyosellinfo?jocd=' + str(code) + '\'">'
            '架空会場</button></td></tr></tbody></table></div>'
            '<div class="dayDataDiv0201"><div>' + ''.join(rows) + '</div></div>')


def page(groups=None, year='2030', month='01'):
    if groups is None:
        groups = [venue(98, [meeting('2030-01-14', '2030-01-16'),
                             meeting('2030-01-20', '2030-01-22', 'B' * 43)]),
                  venue(99, [meeting('2030-01-15', '2030-01-17', 'C' * 43)])]
    return ('<html><body><input type="hidden" id="dispYearData" value="' + year + '">'
            '<input type="hidden" id="dispDayData" value="' + month + '">'
            '<div class="dispoff" id="invented_region">' + ''.join(groups) + '</div>'
            '<input type="hidden" id="fnHdnTouhyouEnc" value="INVENTED_PRIVATE_TOKEN">'
            '</body></html>').encode()


class OfficialCalendarTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(schedule, 'the pure official document adapter is missing')
        return schedule

    def parse(self, body=None, **changes):
        api = self.api()
        body = page() if body is None else body
        args = dict(source_url=URL, body_sha256=sha256(body).hexdigest(),
                    received_at=NOW, now=NOW + timedelta(seconds=1), http_status=200)
        args.update(changes)
        return api.parse_calendar(body, **args)

    def test_only_the_exact_existing_public_document_is_admitted(self):
        api = self.api()
        self.assertEqual(api.admit_official_document(URL), URL)
        for url in (URL + '?day=20300115', URL + '#race', URL + '/',
                    URL.replace('https:', 'http:'), URL.replace('keirin.jp', 'www.keirin.jp'),
                    URL.replace('keirin.jp', 'keirin.jp.attacker.invalid'),
                    'https://user:pass@keirin.jp/sp/raceschedule'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                api.admit_official_document(url)

    def test_periods_bind_to_explicit_adjacent_venue_headers(self):
        parsed = self.parse()
        self.assertEqual(parsed['displayed_month'], '2030-01')
        self.assertEqual(parsed['venue_codes'], [98, 99])
        self.assertEqual(len(parsed['meetings']), 3)
        first = parsed['meetings'][0]
        self.assertEqual((first['venue_code'], first['start_date_jst'], first['end_date_jst']),
                         (98, '2030-01-14', '2030-01-16'))
        self.assertEqual(len(first['navigation_reference_sha256']), 64)
        self.assertEqual(first['navigation_kind'], 'PUBLISHED_RACELIST_FORM_NOT_FOLLOWED')
        self.assertFalse(first['navigation_method_verified'])
        self.assertFalse(parsed['upstream_publication_time_verified'])

    def test_existing_day_roster_projection_stays_held_without_individual_races(self):
        api = self.api()
        out = api.project_day(self.parse(), event_day=DAY)
        self.assertEqual(out['target_day_roster_schema'], 'RACE_AI_KEIRIN_NON_RAKUTEN_OWNER_DAY_ROSTER_V1')
        self.assertEqual(out['calendar_venue_candidate_count'], 2)
        self.assertEqual(out['calendar_meeting_candidate_count'], 2)
        self.assertIsNone(out['day_roster_manifest'])
        self.assertFalse(out['day_roster_manifest_ready'])
        self.assertIsNone(out['races'])
        self.assertIsNone(out['race_count'])
        self.assertIsNone(out['source_day_schedule_race_count'])
        self.assertEqual(out['state'], 'HOLD_CALENDAR_ONLY_NO_INDIVIDUAL_RACE_IDENTITIES')
        for key in ('complete_national_coverage_verified', 'official_cutoffs_verified',
                    'model_features_available', 'full_347_437_audit_verified',
                    'actual_four_model_forecast_saved', 'provider_machine_rights_independently_verified'):
            self.assertIs(out[key], False)
        self.assertEqual(out['new_pre_race_inputs'], 0)

    def test_no_calendar_candidate_does_not_prove_a_zero_race_day(self):
        api = self.api()
        out = api.project_day(self.parse(), event_day='2030-01-31')
        self.assertEqual(out['calendar_meeting_candidate_count'], 0)
        self.assertEqual(out['calendar_venue_candidate_count'], 0)
        self.assertIsNone(out['race_count'])
        self.assertFalse(out['complete_national_coverage_verified'])
        self.assertIsNone(out['day_roster_manifest'])

    def test_byte_identity_http_status_and_actual_receive_clock_are_required(self):
        self.api()
        for changes in ({'body_sha256':'f' * 64}, {'http_status':403}, {'http_status':429},
                        {'http_status':True}, {'received_at':NOW.replace(tzinfo=None)},
                        {'received_at':NOW + timedelta(seconds=2)}, {'now':NOW.replace(tzinfo=None)},
                        {'received_at':'2030-01-15T02:00:00Z'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.parse(**changes)
        with self.assertRaises(ValueError):
            self.parse(b'\xff')

    def test_explicit_weekdays_month_and_year_boundary_are_not_guessed(self):
        api = self.api()
        body = page([venue(98, [meeting('2030-12-31', '2031-01-02')])], month='12')
        parsed = self.parse(body)
        row = parsed['meetings'][0]
        self.assertEqual((row['start_date_jst'], row['end_date_jst']), ('2030-12-31', '2031-01-02'))
        self.assertEqual(api.project_day(parsed, event_day='2030-12-31')['calendar_venue_candidate_count'], 1)
        with self.assertRaises(ValueError):
            self.parse(page().replace(period('2030-01-14', '2030-01-16').encode(), b'01/14(\xe6\x97\xa5)~01/16(\xe6\x9c\xa8)'))
        with self.assertRaises(ValueError):
            api.project_day(self.parse(), event_day='2030-02-01')

    def test_unbound_headers_foreign_navigation_and_unknown_markup_are_refused(self):
        self.api()
        for body in (page().replace(b'class="btn100p clear-fix"', b'class="unknown"', 1),
                     page().replace(b'class="btn100p clear-fix"', b'class', 1),
                     page().replace(b'id="dispDayData" value="01"', b'id="dispDayData" value', 1),
                     page().replace(b'/sp/jyosellinfo?jocd=98', b'/sp/private?jocd=98', 1),
                     page().replace(b'/sp/racelist', b'/private/login', 1),
                     page().replace(b'class="kikan"', b'class="unknown"', 1),
                     page().replace(b"'" + b'A' * 43 + b"'", b"'bad&value'", 1)):
            with self.subTest(body_sha=sha256(body).hexdigest()), self.assertRaises(ValueError):
                self.parse(body)

    def test_duplicate_or_incomplete_rows_are_not_silently_dropped(self):
        self.api()
        for body in (page().replace(b'id="dispYearData"', b'id="dispYearData" id="duplicate"', 1),
                     page().replace(b'</body>', b'<input id="dispYearData" value="2031"></body>'),
                     page([venue(98, [meeting('2030-01-14', '2030-01-16')]),
                           venue(98, [meeting('2030-01-20', '2030-01-22', 'B' * 43)])]),
                     page([venue(98, [meeting('2030-01-14', '2030-01-16'),
                                      meeting('2030-01-20', '2030-01-22')])])):
            with self.subTest(body_sha=sha256(body).hexdigest()), self.assertRaises(ValueError):
                self.parse(body)

    def test_safe_counts_never_export_urls_opaque_values_or_source_text(self):
        api = self.api()
        out = api.project_day(self.parse(), event_day=DAY)
        safe = api.safe_summary(out)
        self.assertEqual(safe['calendar_meetings_observed'], 3)
        self.assertEqual(safe['calendar_venue_candidates'], 2)
        self.assertIsNone(safe['individual_race_count'])
        encoded = json.dumps(safe)
        for private in (URL, 'A' * 43, 'INVENTED_PRIVATE_TOKEN', 'INVENTED_PRIVATE_SOURCE_VALUE', '架空会場'):
            self.assertNotIn(private, encoded)
        forged = deepcopy(out);forged['calendar_venue_candidate_count'] = True
        with self.assertRaises(ValueError):
            api.safe_summary(forged)

    def test_resource_and_challenge_documents_stop_without_network(self):
        api = self.api()
        for body in (b'', b'x' * (api.MAX_HTML_BYTES + 1), b'<html>captcha or login</html>',
                     b'<div>' * 65 + page() + b'</div>' * 65):
            with self.subTest(size=len(body)), self.assertRaises(ValueError):
                self.parse(body)
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
            result = api.project_day(self.parse(), event_day=DAY)
        self.assertEqual(result['provider_http_requests'], 0)


if __name__ == '__main__':
    unittest.main()
