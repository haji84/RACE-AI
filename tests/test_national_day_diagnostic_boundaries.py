"""Malformed HTTP responses must not escape as raw upstream tracebacks."""
from contextlib import redirect_stderr
from datetime import datetime
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.national_day_pipeline import main
from tests.test_national_day_pipeline import DAY, NOW, review


class NationalDayDiagnosticBoundaryTests(unittest.TestCase):
    def test_schedule_protocol_failure_is_sanitized_and_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / 'review.json'
            review_path.write_text(json.dumps(review()), encoding='utf-8')
            output = Path(directory) / 'day.json'
            output.write_text('previous-approved-feed', encoding='utf-8')
            stderr = io.StringIO()
            with patch('sys.argv', ['national_day_pipeline', '--date', DAY.isoformat(),
                       '--review', str(review_path), '--output', str(output), '--execute']), \
                 patch('race_ai.national_day_pipeline.datetime') as clock, \
                 patch('race_ai.official_day_schedule.fetch_schedule', side_effect=
                       http.client.BadStatusLine('SYNTHETIC_UPSTREAM_BODY_MUST_NOT_BE_LOGGED')), \
                 patch('race_ai.national_day_pipeline.fetch_archive') as archive, \
                 redirect_stderr(stderr):
                clock.now.return_value = NOW
                clock.fromisoformat.side_effect = datetime.fromisoformat
                failure = None
                try:
                    main()
                except BaseException as error:
                    failure = error
            self.assertIsInstance(failure, SystemExit)
            self.assertEqual(failure.code, 2)
            self.assertIn(stderr.getvalue(), {
                'SAFE_STOP: SCHEDULE_SOURCE_UNAVAILABLE\n',
                'SAFE_STOP: NATIONAL_PIPELINE_INVALID\n',
            })
            self.assertNotIn('SYNTHETIC_UPSTREAM_BODY', stderr.getvalue())
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous-approved-feed')
            archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
