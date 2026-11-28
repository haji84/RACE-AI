"""Synthetic checks only, never actual-race evidence."""
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from hashlib import sha256
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import keirin_dt_r1_future_settle as settle
from scripts import keirin_dt_r1_future_shadow as shadow

DAY = '2026-11-28'
RACES = ['202611282401', '202611282402', '202611282403']


def forecast(rid):
    triples = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 3)]
    exactas = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 2)]
    return dict(race_id=rid, day=DAY, status='READY', model_sha256=shadow.MODEL_SHA,
                input_sha256='a'*64, riders=[{'car': car} for car in (1, 2, 3)],
                trifectas=triples, exactas=exactas)


class FutureSettlementTests(unittest.TestCase):
    def entries(self):
        return [dict(slot_sha256=shadow.slot(DAY, rid),
                     state=shadow.READY if i < 2 else 'HOLD',
                     reason=None if i < 2 else 'SAVED_ORIGINAL_MISSING',
                     clocks=dict(seal_started_at=DAY + 'T01:00:00Z', cutoff_at=DAY + 'T01:30:00Z'))
                for i,rid in enumerate(RACES)]

    def test_codex_pair_preserves_all_target_and_same_source_denominators(self):
        first, dt_only, codex_only = RACES
        outcomes = [dict(race_id=rid, day=DAY, result_status='VERIFIED_NORMAL', top3=[1, 2, 3],
                         input_sha256='a' * 64) for rid in RACES]
        dt = {rid: forecast(rid) for rid in (first, dt_only)}
        codex = {rid: forecast(rid) for rid in (first, codex_only)}
        metrics = settle._score_codex_pair(dt, outcomes, codex, {first}, 2, {})
        self.assertEqual(metrics['registered_day'], 3)
        self.assertEqual(metrics['codex_all_targets']['evaluable'], 3)
        self.assertEqual(metrics['codex_all_targets']['predicted_evaluable'], 2)
        self.assertEqual(metrics['same_source_originals'], 1)
        self.assertEqual(metrics['official_scorable_pairs'], 1)
        self.assertEqual(metrics['common']['codex']['trifecta']['1'], 1)
        self.assertEqual(metrics['common']['dt_r1']['trifecta']['1'], 1)
        paired = metrics['paired_one_point']
        self.assertEqual((paired['baseline'], paired['comparison']), ('codex', 'dt_r1'))
        self.assertEqual(paired['trifecta']['paired_races'], 1)
        self.assertEqual(paired['exacta']['difference'], 0.)
        self.assertLess(paired['exacta']['difference_ci95'][0], 0.)
        self.assertGreater(paired['exacta']['difference_ci95'][1], 0.)
        self.assertNotIn('proper_scores', str(metrics))
        self.assertNotIn(first, str(metrics))

    def test_codex_cohort_joins_by_exact_dt_first_batch_before_opening_results(self):
        from research.chatgpt_dt_r1 import codex_future_candidate as candidate
        from scripts import keirin_codex_future_pair_replay as replay

        first, codex_only, _ = RACES
        slot = {rid: shadow.slot(DAY, rid) for rid in RACES}
        metadata = {rid: {'source_version': index} for index, rid in enumerate(RACES)}
        source = SimpleNamespace(day=DAY, head='b' * 40, index={'originals': metadata})
        entry = dict(bindings={'input_sha256': 'a' * 64}, clocks={'cutoff_at': DAY + 'T02:00:00Z'})
        dt_manifest = dict(summary={'reader_run_id': '10'})
        manifest = dict(summary=dict(source_archive_commit=source.head, reader_run_id='11',
            dt_producer_run_id='10', dt_manifest_sha256=sha256(settle.codec._canonical(dt_manifest)).hexdigest()))
        retained = {slot[rid]: dict(manifest=manifest, entry=entry, cipher_path=slot[rid]) for rid in (first, codex_only)}
        dt = {slot[first]: dict(manifest=dt_manifest, entry=entry)}
        seen = []

        def load(_, raw, saved_manifest, saved_source, rid, *args):
            seen.append(rid)
            self.assertIs(saved_manifest, manifest)
            self.assertIs(saved_source, source)
            return dict(forecast(rid), **candidate.model_identity())

        with (patch.object(settle.batch_retention, 'read_retained_forecasts', return_value=retained),
              patch.object(settle, '_load_registry', return_value={'registered_race_ids': RACES}),
              patch.object(candidate, 'load_frozen', return_value=object()),
              patch.object(settle.archive, 'read_blob_bytes', return_value=b'cipher fixture'),
              patch.object(replay, 'replay_codex_original', side_effect=load)):
            score = settle._prepare_codex_pair(work=object(), current=source, private=b'', repo=object(), client=object(),
                slots={value: rid for rid, value in slot.items()}, dt_selected=dt, loaded={source.head: source},
                packet_cache={})
        self.assertEqual(seen, [first, codex_only])
        outcomes = [dict(race_id=rid, day=DAY, result_status='VERIFIED_NORMAL', top3=[1, 2, 3],
                         input_sha256='a' * 64) for rid in RACES]
        metrics = score({rid: forecast(rid) for rid in (first, codex_only)}, outcomes)
        self.assertEqual((metrics['codex_replayed'], metrics['official_scorable_pairs']), (2, 1))

    def test_originals_before_results_and_holds_remain_in_denominator(self):
        events = []
        def load_forecast(entry, rid):
            events.append('forecast')
            if rid == RACES[1]:
                raise ValueError('replay mismatch')
            return forecast(rid)
        def result(rid):
            events.append('result')
            return dict(race_id=rid, day=DAY, top3=[1,2,3], result_status='VERIFIED_NORMAL')
        report = settle._score_registered(RACES, DAY, self.entries(),
            [shadow.slot(DAY,rid) for rid in RACES[:2]], {}, load_forecast, result)
        self.assertEqual(events, ['forecast','forecast','result','result','result'])
        self.assertEqual(report['registered_races'], 3)
        self.assertEqual(report['owner_originals_replayed'], 1)
        self.assertEqual(report['metrics']['evaluable'], 3)
        self.assertEqual(report['metrics']['predicted_evaluable'], 1)
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 1)
        self.assertAlmostEqual(report['metrics']['trifecta']['1']['all_target_rate'], 1/3)
        self.assertEqual(report['metrics']['trifecta']['1']['predicted_rate'], 1)
        self.assertEqual(report['forecast_holds'], {
            'SAVED_ORIGINAL_MISSING': 1, 'FORECAST_REPLAY_UNVERIFIED': 1})
        self.assertNotIn('proper_scores', report['metrics'])
        self.assertEqual(report['pdca'], {
            'fixed_trifecta_points': 4, 'placing_checked': 1, 'flow_checked': 0,
            'grade_counts': {'E': 1}})

    def late_slots(self):
        return {shadow.slot(DAY, rid): 'SERVER_READBACK_AFTER_T15' for rid in RACES[:2]}

    def test_late_reader_and_missing_original_are_distinct_registered_holds(self):
        report = settle._score_registered(RACES, DAY, self.entries(), [], self.late_slots(),
            lambda e,r: self.fail('late forecast opened'),
            lambda r: dict(race_id=r, day=DAY, result_status='MISSING_SAVED_RESULT'))
        self.assertEqual(report['registered_races'], 3)
        self.assertEqual(report['forecast_holds'], {
            'SERVER_READBACK_AFTER_T15': 2, 'SAVED_ORIGINAL_MISSING': 1})
        self.assertEqual(sum(report['forecast_holds'].values()), report['registered_races'])

    def test_nowhere_to_replay_is_distinct_from_missing_official_result(self):
        store = SimpleNamespace(day=DAY, index=dict(originals={RACES[0]: {}}, results={}))
        self.assertEqual(settle._result_row(store, RACES[0], b'', None, None)['result_status'],
                         'MISSING_SAVED_RESULT')
        self.assertEqual(settle._result_row(store, RACES[1], b'', None, None)['result_status'],
                         'NO_SAVED_OFFICIAL_ORIGINAL')

    def test_unverified_latest_revision_never_falls_back(self):
        original = {'original': 1}
        old = {'revision': 1, 'observed_at': DAY + 'T02:00:00Z'}
        latest = {'revision': 2, 'observed_at': DAY + 'T03:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [old, latest]}))
        seen = []

        def replay(saved_store, saved_original, meta, private):
            seen.append(meta)
            raise ValueError('untrusted revision detail')

        with patch.object(settle.records, '_replay_saved_result', side_effect=replay):
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_status'], 'RESULT_REPLAY_UNVERIFIED')
        self.assertEqual(row['result_hold_reason'], 'OFFICIAL_RESULT_REPLAY_FAILED')
        self.assertEqual(seen, [latest])
        self.assertNotIn('top3', row)

    def test_result_replay_reuses_existing_safe_failure_classification(self):
        original = {'original': 1}
        latest = {'observed_at': DAY + 'T03:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [latest]}))
        with patch.object(settle.records, '_replay_saved_result',
                          side_effect=ValueError('OFFICIAL_SP_RECORD_SAVED_RESULT_NOT_REPRODUCIBLE')):
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_hold_reason'], 'SAVED_SCORE_REPLAY_HELD')

    def test_out_of_order_result_revisions_are_held_before_opening_any_result(self):
        original = {'original': 1}
        newer = {'observed_at': DAY + 'T03:00:00Z'}
        older = {'observed_at': DAY + 'T02:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [newer, older]}))
        with patch.object(settle.records, '_replay_saved_result',
                          side_effect=AssertionError('Unordered revisions must not be opened')) as replay:
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_status'], 'RESULT_REPLAY_UNVERIFIED')
        self.assertEqual(row['result_hold_reason'], 'RESULT_REVISION_ORDER_UNVERIFIED')
        replay.assert_not_called()

    def test_official_precutoff_cancellation_is_neutral_but_early_finish_is_held(self):
        rid = RACES[0]
        original = {'cutoff_at': DAY + 'T03:00:00Z'}
        revision = {'observed_at': DAY + 'T02:55:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(originals={rid: original}, results={rid: [revision]}))
        final = dict(race_id=rid, official_cutoff_at=original['cutoff_at'],
                     observed_at=DAY + 'T02:50:00Z')
        for status, refund, expected in (
            ('CANCELLED', 'FULL', 'OFFICIAL_CANCELLED'),
            ('FINAL_NORMAL', 'NONE', 'RESULT_REPLAY_UNVERIFIED'),
        ):
            with self.subTest(status=status), patch.object(settle.records, '_replay_saved_result',
                    return_value=(None, {'official_result': dict(final, status=status, refund_status=refund)}, None)):
                row = settle._result_row(store, rid, b'', original, settle.clock(DAY + 'T02:59:00Z'))
            self.assertEqual(row['result_status'], expected)
            self.assertNotIn('top3', row)

    def test_pending_result_does_not_become_miss(self):
        report = settle._score_registered(RACES, DAY, self.entries(), [], self.late_slots(),
            lambda e,r: self.fail('late forecast opened'),
            lambda r: dict(race_id=r,day=DAY,result_status='MISSING_SAVED_RESULT'))
        self.assertEqual(report['metrics']['evaluable'], 0)
        self.assertIsNone(report['metrics']['trifecta']['1']['all_target_rate'])

    def test_duplicate_or_held_slot_cannot_be_admitted(self):
        one = shadow.slot(DAY,RACES[0])
        for eligible in ([one,one],[shadow.slot(DAY,RACES[2])],['f'*64]):
            with self.subTest(eligible=eligible), self.assertRaisesRegex(ValueError, 'REGISTRY_SLOT_MISMATCH'):
                settle._score_registered(RACES,DAY,self.entries(),eligible,{},
                    lambda e,r:self.fail('invalid forecast opened'),
                    lambda r:self.fail('invalid result opened'))

    def test_wrong_result_identity_stops_scoring(self):
        with self.assertRaisesRegex(ValueError, 'RESULT_IDENTITY'):
            settle._score_registered(RACES,DAY,self.entries(),[],self.late_slots(),
                lambda e,r:self.fail('unexpected forecast'),
                lambda r:dict(race_id='different',day=DAY,result_status='MISSING_SAVED_RESULT'))

    def test_back_study_uses_matched_arms_without_probabilities_or_extra_results(self):
        arms = {}
        def forecast_loader(entry, rid):
            controls = {name: forecast(rid) for name in ('back_mixture', 'direct')}
            if rid == RACES[0]:
                controls['direct']['trifectas'][0]['probability'] = 0.
                controls['direct']['trifectas'][1]['probability'] = 1/3
            arms[rid] = controls
            return forecast(rid)

        def outcome(rid):
            if rid == RACES[1]:
                return dict(race_id=rid, day=DAY, result_status='MISSING_SAVED_RESULT')
            return dict(race_id=rid, day=DAY, result_status='VERIFIED_NORMAL', top3=[1, 2, 3])

        report = settle._score_registered(RACES, DAY, self.entries(),
            [shadow.slot(DAY, rid) for rid in RACES[:2]], {}, forecast_loader, outcome, back_pairs=arms)
        paired = report['metrics']['paired_back']
        self.assertEqual((paired['registered_day'], paired['retained_pairs'], paired['official_scorable_pairs']),
                         (3, 2, 1))
        self.assertEqual(paired['back_leader_observations'], 0)
        self.assertEqual(paired['back_mixture']['trifecta']['1'], 1)
        self.assertEqual(paired['direct']['trifecta']['1'], 0)
        self.assertEqual(paired['direct']['exacta']['1'], 1)
        self.assertEqual(set(paired['direct']), {'trifecta', 'exacta'})
        one_point = paired['paired_one_point']
        self.assertEqual((one_point['baseline'], one_point['comparison']), ('direct', 'back_mixture'))
        self.assertEqual(one_point['trifecta']['paired_races'], 1)
        self.assertEqual(one_point['trifecta']['difference'], 1.)
        self.assertEqual(one_point['exacta']['difference'], 0.)
        self.assertLess(one_point['trifecta']['difference_ci95'][0], 0.)
        self.assertNotIn('probability', str(paired))
        self.assertNotIn(RACES[0], str(paired))

    def test_back_replay_hold_keeps_the_frozen_result(self):
        rid = RACES[0]
        report = settle._score_registered(RACES, DAY, self.entries(), [shadow.slot(DAY, rid)],
            {shadow.slot(DAY, RACES[1]): 'SERVER_READBACK_AFTER_T15'},
            lambda entry, race: forecast(race),
            lambda race: dict(race_id=race, day=DAY, result_status='VERIFIED_NORMAL', top3=[1, 2, 3]),
            back_holds={rid: 'BACK_STUDY_RESTORE_UNVERIFIED'})
        self.assertEqual(report['owner_originals_replayed'], 1)
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 1)
        paired = report['metrics']['paired_back']
        self.assertEqual((paired['registered_day'], paired['retained_pairs'], paired['official_scorable_pairs']),
                         (3, 0, 0))
        self.assertEqual(paired['replay_holds'], {'BACK_STUDY_RESTORE_UNVERIFIED': 1})
        self.assertEqual(paired['paired_one_point']['trifecta'],
                         dict(paired_races=0, difference=None, difference_ci95=None))

    def test_profile_study_failure_preserves_the_authenticated_original_score(self):
        rid = RACES[0]
        def failed_profile_report(*_):
            raise RuntimeError('private fixture scoring error')

        report = settle._score_registered(RACES, DAY, self.entries(), [shadow.slot(DAY, rid)],
            {shadow.slot(DAY, RACES[1]): 'SERVER_READBACK_AFTER_T15'},
            lambda entry, race: forecast(race),
            lambda race: dict(race_id=race, day=DAY, result_status='VERIFIED_NORMAL', top3=[1, 2, 3]),
            personal_report=failed_profile_report)
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 1)
        self.assertEqual(report['metrics']['personal_history_study'],
            dict(state='HOLD_PROFILE_STUDY_SCORING_UNVERIFIED', prospectively_sealed=False))

    def test_sealed_profile_scoring_failure_preserves_frozen_and_back_scores(self):
        rid = RACES[0]
        approved = [shadow.slot(DAY, r) for r in RACES[:2]]

        def result(race):
            return dict(race_id=race, day=DAY, top3=[1, 2, 3], result_status='VERIFIED_NORMAL')

        with patch.object(settle, '_score_personal_pairs', side_effect=RuntimeError('synthetic scorer failure')):
            report = settle._score_registered(RACES, DAY, self.entries(), approved, {}, lambda _, r: forecast(r),
                result, back_pairs={rid: {name: forecast(rid) for name in settle.BACK_ARMS}},
                personal_pairs={rid: dict(forecast(rid), used_finishes=1)})
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 2)
        self.assertEqual(report['metrics']['paired_back']['official_scorable_pairs'], 1)
        self.assertEqual(report['metrics']['paired_personal_history'],
                         {'state': 'HOLD_PERSONAL_STUDY_SCORING_UNVERIFIED'})

    def test_encrypted_back_pair_replays_with_or_without_the_two_history_studies(self):
        from research.chatgpt_dt_r1 import official_personal_history as profiles
        from research.chatgpt_dt_r1 import test_back_official_shadow as back_fixtures
        from tests import test_keirin_dt_r1_future_shadow as shadow_fixtures

        def profile(_, target, *, prediction_at):
            return dict(status='READY', policy=profiles.POLICY, proof_sha256='e' * 64, events=[dict(
                identity_key=target['riders'][0]['identity_key'], race_id='203001059801', rank=1,
                field_size=7, source_sha256='f' * 64, published_at='2030-01-05T04:00:00+00:00')])

        back_fixtures.BackOfficialShadowTests.setUpClass()
        back = back_fixtures.BackOfficialShadowTests()
        back.setUp()
        self.addCleanup(back.doCleanups)
        shadow_fixtures.FutureShadowTests.setUpClass()
        for warm, personal in ((False, False), (True, False), (True, True)):
            with self.subTest(warm=warm, personal=personal):
                fixture = shadow_fixtures.FutureShadowTests()
                fixture.setUp()
                try:
                    prior = SimpleNamespace(arguments=lambda *_: dict(history_records=[back.history],
                                                              history_verifier=back.official.verifier))
                    extra = patch.object(profiles, 'profile_finishes', side_effect=profile) if personal else nullcontext()
                    with (
                        patch.object(settle.codec.storage, 'PINNED_OWNER_SPKI_SHA256', back.candidate.owner_pin),
                        back.restored() as trial,
                        patch.object(settle.codec.storage, 'PINNED_OWNER_SPKI_SHA256', fixture.pin),
                        extra,
                    ):
                        fixture.produce(official_history=prior if warm else None, back_trial=trial,
                                        compare_personal_history=personal)
                        manifest = fixture.manifest()
                        entry = next(row for row in manifest['entries'] if row['state'] == shadow.READY)
                        sealed = (fixture.output / entry['cipher']['file']).read_bytes()
                        saved = settle.codec.decrypt_evidence(sealed, fixture.private)
                        material = saved['shared_material']
                        if personal:
                            self.assertEqual(material['schema'], shadow.PERSONAL_STUDY_MATERIAL_SCHEMA)
                            material = material['frozen_material']
                        self.assertEqual(material['schema'], shadow.BACK_STUDY_MATERIAL_SCHEMA)
                        self.assertEqual('no_history_control' in material, warm)
                        trained, venues = shadow.load_frozen(shadow_fixtures.ROOT)
                        pairs, controls, personal_pairs = {}, {}, {}
                        with patch.object(settle, 'OfficialHistory', return_value=prior) as source:
                            replayed = settle._forecast_from_original(entry, sealed, manifest,
                                fixture.store, fixture.rid, fixture.private, trained, venues, object(), {},
                                history_controls=controls, back_trial=lambda: trial, back_pairs=pairs,
                                personal_pairs=personal_pairs)
                        self.assertEqual(replayed, saved['forecast'])
                        self.assertEqual(source.call_count, int(warm))
                        self.assertEqual(bool(controls), warm)
                        self.assertEqual(bool(personal_pairs), personal)
                        self.assertEqual(set(pairs[fixture.rid]), {'back_mixture', 'direct'})
                        self.assertEqual(pairs[fixture.rid]['direct']['input_sha256'], replayed['input_sha256'])
                        tampered = deepcopy(entry)
                        material['back_study']['arms']['direct']['distribution_sha256'] = '0' * 64
                        tampered['bindings']['shared_material_sha256'] = settle.digest(saved['shared_material'])
                        altered = settle.codec.seal_evidence(settle.records.wire(saved), fixture.public, fixture.day,
                                                             entry['clocks']['seal_started_at'])
                        tampered['cipher']['sha256'] = sha256(altered).hexdigest()
                        pairs.clear()
                        controls.clear()
                        personal_pairs.clear()
                        study_holds = {}
                        with patch.object(settle, 'OfficialHistory', return_value=prior):
                            verified = settle._forecast_from_original(tampered, altered, manifest, fixture.store,
                                fixture.rid, fixture.private, trained, venues, object(), {}, history_controls=controls,
                                back_trial=lambda: trial, back_pairs=pairs, back_holds=study_holds,
                                personal_pairs=personal_pairs)
                        self.assertEqual(verified, replayed)
                        self.assertFalse(pairs)
                        self.assertEqual(bool(controls), warm)
                        self.assertEqual(bool(personal_pairs), personal)
                        self.assertEqual(study_holds, {fixture.rid: 'BACK_STUDY_MATERIAL_CHANGED'})
                        controls.clear()
                        study_holds.clear()
                        with patch.object(settle, 'OfficialHistory', return_value=prior):
                            verified = settle._forecast_from_original(entry, sealed, manifest, fixture.store,
                                fixture.rid, fixture.private, trained, venues, object(), {}, history_controls=controls,
                                back_trial=None, back_pairs=pairs, back_holds=study_holds)
                        self.assertEqual(verified, replayed)
                        self.assertEqual(bool(controls), warm)
                        self.assertEqual(study_holds, {fixture.rid: 'BACK_STUDY_RESTORE_UNVERIFIED'})
                finally:
                    fixture.doCleanups()

    def test_back_restore_is_lazy_once_even_after_a_failed_restore(self):
        for fails in (False, True):
            with self.subTest(fails=fails), ExitStack() as stack:
                cleanup = []
                trial = lambda: 'fixture'

                @contextmanager
                def restore(*_args, **_kwargs):
                    if fails:
                        raise ValueError('fixture')
                    yield trial
                    cleanup.append(True)

                with patch.object(settle.back_official_shadow, 'restored_candidate', side_effect=restore) as call:
                    lazy = settle._lazy_back_trial(stack, '/repo', '/private', b'fixture')
                    call.assert_not_called()
                    if fails:
                        with self.assertRaisesRegex(ValueError, 'fixture'):
                            lazy()
                        with self.assertRaisesRegex(settle.SettlementError, 'BACK_STUDY_RESTORE_UNVERIFIED'):
                            lazy()
                    else:
                        self.assertIs(lazy(), trial)
                        self.assertIs(lazy(), trial)
                    call.assert_called_once_with(Path('/repo') / settle.BACK_RECEIPT, '/private',
                                                 owner_private_pem=b'fixture')
                stack.close()
                self.assertEqual(cleanup, [] if fails else [True])

    def test_archived_day_combines_first_slots_and_keeps_latest_registered_denominator(self):
        legacy_rid, later_rid, hold_rid = RACES
        added_rid = '202611282404'
        legacy_slot, later_slot, hold_slot = [shadow.slot(DAY, rid) for rid in RACES]
        registry_meta = dict(cipher_sha256='a'*64, evidence_sha256='b'*64)
        def store(head, race_ids, original_ids, *, complete=True):
            return SimpleNamespace(day=DAY, head=head,
                index=dict(registry=registry_meta, originals={rid: {'source': rid} for rid in original_ids}),
                read=lambda *_: dict(event_day=DAY, registered_race_ids=race_ids,
                                     day_inventory_complete=complete, missing_venues=[] if complete else ['98']))
        old = store(settle.PARENT, RACES, RACES[:1])
        later = store('c'*40, RACES, RACES[:2])
        current = store('d'*40, [*RACES, added_rid], RACES, complete=False)
        current.repo = Path('/reader')
        current.index['results'] = {
            legacy_rid: [{'evidence_sha256': 'a'*64}, {'evidence_sha256': 'b'*64}],
            later_rid: [{'evidence_sha256': 'c'*64}],
            hold_rid: [],
        }
        def batch(source, ready):
            entries = [dict(entry, state=shadow.READY if entry['slot_sha256'] in ready else 'HOLD')
                       for entry in self.entries()]
            return dict(summary=dict(source_archive_commit=source.head, day_jst=DAY, reader_run_id=source.head),
                        registry=registry_meta, entries=entries)
        old_manifest = batch(old, [legacy_slot])
        old_manifest['entries'][0]['cipher'] = {'file': 'first.sealed.json'}
        later_manifest = batch(later, [later_slot])
        additional = {later_slot: dict(entry=later_manifest['entries'][1], manifest=later_manifest,
                                       cipher_path='verified/later.sealed.json')}
        events = []
        def forecast_replay(entry, raw, manifest, source, rid, *args, history_sources, history_controls,
                            back_trial, back_pairs, back_holds, feature_rows, personal_add,
                            personal_pairs, personal_holds):
            events.append(('forecast', rid, source.head))
            self.assertEqual(raw, b'first' if rid == legacy_rid else b'later')
            self.assertEqual(history_sources, {})
            personal_add(race_id=rid)
            feature_rows[rid] = (rid, None)
            if rid == later_rid:
                history_controls[rid] = forecast(rid)
                back_pairs[rid] = {name: forecast(rid) for name in settle.BACK_ARMS}
                personal_pairs[rid] = dict(forecast(rid), used_finishes=2)
            return forecast(rid)
        def result_replay(source, rid, key, original_meta, now):
            events.append(('result', rid, source.head))
            self.assertEqual(original_meta, current.index['originals'].get(rid) if rid in RACES[:2] else None)
            return dict(race_id=rid, day=DAY, result_status='VERIFIED_NORMAL', top3=[1,2,3])

        def prefetch_results(repo, head, paths, prefixes):
            folder = f'{settle.records.ROOT}/{DAY}'
            self.assertEqual((repo, head, prefixes), (current.repo, current.head, (folder,)))
            self.assertEqual(paths, {f"{folder}/{'b'*64}.sealed.json", f"{folder}/{'c'*64}.sealed.json"})
            events.append(('prefetch', current.head))
            raise settle.archive.GitCipherArchiveError('PREFETCH_FIXTURE_FAILURE')
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'first.sealed.json').write_bytes(b'first')
            legacy = (dict(manifest=old_manifest, directory=directory),
                      dict(eligible_slots=[legacy_slot], held_slots={hold_slot: 'SERVER_READBACK_AFTER_T15'}))
            with (
                patch.object(settle.batch_retention, 'read_retained_forecasts', return_value=additional),
                patch.object(settle.records, 'replay_registry', side_effect=lambda payload: payload),
                patch.object(settle.records, 'RecordStore', side_effect=lambda _, __, *, index_commit:
                             {old.head: old, later.head: later}[index_commit]),
                patch.object(settle.archive, 'read_blob_bytes', return_value=b'later'),
                patch.object(settle.archive, 'prefetch_pinned_blobs', side_effect=prefetch_results),
                patch.object(settle, '_forecast_from_original', side_effect=forecast_replay),
                patch.object(settle, '_result_row', side_effect=result_replay),
            ):
                seen = []
                adds = []
                def failed_profile_add(**fields):
                    adds.append(fields['race_id'])
                    raise RuntimeError('private fixture replay error')

                personal = SimpleNamespace(add=failed_profile_add, report=lambda *_: self.fail('failed profile scored'))
                audit = SimpleNamespace(add=lambda row, _: seen.append(row),
                                        report=lambda: {'audited_races': len(seen)})
                report = settle._score_archived_day(None, current, b'', None, None, None, lambda: None, legacy,
                                                   feature_audit=audit, personal_study=personal)
                self.assertEqual(adds, [legacy_rid])
                additional[legacy_slot] = additional[later_slot]
                with self.assertRaisesRegex(ValueError, 'DUPLICATE_FIRST_SLOT'):
                    settle._score_archived_day(None, current, b'', None, None, None, lambda: None, legacy)
        self.assertEqual(events[:2], [('forecast', legacy_rid, old.head), ('forecast', later_rid, later.head)])
        self.assertEqual(events[2:], [('prefetch', current.head),
                                     *(('result', rid, current.head) for rid in [*RACES, added_rid])])
        self.assertEqual(set(seen), {legacy_rid, later_rid})
        self.assertEqual(report['feature_audit'], {'audited_races': 2, 'unaudited_replayed_races': 0})
        self.assertEqual(report['registered_races'], 4)
        self.assertEqual(report['owner_originals_replayed'], 2)
        self.assertEqual(report['metrics']['predicted_evaluable'], 2)
        self.assertEqual(report['metrics']['paired_back']['official_scorable_pairs'], 1)
        self.assertEqual(report['metrics']['paired_personal_history']['official_scorable_pairs'], 1)
        self.assertEqual(report['metrics']['paired_personal_history']['official_prior_personal_finish_exposures'], 2)
        personal = report['metrics']['paired_personal_history']['paired_one_point']
        self.assertEqual((personal['baseline'], personal['comparison']),
                         ('archive_seven', 'seven_and_personal_days_8_to_30'))
        self.assertEqual(personal['exacta']['paired_races'], 1)
        self.assertEqual(report['metrics']['personal_history_study'],
                         dict(state='HOLD_PROFILE_STUDY_SCORING_UNVERIFIED', prospectively_sealed=False))
        paired = report['metrics']['paired_history']
        self.assertEqual((paired['registered_day'], paired['retained_pairs']), (4, 1))
        self.assertEqual(paired['official_history']['predicted_evaluable'], 1)
        self.assertEqual(paired['no_history']['predicted_evaluable'], 1)
        self.assertEqual(paired['paired_one_point']['baseline'], 'no_history')
        self.assertEqual(paired['paired_one_point']['comparison'], 'official_history')
        self.assertEqual(paired['paired_one_point']['trifecta']['paired_races'], 1)
        self.assertNotIn('proper_scores', paired['no_history'])
        self.assertFalse(report['day_inventory_complete'])
        self.assertEqual(report['missing_venues'], 1)
        self.assertEqual(report['timed_originals'], {'legacy': 1, 'additional': 1})
        self.assertEqual(report['forecast_holds'], {'SERVER_READBACK_AFTER_T15': 1, 'SAVED_ORIGINAL_MISSING': 1})


if __name__ == '__main__':
    unittest.main()
