import copy
import json
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from race_ai.national_day_pipeline import collect_national_day, validate_review
from race_ai.tokuyama_day_worker import FetchResponse
from tests.test_official_day_schedule import fixture, DAY

NOW = datetime(2026,10,14,19,tzinfo=timezone.utc)


def review():
    return json.loads((Path(__file__).resolve().parents[1] / 'config/operator-official-facts.json').read_text(encoding='utf-8'))


class NationalPipelineTests(unittest.TestCase):
    def test_default_dryrun_does_not_invoke_sources(self):
        with patch('race_ai.national_day_pipeline.fetch_archive') as archive, \
             patch('race_ai.official_day_schedule.fetch_schedule') as schedule:
            result = collect_national_day(DAY, review=review(), now=NOW)
        self.assertEqual(result['status'], 'DRY_RUN')
        self.assertEqual(result['maximum_source_requests'], 2)
        archive.assert_not_called()
        schedule.assert_not_called()

    def test_review_requires_actual_factual_purposes_scopes_and_venues(self):
        for change in (lambda r:r.update(facts_publish=False), lambda r:r.update(venue_codes=['18']),
                       lambda r:r.update(source_scopes=['https://evil.example/']),
                       lambda r:r.update(reviewed_at='2026-10-16T00:00:00+09:00')):
            r=review();change(r)
            with self.assertRaises(ValueError):
                validate_review(r,day=DAY,now=NOW)

    def test_program_failure_keeps_verified_schedule_and_explicit_errors(self):
        def schedule(url,**bounds):
            return FetchResponse(fixture(),url,200,'text/html')
        def unavailable(url,**bounds):
            raise TimeoutError('internal-secret-not-returned')
        result=collect_national_day(DAY,review=review(),execute=True,now=NOW,
            schedule_transport=schedule,archive_transport=unavailable)
        self.assertTrue(result['redistribution_authorized'])
        self.assertEqual(result['races'],0)
        self.assertEqual(result['venues'][1]['status'],'ERROR')
        self.assertEqual(result['venues'][17]['status'],'NO_EVENT')
        self.assertNotIn('internal-secret',str(result))
