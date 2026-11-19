"""Invented S pairs, original HTML and actual local Git MAC/AES only."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'owner-source'
sys.path.insert(0, str(OWNER))
import race_ai, scripts, tests
for folder in ('pr64-reference', 'pr72-reference'):
    race_ai.__path__.append(str(OWNER / folder / 'race_ai'))
scripts.__path__.append(str(ROOT / 'scripts'))
tests.__path__.append(str(OWNER / 'tests'))

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import importlib.util
import io
import json
import os
import struct
import unittest
import zipfile
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_private_original_vault as vault
from race_ai import boat_official_program as program
from race_ai import official_race_updates as result_parser
from race_ai.all_existing_model_learning import fit
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_venue_learning import read_candidate
from race_ai.observed_p1_connection import RIGHTS
from tests import test_boat_current_pair_eligibility_audit as current
from tests import test_boat_private_original_vault as vault_fixture
from tests.test_all_existing_model_learning import observed_records


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = ROOT / 'scripts/boat_native_pair_raw_evidence.py'
facade = load('main_native_pair_raw', MODULE) if MODULE.is_file() else None
program_fixture = load('native_raw_program_fixture', OWNER / 'tests/test_boat_official_program.py')
result_fixture = load('native_raw_result_fixture', OWNER / 'pr64-reference/tests/test_official_race_updates.py')
SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
KEY = bytes(range(32))
DAY = date(2030, 4, 1)
NOW = current.NOW


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def receipt(raw, url, at):
    return wire(dict(source_url=url, captured_at=at, http_status=200,
                     source_sha256=sha256(raw).hexdigest()))


class TrackedReader:
    def __init__(self, reader, commit):
        self.reader, self.commit, self.calls = reader, commit, []
        self.repo, self.ref = reader.repo, reader.ref

    def fetch(self, commit):
        if commit != self.commit:
            raise AssertionError('snapshot substituted')
        return self.reader.fetch(commit)

    def exists(self, commit, path):
        if commit != self.commit:
            raise AssertionError('snapshot substituted')
        return self.reader.exists(commit, path)

    def read(self, commit, path, maximum):
        if commit != self.commit:
            raise AssertionError('snapshot substituted')
        self.calls.append(path)
        return self.reader.read(commit, path, maximum)

    def head(self):
        raise AssertionError('immutable snapshot must not consult mutable head')


class NativePairRawEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = observed_records(synthetic=False)
        cls.training = fit(cls.records, now=current.TRAIN_NOW,
                           allow_source=lambda *_: True, allow_training=lambda *_: True)

    def setUp(self):
        source = patch.object(current, 'SOURCE', SOURCE)
        source.start(); self.addCleanup(source.stop)
        self.f = current.CurrentPairEligibilityTests('runTest')
        self.f.records, self.f.training = self.records, self.training
        self.f.cell = 'boat/boat-observed-pairwise-factor-v1'
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.program_url = 'https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=24&hd=20300401'
        self.result_url = self.program_url.replace('/racelist?', '/raceresult?')
        self.program_at = '2030-04-01T08:09:59+00:00'
        self.result_at = '2030-04-01T08:31:00+00:00'
        self.program_raw = program_fixture.page(venue='24', race_no=1).replace(b'20:30', b'17:30')
        body = result_fixture.results()
        extra = ''.join(f'<tr><td>{kind}</td><td>{ticket}</td><td>100</td><td>1</td></tr>'
            for kind, ticket in (('3連複', '1=2=3'), ('2連単', '1-2'), ('2連複', '1=2'),
                                 ('単勝', '1'), ('複勝', '1'), ('複勝', '2'),
                                 ('拡連複', '1=2'), ('拡連複', '1=3'), ('拡連複', '2=3')))
        body = body.replace('</tbody></table><table><thead><tr><th>返還',
                            extra + '</tbody></table><table><thead><tr><th>返還')
        self.result_raw = result_fixture.page('raceresult', body, day=DAY).replace(
            b'jcd=18', b'jcd=24').replace(b'08:43', b'17:30')
        seed = current.pair_fixture.AllExistingModelPrivatePairsTests('runTest')
        seed.records = self.records
        self.native = seed.native(1)
        snapshot = self.native['snapshot']
        snapshot.update(scope='OPERATOR_SUPPLIED_RESEARCH', stage='P1', as_of=self.program_at)
        self.native['scope'] = 'OPERATOR_SUPPLIED_RESEARCH'
        participant = snapshot['participants'][0]
        participant['features']['exhibition_time_seconds'] = dict(value=6.9, sample_n=None,
            source_id=snapshot['race_source_id'], transform_id='official_exhibition_time_seconds_v1')
        participant['missing'].pop('exhibition_time_seconds', None)
        for item in snapshot['sources']:
            item['captured_at'] = self.program_at
            item['published_at'] = None
            if item['source_id'] == snapshot['race_source_id']:
                item['source_url'] = 'https://www.boatrace.jp/owpc/pc/race/racelist'
                item['source_sha256'] = sha256(self.program_raw).hexdigest()
                item['source_rights_ref'] = RIGHTS
                item['evidence_basis'] = 'CAPTURED_BY_CLAIM'
        self.make_pairs()
        self.observation = result_parser.parse_update(self.result_raw, kind='raceresult',
            day=DAY, venue='24', race_no=1, source_url=self.result_url,
            captured_at=self.result_at, entries=None)
        self.assertTrue(self.observation['data']['confirmed'], 'fixture must be an ordinary complete result')
        self.f.results(1, [])
        self.f.results(2, [self.observation])
        self.retain()

    def make_pairs(self):
        self.f.pair_build += 1
        folder = self.f.root / ('raw-pairs-' + str(self.f.pair_build))
        make_private_pairs(self.f.context, [dict(cell_key=cell, native_payload=deepcopy(self.native))
            for cell in self.training['models']], folder, now=current.FORECAST_NOW,
            allow_source=lambda *_: True)
        self.payloads = {read_candidate(child)['cell_key']: read_candidate(child)
                         for child in folder.iterdir() if child.is_dir()}
        raw = current.packed({child.name + '/' + name: (child / name).read_bytes()
            for child in folder.iterdir() if child.is_dir()
            for name in ('learning.json', 'learning.enc', 'summary.json')})
        self.f.add(800, 'all-existing-model-pairs-99-1', raw, '2030-04-01T08:10:03Z')

    def captures(self):
        return [(self.program_raw, receipt(self.program_raw, self.program_url, self.program_at)),
                (self.result_raw, receipt(self.result_raw, self.result_url, self.result_at))]

    def retain(self, captures=None, *, later_head=SOURCE, later_run=99):
        fixture = vault_fixture.VaultTests('runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.writer = fixture.git('native-raw-writer', ref=vault.VAULT_REF)
        reader = fixture.git('native-raw-reader', ref=vault.VAULT_REF)
        parent = self.writer.commit({'unrelated/cipher.enc': b'existing'}, None)
        self.writer.push(parent, None)
        unrelated = b'<p>unrelated invented beforeinfo</p>'
        other = receipt(unrelated, self.program_url.replace('/racelist?', '/beforeinfo?'), self.program_at)
        records = [vault._capture_record(self.captures() if captures is None else captures,
                                        run_id=99, head_sha=SOURCE, now=NOW),
                   vault._capture_record([(unrelated, other)], run_id=later_run,
                                        head_sha=later_head, now=NOW)]
        self.retained = vault._retain(records, self.writer.repo, expected_parent=parent,
            key=KEY, transport=self.writer, readback_transport=reader, now=NOW)
        self.snapshot = self.retained['source_commit']
        self.reader = TrackedReader(reader, self.snapshot)

    def change_entry(self, index, change):
        locator = self.retained['locators'][index]
        parent = self.snapshot
        _, mac = vault._keys(KEY)
        batch = vault._unsigned(self.writer.read(parent, locator['batch_path'], vault.MAX_INDEX), mac)
        entry = next(row for row in batch['entries'] if sha256(vault._wire(row)).hexdigest() == locator['entry_sha256'])
        blobs = change(entry) or {}
        raw = vault._signed(batch, mac); sha = sha256(raw).hexdigest()
        path = vault.PREFIX + '2030-04/batches/' + sha + '.json'
        reference = {name: locator[name] for name in ('batch_path', 'batch_sha256', 'entry_sha256', 'artifact_id', 'kind')}
        reference.update(batch_path=path, batch_sha256=sha, entry_sha256=digest(entry))
        run_path = vault.PREFIX + '2030-04/runs/99.json'
        run = vault._unsigned(self.writer.read(parent, run_path, vault.MAX_INDEX), mac)
        for name, old in run['entries'].items():
            if old['entry_sha256'] == locator['entry_sha256']:
                run['entries'][name] = reference
        run_raw = vault._signed(run, mac)
        month_path = vault.PREFIX + '2030-04/month.json'
        month = vault._unsigned(self.writer.read(parent, month_path, vault.MAX_INDEX), mac)
        month['runs']['99'] = sha256(run_raw).hexdigest()
        commit = self.writer.commit({path: raw, run_path: run_raw,
            month_path: vault._signed(month, mac), **blobs}, parent)
        self.writer.push(commit, parent)
        self.snapshot = self.reader.commit = commit

    def api(self, **changes):
        self.assertIsNotNone(facade, 'strict native per-pair raw facade is missing')
        values = dict(get=self.f.get, repo=self.reader.repo, run_id=99, pair_artifact_id=800,
            record_sha256=digest(self.payloads[self.f.cell]), vault_snapshot_commit=self.snapshot,
            now=NOW, key=KEY, transport=self.reader)
        values.update(changes)
        return facade.audit_native_pair_raw_evidence(**values)

    def assert_hold(self, value):
        public = value['public']
        self.assertEqual(public['raw_status'], 'HOLD')
        self.assertIs(public['raw_program_match'], False)
        self.assertIs(public['raw_result_match'], False)
        self.assertIs(public['formal_qualified'], False)
        self.assertEqual(public['formal_status'], 'HOLD_UNPROVEN_PUBLICATION_AND_ACTUAL_CLOSE')
        self.assertIsNone(value['private'])
        self.assert_safe(value)

    def assert_safe(self, value):
        public = value['public']
        self.assertTrue(all(type(v) in (str, int, bool, type(None)) for v in public.values()))
        encoded = json.dumps(public)
        for secret in ('https://', '20300401-24-01', 'PRIVATE_RESULT_SENTINEL', '選手', 'roster', 'payout'):
            self.assertNotIn(secret, encoded)
        self.assertIsNone(public['upstream_published_at'])
        self.assertIsNone(public['actual_voting_closed_at'])
        self.assertEqual(public['source_requests'], 0)

    def test_equal_normal_cutoffs_require_real_raw_evidence_for_both_existing_cells(self):
        before = deepcopy((self.payloads, self.f.raws, self.f.metas))
        for cell, payload in self.payloads.items():
            with self.subTest(cell=cell):
                value = self.api(record_sha256=digest(payload))
                public, private = value['public'], value['private']
                self.assertEqual(public['raw_status'], 'RAW_SOURCE_REPLAY_MATCH')
                for name in ('raw_program_match', 'raw_result_match', 'registered_identities_match', 'capture_clocks_match'):
                    self.assertIs(public[name], True)
                self.assertEqual(public['comparison_count'], 1)
                self.assertEqual(public['formal_status'], 'HOLD_UNPROVEN_PUBLICATION_AND_ACTUAL_CLOSE')
                self.assertIs(public['formal_qualified'], False)
                self.assertEqual(private['record_sha256'], digest(payload))
                self.assertEqual(private['input_sha256'], payload['pair']['input_sha256'])
                self.assertEqual(private['result_observation_sha256'], digest(self.observation))
                self.assertEqual(private['result_snapshot']['observed_at'], NOW.isoformat())
                self.assertEqual(private['result_snapshot'].get('completed_rounds'), [1, 2])
                self.assertEqual(private['result_snapshot'].get('owner_source_commit'), SOURCE)
                self.assertEqual(private['vault_snapshot_commit'], self.snapshot)
                self.assert_safe(value)
        self.assertEqual((self.payloads, self.f.raws, self.f.metas), before)

    def test_missing_raw_or_wrong_original_receive_clock_never_qualifies(self):
        for mode in ('missing_program', 'program_clock', 'result_clock', 'url'):
            captures = self.captures()
            if mode == 'missing_program': captures = captures[1:]
            else:
                number = 1 if mode == 'result_clock' else 0
                meta = json.loads(captures[number][1])
                if mode == 'url': meta['source_url'] = self.program_url.replace('rno=1&', 'rno=2&')
                else: meta['captured_at'] = '2030-04-01T08:10:00+00:00'
                captures[number] = (captures[number][0], wire(meta))
            self.retain(captures)
            with self.subTest(mode=mode): self.assert_hold(self.api())

    def test_every_later_header_is_authenticated_before_opening_any_candidate(self):
        def extra(entry):
            entry['header']['files']['capture-9999.raw'] = dict(size=1, sha256='a' * 64)
        self.change_entry(1, extra)
        self.assert_hold(self.api())
        self.assertFalse(any('/chunks/' in path for path in self.reader.calls))

    def test_month_mac_missing_run_and_inventory_total_disagreement_are_rejected(self):
        for mode in ('mac', 'count', 'missing_run'):
            self.retain()
            path = vault.PREFIX + '2030-04/month.json'
            _, mac = vault._keys(KEY)
            value = vault._unsigned(self.writer.read(self.snapshot, path, vault.MAX_INDEX), mac)
            if mode == 'count': value['entries'] += 1
            elif mode == 'missing_run': value['runs'].pop('99')
            raw = vault._signed(value, mac)
            if mode == 'mac':
                at = raw.index(b'"mac":"') + len(b'"mac":"')
                raw = raw[:at] + (b'a' if raw[at:at + 1] != b'a' else b'b') + raw[at + 1:]
            commit = self.writer.commit({path: raw}, self.snapshot)
            self.writer.push(commit, self.snapshot)
            self.snapshot = self.reader.commit = commit
            with self.subTest(mode=mode): self.assert_hold(self.api())

    def test_foreign_run_or_source_header_is_not_silently_excluded(self):
        self.retain(later_head='f' * 40)
        self.assert_hold(self.api())
        self.retain(later_run=100)
        # A foreign run is not part of the requested run index; the selected
        # capture's own header must nevertheless never be relabelled.
        self.change_entry(0, lambda entry: entry['header']['summary'].update(run_id=100))
        self.assert_hold(self.api())

    def test_unknown_or_missing_numbered_header_inventory_is_rejected(self):
        for mode in ('missing_json', 'wrong_number', 'bool_count'):
            self.retain()
            def change(entry):
                files = entry['header']['files']
                if mode == 'missing_json': files.pop('capture-0000.json')
                elif mode == 'wrong_number': files['capture-0009.json'] = files.pop('capture-0000.json')
                else: entry['header']['summary']['capture_count'] = True
            self.change_entry(1, change)
            with self.subTest(mode=mode): self.assert_hold(self.api())

    def test_actual_aead_nonce_wrong_key_and_signed_index_tampering_are_rejected(self):
        self.assert_hold(self.api(key=bytes(range(1, 33))))
        def nonce(entry):
            chunk = entry['chunks'][0]
            raw = bytearray(self.writer.read(self.snapshot, chunk['path'], 8 * 1024 * 1024))
            header_size = struct.unpack('>I', raw[8:12])[0]
            raw[12 + header_size] ^= 1
            raw = bytes(raw); sha = sha256(raw).hexdigest()
            path = vault.PREFIX + '2030-04/chunks/' + sha + '.enc'
            chunk.update(path=path, sha256=sha)
            entry['cipher_sha256'] = sha
            return {path: raw}
        self.change_entry(0, nonce)
        self.assert_hold(self.api())

    def test_result_full_body_not_only_its_closing_clock_must_match(self):
        for field in ('payout', 'unknown_extra', 'publication', 'enum'):
            row = deepcopy(self.observation)
            if field == 'payout': row['data']['payouts'][0]['payout_per_100_yen'] += 10
            elif field == 'unknown_extra': row['official_permission'] = True
            elif field == 'publication': row['upstream_published_at'] = self.result_at
            else: row['status'] = True
            self.f.results(2, [row])
            with self.subTest(field=field): self.assert_hold(self.api())

    def test_pending_latest_revision_never_falls_back_to_prior_settled_raw(self):
        pending = deepcopy(self.observation)
        pending.update(status='PENDING', data=None, body_identity_verified=False,
                       captured_at='2030-04-01T08:32:00+00:00', available_at='2030-04-01T08:32:00+00:00')
        self.f.results(2, [self.observation, pending])
        self.assert_hold(self.api())

    def test_result_before_cutoff_and_roster_disagreement_are_rejected(self):
        row = deepcopy(self.observation)
        row['captured_at'] = row['available_at'] = '2030-04-01T08:29:00+00:00'
        self.f.results(2, [row])
        self.assert_hold(self.api())
        row = deepcopy(self.observation)
        row['data']['results'][0]['racer_registration_id'] = '4999'
        self.f.results(2, [row])
        self.assert_hold(self.api())

    def test_program_roster_and_raw_grid_cannot_disagree_with_the_original_pair(self):
        original = self.program_raw
        for mode in ('roster', 'cutoff'):
            self.program_raw = original.replace(b'4001', b'4999') if mode == 'roster' else original.replace(b'17:30', b'17:31')
            source = next(row for row in self.native['snapshot']['sources']
                          if row['source_id'] == self.native['snapshot']['race_source_id'])
            source['source_sha256'] = sha256(self.program_raw).hexdigest()
            self.make_pairs(); self.retain()
            with self.subTest(mode=mode): self.assert_hold(self.api())

    def test_pair_zip_metadata_source_or_original_hash_cannot_be_swapped(self):
        for field in ('digest', 'cipher', 'source', 'record', 'bool_id'):
            original = deepcopy((self.f.raws, self.f.metas))
            options = {}
            if field == 'digest': self.f.metas[800]['digest'] = 'sha256:' + 'f' * 64
            elif field == 'cipher':
                with zipfile.ZipFile(io.BytesIO(self.f.raws[800])) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
                name = next(name for name in members if name.endswith('/learning.enc'))
                members[name] = members[name][:-1] + bytes([members[name][-1] ^ 1])
                self.f.raws[800] = current.packed(members)
                self.f.metas[800]['size_in_bytes'] = len(self.f.raws[800])
                self.f.metas[800]['digest'] = 'sha256:' + sha256(self.f.raws[800]).hexdigest()
            elif field == 'source': self.f.metas[800]['workflow_run']['head_sha'] = 'f' * 40
            elif field == 'record': options['record_sha256'] = 'f' * 64
            else: options['pair_artifact_id'] = True
            with self.subTest(field=field): self.assert_hold(self.api(**options))
            self.f.raws, self.f.metas = original

    def test_snapshot_is_fixed_and_later_result_is_derived_never_backdated_into_pair(self):
        value = self.api()
        self.assertEqual(value['public']['raw_status'], 'RAW_SOURCE_REPLAY_MATCH')
        later = self.api(now=NOW + timedelta(minutes=1))
        self.assertEqual(later['private']['record_sha256'], value['private']['record_sha256'])
        self.assertEqual(later['private']['result_snapshot']['observed_at'], (NOW + timedelta(minutes=1)).isoformat())
        self.assertNotEqual(later['public']['proof_sha256'], value['public']['proof_sha256'])
        self.assert_hold(self.api(vault_snapshot_commit='f' * 40))

    def test_real_key_resolution_requires_trusted_readonly_actions_before_secret_access(self):
        self.assertIsNotNone(facade, 'strict native per-pair raw facade is missing')
        with patch.dict(os.environ, {}, clear=True), patch('race_ai.boat_pdca_state.state_key',
                side_effect=AssertionError('key must not be resolved outside Actions')) as key_reader:
            self.assert_hold(self.api(key=None))
            key_reader.assert_not_called()

    def test_only_verified_main_actions_can_use_the_default_key_path(self):
        main = dict(id=77, head_sha='b' * 40, head_branch='main', event='push', run_attempt=1,
            path='.github/workflows/boat-owner-national-p1-matrix.yml', status='in_progress', conclusion=None,
            created_at='2030-04-01T09:00:00Z',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        environment = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='push', GITHUB_RUN_ATTEMPT='1',
            GITHUB_RUN_ID='77', GITHUB_SHA='b' * 40)
        self.f.extra['actions/runs/77'] = wire(main)
        with patch.dict(os.environ, environment):
            self.assertEqual(self.api(key=None)['public']['raw_status'], 'RAW_SOURCE_REPLAY_MATCH')
            for field, bad in (('head_branch', 'foreign'), ('event', 'pull_request'),
                               ('run_attempt', True), ('created_at', '2030-04-02T09:00:00Z')):
                changed = dict(main, **{field: bad})
                self.f.extra['actions/runs/77'] = wire(changed)
                with self.subTest(field=field), patch('race_ai.boat_pdca_state.state_key',
                        side_effect=AssertionError('unverified context must not resolve key')) as key_reader:
                    self.assert_hold(self.api(key=None))
                    key_reader.assert_not_called()

    def test_private_get_errors_and_forged_enum_objects_never_leak(self):
        def denied(route):
            raise ValueError('PRIVATE_RESULT_SENTINEL https://signed.invalid/?secret=raw')
        self.assert_hold(self.api(get=denied))
        self.assert_hold(self.api(run_id=True))
        self.assert_hold(self.api(record_sha256={'official': True}))


if __name__ == '__main__':
    unittest.main()
