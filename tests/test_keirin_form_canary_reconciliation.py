"""One reviewed reconciliation uses frozen inputs and the actual observation clock."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts import keirin_official_form_canary as api
from tests.test_keirin_result_collection import fixture


NOW = datetime.fromisoformat('2026-11-21T02:20:00+09:00')


class FixtureLease:
    def __init__(self):
        self.calls = []
        self.finished = []

    def assert_active(self, *, now, repo):
        if self.finished:
            raise ValueError('RECONCILIATION_LEASE_CLOSED')

    def before_request(self, **kwargs):
        self.assert_active(now=kwargs['now'], repo='/synthetic')
        self.calls.append(kwargs)

    def finish(self, *, state, now):
        self.finished.append(state)


class CanaryReconciliation(unittest.TestCase):
    def test_scoped_lease_preserves_actual_next_day_receipts_and_source_sequence(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        responses, frozen = fixture()
        lease, calls = FixtureLease(), []
        def request(url, fields=None, referer=None):
            calls.append(url)
            self.assertEqual(lease.calls[-1]['url'], url, 'LEASE_BEFORE_EVERY_REQUEST')
            return dict(url=url, status=200, raw=responses[urlsplit(url).path], observed_at=NOW)
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(reconciliation, 'ReconciliationLease', FixtureLease),
              patch.object(api, '_provider_preflight', side_effect=AssertionError('normal stop is not cleared'))):
            out = api.collect_final_result(repo='/synthetic', private_root=folder,
                frozen_card=frozen, clock=lambda:NOW, request=request, reconciliation_lease=lease)
        self.assertEqual(len(calls), 8)
        self.assertEqual(out['official_order']['race_id'], api.RACE)
        self.assertEqual(out['observed_at'], NOW.astimezone(api.timezone.utc).isoformat())
        self.assertTrue(all(datetime.fromisoformat(row['captured_at']) == NOW
                            for row in out['source_receipts']))
        self.assertEqual(out['payout_unit_state'], 'VERIFIED')

    def test_unknown_or_closed_lease_cannot_make_provider_request(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        _, frozen = fixture()
        closed = FixtureLease(); closed.finished.append('FAILED')
        with patch.object(reconciliation, 'ReconciliationLease', FixtureLease):
            for lease in (True, object(), closed):
                with (self.subTest(lease=type(lease)), tempfile.TemporaryDirectory() as folder,
                      patch.object(api.card_source, '_CurlPublicSession') as transport):
                    with self.assertRaises(ValueError):
                        api.collect_final_result(repo='/synthetic', private_root=folder,
                            frozen_card=frozen, clock=lambda:NOW, reconciliation_lease=lease)
                    transport.assert_not_called()

    def test_lease_closing_before_unit_preserves_verified_order(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        responses, frozen = fixture()
        class GuideExpiredLease(FixtureLease):
            def before_request(self, **kwargs):
                if kwargs['purpose'] == 'OFFICIAL_PAYOUT_UNIT':
                    raise reconciliation.ReconciliationError('HOLD_RECONCILIATION_LEASE_EXPIRED')
                return super().before_request(**kwargs)
        lease, calls = GuideExpiredLease(), []
        def request(url, fields=None, referer=None):
            calls.append(url)
            return dict(url=url, status=200, raw=responses[urlsplit(url).path], observed_at=NOW)
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(reconciliation, 'ReconciliationLease', FixtureLease)):
            out = api.collect_final_result(repo='/synthetic', private_root=folder,
                frozen_card=frozen, clock=lambda:NOW, request=request, reconciliation_lease=lease)
        self.assertEqual(len(calls), 7)
        self.assertEqual(out['official_order']['winning_triples'], [[1, 2, 3]])
        self.assertEqual(out['payout_unit_state'], 'UNAVAILABLE')
        self.assertIsNone(out['safe_diagnostics'][-1]['http_status'])

    def test_actual_denial_still_persists_and_ends_source_sequence(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        responses, frozen = fixture()
        lease, calls = FixtureLease(), []
        def request(url, fields=None, referer=None):
            calls.append(url)
            return dict(url=url, status=403 if url.endswith('/sp/race') else 200,
                        raw=responses[urlsplit(url).path], observed_at=NOW)
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(reconciliation, 'ReconciliationLease', FixtureLease),
              patch.object(api.provider_stop, 'record_denial') as stop):
            with self.assertRaises(api.CanaryError) as error:
                api.collect_final_result(repo='/synthetic', private_root=folder,
                    frozen_card=frozen, clock=lambda:NOW, request=request, reconciliation_lease=lease)
        self.assertEqual(len(calls), 7)
        self.assertEqual(calls[-1], 'https://keirin.jp/sp/race')
        stop.assert_called_once_with(repo='/synthetic', code=api.provider_stop.DENIED,
                                     observed_at=NOW.isoformat())
        self.assertEqual(error.exception.safe_diagnostics[-1]['http_status'], 403)

    def test_origin_failure_cannot_consume_reconciliation_or_access_provider(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        public = Path(api.__file__).resolve().parents[1]/'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(api, 'check_runtime'),
              patch.object(api, '_load_original_bundle', return_value=({}, {}, [])),
              patch.object(api, '_archived_pair', return_value=(b'a', b'b', {'producer_run_id':'123456'})),
              patch.object(api, 'reuse_completed', return_value=None),
              patch('race_ai.keirin_github_evidence_client.GitHubEvidenceClient.read_run_bundle', return_value={}),
              patch.object(api, '_verify_origins', side_effect=api.CanaryError('CANARY_ORIGIN_UNVERIFIED')),
              patch.object(reconciliation, 'begin') as begin,
              patch.object(api, 'collect_final_result') as collect):
            with self.assertRaisesRegex(api.CanaryError, 'CANARY_ORIGIN_UNVERIFIED'):
                api.run_settle(repo='/synthetic', private_root=folder, owner_public_pem=public,
                    owner_private_pem=b'fixture-only', clock=lambda:NOW, reconcile_legacy_stop=True)
            begin.assert_not_called(); collect.assert_not_called()

    def test_post_collection_failure_finishes_attempt_without_regenerating_forecasts(self):
        from race_ai import keirin_provider_reconciliation as reconciliation
        public = Path(api.__file__).resolve().parents[1]/'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
        lease, stages = FixtureLease(), []
        def verify(*args): stages.append('ORIGINALS_AUTHENTICATED')
        def begin(**kwargs):
            self.assertEqual(stages, ['ORIGINALS_AUTHENTICATED'])
            stages.append('CLAIM_COMMITTED')
            return lease
        def collect(**kwargs):
            self.assertEqual(stages[-1], 'CLAIM_COMMITTED')
            self.assertIs(kwargs['reconciliation_lease'], lease)
            return {'safe_diagnostics': []}
        with (tempfile.TemporaryDirectory() as folder,
              patch.dict('os.environ', {'GITHUB_SHA':'a'*40}),
              patch.object(api, 'check_runtime'),
              patch.object(api, '_load_original_bundle', return_value=({'card_manifest':{}}, {}, [])),
              patch.object(api, '_archived_pair', return_value=(b'a', b'b', {'producer_run_id':'123456'})),
              patch.object(api, 'reuse_completed', return_value=None),
              patch('race_ai.keirin_github_evidence_client.GitHubEvidenceClient.read_run_bundle', return_value={}),
              patch.object(api, '_verify_origins', side_effect=verify),
              patch.object(reconciliation, 'begin', side_effect=begin),
              patch.object(api, 'collect_final_result', side_effect=collect),
              patch.object(api, 'compare_frozen', side_effect=ValueError('PRIVATE_INPUT_NOT_FOR_LOGS')),
              patch.object(api.core, 'generate_A_B') as generate):
            with self.assertRaisesRegex(api.CanaryError, 'CANARY_RESULT_COMPARISON_OR_ARCHIVE_FAILED'):
                api.run_settle(repo='/synthetic', private_root=folder, owner_public_pem=public,
                    owner_private_pem=b'fixture-only', clock=lambda:NOW, reconcile_legacy_stop=True)
            generate.assert_not_called()
        self.assertEqual(lease.finished, ['FAILED'])


if __name__ == '__main__':
    unittest.main()
