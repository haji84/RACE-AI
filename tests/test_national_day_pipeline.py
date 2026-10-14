import copy
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from race_ai.national_day_pipeline import collect_national_day, validate_review, main
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

    def test_schedule_failure_has_fixed_code_and_never_fetches_archive(self):
        for status,code in (('SOURCE_UNAVAILABLE','SCHEDULE_SOURCE_UNAVAILABLE'),
                            ('SOURCE_INVALID','SCHEDULE_SOURCE_INVALID'),
                            ('SOURCE_RIGHTS_BLOCKED','SCHEDULE_SOURCE_RIGHTS_BLOCKED'),
                            ('DAY_INVALID','SCHEDULE_DAY_INVALID'),
                            ('secret-token=https://private.invalid/','SCHEDULE_STATUS_INVALID')):
            with self.subTest(status=status), \
                 patch('race_ai.national_day_pipeline.collect_day_schedule',return_value={'status':status,'body':'internal-secret'}), \
                 patch('race_ai.national_day_pipeline.fetch_archive') as archive:
                with self.assertRaises(ValueError) as failure:
                    collect_national_day(DAY,review=review(),execute=True,now=NOW)
                self.assertEqual(getattr(failure.exception,'code',None),code)
                self.assertEqual(str(failure.exception),code)
                archive.assert_not_called()

    def test_cli_schedule_timeout_prints_only_code_and_preserves_existing_output(self):
        def unavailable(url,**bounds):
            raise TimeoutError('secret-token https://private.invalid/ upstream body')
        with tempfile.TemporaryDirectory() as folder:
            review_path=Path(folder)/'review.json';review_path.write_text(json.dumps(review()),encoding='utf-8')
            output=Path(folder)/'approved.json';output.write_text('previous-approved-feed',encoding='utf-8')
            stderr=io.StringIO()
            with patch('sys.argv',['national_day_pipeline','--date',DAY.isoformat(),'--review',str(review_path),'--output',str(output),'--execute']), \
                 patch('race_ai.national_day_pipeline.datetime') as clock, \
                 patch('race_ai.official_day_schedule.fetch_schedule',side_effect=unavailable), \
                 patch('race_ai.national_day_pipeline.fetch_archive') as archive, redirect_stderr(stderr):
                clock.now.return_value=NOW;clock.fromisoformat.side_effect=datetime.fromisoformat
                with self.assertRaises(SystemExit) as failure: main()
            self.assertEqual(failure.exception.code,2)
            self.assertEqual(stderr.getvalue(),'SAFE_STOP: SCHEDULE_SOURCE_UNAVAILABLE\n')
            self.assertEqual(output.read_text(encoding='utf-8'),'previous-approved-feed')
            archive.assert_not_called()

    def test_cli_unexpected_failure_never_prints_exception_text(self):
        with tempfile.TemporaryDirectory() as folder:
            review_path=Path(folder)/'review.json';review_path.write_text(json.dumps(review()),encoding='utf-8')
            output=Path(folder)/'missing.json';stderr=io.StringIO()
            with patch('sys.argv',['national_day_pipeline','--date',DAY.isoformat(),'--review',str(review_path),'--output',str(output),'--execute']), \
                 patch('race_ai.national_day_pipeline.collect_national_day',side_effect=ValueError('secret-body https://private.invalid/')), redirect_stderr(stderr):
                with self.assertRaises(SystemExit): main()
            self.assertEqual(stderr.getvalue(),'SAFE_STOP: NATIONAL_PIPELINE_INVALID\n')
            self.assertFalse(output.exists())
