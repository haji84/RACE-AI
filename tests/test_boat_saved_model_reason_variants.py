"""Synthetic reason-only history: preserve bodies without qualifying a result."""
from contextlib import redirect_stdout
from copy import deepcopy
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_saved_model_view as M, saved_view_feed as F
from race_ai.boat_saved_view_intake import append_views
from tests.test_boat_saved_model_view import view, add_result, candidates, reconciled_views

OBS = 'saved_result_observation_reason_variants'
REJ = 'saved_result_rejection_reason_variants'


def pair(*, rejection=False):
    base = add_result(view(), status='unsupported' if rejection else 'pending', rejected=rejection)
    field = 'result_observation_rejections' if rejection else 'result_observations'
    base['records'][0][field][0]['reason'] = 'RESULT_METADATA_FIRST'
    extra = deepcopy(base)
    extra['records'][0][field][0]['reason'] = 'RESULT_METADATA_SECOND'
    return base, extra, field


class ReasonVariantTests(unittest.TestCase):
    def test_reason_only_originals_survive_union_replay_and_web_parser(self):
        for rejection in (False, True):
            with self.subTest(rejection=rejection):
                base, extra, field = pair(rejection=rejection)
                before = deepcopy((base, extra)); sidecar = REJ if rejection else OBS
                out = M.merge_saved_views(base, [extra]); row = out['records'][0]
                self.assertEqual(row[field], before[0]['records'][0][field])
                self.assertEqual(row[sidecar], [before[0]['records'][0][field][0], before[1]['records'][0][field][0]])
                self.assertEqual(M.merge_saved_views(out, [extra, base]), out)
                self.assertEqual((base, extra), before)
                self.assertEqual(candidates(row), candidates(base['records'][0]))
                self.assertEqual(row['result']['status'], 'unsupported' if rejection else 'pending')
                proc = subprocess.run(['node', '-e', "require('./web/product-data.js').parse(require('fs').readFileSync(0,'utf8'))"],
                    input=json.dumps(out), text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=20)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_every_non_reason_field_and_exact_clock_remains_strict(self):
        changes = [dict(status='AVAILABLE'), dict(source_sha256='b'*64),
            dict(captured_at='2030-04-01T02:00:00Z'), dict(closed_at='2030-04-01T10:01:00+09:00'),
            dict(race_id='20300401-01-02'), dict(source_url='https://invalid.example/changed'),
            dict(body_identity_verified=True), dict(source_provenance='CHANGED'), dict(unknown={'value':1}),
            dict(data={'results':[{'lane':1,'finish':2}]}), dict(data={'payouts':[{'payout_per_100_yen':999}]}),
            dict(data={'status':'settled'}), dict(missing_reason='CHANGED')]
        for rejection in (False, True):
            for change in changes:
                with self.subTest(rejection=rejection, change=change):
                    base, extra, field = pair(rejection=rejection)
                    # Rejections keyed by hash must still reject differing source
                    # within an alleged reason-variant sidecar, not new captures.
                    extra['records'][0][field][0].update(change)
                    if rejection and 'source_sha256' in change:
                        extra['records'][0][REJ] = [deepcopy(base['records'][0][field][0]), deepcopy(extra['records'][0][field][0])]
                    with self.assertRaises(M.SavedModelViewError): M.merge_saved_views(base, [extra])

    def test_variant_history_is_validated_and_cannot_hide_a_conflict(self):
        for rejection in (False, True):
            base, extra, field = pair(rejection=rejection); out = M.merge_saved_views(base, [extra])
            sidecar = REJ if rejection else OBS
            for change in ('data', 'unknown', 'orphan', 'type', 'empty', 'duplicate', 'single', 'reason', 'no_sha'):
                bad = deepcopy(out); row = bad['records'][0]
                if change == 'data': row[sidecar][1]['data'] = {'finish':2}
                elif change == 'unknown': row[sidecar][1]['SECRET'] = 'SECRET'
                elif change == 'orphan': row[field] = []
                elif change == 'type': row[sidecar] = {}
                elif change == 'empty': row[sidecar] = []
                elif change == 'duplicate': row[sidecar][1] = deepcopy(row[sidecar][0])
                elif change == 'single': row[sidecar] = row[sidecar][:1]
                elif change == 'reason': row[sidecar][1]['reason'] = {'SECRET':'SECRET'}
                else:
                    for item in [*row[field], *row[sidecar]]: item.pop('source_sha256')
                with self.subTest(rejection=rejection, change=change), self.assertRaises(M.SavedModelViewError): M.merge_saved_views(bad)

    def test_available_observation_variants_do_not_rewrite_or_promote_the_projected_result(self):
        base = add_result(view()); extra = deepcopy(base)
        extra['records'][0]['result_observations'][0]['reason'] = None
        out = M.merge_saved_views(base, [extra])
        self.assertEqual(out['records'][0]['result'], base['records'][0]['result'])
        self.assertEqual(out['records'][0]['result_observations'], base['records'][0]['result_observations'])
        self.assertEqual(len(out['records'][0][OBS]), 2)

    def test_later_result_sync_keeps_historical_rejection_anchors_through_aes_and_parser(self):
        for status in ('PENDING', 'AVAILABLE'):
            base, extra, field = pair(rejection=True)
            united = append_views(base, [extra]); before = deepcopy(united)
            incoming = deepcopy(united['records'][0]['result_observations'][0])
            incoming.update(captured_at='2030-04-01T12:00:00+09:00', source_sha256='e'*64,
                            status=status, body_identity_verified=status == 'PENDING')
            updated = F.update_view(united, [incoming], synced_at='2030-04-01T13:00:00+09:00')
            replayed = M.merge_saved_views(updated)
            self.assertEqual(replayed['records'][0][REJ], before['records'][0][REJ])
            self.assertEqual(replayed['records'][0][field][0], before['records'][0][field][0])
            self.assertEqual(replayed['records'][0]['result']['status'], 'pending' if status == 'PENDING' else 'unsupported')
            self.assertEqual(replayed['records'][0]['result']['observed_at'], incoming['captured_at'])
            self.assertEqual(F.update_view(updated, [incoming], synced_at='2030-04-01T13:00:00+09:00'), updated)
            raw = F.encrypt_view(replayed, b'k'*32, view_id='a'*64, source_sha='b'*64, generation=3, previous='c'*64)
            _, decoded = F.decrypt_view(raw, b'k'*32, view_id='a'*64)
            self.assertEqual(decoded['records'][0][REJ], before['records'][0][REJ])
            F.ensure_append_only(united, decoded)
            proc = subprocess.run(['node', '-e', "require('./web/product-data.js').parse(require('fs').readFileSync(0,'utf8'))"],
                input=json.dumps(decoded), text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(united, before)

    def test_result_sync_replays_only_exact_already_validated_observation_alternates(self):
        base, extra, field = pair(); united = append_views(base, [extra]); before = deepcopy(united)
        incoming = extra['records'][0][field]
        updated = F.update_view(united, incoming, synced_at='2030-04-01T13:00:00+09:00')
        self.assertEqual(updated['records'][0][OBS], before['records'][0][OBS])
        self.assertEqual(updated['records'][0][field], before['records'][0][field])
        self.assertEqual(F.update_view(united, [*base['records'][0][field], *incoming], synced_at='2030-04-01T13:00:00+09:00'), updated)
        self.assertEqual(M.merge_saved_views(updated), M.merge_saved_views(F.update_view(united, base['records'][0][field], synced_at='2030-04-01T13:00:00+09:00')))
        for change in (dict(reason='NEW_UNKNOWN_REASON'), dict(data={}), dict(status='AVAILABLE'),
                       dict(source_sha256='e'*64), dict(captured_at='2030-04-01T02:00:00Z'), dict(unknown=True)):
            changed = deepcopy(incoming); changed[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                F.update_view(united, changed, synced_at='2030-04-01T13:00:00+09:00')
        self.assertEqual(united, before)

    def test_later_settled_capture_is_not_blocked_by_historical_rejection_reasons(self):
        base, extra, field = pair(rejection=True); united = append_views(base, [extra])
        settled, _ = reconciled_views(); incoming = deepcopy(settled['records'][0]['result_observations'][0])
        incoming.update(captured_at='2030-04-01T12:00:00+09:00', source_sha256='e'*64,
                        closed_at=united['records'][0]['cutoff_at'])
        updated = F.update_view(united, [incoming], synced_at='2030-04-01T13:00:00+09:00')
        self.assertEqual(updated['records'][0]['result']['status'], 'final')
        self.assertEqual(updated['records'][0][REJ], united['records'][0][REJ])
        self.assertEqual(M.merge_saved_views(updated)['records'][0]['result'], updated['records'][0]['result'])
        F.ensure_append_only(united, updated)

    def test_same_capture_sync_cannot_promote_or_replace_a_preserved_rejection(self):
        base, extra, field = pair(rejection=True)
        # Both already-retained reasons are real HOLD codes; exact source and
        # body remain unchanged, while this later projection can read pending.
        for doc in (base, extra): doc['records'][0]['result_observations'][0]['body_identity_verified'] = True
        united = append_views(base, [extra]); before = deepcopy(united)
        updated = F.update_view(united, base['records'][0]['result_observations'], synced_at='2030-04-01T13:00:00+09:00')
        self.assertEqual(updated['records'][0]['result']['status'], 'unsupported')
        self.assertEqual(updated['records'][0][field], before['records'][0][field])
        self.assertEqual(updated['records'][0][REJ], before['records'][0][REJ])
        # A fresh different rejection under the same capture is not silently
        # appended, normalized or discarded during projection.
        original_base, original_extra, _ = pair(rejection=True)
        original = append_views(original_base, [original_extra])
        with self.assertRaisesRegex(ValueError, '^RESULT_CAPTURE_CONFLICT$'):
            F.update_view(original, original['records'][0]['result_observations'], synced_at='2030-04-01T13:00:00+09:00')
        self.assertEqual(united, before)

    def test_result_sync_refuses_forged_or_orphan_variant_histories(self):
        for rejection in (False, True):
            base, extra, field = pair(rejection=rejection); united = append_views(base, [extra]); sidecar = REJ if rejection else OBS
            incoming = deepcopy(base['records'][0]['result_observations'][0]); incoming['captured_at'] = '2030-04-01T12:00:00+09:00'
            for change in ('orphan', 'unknown', 'empty'):
                invalid = deepcopy(united)
                if change == 'orphan': invalid['records'][0][field] = []
                elif change == 'empty': invalid['records'][0][sidecar] = []
                else: invalid['records'][0][sidecar][1]['unknown'] = 'SECRET'
                with self.subTest(rejection=rejection, change=change), self.assertRaises(ValueError):
                    F.update_view(invalid, [incoming], synced_at='2030-04-01T13:00:00+09:00')

    def test_rejection_variant_cannot_bypass_existing_cutoff_reconciliation(self):
        base, extra = reconciled_views()
        observation = deepcopy(base['records'][0]['result_observations'])
        extra['records'][0].update(result_observations=observation,
            result_observation_rejections=[dict(captured_at=observation[0]['captured_at'], source_sha256='f'*64,
                                               reason='RESULT_AMBIGUOUS_FORECAST_CUTOFF')])
        other = deepcopy(extra)
        other['records'][0]['result_observation_rejections'][0]['reason'] = 'RESULT_ROSTER_MISMATCH'
        out = M.merge_saved_views(base, [extra, other])
        self.assertEqual(out['records'][0]['result']['status'], 'unsupported')
        self.assertEqual(len(out['records'][0][REJ]), 2)
        self.assertEqual(M.merge_saved_views(out, [extra, other]), out)

    def test_no_variant_leaves_existing_shape_and_reason_absence_is_preserved(self):
        base = add_result(view(), status='pending'); extra = deepcopy(base)
        extra['records'][0]['result_observations'][0]['reason'] = None
        out = M.merge_saved_views(base, [extra])
        self.assertNotIn('reason', out['records'][0][OBS][0])
        self.assertIsNone(out['records'][0][OBS][1]['reason'])
        unchanged = M.merge_saved_views(base, [deepcopy(base)])['records'][0]
        self.assertNotIn(OBS, unchanged); self.assertNotIn(REJ, unchanged)

    def test_optional_reason_shapes_and_identical_unknown_fields_are_preserved(self):
        base = add_result(view(), status='pending'); extra = deepcopy(base); third = deepcopy(base)
        for doc in (base, extra, third):
            doc['records'][0]['result_observations'][0]['unknown'] = {'exact':[True, 1, None]}
        extra['records'][0]['result_observations'][0]['reason'] = None
        third['records'][0]['result_observations'][0]['reason'] = 'RESULT_WAIT'
        out = M.merge_saved_views(base, [extra, third])
        expected = [doc['records'][0]['result_observations'][0] for doc in (base, extra, third)]
        self.assertEqual(out['records'][0][OBS], expected)
        self.assertEqual(M.merge_saved_views(out, [third, base, extra]), out)

    def test_malformed_reason_and_null_rejection_cannot_enter_variant_history(self):
        for rejection in (False, True):
            for reason in ('', ' lower ', 'not-a-fixed-code', 'X'*201, [], {}, True, 1, None):
                if reason is None and not rejection: continue
                base, extra, field = pair(rejection=rejection)
                extra['records'][0][field][0]['reason'] = reason
                with self.subTest(rejection=rejection, reason=reason), self.assertRaises(M.SavedModelViewError):
                    M.merge_saved_views(base, [extra])

    def test_cli_still_refuses_conflicting_data_before_any_publication(self):
        from scripts import boat_saved_view_feed as cli
        base, extra, field = pair(); extra['records'][0][field][0]['data'] = {'SECRET':'SECRET'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = root/'audit/state/boat-saved-view-input.json'; config.parent.mkdir(parents=True)
            raw = b'synthetic-bootstrap'
            config.write_text(json.dumps(dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest(), catchup_artifact_id=1, catchup_sha256='a'*64)))
            output = io.StringIO()
            with patch.object(cli, 'ROOT', root), patch.object(cli, 'git_auth'), patch.object(cli.F, 'FeedRepository'), \
                 patch.object(cli.F, 'open_bootstrap', return_value={}), \
                 patch.object(cli.F, 'current_view', return_value=('d'*40, 'c'*64, 1, base)), \
                 patch.object(cli, 'intake_saved_models', side_effect=lambda old, **kw: append_views(old, [extra])), \
                 patch.object(cli.F, 'publish_view') as publish, redirect_stdout(output):
                self.assertEqual(cli.main([]), 2)
            publish.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['reason'], 'SAVED_MODEL_VIEW_CONFLICTING_RESULT_OBSERVATION')
            self.assertNotIn('SECRET', output.getvalue())

    def test_cli_union_reaches_real_aes_without_plaintext_or_original_changes(self):
        from scripts import boat_saved_view_feed as cli
        base, extra, field = pair()
        key = b'k'*32; captured = {}; before = deepcopy((base, extra))
        def publish(git, bootstrap, candidate, **kwargs):
            F.ensure_append_only(base, candidate)
            raw = F.encrypt_view(candidate, key, view_id='a'*64, source_sha='b'*64, generation=2, previous='c'*64)
            _, decoded = F.decrypt_view(raw, key, view_id='a'*64)
            self.assertEqual(decoded, candidate)
            self.assertEqual(decoded['records'][0][OBS], [base['records'][0][field][0], extra['records'][0][field][0]])
            self.assertEqual(F.forecast_inventory(decoded), F.forecast_inventory(base))
            with self.assertRaises(ValueError): F.decrypt_view(raw, b'x'*32, view_id='a'*64)
            damaged = json.loads(raw); damaged['ciphertext'] = base64.b64encode(b'x'*32).decode()
            with self.assertRaises(ValueError): F.decrypt_view(json.dumps(damaged).encode(), key, view_id='a'*64)
            captured['raw'] = raw
            return {'status':'SYNTHETIC_ENCRYPTED_VIEW_VERIFIED'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = root/'audit/state/boat-saved-view-input.json'; config.parent.mkdir(parents=True)
            raw = b'synthetic-bootstrap'
            config.write_text(json.dumps(dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest(), catchup_artifact_id=1, catchup_sha256='a'*64)))
            output = io.StringIO()
            with patch.object(cli, 'ROOT', root), patch.object(cli, 'git_auth'), patch.object(cli.F, 'FeedRepository'), \
                 patch.object(cli.F, 'open_bootstrap', return_value={}), \
                 patch.object(cli.F, 'current_view', return_value=('d'*40, 'c'*64, 1, base)), \
                 patch.object(cli, 'intake_saved_models', side_effect=lambda old, **kw: append_views(old, [extra])), \
                 patch.object(cli, 'observations', return_value=extra['records'][0][field]), patch.object(cli.F, 'publish_view', side_effect=publish), \
                 patch.dict(os.environ, {'RUNNER_TEMP':folder, 'RACE_AI_ORIGINAL_VAULT_ENABLED':'false'}), redirect_stdout(output):
                self.assertEqual(cli.main([]), 0, output.getvalue())
            self.assertIn('SYNTHETIC_ENCRYPTED_VIEW_VERIFIED', output.getvalue())
            self.assertNotIn('RESULT_METADATA', output.getvalue())
            self.assertNotIn(b'RESULT_METADATA', captured['raw'])
        self.assertEqual((base, extra), before)


if __name__ == '__main__': unittest.main()
