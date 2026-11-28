"""Synthetic boundary checks for private official profile extracts."""
from copy import deepcopy
from datetime import date, timedelta
import unittest

from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_github_origin_evidence as origin
from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_rider_form_evidence as form

from research.chatgpt_dt_r1 import official_personal_history as study
from research.chatgpt_dt_r1.data import input_digest
from research.chatgpt_dt_r1.official_inputs import IDENTITY_NAMESPACE, SCHEMA
from research.chatgpt_dt_r1.policy import digest


DAY = date(2026, 11, 28)
RID = '202611282401'
AT = '2026-11-28T17:45:00+09:00'
CUTOFF = '2026-11-28T18:00:00+09:00'
CAPTURE = '2026-11-28T16:20:00+09:00'
GENERATED = '2026-11-28T16:30:00+09:00'
SEALED = '2026-11-28T16:31:00+09:00'
VERIFIED = '2026-11-28T16:45:00+09:00'
BASELINE, CONDITION, COHORT, PAGE = (c * 64 for c in 'abcd')
SYNTHETIC_COMMIT = 'e' * 40


def result(age, *, status='FINISHED', place=2, field_size=7, suffix='2401'):
    day = DAY - timedelta(days=age)
    return dict(race_id=day.strftime('%Y%m%d') + suffix, race_date=day.isoformat(), status=status,
                place=place, field_size=field_size, published_at=day.isoformat() + 'T20:00:00+09:00',
                source_sha256=PAGE)


def stamp(document, key):
    document[key] = core.digest({k: v for k, v in document.items() if k != key})


def stamp_condition(original):
    condition = original['conditioned']
    condition['condition_supplement_sha256'] = core.digest(original['supplement'])
    stamp(condition, 'sha256')


def fixture():
    carriers = [dict(car=car, athlete_id=str(100000 + car)) for car in range(1, 6)]
    riders = [dict(car=row['car'], official_registration_id=row['athlete_id'],
                   identity_key=digest(dict(namespace=IDENTITY_NAMESPACE, registration=row['athlete_id'])),
                   identity_status='OFFICIAL_REGISTRATION_SOURCE_BOUND', identity_usable=True)
              for row in carriers]
    page = dict(kind='PROGRAM', url='https://keirin.jp/sp/race', bytes_sha256=PAGE, captured_at=CAPTURE)
    snapshot = dict(race_id=RID, published_cutoff_at=CUTOFF, as_of=CAPTURE,
                    cutoff_source=page, riders=carriers)
    original = dict(schema=records.PRE_SCHEMA, race_id=RID, day_jst=DAY.isoformat(), snapshot=snapshot,
        producer_run_id='1', producer_commit=SYNTHETIC_COMMIT, cohort_sha256=COHORT,
        baseline_cipher_sha256=BASELINE, baseline_sealed_at=SEALED,
        condition_state='CONDITIONED_AUTHENTICATED_PRE_CUTOFF',
        conditioned_cipher_sha256=CONDITION, conditioned_sealed_at=SEALED,
        baseline=dict(schema=core.PREDICTION, race_id=RID, published_cutoff_at=CUTOFF,
                      generated_at=GENERATED, source_facts_sha256=core.digest(snapshot)),
        supplement=dict(schema=shadow.SUPPLEMENT_SCHEMA, race_id=RID, source_pages=[page],
            condition_evidence=dict(schema=form.SCHEMA, as_of=CAPTURE, riders=[dict(car=1,
                results=[result(7), result(8), result(30), result(31),
                         result(9, status='FALL_FINISHED'), result(10, status='OTHER_DNF', place=None)],
                comments=[], absences=[])])))
    stamp(original['baseline'], 'prediction_sha256')
    baseline_sha = original['baseline']['prediction_sha256']
    original['conditioned'] = dict(schema=shadow.SCHEMA, race_id=RID, generated_at=GENERATED,
                                  published_cutoff_at=CUTOFF, baseline_source_sha256=core.digest(snapshot),
                                  baseline_prediction_sha256=baseline_sha)
    stamp_condition(original)
    base = dict(schema=origin.SCHEMA, state='GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED', race_id=RID,
                cipher_sha256=BASELINE, official_cutoff_at=CUTOFF, latest_server_evidence_at=VERIFIED,
                minimum_margin_seconds=65, producer_run_id=1, readback_run_id=1,
                producer_commit=SYNTHETIC_COMMIT, readback_commit=SYNTHETIC_COMMIT,
                producer_job_id=2, readback_job_id=3, producer_artifact_id=4, readback_artifact_id=5,
                producer_archive_sha256='a' * 64, readback_archive_sha256='b' * 64)
    stamp(base, 'evidence_sha256')
    form_origin = dict(base, schema='RACE_AI_KEIRIN_CONDITIONED_GITHUB_SERVER_ORIGIN_EVIDENCE_V1',
        state='GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED', cipher_sha256=CONDITION,
        baseline_cipher_sha256=BASELINE, baseline_prediction_sha256=baseline_sha, cohort_sha256=COHORT,
        baseline_origin_evidence_sha256=base['evidence_sha256'], plaintext_parent_linkage_verified=False)
    stamp(form_origin, 'evidence_sha256')
    original['origin_receipts'] = dict(baseline_origin=base, condition_origin=form_origin)
    target = dict(race_id=RID, day=DAY.isoformat(), venue_code='24', cohort='prospective',
                  cutoff_at=CUTOFF, published_cutoff_at=CUTOFF, context_as_of=AT,
                  available_at=CAPTURE, source_available_at=CAPTURE, source_sha256=PAGE,
                  source_projection_schema=SCHEMA, field_size=5, field_supported=True,
                  identity_scope=IDENTITY_NAMESPACE, riders=riders)
    target['input_sha256'] = input_digest(target)
    return original, target


