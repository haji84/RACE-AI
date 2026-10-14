import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DayPublishCallerTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'scripts/publish_day_feed.py'
        self.assertTrue(path.exists(), 'authenticated automatic day-feed caller must exist')
        spec=importlib.util.spec_from_file_location('day_caller',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_target_is_scoped_to_race_ai_preview(self):
        url='https://race-ai-preview-pbo42t6h3-qq1130034-1738.vercel.app/api/publish-day'
        self.assertEqual(self.module.validate_target(url),url)

    def test_sensitive_or_out_of_scope_target_rejected_without_echo(self):
        for url in ['https://evil.vercel.app/api/publish-day','https://race-ai-preview-pbo42t6h3-qq1130034-1738.vercel.app/api/publish-day?secret=PRIVATE','http://race-ai-preview-pbo42t6h3-qq1130034-1738.vercel.app/api/publish-day','https://race-ai-preview-pbo42t6h3-qq1130034-1738.vercel.app/api/today']:
            with self.subTest(url=url), self.assertRaisesRegex(ValueError,'^PUBLISH_TARGET_INVALID$'):
                self.module.validate_target(url)

    def test_readback_hash_not_only_race_counts(self):
        expected={'date_jst':'2026-10-15','races':156,'venues':[{'venue':'02'}]}
        digest=self.module.canonical_sha(expected)
        self.assertEqual(self.module.verify_day_response(expected,expected,digest),digest)
        tampered={**expected,'venues':[{'venue':'18'}]}
        with self.assertRaisesRegex(ValueError,'READBACK'):
            self.module.verify_day_response(expected,tampered,digest)
