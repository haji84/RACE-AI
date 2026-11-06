"""Synthetic private P1 archives, real owner encryption, no external requests."""
from copy import deepcopy
from datetime import timedelta, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_venue_learning import read_candidate, seal_candidate
from race_ai.observed_weight_learning import seal
from tests import test_boat_venue_research_forecast as forecast_tests
from tests import test_observed_p1_connection as p1_tests

NOW = forecast_tests.NOW
RUN_ID = 99
HEAD = 'a' * 40


class ResearchReferenceTests(unittest.TestCase):
    def api(self):
        module = importlib.import_module('race_ai.boat_venue_research_receipt')
        if not hasattr(module, 'validate_research_refs'):
            self.fail('private artifact handles cannot survive continuity recovery safely')
        return module

    def reference(self, artifact_id=800):
        return dict(artifact_id=artifact_id, run_id=99, head_sha=HEAD, digest='sha256:'+'d'*64)

    def test_normalizes_sorted_copies_without_a_key_or_admission_claim(self):
        api = self.api()
        values = [self.reference(801), self.reference(800)]
        original = deepcopy(values)
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch.object(
                api, 'state_key', side_effect=AssertionError('references are not artifact admission')):
            result = api.validate_research_refs(values)
        self.assertEqual(result, [self.reference(800), self.reference(801)])
        self.assertEqual(values, original)
        result[0]['run_id'] = 100
        self.assertEqual(values, original)
        self.assertEqual(api.validate_research_refs([]), [])

    def test_identical_duplicate_handles_merge_but_conflicting_identity_stops(self):
        api = self.api()
        reference = self.reference()
        self.assertEqual(api.validate_research_refs([reference, deepcopy(reference)]), [reference])
        for key, value in (('run_id', 100), ('head_sha', 'b'*40), ('digest', 'sha256:'+'e'*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.validate_research_refs([reference, dict(reference, **{key: value})])

    def test_rejects_inexact_fields_boolean_ids_and_noncanonical_hashes(self):
        api = self.api()
        invalid = [None, {}, (), 'handles', [None], [dict(self.reference(), extra=True)],
                   [{k:v for k,v in self.reference().items() if k != 'digest'}]]
        for key, value in (('artifact_id', True), ('artifact_id', 0), ('artifact_id', '800'),
                           ('run_id', False), ('run_id', -1), ('head_sha', 'A'*40),
                           ('head_sha', 'main'), ('digest', 'd'*64),
                           ('digest', 'sha256:'+'D'*64), ('digest', 'sha256:'+'d'*63)):
            invalid.append([dict(self.reference(), **{key: value})])
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.validate_research_refs(value)

    def test_bounds_input_handles_before_deduplication(self):
        api = self.api()
        values = [self.reference(i) for i in range(1, 10_001)]
        self.assertEqual(len(api.validate_research_refs(values)), 10_000)
        with self.assertRaises(ValueError):
            api.validate_research_refs([self.reference()]*10_001)


class PrivateP1ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_class = forecast_tests.PrivateVenueForecastTests
        fixture_class.setUpClass()
        cls.addClassCleanup(fixture_class.doClassCleanups)
        cls.fixture = fixture_class()
        cls.payloads = None

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_research_receipt')
        except ModuleNotFoundError:
            self.fail('private P1 ciphertext has no independent artifact admission reader')

    def prepare(self):
        if type(self).payloads is not None:
            return
        api = importlib.import_module('race_ai.boat_venue_research_forecast')
        payloads = []
        with tempfile.TemporaryDirectory(prefix='private-p1-receipt-fixture-') as temporary:
            for number in range(1, 5):
                base, extra, provenance = p1_tests.inputs()
                base.update(race_id=f'20300401-17-{number:02d}',
                            cutoff_at=(NOW+timedelta(minutes=30)).astimezone(
                                timezone(timedelta(hours=9))).isoformat(),
                            captured_at=(NOW+timedelta(minutes=9)).isoformat())
                extra.update(race_id=base['race_id'], observed_at=base['captured_at'])
                provenance.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(),
                                  preview_captured_at=base['captured_at'])
                for name in ('program_url', 'preview_url'):
                    provenance[name] = provenance[name].replace('jcd=01', 'jcd=17').replace('rno=1', f'rno={number}')
                bundle = p1_tests.bridge.build_bundle(
                    base, extra, (NOW+timedelta(minutes=10)).isoformat(),
                    **provenance, owner_reviewed=True)
                output = Path(temporary)/str(number)
                self.fixture.run_private(api, bundle, output)
                payloads.append(read_candidate(output))
        type(self).payloads = payloads

    def archive(self, payloads=None):
        self.prepare()
        selected = self.payloads[:1] if payloads is None else payloads
        members = {}
        with tempfile.TemporaryDirectory(prefix='private-p1-receipt-archive-') as temporary:
            for index, payload in enumerate(selected):
                root = Path(temporary)/str(index)
                seal_candidate(payload, root)
                race_id = payload['original_bundle']['race_id']
                for name in ('learning.json', 'learning.enc', 'summary.json'):
                    members[race_id+'/'+name] = (root/name).read_bytes()
        return self.zip_members(members), members

    def zip_members(self, members, *, compression=zipfile.ZIP_DEFLATED, duplicate=None, symlink=None):
        output = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(output, 'w', compression=compression) as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, body in members.items():
                if name == symlink:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, body)
                else:
                    archive.writestr(name, body)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
        return output.getvalue()

    def metadata(self, raw, **changes):
        result = dict(id=800, name='boat-venue-research-p1-99-1', expired=False,
                      size_in_bytes=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                      created_at=(NOW+timedelta(minutes=11, seconds=5)).isoformat(),
                      expires_at=(NOW+timedelta(days=7)).isoformat(),
                      workflow_run=dict(id=99, repository_id=1416489937,
                                        head_repository_id=1416489937, head_sha=HEAD))
        result.update(changes)
        return result

    def verify(self, api, raw, metadata=None, **changes):
        arguments = dict(now=NOW+timedelta(minutes=12), expected_run_id=RUN_ID,
                         expected_head_sha=HEAD)
        arguments.update(changes)
        return api.verify_private_p1_artifact(raw, self.metadata(raw) if metadata is None else metadata,
                                              **arguments)

    def test_missing_owner_key_rejects_before_zip_or_metadata_inspection(self):
        api = self.api()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch.object(
                api.zipfile, 'ZipFile', side_effect=AssertionError('must validate owner key first')):
            with self.assertRaises(ValueError):
                self.verify(api, b'not a ZIP', metadata=None)

    def test_one_and_four_races_admit_after_cutoff_without_exposing_forecasts(self):
        api = self.api()
        self.prepare()
        for count in (1, 4):
            raw, _ = self.archive(self.payloads[:count])
            try:
                result = self.verify(api, raw, now=NOW+timedelta(hours=1))
            except ValueError as exc:
                self.fail('valid encrypted multi-race artifact was capped: '+str(exc))
            self.assertEqual(result['status'], 'PRIVATE_VENUE_P1_ARTIFACT_PRE_CUTOFF_VERIFIED')
            self.assertEqual(result['unique_races'], count)
            self.assertEqual(result['baseline_forecast_count'], count*2)
            self.assertEqual(result['learned_forecast_count'], count*2)
            self.assertEqual(result['artifact_id'], 800)
            self.assertEqual(result['workflow_run_id'], 99)
            self.assertEqual(result['head_sha'], HEAD)
            self.assertEqual(len(result['record_sha256']), count)
            self.assertEqual(set(result['record_sha256']), {digest(p) for p in self.payloads[:count]})
            self.assertTrue(result['independent_pre_cutoff_receipt_verified'])
            for name in ('provider_permission_confirmed', 'production_promoted',
                         'actual_purchases', 'plaintext_published'):
                self.assertIs(result[name], False)
            public = json.dumps(result)
            for secret in ('weights', 'ordered_top8', 'participants', 'source_url', '4001', 'payloads', 'snapshot'):
                self.assertNotIn(secret, public)

    def test_wrong_artifact_digest_identity_run_head_name_and_expiry_are_rejected(self):
        api = self.api()
        raw, _ = self.archive()
        original = self.metadata(raw)
        changes = [dict(id=True), dict(id=0), dict(expired=True), dict(expired=0),
                   dict(size_in_bytes=len(raw)+1), dict(digest='sha256:'+'0'*64),
                   dict(name='boat-venue-research-p1-98-1'), dict(name='boat-venue-research-p1-99-0'),
                   dict(name='boat-venue-research-p1-99-01'), dict(name='boat-venue-research-p1-99-1-extra'),
                   dict(expires_at=(NOW+timedelta(minutes=12)).isoformat()),
                   dict(created_at=(NOW+timedelta(minutes=12, microseconds=1)).isoformat()),
                   dict(created_at=NOW.replace(tzinfo=None).isoformat())]
        for name, value in (('id', 98), ('id', True), ('repository_id', 1),
                            ('head_repository_id', 1), ('head_sha', 'b'*40)):
            workflow = dict(original['workflow_run'], **{name: value})
            changes.append(dict(workflow_run=workflow))
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(api, raw, dict(original, **change))
        for expected in (dict(expected_run_id=True), dict(expected_run_id=0),
                         dict(expected_head_sha='main'), dict(now=NOW.replace(tzinfo=None))):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.verify(api, raw, **expected)

    def test_whole_second_saved_clock_has_a_strict_conservative_cutoff_margin(self):
        api = self.api()
        raw, _ = self.archive()
        cutoff = NOW+timedelta(minutes=30)
        for offset in (timedelta(seconds=1), timedelta(microseconds=999_999), timedelta(0)):
            metadata = self.metadata(raw, created_at=(cutoff-offset).isoformat())
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.verify(api, raw, metadata, now=cutoff+timedelta(minutes=1))
        metadata = self.metadata(raw, created_at=(cutoff-timedelta(seconds=1, microseconds=1)).isoformat())
        self.assertTrue(self.verify(api, raw, metadata, now=cutoff+timedelta(minutes=1))[
            'independent_pre_cutoff_receipt_verified'])

    def test_saved_precision_tolerance_never_accepts_a_forecast_from_the_future(self):
        api = self.api()
        raw, _ = self.archive()
        generated = NOW+timedelta(minutes=11)
        metadata = self.metadata(raw, created_at=generated.isoformat())
        self.assertTrue(self.verify(api, raw, metadata, now=generated)['independent_pre_cutoff_receipt_verified'])
        metadata['created_at'] = (generated-timedelta(seconds=1, microseconds=1)).isoformat()
        with self.assertRaises(ValueError):
            self.verify(api, raw, metadata)
        metadata['created_at'] = (generated-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            self.verify(api, raw, metadata)
        metadata['created_at'] = (generated-timedelta(microseconds=500_000)).isoformat()
        with self.assertRaises(ValueError):
            self.verify(api, raw, metadata, now=generated-timedelta(microseconds=1))

    def test_path_traversal_extra_files_duplicate_symlink_and_unsupported_compression_stop(self):
        api = self.api()
        _, members = self.archive()
        name = next(iter(members))
        variants = [dict(members, **{'index.json': b'{}'}),
                    {p.replace('20300401-17-01/', '../'): b for p, b in members.items()},
                    {p.replace('20300401-17-01/', '/20300401-17-01/'): b for p, b in members.items()},
                    {p.replace('/', '\\'): b for p, b in members.items()},
                    {p.replace('/learning.json', '/extra/learning.json'): b for p, b in members.items()},
                    {p: b for p, b in members.items() if not p.endswith('summary.json')}]
        raws = [self.zip_members(v) for v in variants]
        raws += [self.zip_members(members, duplicate=name), self.zip_members(members, symlink=name),
                 self.zip_members(members, compression=zipfile.ZIP_BZIP2)]
        for index, raw in enumerate(raws):
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.verify(api, raw)

    def test_nul_terminated_zip_names_are_rejected_before_python_path_normalization(self):
        api = self.api()
        _, members = self.archive()
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as archive:
            for name, value in members.items():
                info = zipfile.ZipInfo(name)
                info.filename = name+'\0ignored-path'
                archive.writestr(info, value)
        with self.assertRaises(ValueError):
            self.verify(api, body.getvalue())

    def test_encrypted_zip_members_and_empty_or_overlarge_archives_stop(self):
        api = self.api()
        raw, _ = self.archive()
        encrypted = bytearray(raw)
        start = 0
        while True:
            start = encrypted.find(b'PK\x01\x02', start)
            if start < 0:
                break
            flags = struct.unpack_from('<H', encrypted, start+8)[0]
            struct.pack_into('<H', encrypted, start+8, flags | 1)
            start += 4
        for value in (bytes(encrypted), b'', b'x'*(64*1024*1024+1), self.zip_members({})):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                self.verify(api, value)

    def test_per_file_and_uncompressed_total_bounds_apply_before_owner_decryption(self):
        api = self.api()
        _, members = self.archive()
        for name, limit in (('learning.json', 1024*1024),
                            ('learning.enc', 12*1024*1024), ('summary.json', 1024*1024)):
            modified = dict(members)
            modified['20300401-17-01/'+name] = b'x'*(limit+1)
            raw = self.zip_members(modified)
            with self.subTest(name=name), patch.object(api, 'read_candidate',
                    side_effect=AssertionError('reject bounds before owner decrypt')), self.assertRaises(ValueError):
                self.verify(api, raw)
        cipher = b'x'*(12*1024*1024)
        large = {f'20300401-17-{number:02d}/{name}': cipher if name == 'learning.enc' else b'x'
                 for number in range(1, 7) for name in ('learning.json', 'learning.enc', 'summary.json')}
        raw = self.zip_members(large)
        with patch.object(api, 'read_candidate', side_effect=AssertionError('reject total before owner decrypt')):
            with self.assertRaises(ValueError):
                self.verify(api, raw)

    def test_mixed_race_directory_or_more_than_physical_race_universe_cannot_partially_admit(self):
        api = self.api()
        _, members = self.archive()
        wrong = {p.replace('20300401-17-01', '20300401-17-02'): b for p, b in members.items()}
        raw = self.zip_members(dict(members, **wrong))
        with self.assertRaises(ValueError):
            self.verify(api, raw)
        race_ids = [f'20300401-{venue:02d}-{number:02d}'
                    for venue in range(1, 25) for number in range(1, 13)] + ['20300402-01-01']
        excessive = {p.replace('20300401-17-01', race_id): b
                     for race_id in race_ids for p, b in members.items()}
        raw = self.zip_members(excessive)
        with patch.object(api, 'read_candidate', side_effect=AssertionError('reject race count before decrypt')):
            with self.assertRaises(ValueError):
                self.verify(api, raw)

    def test_full_physical_race_universe_fits_archive_boundary_without_a_coverage_cap(self):
        api = self.api()
        self.prepare()
        race_ids = [f'20300401-{venue:02d}-{number:02d}'
                    for venue in range(1, 25) for number in range(1, 13)]
        public = dict(self.payloads[0]['summary'], encrypted_readback_verified=True, plaintext_published=False)
        # This test isolates the archive boundary. Other tests use the real
        # Node decoder and pure native replay for four encrypted race payloads.
        members = {race_id+'/'+name: body for race_id in race_ids for name, body in
                   (('learning.json', b'synthetic-boundary-manifest'),
                    ('learning.enc', b'synthetic-boundary-ciphertext'),
                    ('summary.json', json.dumps(public).encode()))}
        raw = self.zip_members(members)
        def decoded(root):
            race_id = race_ids[int(root.name)]
            payload = deepcopy(self.payloads[0])
            payload['snapshot'].update(race_id='boat:2030-04-01:boatrace-jcd-'+race_id[9:11]+':'+str(int(race_id[-2:])),
                                       venue='boatrace-jcd-'+race_id[9:11])
            return payload
        with patch.object(api, 'read_candidate', side_effect=decoded), \
             patch.object(api, 'verify_private_forecast', return_value=True):
            try:
                result = self.verify(api, raw)
            except ValueError as exc:
                self.fail('valid physical race universe was capped: '+str(exc))
        self.assertEqual(result['unique_races'], 288)
        self.assertEqual(result['baseline_forecast_count'], 576)
        self.assertEqual(result['learned_forecast_count'], 576)

    def test_wrong_owner_key_and_corrupt_cipher_or_public_summary_are_rejected(self):
        import base64
        api = self.api()
        raw, members = self.archive()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()):
            with self.assertRaises(ValueError):
                self.verify(api, raw)
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            modified = dict(members)
            modified['20300401-17-01/'+name] += b'corrupt'
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(api, self.zip_members(modified))
        summary_path = '20300401-17-01/summary.json'
        modified = dict(members)
        public = json.loads(modified[summary_path])
        public['learned_shadow_count'] = 100
        modified[summary_path] = json.dumps(public).encode()
        with self.assertRaises(ValueError):
            self.verify(api, self.zip_members(modified))

    def test_authenticated_baseline_or_learned_tamper_replays_fail_for_entire_archive(self):
        api = self.api()
        self.prepare()
        for field in ('baseline_suite', 'shadows'):
            payload = deepcopy(self.payloads[1])
            if field == 'baseline_suite':
                model = next(iter(payload[field]['models'].values()))
                model['ordered_top8'][0] = [6, 5, 4]
                seal(model, 'prediction_sha256')
                seal(payload[field], 'suite_sha256')
            else:
                payload[field][0]['ordered_top8'][0] = [6, 5, 4]
                seal(payload[field][0], 'prediction_sha256')
            raw, _ = self.archive([self.payloads[0], payload])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(api, raw)

    def test_training_receipt_has_a_full_second_margin_before_the_p1_input(self):
        api = self.api()
        self.prepare()
        payload = deepcopy(self.payloads[0])
        as_of = NOW+timedelta(minutes=11)
        receipt = payload['training_receipt']
        receipt['created_at'] = (as_of-timedelta(microseconds=999_999)).isoformat()
        for record in payload['shadows']:
            record['training_receipt'] = deepcopy(receipt)
            seal(record, 'prediction_sha256')
        raw, _ = self.archive([payload])
        with self.assertRaises(ValueError):
            self.verify(api, raw)