class OfficialPersonalHistoryTests(unittest.TestCase):
    def test_closed_window_normal_finishes_only_and_private_minimal_projection(self):
        original, target = fixture()
        before = deepcopy(original)
        packet = study.profile_finishes(original, target, prediction_at=AT)
        self.assertEqual(original, before)
        self.assertEqual(set(packet), {'policy', 'status', 'events', 'proof_sha256'})
        self.assertEqual(packet['status'], 'READY')
        self.assertEqual([row['race_id'] for row in packet['events']], ['202610292401', '202611202401'])
        for event in packet['events']:
            self.assertEqual(set(event), {'identity_key', 'race_id', 'published_at', 'rank',
                                          'field_size', 'source_sha256'})
            self.assertEqual(event['identity_key'], target['riders'][0]['identity_key'])
        self.assertRegex(packet['proof_sha256'], r'^[0-9a-f]{64}$')

    def test_safe_status_for_absent_and_late_sources(self):
        original, target = fixture()
        original.update(condition_state='NO_CONDITIONED_ORIGINAL', conditioned=None, supplement=None,
                        conditioned_cipher_sha256=None, conditioned_sealed_at=None)
        original['origin_receipts']['condition_origin'] = None
        absent = study.profile_finishes(original, target, prediction_at=AT)
        self.assertEqual((absent['status'], absent['events']), ('NO_AUTHENTICATED_PROFILE', []))
        original, target = fixture()
        earlier = '2026-11-28T16:44:59+09:00'
        target['context_as_of'] = earlier
        late = study.profile_finishes(original, target, prediction_at=earlier)
        self.assertEqual((late['status'], late['events']), ('PROFILE_NOT_AVAILABLE_AT_PREDICTION', []))

    def test_registration_cannot_be_swapped_even_with_matching_rehashed_target(self):
        original, target = fixture()
        left, right = target['riders'][:2]
        for key in ('official_registration_id', 'identity_key'):
            left[key], right[key] = right[key], left[key]
        target['input_sha256'] = input_digest(target)
        with self.assertRaises(study.ProfileHistoryError):
            study.profile_finishes(original, target, prediction_at=AT)

    def test_verified_but_no_in_window_finishes_still_has_a_proof(self):
        original, target = fixture()
        original['supplement']['condition_evidence']['riders'][0]['results'] = [result(7), result(31)]
        stamp_condition(original)
        packet = study.profile_finishes(original, target, prediction_at=AT)
        self.assertEqual((packet['status'], packet['events']), ('NO_ELIGIBLE_FINISHES', []))
        self.assertRegex(packet['proof_sha256'], r'^[0-9a-f]{64}$')

    def test_multiple_individuals_in_same_prior_race_keep_distinct_identity(self):
        original, target = fixture()
        second = dict(car=2, results=[result(8, place=4)], comments=[], absences=[])
        original['supplement']['condition_evidence']['riders'].append(second)
        stamp_condition(original)
        packet = study.profile_finishes(original, target, prediction_at=AT)
        events = {entry['identity_key']: entry['rank'] for entry in packet['events']
                  if entry['race_id'] == '202611202401'}
        self.assertEqual(events, {target['riders'][0]['identity_key']: 2,
                                  target['riders'][1]['identity_key']: 4})
        second['results'][0]['field_size'] = 8
        stamp_condition(original)
        with self.assertRaises(study.ProfileHistoryError):
            study.profile_finishes(original, target, prediction_at=AT)

    def test_prediction_later_than_t15_or_wrong_context_is_rejected(self):
        original, target = fixture()
        for later in ('2026-11-28T17:45:01+09:00', '2026-11-28T17:44:59+09:00'):
            with self.subTest(later=later), self.assertRaises(study.ProfileHistoryError):
                study.profile_finishes(original, target, prediction_at=later)

    def test_forged_parent_receipt_or_unbound_profile_change_fails_closed(self):
        original, target = fixture()
        proof = original['origin_receipts']['condition_origin']
        proof['baseline_origin_evidence_sha256'] = 'f' * 64
        stamp(proof, 'evidence_sha256')
        with self.assertRaises(study.ProfileHistoryError):
            study.profile_finishes(original, target, prediction_at=AT)
        original, target = fixture()
        original['supplement']['condition_evidence']['riders'][0]['results'][1]['place'] = 1
        with self.assertRaises(study.ProfileHistoryError):
            study.profile_finishes(original, target, prediction_at=AT)

    def test_duplicate_same_day_future_missing_source_and_invalid_race_fail_closed(self):
        edits = (result(8), result(0, suffix='2402'), result(-1),
                 dict(result(11), source_sha256='e' * 64), result(11, suffix='2499'),
                 dict(result(11), published_at='2026-11-28T17:00:00+09:00'))
        for appended in edits:
            with self.subTest(appended=appended['race_id']):
                original, target = fixture()
                original['supplement']['condition_evidence']['riders'][0]['results'].append(appended)
                stamp_condition(original)
                with self.assertRaises(study.ProfileHistoryError):
                    study.profile_finishes(original, target, prediction_at=AT)


if __name__ == '__main__':
    unittest.main()
