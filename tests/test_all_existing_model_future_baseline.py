"""Authored baseline artifacts and cards; fixture keys, no real source access."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_research as research
from race_ai.all_existing_model_learning import fit, verify_training
from race_ai.boat_venue_learning import seal_candidate
from race_ai.four_sport_learning import LEARNED_ID, forecast
from race_ai.official_order_only_result import EVALUATION_SCOPE
from tests.test_all_existing_model_matrix import native_records, native_payload, _shift_dates
from tests.test_boat_venue_research import SOURCE, CONTENT, B_RIGHTS
from tests.test_boat_venue_learning import POINTER

from race_ai import all_existing_model_future_baseline as baseline

KEY = bytes(range(32))
CREATED = datetime(2030, 2, 1, tzinfo=timezone.utc)
NOW = datetime(2030, 2, 15, 0, 10, tzinfo=timezone.utc)
HEAD = 'a' * 40


@lru_cache(maxsize=2)
def fitted(order_only=False):
    rows = native_records(LEARNED_ID, 'boat') + native_records(LEARNED_ID, 'horse')
    training = fit(rows, now=CREATED, allow_order_only=order_only)
    return training


def bound_training(order_only=False):
    training = deepcopy(fitted(order_only))
    owner = research.issue_decision(source_pointer=SOURCE, state_content_sha256=CONTENT,
        dataset_pointer=POINTER, source_refs=[('https://www.boatrace.jp/fixture/card', B_RIGHTS)],
        intake_sha256=training['source_intake_sha256'], registry_sha256=training['registry_sha256'],
        now=CREATED, expires_at=CREATED + timedelta(days=1),
        label_evaluation_scope=EVALUATION_SCOPE if order_only else None)
    training.update(training_basis='OWNER_PERSONAL_RESEARCH', owner_research_decision_sha256=digest(owner),
        source_content_sha256=CONTENT, venue_dataset_sha256=POINTER['dataset_sha256'])
    training['training_sha256'] = digest({k: v for k, v in training.items() if k != 'training_sha256'})
    verify_training(training)
    return training, owner


def receipt(raw=b'authored candidate'):
    return dict(id=800, name='all-existing-model-learning-42-1', expired=False,
        size_in_bytes=len(raw), digest='sha256:' + sha256(raw).hexdigest(),
        created_at=(CREATED + timedelta(seconds=2)).isoformat(),
        expires_at=(NOW + timedelta(days=7)).isoformat(), workflow_run=dict(id=42,
            head_sha=HEAD, repository_id=1416489937, head_repository_id=1416489937))


def pin(actual):
    return dict(id=actual['id'], digest=actual['digest'], run_id=actual['workflow_run']['id'],
        head_sha=actual['workflow_run']['head_sha'])


def card(sport='horse'):
    payload = _shift_dates(native_payload(LEARNED_ID, sport), 31)
    captured = (NOW - timedelta(minutes=9)).isoformat()
    url = 'https://www.boatrace.jp/fixture/card' if sport == 'boat' else 'https://www.jra.go.jp/fixture/card'
    payload['source_evidence'] = [dict(source_ref=url, source_sha256='b' * 64,
        source_rights_ref='fixture-card', captured_at=captured, published_at=None)]
    metadata = dict(source_url=url, final_url=url, source_sha256='b' * 64, status=200,
        fetched_at=(NOW - timedelta(minutes=10)).isoformat(), response_received_at=captured,
        byte_count=17, headers={'Content-Type': 'text/html'})
    return payload, metadata


class FutureBaselineTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment.start(); self.addCleanup(environment.stop)
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden'))
        network.start(); self.addCleanup(network.stop)
        self.training, self.owner = bound_training()
        self.context = dict(training=self.training, receipt=receipt(), owner_research_record=self.owner)

    def test_pins_are_exact_copied_and_reject_bool_unknown_and_malformed_values(self):
        value = pin(receipt()); self.assertEqual(baseline.validate_pin(value), value)
        self.assertIsNot(baseline.validate_pin(value), value)
        for change in (dict(id=True), dict(run_id=True), dict(digest='b' * 64), dict(head_sha='a' * 39), dict(extra=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                baseline.validate_pin(dict(value, **change))

    def test_owner_v1_and_v2_verify_at_original_fit_clock_even_after_permission_expiry(self):
        self.assertTrue(baseline.verify_owner(self.training, self.owner))
        other, owner = bound_training(True)
        self.assertTrue(baseline.verify_owner(other, owner, schema=research.ORDER_SCHEMA))
        with self.assertRaises(ValueError): baseline.verify_owner(other, owner, schema=research.SCHEMA)

    def test_resigned_owner_intake_scope_and_source_changes_do_not_authorize_another_fit(self):
        for field, value in (('intake_sha256', 'f' * 64), ('source_content_sha256', 'e' * 64),
                             ('model_cells', []), ('provider_permission_confirmed', True)):
            owner = deepcopy(self.owner); owner['decision'][field] = value
            owner['mac'] = research._mac(owner['decision'], schema=owner['schema'])
            training = deepcopy(self.training); training['owner_research_decision_sha256'] = digest(owner)
            training['training_sha256'] = digest({k: v for k, v in training.items() if k != 'training_sha256'})
            with self.subTest(field=field), self.assertRaises(ValueError): baseline.verify_owner(training, owner)
        owner = deepcopy(self.owner); owner['mac'] = '0' * 64
        with self.assertRaises(ValueError): baseline.verify_owner(self.training, owner)

    def test_owner_bound_intake_takes_precedence_over_legacy_record_digest(self):
        training = deepcopy(self.training); training['owner_bound_intake_sha256'] = 'd' * 64
        owner = deepcopy(self.owner); owner['decision']['intake_sha256'] = 'd' * 64
        owner['mac'] = research._mac(owner['decision'], schema=owner['schema'])
        training['owner_research_decision_sha256'] = digest(owner)
        training['training_sha256'] = digest({k: v for k, v in training.items() if k != 'training_sha256'})
        self.assertTrue(baseline.verify_owner(training, owner))

    def archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'candidate'
            seal_candidate(dict(training=self.training, owner_research_record=self.owner, excluded=[],
                summary=dict(state='FITTED_SHADOW_ONLY', actual_purchases=False, production_promoted=False)), root)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for name in ('learning.enc', 'learning.json', 'summary.json'):
                    archive.writestr(name, (root / name).read_bytes())
            return stream.getvalue()

    def test_actual_candidate_codec_and_metadata_pins_load_original_owner_and_native_weights(self):
        raw = self.archive(); actual = receipt(raw); calls = []
        context = baseline.load_baseline(pin(actual), now=NOW,
            fetch_metadata=lambda ident: calls.append(('metadata', ident)) or deepcopy(actual),
            fetch_zip=lambda ident: calls.append(('zip', ident)) or raw)
        self.assertEqual(context, dict(training=self.training, receipt=actual, owner_research_record=self.owner))
        self.assertEqual(calls, [('zip', 800), ('metadata', 800)])
        for field, value in (('digest', 'sha256:' + '0' * 64), ('head_sha', 'c' * 40), ('run_id', 43)):
            changed = dict(pin(actual), **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                baseline.load_baseline(changed, now=NOW, fetch_metadata=lambda _: deepcopy(actual), fetch_zip=lambda _: raw)

    def test_missing_key_stops_before_callbacks_and_wrong_key_before_metadata(self):
        raw = self.archive(); actual = receipt(raw); calls = []
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            with self.assertRaises(ValueError): baseline.load_baseline(pin(actual), now=NOW,
                fetch_metadata=lambda _: calls.append('metadata'), fetch_zip=lambda _: calls.append('zip'))
        self.assertEqual(calls, [])
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(KEY))).decode()):
            with self.assertRaises(ValueError): baseline.load_baseline(pin(actual), now=NOW,
                fetch_metadata=lambda _: calls.append('metadata'), fetch_zip=lambda _: calls.append('zip') or raw)
        self.assertEqual(calls, ['zip'])

    def test_attachment_preserves_native_snapshot_and_sources_and_predicts_original_baseline(self):
        for sport in ('boat', 'horse'):
            payload, metadata = card(sport); before = deepcopy(payload); context_before = deepcopy(self.context)
            metadata['source_packet_closure'] = {'dom': {'kind': 'RENDERED_DOM', 'captured_at': metadata['response_received_at']}}
            attached = baseline.attach(payload, self.context, sport=sport, source_metadata=metadata, now=NOW)
            self.assertEqual(payload, before); self.assertEqual(self.context, context_before)
            self.assertEqual(attached['snapshot'], before['snapshot']); self.assertEqual(attached['source_evidence'], before['source_evidence'])
            model = self.training['models'][sport + '/' + LEARNED_ID]
            self.assertEqual(attached['learned_model'], model['native_training'])
            self.assertEqual(attached['baseline_attachment']['original_payload_sha256'], digest(before))
            self.assertTrue(baseline.verify_attachment(attached, self.context, sport=sport, now=NOW + timedelta(seconds=2),
                generated_at=(NOW + timedelta(seconds=1)).isoformat()))
            self.assertEqual(attached['baseline_attachment']['source_lineage'], model['source_lineage'])
            self.assertEqual(attached['baseline_attachment']['owner_research_record'], self.owner)
            self.assertEqual(attached['baseline_attachment']['source_metadata'], metadata)
            self.assertNotIn('status', attached['baseline_attachment']['source_metadata']['source_packet_closure']['dom'])
            self.assertEqual(forecast(attached['snapshot'], attached['learned_model']),
                             forecast(before['snapshot'], model['native_training']))

    def test_clock_boundaries_use_original_card_start_and_never_retimestamp_inputs(self):
        payload, metadata = card(); available = datetime.fromisoformat(self.context['receipt']['created_at']) + timedelta(seconds=1)
        for kind in ('before_receipt', 'after_now', 'reversed_response', 'created_equal_fetch'):
            changed = deepcopy(metadata); context = deepcopy(self.context)
            if kind == 'before_receipt': changed['fetched_at'] = (available - timedelta(microseconds=1)).isoformat()
            if kind == 'after_now': changed['response_received_at'] = (NOW + timedelta(seconds=1)).isoformat()
            if kind == 'reversed_response': changed['fetched_at'] = (NOW + timedelta(seconds=1)).isoformat()
            if kind == 'created_equal_fetch': changed['fetched_at'] = self.training['models']['horse/' + LEARNED_ID]['native_training']['created_at']
            with self.subTest(kind=kind), self.assertRaises(ValueError): baseline.attach(payload, context, sport='horse', source_metadata=changed, now=NOW)
        changed = deepcopy(metadata); changed['fetched_at'] = available.isoformat()
        self.assertTrue(baseline.attach(payload, self.context, sport='horse', source_metadata=changed, now=NOW))

    def test_missing_source_wrong_schema_scope_and_existing_baselines_are_unavailable(self):
        payload, metadata = card()
        for kind in ('evidence', 'source_sha', 'source_url', 'source_clock', 'scope', 'schema', 'learned_model', 'baseline_attachment'):
            changed = deepcopy(payload); meta = deepcopy(metadata)
            if kind == 'evidence': changed['source_evidence'] = []
            elif kind == 'source_sha': meta['source_sha256'] = 'f' * 64
            elif kind == 'source_url': meta['source_url'] += '/other'
            elif kind == 'source_clock': meta['response_received_at'] = (NOW - timedelta(seconds=1)).isoformat()
            elif kind == 'scope': changed['snapshot']['scope'] = 'OPERATOR_SUPPLIED_RESEARCH'
            elif kind == 'schema': changed['snapshot']['schema'] += '_OTHER'
            else: changed[kind] = {}
            with self.subTest(kind=kind), self.assertRaises(ValueError): baseline.attach(changed, self.context, sport='horse', source_metadata=meta, now=NOW)

    def test_rehashed_original_or_model_proof_swaps_and_generation_reversal_reject(self):
        payload, metadata = card(); attached = baseline.attach(payload, self.context, sport='horse', source_metadata=metadata, now=NOW)
        for kind in ('feature', 'model', 'proof_sha', 'receipt', 'metadata', 'attached_at', 'lineage', 'owner', 'historical_refs'):
            changed = deepcopy(attached)
            if kind == 'feature': changed['snapshot']['participants'][0]['draw'] = 2
            elif kind == 'model': changed['learned_model']['weights'][0] += .1
            elif kind == 'proof_sha': changed['baseline_attachment']['original_payload_sha256'] = 'f' * 64
            elif kind == 'receipt': changed['baseline_attachment']['artifact_receipt']['id'] += 1
            elif kind == 'metadata': changed['baseline_attachment']['source_metadata']['source_sha256'] = 'f' * 64
            elif kind == 'attached_at': changed['baseline_attachment']['attached_at'] = (NOW + timedelta(seconds=1)).isoformat()
            elif kind == 'lineage': changed['baseline_attachment']['source_lineage'][0]['input_sha256'] = 'f' * 64
            elif kind == 'owner': changed['baseline_attachment']['owner_research_record']['mac'] = '0' * 64
            else: changed['baseline_attachment']['historical_source_refs'].append(['https://www.jra.go.jp/invented-source', 'not-granted'])
            with self.subTest(kind=kind), self.assertRaises(ValueError): baseline.verify_attachment(changed, self.context, sport='horse', now=NOW)
        with self.assertRaises(ValueError): baseline.verify_attachment(attached, self.context, sport='horse', now=NOW,
            generated_at=(NOW - timedelta(microseconds=1)).isoformat())

    def test_serialized_attachment_clock_and_malformed_actual_metadata_fail_closed(self):
        payload, metadata = card(); attached = baseline.attach(payload, self.context, sport='horse', source_metadata=metadata, now=NOW)
        attached['baseline_attachment']['attached_at'] = NOW
        with self.assertRaises(ValueError): baseline.verify_attachment(attached, self.context, sport='horse', now=NOW)
        raw = self.archive(); actual = receipt(raw)
        del actual['workflow_run']
        with self.assertRaises(ValueError): baseline.load_baseline(pin(receipt(raw)), now=NOW,
            fetch_metadata=lambda _: actual, fetch_zip=lambda _: raw)

    def test_expired_actual_artifact_does_not_borrow_original_owner_validity(self):
        raw = self.archive(); actual = receipt(raw); actual['expires_at'] = NOW.isoformat()
        with self.assertRaises(ValueError): baseline.load_baseline(pin(actual), now=NOW,
            fetch_metadata=lambda _: actual, fetch_zip=lambda _: raw)

    def test_attachment_cannot_precede_original_snapshot_availability_on_later_replay(self):
        payload, metadata = card()
        attached = baseline.attach(payload, self.context, sport='horse', source_metadata=metadata, now=NOW)
        attached['baseline_attachment']['attached_at'] = (NOW - timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError): baseline.verify_attachment(attached, self.context, sport='horse',
            now=NOW + timedelta(seconds=5), generated_at=(NOW + timedelta(seconds=1)).isoformat())


if __name__ == '__main__': unittest.main()
