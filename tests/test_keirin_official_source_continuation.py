"""Real local Git and synthetic evidence boundaries; never provider requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from copy import deepcopy
import importlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from race_ai import keirin_provider_reconciliation as legacy
from race_ai import keirin_github_provider_stop as stop


NOW = datetime.fromisoformat('2026-11-21T12:00:00+09:00')


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def api(test):
    name = 'race_ai.keirin_official_source_continuation'
    test.assertIsNotNone(importlib.util.find_spec(name),
                         'Authenticated official-source continuation is not implemented')
    return importlib.import_module(name)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.api = api(self)
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.origin = self.root/'origin.git'
        self.writer = self.root/'writer'; self.other = self.root/'other'
        git(self.root, 'init', '--bare', '-b', legacy.archive.BRANCH, str(self.origin))
        git(self.root, 'clone', str(self.origin), str(self.writer))
        git(self.writer, 'config', 'user.name', 'Synthetic fixture')
        git(self.writer, 'config', 'user.email', 'fixture@example.invalid')
        self.write(legacy.MARKER_PATH, canonical(legacy.MARKER))
        self.write('gate.enc', b'SYNTHETIC ENCRYPTED GATE')
        self.write('original.enc', b'RETAIN ORIGINAL')
        git(self.writer, 'add', '.'); git(self.writer, 'commit', '-m', 'synthetic retained state')
        gate_code = git(self.writer, 'rev-parse', 'HEAD')
        p = patch.object(self.api, 'GATE_SOURCE_COMMIT', gate_code); p.start(); self.addCleanup(p.stop)
        started = NOW-timedelta(hours=1)
        self.claim = dict(schema=legacy.CLAIM_SCHEMA, race_id=legacy.RACE, day_jst=legacy.DAY,
            attempt_id='a'*32, run_id=self.api.GATE_RUN_ID, source_commit=gate_code,
            prior_state_commit=gate_code, legacy_stop_blob=legacy.MARKER_BLOB,
            started_at=started.isoformat(), expires_at=(started+timedelta(seconds=600)).isoformat(),
            permitted_purposes=list(legacy.PURPOSES), max_source_requests=8,
            legacy_incident_resolved=False, general_source_release=False)
        self.write(legacy.CLAIM_PATH, canonical(self.claim))
        git(self.writer, 'add', '.'); git(self.writer, 'commit', '-m', 'synthetic prior reconciliation')
        self.finish = dict(schema=legacy.FINISH_SCHEMA, race_id=legacy.RACE,
            attempt_id='a'*32, run_id=self.api.GATE_RUN_ID, source_commit=gate_code,
            claim_commit=git(self.writer, 'rev-parse', 'HEAD'), legacy_stop_blob=legacy.MARKER_BLOB,
            state='FOUR_ARMS_ARCHIVED', finished_at=(started+timedelta(seconds=60)).isoformat(),
            requests_consumed=8, purposes_consumed=list(legacy.PURPOSES),
            legacy_incident_resolved=False, general_source_release=False)
        self.write(legacy.FINISH_PATH, canonical(self.finish))
        git(self.writer, 'add', '.'); git(self.writer, 'commit', '-m', 'synthetic completed reconciliation')
        git(self.writer, 'push', 'origin', legacy.archive.BRANCH)
        git(self.root, 'clone', str(self.origin), str(self.other))
        git(self.other, 'config', 'user.name', 'Synthetic fixture')
        git(self.other, 'config', 'user.email', 'fixture@example.invalid')
        self.source = git(self.writer, 'rev-parse', 'HEAD')
        self.gate_blob = git(self.writer, 'rev-parse', 'HEAD:gate.enc')
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937', GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA=self.source,
            GITHUB_RUN_ID='123456789', GITHUB_RUN_ATTEMPT='1',
            GITHUB_JOB='official-sp-capture', GITHUB_WORKFLOW_REF=legacy.WORKFLOW_REF,
            RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true')
        p = patch.dict(self.api.os.environ, env, clear=False); p.start(); self.addCleanup(p.stop)
        remote = legacy.archive._remote
        p = patch.object(legacy.archive, '_remote', side_effect=lambda repo, **kw:
            remote(repo, synthetic_local=True)); p.start(); self.addCleanup(p.stop)
        # The real cryptographic replay is exercised separately below. These
        # tests keep the remote Git CAS, stops, clocks and route policy real.
        p = patch.object(self.api, '_replay_gate', return_value={'gate.enc': self.gate_blob})
        p.start(); self.addCleanup(p.stop)

    def write(self, path, raw):
        p = self.writer/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)

    def begin(self, repo=None, now=NOW, **kw):
        return self.api.begin(repo=repo or self.writer, now=now, source_commit=self.source,
            owner_private_pem=b'synthetic-private-boundary', event_day=now.astimezone(legacy.JST).date().isoformat(),
            **kw)

    def read(self, path):
        return git(self.origin, 'show', legacy.archive.BRANCH+':'+path)

    def mutate(self, path, raw):
        git(self.other, 'fetch', 'origin', legacy.archive.BRANCH)
        git(self.other, 'reset', '--hard', 'origin/'+legacy.archive.BRANCH)
        p = self.other/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        git(self.other, 'add', '--', path); git(self.other, 'commit', '-m', 'synthetic external append')
        git(self.other, 'push', 'origin', legacy.archive.BRANCH)

    def request(self, lease, **kw):
        args = dict(purpose='OFFICIAL_CALENDAR', method='GET',
                    url='https://keirin.jp/sp/raceschedule', now=NOW)
        args.update(kw); return lease.before_request(**args)

    def test_source_specific_decision_and_claim_are_read_back_without_releasing_legacy_stop(self):
        lease = self.begin(max_requests=3)
        decision = json.loads(self.read(self.api.DECISION_PATH))
        claim = json.loads(self.read(lease.claim_path))
        self.assertEqual(decision['gate_cipher_sha256'], self.api.GATE_CIPHER_SHA256)
        self.assertIs(decision['general_source_release'], False)
        self.assertIs(decision['legacy_incident_resolved'], False)
        self.assertEqual(claim['max_source_requests'], 3)
        self.assertEqual(stop.read_for_observed_day(repo=self.writer, day='2026-11-21'), legacy.MARKER)
        self.assertEqual(self.read('original.enc'), 'RETAIN ORIGINAL')
        self.assertEqual(lease.request_count, 0)
        self.request(lease)
        self.assertEqual(lease.request_count, 1)
        public = json.dumps([decision, claim])
        for private in ('ranked_tickets', 'prediction_sha256', 'source_facts_sha256',
                        'supplement', 'Cookie', 'encp=', 'snum=', 'synthetic-private'):
            self.assertNotIn(private, public)

    def test_replay_failure_or_non_full_finish_grants_no_claim(self):
        with patch.object(self.api, '_replay_gate', side_effect=ValueError('private-key-token-do-not-log')):
            with self.assertRaises(self.api.ContinuationError) as caught: self.begin()
        self.assertNotIn('private-key-token', str(caught.exception))
        with self.assertRaises(subprocess.CalledProcessError): self.read(self.api.DECISION_PATH)
        self.mutate(legacy.FINISH_PATH, canonical(dict(self.finish, state='ORDER_ONLY_ARCHIVED')))
        with self.assertRaises(self.api.ContinuationError): self.begin()
        with self.assertRaises(subprocess.CalledProcessError): self.read(self.api.DECISION_PATH)

    def test_runtime_job_branch_code_event_and_current_day_are_required(self):
        for change in (dict(GITHUB_JOB='form-canary-settle'), dict(GITHUB_EVENT_NAME='push'),
                       dict(GITHUB_EVENT_NAME='pull_request'), dict(GITHUB_RUN_ATTEMPT='2'),
                       dict(GITHUB_REF='refs/heads/untrusted'), dict(GITHUB_REPOSITORY_ID='1'),
                       dict(GITHUB_SHA='f'*40), dict(GITHUB_WORKFLOW_REF='unrelated'),
                       dict(RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='false')):
            with self.subTest(change=change), patch.dict(self.api.os.environ, change):
                with self.assertRaises(self.api.ContinuationError): self.begin()
        with self.assertRaises(self.api.ContinuationError):
            self.api.begin(repo=self.writer, now=NOW, source_commit=self.source,
                owner_private_pem=b'fixture', event_day='2026-11-20')
        for value in (True, 0, 301):
            with self.subTest(budget=value), self.assertRaises(self.api.ContinuationError):
                self.begin(max_requests=value)

    def test_only_observed_routes_and_exact_parameter_shapes_get_permission(self):
        lease = self.begin(max_requests=30)
        for purpose, method, url, fields in (
            ('OFFICIAL_CALENDAR','GET','https://keirin.jp/sp/raceschedule',None),
            ('OFFICIAL_RACE_LIST','POST','https://keirin.jp/sp/racelist',{'encp':'A'*43,'disp':'SJ0301'}),
            ('OFFICIAL_CARD','POST','https://keirin.jp/sp/race',[('encp','B'*43),('disp','SJ0315')]),
            ('OFFICIAL_HISTORY_RESULT','POST','https://keirin.jp/sp/race',{'encp':'C'*43,'disp':'SJ0326'}),
            ('OFFICIAL_FINAL_RESULT','POST','https://keirin.jp/sp/race',{'encp':'D'*43,'disp':'SJ0326'}),
            ('OFFICIAL_PROFILE','GET','https://keirin.jp/sp/racerracentrecord?snum=015001',None),
            ('OFFICIAL_PREDICTION_TAB','GET','https://keirin.jp/sp/json?encp='+'E'*64+'&skbn=1&type=JSJ041',None),
            ('OFFICIAL_PAYOUT_UNIT','GET','https://www.hofukeirin.jp/ticket/',None)):
            lease.before_request(purpose=purpose, method=method, url=url, fields=fields, now=NOW)
        for purpose, path in (
            ('LINE_VIEW_SCRIPT','SJ0314_v.js'), ('PREDICTION_FRAME_SCRIPT','FSJ0315.js'),
            ('PREDICTION_CONTROLLER_SCRIPT','SJ0321_c.js'), ('PUBLIC_JSON_SCRIPT','commonJSON.js'),
            ('PREDICTION_VIEW_SCRIPT','SJ0321_v.js')):
            self.request(lease, purpose=purpose, url='https://keirin.jp/sp/static/js/'+path)
        self.assertEqual(lease.request_count, 13)
        lease.finish(state='COMPLETED', now=NOW)
        with self.assertRaises(self.api.ContinuationError): self.request(lease)

    def test_invalid_requests_close_without_consuming_or_revealing_parameters(self):
        for args in (
            dict(url='https://keirin.jp/pc/json?encp=private'),
            dict(url='https://www.winticket.jp/keirin/'),
            dict(url='https://keirin.jp/sp/raceschedule?retry=private'),
            dict(purpose='OFFICIAL_PROFILE',url='https://keirin.jp/sp/racerracentrecord?snum=015001&token=private'),
            dict(purpose='OFFICIAL_PREDICTION_TAB',url='https://keirin.jp/sp/json?encp='+'E'*64+'&skbn=2&type=JSJ041'),
            dict(purpose='OFFICIAL_CARD',method='POST',url='https://keirin.jp/sp/race',fields={'encp':'B'*43,'disp':'SJ0326'})):
            with self.subTest(args=args), patch.dict(self.api.os.environ, {'GITHUB_RUN_ID':str(700000+len(self.read_run_paths()))}):
                lease = self.begin()
                with self.assertRaises(self.api.ContinuationError) as caught: self.request(lease, **args)
                self.assertNotIn('private', str(caught.exception))
                self.assertEqual(lease.request_count, 0)
                with self.assertRaises(self.api.ContinuationError): self.request(lease)
                lease.finish(state='FAILED', now=NOW)

    def read_run_paths(self):
        return git(self.origin, 'ls-tree', '-r', '--name-only', legacy.archive.BRANCH).splitlines()

    def test_any_new_stop_or_changed_legacy_or_gate_blocks_next_request(self):
        lease = self.begin()
        self.request(lease)
        new = dict(schema=stop.SCHEMA, day_jst='2026-11-21', code=stop.DENIED,
                   observed_at=NOW.isoformat())
        self.mutate(stop.ROOT+'/2026-11-21.json', canonical(new))
        with self.assertRaises(self.api.ContinuationError): self.request(lease)
        self.assertEqual(lease.request_count, 1)
        receipt = lease.finish(state='PROVIDER_STOPPED', now=NOW)
        self.assertEqual(receipt['requests_consumed'], 1)
        with patch.dict(self.api.os.environ, {'GITHUB_RUN_ID':'987654321'}):
            with self.assertRaises(self.api.ContinuationError): self.begin()

    def test_changed_legacy_is_never_an_eligible_exception(self):
        self.mutate(legacy.MARKER_PATH, canonical(dict(legacy.MARKER, observed_at=NOW.isoformat())))
        with self.assertRaises(self.api.ContinuationError): self.begin()

    def test_gate_blob_changes_are_detected_after_successful_admission(self):
        lease = self.begin()
        self.mutate('gate.enc', b'CHANGED ENCRYPTED GATE')
        with self.assertRaises(self.api.ContinuationError): self.request(lease)
        self.assertEqual(lease.request_count, 0)

    def test_shallow_checkout_verifies_code_ancestry_without_fetching_unrelated_state_branch(self):
        unrelated = git(self.writer, 'commit-tree', git(self.writer, 'rev-parse', 'HEAD^{tree}'),
                        '-m', 'unrelated encrypted-state fixture')
        git(self.writer, 'push', 'origin', unrelated+':refs/heads/state/unrelated-private-history')
        shallow = self.root/'shallow'
        git(self.root, 'clone', '--depth=1', '--single-branch', '--branch', legacy.archive.BRANCH,
            self.origin.as_uri(), str(shallow))
        self.assertEqual(git(shallow,'rev-parse','--is-shallow-repository'),'true')
        try:
            lease = self.begin(repo=shallow)
        except self.api.ContinuationError:
            self.fail('A valid newer main checkout is blocked solely because Actions checked it out shallowly')
        self.request(lease)
        self.assertEqual(lease.request_count,1)
        absent = subprocess.run(['git','cat-file','-e',unrelated+'^{commit}'],cwd=shallow,
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.assertNotEqual(absent.returncode,0,'Unrelated state branch must not be fetched for code ancestry')

    def test_expired_reconciliation_finish_is_not_an_admission_proof(self):
        late = dict(self.finish, finished_at=(NOW-timedelta(minutes=49)).isoformat())
        self.mutate(legacy.FINISH_PATH, canonical(late))
        with self.assertRaises(self.api.ContinuationError): self.begin()

    def test_request_and_wall_clock_budgets_close_lease(self):
        lease = self.begin(max_requests=1, lease_seconds=60)
        self.request(lease)
        with self.assertRaises(self.api.ContinuationError): self.request(lease)
        lease.finish(state='PARTIAL', now=NOW)
        with patch.dict(self.api.os.environ, {'GITHUB_RUN_ID':'987654321'}):
            later = self.begin(lease_seconds=60)
            with self.assertRaises(self.api.ContinuationError):
                self.request(later, now=NOW+timedelta(seconds=60))

    def test_expiry_during_remote_recheck_cannot_authorize_using_stale_caller_clock(self):
        ticks = iter((10.0, 10.0, 11.0, 80.0))
        with patch.object(self.api.time, 'monotonic', side_effect=lambda:next(ticks)):
            lease = self.begin(lease_seconds=60)
            with self.assertRaises(self.api.ContinuationError): self.request(lease)
        self.assertEqual(lease.request_count, 0)

    def test_same_run_replay_and_overlapping_other_run_never_grant_second_lease(self):
        lease = self.begin()
        with self.assertRaises(self.api.ContinuationError): self.begin()
        with patch.dict(self.api.os.environ, {'GITHUB_RUN_ID':'987654321'}):
            with self.assertRaises(self.api.ContinuationError): self.begin()
        lease.finish(state='COMPLETED', now=NOW)
        with self.assertRaises(self.api.ContinuationError): self.begin()
        with patch.dict(self.api.os.environ, {'GITHUB_JOB':'official-sp-settle'}):
            second = self.begin()
            self.request(second)
            self.assertEqual(second.request_count, 1)

    def test_existing_live_observer_can_collect_results_while_capture_is_active(self):
        capture = self.begin()
        live_ref = 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main'
        with patch.dict(self.api.os.environ, {'GITHUB_JOB':'observe-results',
                        'GITHUB_WORKFLOW_REF':live_ref, 'GITHUB_RUN_ID':'987654321'}):
            try:
                observer = self.begin()
            except self.api.ContinuationError:
                self.fail('The existing result observer is incorrectly blocked by a capture lease')
            self.request(observer)
            self.assertEqual(observer.request_count, 1)
            observer.finish(state='COMPLETED', now=NOW)
        self.request(capture)
        self.assertEqual(capture.request_count, 1)

    def test_a_job_name_cannot_be_transplanted_into_an_unapproved_workflow(self):
        for job, workflow in (
            ('observe-results', legacy.WORKFLOW_REF),
            ('official-sp-capture', 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main')):
            with patch.dict(self.api.os.environ, {'GITHUB_JOB':job, 'GITHUB_WORKFLOW_REF':workflow}):
                with self.assertRaises(self.api.ContinuationError): self.begin()

    def test_concurrent_claimants_grant_at_most_one_lease(self):
        barrier = Barrier(2); original = self.api._append_files
        def synchronized(*args, **kwargs):
            barrier.wait(timeout=10)
            return original(*args, **kwargs)
        def attempt(repo):
            try: return self.begin(repo=repo)
            except self.api.ContinuationError: return None
        with patch.object(self.api, '_append_files', side_effect=synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            leases = list(pool.map(attempt, (self.writer, self.other)))
        self.assertEqual(sum(value is not None for value in leases), 1)

    def test_lost_push_acknowledgement_consumes_claim_and_never_grants_lease(self):
        original = self.api._append_files
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('private transport response')
        with patch.object(self.api, '_append_files', side_effect=lost):
            with self.assertRaises(self.api.ContinuationError): self.begin()
        with self.assertRaises(self.api.ContinuationError): self.begin()

    def test_remote_readback_failure_never_grants_lease_or_reusable_claim(self):
        with patch.object(self.api, '_readback', side_effect=ValueError('unverified remote')):
            with self.assertRaises(self.api.ContinuationError): self.begin()
        with self.assertRaises(self.api.ContinuationError): self.begin()


class GateReplayTests(unittest.TestCase):
    """Actual RSA/AES, server-origin checks, result parser and four-arm scorer.

    Only the unrelated source-join grammar is supplied by an existing synthetic
    input fixture. No production ciphertext or private key is read in tests.
    """
    def test_authenticated_four_arm_gate_replays_and_rejects_forged_saved_comparison(self):
        from tests import test_keirin_official_form_canary as fixture_module
        from tests.test_keirin_form_canary_origin import fixture as origin_fixture, replace_report
        from tests.test_keirin_result_collection import fixture as result_fixture
        from scripts import keirin_official_form_canary as canary
        from scripts import keirin_official_day_pipeline as pipeline
        from race_ai import keirin_nationwide_auto_storage as storage
        from race_ai import keirin_official_run_history as history
        continuation = api(self)
        fixture_module.FrozenCanaryPackage.setUpClass()
        helper = fixture_module.FrozenCanaryPackage()
        inputs = helper.inputs()
        with TemporaryDirectory() as folder, patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', helper.pin):
            root = Path(folder); repo = root/'repo'; repo.mkdir()
            git(repo, 'init', '-b', 'fixture')
            git(repo, 'config', 'user.name', 'Synthetic fixture')
            git(repo, 'config', 'user.email', 'fixture@example.invalid')
            (repo/'README').write_text('Synthetic proof only')
            git(repo, 'add', '.'); git(repo, 'commit', '-m', 'synthetic parent')
            parent = git(repo, 'rev-parse', 'HEAD')
            source = b'invented pre-race source'
            package = canary.freeze_package(inputs=inputs, card_manifest={}, history_manifest={},
                source_bytes_by_sha={sha256(source).hexdigest():source}, private_root=root/'private',
                public_pem=helper.public, generated_at='2026-11-20T13:01:00+09:00',
                sealed_at='2026-11-20T13:01:01+09:00', producer_run_id='123456', producer_commit='a'*40)
            producer, reader = origin_fixture()
            for packet, member in ((producer,'summary.json'), (reader,'keirin-git-independent.json')):
                with ZipFile(BytesIO(packet['archive_bytes'])) as z:
                    report = json.loads(z.read(member))
                row = report['new_encrypted_originals' if packet is producer else 'records'][0]
                row.update(cipher_sha256=package['baseline_cipher_sha256'],
                    conditioned_cipher_sha256=package['conditioned_cipher_sha256'],
                    baseline_prediction_sha256=package['payload']['baseline']['prediction_sha256'],
                    cohort_sha256=canary.core.digest(canary.COHORT))
                replace_report(packet, member, report)
                for section in ('run','job','artifact'):
                    for key, value in packet[section].items():
                        if isinstance(value, str) and value.startswith('2026-11-20T'):
                            packet[section][key] = value.replace('T00:', 'T03:').replace('T01:', 'T04:')
            producer['artifact']['created_at'] = producer['artifact']['updated_at'] = '2026-11-20T04:01:10Z'
            producer['job']['completed_at'] = '2026-11-20T04:01:15Z'
            responses, frozen = result_fixture()
            raw = responses['/sp/race']; guide = responses['/ticket/']; guide_sha = sha256(guide).hexdigest()
            url = 'https://www.hofukeirin.jp/ticket/'
            capture = dict(raw_result=raw, observed_at='2026-11-20T17:12:00+09:00',
                expected_reference=dict(source_url='https://keirin.jp/sp/race',method='POST',disp='SJ0326',
                    token='D'*43,official_cutoff_at=canary.CUTOFF,starters=frozen['riders']),
                unit_evidence=dict(url=url,source_sha256=guide_sha,observed_at='2026-11-20T17:10:00+09:00',
                    verified_payout_basis_yen=100,exact_excerpt=canary.payout_unit.UNIT_URLS[url]),
                source_bytes_by_sha={guide_sha:guide,sha256(raw).hexdigest():raw})
            def write(path, raw):
                dest=repo/path; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
            def evidence(raw, run):
                envelope=json.loads(raw); digest=envelope['evidence_plaintext_sha256']
                paths=history._refs(canary.DAY,digest)
                receipt=dict(schema=history.RECEIPT,day_jst=canary.DAY,
                    cipher_sha256=sha256(raw).hexdigest(),evidence_plaintext_sha256=digest,
                    observed_at=envelope['observed_at'],report_sha256=envelope['report_sha256'],producer_run_id=run)
                write(paths[0],raw); write(paths[1],history._canonical(receipt))
                return digest, paths
            base_paths=legacy.archive._refs(canary.RACE)
            base_doc=json.loads(package['baseline_cipher'])
            base_receipt=legacy.archive._receipt(base_doc,package['baseline_cipher_sha256'],
                '123456','a'*40,parent,canary.core.digest(canary.COHORT))
            write(base_paths[0],package['baseline_cipher']); write(base_paths[1],canonical(base_receipt))
            git(repo,'add','.'); git(repo,'commit','-m','synthetic baseline')
            form_paths=legacy.archive._form_refs(canary.RACE)
            form_doc=json.loads(package['conditioned_cipher'])
            form_receipt=dict(schema=legacy.archive.FORM_SCHEMA,race_id=canary.RACE,
                cipher_sha256=package['conditioned_cipher_sha256'],original_sealed_at=form_doc['sealed_at'],
                producer_run_id='123456',producer_commit='a'*40,previous_archive_commit=git(repo,'rev-parse','HEAD'),
                branch=legacy.archive.BRANCH,cipher_only_not_source_or_cutoff_attestation=True,
                cohort_sha256=canary.core.digest(canary.COHORT),baseline_cipher_sha256=package['baseline_cipher_sha256'],
                baseline_prediction_sha256=package['payload']['baseline']['prediction_sha256'])
            write(form_paths[0],package['conditioned_cipher']); write(form_paths[1],canonical(form_receipt))
            pre_digest, pre_paths=evidence(package['evidence_cipher'],'123456')
            with patch.object(canary.join,'build_inputs',return_value=inputs):
                scored=canary.compare_frozen(payload=package['payload'],raw_baseline=package['baseline_cipher'],
                    raw_conditioned=package['conditioned_cipher'],owner_private_pem=helper.private,
                    packets=dict(producer=producer,readback=reader),final_capture=capture)
                safe=canary._report('REAL_FUTURE_CANARY_FOUR_ARMS_COMPARISON_COMPLETE')
                safe.update(server_origin_verified=True,paired_comparable_races=1,nationwide_expansion_gate_passed=True,
                    actual_official_result_verified=True,exact_frozen_originals_authenticated=True,same_conditions_all_four_arms=True)
                saved=dict(schema=canary.SETTLEMENT_SCHEMA,day_jst=canary.DAY,race_id=canary.RACE,
                    pre_cutoff_evidence_plaintext_sha256=pre_digest,
                    baseline_cipher_sha256=package['baseline_cipher_sha256'],conditioned_cipher_sha256=package['conditioned_cipher_sha256'],
                    producer_run_id='123456',producer_commit='a'*40,settler_run_id='123457',settler_commit='b'*40,
                    origin_packets=dict(producer=producer,readback=reader),final_capture=capture,**scored,safe_report=safe)
                for corrupt in (False,True):
                    candidate=deepcopy(saved)
                    if corrupt:
                        candidate['comparison']['metrics']['A']['original']['stake_yen'] += 100
                    sealed=history.seal_evidence(pipeline.private_snapshot_json(candidate),helper.public,canary.DAY,
                                               '2026-11-21T02:40:00+09:00')
                    digest, paths=evidence(sealed,'123457')
                    git(repo,'add','.'); git(repo,'commit','-m','synthetic encrypted result')
                    head=git(repo,'rev-parse','HEAD')
                    pins=dict(GATE_DIGEST=digest,GATE_CIPHER_SHA256=sha256(sealed).hexdigest(),
                        GATE_BLOB=git(repo,'rev-parse','HEAD:'+paths[0]),GATE_RUN_ID='123457',GATE_SOURCE_COMMIT='b'*40,
                        PRE_CUTOFF_DIGEST=pre_digest,PRE_CUTOFF_CIPHER_SHA256=sha256(package['evidence_cipher']).hexdigest(),
                        PRE_CUTOFF_BLOB=git(repo,'rev-parse','HEAD:'+pre_paths[0]),PRE_CUTOFF_RUN_ID='123456')
                    with patch.multiple(continuation,**pins):
                        if corrupt:
                            with self.assertRaisesRegex(ValueError,'COMPARISON_NOT_REPRODUCIBLE'):
                                continuation._replay_gate(repo,head,helper.private)
                        else:
                            proof=continuation._replay_gate(repo,head,helper.private)
                            self.assertEqual(set(proof),set(paths+pre_paths+base_paths+form_paths))
                            with self.assertRaises(ValueError):
                                continuation._replay_gate(repo,head,b'not a private key')


if __name__ == '__main__':
    unittest.main()
