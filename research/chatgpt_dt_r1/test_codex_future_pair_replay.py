"""Synthetic sealed Codex pair replay through the existing private producer."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from race_ai import keirin_official_run_history as codec
from research.chatgpt_dt_r1 import codex_future_candidate, official_inputs
from research.chatgpt_dt_r1 import test_codex_future_candidate as codex_fixture
from research.chatgpt_dt_r1.policy import clock, digest
from scripts import keirin_codex_future_pair_replay as replay
from scripts import keirin_dt_r1_future_shadow as shadow
from tests import test_keirin_dt_r1_future_shadow as shadow_fixture


class CodexFuturePairReplayTests(TestCase):
    @classmethod
    def setUpClass(cls):
        shadow_fixture.FutureShadowTests.setUpClass()
        keys = shadow_fixture.FutureShadowTests
        cls.private, cls.public, cls.owner_pin = keys.private, keys.public, keys.pin

    def setUp(self):
        fixture = codex_fixture.CodexFutureCandidateTests()
        fixture.setUp()
        self.fixture = fixture
        self.candidate = fixture.load()
        self.rid, self.day = fixture.original['race_id'], fixture.day
        self.run, self.commit = '456', '3' * 40
        self.peer = dict(dt_producer_run_id='123', dt_manifest_sha256='a' * 64)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        self.pins = dict(cipher_sha256='b' * 64, evidence_sha256='c' * 64)
        self.source = SimpleNamespace(day=self.day, head='d' * 40,
            index=dict(registry=self.pins, originals={self.rid: fixture.meta}), read=self.read_original)
        self.reads = []
        pin = patch.object(codec.storage, 'PINNED_OWNER_SPKI_SHA256', self.owner_pin)
        pin.start()
        self.addCleanup(pin.stop)
        admit = patch.object(replay.records, 'admit_original',
                             return_value=(fixture.original, {}))
        self.admit = admit.start()
        self.addCleanup(admit.stop)
        common = official_inputs.verification_payload(
            fixture.payload, fixture.original, prediction_at=fixture.at)['normalized_input']
        self.row = fixture.project(input_sha256=common['input_sha256'])
        at = clock(fixture.at)
        start_at, generated_at, seal_at, readback_at = [
            (at + timedelta(seconds=offset)).isoformat() for offset in (1, 2, 3, 4)]
        self.forecast = codex_future_candidate.forecast(
            self.candidate, self.row, generated_or_started_at=start_at)
        self.forecast.update(prediction_at=generated_at,
            scope=shadow._report_scope(True) + '_PENDING_INDEPENDENT_READBACK')
        phases = iter(map(clock, (seal_at, readback_at)))
        with patch.dict(os.environ, {'GITHUB_RUN_ID': self.run}):
            self.entry = shadow._save_forecast(output=output,
                entry=dict(slot_sha256=shadow.slot(self.day, self.rid), source_admitted=True,
                           context_geometry_present=None),
                row=self.row, forecast=self.forecast, payload=fixture.payload, original=fixture.original,
                store=self.source, public=self.public, private=self.private, code_commit=self.commit,
                input_at=fixture.at, prediction_started_at=start_at, proof=None,
                clock=lambda: next(phases), remaining_cipher_bytes=8_000_000, codex_peer=self.peer)
        self.raw = (output / self.entry['cipher']['file']).read_bytes()
        self.manifest = dict(schema=shadow.SCHEMA, model=codex_future_candidate.model_identity(),
            entries=[self.entry], registry=self.pins, summary=dict(schema=shadow.CODEX_SUMMARY_SCHEMA,
                scope=shadow._report_scope(True), day_jst=self.day, reader_run_id=self.run,
                reader_code_commit=self.commit, source_archive_commit=self.source.head,
                started_at=fixture.at, finished_at=readback_at, **self.peer))

    def read_original(self, meta, private):
        self.assertEqual(meta, self.fixture.meta)
        self.assertEqual(private, self.private)
        self.reads.append(meta)
        return self.fixture.payload

    def call(self, *, entry=None, raw=None, manifest=None, candidate=None):
        return replay.replay_codex_original(entry or self.entry, raw or self.raw,
            manifest or self.manifest, self.source, self.rid, self.private, candidate or self.candidate,
            object(), {})

    def rewrite(self, change):
        saved = codec.decrypt_evidence(self.raw, self.private)
        change(saved)
        raw = codec.seal_evidence(saved, self.public, self.day, self.entry['clocks']['seal_started_at'])
        entry = deepcopy(self.entry)
        entry['cipher'].update(sha256=sha256(raw).hexdigest(), bytes=len(raw),
            plaintext_sha256=codec._checked_cipher(raw)['evidence_plaintext_sha256'])
        manifest = dict(self.manifest, entries=[entry])
        return dict(entry=entry, raw=raw, manifest=manifest)

    def test_exact_original_and_only_official_prerace_read(self):
        self.assertEqual(self.call(), self.forecast)
        self.assertEqual(self.reads, [self.fixture.meta])
        self.admit.assert_called_once()

    def test_tampered_ciphertext_and_registry_fail_before_any_source_read(self):
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_CIPHERTEXT$'):
            self.call(raw=self.raw + b' ')
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_SCOPE$'):
            self.call(manifest=dict(self.manifest, registry=dict(self.pins, evidence_sha256='e' * 64)))
        self.assertEqual(self.reads, [])

    def test_authentic_ciphertext_cannot_cover_changed_feature_scope_model_or_probability(self):
        mutations = (
            ('CODEX_REPLAY_FEATURES', lambda saved: saved['feature_row']['codex_features']['riders'][0]
             .update(points=-1)),
            ('CODEX_REPLAY_PRIVATE_BINDING', lambda saved: saved['safe_report'].update(scope='other')),
            ('CODEX_REPLAY_DISTRIBUTION', lambda saved: saved['forecast'].update(model_sha256='9' * 64)),
            ('CODEX_REPLAY_DISTRIBUTION', lambda saved: saved['forecast']['trifectas'][0]
             .update(probability=0)),
            ('CODEX_REPLAY_DISTRIBUTION', lambda saved: saved['forecast']['exactas'][0]
             .update(probability=0)),
            ('CODEX_REPLAY_DISTRIBUTION', lambda saved: saved['forecast']
             .update(prediction_at=self.entry['clocks']['prediction_started_at'])),
        )
        for reason, change in mutations:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(replay.CodexReplayError, '^' + reason + '$'):
                    self.call(**self.rewrite(change))

    def test_altered_material_and_clocks_cannot_rebind_the_original(self):
        changed = self.rewrite(lambda saved: saved['shared_material'].update(dt_producer_run_id='999'))
        self.assertNotEqual(changed['entry']['bindings']['shared_material_sha256'], digest(
            codec.decrypt_evidence(changed['raw'], self.private)['shared_material']))
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_FEATURES$'):
            self.call(**changed)
        entry = deepcopy(self.entry)
        entry['clocks']['local_readback_at'] = self.fixture.cutoff
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_CLOCKS$'):
            self.call(entry=entry, manifest=dict(self.manifest, entries=[entry]))

    def test_wrong_candidate_day_and_official_cutoff_fail_closed(self):
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_DISTRIBUTION$'):
            self.call(candidate=replace(self.candidate, day='2030-01-16'))
        original = deepcopy(self.fixture.original)
        original['snapshot']['published_cutoff_at'] = self.entry['clocks']['local_readback_at']
        self.admit.return_value = (original, {})
        with self.assertRaisesRegex(replay.CodexReplayError, '^CODEX_REPLAY_OFFICIAL_INPUT$'):
            self.call()
