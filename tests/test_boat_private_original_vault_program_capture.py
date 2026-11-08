"""Official B capture retention needs only the pinned archive URL helper."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import race_ai
from race_ai import boat_private_original_vault as V
from tests import test_boat_private_original_vault as F


@contextmanager
def without_model_collector():
    root = Path(__file__).resolve().parents[1]
    # Match a saved-display runner with PR64 available and no optional PR72 checkout.
    with patch.object(race_ai, '__path__', [str(root/'race_ai'), str(root/'pr64-reference'/'race_ai')]), \
            patch.dict(sys.modules, {'scripts.existing_day_program': None,
                                    'race_ai.boat_observed_program_bridge': None}), \
            patch('urllib.request.urlopen', side_effect=AssertionError('official request forbidden')):
        yield


class ProgramCaptureTests(unittest.TestCase):
    def test_official_b_capture_retains_and_restores_exact_bytes_without_collector_or_pr72(self):
        fixture = F.VaultTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = b'invented official B archive bytes\r\n\x00\xff'
        metadata = dict(source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',
            captured_at='2030-04-01T03:00:00Z', source_sha256=V._sha(raw), http_status=200)
        receipt = json.dumps(metadata, indent=3).encode()+b'\n\n'
        with without_model_collector():
            locator = V.retain_capture_bundle([(raw, receipt)], fixture.writer.repo,
                run_id=2, head_sha=F.HEAD, expected_parent=fixture.parent, key=F.KEY,
                transport=fixture.writer, readback_transport=fixture.reader, now=F.NOW)
            retained_head = fixture.writer.head()
            restored = V.restore_capture_bundle(locator, fixture.reader.repo,
                key=F.KEY, transport=fixture.reader)
        self.assertEqual(restored['captures'], [(raw, receipt)])
        self.assertEqual(restored['provenance']['receipt_scope'], 'OWNER_RETAINED_SOURCE_CAPTURES')
        self.assertTrue(restored['provenance']['independent_git_readback_verified'])
        self.assertEqual(fixture.writer.head(), retained_head)

    def test_canonical_b_url_and_calendar_checks_still_reject_altered_identity(self):
        with without_model_collector():
            self.assertTrue(V._capture_url('https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh'))
            for url in (
                'https://www1.mbrace.or.jp/od2/B/203002/b300230.lzh',
                'https://www1.mbrace.or.jp/od2/B/203004/b290401.lzh',
                'https://www1.mbrace.or.jp/od2/B/203004/b300501.lzh',
                'https://www1.mbrace.or.jp/od2/K/203004/k300401.lzh',
                'https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh?extra=1',
                'https://foreign.invalid/od2/B/203004/b300401.lzh',
            ):
                with self.subTest(url=url):
                    self.assertFalse(V._capture_url(url))
