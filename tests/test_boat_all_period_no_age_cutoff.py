"""Real local AES/Git archives; all races and keys below are invented fixtures."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import unittest

from race_ai import saved_view_feed as F, model_pdca_history as H
from race_ai.racer_result_bridge import SavedResultBridge
from race_ai.racer_intraday_handoff import load_intraday, save_intraday
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from scripts import racer_intraday_refresh as R
from scripts.verify_all_history_pdca_readback import verify_snapshot
from tests import test_racer_result_bridge as bridge_fixtures
from tests.test_racer_result_bridge import saved_view
from tests.test_racer_intraday_handoff import FixtureGit
from tests import test_retained_model_pdca_audit as audit_fixtures
from tests.test_racer_daily import NOW

DAYS = ('2000-01-01', '2010-06-01', '2020-12-31', '2025-11-01',
        '2026-10-01', '2026-11-05', '2026-11-06', '2026-11-07')


class AllPeriodNoAgeCutoffTests(unittest.TestCase):
    def setUp(self):
        f = bridge_fixtures.BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        f.setUp(); self.addCleanup(f.doCleanups); self.fixture = f
        self.view = audit_fixtures.HistoricalModelPdcaAudit().capture(saved_view(DAYS))
        f.seed(self.view)
        parent, previous, generation, view = F.current_view(f.git, f.boot)
        F.publish_view(f.git, f.boot, view, parent=parent, previous=previous,
                       generation=generation, history=True)
        self.feed_head = f.git.head()
        self.writer = FixtureGit(f.repo, ref=TRANSFER_REF)
        first = self.writer.commit({'unrelated/retained.enc': b'ORIGINAL'}, None)
        self.writer.push(first, None)
        self.key = bytes(range(32)); self.now = NOW + timedelta(days=1)
        initial = load_intraday(f.repo, initialize=True, key=self.key,
                               transport=self.writer, now=self.now)
        save_intraday(initial, catalogue_sha256='a'*64, key=self.key, now=self.now)

    def bridge(self):
        f = self.fixture
        return SavedResultBridge(f.repo, now=self.now + timedelta(minutes=2),
                                 transport=f.git, bootstrap=f.boot)

    def stage(self, bridge=None):
        return R.stage_existing_pdca_without_source(
            self.fixture.repo, now=self.now + timedelta(minutes=2),
            intraday_transport=self.writer, bridge=bridge or self.bridge(), key=self.key)

    def test_stage_and_independent_readback_cover_every_saved_day_without_age_cutoff(self):
        bridge = self.bridge()
        self.assertTrue(bridge.history)
        self.assertEqual(set(bridge.available_days), set(DAYS))
        with patch.object(R, 'OfficialClient', side_effect=AssertionError('NO_PROVIDER_GET')):
            report = self.stage(bridge)
        self.assertEqual(report['archived_days'], len(DAYS))
        self.assertEqual(report['all_period_stage']['max_age_days'], None)
        self.assertEqual(report['all_period_stage']['indexed_saved_days'], len(DAYS))
        self.assertEqual(report['all_period_stage']['archived_saved_days'], len(DAYS))
        self.assertFalse(report['all_period_stage']['automatic_age_purge'])
        self.assertEqual(report['source_provider_requests'], 0)
        reopened = load_intraday(self.fixture.repo, key=self.key,
                                 transport=FixtureGit(self.fixture.repo, ref=TRANSFER_REF),
                                 now=self.now + timedelta(minutes=3))
        self.assertEqual(set(H._unwrap(reopened['state'].control)['days']), set(DAYS))
        proof = verify_snapshot(reopened['state'], self.bridge(), now=self.now + timedelta(minutes=3))
        self.assertEqual(proof['full_period_saved_days'], len(DAYS))
        self.assertEqual(proof['full_period_independently_read_days'], len(DAYS))
        self.assertTrue(proof['full_period_readback_coverage_proven'])
        self.assertFalse(proof['all_history_completion_proven'], 'pending fixture results remain pending')
        self.assertEqual(self.fixture.git.head(), self.feed_head, 'forecast originals must not be rewritten')

    def test_corrupt_older_day_cannot_save_a_fake_complete_all_history_checkpoint(self):
        bridge = self.bridge(); old_head = self.writer.head()
        original = F.current_view
        def read(git, bootstrap, **kwargs):
            if kwargs.get('day') == DAYS[0]:
                raise ValueError('TEST_CORRUPT_OLDEST_AUTHENTICATED_DAY')
            return original(git, bootstrap, **kwargs)
        with patch.object(F, 'current_view', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'TEST_CORRUPT_OLDEST_AUTHENTICATED_DAY'):
                self.stage(bridge)
        self.assertEqual(self.writer.head(), old_head)
        self.assertEqual(self.fixture.git.head(), self.feed_head)

    def test_repeating_all_period_stage_keeps_original_forecasts_and_revision_counts(self):
        first = self.stage()
        second = self.stage()
        self.assertEqual(first['archived_days'], len(DAYS))
        self.assertEqual(first['archived_revisions'], second['archived_revisions'])
        self.assertEqual(self.fixture.git.head(), self.feed_head)
        for day in DAYS:
            restored = F.current_view(self.fixture.git, self.fixture.boot, day=day)[3]
            expected = dict(self.view, records=[r for r in self.view['records'] if r['event_date_jst'] == day])
            self.assertEqual(F.forecast_inventory(restored), F.forecast_inventory(expected))


if __name__ == '__main__': unittest.main()
