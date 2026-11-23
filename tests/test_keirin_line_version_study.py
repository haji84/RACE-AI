import unittest

from scripts import keirin_line_version_study as versions


def card(groups, clock):
    return {'date':'2026-11-24','race_id':'202611241101','deadline_time':'08:45',
            'fetched_at':f'2026-11-24T{clock}:00+09:00','lines':groups,
            'riders':[{'number':i,'name':f'Starter {i}'} for i in range(1,6)]}


class LineVersionTests(unittest.TestCase):
    def test_outer_order_preserves_the_line_and_inner_order_changes_it(self):
        old=card([[1,2],[3,4,5]],'06:00')
        self.assertEqual(versions.compare(old,card([[3,4,5],[1,2]],'08:30')),'unchanged')
        self.assertEqual(versions.compare(old,card([[3,4,5],[2,1]],'08:30')),'within_line_order')

    def test_publication_and_split_are_distinct(self):
        self.assertEqual(versions.compare(card(None,'06:00'),card([[1,2],[3,4],[5]],'08:30')),'newly_listed')
        self.assertEqual(versions.compare(card([[1,2],[3,4,5]],'06:00'),card([[1,2],[3,4],[5]],'08:30')),'split')

    def test_reject_version_at_cutoff_and_name_changes(self):
        old=card([[1,2],[3,4,5]],'06:00')
        with self.assertRaisesRegex(ValueError,'before the same cutoff'):
            versions.compare(old,card([[1,2],[3,4,5]],'08:45'))
        new=card([[1,2],[3,4,5]],'08:30')
        new['riders'][0]['name']='Someone else'
        with self.assertRaisesRegex(ValueError,'same full field'):
            versions.compare(old,new)


if __name__=='__main__':
    unittest.main()
