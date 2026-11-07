"""Count reports from native recovery must not abort feed publication."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import boat_saved_view_feed as cli


class ModelRecoveryIntakeTests(unittest.TestCase):
    def test_recovery_status_and_counts_reach_the_feed_without_keyword_collision(self):
        view={'records':[]};counts=dict(status='SAVED_MODEL_RECOVERY_COMPLETE',appended_forecasts=0)
        with tempfile.TemporaryDirectory() as folder,patch.object(cli,'ROOT',Path(folder)),\
             patch.dict(os.environ,{'RUNNER_TEMP':folder}),\
             patch('race_ai.boat_all_model_recovery.recover_saved_models',return_value=(view,counts)) as recover:
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(cli.intake_saved_models(view,recover_runs=[42]),view)
            self.assertEqual(json.loads(output.getvalue())['status'],counts['status'])
            recover.assert_called_once_with(view,cli.gh,run_ids=[42],day=None)


if __name__=='__main__':unittest.main()
