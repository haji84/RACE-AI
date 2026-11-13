"""Fast official result queue: no artificial 12 GET maximum.

Fixture-only older-day due races, exactly-once GET and physical worker checkpoint.
The fast 1-minute publication check and 2-minute pending recheck remain intact.
"""
import unittest
from datetime import timedelta
from unittest.mock import patch
from tests.test_racer_result_queue import ResultQueueTests
from tests.test_racer_daily import NOW
from race_ai import racer_intraday
from race_ai.source_retry_policy import SourceWait

class DueFastResultsNoQuotaTests(unittest.TestCase):
    state=ResultQueueTests.state
    base=ResultQueueTests.base
    source_results=ResultQueueTests.source_results
    def setup(self):
        state=self.state()
        state.control.update(day='2026-11-07',schedule='VERIFIED_TEST_INDEX',
                             archive_next=(NOW+timedelta(days=1)).isoformat(),
                             venues=[],meetings={})
        targets=[dict(race_id=f'20261104-{venue:02d}-{n:02d}',
                      cutoff_at='2026-11-04T10:00:00+09:00',pending=True)
                 for venue in (17,18,19,20,21) for n in range(1,13)]
        return state, targets

    def test_all_sixty_due_results_advance_without_twelve_GET_cap(self):
        state,targets=self.setup();calls,fetch=self.source_results()
        result=state.advance(self.base(),now=NOW,fetch=fetch,max_requests=60,
                             result_targets=targets)
        self.assertEqual(result['requests'],60)
        self.assertEqual(len(calls),60)
        self.assertEqual(len(set(calls)),60)
        self.assertEqual(len(state.control['settlement_captures']),60)
        calls.clear()
        repeated=state.advance(self.base(),now=NOW,fetch=fetch,max_requests=60,
                               result_targets=targets)
        self.assertEqual(repeated['requests'],0)
        self.assertFalse(calls)

    def test_job_deadline_checkpoints_pending_and_next_worker_continues(self):
        state,targets=self.setup();calls,fetch=self.source_results()
        with patch.object(racer_intraday.time,'monotonic',return_value=200.):
            held=state.advance(self.base(),now=NOW,fetch=fetch,max_requests=60,
                               result_targets=targets,source_deadline=199.)
        self.assertEqual(held['requests'],0)
        self.assertFalse(calls)
        with patch.object(racer_intraday.time,'monotonic',return_value=200.):
            done=state.advance(self.base(),now=NOW,fetch=fetch,max_requests=60,
                               result_targets=targets,source_deadline=201.)
        self.assertEqual(done['requests'],60)

    def test_upstream_429_still_blocks_after_first_request(self):
        state,targets=self.setup();calls=[]
        def denied(url):
            calls.append(url)
            raise SourceWait('HTTP_RATE_LIMIT',(NOW+timedelta(hours=1)).isoformat(),
                             state='RATE_LIMIT_WAIT')
        held=state.advance(self.base(),now=NOW,fetch=denied,max_requests=60,
                           result_targets=targets)
        self.assertEqual(held['requests'],1)
        self.assertEqual(len(calls),1)
        self.assertIn('boatrace',state.control['waits'])

if __name__=='__main__':unittest.main()
