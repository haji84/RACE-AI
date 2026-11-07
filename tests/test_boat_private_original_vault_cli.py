"""Actions-facing vault commands against exact fixture receipts and local Git."""
import base64
from contextlib import redirect_stdout
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

from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from tests.test_boat_private_original_vault import KEY, HEAD, NOW, LocalGit, original, wire

try:
    cli = importlib.import_module('scripts.boat_private_original_vault')
except ModuleNotFoundError:
    cli = None


class VaultCliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cli, 'Actions vault CLI is absent')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        remote = self.root/'remote.git'
        subprocess.run(['git','init','--bare',str(remote)], check=True, capture_output=True)
        subprocess.run(['git','--git-dir',str(remote),'config','uploadpack.allowFilter','true'],
                       check=True,capture_output=True)
        self.writer = self.git('writer', remote); self.reader = self.git('reader', remote)
        self.parent = self.writer.commit({'unrelated.enc':b'existing ciphertext'}, None)
        self.writer.push(self.parent, None)
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_RUN_ID='2',
            GITHUB_SHA=HEAD, GH_TOKEN='fixture-token-only-not-a-credential',
            RUNNER_TEMP=str(self.root), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())

    def git(self, name, remote):
        repo = self.root/name
        subprocess.run(['git','init',str(repo)], check=True, capture_output=True)
        subprocess.run(['git','-C',str(repo),'remote','add','origin',str(remote)], check=True, capture_output=True)
        return LocalGit(repo, ref=TRANSFER_REF)

    def run_cli(self, args, get=None, env=None):
        output = io.StringIO()
        with patch.dict(os.environ, self.env if env is None else env, clear=True), redirect_stdout(output):
            code = cli.main([*args, '--repo-root', str(self.writer.repo)], transport=self.writer,
                            readback_transport=self.reader, github_get=get, now=NOW)
        return code, json.loads(output.getvalue())

    def test_capture_fetches_actual_metadata_run_and_zip_then_restore_writes_exact_private_files(self):
        raw, metadata = original()
        info = wire(dict(id=2, head_sha=HEAD, workflow_id=405276784,
            head_branch='feat/four-sport-forecast-audit-view-20261022',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI')))
        responses = {'actions/artifacts/101':metadata, 'actions/runs/2':info, 'actions/artifacts/101/zip':raw}
        output = self.root/'report.json'
        code, report = self.run_cli(['capture','--artifact','101','--expected-parent','current','--output',str(output)],
                                    get=lambda path:responses[path])
        self.assertEqual(code, 0)
        locator_file = self.root/'locator.json'; locator_file.write_bytes(wire(report['locators'][0])); locator_file.chmod(0o600)
        restored = self.root/'restored'
        code, result = self.run_cli(['restore','--locator',str(locator_file),'--output-dir',str(restored)])
        self.assertEqual(code, 0)
        self.assertEqual((restored/'original.zip').read_bytes(), raw)
        self.assertEqual((restored/'metadata.json').read_bytes(), metadata)
        self.assertEqual(restored.stat().st_mode & 0o777, 0o700)
        self.assertEqual((restored/'original.zip').stat().st_mode & 0o777, 0o600)
        self.assertNotIn('RACE_AI_EXISTING_P0_DAY_V1', json.dumps(result))
        code, _ = self.run_cli(['restore','--locator',str(locator_file),'--output-dir',str(restored)])
        self.assertEqual(code, 2)

    def test_http_denial_stops_without_second_transport_or_archive_fallback(self):
        calls = []
        def denied(path):
            calls.append(path); raise RuntimeError('GITHUB_API_READ_HTTP_403_HALT')
        code, report = self.run_cli(['capture','--artifact','101','--expected-parent','current'], get=denied)
        self.assertEqual(code, 2)
        self.assertEqual(calls, ['actions/artifacts/101'])
        self.assertEqual(self.writer.head(), self.parent)
        self.assertEqual(report['status'], 'EXACT_ORIGINAL_VAULT_REJECTED')

    def test_restore_accepts_single_locator_report_without_rewriting_receipt(self):
        raw, metadata = original()
        from race_ai import boat_private_original_vault as V
        locator = V.retain_original(raw,metadata,self.writer.repo,expected_parent=self.parent,key=KEY,
            transport=self.writer,readback_transport=self.reader,now=NOW)
        report_path = self.root/'single-report.json'
        report_path.write_bytes(wire(dict(status='EXACT_ORIGINAL_VAULT_RETAINED',locators=[locator])))
        report_path.chmod(0o600)
        folder = self.root/'report-restored'
        code, _ = self.run_cli(['restore','--locator',str(report_path),'--output-dir',str(folder)])
        self.assertEqual(code,0)
        self.assertEqual((folder/'metadata.json').read_bytes(),metadata)

    def test_missing_owner_key_or_non_actions_environment_stops_before_get(self):
        for field in ('RACE_AI_STATE_KEY','GITHUB_ACTIONS'):
            env = dict(self.env); env.pop(field)
            code, _ = self.run_cli(['capture','--artifact','101','--expected-parent','current'],
                env=env, get=lambda _:self.fail('missing key made a source request'))
            self.assertEqual(code, 2)

    def test_private_file_manifest_and_result_capture_folder_are_retained_without_get(self):
        raw, metadata = original()
        zip_path, meta_path = self.root/'input.zip', self.root/'input.json'
        zip_path.write_bytes(raw); meta_path.write_bytes(metadata)
        zip_path.chmod(0o600); meta_path.chmod(0o600)
        manifest = self.root/'manifest.json'
        manifest.write_bytes(wire([dict(raw_zip=str(zip_path), metadata_raw=str(meta_path))])); manifest.chmod(0o600)
        code, report = self.run_cli(['retain-files','--manifest',str(manifest),'--expected-parent','current'],
            get=lambda _:self.fail('file backfill requested a source'))
        self.assertEqual(code, 0)
        captures = self.root/'captures'; captures.mkdir(mode=0o700)
        html = b'<html>invented exact result bytes</html>'
        receipt = wire(dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at='2030-04-01T03:00:00Z', source_sha256=sha256(html).hexdigest(), http_status=200))
        for name, body in ((sha256(html).hexdigest()+'.html',html),(sha256(receipt.rstrip(b'\n')).hexdigest()+'.json',receipt)):
            path = captures/name; path.write_bytes(body); path.chmod(0o600)
        code, capture_report = self.run_cli(['retain-captures','--capture-dir',str(captures),'--expected-parent','current'],
            get=lambda _:self.fail('capture backfill requested a source'))
        self.assertEqual(code, 0)
        self.assertNotEqual(report['source_commit'], capture_report['source_commit'])

    def test_control_capture_reuses_already_archived_companion_before_any_companion_get(self):
        from race_ai import boat_private_original_vault as V
        from race_ai.boat_private_original_archive import seal_original_zip
        from race_ai.boat_source_control import build_summary
        from tests.test_boat_private_original_vault import packed
        from tests.test_continuity_checkpoint import session
        cipher = seal_original_zip(packed({'repeat-session.json':session()}),run_id='7',head_sha=HEAD,kind='CONTINUITY',key=KEY)
        continuity = packed({'private-original.enc':cipher})
        control = packed({'source-control.json':wire(build_summary(cipher,run_id=7,head_sha=HEAD,key=KEY))})
        def metadata(raw,ident,name):
            return wire(dict(id=ident,name=name,expired=False,created_at='2030-04-01T02:00:00Z',
                expires_at='2030-04-08T02:00:00Z',digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
                workflow_run=dict(id=7,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD)))
        continuity_meta = metadata(continuity,801,'race-cycle-continuity-7')
        V.retain_original(continuity,continuity_meta,self.writer.repo,expected_parent=self.parent,key=KEY,
            transport=self.writer,readback_transport=self.reader,now=NOW)
        responses = {'actions/artifacts/802':metadata(control,802,'race-source-control-7'),
            'actions/artifacts/802/zip':control,'actions/runs/7':wire(dict(id=7,head_sha=HEAD,workflow_id=405276784,
                head_branch='feat/four-sport-forecast-audit-view-20261022',
                repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937,full_name='haji84/RACE-AI')))}
        code, report = self.run_cli(['capture','--artifact','802','--artifact','801','--expected-parent','current'],
                                   get=lambda path:responses[path])
        self.assertEqual(code,0)
        self.assertEqual(report['retained_originals'],2)


if __name__ == '__main__':
    unittest.main()
