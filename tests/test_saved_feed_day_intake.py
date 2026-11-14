"""A history publisher reads one day without reinserting the old seed days."""
from copy import deepcopy
from contextlib import redirect_stdout
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import boat_saved_view_feed as cli


class DayIntakeTests(unittest.TestCase):
    def test_history_intake_skips_old_seed_but_keeps_new_day(self):
        view={'records':[{'event_date_jst':d} for d in ('2026-11-06','2026-11-07','2026-11-08')]}
        before=deepcopy(view)
        self.assertEqual([r['event_date_jst'] for r in cli.intake_day_scope(view,since_day='2026-11-07')['records']],
                         ['2026-11-07','2026-11-08'])
        self.assertEqual(view,before)

    def test_explicit_historical_day_is_isolated_and_bad_date_rejected(self):
        view={'records':[{'event_date_jst':d} for d in ('2026-11-06','2026-11-07')]}
        self.assertEqual(cli.intake_day_scope(view,day='2026-11-06')['records'],[view['records'][0]])
        self.assertEqual(cli.intake_day_scope(view),view)
        with self.assertRaises(ValueError):cli.intake_day_scope(view,day='2026-02-30')

    def test_explicit_day_reaches_the_history_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'audit/state';state.mkdir(parents=True)
            raw=b'invented-bootstrap'
            config=dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1',bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest(),catchup_artifact_id=1,catchup_sha256='a'*64)
            (state/'boat-saved-view-input.json').write_text(json.dumps(config))
            with patch.object(cli,'ROOT',root),patch.object(cli,'git_auth'),patch.object(cli.F,'open_bootstrap'),\
                 patch.object(cli.F,'FeedRepository') as repo,\
                 patch.object(cli.F,'current_view',side_effect=ValueError('FEED_TEST_HOLD')) as read,redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--day','2026-11-06']),2)
            read.assert_called_once_with(repo.return_value,unittest.mock.ANY,day='2026-11-06')

    def test_view_failure_keeps_fixed_diagnostic_without_private_bodies(self):
        from race_ai.boat_saved_model_view import _need,SavedModelViewError
        try:_need(False,'original prediction identity conflict')
        except SavedModelViewError as error:
            self.assertEqual(error.reason_code,'SAVED_MODEL_VIEW_ORIGINAL_PREDICTION_IDENTITY_CONFLICT')
            self.assertNotIn('ordered_top8',error.reason_code)


if __name__=='__main__':unittest.main()
