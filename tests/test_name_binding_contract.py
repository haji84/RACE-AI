"""Synthetic independent body proofs; these are not live race observations."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import subprocess
import sys
import unittest
from pathlib import Path

from race_ai.official_racelist_adapter import endpoint, parse_official_racelist
from tests.test_official_racelist_adapter import DAY, fixture
from web import race_contract as facts

BASELINE = 'b' * 64
ARCHIVE = 'a' * 64
CAPTURE = datetime(2026, 10, 14, 22, tzinfo=timezone.utc)
GENERATED = CAPTURE + timedelta(seconds=1)
NOW = CAPTURE + timedelta(seconds=4)
PINS = dict(baseline_snapshot_id=BASELINE, b_program_sha256=ARCHIVE)


def body():
    # The independently observed spelling belongs only to this synthetic body.
    return fixture().replace('4001', '4544').replace('選手 1', '松田　大志郎').encode()


def detail(raw=None, captured=CAPTURE):
    return parse_official_racelist(body() if raw is None else raw, day=DAY,
        venue='18', race_no=1, source_url=endpoint(DAY, '18', 1), captured_at=captured.isoformat())


def program():
    return dict(race_id='20261015-18-01', closed_at='2026-10-15T08:03:00+09:00',
        boats=[dict(lane=n, racer_registration_id='4544' if n == 1 else str(4000+n),
            name='松田大志' if n == 1 else f'選手 {n}', national_win_rate=5.25,
            extra={'unchanged': [n]}) for n in range(1, 7)])


def rehash(value):
    value['snapshot_id'] = hashlib.sha256(facts.canonical(
        {key: item for key, item in value.items() if key != 'snapshot_id'})).hexdigest()


class NameBindingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.contract = importlib.import_module('web.name_binding_contract')
        except ModuleNotFoundError:
            cls.contract = None

    def setUp(self):
        self.assertIsNotNone(self.contract, 'standalone registered-name contract must exist')
        self.race = program()

    def build(self, source=None, generated=GENERATED, now=NOW):
        return self.contract.build_name_binding(detail() if source is None else source,
            self.race, **PINS, generated_at=generated, now=now)

    def validate(self, value, now=NOW, **pins):
        return self.contract.validate_name_binding(value, self.race, now=now, **(pins or PINS))

    def receipt(self):
        return dict(schema_version=1, request_id='123456-1', baseline_request_id='123455-1',
            snapshot=self.build(), runner_saved_at=facts.stamp(CAPTURE+timedelta(seconds=2)),
            cloud_saved_at=facts.stamp(CAPTURE+timedelta(seconds=3)), cloud_eligible_pre_race=True,
            **PINS, program_identity_sha256=facts.program_digest(self.race))

    def test_abbreviation_uses_body_registration_and_preserves_b_bytes(self):
        before = facts.canonical(self.race)
        proof = self.build()
        self.assertEqual(proof['bindings'][0], dict(lane=1, racer_registration_id='4544',
            program_name='松田大志', verified_full_name='松田 大志郎', name_relation='VERIFIED_B_ABBREVIATION'))
        self.assertEqual(proof['bindings'][1]['name_relation'], 'EXACT_CANONICAL_NAME')
        self.assertEqual(proof['source']['source_sha256'], hashlib.sha256(body()).hexdigest())
        self.assertEqual(proof['source']['observed_racers'][0],
            dict(lane=1, racer_registration_id='4544', name='松田 大志郎'))
        self.assertEqual(proof['closed_at'], '2026-10-14T23:03:00.000000+00:00')
        self.assertEqual(proof['program_identity_sha256'], facts.program_digest(self.race))
        self.assertEqual(self.validate(proof), proof)
        self.assertEqual(facts.canonical(self.race), before)
        unsigned = {k:v for k,v in proof.items() if k != 'snapshot_id'}
        self.assertEqual(proof['snapshot_id'], hashlib.sha256(facts.canonical(unsigned)).hexdigest())

    def test_whitespace_canonicalizes_only_for_relation_not_observed_or_program_names(self):
        self.race['boats'][0]['name'] = '松田　大志郎'
        proof = self.build()
        self.assertEqual(proof['bindings'][0]['program_name'], '松田　大志郎')
        self.assertEqual(proof['bindings'][0]['verified_full_name'], '松田 大志郎')
        self.assertEqual(proof['bindings'][0]['name_relation'], 'EXACT_CANONICAL_NAME')

    def test_prefix_without_complete_independent_registration_evidence_rejects(self):
        for mutate in (
            lambda d: d.update(status='URL_IDENTITY_VERIFIED'),
            lambda d: d['boats'][0].update(verified_source=False),
            lambda d: d['boats'][0].update(racer_registration_id='4999'),
            lambda d: d['boats'].pop(),
            lambda d: d['boats'][5].update(lane=1),
            lambda d: d['boats'][5].update(racer_registration_id='4544'),
            lambda d: d.update(race_id='20261015-18-02'),
            lambda d: d.update(closed_at='2026-10-15T08:04:00+09:00'),
            lambda d: d.update(date_jst='2026-10-14'),
            lambda d: d.update(venue='17'),
            lambda d: d['boats'][0].update(source_url=endpoint(DAY, '18', 2)),
            lambda d: d['boats'][0].update(captured_at=facts.stamp(GENERATED)),
            lambda d: d['boats'][0].update(race_id='20261015-18-02'),
            lambda d: d['boats'][0].update(closed_at='2026-10-15T08:04:00+09:00')):
            source = detail(); mutate(source)
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.build(source)

    def test_false_suffix_and_other_renames_reject_even_when_rehashed(self):
        proof = self.build()
        for name in ('松田大志朗', '別人 大志郎'):
            changed = copy.deepcopy(proof)
            changed['bindings'][0]['verified_full_name'] = name
            rehash(changed)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(changed)
        for short in ('松田大', '松田大志郎名', '別人大志'):
            self.race['boats'][0]['name'] = short
            with self.subTest(short=short), self.assertRaises(ValueError):
                self.build()

    def test_pinned_baseline_archive_and_unchanged_program_cannot_be_substituted(self):
        proof = self.build()
        for pins in (dict(PINS, baseline_snapshot_id='c'*64), dict(PINS, b_program_sha256='c'*64),
                     dict(PINS, baseline_snapshot_id='B'*64), dict(PINS, b_program_sha256='not-a-hash')):
            with self.subTest(pins=pins), self.assertRaises(ValueError):
                self.validate(proof, **pins)
        for field, value in (('name', '別人'), ('racer_registration_id', '4999'), ('lane', True)):
            self.race = program(); self.race['boats'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(proof)

    def test_exact_snapshot_and_nested_schema_rejects_tampering(self):
        proof = self.build()
        cases = [lambda p:p.update(extra='x'), lambda p:p.pop('capture_eligible_pre_race'),
            lambda p:p.update(schema_version=True), lambda p:p.update(kind='racelist'),
            lambda p:p.update(closed_at=self.race['closed_at']),
            lambda p:p.update(program_identity_sha256='C'*64),
            lambda p:p.update(capture_eligible_pre_race=False),
            lambda p:p['source'].update(extra=True), lambda p:p['source'].pop('parser'),
            lambda p:p['source'].update(parser='other/v1'),
            lambda p:p['source'].update(body_identity_verified=1),
            lambda p:p['source'].update(upstream_published_at=facts.stamp(CAPTURE)),
            lambda p:p['source'].update(source_sha256='A'*64),
            lambda p:p['source'].update(source_url=endpoint(DAY, '18', 1)+'&extra=x'),
            lambda p:p['source']['observed_racers'][0].update(extra=True),
            lambda p:p['source']['observed_racers'][0].update(lane=True),
            lambda p:p['source']['observed_racers'][0].update(racer_registration_id='4999'),
            lambda p:p['source']['observed_racers'].pop(),
            lambda p:p['bindings'][0].update(extra=True),
            lambda p:p['bindings'][0].update(name_relation='EXACT_CANONICAL_NAME'),
            lambda p:p['bindings'][0].update(program_name='松田 大志'),
            lambda p:p['bindings'][5].update(lane=1),
            lambda p:p['bindings'][5].update(racer_registration_id='4544')]
        for index, mutate in enumerate(cases):
            changed = copy.deepcopy(proof); mutate(changed); rehash(changed)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(changed)
        changed = copy.deepcopy(proof); changed['snapshot_id'] = 'c'*64
        with self.assertRaises(ValueError): self.validate(changed)

    def test_invisible_empty_and_unbounded_names_reject(self):
        for name in ('', '　 ', '松田\u200b大志郎', '松田\x00大志郎', '松'*129, '\ud800'):
            source = detail(); source['boats'][0]['name'] = name
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                self.build(source)

    def test_capture_generation_and_asof_clocks_are_ordered_current_day_before_close(self):
        close = facts._time(self.race['closed_at'])
        for captured, generated, now in ((GENERATED, CAPTURE, NOW), (CAPTURE, NOW+timedelta(seconds=1), NOW),
            (CAPTURE, close, close), (close, close, close),
            (CAPTURE-timedelta(days=1), GENERATED, NOW), (CAPTURE, GENERATED, NOW+timedelta(days=1)),
            (CAPTURE, GENERATED.replace(tzinfo=None), NOW)):
            source = detail(); source['first_observed_at'] = captured.isoformat()
            for boat in source['boats']: boat['captured_at'] = captured.isoformat()
            with self.subTest(captured=captured, generated=generated, now=now), self.assertRaises(ValueError):
                self.build(source, generated, now)
        proof = self.build()
        self.assertEqual(self.validate(proof, close+timedelta(minutes=1)), proof)
        for field in ('captured_at', 'available_at'):
            changed = copy.deepcopy(proof); changed['source'][field] = facts.stamp(GENERATED)
            rehash(changed)
            with self.subTest(field=field), self.assertRaises(ValueError): self.validate(changed)

    def test_receipt_requires_real_preclose_runner_cloud_order_and_strict_nonces(self):
        receipt = self.receipt()
        validator = self.contract.validate_name_binding_receipt
        self.assertEqual(validator(receipt, self.race, **PINS, now=NOW), receipt)
        close = facts._time(self.race['closed_at'])
        self.assertEqual(validator(receipt, self.race, **PINS, now=close+timedelta(minutes=1)), receipt)
        changes = [('extra', True), ('schema_version', True), ('request_id', '0-1'),
            ('request_id', '1-0'), ('request_id', '01-1'), ('baseline_request_id', '1-01'),
            ('baseline_request_id', 123), ('cloud_eligible_pre_race', 1),
            ('baseline_snapshot_id', 'c'*64), ('b_program_sha256', 'c'*64),
            ('program_identity_sha256', 'c'*64), ('runner_saved_at', facts.stamp(CAPTURE)),
            ('cloud_saved_at', facts.stamp(GENERATED)), ('runner_saved_at', facts.stamp(close)),
            ('cloud_saved_at', facts.stamp(close)), ('cloud_saved_at', facts.stamp(NOW+timedelta(seconds=1))),
            ('runner_saved_at', facts.stamp(CAPTURE-timedelta(days=1))),
            ('cloud_saved_at', facts.stamp(CAPTURE+timedelta(days=1)))]
        for field, value in changes:
            changed = copy.deepcopy(receipt); changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validator(changed, self.race, **PINS, now=NOW)
        with self.assertRaises(ValueError): validator(receipt, self.race, **PINS, now=NOW+timedelta(days=1))

    def test_explicit_projection_is_a_deep_copy_without_mutating_frozen_inputs(self):
        receipt = self.receipt(); before = facts.canonical([self.race, receipt])
        projected = self.contract.project_name_bound_program(receipt['snapshot'], self.race, **PINS, now=NOW)
        self.assertEqual(projected['boats'][0]['name'], '松田 大志郎')
        self.assertEqual(projected['boats'][0]['racer_registration_id'], '4544')
        projected['boats'][0]['extra']['unchanged'].append(99)
        self.assertEqual(facts.canonical([self.race, receipt]), before)

    def test_contract_imports_under_the_standalone_web_root(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', 'import name_binding_contract'],
            cwd=Path(__file__).resolve().parents[1]/'web', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
