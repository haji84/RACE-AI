"""Invented bounded source evidence; never prediction admission."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import json
import unittest

from race_ai import keirin_official_nationwide_extension as extension
from race_ai import keirin_official_nationwide_sources as sources
from tests.test_keirin_official_sp_receipt import AT, DAY, calendar_receipt, list_data, detail_data, html


class SourceSession:
    def __init__(self, details, deny=False):
        self.details, self.deny = details, deny
        self.halted = self.provider_denied = False
        self.count = 0
        self.calls = []
        self.cache = {}

    def fetch(self, url, fields=None, referer=None):
        key = (url, tuple(fields or []))
        if key in self.cache:
            return self.cache[key]
        if self.halted:
            raise ValueError('STOPPED')
        self.count += 1
        self.calls.append((url, fields))
        if fields:
            if self.deny:
                self.halted = self.provider_denied = True
                raise ValueError('private source error with SECRET')
            number = ord(dict(fields)['encp'][0])-65
            raw = self.details[number]
        else:
            raw = ''.join(sources.LIST_SCRIPTS[url.replace('https://keirin.jp', '')]).encode()
        out = dict(raw_bytes=raw, expected_sha256=sha256(raw).hexdigest(),
                   observed_at=AT.isoformat(), http_status=200, source_url=url)
        self.cache[key] = out
        return out


class ClassEvidenceTests(unittest.TestCase):
    def api(self):
        return importlib.import_module('race_ai.keirin_official_class_evidence')

    def fixture(self, labels=('A級選抜', 'A級選抜', 'A級チャレンジ準決勝'), kind='1'):
        data = list_data()
        rows = data['SJ0301']['kaisaiDayList'][1]['raceProgramList']
        details = {}
        for number, label in enumerate(labels, 1):
            rows[number-1].update(strSyumokuName=label, strRaceLnkKbn=kind)
            detail = detail_data()
            detail['SC0201']['C0201data']['selRaceNo'] = number
            for car, row in enumerate(detail['SJ0315']['sensyuTypeInfo']):
                if label.startswith('ガ'):
                    row['kyuhan'] = 'L1'
                else:
                    row['kyuhan'] = 'A3' if 'チャレンジ' in label else ('A1' if car % 2 else 'A2')
            details[number] = html(detail)
        raw = html(data).replace(b'</body>', (''.join('<script src="'+path+'"></script>'
            for path in sources.LIST_SCRIPTS)+'</body>').encode())
        listed = dict(venue_code=98, raw_bytes=raw, expected_sha256=sha256(raw).hexdigest(),
                      observed_at=AT, http_status=200)
        calendar = calendar_receipt()
        registry = extension.register_day(calendar_receipt=calendar, list_sources=[listed],
            event_day=DAY, now=AT)
        return dict(registry=registry, calendar_receipt=calendar, list_sources=[listed]), details

    def test_unknown_class_is_bound_to_one_published_card_without_prediction(self):
        inventory, details = self.fixture()
        session = SourceSession(details)
        out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory,
            clock=lambda:AT, max_classes=4)
        self.assertEqual(len(out['records']), 2)
        self.assertEqual([r['grades'] for r in out['safe_summary']], [['A1', 'A2'], ['A3']])
        self.assertEqual([r['race_id'] for r in out['safe_summary']], ['203001159801', '203001159803'])
        self.assertTrue(all(r['prediction_admitted'] is False for r in out['safe_summary']))
        self.assertEqual(out['model_generation'], 0)
        public = json.dumps(out['safe_summary'], ensure_ascii=False)
        for private in ('encp', 'SECRET', '架空選手', '<html>', 'BBBBBBBBBB'):
            self.assertNotIn(private, public)
        self.assertEqual(out['records'][0]['detail_source']['raw_bytes'], details[1])
        self.assertEqual(out['safe_summary'][0]['detail_sha256'], sha256(details[1]).hexdigest())

    def test_supported_labels_and_published_results_never_trigger_probe(self):
        for labels, kind in (
                (('S級一般',)*3, '1'),
                (('A級チャレンジ一般', 'A級特選', 'A級チャレンジ選抜'), '1'),
                (('A級一般', 'A級チャレンジ予選', 'A級予選'), '1'),
                (('A級特予選', 'A級準決勝', 'A級初日特選'), '1'),
                (('A級選抜',)*3, '2')):
            inventory, details = self.fixture(labels, kind)
            session = SourceSession(details)
            out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory,
                clock=lambda:AT)
            self.assertEqual(out['records'], [])
            self.assertEqual(session.calls, [])

    def test_official_girls_round_forms_can_be_safely_reported_without_admission(self):
        cases = (
            (('ガールズ予選1', 'ガ予2', 'ガールズ予選1 架空選手'),
             ['ガールズ予選1', 'ガ予2', 'UNRECOGNIZED_CLASS_LABEL']),
            (('ガールズ予選（第１走）', 'ガールズ予選（第２走）', 'ガールズ予選（第９走）'),
             ['ガールズ予選(第1走)', 'ガールズ予選(第2走)', 'UNRECOGNIZED_CLASS_LABEL']),
        )
        for labels, expected in cases:
            with self.subTest(labels=labels):
                inventory, details = self.fixture(labels)
                out = self.api().collect_unknown_class_evidence(session=SourceSession(details),
                                                               inventory=inventory, clock=lambda: AT)
                self.assertEqual([row['class_label'] for row in out['safe_summary']], expected)
                self.assertTrue(all(row['grades'] == ['L1'] for row in out['safe_summary']))
                self.assertTrue(all(row['prediction_admitted'] is False for row in out['safe_summary']))
                self.assertEqual(out['model_generation'], 0)

    def test_denial_stops_remaining_class_evidence_and_never_exposes_exception(self):
        inventory, details = self.fixture()
        session = SourceSession(details, deny=True)
        out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory,
            clock=lambda:AT)
        self.assertEqual(len([r for r in session.calls if r[1]]), 1)
        self.assertEqual(out['records'], [])
        self.assertTrue(out['provider_denied'])
        self.assertNotIn('SECRET', json.dumps(out['safe_summary']))

    def test_soft_deferral_preserves_verified_class_evidence_without_adding_a_failed_sample(self):
        inventory, details = self.fixture()
        session = SourceSession(details)
        fetch = session.fetch

        def defer_later_card(url, fields=None, referer=None):
            if fields and dict(fields)['encp'].startswith('D'):
                raise sources.CaptureBudgetPending('CAPTURE_SOFT_BUDGET_PENDING')
            return fetch(url, fields, referer)

        session.fetch = defer_later_card
        out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory, clock=lambda:AT)
        self.assertEqual([r['race_id'] for r in out['records']], ['203001159801'])
        self.assertEqual([r['race_id'] for r in out['safe_summary']], ['203001159801'])
        self.assertTrue(out['budget_pending'])
        self.assertFalse(out['provider_denied'])
        self.assertFalse(session.halted)

    def test_wrong_race_identity_and_changed_bytes_do_not_become_verified_grade_evidence(self):
        inventory, details = self.fixture(('A級選抜',)*3)
        for mode in ('identity', 'hash'):
            with self.subTest(mode=mode):
                session = SourceSession(deepcopy(details))
                if mode == 'identity':
                    detail = detail_data();detail['SC0201']['C0201data']['selRaceNo'] = 2
                    session.details[1] = html(detail)
                else:
                    original = session.fetch
                    def changed(*args, **kwargs):
                        out = original(*args, **kwargs)
                        if len(args)>1 and args[1]:
                            out = dict(out, expected_sha256='0'*64)
                        return out
                    session.fetch = changed
                out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory,
                    clock=lambda:AT)
                self.assertEqual(out['records'], [])
                self.assertEqual(out['safe_summary'][0]['state'], 'DETAIL_VALIDATION_FAILED')

    def test_maximum_and_missing_future_margin_remain_bounded(self):
        inventory, details = self.fixture()
        for bound in (0, 5, True):
            with self.assertRaises(ValueError):
                self.api().collect_unknown_class_evidence(session=SourceSession(details),
                    inventory=inventory, clock=lambda:AT, max_classes=bound)
        session = SourceSession(details)
        out = self.api().collect_unknown_class_evidence(session=session, inventory=inventory,
            clock=lambda:AT, max_classes=1)
        self.assertEqual(len(out['records']), 1)
        late = self.api().collect_unknown_class_evidence(session=SourceSession(details), inventory=inventory,
            clock=lambda:AT+timedelta(hours=3))
        self.assertEqual(late['records'], [])
        self.assertTrue(all(r['state']=='DETAIL_VALIDATION_FAILED' for r in late['safe_summary']))


if __name__ == '__main__':
    unittest.main()
