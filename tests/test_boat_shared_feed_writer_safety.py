"""Source-free integration checks: two real local Git writers, ephemeral keys."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from race_ai import saved_view_feed as F
from race_ai.racer_intraday import IntradayState
from tests import test_racer_result_bridge as fixtures

FixtureFeed = fixtures.FixtureFeed
saved_view = fixtures.saved_view
NOW = fixtures.NOW


class SharedFeedWriterSafetyTests(unittest.TestCase):
    setUp = fixtures.BridgeTests.setUp
    seed = fixtures.BridgeTests.seed
    bridge = fixtures.BridgeTests.bridge
    capture = fixtures.BridgeTests.capture

    def _other_writer(self):
        repo = Path(self.temp.name) / 'other-writer'
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin',
                        self.git.push_url], check=True, capture_output=True)
        return FixtureFeed(repo)

    def test_actual_late_git_race_preserves_new_forecast_and_replays_saved_result(self):
        state = IntradayState()
        self.capture(state)
        retained = deepcopy(state.control['settlement_captures'])
        capture_bytes = [state.capture(p) for p in retained.values()]
        bridge = self.bridge()
        rival = self._other_writer()
        parent, previous, generation, view = F.current_view(rival, self.boot)
        added = deepcopy(view)
        added['records'].extend(saved_view(('2026-11-08',))['records'])
        added['forecast_base_sha256'] = self.boot['forecast_sha256']
        expected_inventory = F.forecast_inventory(added)
        old_cipher = self.git.read(parent, 'views/' + previous + '.json', F.MAX_WIRE)
        published = []
        original_run = self.git._run

        def concurrent_push(args, **kwargs):
            # Race AFTER the first client's head check, BEFORE server ref update.
            if args and args[0] == 'push' and not published:
                published.append(F.publish_view(rival, self.boot, added,
                    parent=parent, previous=previous, generation=generation))
            return original_run(args, **kwargs)

        with patch.object(self.git, '_run', side_effect=concurrent_push):
            with self.assertRaisesRegex(ValueError, 'STATE_GIT_OPERATION_FAILED'):
                bridge.publish(state, now=NOW)
        self.assertEqual(len(published), 1)
        winner = published[0]['commit']
        self.assertEqual(self.git.head(), winner)
        self.assertEqual(state.control['settlement_captures'], retained)
        self.assertEqual([state.capture(p) for p in retained.values()], capture_bytes)
        self.assertEqual(self.git.read(parent, 'views/' + previous + '.json', F.MAX_WIRE), old_cipher)
        _, _, _, before_replay = F.current_view(self.git, self.boot)
        self.assertEqual(F.forecast_inventory(before_replay), expected_inventory)
        self.assertIsNone(before_replay['records'][0]['result'])

        # A fresh bridge uses the retained bytes, not another provider fetch.
        report = self.bridge().publish(state, now=NOW + timedelta(minutes=1))
        self.assertEqual(report['confirmed'], 1)
        self.assertEqual(report['changed_races'], 1)
        final_commit, _, _, after = F.current_view(self.git, self.boot)
        self.assertEqual(F.forecast_inventory(after), expected_inventory)
        self.assertEqual(after['records'][0]['result']['winning_combinations'], [[1, 2, 3]])
        self.assertIsNone(after['records'][1]['result'])
        self.assertNotEqual(final_commit, winner)
        self.assertEqual(self.bridge().publish(state, now=NOW + timedelta(minutes=2))['changed_races'], 0)
        self.assertEqual(self.git.head(), final_commit)

    def test_stale_display_writer_cannot_replace_confirmed_results(self):
        display = self._other_writer()
        parent, previous, generation, stale = F.current_view(display, self.boot)
        state = IntradayState()
        self.capture(state)
        self.assertEqual(self.bridge().publish(state, now=NOW)['confirmed'], 1)
        current = self.git.head()
        with self.assertRaisesRegex(ValueError, 'FEED_CONCURRENT_UPDATE'):
            F.publish_view(display, self.boot, stale, parent=parent,
                           previous=previous, generation=generation)
        self.assertEqual(self.git.head(), current)
        _, _, _, after = F.current_view(display, self.boot)
        self.assertEqual(after['records'][0]['result']['status'], 'final')


if __name__ == '__main__':
    unittest.main()
