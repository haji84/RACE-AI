"""Existing source builders with invented records; no HTTP, keys or permission grant."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import canonical, digest
from race_ai import all_existing_model_source_derivations as guard
from race_ai.boat_all_model_inputs import _composite, build_native_inputs, pdca_payload_from_history
from race_ai.observed_p1_connection import RIGHTS
from tests.test_boat_all_model_inputs import ASOF, official_inputs


def direct(url, sha='a', at='2030-01-15T08:50:00+09:00'):
    return dict(source_ref=url, source_sha256=sha*64, source_rights_ref=RIGHTS,
                captured_at=at, published_at=None)


def simple_payload():
    program, before = official_inputs()
    result = build_native_inputs(program, before, as_of=ASOF)
    return result['native_inputs']['boat_full']


def nested_payload():
    program, before = official_inputs()
    history = _composite([direct('https://www1.mbrace.or.jp/od2/B/202611/b261104.lzh', 'c',
                                '2026-11-05T18:00:00+09:00'),
                          direct('https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh', 'd',
                                '2026-11-05T18:00:00+09:00')], 'official-history')
    sources = [direct(program['source_url']), direct(before['source_url'], 'b', before['captured_at']), history]
    composite = _composite(sources, 'boat-native-inputs')
    return dict(as_of=ASOF, source_evidence=sources+[composite], snapshot=dict(as_of=ASOF,
        entrants=[dict(source_ref=composite['source_ref'], captured_at=composite['captured_at'], published_at=None)]))


def seller_payload():
    from race_ai.boat_seller_inputs import build_seller_native_inputs
    from tests.test_boat_seller_inputs import sources, DAY, AT
    cards, waku, ids = sources()
    for source in (cards, waku):
        source['source_url'] = ('https://raw.githubusercontent.com/haji84/RACE-AI/'+'a'*40+
                                '/tests/fixtures/fictional-'+source['dataset_kind']+'.csv')
        source['source_rights_ref'] = RIGHTS
    result = build_seller_native_inputs(cards, waku, day=DAY, as_of=AT, expected_race_ids=ids)
    payload = result['native_inputs']['seller']; payload['as_of'] = AT
    return payload


class SourceDerivationTests(unittest.TestCase):
    def test_actual_composite_builder_closure_is_recomputed_without_mutation_or_publication(self):
        payload = simple_payload(); before = deepcopy(payload)
        expected = {(source['source_ref'], source['source_rights_ref']) for source in payload['source_evidence']
                    if source['source_ref'].startswith('urn:')}
        self.assertEqual(guard.validate_source_derivations(payload), expected)
        self.assertTrue(expected)
        self.assertEqual(payload, before)
        self.assertTrue(all(source['published_at'] is None for source in payload['source_evidence']))
        self.assertTrue(all(pair[0].startswith('urn:race-ai:') for pair in expected))

    def test_actual_history_store_nested_manifests_and_native_features_are_accepted(self):
        from race_ai.boat_history_store import HistoryStore
        from tests.test_boat_history_store import archives, DAY
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/'history.sqlite')
            try:
                raw, proofs = archives()
                store.ingest_day(DAY, raw['B'], raw['K'], proofs['B'], proofs['K'])
                program, before = official_inputs()
                result = build_native_inputs(program, before, as_of=ASOF,
                    history_context=dict(history_store=store, history_identity_verified=True))
            finally:
                store.close()
        payload = result['native_inputs']['boat_full']
        before = deepcopy(payload)
        pairs = guard.validate_source_derivations(payload)
        self.assertEqual({pair[0].split(':')[2] for pair in pairs}, {'boat-native-inputs', 'official-history'})
        self.assertEqual(payload, before)
        history = next(source for source in payload['source_evidence'] if ':official-history:' in source['source_ref'])
        self.assertEqual(history['captured_at'], '2026-11-05T18:00:00+09:00')
        self.assertIsNone(history['published_at'])

    def test_nested_urns_are_bound_to_full_ordered_recursive_upstream_manifests(self):
        payload = nested_payload()
        self.assertEqual(len(guard.validate_source_derivations(payload)), 2)
        changes = [lambda p:p['source_evidence'][-1]['source_members'].reverse(),
            lambda p:p['source_evidence'][-1].update(source_sha256='e'*64),
            lambda p:p['source_evidence'][-1]['source_members'][0].update(source_sha256='e'*64),
            lambda p:p['source_evidence'][-1].update(published_at='2030-01-15T08:00:00+09:00'),
            lambda p:p['source_evidence'][-1].update(captured_at=ASOF),
            lambda p:p['source_evidence'][-1]['source_members'][0].update(captured_at='2030-01-15T09:11:00+09:00'),
            lambda p:p['snapshot']['entrants'][0].update(captured_at='2030-01-15T09:11:00+09:00')]
        for change in changes:
            value = deepcopy(payload); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)

    def test_all_available_builder_native_groups_have_complete_replayable_source_closure(self):
        from race_ai.boat_history_store import HistoryStore
        from race_ai.four_sport_learning import fit_training_only
        from tests.test_boat_history_store import archives, DAY
        rows = []; admitted = set(); result_pairs = set()
        for number in range(1, 7):
            day = f'2030-01-{number:02d}'
            program, before = official_inputs()
            program = json.loads(json.dumps(program).replace('2030-01-15', day).replace('20300115', day.replace('-', '')))
            before = json.loads(json.dumps(before).replace('2030-01-15', day).replace('20300115', day.replace('-', '')))
            batch = build_native_inputs(program, before, as_of=day+'T09:10:00+09:00')
            admitted.update((source['source_ref'], source['source_rights_ref']) for source in batch['source_evidence'])
            result_url = 'https://www.boatrace.jp/owpc/pc/race/raceresult?hd='+day.replace('-', '')+'&jcd=17&rno=1'
            result_right = 'OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106'
            result_pairs.add((result_url, result_right))
            rows.append(dict(snapshot=batch['native_inputs']['shared']['snapshot'], result=dict(
                race_id=program['race_id'], status='settled', ordered_top3=[3, 1, 6], published_at=None,
                captured_at=day+'T11:01:00+09:00', source_sha256='f'*64,
                source_ref=result_url, source_rights_ref=result_right)))
        fitted = fit_training_only(rows, sport='boat', train_end_at='2030-01-06T23:59:00+09:00', epochs=1,
            now=lambda:datetime.fromisoformat('2030-01-07T00:00:00+09:00'),
            allow_source=lambda ref, rights, purpose:purpose == 'analysis' and (ref, rights) in admitted,
            allow_result=lambda ref, rights, purpose:purpose == 'result_evaluation' and (ref, rights) in result_pairs)
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/'history.sqlite')
            try:
                raw, proofs = archives(); store.ingest_day(DAY, raw['B'], raw['K'], proofs['B'], proofs['K'])
                program, before = official_inputs()
                result = build_native_inputs(program, before, as_of=ASOF,
                    history_context=dict(history_store=store, history_identity_verified=True, owner_reviewed=True),
                    fitted_model=fitted)
            finally:
                store.close()
        self.assertTrue({'shared', 'shared_learned', 'boat_full', 'boat_ab', 'boat_clite', 'boat_observed', 'boat_tactical'} <=
                        result['native_inputs'].keys())
        for group, payload in result['native_inputs'].items():
            with self.subTest(group=group):
                pairs = guard.validate_source_derivations(payload)
                if group == 'boat_observed':
                    self.assertEqual(pairs, set())
                else:
                    self.assertTrue(pairs)

    def test_clite_exact_program_then_preview_concat_not_manifest_digest(self):
        program, before = official_inputs()
        payload = build_native_inputs(program, before, as_of=ASOF)['native_inputs']['boat_clite']
        pairs = guard.validate_source_derivations(payload)
        self.assertTrue(any(':boat-clite-extra:' in ref for ref, rights in pairs))
        changes = [lambda p:p['source_evidence'][-1]['source_members'].reverse(),
            lambda p:p['source_evidence'][-1].update(transform_id='UNKNOWN'),
            lambda p:p['source_evidence'][-1].update(captured_at=program['captured_at']),
            lambda p:p['source_evidence'][-1]['source_members'][0].update(source_ref=before['source_url'])]
        for change in changes:
            value = deepcopy(payload); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)
        value = deepcopy(payload); source = value['source_evidence'][-1]
        forged = digest(source['source_members'])
        source.update(source_ref='urn:race-ai:boat-clite-extra:'+forged, source_sha256=forged)
        with self.assertRaisesRegex(ValueError, 'CLITE_COMPOSITE_HASH'):
            guard.validate_source_derivations(value)

    def test_unmanifested_lightweight_references_unknown_namespaces_and_wrong_rights_fail(self):
        payload = simple_payload()
        urn = next(source['source_ref'] for source in payload['source_evidence'] if source['source_ref'].startswith('urn:'))
        cases = [dict(as_of=ASOF, source_ref=urn, source_rights_ref=RIGHTS),
            dict(as_of=ASOF, source_ref='urn:race-ai:arbitrary:'+'a'*64, source_rights_ref=RIGHTS),
            dict(as_of=ASOF, unrelated='URN:race-ai:boat-native-inputs:'+'a'*64),
            dict(source_evidence=payload['source_evidence'])]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)
        value = deepcopy(payload)
        value['source_evidence'][-1]['source_rights_ref'] = 'UNREVIEWED_LICENSE'
        with self.assertRaises(ValueError):
            guard.validate_source_derivations(value)

    def test_local_feature_reference_sha_rights_clock_and_manifest_conflicts_fail(self):
        payload = nested_payload(); composite = payload['source_evidence'][-1]
        feature = dict(value=.5, source_ref=composite['source_ref'], source_sha256=composite['source_sha256'],
            source_rights_ref=RIGHTS, published_at=None, captured_at=composite['captured_at'])
        payload['feature'] = feature
        guard.validate_source_derivations(payload)
        for field, bad in [('source_sha256', 'e'*64), ('source_rights_ref', 'unknown'),
                           ('captured_at', ASOF), ('published_at', ASOF)]:
            value = deepcopy(payload); value['feature'][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)
        value = deepcopy(payload)
        conflicting = deepcopy(value['source_evidence'][-1]); conflicting['captured_at'] = ASOF
        value['source_evidence'].append(conflicting)
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_LOCAL_MANIFEST'):
            guard.validate_source_derivations(value)

    def test_direct_upstream_guards_keep_existing_hosts_rights_and_source_clocks(self):
        original = nested_payload()
        for url, rights in [('https://foreign.example/source', RIGHTS),
                ('https://www.boatrace.jp/source#fragment', RIGHTS),
                ('https://user:pass@www.boatrace.jp/source', RIGHTS),
                ('https://raw.githubusercontent.com/another/repo/source', RIGHTS),
                ('https://www.boatrace.jp/source', 'UNREVIEWED_LICENSE')]:
            source = direct(url); source['source_rights_ref'] = rights
            composite = _composite([source], 'boat-native-inputs')
            value = dict(as_of=ASOF, source_evidence=[source, composite])
            with self.subTest(url=url, rights=rights), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)
        value = deepcopy(original)
        value['source_evidence'][0]['published_at'] = '2030-01-15T08:51:00+09:00'
        with self.assertRaises(ValueError):
            guard.validate_source_derivations(value)
        self.assertEqual(guard.validate_source_derivations(dict(scope='SYNTHETIC_ONLY',
            source_ref='synthetic://fixture', source_rights_ref='fictional')), set())

    def pdca(self):
        from race_ai.boat_history_store import HistoryStore
        from tests.test_boat_history_store import archives, DAY
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/'history.sqlite')
            try:
                raw, proofs = archives()
                store.ingest_day(DAY, raw['B'], raw['K'], proofs['B'], proofs['K'])
                program, before = official_inputs()
                facts = dict(race_id=program['race_id'], captured_at=before['captured_at'],
                    cutoff_at=program['closed_at'], source_url=before['source_url'], source_sha256='b'*64,
                    program_sha256='a'*64, rights_verified=True, license_purpose='private_analysis')
                return pdca_payload_from_history(facts, as_of=ASOF,
                    history_context=dict(history_store=store, history_identity_verified=True, owner_reviewed=True),
                    source_evidence=[direct(program['source_url']), direct(before['source_url'], 'b', before['captured_at'])])
            finally:
                store.close()

    def test_actual_pdca_builder_report_bytes_are_bound_to_verified_archive_members(self):
        payload = self.pdca(); before = deepcopy(payload)
        pairs = guard.validate_source_derivations(payload)
        self.assertEqual(len(pairs), len(payload['rows']))
        self.assertTrue(all(':pdca-history-report:' in ref for ref, rights in pairs))
        self.assertEqual(payload, before)
        self.assertTrue(all(member['published_at'] is None for source in payload['source_evidence']
                            for member in source.get('source_members', [])))

    def test_pdca_report_forgery_semantics_reordered_rows_and_wrong_members_fail(self):
        payload = self.pdca()
        self.assertGreater(len(payload['rows']), 1)
        changes = [lambda p:p['rows'].reverse(),
            lambda p:p['rows'][0].update(report_sha256='e'*64),
            lambda p:p['rows'][0].update(report_json=p['rows'][0]['report_json']+' '),
            lambda p:p['rows'][0].update(db_saved_at=ASOF),
            lambda p:next(s for s in p['source_evidence'] if s['source_ref'].startswith('urn:'))['source_members'][0].update(source_sha256='e'*64)]
        for change in changes:
            value = deepcopy(payload); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)
        value = deepcopy(payload)
        report = json.loads(value['rows'][0]['report_json']); report['source_sha256'] = 'e'*64
        old = value['rows'][0]['report_sha256']; new = digest(report)
        value['rows'][0].update(report_json=canonical(report), report_sha256=new)
        source = next(s for s in value['source_evidence'] if s['source_ref'].endswith(old))
        source.update(source_ref='urn:race-ai:pdca-history-report:'+new, source_sha256=new)
        with self.assertRaisesRegex(ValueError, 'UPSTREAM_BINDING'):
            guard.validate_source_derivations(value)

    def test_actual_seller_csv_projections_preserve_days_metric_semantics_and_unknown_publication(self):
        payload = seller_payload(); before = deepcopy(payload)
        pairs = guard.validate_source_derivations(payload)
        self.assertEqual({ref.split(':')[2] for ref, rights in pairs}, {'seller-race_cards', 'seller-waku10'})
        self.assertEqual(payload, before)
        for source in payload['source_evidence']:
            if 'captured_at' in source:
                self.assertEqual(source['captured_at'], '2030-01-15T05:00:00+09:00')
                self.assertIsNone(source['published_at'])

    def test_seller_projection_or_upstream_semantic_tampering_is_rejected(self):
        payload = seller_payload()
        changes = [lambda p:next(iter(p['cards'].values())).update(艇1_全国勝率='9.9'),
            lambda p:p['source_evidence'][1]['source_members'][0].update(dataset_kind='waku10'),
            lambda p:p['source_evidence'][1]['source_members'][0].update(event_date_jst='2030-01-14'),
            lambda p:p['source_evidence'][1]['source_members'][0].update(metric_semantics='PERCENT'),
            lambda p:p['source_evidence'][1].update(transform_id='UNKNOWN'),
            lambda p:p['source_evidence'][1]['source_members'].append(deepcopy(p['source_evidence'][0]))]
        for change in changes:
            value = deepcopy(payload); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                guard.validate_source_derivations(value)

    def test_object_cycles_depth_count_and_member_bounds_fail_closed(self):
        value = {}; value['self'] = value
        with self.assertRaisesRegex(ValueError, 'CYCLIC_PAYLOAD'):
            guard.validate_source_derivations(value)
        value = simple_payload(); nested = value
        for _ in range(guard.MAX_DEPTH+1):
            nested['child'] = {}; nested = nested['child']
        with self.assertRaisesRegex(ValueError, 'BOUND'):
            guard.validate_source_derivations(value)
        with patch.object(guard, 'MAX_NODES', 3), self.assertRaisesRegex(ValueError, 'BOUND'):
            guard.validate_source_derivations(simple_payload())
        with patch.object(guard, 'MAX_MEMBERS', 1), self.assertRaisesRegex(ValueError, 'SOURCE_MEMBERS'):
            guard.validate_source_derivations(simple_payload())
        local = 'urn:race-ai:boat-native-inputs:'+'a'*64
        member = dict(source_ref=local, source_sha256='a'*64, source_rights_ref=RIGHTS,
                      captured_at=ASOF, published_at=None)
        definition = dict(member, source_members=[member])
        with self.assertRaisesRegex(ValueError, 'CYCLIC_LOCAL_MANIFEST'):
            guard.validate_source_derivations(dict(as_of=ASOF, source_evidence=[definition]))


if __name__ == '__main__':
    unittest.main()
