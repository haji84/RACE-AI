"""Registry identity requires separately bound entrant IDs, never slot fallbacks."""
from copy import deepcopy
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.autorace_personal_baseline import predict_personal
from race_ai.existing_model_dispatch import InputMissing
from race_ai.existing_special_parameter_adapters import predict as native_predict
from tests.test_autorace_personal_baseline import sample
from tests.test_existing_special_parameter_adapters import seller_payload, AUTO, SELLER


ROSTER_SCHEMA = 'RACE_AI_REGISTERED_NATIVE_ROSTER_V1'


def bound_payload(model_id):
    if model_id == AUTO:
        payload = dict(snapshot=sample(count=3), scope='SYNTHETIC_ONLY')
        race = payload['snapshot']['race']; race_id = race['race_id']; at = race['as_of_at']
        native = payload['snapshot']; source = race['source_url']; captured = race['source_captured_at']
        roster = {str(p['car_no']): 'fictional-driver-'+str(6000+p['car_no']) for p in native['drivers']}
        sport = 'autorace'; source_sha = digest(native)
        evidence = [dict(source_ref=source, source_rights_ref='fictional-program',
                         source_sha256=source_sha, captured_at=captured)]
    else:
        payload = seller_payload(count=1)
        payload.update(scope='SYNTHETIC_ONLY', race_id='203001151801',
                       as_of='2030-01-15T06:30:00+09:00', cutoff_at='2030-01-15T10:00:00+09:00')
        race_id = payload['race_id']; at = payload['as_of']; captured = at
        native = {key:payload[key] for key in ('cards', 'waku', 'day')}
        roster = {str(i): str(4000+i) for i in range(1, 7)}
        sport = 'boat'; source = 'https://example.test/fictional-program'; source_sha = digest(payload['cards'])
        evidence = [dict(source_ref=source, source_rights_ref='fictional-program',
                         source_sha256=source_sha, captured_at=captured),
                    dict(source_ref='https://example.test/fictional-course', source_rights_ref='fictional-course',
                         source_sha256=digest(payload['waku']), captured_at=captured)]
    payload['source_evidence'] = evidence
    payload['registered_roster'] = dict(schema=ROSTER_SCHEMA, sport=sport, race_id=race_id, as_of=at,
        roster=roster, native_input_sha256=digest(native), source_ref=source,
        source_rights_ref='fictional-program', source_sha256=source_sha, captured_at=captured)
    return payload, sport, at


class RegisteredNativeRosterTests(unittest.TestCase):
    def test_missing_roster_is_explicitly_unavailable_instead_of_fabricated_slot_ids(self):
        for mid in (SELLER, AUTO):
            payload, sport, at = bound_payload(mid); payload.pop('registered_roster')
            with self.subTest(model=mid), self.assertRaisesRegex(InputMissing, 'REGISTERED_ROSTER_INPUT_MISSING'):
                registry.identity(mid, sport, payload)

    def test_registered_ids_bind_identity_without_changing_native_default_prediction(self):
        for mid in (SELLER, AUTO):
            payload, sport, at = bound_payload(mid); before = deepcopy(payload)
            info = registry.identity(mid, sport, payload)
            self.assertEqual(info['roster'], payload['registered_roster']['roster'])
            self.assertNotEqual(info['roster'], {k:k for k in info['roster']})
            native = native_predict(mid, payload, None, at=at)
            self.assertEqual(registry.predict(mid, sport, payload, None, at=at), native)
            if mid == AUTO:
                self.assertEqual(native, predict_personal(payload['snapshot'], generated_at=at))
            self.assertEqual(payload, before)

    def test_roster_source_hash_race_clock_and_native_input_are_bound_independently(self):
        mutations = (
            lambda p:p['registered_roster'].update(native_input_sha256='f'*64),
            lambda p:p['registered_roster'].update(source_sha256='f'*64),
            lambda p:p['registered_roster'].update(race_id='unrelated-race'),
            lambda p:p['registered_roster'].update(captured_at='2031-01-01T00:00:00+09:00'),
            lambda p:p['registered_roster'].update(source_ref='https://example.test/unbound-source'),
            lambda p:p.update(source_evidence=[]),
        )
        for mid in (SELLER, AUTO):
            for mutation in mutations:
                payload, sport, at = bound_payload(mid); mutation(payload)
                with self.subTest(model=mid, mutation=mutation), self.assertRaises(ValueError):
                    registry.validate_payload(mid, sport, payload, at=at)

    def test_duplicate_or_missing_entrant_ids_and_native_slot_number_fallback_are_rejected(self):
        for mid in (SELLER, AUTO):
            payload, sport, _ = bound_payload(mid)
            original = payload['registered_roster']['roster']
            invalid = [dict(original, **{'1': original['2']}), {k:v for k,v in original.items() if k != '1'},
                       dict(original, **{'9':'9009'}), {k:k for k in original},
                       dict(original, **{'1': True}), dict(original, **{'1': '0000'})]
            for roster in invalid:
                supplied = deepcopy(payload); supplied['registered_roster']['roster'] = roster
                with self.subTest(model=mid, roster=roster), self.assertRaises(ValueError):
                    registry.identity(mid, sport, supplied)

    def test_research_roster_needs_its_bound_source_admission(self):
        for mid in (SELLER, AUTO):
            payload, sport, at = bound_payload(mid); payload['scope'] = 'OPERATOR_SUPPLIED_RESEARCH'
            self.assertEqual(registry.validate_payload(mid, sport, payload, at=at, allow_source=lambda *_:True)['roster'],
                             payload['registered_roster']['roster'])
            with self.assertRaises(ValueError):
                registry.validate_payload(mid, sport, payload, at=at, allow_source=lambda *_:False)

    def test_auto_envelope_uses_native_car_slots_and_rejects_out_of_range_or_unhashable_slots(self):
        payload, sport, at = bound_payload(AUTO)
        for row, number in zip(payload['snapshot']['drivers'], (1, 4, 8)):
            row['car_no'] = number
        envelope = payload['registered_roster']
        envelope['roster'] = {'1':'fictional-driver-alpha', '4':'fictional-driver-beta', '8':'fictional-driver-gamma'}
        envelope['native_input_sha256'] = digest(payload['snapshot'])
        self.assertEqual(registry.identity(AUTO, sport, payload)['roster'], envelope['roster'])
        for number in (9, []):
            invalid = deepcopy(payload); invalid['snapshot']['drivers'][0]['car_no'] = number
            invalid['registered_roster']['native_input_sha256'] = digest(invalid['snapshot'])
            invalid['registered_roster']['roster'][str(number)] = invalid['registered_roster']['roster'].pop('1')
            with self.subTest(number=number), self.assertRaises(ValueError):
                registry.identity(AUTO, sport, invalid)


if __name__ == '__main__':
    unittest.main()
