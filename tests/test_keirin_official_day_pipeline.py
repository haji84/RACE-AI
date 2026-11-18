"""Contract tests for official cohort/secondary-source reconciliation."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
import json
import unittest

from scripts import keirin_capture_public_two_sources as capture


DAY = '2030-01-15'
R1, R2, R3 = '203001152601', '203001152602', '203001152401'


def sample():
    schedule = {'day_jst': DAY, 'races': [
        {'race_id': R1, 'official_cutoff_at': DAY+'T10:47:00+09:00'},
        {'race_id': R2, 'official_cutoff_at': DAY+'T11:12:00+09:00'},
        {'race_id': R3, 'official_cutoff_at': DAY+'T20:47:00+09:00'}]}
    manifest = {'schema': capture.SCHEMA, 'day_jst': DAY,
        'source_use_scope': 'OWNER_PERSONAL_RESEARCH_ONLY', 'races': [
        {'race_id': R1,
         'netkeirin_url': 'https://keirin.netkeiba.com/race/entry/?race_id='+R1,
         'kdreams_url': 'https://keirin.kdreams.jp/seibuen/racedetail/2620300115010001/',
         'cutoff_hint': None}]}
    return schedule, manifest


class OfficialDayReconciliation(unittest.TestCase):
    def implementation(self):
        from scripts import keirin_official_day_pipeline
        return keirin_official_day_pipeline

    def test_official_denominator_keeps_unlinked_races_and_injects_actual_cutoff(self):
        pipeline = self.implementation()
        schedule, manifest = sample()
        result, counts = pipeline.reconcile_manifest(schedule, manifest)
        self.assertEqual(len(schedule['races']), 3)
        self.assertEqual(counts['official_registered_races'], 3)
        self.assertEqual(counts['source_linked_races'], 1)
        self.assertEqual(counts['missing_source_links'], 2)
        self.assertEqual(result['races'][0]['cutoff_hint'], DAY+'T10:47:00+09:00')
        self.assertIsNone(manifest['races'][0]['cutoff_hint'])

    def test_secondary_extra_race_cannot_expand_or_change_official_cohort(self):
        pipeline = self.implementation()
        schedule, manifest = sample()
        extra = deepcopy(manifest['races'][0])
        extra['race_id'] = '203001152699'
        manifest['races'].append(extra)
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_OFFICIAL'):
            pipeline.reconcile_manifest(schedule, manifest)

    def test_duplicate_official_or_secondary_race_is_rejected(self):
        pipeline = self.implementation()
        for side in ('official', 'secondary'):
            schedule, manifest = sample()
            data = schedule if side == 'official' else manifest
            data['races'].append(deepcopy(data['races'][0]))
            with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
                pipeline.reconcile_manifest(schedule, manifest)

    def test_different_day_is_rejected_even_when_ids_look_valid(self):
        pipeline = self.implementation()
        schedule, manifest = sample()
        manifest['day_jst'] = '2030-01-16'
        with self.assertRaisesRegex(ValueError, 'DAY'):
            pipeline.reconcile_manifest(schedule, manifest)

    def test_official_cutoff_must_be_on_race_day(self):
        pipeline = self.implementation()
        schedule, manifest = sample()
        schedule['races'][0]['official_cutoff_at'] = '2030-01-16T00:01:00+09:00'
        with self.assertRaises(ValueError):
            pipeline.reconcile_manifest(schedule, manifest)


class OfficialCollectedSettlement(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from race_ai import keirin_nationwide_auto_generator as model
        from race_ai import keirin_nationwide_auto_storage as storage
        from race_ai import keirin_official_public_source as official
        from tests.test_keirin_nationwide_auto_generator import fixture, AT
        from tests.test_keirin_official_public_source import fixtures
        from tests.test_keirin_github_origin_evidence import evidence_fixture, archive_bytes, report_bytes
        from urllib.parse import parse_qs, urlsplit
        self.rid = '202611182601'
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        root.chmod(0o700)
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
        self.pem = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        patcher = patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', pin)
        patcher.start(); self.addCleanup(patcher.stop)
        snap = fixture()
        forecast = model.generate_A_B(snap, generated_at=AT)
        path = root / 'original.sealed.json'
        rec = storage.seal_once(snapshot=snap, prediction=forecast,
            public_key_pem=public, path=path, sealed_at='2026-11-18T09:01:05+09:00')
        self.original = {'raw_cipher': path.read_bytes(), 'cipher_sha256': rec['cipher_sha256'],
                         'producer_run_id': '123456', 'producer_commit': 'a'*40}
        data = json.loads(json.dumps(fixtures()).replace('20261002', '20261118')
                          .replace('2026/10/02', '2026/11/18'))
        get = lambda url: json.dumps(data[parse_qs(urlsplit(url).query)['type'][0]]).encode()
        clock = lambda: datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
        self.schedule = official.fetch_day_schedule('2026-11-18', fetcher=get, clock=clock)
        self.record = official.fetch_race_result(self.rid, schedule=self.schedule,
                                                fetcher=get, clock=clock)
        producer, readback = evidence_fixture()
        for packet in (producer, readback):
            with ZipFile(BytesIO(packet['archive_bytes'])) as zipped:
                member = zipped.namelist()[0]
                doc = json.loads(zipped.read(member))
            entries = doc.get('new_encrypted_originals', doc.get('records'))
            entries[0]['cipher_sha256'] = self.original['cipher_sha256']
            packet['archive_bytes'] = archive_bytes(member, report_bytes(doc))
            packet['artifact']['digest'] = 'sha256:' + sha256(packet['archive_bytes']).hexdigest()
            packet['artifact']['size_in_bytes'] = len(packet['archive_bytes'])
        self.bundle = {'producer': producer, 'readback': readback}

    def run_pipeline(self):
        from scripts import keirin_official_day_pipeline as pipeline
        return pipeline.settle_collected(schedule=self.schedule,
            originals_by_race={self.rid:self.original},
            official_records_by_race={self.rid:self.record},
            origin_packets_by_race={self.rid:self.bundle}, owner_private_pem=self.pem)

    def test_actual_crypto_official_reparse_server_proof_and_same_cohort_score(self):
        report, rows, proofs = self.run_pipeline()
        self.assertEqual(report['registered_races'], 2)
        self.assertEqual(report['paired_A_B_scored'], 1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(report['scorecard']['national_day_universe_independently_verified'])
        self.assertNotIn('ranked_tickets', json.dumps(report))
        self.assertIn('ranked_tickets', rows[0]['A'])
        self.assertIsNone(rows[1]['A'])
        self.assertEqual(proofs[self.rid]['state'], 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED')

    def test_unbound_result_cannot_be_admitted_by_an_always_true_callback(self):
        self.record['result']['payouts_100yen'][0]['yen'] += 100
        report, rows, proofs = self.run_pipeline()
        self.assertEqual(report['paired_A_B_scored'], 0)
        self.assertEqual(report['official_result_states'][self.rid], 'HOLD_OFFICIAL_SOURCE_RECEIPT_INVALID')

    def test_bad_remote_artifact_cannot_pass_on_valid_local_cipher_alone(self):
        self.bundle['readback']['archive_bytes'] += b'changed'
        report, rows, proofs = self.run_pipeline()
        self.assertEqual(report['paired_A_B_scored'], 0)
        self.assertNotIn(self.rid, proofs)


class OfficialRuntimeBoundaries(unittest.TestCase):
    def test_private_json_bytes_roundtrip_and_malformed_binary_rejected(self):
        from scripts import keirin_official_day_pipeline as pipeline
        value = {'records': [{'source': b'\x00\xff\n', 'counter': 2}]}
        self.assertEqual(pipeline.restore_private_snapshot_json(
            pipeline.private_snapshot_json(value)), value)
        with self.assertRaises(ValueError):
            pipeline.restore_private_snapshot_json({'encoding':'base64','bytes':'bad!!!'})

    def test_live_official_gate_is_checked_before_transport(self):
        from scripts import keirin_official_day_pipeline as pipeline
        with patch.dict('os.environ', {}, clear=True), \
                patch('race_ai.keirin_official_public_source._http_get') as get:
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED'):
                pipeline.official_fetcher(Path('/unused'), lambda: datetime.now(timezone.utc))
            get.assert_not_called()

    def test_result_queue_keeps_full_cohort_and_revisits_completed_results(self):
        from scripts import keirin_official_day_pipeline as pipeline
        schedule = {'races': [
            {'race_id':f'2026111826{n:02d}', 'official_cutoff_at':'2026-11-18T10:00:00+09:00'}
            for n in range(1, 11)]}
        now = datetime.fromisoformat('2026-11-18T20:00:00+09:00')
        records = {r['race_id']:{'state':'OFFICIAL_FINAL'} for r in schedule['races']}
        first = pipeline.select_result_races(schedule, records, {}, now, max_races=8)
        later = pipeline.select_result_races(schedule, records, {},
                    now.replace(minute=10), max_races=8)
        self.assertEqual(len(first), 8)
        self.assertEqual(set(first) | set(later), {r['race_id'] for r in schedule['races']})
        self.assertEqual(len(schedule['races']), 10)

    def test_result_queue_does_not_fetch_a_future_result(self):
        from scripts import keirin_official_day_pipeline as pipeline
        schedule={'races':[{'race_id':'202611182601',
            'official_cutoff_at':'2026-11-18T20:00:00+09:00'}]}
        chosen=pipeline.select_result_races(schedule, {}, {},
            datetime.fromisoformat('2026-11-18T19:59:00+09:00'), max_races=8)
        self.assertEqual(chosen, [])


class OfficialBatchRuntime(unittest.TestCase):
    def test_one_client_is_shared_and_denial_visible_across_day_boundaries(self):
        from scripts import keirin_official_day_pipeline as pipeline
        days=['2026-11-19','2026-11-18','2026-11-02']
        seen=[]
        class Client:
            stopped_reason=None
        client=Client()
        def settle(**kw):
            seen.append(kw['github_client'])
            kw['github_client'].stopped_reason='GITHUB_EVIDENCE_HTTP_403'
            return {'day_jst':kw['day'], 'registered_races':2,
                    'paired_A_B_scored':0,'github_evidence_state':client.stopped_reason}
        with TemporaryDirectory() as tmp, \
             patch.object(pipeline,'check_owner_private_key'), \
             patch.object(pipeline,'official_fetcher',return_value=lambda _:b'fixture') as official_get, \
             patch('scripts.keirin_official_backlog_days.discover_days',return_value=days), \
             patch('scripts.keirin_official_backlog_days.select_days',return_value=days), \
             patch('race_ai.keirin_github_evidence_client.GitHubEvidenceClient',return_value=client) as create, \
             patch.object(pipeline,'run_settlement',side_effect=settle):
            Path(tmp).chmod(0o700)
            report=pipeline.run_settlement_days(repo=Path('/unused'),private_root=Path(tmp),
                owner_public_path='/unused/public.pem',owner_private_pem=b'fixture',
                clock=lambda:datetime.fromisoformat('2026-11-19T12:00:00+09:00'))
            self.assertEqual(create.call_count,1)
            self.assertEqual(official_get.call_count,1)
            self.assertEqual(seen,[client,client,client])
            self.assertEqual(report['days_held'],3)
            self.assertEqual(report['github_evidence_state'],'GITHUB_EVIDENCE_HTTP_403')
            self.assertTrue(all((Path(tmp)/day/'safe.json').is_file() for day in days))

    def test_failure_to_persist_provider_stop_ends_batch_before_another_day(self):
        from scripts import keirin_official_day_pipeline as pipeline
        from race_ai.keirin_github_provider_stop import ProviderStopPersistenceError
        days=['2026-11-19','2026-11-18','2026-11-02']
        with TemporaryDirectory() as tmp, \
             patch.object(pipeline,'check_owner_private_key'), \
             patch.object(pipeline,'official_fetcher',return_value=lambda _:b'fixture'), \
             patch('scripts.keirin_official_backlog_days.discover_days',return_value=days), \
             patch('scripts.keirin_official_backlog_days.select_days',return_value=days), \
             patch.object(pipeline,'run_settlement',side_effect=ProviderStopPersistenceError(
                 'PROVIDER_STOP_PERSISTENCE_FAILED_NO_RETRY')) as settle:
            Path(tmp).chmod(0o700)
            report=pipeline.run_settlement_days(repo=Path('/unused'),private_root=Path(tmp),
                owner_public_path='/unused/public.pem',owner_private_pem=b'fixture')
            self.assertEqual(settle.call_count,1)
            self.assertEqual(report['days_not_attempted'],2)
            self.assertEqual(report['days_held'],1)

    def test_invalid_existing_private_key_stops_before_git_discovery(self):
        from scripts import keirin_official_day_pipeline as pipeline
        with patch('scripts.keirin_official_backlog_days.discover_days') as discover:
            with self.assertRaisesRegex(ValueError,'PRIVATE_SECRET_INVALID'):
                pipeline.run_settlement_days(repo=Path('/unused'),private_root=Path('/unused'),
                    owner_public_path='/unused/public.pem',owner_private_pem=b'not-a-key')
            discover.assert_not_called()

    def test_official_refusal_latch_survives_midnight_in_same_batch(self):
        from scripts import keirin_official_day_pipeline as pipeline
        from race_ai import keirin_official_public_source as official
        days=['2026-11-18','2026-11-17']
        clocks=iter([datetime.fromisoformat('2026-11-18T23:59:59+09:00'),
                     datetime.fromisoformat('2026-11-19T00:00:01+09:00')])
        now=[next(clocks)]
        calls=[]
        def denied(url):
            calls.append(url)
            raise official.OfficialProviderStop(403)
        shared=pipeline.official_fetcher(Path('/unused'),lambda:now[0],fetch=denied)
        def settle(**kw):
            with self.assertRaises(official.OfficialProviderStop):
                kw['shared_official_fetch']('https://keirin.jp/pc/json?fixture')
            now[0]=datetime.fromisoformat('2026-11-19T00:00:01+09:00')
            return {'day_jst':kw['day'],'provider_state':'HOLD_OFFICIAL_PROVIDER_STOPPED_THIS_POLL'}
        with TemporaryDirectory() as tmp, \
             patch.object(pipeline,'check_owner_private_key'), \
             patch.object(pipeline,'official_fetcher',return_value=shared), \
             patch('race_ai.keirin_github_provider_stop.record_denial') as persist, \
             patch('scripts.keirin_official_backlog_days.discover_days',return_value=days), \
             patch('scripts.keirin_official_backlog_days.select_days',return_value=days), \
             patch.object(pipeline,'run_settlement',side_effect=settle):
            Path(tmp).chmod(0o700)
            report=pipeline.run_settlement_days(repo=Path('/unused'),private_root=Path(tmp),
                owner_public_path='/unused/public.pem',owner_private_pem=b'fixture',clock=lambda:now[0])
            self.assertEqual(len(calls),1)
            self.assertEqual(persist.call_count,1)
            self.assertEqual(report['days_held'],2)

if __name__ == '__main__':
    unittest.main()
