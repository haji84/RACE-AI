"""Synthetic saved archives only; no source reads or timestamp attestation."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.frozen_day_cycle import read_p0
from tests.test_frozen_day_cycle import sample, observation
from tests.test_observed_p1_connection import inputs, archive, bridge, AT
from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
try:
    from race_ai import private_cycle_restore as restore
except ImportError:
    restore = None


class PrivateRestoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(restore, 'restore_manifest', None)), 'private artifact restore is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = dict(repo='haji84/RACE-AI', repository_id=1416489937,
                             day_jst='2030-04-01', artifacts=[])

    def add(self, kind, raw, meta, member):
        number = len(self.manifest['artifacts'])
        meta_raw = json.dumps(meta).encode()
        names = (f'metadata-{number}.json', f'original-{number}.zip')
        (self.root/names[0]).write_bytes(meta_raw)
        (self.root/names[1]).write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            member_sha = hashlib.sha256(z.read(member)).hexdigest()
        entry = dict(kind=kind, artifact_id=meta['id'], run_id=meta['workflow_run']['id'],
                     metadata_file=names[0], zip_file=names[1],
                     metadata_sha256=hashlib.sha256(meta_raw).hexdigest(),
                     zip_sha256=hashlib.sha256(raw).hexdigest(), member_sha256=member_sha,
                     created_at=meta['created_at'])
        self.manifest['artifacts'].append(entry)
        return entry

    def p0(self):
        doc, raw, meta = sample()
        self.add('p0', raw, meta, 'forecasts.json')
        return doc, raw, meta

    def p1(self, learned=False):
        base, extra, proof = inputs()
        bundle = bridge.build_bundle(base, extra, AT, **proof, owner_reviewed=True)
        doc = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
                   paired_forecasts=[build_pair(base, AT)],
                   additional_official_feature_shadows=[build_live_feature_shadow(base, extra, AT)],
                   observed_pairwise_p1_bundles=[bundle])
        if learned:
            doc['learned_pairwise_shadows'] = [dict(training_receipt={'id':999}, training_sha256='e'*64)]
        raw, meta = archive(doc)
        self.add('p1', raw, meta, 'national.json')
        return doc, raw, meta

    def result(self, rows, artifact_id=700, at='2030-04-01T02:15:00Z'):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('official-result-observations.json', json.dumps(rows))
        raw = buf.getvalue()
        meta = dict(id=artifact_id, name='race-existing-cycle-99', expired=False,
                    created_at=at, digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                    workflow_run=dict(id=99, head_repository_id=1416489937))
        self.add('result', raw, meta, 'official-result-observations.json')

    def test_original_p0_and_p1_rows_and_documents_survive_without_io_or_attestation(self):
        p0, _, _ = self.p0()
        p1, _, _ = self.p1()
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        manifest_before = copy.deepcopy(self.manifest)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
             patch('subprocess.run', side_effect=AssertionError('process')), \
             patch('pathlib.Path.write_bytes', side_effect=AssertionError('write')), \
             patch('pathlib.Path.write_text', side_effect=AssertionError('write')), \
             patch('race_ai.boat_observed_pairwise_models.predict_pair', side_effect=AssertionError('forecast')):
            state = restore.restore_manifest(self.manifest, self.root)
        self.assertEqual(len(state['rows']), 7)
        self.assertEqual({r['stage'] for r in state['rows']}, {'P0','P1'})
        self.assertEqual(state['coverage_scope'], 'EXPLICIT_ARTIFACTS_ONLY')
        self.assertFalse(state['complete'])
        self.assertFalse(state['external_receipts_verified'])
        self.assertFalse(state['source_rights_verified'])
        docs = {r['member_name']:r['document'] for r in state['original_documents']}
        self.assertEqual(docs['forecasts.json'], json.loads(json.dumps(p0)))
        self.assertEqual(docs['national.json'], json.loads(json.dumps(p1)))
        self.assertEqual(state['state_sha256'], digest({k:v for k,v in state.items() if k!='state_sha256'}))
        self.assertEqual(self.manifest, manifest_before)
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir()}, before)

    def test_empty_historical_attempt_remains_an_empty_original_not_a_forecast(self):
        _,_,meta=sample()
        doc=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst='2030-04-01',predictions=[],
                 race_count=None,model_forecast_count=None,actual_purchases=False)
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('forecasts.json',json.dumps(doc))
        raw=buf.getvalue();meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
        self.add('p0',raw,meta,'forecasts.json')
        state=restore.restore_manifest(self.manifest,self.root)
        self.assertEqual(state['rows'],[])
        self.assertEqual(state['original_documents'][0]['document'],doc)
        self.assertFalse(state['complete'])

    def test_raw_result_revisions_are_retained_and_forecast_receipt_is_unchanged(self):
        _, raw, meta = self.p0()
        _, rows = read_p0(raw, meta, expected_day='2030-04-01')
        first = observation(rows[0]); second = copy.deepcopy(first)
        second['captured_at'] = '2030-04-01T02:12:00Z'
        second['source_sha256'] = 'c'*64
        self.result([first, second])
        state = restore.restore_manifest(self.manifest, self.root)
        self.assertEqual(state['observations'], [first, second])
        self.assertEqual(state['rows'], rows)
        self.assertNotIn('revision_no', state['observations'][0])

    def test_later_original_does_not_replace_first_and_repeated_artifact_is_rejected(self):
        _, raw, meta = self.p0()
        later = copy.deepcopy(meta); later.update(id=2, created_at='2030-04-01T01:44:00Z')
        self.add('p0', raw, later, 'forecasts.json')
        state = restore.restore_manifest(self.manifest, self.root)
        self.assertEqual(len(state['rows']), 2)
        self.assertEqual({r['artifact_id'] for r in state['rows']}, {1})
        self.assertEqual(len(state['excluded_repeats']), 2)
        self.manifest['artifacts'].append(copy.deepcopy(self.manifest['artifacts'][0]))
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_wrong_pins_metadata_identity_day_expiration_and_late_receipt_are_rejected(self):
        _, raw, meta = self.p0()
        original = copy.deepcopy(self.manifest)
        for field in ('metadata_sha256','zip_sha256','member_sha256'):
            self.manifest = copy.deepcopy(original)
            self.manifest['artifacts'][0][field] = 'f'*64
            with self.subTest(field=field), self.assertRaises(ValueError):
                restore.restore_manifest(self.manifest, self.root)
        for change in ({'id':99}, {'expired':True}, {'created_at':'2030-04-01T02:00:00Z'},
                       {'workflow_run':{'id':99,'head_repository_id':1416489937}},
                       {'workflow_run':{'id':2,'head_repository_id':99}},
                       {'workflow_run':{'id':2,'head_repository_id':1416489937,'repository_id':99}}):
            self.manifest = dict(original, artifacts=[])
            altered = dict(meta, **change)
            entry = self.add('p0', raw, altered, 'forecasts.json')
            if 'id' in change:entry['artifact_id'] = 1
            if 'workflow_run' in change:entry['run_id'] = 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                restore.restore_manifest(self.manifest, self.root)
        self.manifest = dict(original, day_jst='2030-04-02')
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_manifest_is_exact_bounded_and_does_not_accept_other_repository(self):
        self.p0()
        for change in ({'repo':'other/repo'}, {'repository_id':False}, {'day_jst':'20300401'},
                       {'artifacts':[]}, {'artifacts':self.manifest['artifacts']*101}, {'extra':True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                restore.restore_manifest(dict(self.manifest, **change), self.root)
        entry = self.manifest['artifacts'][0]
        for change in ({'kind':'continuity'}, {'artifact_id':True}, {'zip_sha256':'not-a-sha'},
                       {'extra':True}, {'created_at':'2030-04-01T01:42:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                restore.restore_manifest(dict(self.manifest, artifacts=[dict(entry, **change)]), self.root)

    def test_path_escape_symlink_hardlink_and_git_roots_are_rejected_without_path_leak(self):
        self.p0(); entry = self.manifest['artifacts'][0]
        linked = self.root/'linked.zip'; linked.symlink_to(entry['zip_file'])
        hard = self.root/'hard.zip'; os.link(self.root/entry['zip_file'], hard)
        for path in ('../secret.zip', str(self.root/entry['zip_file']), 'linked.zip', 'hard.zip', './original-0.zip'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, '^PRIVATE_ARTIFACT_RESTORE_REJECTED$'):
                restore.restore_manifest(dict(self.manifest, artifacts=[dict(entry, zip_file=path)]), self.root)
        hard.unlink()
        (self.root/'.git').mkdir()
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_root_or_ancestor_symlink_is_rejected(self):
        self.p0()
        target = self.root/'actual'; target.mkdir()
        alias = self.root/'alias'; alias.symlink_to(target, target_is_directory=True)
        nested = target/'nested'; nested.mkdir()
        for folder in (target,nested):
            for entry in self.manifest['artifacts']:
                for field in ('metadata_file','zip_file'):
                    (folder/entry[field]).write_bytes((self.root/entry[field]).read_bytes())
        for root in (alias, alias/'nested'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                restore.restore_manifest(self.manifest, root)

    def test_duplicate_json_keys_and_extra_forecast_zip_members_are_rejected(self):
        _, raw, meta = self.p0(); entry = self.manifest['artifacts'][0]
        text = (self.root/entry['metadata_file']).read_text()
        altered = text[:-1]+',"expired": false}'
        (self.root/entry['metadata_file']).write_text(altered)
        entry['metadata_sha256'] = hashlib.sha256(altered.encode()).hexdigest()
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)
        self.manifest['artifacts'] = []
        buf = io.BytesIO(raw)
        with zipfile.ZipFile(buf, 'a') as z:z.writestr('extra.json', '{}')
        changed = buf.getvalue(); meta['digest'] = 'sha256:'+hashlib.sha256(changed).hexdigest()
        self.add('p0', changed, meta, 'forecasts.json')
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_cross_day_p1_and_future_result_capture_are_rejected(self):
        self.p1()
        with self.assertRaises(ValueError):
            restore.restore_manifest(dict(self.manifest, day_jst='2030-04-02'), self.root)
        self.manifest['artifacts'] = []
        _, raw, meta = self.p0(); _, rows = read_p0(raw, meta, expected_day='2030-04-01')
        event = observation(rows[0]); event['captured_at'] = '2030-04-01T03:00:00Z'
        self.result([event])
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_pinned_forecast_cannot_bind_same_race_to_another_cutoff_day(self):
        doc, _, _ = self.p1()
        self.manifest['artifacts'] = []
        pair = doc['paired_forecasts'][0]
        pair['cutoff_at'] = '2030-04-02T10:59:00+09:00'
        pair['bundle_sha256'] = digest({k:v for k,v in pair.items() if k!='bundle_sha256'})
        raw, meta = archive(doc)
        self.add('p1', raw, meta, 'national.json')
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_confirmed_result_capture_cannot_precede_its_official_cutoff(self):
        _, raw, meta = self.p0(); _, rows = read_p0(raw, meta, expected_day='2030-04-01')
        event = observation(rows[0]); event['captured_at'] = '2030-04-01T01:00:00Z'
        self.result([event])
        with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)

    def test_learned_documents_remain_intact_and_unresolved_without_inference_replay(self):
        original, _, _ = self.p1(learned=True)
        with patch('race_ai.observed_weight_learning.make_shadows', side_effect=AssertionError('inference replay')):
            state = restore.restore_manifest(self.manifest, self.root)
        self.assertEqual(len(state['rows']), 5)
        self.assertEqual(state['original_documents'][0]['document'], json.loads(json.dumps(original)))
        self.assertEqual(state['unresolved_learned_dependencies'][0]['training_artifact_id'], 999)
        self.assertFalse(state['learned_shadows_restored'])

    def test_total_disk_and_uncompressed_budget_are_enforced_before_restore(self):
        self.p0()
        with patch.object(restore, 'MAX_TOTAL_BYTES', 32):
            with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)
        self.manifest['artifacts'] = []
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('official-result-observations.json', '[]')
            z.writestr('ignored.bin', b'0'*65536)
        raw = buf.getvalue()
        meta = dict(id=9, name='race-existing-cycle-99', expired=False, created_at='2030-04-01T02:15:00Z',
                    digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                    workflow_run=dict(id=99, head_repository_id=1416489937))
        self.add('result', raw, meta, 'official-result-observations.json')
        with patch.object(restore, 'MAX_TOTAL_BYTES', 4096):
            with self.assertRaises(ValueError):restore.restore_manifest(self.manifest, self.root)
