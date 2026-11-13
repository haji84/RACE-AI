"""Real due result queue has no artificial 12/36 official GET ceiling.

The already authenticated queue is finite (one GET per due race), and the
official client still paces and stops on upstream 403/429. These are synthetic
source bytes only: no live HTTP, no forecast regeneration or private data.
"""
from datetime import timedelta
import unittest
from race_ai.racer_intraday import IntradayState
from race_ai.source_retry_policy import SourceWait
from tests.test_racer_result_queue import ResultQueueTests
from tests.test_racer_daily import NOW


class DynamicDueQueueTests(unittest.TestCase):
    state = ResultQueueTests.state
    base = ResultQueueTests.base
    source_results = ResultQueueTests.source_results

    def _ready(self):
        s=self.state()
        s.control.update(day='2026-11-07',schedule='AUTHENTICATED_TEST_SCHEDULE',
                         archive_next=(NOW+timedelta(days=1)).isoformat(),
                         venues=[],meetings={})
        return s

    def _targets(self):
        return [dict(race_id=f'20261104-{venue:02d}-{number:02d}',
                     cutoff_at='2026-11-04T10:00:00+09:00',pending=True)
                for venue in (17,18,19,20,21) for number in range(1,13)]

    def test_sixty_authentic_due_races_are_not_capped_at_thirty_six(self):
        s=self._ready();base=self.base();calls,fetch=self.source_results()
        targets=self._targets()
        result=s.advance(base,now=NOW,fetch=fetch,max_requests=len(targets),
                         result_targets=targets)
        self.assertEqual(result['requests'],60)
        self.assertEqual(len(calls),60)
        self.assertEqual(len(set(calls)),60)
        self.assertEqual(len(s.control['settlement_captures']),60)
        calls.clear()
        repeat=s.advance(base,now=NOW,fetch=fetch,max_requests=len(targets),
                         result_targets=targets)
        self.assertEqual(repeat['requests'],0)
        self.assertEqual(calls,[])

    def test_first_429_stops_even_when_due_count_is_60(self):
        s=self._ready();base=self.base();calls=[]
        def denied(url):
            calls.append(url)
            raise SourceWait('HTTP_RATE_LIMIT', (NOW+timedelta(hours=1)).isoformat(),
                             state='RATE_LIMIT_WAIT')
        first=s.advance(base,now=NOW,fetch=denied,max_requests=60,
                        result_targets=self._targets())
        self.assertEqual(first['requests'],1)
        self.assertEqual(len(calls),1)
        self.assertIn('boatrace',s.control['waits'])


if __name__ == '__main__':
    unittest.main()
