"""Synthetic native pairs/receipts/PDCA; no live save or accuracy claim."""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from tests.test_observed_weight_learning import NOW

FORECAST_NOW = NOW+timedelta(minutes=10)
HEAD = 'a'*40


class AllExistingModelPrivatePairsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        from tests.test_all_existing_model_learning import observed_records
        records = observed_records(); mid = records[0]['model_id']
        cls.records = [r for r in records if r['model_id'] == mid]
        cls.training = fit(cls.records, now=NOW)
        cls.cell = next(iter(cls.training['models']))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-all-model-pairs-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode())
        environment.start(); self.addCleanup(environment.stop)
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        candidate = self.root/'candidate'
        seal_candidate(dict(training=deepcopy(self.training), excluded=[], summary=dict(
            state=self.training['state'], fitted_model_count=len(self.training['models']),
            production_promoted=False, actual_purchases=False, plaintext_published=False)), candidate)
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.json', 'learning.enc', 'summary.json'):
                archive.writestr(name, (candidate/name).read_bytes())
        raw = body.getvalue()
        receipt = dict(id=700, name='all-existing-model-learning-99-1', expired=False,
            size_in_bytes=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            created_at=(NOW+timedelta(seconds=2)).isoformat(), expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=99, repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD))
        self.context = context_from_encrypted_artifact(raw, 700, now=FORECAST_NOW,
                                                     _fetch=lambda _: deepcopy(receipt))

    def native(self, number=12):
        native = deepcopy(self.records[0]['native_payload']); snapshot = native['snapshot']
        snapshot.update(race_id=f'boat:2030-04-01:boatrace-jcd-24:{number}', venue='boatrace-jcd-24',
            as_of=(FORECAST_NOW-timedelta(seconds=1)).isoformat(),
            sales_cutoff_at=(FORECAST_NOW+timedelta(minutes=20)).isoformat())
        for source in snapshot['sources']:
            source['captured_at'] = snapshot['as_of']
            if source['published_at'] is not None:
                source['published_at'] = snapshot['as_of']
        return native

    def extra_native_requests(self, number=12):
        """Independent fictional native A/B and C-lite inputs for this race."""
        from race_ai.boat_ab_shadow import MODEL_IDS
        from race_ai.boat_live_feature_shadow import MODEL_ID
        from tests.test_boat_ab_shadow import fixture as ab_fixture
        from tests.test_boat_live_feature_shadow import fixture as clite_fixture
        snapshot = self.native(number)['snapshot']
        registrations = {p['lane']: p['registration_no'] for p in snapshot['participants']}
        source = ab_fixture(); source.update(race_id=f'20300401-24-{number:02d}',
            captured_at=snapshot['as_of'], cutoff_at=snapshot['sales_cutoff_at'])
        for boat in source['boats']:
            boat['racer_id'] = registrations[boat['lane']]
        requests = [dict(cell_key='boat/'+mid, native_payload=dict(source=deepcopy(source), scope='SYNTHETIC_ONLY'))
                    for mid in MODEL_IDS]
        base, extra, _ = clite_fixture()
        base.update(race_id=source['race_id'], captured_at=source['captured_at'], cutoff_at=source['cutoff_at'])
        extra.update(race_id=source['race_id'], observed_at=source['captured_at'])
        for row in base['boats']:
            row['racer_id'] = registrations[row['lane']]
        for row in extra['participants']:
            row['racer_id'] = registrations[row['lane']]
        requests.append(dict(cell_key='boat/'+MODEL_ID, native_payload=dict(
            base_source=base, extra=extra, scope='SYNTHETIC_ONLY')))
        return requests

    def make(self, **changes):
        from race_ai.all_existing_model_pairs import make_private_pairs
        values = dict(now=FORECAST_NOW, allow_source=lambda *args: True)
        values.update(changes)
        return make_private_pairs(self.context, [{'cell_key': self.cell, 'native_payload': self.native()}],
                                  self.root/'pairs', **values)

    def payload(self):
        from race_ai.boat_venue_learning import read_candidate
        return read_candidate(next(p for p in (self.root/'pairs').iterdir() if p.is_dir()))

    def archive(self):
        members = {}
        for folder in sorted(p for p in (self.root/'pairs').iterdir() if p.is_dir()):
            for name in ('learning.json', 'learning.enc', 'summary.json'):
                members[folder.name+'/'+name] = (folder/name).read_bytes()
        return self.zip_members(members), members

    def zip_members(self, members, *, duplicate=None, symlink=None):
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in members.items():
                if name == symlink:
                    info = zipfile.ZipInfo(name); info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, value)
                else:
                    archive.writestr(name, value)
            if duplicate is not None:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr(duplicate, members[duplicate])
        return body.getvalue()

    def metadata(self, raw, **changes):
        result = dict(id=800, name='all-existing-model-pairs-99-1', expired=False,
            size_in_bytes=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            created_at=(FORECAST_NOW+timedelta(seconds=3)).isoformat(),
            expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=99, repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD))
        result.update(changes); return result

    def verify(self, raw, metadata=None, **changes):
        from race_ai.all_existing_model_receipt import verify_private_pairs_artifact
        values = dict(now=FORECAST_NOW+timedelta(hours=1), expected_run_id=99, expected_head_sha=HEAD)
        values.update(changes)
        return verify_private_pairs_artifact(raw, self.metadata(raw) if metadata is None else metadata, **values)

    def observation(self, **changes):
        pair = self.payload()['pair']; normalized = pair['baseline_normalized']
        result = dict(race_id=pair['race_id'], sport=pair['sport'], status='settled',
            ordered_top3=normalized['top'][0], roster=deepcopy(normalized['roster']),
            captured_at=(FORECAST_NOW+timedelta(minutes=21)).isoformat(), source_sha256='b'*64,
            identity_verified=True, payout_per_100_yen=1230, refund_numbers=[])
        result.update(changes); return result

    def score(self, raw, observations, **changes):
        from race_ai.all_existing_model_pdca import score_private_pairs_artifact
        values = dict(now=FORECAST_NOW+timedelta(hours=1), expected_run_id=99, expected_head_sha=HEAD)
        values.update(changes)
        return score_private_pairs_artifact(raw, self.metadata(raw), observations, self.root/'pdca', **values)

    def test_native_fitted_subset_roundtrips_and_missing_cells_stay_explicit(self):
        from race_ai.all_existing_model_pairs import make_private_pairs, verify_private_pair
        missing = next(k for k in self.training['model_states'] if k not in self.training['models'])
        requests = [dict(cell_key=self.cell, native_payload=self.native()),
                    dict(cell_key=missing, native_payload={})]
        before = deepcopy((self.context, requests))
        result = make_private_pairs(self.context, requests, self.root/'pairs', now=FORECAST_NOW,
                                    allow_source=lambda *args: True)
        payload = self.payload(); pair = payload['pair']
        self.assertTrue(verify_private_pair(payload)); self.assertEqual(result['partition_count'], 1)
        self.assertEqual(result['registered_cell_count'], 31); self.assertEqual(result['fitted_cell_count'], 1)
        self.assertEqual(result['missing_requested_cells'], [missing])
        self.assertEqual(pair['input_sha256'], digest(requests[0]['native_payload']))
        self.assertEqual(pair['baseline_normalized']['roster'], pair['learned_normalized']['roster'])
        self.assertEqual((self.context, requests), before)
        self.assertFalse(result['independent_pre_cutoff_receipt_verified'])
        public = json.dumps(result)
        for secret in ('parameters', 'source_url', 'participants', 'ordered_top8', 'native_payload'):
            self.assertNotIn(secret, public)

    def test_valid_unfitted_native_inputs_are_retained_without_unfitted_predictions(self):
        from race_ai import all_existing_model_pairs as api
        from race_ai.boat_observed_pairwise_models import MODEL_IDS
        requests = self.extra_native_requests()+[
            dict(cell_key='boat/'+mid, native_payload=self.native()) for mid in MODEL_IDS]
        original = deepcopy(requests)
        with patch.object(api, 'forecast_pair', wraps=api.forecast_pair) as forecast:
            summary = api.make_private_pairs(self.context, requests, self.root/'pairs',
                now=FORECAST_NOW, allow_source=lambda *args: True)
        self.assertTrue(all(call.args[1] == self.cell for call in forecast.call_args_list))
        payload = self.payload(); capsules = payload['captured_native_inputs']
        self.assertEqual(len(capsules), 5); self.assertEqual(summary['captured_native_input_count'], 5)
        self.assertEqual(summary['captured_unfitted_native_input_count'], 4)
        self.assertEqual(summary['baseline_forecast_count'], 1); self.assertEqual(summary['learned_forecast_count'], 1)
        self.assertEqual(requests, original)
        for capsule in capsules:
            request = next(row for row in requests if row['cell_key'] == capsule['cell_key'])
            self.assertEqual(capsule['native_payload'], request['native_payload'])
            self.assertEqual(capsule['input_sha256'], digest(request['native_payload']))
        raw, _ = self.archive(); admitted = self.verify(raw)
        self.assertEqual(admitted['captured_native_input_count'], 5)
        public = json.dumps(summary)+json.dumps(admitted)
        for secret in ('native_payload', 'program_source_sha256', 'exhibition_time_seconds', 'national_win_rate'):
            self.assertNotIn(secret, public)
        for name in ('learning.json', 'summary.json'):
            for path in (self.root/'pairs').glob('*/'+name):
                self.assertNotIn(b'program_source_sha256', path.read_bytes())

    def test_captured_input_hash_native_race_and_roster_tampering_fail_replay(self):
        from race_ai import all_existing_model_pairs as api
        requests = [dict(cell_key=self.cell, native_payload=self.native())]+self.extra_native_requests()
        api.make_private_pairs(self.context, requests, self.root/'pairs', now=FORECAST_NOW,
                               allow_source=lambda *args: True)
        original = self.payload()
        for kind in ('hash', 'race', 'roster'):
            payload = deepcopy(original)
            capsule = next(c for c in payload['captured_native_inputs'] if 'source' in c['native_payload'])
            if kind == 'hash':
                capsule['input_sha256'] = 'f'*64
            else:
                source = capsule['native_payload']['source']
                if kind == 'race':
                    source['race_id'] = '20300401-24-11'
                else:
                    source['boats'][0]['racer_id'] = '9999'
                capsule['input_sha256'] = digest(capsule['native_payload'])
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'CAPTURED_INPUT'):
                api.verify_private_pair(payload)

    def test_capsules_stay_in_their_own_race_partition(self):
        from race_ai.all_existing_model_pairs import make_private_pairs
        from race_ai.boat_venue_learning import read_candidate
        requests = [dict(cell_key=self.cell, native_payload=self.native(number)) for number in (11, 12)]
        requests += self.extra_native_requests(12)
        summary = make_private_pairs(self.context, requests, self.root/'pairs', now=FORECAST_NOW,
                                     allow_source=lambda *args: True)
        self.assertEqual(summary['partition_count'], 2)
        counts = {}
        for folder in (self.root/'pairs').iterdir():
            if folder.is_dir():
                payload = read_candidate(folder)
                counts[payload['pair']['race_id']] = len(payload['captured_native_inputs'])
        self.assertEqual(counts, {'boat:2030-04-01:boatrace-jcd-24:11': 1,
                                 'boat:2030-04-01:boatrace-jcd-24:12': 4})

    def test_artifact_clock_admits_every_captured_native_deadline(self):
        from race_ai.all_existing_model_receipt import _payload_clock
        generated = FORECAST_NOW.isoformat(); saved = FORECAST_NOW+timedelta(seconds=3)
        payload = dict(generated_at=generated, pair=dict(as_of=generated,
            cutoff_at=(saved+timedelta(minutes=10)).isoformat()), captured_native_inputs=[dict(
            captured_as_of=generated, cutoff_at=(saved+timedelta(seconds=1)).isoformat())])
        with self.assertRaisesRegex(ValueError, 'CAPTURED_INPUT_PRE_CUTOFF'):
            _payload_clock(payload, saved, saved+timedelta(minutes=20))

    def test_training_receipt_identity_expiry_and_second_margin_precede_inference(self):
        from race_ai import all_existing_model_pairs as api
        original = deepcopy(self.context)
        mutations = [dict(id=True), dict(digest='0'*64), dict(expired=True),
            dict(expires_at=FORECAST_NOW.isoformat()),
            dict(created_at=(FORECAST_NOW-timedelta(microseconds=999_999)).isoformat()),
            dict(workflow_run=dict(original['receipt']['workflow_run'], head_sha='main')),
            dict(workflow_run=dict(original['receipt']['workflow_run'], repository_id=1))]
        for mutation in mutations:
            self.context = deepcopy(original); self.context['receipt'].update(mutation)
            with self.subTest(mutation=mutation), patch.object(api, 'forecast_pair',
                    side_effect=AssertionError('receipt must precede inference')), self.assertRaises(ValueError):
                self.make()
            self.assertFalse((self.root/'pairs').exists())

    def test_duplicate_unknown_cell_and_future_native_source_are_rejected_before_writing(self):
        from race_ai.all_existing_model_pairs import make_private_pairs
        request = dict(cell_key=self.cell, native_payload=self.native())
        future = deepcopy(request); future['native_payload']['snapshot']['sources'][0]['captured_at'] = (
            FORECAST_NOW+timedelta(seconds=1)).isoformat()
        for requests in ([request, request], [dict(cell_key='boat/foreign', native_payload={})], [future]):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                make_private_pairs(self.context, requests, self.root/'pairs', now=FORECAST_NOW,
                                   allow_source=lambda *args: True)
            self.assertFalse((self.root/'pairs').exists())

    def test_late_monotonic_completion_quarantines_ciphertext_and_never_resets_output(self):
        from race_ai import all_existing_model_pairs as api
        with patch.object(api.time, 'monotonic', side_effect=[0, 0, 3600]):
            with self.assertRaisesRegex(ValueError, 'CUTOFF_ELAPSED_DURING_SEAL'):
                self.make()
        root = self.root/'pairs'; self.assertTrue((root/'quarantine.json').exists())
        self.assertFalse(json.loads((root/'quarantine.json').read_text())['independent_pre_cutoff_receipt_verified'])
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            self.make()
        self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_same_input_pair_tamper_fails_native_replay(self):
        from race_ai.all_existing_model_pairs import verify_private_pair
        self.make(); payload = self.payload(); pair = payload['pair']
        pair['learned_normalized']['top'][0] = list(reversed(pair['learned_normalized']['top'][0]))
        pair['pair_sha256'] = digest({k:v for k,v in pair.items() if k != 'pair_sha256'})
        with self.assertRaisesRegex(ValueError, 'REPLAY'):
            verify_private_pair(payload)

    def test_actual_archive_admits_after_race_without_exposing_private_records(self):
        self.make(); raw, _ = self.archive(); summary = self.verify(raw)
        self.assertEqual(summary['partition_count'], 1); self.assertEqual(summary['cell_count'], 1)
        self.assertEqual(summary['record_sha256'], [digest(self.payload())])
        self.assertTrue(summary['independent_pre_cutoff_receipt_verified'])
        for secret in ('native_payload', 'participants', 'ordered_top8', 'parameters', 'roster'):
            self.assertNotIn(secret, json.dumps(summary))

    def test_archive_metadata_digest_run_head_repository_and_conservative_cutoff(self):
        self.make(); raw, _ = self.archive(); good = self.metadata(raw)
        bad = [dict(id=True), dict(expired=True), dict(digest='sha256:'+'0'*64),
            dict(size_in_bytes=len(raw)+1), dict(name='all-existing-model-pairs-98-1'),
            dict(expires_at=(FORECAST_NOW+timedelta(hours=1)).isoformat()),
            dict(created_at=(FORECAST_NOW+timedelta(minutes=20, seconds=-1)).isoformat())]
        for key, value in (('id', 98), ('head_sha', 'b'*40), ('repository_id', 1), ('head_repository_id', 1)):
            bad.append(dict(workflow_run=dict(good['workflow_run'], **{key:value})))
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify(raw, dict(good, **changes))

    def test_zip_paths_duplicates_symlinks_extra_root_summary_and_corrupt_cipher_stop(self):
        self.make(); _, members = self.archive(); name = next(iter(members)); key = name.split('/')[0]
        variants = [dict(members, **{'summary.json': b'{}'}),
            {p.replace(key+'/', '../'): value for p,value in members.items()},
            {p.replace(key+'/', '0'*64+'/'): value for p,value in members.items()},
            {p:value+b'corrupt' if p.endswith('learning.enc') else value for p,value in members.items()}]
        raw_variants = [self.zip_members(v) for v in variants]
        raw_variants += [self.zip_members(members, duplicate=name), self.zip_members(members, symlink=name)]
        for index, raw in enumerate(raw_variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify(raw)

    def test_zip_member_and_total_plaintext_bounds_precede_owner_decryption(self):
        from race_ai import all_existing_model_receipt as api
        self.make(); _, members = self.archive(); key = next(iter(members)).split('/')[0]
        variants = []
        for name, limit in api.MEMBER_LIMITS.items():
            variants.append(dict(members, **{key+'/'+name: b'x'*(limit+1)}))
        variants.append({digest({'synthetic':i})+'/'+name: b'x'*(12*1024*1024) if name == 'learning.enc' else b'x'
                         for i in range(6) for name in api.MEMBER_LIMITS})
        for index, values in enumerate(variants):
            raw = self.zip_members(values)
            with self.subTest(index=index), patch.object(api, 'read_candidate',
                    side_effect=AssertionError('bounds before decryption')), self.assertRaises(ValueError):
                self.verify(raw)

    def test_outputs_inside_git_or_through_symlinks_are_rejected_without_reset(self):
        from race_ai.all_existing_model_pairs import make_private_pairs
        git = self.root/'repo'; git.mkdir(); (git/'.git').mkdir()
        link = self.root/'link'; link.symlink_to(git, target_is_directory=True)
        for path in (git/'pairs', link/'pairs'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                make_private_pairs(self.context, [dict(cell_key=self.cell, native_payload=self.native())],
                    path, now=FORECAST_NOW, allow_source=lambda *args: True)
            self.assertFalse((git/'pairs').exists())

    def test_missing_owner_key_stops_before_archive_inspection(self):
        from race_ai import all_existing_model_receipt as api
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch.object(api.zipfile, 'ZipFile',
                side_effect=AssertionError('key must precede archive')), self.assertRaises(ValueError):
            self.verify(b'not an archive')

    def test_native_pdca_same_cell_cohort_and_encrypted_detail_replay(self):
        from race_ai.all_existing_model_pdca import verify_private_pdca
        from race_ai.boat_venue_learning import read_candidate
        self.make(); raw, _ = self.archive(); observation = self.observation()
        summary = self.score(raw, [observation]); board = summary['scoreboard'][self.cell]
        self.assertEqual(summary['paired_forecasts'], 1)
        self.assertEqual(board['baseline']['forecasts'], board['learned']['forecasts'])
        self.assertEqual(board['baseline']['ticket_count'], 8)
        self.assertEqual(board['baseline']['stake_yen'], 800); self.assertEqual(board['baseline']['payout_yen'], 1230)
        self.assertEqual(board['baseline']['hits'], 1); self.assertIsNotNone(board['baseline']['mean_log_loss'])
        self.assertFalse(summary['accuracy_improvement_proven'])
        folder = next(p for p in (self.root/'pdca').iterdir() if p.is_dir())
        payload = read_candidate(folder); self.assertTrue(verify_private_pdca(payload))
        payload['score']['score']['baseline']['payout_yen'] += 100
        with self.assertRaisesRegex(ValueError, 'REPLAY'):
            verify_private_pdca(payload)
        public = json.dumps(summary)
        for secret in ('ordered_top3', 'roster', 'native_payload', 'parameters', 'source_url'):
            self.assertNotIn(secret, public)

    def test_pending_result_stays_unpaired_and_invalid_results_do_not_create_output(self):
        self.make(); raw, _ = self.archive()
        invalid = [self.observation(identity_verified=False), self.observation(roster={'1': 'wrong'}),
            self.observation(captured_at=(FORECAST_NOW+timedelta(hours=2)).isoformat()),
            self.observation(captured_at=FORECAST_NOW.isoformat()), self.observation(source_sha256='invalid')]
        for observation in invalid:
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                self.score(raw, [observation])
            self.assertFalse((self.root/'pdca').exists())
        observation = self.observation()
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_RESULT'):
            self.score(raw, [observation, observation])
        summary = self.score(raw, [self.observation(status='pending', ordered_top3=[], payout_per_100_yen=0)])
        self.assertEqual(summary['paired_forecasts'], 0)
        self.assertEqual(summary['result_state_counts'], {'PENDING_RESULT': 1})

    def test_documented_official_boat_alias_scores_and_duplicate_aliases_are_rejected(self):
        from race_ai.all_existing_model_pairs import partition_key
        self.make(); raw, _ = self.archive(); native = self.observation()
        official = self.observation(race_id='20300401-24-12')
        pair = self.payload()['pair']
        self.assertEqual(partition_key(pair), partition_key(dict(pair, race_id=official['race_id'])))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_RESULT'):
            self.score(raw, [native, official])
        result = self.score(raw, [official])
        self.assertEqual(result['paired_forecasts'], 1)


class NativeSelectionScoringTests(unittest.TestCase):
    def plan(self, count):
        tickets = [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2]][:count]
        return dict(top=tickets, stakes=[100]*count, ticket_count=count, ranked=[],
            kind='SELECTION', selection_status='SELECTED' if count else 'ABSTAINED',
            roster={str(i): str(i) for i in range(1, 7)})

    def test_seller_three_and_five_ticket_native_plans_retain_counts_and_stakes(self):
        from race_ai.all_existing_model_pdca import _score
        pair = dict(baseline_normalized=self.plan(3), learned_normalized=self.plan(5))
        result = _score(pair, dict(status='settled', ordered_top3=[1, 2, 3],
                                   payout_per_100_yen=1000, refund_numbers=[]))
        self.assertTrue(result['paired']); self.assertTrue(result['ticket_count_changed'])
        self.assertEqual(result['baseline']['stake_yen'], 300)
        self.assertEqual(result['learned']['stake_yen'], 500)
        self.assertIsNone(result['baseline']['log_loss'])

    def test_native_abstention_is_unpaired_and_special_refunds_keep_native_stakes(self):
        from race_ai.all_existing_model_pdca import _score
        pair = dict(baseline_normalized=self.plan(0), learned_normalized=self.plan(3))
        result = _score(pair, dict(status='special', ordered_top3=[], payout_per_100_yen=0, refund_numbers=[1]))
        self.assertFalse(result['paired']); self.assertEqual(result['state'], 'NATIVE_ABSTENTION_UNPAIRED')
        self.assertEqual(result['baseline']['ticket_count'], 0)
        self.assertEqual(result['learned']['refund_yen'], 300)

    def test_both_native_seller_plans_keep_separate_stakes_payouts_and_cohorts(self):
        from race_ai.all_existing_model_pdca import _score, _aggregate
        main = self.plan(5); main['stakes'] = [2000]*5
        three = self.plan(3); three['stakes'] = [4000, 3000, 3000]
        main['plans'] = {name:{k:plan[k] for k in ('top', 'stakes', 'ticket_count')}
                         for name,plan in (('three', three), ('five', deepcopy(main)))}
        pair = dict(baseline_normalized=deepcopy(main), learned_normalized=deepcopy(main))
        score = _score(pair, dict(status='settled', ordered_top3=[1, 2, 3],
                                 payout_per_100_yen=1000, refund_numbers=[]))
        self.assertEqual(score['primary_native_plan'], 'five')
        variants = score['native_plan_variants']
        self.assertEqual(variants['three']['baseline']['ticket_count'], 3)
        self.assertEqual(variants['five']['baseline']['ticket_count'], 5)
        self.assertEqual(variants['three']['baseline']['payout_yen'], 40000)
        self.assertEqual(variants['five']['baseline']['payout_yen'], 20000)
        board = _aggregate([dict(cell_key='boat/existing-seller', forecast_record_sha256='f'*64, score=score)])
        self.assertEqual(board['boat/existing-seller']['native_plan_variants']['three']['baseline']['roi'], 4)
        self.assertEqual(board['boat/existing-seller']['native_plan_variants']['five']['baseline']['roi'], 2)

    def test_non_boat_registered_roster_and_unequal_cell_coverage_are_independent(self):
        from race_ai.all_existing_model_pdca import _observation, _score, _aggregate
        plan = self.plan(3); plan['roster'] = {str(i): 'rider-'+str(i) for i in range(1, 10)}
        pair = dict(race_id='synthetic-keirin-race', sport='keirin',
            cutoff_at=FORECAST_NOW.isoformat(), race_cutoff_at=FORECAST_NOW.isoformat(),
            baseline_normalized=deepcopy(plan), learned_normalized=deepcopy(plan))
        observation = dict(race_id=pair['race_id'], sport='keirin', status='settled', ordered_top3=[1, 2, 3],
            roster=deepcopy(plan['roster']), captured_at=(FORECAST_NOW+timedelta(minutes=1)).isoformat(),
            source_sha256='c'*64, identity_verified=True, payout_per_100_yen=900, refund_numbers=[])
        _observation(observation, pair, FORECAST_NOW+timedelta(hours=1))
        settled = _score(pair, observation); pending = _score(pair, None)
        board = _aggregate([dict(cell_key='keirin/existing-a', forecast_record_sha256='a'*64, score=settled),
            dict(cell_key='keirin/existing-a', forecast_record_sha256='b'*64, score=settled),
            dict(cell_key='keirin/existing-b', forecast_record_sha256='c'*64, score=settled),
            dict(cell_key='keirin/existing-b', forecast_record_sha256='d'*64, score=pending)])
        self.assertEqual(board['keirin/existing-a']['paired_forecasts'], 2)
        self.assertEqual(board['keirin/existing-b']['paired_forecasts'], 1)
        for entry in board.values():
            self.assertEqual(entry['baseline']['forecasts'], entry['learned']['forecasts'])


if __name__ == '__main__':
    unittest.main()
