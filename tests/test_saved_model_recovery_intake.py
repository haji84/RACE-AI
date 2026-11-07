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
             patch('race_ai.boat_all_model_recovery.recover_saved_models',return_value=(view,counts)) as recover,\
             patch('race_ai.boat_saved_result_recovery.recover_saved_results',return_value=(view,{'status':'SAVED_RESULTS_RECOVERED'})) as results:
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(cli.intake_saved_models(view,recover_runs=[42]),view)
            reports=[json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(reports[0]['status'],counts['status'])
            self.assertEqual(reports[1]['status'],'SAVED_RESULTS_RECOVERED')
            recover.assert_called_once_with(view,cli.gh,run_ids=[42],day=None)
            results.assert_called_once_with(view,cli.gh,run_ids=[42])


if __name__=='__main__':unittest.main()
