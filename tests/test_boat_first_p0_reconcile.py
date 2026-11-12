"""Invented native P0/AES fixtures replay through real retained-result readers."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
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

from race_ai import boat_private_original_vault as V
from race_ai import boat_model_runtime as runtime
from race_ai import saved_view_feed as F
from race_ai.actions_contract import digest
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.boat_pdca_recipient import receiver_document
from race_ai.boat_racer_database import RacerDatabase
from race_ai.boat_racer_term import term_info
from race_ai.boat_saved_view_intake import append_views, project_native_state
from race_ai.racer_intraday_handoff import load_intraday, save_intraday
from tests.intraday_fixture import packet
from tests.test_boat_first_p0_readback import retain_bundle
from tests.test_boat_private_original_vault import KEY, NOW, LocalGit, wire
from tests.test_boat_model_runtime import invented_files
from tests.test_boat_racer_database import term_archive
from tests.test_boat_racer_term import record
from tests.test_boat_sp_settlement import document
from tests.test_racer_intraday_handoff import FixtureGit
from tests.test_racer_result_bridge import FixtureFeed, saved_view

try:
    reconcile = importlib.import_module('scripts.boat_first_p0_reconcile')
except ModuleNotFoundError:
    reconcile = None


class FixtureRuntime(runtime.GitRuntimeRepository):
    def _check_remote(self):
        self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()


class FirstP0ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(reconcile, 'source-free first-P0 reconciliation is absent')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root/'remote.git'
        for cmd in (['git', 'init', '--bare', str(self.remote)],
                    ['git', '--git-dir', str(self.remote), 'config', 'uploadpack.allowFilter', 'true']):
            subprocess.run(cmd, check=True, capture_output=True)
        writer = self.git('vault-writer', LocalGit, V.VAULT_REF)
        reader = self.git('vault-retention-reader', LocalGit, V.VAULT_REF)
        self.vault = self.git('independent-runner', LocalGit, V.VAULT_REF)
        self.repo = self.vault.repo
        parent = writer.commit({'unrelated.enc': b'existing ciphertext'}, None)
        writer.push(parent, None)
        self.bundle = retain_bundle(writer, reader, parent)
        self.feed = FixtureFeed(self.repo)
        self.intraday = FixtureGit(self.repo, ref=TRANSFER_REF)
        state_parent = self.intraday.commit({'state/unrelated.enc': b'old encrypted state'}, None)
        self.intraday.push(state_parent, None)
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_RUN_ID='99', GITHUB_SHA='d'*40, GH_TOKEN='fixture-not-a-credential',
            RUNNER_TEMP=str(self.root), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        auth = patch('scripts.boat_saved_view_feed.git_auth')
        auth.start(); self.addCleanup(auth.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('source request forbidden'))
        network.start(); self.addCleanup(network.stop)
        self.seed_feed(('2030-03-31',))
        self.loaded = load_intraday(self.repo, initialize=True, key=KEY,
                                    transport=self.intraday, now=NOW)
        self.receipts = []
        self.runtime = FixtureRuntime(self.repo)
        self.seed_runtime()

    def seed_runtime(self, registrations=range(4001, 4007), *, mutation=None):
        raw = term_archive(b'\n'.join(record(str(pid)) for pid in registrations))
        self.name_source = dict(source_url=term_info('2026-2')['source_url'],
            source_sha256=sha256(raw).hexdigest(), captured_at=(NOW-timedelta(days=1)).isoformat())
        database = RacerDatabase(clock=lambda: NOW)
        try:
            database.import_term(raw, term='2026-2',
                **{key: self.name_source[key] for key in ('source_url', 'captured_at')})
            self.registry_names = {pid: json.loads(body)['name'] for pid, body in
                                   database.db.execute('SELECT racer_id,document FROM racers')}
            if mutation == 'document':
                database.db.execute('DROP TRIGGER immutable_racers_update')
                pid, body = database.db.execute('SELECT racer_id,document FROM racers LIMIT 1').fetchone()
                document = json.loads(body); document['name'] = '改変氏名'
                database.db.execute('UPDATE racers SET document=? WHERE racer_id=?',
                                    (json.dumps(document), pid))
            elif mutation in ('raw', 'url'):
                database.db.execute('DROP TRIGGER immutable_sources_update')
                if mutation == 'raw':
                    database.db.execute('UPDATE sources SET raw=?', (b'untrusted changed source',))
                else:
                    database.db.execute('UPDATE sources SET url=?', ('https://example.test/untrusted',))
            files = invented_files(); files['racers.sqlite'] = database.serialize()
        finally:
            database.db.close()
        receiver = receiver_document(key=KEY, run_id='99', source_head='d'*40)
        encrypted, _ = runtime.seal_runtime(files, receiver, created_at=NOW.isoformat())
        self.runtime_pointer = runtime.publish_runtime(encrypted, self.repo,
            expected_parent=self.runtime.head(), transport=self.runtime)
        (self.repo/runtime.INPUT_PATH).write_bytes(wire(self.runtime_pointer))

    def git(self, name, cls, ref):
        repo = self.root/name
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', str(self.remote)],
                       check=True, capture_output=True)
        return cls(repo, ref=ref)

    def seed_feed(self, days):
        view = saved_view(days)
        for row in view['records']:
            row['prediction']['prediction_sha256'] = sha256(wire(row['prediction'])).hexdigest()
        view = append_views(view)
        self.bootstrap = dict(key=b'x'*32, view_id='a'*64, cipher_sha256='c'*64,
                              forecast_sha256=F.forecast_anchor(view), pages_commit='d'*40)
        raw = F.encrypt_view(view, self.bootstrap['key'], view_id=self.bootstrap['view_id'],
                             source_sha='c'*64, generation=1, previous='d'*64)
        ident = sha256(raw).hexdigest()
        parent = self.feed.head()
        commit = self.feed.commit({'latest.json': wire(dict(header=json.loads(raw)['header'],
            cipher_sha256=ident))+b'\n', 'views/'+ident+'.json': raw}, parent)
        self.feed.push(commit, parent)
        parent, previous, generation, before = F.current_view(self.feed, self.bootstrap)
        F.publish_view(self.feed, self.bootstrap, before, parent=parent, previous=previous,
                       generation=generation, history=True)
        receiver = receiver_document(key=KEY, run_id='99', source_head='d'*40)
        encoded = F.seal_bootstrap(self.bootstrap['key'], self.bootstrap['view_id'],
            self.bootstrap['cipher_sha256'], self.bootstrap['pages_commit'],
            self.bootstrap['forecast_sha256'], receiver)
        config = dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(encoded).decode(),
            bootstrap_sha256=sha256(encoded).hexdigest(), catchup_artifact_id=123,
            catchup_sha256='e'*64)
        path = self.repo/'audit/state/boat-saved-view-input.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wire(config))

    def capture(self, *, bucket='results', pending=False, at=None, wrong_roster=False):
        doc = document(day='20300401', pending=pending)
        doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
        if wrong_roster:
            doc['maindata']['teiinfolist'][0]['registno'] = '9999'
        raw, receipt = packet(doc, captured=(at or NOW-timedelta(hours=1)).isoformat())
        pointer = self.loaded['state'].remember('RESULT', raw, receipt)
        self.loaded['state'].control.setdefault(bucket, {})['20300401-01-01'] = pointer
        self.receipts.append(receipt)
        return pointer

    def save_results(self):
        self.source_saved = save_intraday(self.loaded, catalogue_sha256='a'*64, now=NOW, key=KEY)
        return self.source_saved

    def receipt_get(self, path, *, ref):
        self.assertEqual(path, 'docs/evidence/2030-04-01/p0-first-receipt.json')
        self.assertEqual(ref, self.bundle['receipt_commit'])
        return deepcopy(self.bundle['receipt_file'])

    def run_reconcile(self, **changes):
        arguments = {key: self.bundle[key] for key in (
            'vault_commit', 'receipt_commit', 'day', 'p0_artifact', 'companion_artifacts')}
        arguments.update(changes)
        return reconcile.reconcile(self.repo, transport=self.vault,
            receipt_get=self.receipt_get, feed_transport=self.feed,
            intraday_transport=self.intraday, runtime_transport=self.runtime,
            now=NOW+timedelta(minutes=1), **arguments)

    def test_native_nameless_rows_receive_only_verified_registry_display_names(self):
        verified, document, rows, metadata = reconcile.readback.verify(self.repo,
            **{key: self.bundle[key] for key in (
                'vault_commit', 'receipt_commit', 'day', 'p0_artifact', 'companion_artifacts')},
            transport=self.vault, receipt_get=self.receipt_get)
        original_digest = digest([document, rows, metadata])
        documents = [dict(artifact_id=101, member_name='forecasts.json',
            member_sha256=verified['json_sha256'], document=document)]
        state = dict(schema='RACE_AI_PRIVATE_ARTIFACT_READBACK_V1', day_jst=self.bundle['day'],
            rows=rows, receipts=[metadata], observations=[], original_documents=documents,
            complete=False, coverage_scope='EXPLICIT_ARTIFACTS_ONLY', excluded_repeats=[])
        state['state_sha256'] = digest(state)
        native = project_native_state(state, documents=documents)
        self.assertTrue(all(not p.get('name') for r in native['records'] for p in r['participants']))
        old_parent, old_cipher, _, old = F.current_view(self.feed, self.bootstrap, day='2030-03-31')
        old_bytes = self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE)
        pointer = self.capture(); raw, receipt = self.loaded['state'].capture(pointer)
        expected_score = reconcile.evaluate(rows, [F.parse_capture(raw, receipt)])
        self.save_results()
        report = self.run_reconcile()
        after = F.current_view(self.feed, self.bootstrap, day=self.bundle['day'])[3]
        people = after['records'][0]['participants']
        self.assertEqual([p.get('name') for p in people],
                         [self.registry_names[p['registration_no']] for p in people])
        for person in people:
            self.assertEqual(person['name_source'], dict(self.name_source,
                kind='VERIFIED_RACER_REGISTRY', registration_no=person['registration_no'], verified=True))
        self.assertEqual(report['display_name_participants'], 6)
        self.assertEqual(report['display_name_present'], 6)
        self.assertEqual(report['display_name_registry_bound'], 6)
        self.assertEqual(report['display_name_missing'], 0)
        self.assertEqual(report['display_name_runtime_commit'], self.runtime_pointer['source_commit'])
        self.assertEqual(report['display_name_registry_source_sha256'], self.name_source['source_sha256'])
        self.assertEqual(F.forecast_inventory(after), F.forecast_inventory(native))
        self.assertEqual([r['prediction'] for r in after['records']], [r['prediction'] for r in native['records']])
        self.assertEqual([r['comparison_predictions'] for r in after['records']],
                         [r['comparison_predictions'] for r in native['records']])
        self.assertEqual(report['native_evaluation_sha256'], digest(expected_score))
        self.assertEqual(report['original_document_set_sha256'], original_digest)
        self.assertEqual(digest([document, rows, metadata]), original_digest)
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3], old)
        self.assertEqual(self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE), old_bytes)

    def test_existing_nameless_native_view_is_enriched_without_rescoring_or_rewriting(self):
        self.seed_runtime((4999,))
        self.capture(); self.save_results()
        initial = self.run_reconcile()
        parent, cipher, _, before = F.current_view(self.feed, self.bootstrap, day=self.bundle['day'])
        old_bytes = self.feed.read(parent, 'views/'+cipher+'.json', F.MAX_WIRE)
        self.assertEqual(initial['display_name_missing'], 6)
        self.seed_runtime()
        report = self.run_reconcile()
        after = F.current_view(self.feed, self.bootstrap, day=self.bundle['day'])[3]
        self.assertTrue(report['feed_changed'])
        self.assertEqual(report['display_name_registry_bound'], 6)
        self.assertEqual(report['display_name_missing'], 0)
        self.assertEqual(F.forecast_inventory(after), F.forecast_inventory(before))
        for field in ('native_evaluation_sha256', 'original_document_set_sha256',
                      'native_verdict_counts', 'model_score_counts'):
            self.assertEqual(report[field], initial[field])
        self.assertEqual(self.feed.read(parent, 'views/'+cipher+'.json', F.MAX_WIRE), old_bytes)

    def test_untrusted_term_sources_or_mismatched_documents_reject_before_publication(self):
        self.capture(); self.save_results()
        before = self.feed.head()
        for mutation in ('raw', 'url', 'document'):
            with self.subTest(mutation=mutation):
                self.seed_runtime(mutation=mutation)
                with self.assertRaisesRegex(ValueError, '^FIRST_P0_RECONCILE_DISPLAY_NAMES_REJECTED$'):
                    self.run_reconcile()
                self.assertEqual(self.feed.head(), before)
                self.assertEqual(self.intraday.head(), self.source_saved['source_commit'])
                self.assertEqual(list(self.root.glob('boat-first-p0-names-*')), [])

    def test_runtime_cipher_mismatch_rejects_without_fallback_or_publication(self):
        self.save_results(); before = self.feed.head()
        original_read = self.runtime.read
        def changed(commit, path, maximum):
            raw = original_read(commit, path, maximum)
            return raw[:-1]+bytes([raw[-1]^1]) if path == self.runtime_pointer['cipher_path'] else raw
        with patch.object(self.runtime, 'read', side_effect=changed), self.assertRaisesRegex(
                ValueError, '^FIRST_P0_RECONCILE_DISPLAY_NAMES_REJECTED$'):
            self.run_reconcile()
        self.assertEqual(self.feed.head(), before)

    def test_saved_B_name_candidates_require_exact_day_race_lane_and_registration(self):
        day = self.bundle['day']
        rid = day.replace('-', '') + '-01-01'
        people = [dict(number=n, registration_no=str(4000+n), name=None)
                  for n in range(1, 7)]
        view = dict(records=[dict(sport='boat', event_date_jst=day,
                                  race_id=rid, participants=people)])
        manifest = dict(schema='RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1',
                        b_sources=[dict(day=day, raw_b_base64='authenticated-B-placeholder')])
        metadata_path = self.root/'program-name-metadata.json'
        metadata_path.write_text(json.dumps(dict(name_alias_sources=manifest)))
        source = dict(day=day, source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',
                      source_sha256='a'*64, captured_at=NOW.isoformat())
        boats = [dict(lane=6, racer_registration_id='4006', name='認証済み短縮名')]
        program = dict(venues=[dict(races=[dict(race_id=rid, boats=boats)])])
        known = {str(4000+n):dict(name='TERM登録選手') for n in range(1, 6)}
        with patch('race_ai.boat_name_aliases._b_programs',
                   return_value=[(source, program)]) as source_reader:
            found = reconcile._saved_program_names(
                {'metadata.json': str(metadata_path)}, view, day, NOW, known)
        source_reader.assert_called_once()
        self.assertEqual(found[rid]['4006'], dict(name='認証済み短縮名', number=6,
            registration_no='4006', source_url=source['source_url'],
            source_sha256=source['source_sha256'], captured_at=source['captured_at']))
        self.assertEqual(len(found[rid]), 1)
        for alternative in (
            dict(lane=5, racer_registration_id='4006', name='不一致'),
            dict(lane=6, racer_registration_id='9999', name='不一致'),
            dict(lane=1, racer_registration_id='4001', name='TERM登録済み'),
        ):
            with self.subTest(alternative=alternative), patch(
                    'race_ai.boat_name_aliases._b_programs',
                    return_value=[(source, dict(venues=[dict(races=[
                        dict(race_id=rid, boats=[alternative])])]))]):
                self.assertEqual(reconcile._saved_program_names(
                    {'metadata.json': str(metadata_path)}, view, day, NOW, known), {})

    def test_legacy_seller_B_requires_original_p0_packet_validation(self):
        day = self.bundle['day']; rid = day.replace('-', '')+'-01-01'
        source = dict(day=day, source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',
                      source_sha256='b'*64, captured_at=NOW.isoformat())
        document = dict(day_jst=day, source_url=source['source_url'],
                        source_sha256=source['source_sha256'],
                        captured_at=source['captured_at'])
        receipt = dict(independently_verified=True)
        metadata_file = self.root/'seller-name-metadata.json'
        metadata_file.write_text(json.dumps(dict(seller_official_source=dict(
            day=day, raw_b_base64=base64.b64encode(b'archived B').decode()))))
        packet_file = self.root/'seller-original-p0.json'
        packet_file.write_text(json.dumps(dict(document=document, receipt=receipt)))
        files = {'metadata.json': str(metadata_file), 'p0-source.json': str(packet_file)}
        view = dict(records=[dict(sport='boat', event_date_jst=day, race_id=rid,
            participants=[dict(number=6, registration_no='4006', name=None)])])
        boats = [dict(lane=6, racer_registration_id='4006', name='原本から取得')]
        parsed = dict(venues=[dict(races=[dict(race_id=rid, boats=boats)])])
        with patch('race_ai.boat_seller_inputs.official_b_cards_source') as verifier, patch(
                'race_ai.boat_name_aliases._b_programs',
                return_value=[(source, parsed)]):
            actual = reconcile._saved_program_names(files, view, day, NOW, {})
        verifier.assert_called_once_with(b'archived B', document, receipt,
                                         day=day, as_of=NOW.isoformat())
        self.assertEqual(actual[rid]['4006']['name'], '原本から取得')
        # Without the original P0 source packet, no name is claimed.
        self.assertEqual(reconcile._saved_program_names(
            {'metadata.json': str(metadata_file)}, view, day, NOW, {}), {})
        metadata_file.write_text(json.dumps(dict(seller_official_source=dict(
            day=day, raw_b_base64='not valid base64 %'))))
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_PROGRAM_SELLER_BYTES_INVALID'):
            reconcile._saved_program_names(files, view, day, NOW, {})

    def test_unverified_or_wrong_day_program_source_never_fills_a_name(self):
        day = self.bundle['day']
        rid = day.replace('-', '')+'-01-01'
        view = dict(records=[dict(sport='boat', event_date_jst=day,
            race_id=rid, participants=[dict(number=6, registration_no='4006', name=None)])])
        path = self.root/'wrong-day-program-metadata.json'
        path.write_text(json.dumps(dict(name_alias_sources=dict(
            schema='RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1',
            b_sources=[dict(day='2030-03-31', raw_b_base64='not-read')]))))
        with patch('race_ai.boat_name_aliases._b_programs',
                   side_effect=AssertionError('wrong-day B must not be parsed')):
            self.assertEqual(reconcile._saved_program_names(
                {'metadata.json':str(path)}, view, day, NOW, {}), {})
        path.write_text(json.dumps(dict(seller_official_source=dict(
            day=day, raw_b_base64=base64.b64encode(b'B').decode()))))
        with patch('race_ai.boat_seller_inputs.official_b_cards_source',
                   side_effect=AssertionError('P0 original is absent')):
            self.assertEqual(reconcile._saved_program_names(
                {'metadata.json':str(path)}, view, day, NOW, {}), {})

    def test_authenticated_program_name_fill_does_not_change_original_or_scoring(self):
        self.seed_runtime(range(4001, 4006))
        self.capture(); self.save_results()
        before = self.run_reconcile()
        self.assertEqual(before['display_name_missing'], 1)
        day = self.bundle['day']; rid = day.replace('-', '')+'-01-01'
        program_name = {rid: {'4006': dict(name='保存済みB短縮名', number=6,
            registration_no='4006', source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',
            source_sha256='a'*64, captured_at=(NOW-timedelta(days=1)).isoformat())}}
        with patch('scripts.boat_first_p0_reconcile._saved_program_names',
                   return_value=program_name):
            after = self.run_reconcile()
        current = F.current_view(self.feed, self.bootstrap, day=day)[3]
        person = next(p for p in current['records'][0]['participants']
                      if p['registration_no']=='4006')
        self.assertEqual(person['name'], '保存済みB短縮名')
        self.assertEqual(person['name_source']['kind'], 'SAME_RACE_PROGRAM')
        self.assertEqual(person['name_source']['race_id'], rid)
        self.assertEqual(after['display_name_missing'], 0)
        self.assertEqual(after['display_name_registry_bound'], 5)
        self.assertEqual(after['display_name_program_candidates'], 1)
        self.assertTrue(after['originals_unchanged'])
        self.assertEqual(after['forecast_rewrites'], 0)
        self.assertEqual(after['new_forecasts_created'], 0)
        for field in ('native_evaluation_sha256', 'native_verdict_counts',
                      'model_score_counts', 'original_document_set_sha256'):
            self.assertEqual(after[field], before[field])
    
    def test_source_free_official_result_names_fill_only_exact_missing_racer(self):
        # The default path remains unchanged until the explicit display-only flag.
        self.seed_runtime(range(4001, 4006))
        self.capture(); self.save_results()
        before = self.run_reconcile()
        self.assertEqual(before['display_name_missing'], 1)
        after = self.run_reconcile(include_verified_result_names=True)
        self.assertEqual(after['display_name_missing'], 0)
        self.assertEqual(after['display_name_result_candidates'], 1)
        self.assertEqual(after['display_name_result_races'], 1)
        current = F.current_view(self.feed, self.bootstrap, day=self.bundle['day'])[3]
        person = next(p for p in current['records'][0]['participants']
                      if p['registration_no'] == '4006')
        self.assertEqual(person['name_source']['kind'], 'SAME_RACE_RESULT')
        self.assertEqual(person['name_source']['race_id'], current['records'][0]['race_id'])
        for field in ('native_evaluation_sha256', 'original_document_set_sha256',
                      'native_verdict_counts', 'model_score_counts'):
            self.assertEqual(after[field], before[field])
        self.assertTrue(after['originals_unchanged'])
        self.assertEqual(after['new_forecasts_created'], 0)
        self.assertEqual(after['provider_requests'], 0)
        self.assertEqual(after['forecast_rewrites'], 0)
        self.assertFalse(after['plaintext_published'])

    def test_retained_result_names_hold_pending_and_foreign_registration(self):
        from race_ai.racer_intraday_source import parse_result
        day = self.bundle['day']; rid = day.replace('-', '')+'-01-01'
        base = dict(records=[dict(sport='boat', race_id=rid,
            participants=[dict(number=6, registration_no='4999', name=None)])])
        raw, receipt = packet(document(day=day.replace('-', '')), captured=NOW.isoformat())
        self.assertEqual(parse_result(raw, receipt, now=NOW)['status'], 'CONFIRMED')
        self.assertEqual(reconcile._retained_result_names([(raw, receipt)], base, NOW), ({}, 0))
        waiting, waiting_receipt = packet(document(day=day.replace('-', ''), pending=True),
                                          captured=NOW.isoformat())
        self.assertEqual(reconcile._retained_result_names(
            [(waiting, waiting_receipt)], base, NOW), ({}, 0))

    def test_conflicting_authenticated_result_names_never_override_a_frozen_identity(self):
        day = self.bundle['day']; rid = day.replace('-', '')+'-01-01'
        target = dict(records=[dict(sport='boat', race_id=rid,
            participants=[dict(number=6, registration_no='4006', name=None)])])
        body = document(day=day.replace('-', ''))
        raw1, rec1 = packet(body, captured=(NOW-timedelta(minutes=1)).isoformat())
        other = deepcopy(body)
        other['maindata']['teiinfolist'][-1]['racername'] = '別の架空名'
        raw2, rec2 = packet(other, captured=NOW.isoformat())
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_RETAINED_RESULT_NAME_CONFLICT'):
            reconcile._retained_result_names([(raw1, rec1), (raw2, rec2)], target, NOW)

    def test_missing_registration_stays_missing_without_guessing(self):
        self.seed_runtime(range(4001, 4006))
        self.capture(); self.save_results()
        report = self.run_reconcile()
        after = F.current_view(self.feed, self.bootstrap, day=self.bundle['day'])[3]
        self.assertEqual(report['display_name_participants'], 6)
        self.assertEqual(report['display_name_present'], 5)
        self.assertEqual(report['display_name_registry_bound'], 5)
        self.assertEqual(report['display_name_missing'], 1)
        missing = after['records'][0]['participants'][-1]
        self.assertIsNone(missing.get('name'))
        self.assertNotIn('name_source', missing)
        self.assertEqual(report['scored_forecasts'], 2)

    def test_statistics_capture_scores_original_and_appends_new_v5_day(self):
        old_parent, old_cipher, _, old = F.current_view(self.feed, self.bootstrap, day='2030-03-31')
        old_wire = self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE)
        self.capture(bucket='results')
        source = self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['status'], 'FIRST_P0_RECONCILED')
        self.assertEqual(report['scored_forecasts'], 2)
        self.assertEqual(report['held_forecasts'], 0)
        self.assertEqual(report['scored_races'], 1)
        self.assertEqual(report['retained_result_captures'], 1)
        self.assertEqual(report['retained_result_races'], 1)
        self.assertEqual(report['results_source_commit'], source['source_commit'])
        self.assertEqual(report['provider_requests'], 0)
        self.assertEqual(report['new_forecasts_created'], 0)
        self.assertFalse(report['source_state_saved'])
        self.assertFalse(report['source_complete'])
        self.assertEqual(report['coverage_scope'], 'EXPLICIT_ARTIFACTS_ONLY')
        self.assertTrue(report['originals_unchanged'])
        self.assertTrue(report['feed_changed'])
        parent, _, generation, updated = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        self.assertEqual(parent, report['feed_commit'])
        self.assertEqual(generation, report['feed_generation'])
        self.assertEqual(updated['records'][0]['result']['status'], 'final')
        native = [updated['records'][0]['prediction'], *updated['records'][0]['comparison_predictions']]
        self.assertEqual(len(native), 2)
        self.assertTrue(all(p['artifact_id'] == 101 and p['external_receipt_verified'] for p in native))
        self.assertTrue(all(p['original_json_sha256'] == report['json_sha256'] for p in native))
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3]['records'], old['records'])
        self.assertEqual(self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE), old_wire)
        self.assertEqual(self.intraday.head(), source['source_commit'])
        self.assertEqual(self.vault.head(), self.bundle['vault_commit'])
        public = wire(report).decode()
        for forbidden in ('top8', 'ranked', 'racername', '4001', '20300401-01-01', '架空', 'per_forecast'):
            self.assertNotIn(forbidden, public)

    def test_missing_results_publishes_exact_original_with_hold_and_replay_is_quiet(self):
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['retained_result_captures'], 0)
        parent, previous, generation, view = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        self.assertIsNone(view['records'][0]['result'])
        again = self.run_reconcile()
        self.assertFalse(again['feed_changed'])
        self.assertEqual((self.feed.head(), again['feed_commit'], again['feed_generation']),
                         (parent, parent, generation))
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[1], previous)
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3], view)

    def test_newer_pending_settlement_does_not_reuse_older_final_statistics(self):
        self.capture(bucket='results', at=NOW-timedelta(hours=2))
        self.capture(bucket='settlement_captures', pending=True, at=NOW-timedelta(hours=1))
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['retained_result_captures'], 2)
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        view = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertEqual(view['records'][0]['result']['status'], 'pending')
        self.assertEqual(len(view['records'][0]['result_observations']), 2)

    def test_wrong_roster_is_rejected_by_existing_scorer_and_cannot_become_a_miss(self):
        self.capture(wrong_roster=True)
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['rejected_forecasts'], 2)
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
                         ['records'][0]['result']['status'], 'unsupported')

    def test_newer_saved_pending_or_rejected_observation_blocks_older_retained_final(self):
        self.capture(at=NOW-timedelta(hours=2))
        self.save_results()
        self.assertEqual(self.run_reconcile()['scored_forecasts'], 2)
        for offset, pending in enumerate((True, False)):
            with self.subTest(pending=pending):
                doc = document(day='20300401', pending=pending)
                doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
                if not pending:
                    doc['maindata']['infolist3t'][0]['winno'] = '3-2-1'
                raw, receipt = packet(doc, captured=(NOW-timedelta(minutes=30-offset)).isoformat())
                parent, previous, generation, view = F.current_view(
                    self.feed, self.bootstrap, day='2030-04-01')
                updated = F.update_view(view, [], captures=[(raw, receipt)], synced_at=NOW.isoformat())
                F.publish_view(self.feed, self.bootstrap, updated, parent=parent,
                               previous=previous, generation=generation)
                report = self.run_reconcile()
                self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
                self.assertEqual(report['scored_forecasts'], 0)
                self.assertEqual(report['held_forecasts'], 2)
                self.assertEqual(report['newer_saved_observation_races'], 1)
                after = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
                self.assertEqual(after['records'][0]['result']['status'],
                                 'pending' if pending else 'unsupported')
                self.assertEqual(after['records'][0]['result_observations'],
                                 updated['records'][0]['result_observations'])

    def test_partial_new_day_cannot_inherit_old_days_completeness_claim(self):
        parent, previous, generation, view = F.current_view(self.feed, self.bootstrap)
        view.update(source_complete=True, coverage_scope='INVENTED_PREVIOUS_DAY_COMPLETE')
        F.publish_view(self.feed, self.bootstrap, view, parent=parent,
                       previous=previous, generation=generation)
        old = F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3]
        self.save_results()
        self.run_reconcile()
        new = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertFalse(new['source_complete'])
        self.assertEqual(new['coverage_scope'], 'EXPLICIT_ARTIFACTS_ONLY')
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3], old)

    def test_future_saved_journal_is_rejected_before_scoring_or_publication(self):
        self.capture()
        self.save_results()
        self.run_reconcile()
        doc = document(day='20300401', pending=True)
        doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
        raw, receipt = packet(doc, captured=(NOW+timedelta(minutes=30)).isoformat())
        parent, previous, generation, view = F.current_view(
            self.feed, self.bootstrap, day='2030-04-01')
        future = F.update_view(view, [], captures=[(raw, receipt)],
                               synced_at=(NOW+timedelta(minutes=31)).isoformat())
        F.publish_view(self.feed, self.bootstrap, future, parent=parent,
                       previous=previous, generation=generation)
        before = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_RESULT_JOURNAL_FUTURE'):
            self.run_reconcile()
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01'), before)
        self.assertEqual(self.intraday.head(), self.source_saved['source_commit'])
        self.assertEqual(self.vault.head(), self.bundle['vault_commit'])

    def test_existing_historical_target_and_later_day_keep_all_prior_predictions(self):
        self.seed_feed(('2030-03-31', '2030-04-01', '2030-04-02'))
        old_target = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        later = F.current_view(self.feed, self.bootstrap, day='2030-04-02')[3]
        self.capture(bucket='settlement_captures')
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['scored_forecasts'], 2)
        updated = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertEqual(updated['records'][0]['prediction'], old_target['records'][0]['prediction'])
        self.assertEqual(len(updated['records'][0]['comparison_predictions']), 2)
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-02')[3], later)

    def test_corrupt_authenticated_capture_pointer_aborts_before_feed_publication(self):
        pointer = self.capture()
        pointer['source_sha256'] = 'f'*64
        self.save_results()
        before = self.feed.head()
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_RETAINED_RESULTS_REJECTED'):
            self.run_reconcile()
        self.assertEqual(self.feed.head(), before)

    def test_count_only_cli_and_private_output_path_are_validated_before_publish(self):
        self.capture()
        self.save_results()
        args = ['--repo-root', str(self.repo), '--vault-commit', self.bundle['vault_commit'],
            '--receipt-commit', self.bundle['receipt_commit'], '--day', self.bundle['day'],
            '--p0-artifact', '101', '--companion-artifact', '801', '--companion-artifact', '802']
        before = self.feed.head()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = reconcile.main(args+['--output', str(self.repo/'forbidden.json')],
                transport=self.vault, receipt_get=self.receipt_get, feed_transport=self.feed,
                intraday_transport=self.intraday, runtime_transport=self.runtime,
                now=NOW+timedelta(minutes=1))
        self.assertEqual(status, 2)
        self.assertEqual(self.feed.head(), before)
        self.assertNotIn(str(self.repo), stdout.getvalue())
        output = self.root/'counts.json'
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = reconcile.main(args+['--output', str(output)],
                transport=self.vault, receipt_get=self.receipt_get, feed_transport=self.feed,
                intraday_transport=self.intraday, runtime_transport=self.runtime,
                now=NOW+timedelta(minutes=1))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.read_bytes()), json.loads(stdout.getvalue()))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('fixture-not-a-credential', stdout.getvalue())
        self.assertNotIn('ordered_top8', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
