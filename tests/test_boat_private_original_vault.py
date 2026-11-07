"""Exact invented originals, ephemeral owner keys and local Git remotes only."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.boat_pdca_github_handoff import GitStateRepository, TRANSFER_REF
from race_ai.boat_private_original_archive import seal_original_zip
from tests.test_frozen_day_cycle import sample

try:
    vault = importlib.import_module('race_ai.boat_private_original_vault')
except ModuleNotFoundError:
    vault = None

KEY = bytes(range(32))
HEAD = 'a' * 40
NOW = datetime(2030, 4, 1, 12, tzinfo=timezone.utc)
_, BASE_NATIVE, BASE_METADATA = sample()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def packed(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as target:
        for name, body in files.items():
            target.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), body)
    return output.getvalue()


def original(*, ident=101, run=2, encrypted=False, extra=None):
    native, meta = BASE_NATIVE, deepcopy(BASE_METADATA)
    meta.update(id=ident, name=f'boat-p0-existing-{run}', created_at='2030-04-01T01:43:00Z',
                expires_at='2030-04-08T01:43:00Z', updated_at='2030-04-01T01:43:00Z')
    meta['workflow_run'].update(id=run, repository_id=1416489937,
                                head_repository_id=1416489937, head_sha=HEAD)
    if extra is not None:
        with zipfile.ZipFile(io.BytesIO(native)) as source:
            document = json.loads(source.read('forecasts.json'))
        document['opaque_padding'] = extra.hex()
        native = packed({'forecasts.json': wire(document)})
    if encrypted:
        native = packed({'private-original.enc': seal_original_zip(native, run_id=str(run),
                         head_sha=HEAD, kind='P0', key=KEY)})
    meta.update(digest='sha256:'+sha256(native).hexdigest(), size_in_bytes=len(native))
    # Deliberately noncanonical: retain the actual response, not a JSON rewrite.
    metadata = json.dumps(meta, ensure_ascii=False, indent=3).encode()+b'\n\n'
    return native, metadata


class LocalGit(getattr(vault,'VaultGitRepository',GitStateRepository)):
    def _check_remote(self):
        self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(vault, 'exact original vault is absent')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root/'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git','--git-dir',str(self.remote),'config','uploadpack.allowFilter','true'],
                       check=True,capture_output=True)
        self.writer = self.git('writer')
        self.reader = self.git('independent-reader')
        self.parent = self.writer.commit({'unrelated/retained.enc': b'existing ciphertext'}, None)
        self.writer.push(self.parent, None)

    def git(self, name):
        repo = self.root/name
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', str(self.remote)],
                       check=True, capture_output=True)
        return LocalGit(repo, ref=TRANSFER_REF)

    def retain(self, pair=None, **kwargs):
        pair = original() if pair is None else pair
        return vault.retain_original(*pair, self.writer.repo, expected_parent=kwargs.pop('expected_parent', self.parent),
            key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW, **kwargs)

    def restore(self, locator, **kwargs):
        return vault.restore_original(locator, self.reader.repo, key=kwargs.pop('key', KEY),
                                      transport=self.reader, **kwargs)

    def test_legacy_zip_and_noncanonical_receipt_restore_after_expiry_without_live_get(self):
        raw, metadata_raw = original()
        locator = self.retain((raw, metadata_raw))
        with patch('urllib.request.urlopen', side_effect=AssertionError('source GET')):
            restored = self.restore(locator)
        self.assertEqual(restored['raw_zip'], raw)
        self.assertEqual(restored['metadata_raw'], metadata_raw)
        self.assertEqual(restored['metadata']['created_at'], '2030-04-01T01:43:00Z')
        self.assertIs(restored['metadata']['expired'], False)
        self.assertEqual(restored['provenance']['receipt_scope'], 'ARCHIVED_GITHUB_ARTIFACT_RESPONSE')
        self.assertEqual(restored['provenance']['current_artifact_status'], 'NOT_QUERIED')
        self.assertTrue(restored['provenance']['independent_git_readback_verified'])
        subprocess.run(['git', '--git-dir', str(self.remote), 'fsck', '--no-dangling'],
                       check=True, capture_output=True)
        tree = self.writer._run(['ls-tree', '-r', '--name-only', locator['source_commit']]).decode().splitlines()
        self.assertNotIn('original.zip', tree)
        self.assertEqual(self.writer.read(locator['source_commit'], 'unrelated/retained.enc', 100), b'existing ciphertext')
        for path in tree:
            raw_blob = self.writer.read(locator['source_commit'], path, 9*1024*1024)
            self.assertNotIn(b'RACE_AI_EXISTING_P0_DAY_V1', raw_blob)

    def test_second_append_keeps_first_locator_lookup_and_original_bytes(self):
        first = self.retain()
        other = original(ident=102, run=3, encrypted=True)
        second = self.retain(other, expected_parent=first['source_commit'])
        self.assertNotEqual(first['source_commit'], second['source_commit'])
        self.assertEqual(self.restore(first)['raw_zip'], original()[0])
        self.assertEqual(self.restore(second)['raw_zip'], other[0])
        located = vault.lookup_original(101, self.reader.repo, key=KEY, transport=self.reader)
        self.assertEqual(self.restore(located)['metadata_raw'], original()[1])
        self.assertEqual(vault.lookup_original(999, self.reader.repo, key=KEY, transport=self.reader), None)

    def test_batch_uses_one_cas_commit_and_one_bounded_batch_index(self):
        originals = [original(ident=101), original(ident=102, run=3)]
        report = vault.retain_originals(originals, self.writer.repo, expected_parent=self.parent,
            key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        self.assertEqual(report['retained_originals'], 2)
        self.assertEqual({p['source_commit'] for p in report['locators']}, {report['source_commit']})
        self.assertEqual(self.writer._run(['rev-list', '--count', self.parent+'..'+report['source_commit']]).strip(), b'1')
        for pair, locator in zip(originals, report['locators']):
            self.assertEqual(self.restore(locator)['raw_zip'], pair[0])
        batch_paths = self.writer._run(['ls-tree', '-r', '--name-only', report['source_commit']]).decode().splitlines()
        self.assertEqual(sum('/batches/' in name for name in batch_paths), 1)

    def test_identical_retry_is_idempotent_but_id_receipt_clock_conflicts_stop(self):
        pair = original()
        first = self.retain(pair)
        same = self.retain(pair, expected_parent=first['source_commit'])
        self.assertEqual(same, first)
        for field, value in (('created_at', '2030-04-01T01:43:01Z'), ('updated_at', '2030-04-01T01:43:01Z')):
            metadata = json.loads(pair[1]); metadata[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.retain((pair[0], wire(metadata)), expected_parent=first['source_commit'])
        self.assertEqual(self.writer.head(), first['source_commit'])

    def test_month_rollover_does_not_scan_or_forget_older_originals(self):
        first = self.retain()
        raw, metadata = original(ident=201, run=3)
        raw = packed({'forecasts.json':wire(dict(schema='RACE_AI_EXISTING_P0_DAY_V1', day_jst='2030-05-01',
            predictions=[], race_count=0, model_forecast_count=0, actual_purchases=False))})
        value = json.loads(metadata)
        value.update(created_at='2030-05-01T01:00:00Z', expires_at='2030-05-08T01:00:00Z',
                     digest='sha256:'+sha256(raw).hexdigest(), size_in_bytes=len(raw))
        second = vault.retain_original(raw, wire(value), self.writer.repo, expected_parent=first['source_commit'],
            key=KEY, transport=self.writer, readback_transport=self.reader,
            now=datetime(2030, 5, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(self.restore(vault.lookup_original(101, self.reader.repo, key=KEY,
                         transport=self.reader))['metadata_raw'], original()[1])
        self.assertEqual(self.restore(second)['metadata']['created_at'], '2030-05-01T01:00:00Z')
        april = vault.list_originals('2030-04', self.reader.repo, key=KEY, transport=self.reader)
        may = vault.list_originals('2030-05', self.reader.repo, key=KEY, transport=self.reader)
        self.assertEqual([p['artifact_id'] for p in april], [101])
        self.assertEqual([p['artifact_id'] for p in may], [201])

    def test_chunks_are_bounded_and_large_original_restores_exactly(self):
        pair = original(extra=os.urandom(8*1024*1024+117))
        locator = self.retain(pair)
        self.assertEqual(self.restore(locator)['raw_zip'], pair[0])
        rows = self.writer._run(['ls-tree', '-rlz', locator['source_commit']]).split(b'\0')
        lengths = [int(row.split(b'\t')[0].split()[-1]) for row in rows if b'/chunks/' in row]
        self.assertGreater(len(lengths), 1)
        self.assertLessEqual(max(lengths), 8*1024*1024)

    def test_wrong_key_missing_key_wrong_locator_and_cipher_tamper_are_rejected(self):
        locator = self.retain()
        with self.assertRaises(ValueError): self.restore(locator, key=b'x'*32)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            vault.restore_original(locator, self.reader.repo, transport=self.reader)
        for field, value in (('ref', 'main'), ('artifact_id', 999), ('entry_sha256', 'f'*64), ('source_commit', '--bad')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.restore(dict(locator, **{field:value}))
        paths = self.writer._run(['ls-tree', '-r', '--name-only', locator['source_commit']]).decode().splitlines()
        chunk = next(p for p in paths if '/chunks/' in p)
        corrupted = self.writer.commit({chunk:b'altered ciphertext'}, locator['source_commit'])
        self.writer.push(corrupted, locator['source_commit'])
        with self.assertRaises(ValueError): self.restore(dict(locator, source_commit=corrupted))

    def test_missing_chunk_and_modified_signed_index_are_rejected(self):
        locator = self.retain()
        paths = self.writer._run(['ls-tree', '-r', '--name-only', locator['source_commit']]).decode().splitlines()
        chunk = next(p for p in paths if '/chunks/' in p)
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory)/'index'))
            self.writer._run(['read-tree', locator['source_commit']], env=env)
            self.writer._run(['update-index', '--force-remove', chunk], env=env)
            tree_id = self.writer._run(['write-tree'], env=env).decode().strip()
        bad = self.writer._run(['-c','user.name=fixture','-c','user.email=fixture@example.test',
            'commit-tree',tree_id,'-p',locator['source_commit']], body=b'fixture missing chunk\n').decode().strip()
        self.writer.push(bad, locator['source_commit'])
        with self.assertRaises(ValueError): self.restore(dict(locator, source_commit=bad))
        lookup = next(p for p in paths if '/lookup/' in p)
        altered = self.writer.commit({lookup:b'{"state":{},"mac":"'+b'0'*64+b'"}'}, bad)
        self.writer.push(altered, bad)
        with self.assertRaises(ValueError):
            vault.lookup_original(101, self.reader.repo, key=KEY, transport=self.reader)

    def test_stale_parent_and_missing_existing_transfer_ref_do_not_initialize(self):
        locator = self.retain()
        with self.assertRaises(ValueError): self.retain(original(ident=102))
        self.assertEqual(self.writer.head(), locator['source_commit'])
        with self.assertRaises(ValueError):
            vault.retain_original(*original(), self.writer.repo, expected_parent=None,
                key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)

    def test_expired_foreign_wrong_digest_and_future_receipts_reject_before_publication(self):
        raw, metadata = original()
        for mutate in (lambda m:m.update(expired=True), lambda m:m.update(digest='sha256:'+'f'*64),
                       lambda m:m.update(created_at='2030-04-02T01:00:00Z'),
                       lambda m:m.update(expires_at='2030-04-01T02:00:00Z'),
                       lambda m:m['workflow_run'].update(repository_id=1),
                       lambda m:m['workflow_run'].update(head_sha='b'*40)):
            meta = json.loads(metadata); mutate(meta)
            # A clear legacy ZIP has no head AEAD, but its receipt must still
            # pass every native phase validation that exists for that original.
            if meta['workflow_run']['head_sha'] == 'b'*40: continue
            with self.subTest(meta=meta['id']), self.assertRaises(ValueError):
                self.retain((raw, wire(meta)))
        self.assertEqual(self.writer.head(), self.parent)

    def test_reader_selects_vault_before_get_and_never_falls_back_after_denial(self):
        pair = original(); locator = self.retain(pair)
        calls = []
        def denied(path):
            calls.append(path)
            raise RuntimeError('GITHUB_API_READ_HTTP_410_HALT')
        reader = vault.VaultArtifactReader(denied, self.reader.repo, key=KEY, transport=self.reader,
                                           known_locators={101:locator})
        self.assertEqual(reader('actions/artifacts/101'), pair[1])
        self.assertEqual(reader('actions/artifacts/101/zip'), pair[0])
        self.assertEqual(calls, [])
        with self.assertRaises(RuntimeError): reader('actions/artifacts/999')
        self.assertEqual(calls, ['actions/artifacts/999'])
        # Discovering a later archive cannot change this already-live selection.
        with patch.object(vault, 'lookup_original', side_effect=AssertionError('post-denial fallback')):
            with self.assertRaises(RuntimeError): reader('actions/artifacts/999/zip')

    def test_source_capture_bundle_retains_exact_html_and_receipts_with_separate_provenance(self):
        raw = b'<html>invented exact source bytes\r\n</html>'
        receipt = json.dumps(dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z', http_status=200, source_sha256=sha256(raw).hexdigest()), indent=2).encode()+b'\n'
        locator = vault.retain_capture_bundle([(raw, receipt)], self.writer.repo, run_id=2, head_sha=HEAD,
            expected_parent=self.parent, key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        result = vault.restore_capture_bundle(locator, self.reader.repo, key=KEY, transport=self.reader)
        self.assertEqual(result['captures'], [(raw, receipt)])
        self.assertEqual(result['provenance']['receipt_scope'], 'OWNER_RETAINED_SOURCE_CAPTURES')
        self.assertFalse(result['provenance']['github_artifact_receipt_created'])
        broken = json.loads(receipt); broken['http_status'] = 403
        with self.assertRaises(ValueError):
            vault.retain_capture_bundle([(raw, wire(broken))], self.writer.repo, run_id=2, head_sha=HEAD,
                expected_parent=locator['source_commit'], key=KEY, transport=self.writer,
                readback_transport=self.reader, now=NOW)

    def test_month_capacity_stops_without_deleting_prior_originals(self):
        first = self.retain()
        with patch.object(vault, 'MAX_MONTH_ENTRIES', 1), self.assertRaises(ValueError):
            self.retain(original(ident=102), expected_parent=first['source_commit'])
        self.assertEqual(self.writer.head(), first['source_commit'])
        self.assertEqual(self.restore(first)['raw_zip'], original()[0])

    def test_exact_github_run_and_listing_capture_bytes_use_owner_capture_provenance(self):
        raw = b'{ "id":2, "status":"completed", "artifacts":[] }\n'
        receipt = wire(dict(source_url='https://api.github.com/repos/haji84/RACE-AI/actions/runs/2/artifacts?per_page=100&page=1',
            captured_at='2030-04-01T11:59:00Z', http_status=200, source_sha256=sha256(raw).hexdigest()))
        locator = vault.retain_capture_bundle([(raw, receipt)], self.writer.repo, run_id=2, head_sha=HEAD,
            expected_parent=self.parent, key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        restored = vault.restore_capture_bundle(locator, self.reader.repo, key=KEY, transport=self.reader)
        self.assertEqual(restored['captures'], [(raw, receipt)])
        self.assertFalse(restored['provenance']['github_artifact_receipt_created'])
        bad = json.loads(receipt); bad['source_url'] = 'https://api.github.com/repos/another/repo/actions/runs/2'
        with self.assertRaises(ValueError):
            vault.retain_capture_bundle([(raw, wire(bad))], self.writer.repo, run_id=2, head_sha=HEAD,
                expected_parent=locator['source_commit'], key=KEY, transport=self.writer,
                readback_transport=self.reader, now=NOW)

    def test_native_p1_result_continuity_and_all_model_outer_archives_retain_exactly(self):
        from tests.private_cycle_ui_fixture import _artifacts
        from tests.test_continuity_checkpoint import session
        from race_ai import boat_all_model_store as store
        native_pairs, _, _ = _artifacts()
        pairs = []
        for raw, meta in native_pairs:
            if meta['name'].startswith('boat-p0'): continue
            meta = deepcopy(meta)
            meta.update(size_in_bytes=len(raw), expires_at='2030-04-08T12:00:00Z')
            meta['workflow_run'].update(repository_id=1416489937, head_sha=HEAD)
            pairs.append((raw, wire(meta)))
        continuity = packed({'repeat-session.json':session()})
        continuity_meta = dict(id=801, name='race-cycle-continuity-7', expired=False,
            created_at='2030-04-01T02:00:00Z', expires_at='2030-04-08T12:00:00Z',
            digest='sha256:'+sha256(continuity).hexdigest(), size_in_bytes=len(continuity),
            workflow_run=dict(id=7, repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD))
        pairs.append((continuity, wire(continuity_meta)))
        payload = dict(schema='RACE_AI_BOAT_ALL_MODEL_CYCLE_V1', source_requests=0, originals_overwritten=False,
            source_code_commit=HEAD, run_id='42', generated_at='2030-04-01T02:00:00Z',
            as_of='2030-04-01T02:00:00Z', baseline=None, dispatch_reports=[])
        from race_ai.boat_all_model_cycle import SCHEMA as CYCLE_SCHEMA
        payload['schema'] = CYCLE_SCHEMA
        all_model = packed({'forecasts.enc':store.seal_forecasts(payload, run_id='42', round_no=0, key=KEY)})
        all_meta = dict(id=802, name='boat-all-model-forecasts-42-r0', expired=False,
            created_at='2030-04-01T02:00:01Z', expires_at='2030-04-08T12:00:00Z',
            digest='sha256:'+sha256(all_model).hexdigest(), size_in_bytes=len(all_model),
            workflow_run=dict(id=42, repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD))
        pairs.append((all_model, wire(all_meta)))
        report = vault.retain_originals(pairs, self.writer.repo, expected_parent=self.parent,
            key=KEY, transport=self.writer, readback_transport=self.reader, now=NOW)
        self.assertEqual({p['kind'] for p in report['locators']}, {'P1','RESULT','CONTINUITY','ALL_MODEL'})
        for pair, locator in zip(pairs, report['locators']):
            restored = self.restore(locator)
            self.assertEqual((restored['raw_zip'], restored['metadata_raw']), pair)

    def test_unchanged_capture_bundle_reuses_existing_cipher_and_does_not_append(self):
        raw = b'<html>invented fixed bytes</html>'
        receipt = wire(dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z', http_status=200, source_sha256=sha256(raw).hexdigest()))
        first = vault.retain_capture_bundle([(raw,receipt)],self.writer.repo,run_id=2,head_sha=HEAD,
            expected_parent=self.parent,key=KEY,transport=self.writer,readback_transport=self.reader,now=NOW)
        second = vault.retain_capture_bundle([(raw,receipt)],self.writer.repo,run_id=2,head_sha=HEAD,
            expected_parent=first['source_commit'],key=KEY,transport=self.writer,readback_transport=self.reader,
            now=datetime(2030,4,1,12,1,tzinfo=timezone.utc))
        self.assertEqual(second,first)
        self.assertEqual(self.writer.head(),first['source_commit'])

    def test_encrypted_original_wrong_head_cannot_be_archived_with_a_valid_outer_digest(self):
        raw, metadata = original(encrypted=True)
        value = json.loads(metadata); value['workflow_run']['head_sha'] = 'b'*40
        with self.assertRaises(ValueError): self.retain((raw,wire(value)))
        self.assertEqual(self.writer.head(),self.parent)

    def test_source_control_requires_its_exact_authenticated_continuity_sibling(self):
        from tests.test_continuity_checkpoint import session
        from race_ai.boat_source_control import build_summary
        continuity_plain = packed({'repeat-session.json':session()})
        cipher = seal_original_zip(continuity_plain,run_id='7',head_sha=HEAD,kind='CONTINUITY',key=KEY)
        continuity = packed({'private-original.enc':cipher})
        def metadata(raw,ident,name):
            return wire(dict(id=ident,name=name,expired=False,created_at='2030-04-01T02:00:00Z',
                expires_at='2030-04-08T02:00:00Z',digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
                workflow_run=dict(id=7,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD)))
        summary = build_summary(cipher,run_id=7,head_sha=HEAD,key=KEY)
        source_control = packed({'source-control.json':wire(summary)})
        companion = (continuity,metadata(continuity,801,'race-cycle-continuity-7'))
        control_meta = metadata(source_control,802,'race-source-control-7')
        with self.assertRaises(ValueError):
            self.retain((source_control,control_meta))
        locator = self.retain((source_control,control_meta),companion=companion)
        self.assertEqual(self.restore(locator)['raw_zip'],source_control)

    def test_batch_byte_capacity_and_nonindependent_reader_reject_before_remote_change(self):
        pairs = [original(ident=101),original(ident=102)]
        with patch.object(vault,'MAX_BATCH_PLAIN',len(pairs[0][0])+len(pairs[0][1])+1,create=True), self.assertRaises(ValueError):
            vault.retain_originals(pairs,self.writer.repo,expected_parent=self.parent,key=KEY,
                transport=self.writer,readback_transport=self.reader,now=NOW)
        self.assertEqual(self.writer.head(),self.parent)

        with self.assertRaises(ValueError):
            vault.retain_original(*pairs[0],self.writer.repo,expected_parent=self.parent,key=KEY,
                transport=self.writer,readback_transport=self.writer,now=NOW)
        self.assertEqual(self.writer.head(),self.parent)

    def test_independent_readback_does_not_download_unrelated_retained_ciphertexts(self):
        unrelated = self.writer._run(['rev-parse',self.parent+':unrelated/retained.enc']).decode().strip()
        locator = self.retain()
        self.assertEqual(self.restore(locator)['raw_zip'],original()[0])
        result = subprocess.run(['git','-C',str(self.reader.repo),'cat-file','-e',unrelated],
            env=dict(os.environ,GIT_NO_LAZY_FETCH='1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode,0,'fresh readback downloaded unrelated historical bytes')

    def corrupt_remote_chunk(self,commit):
        paths=self.writer._run(['ls-tree','-r','--name-only',commit]).decode().splitlines()
        chunk=next(path for path in paths if '/chunks/' in path)
        broken=self.writer.commit({chunk:b'broken remote ciphertext'},commit)
        self.writer.push(broken,commit)
        return broken

    def test_unchanged_retry_rejects_corrupt_remote_original_in_fresh_readback(self):
        pair=original();first=self.retain(pair)
        broken=self.corrupt_remote_chunk(first['source_commit'])
        with self.assertRaises(ValueError):
            vault.retain_originals([pair],self.writer.repo,expected_parent=broken,key=KEY,
                transport=self.writer,readback_transport=self.git('unchanged-fresh-reader'),now=NOW)
        self.assertEqual(self.writer.head(),broken)

    def test_mixed_batch_rejects_corrupt_existing_original_before_appending_new_bytes(self):
        pair=original();first=self.retain(pair)
        broken=self.corrupt_remote_chunk(first['source_commit'])
        with self.assertRaises(ValueError):
            vault.retain_originals([pair,original(ident=102,run=3)],self.writer.repo,
                expected_parent=broken,key=KEY,transport=self.writer,
                readback_transport=self.git('mixed-fresh-reader'),now=NOW)
        self.assertEqual(self.writer.head(),broken)

    def test_unchanged_capture_retry_rejects_corrupt_remote_capture_ciphertext(self):
        raw=b'<html>invented exact captures</html>'
        receipt=wire(dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z',http_status=200,source_sha256=sha256(raw).hexdigest()))
        first=vault.retain_capture_bundle([(raw,receipt)],self.writer.repo,run_id=2,head_sha=HEAD,
            expected_parent=self.parent,key=KEY,transport=self.writer,readback_transport=self.reader,now=NOW)
        broken=self.corrupt_remote_chunk(first['source_commit'])
        with self.assertRaises(ValueError):
            vault.retain_capture_bundle([(raw,receipt)],self.writer.repo,run_id=2,head_sha=HEAD,
                expected_parent=broken,key=KEY,transport=self.writer,
                readback_transport=self.git('capture-fresh-reader'),now=NOW)
        self.assertEqual(self.writer.head(),broken)


if __name__ == '__main__':
    unittest.main()
