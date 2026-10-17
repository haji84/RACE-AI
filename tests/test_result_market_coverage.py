"""Source payout presence alone cannot prove a complete multiwinner market."""
import unittest

from race_ai.core import SourceError
from race_ai.official_race_updates import endpoint, parse_update, settlement_for_market
from tests.test_official_race_updates import DAY, page, results


class ResultMarketCoverageTests(unittest.TestCase):
    def test_missing_dead_heat_winner_payout_cannot_settle_as_a_loss(self):
        # Synthetic six-boat result: boats 1 and 2 tie for first, but the
        # supplied payout table has only boat 1's winning single-boat ticket.
        body = results().replace('3連単', '単勝').replace('1-2-3', '1').replace(
            '<td>2</td><td class="is-boatColor2">',
            '<td>1</td><td class="is-boatColor2">')
        with self.assertRaises(SourceError):
            observation = parse_update(page('raceresult', body), kind='raceresult', day=DAY,
                venue='18', race_no=1, source_url=endpoint(DAY, '18', 1, 'raceresult'),
                captured_at='2026-10-15T09:00:00+09:00')
            settlement_for_market(observation, 'win')


if __name__ == '__main__':
    unittest.main()
