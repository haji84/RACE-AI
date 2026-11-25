import unittest
from scripts import keirin_home_first_study as home


class HomePriorityTest(unittest.TestCase):
    def setUp(self):
        self.starters = {n: f'{n:06}' for n in range(1, 8)}
        prefs = ('青森', '愛知県', '東京', '神奈川', '愛知', '外国', '京都')
        self.programme = {n: (reg, prefs[n - 1]) for n, reg in self.starters.items()}
        self.lines = [[2, 5, 1], [3, 4], [6, 7]]
        self.ranks = [[3, 4, 1], [5, 2, 1], [1, 3, 4], [4, 3, 1],
                      [2, 3, 4], [1, 2, 3], [3, 2, 5], [2, 6, 7]]
        self.base = {tuple(t): v for t, v in zip(self.ranks, (.12, .11, .08, .07, .06, .05, .04, .03))}

    def roles(self, **kwargs):
        args = dict(starters=self.starters, programme=self.programme, venue_prefecture='愛知県', lines=self.lines)
        return home.home_roles(**(args | kwargs))

    def test_verified_roles_and_individuals(self):
        self.assertEqual(self.roles(), {2: 2, 5: 3, 1: 4, 3: 0, 4: 0, 6: 0, 7: 0})
        self.assertEqual(self.roles(lines=None, individual=True)[5], 1)
        self.assertEqual(home.prefecture_name('京 都'), '京都')
        self.assertEqual(home.prefecture_name('京都府'), '京都')
        self.assertEqual(home.prefecture_name('北海道'), '北海道')

    def test_missing_or_unmatched_data_preserves_original(self):
        self.assertFalse(self.roles(programme={}))
        self.assertFalse(self.roles(programme=self.programme | {2: ('901234', '愛知')}))
        self.assertFalse(self.roles(venue_prefecture='移転'))
        self.assertFalse(self.roles(lines=None))
        self.assertFalse(self.roles(lines=[[1, 2, 3], [2, 5, 6, 7]]))
        self.assertEqual(home.prioritize_first(self.ranks, {}, {}, published_points=4), self.ranks)

    def test_swap_only_within_four_and_no_mutation(self):
        out = home.prioritize_first(self.ranks, self.base, self.roles(), published_points=4)
        self.assertEqual(out[:2], [self.ranks[1], self.ranks[0]])
        self.assertEqual(out[2:], self.ranks[2:])
        self.assertEqual(self.ranks[0], [3, 4, 1])
        for cap in (4, 8):
            self.assertEqual(set(map(tuple, out[:cap])), set(map(tuple, self.ranks[:cap])))
        self.assertEqual(home.prioritize_first(self.ranks, self.base, self.roles(), published_points=1), self.ranks)

    def test_boolean_and_noninteger_cars_cannot_bind_or_score(self):
        for bad in (True, 1.0, '1'):
            self.assertFalse(self.roles(lines=[[2, 5, bad], [3, 4], [6, 7]]))
            invalid = self.ranks.copy()
            invalid[0] = [3, 4, bad]
            with self.assertRaisesRegex(ValueError, 'car number'):
                home.prioritize_first(invalid, self.base, self.roles(), published_points=4)

    def test_published_budget_and_malformed_input(self):
        for cap in (False, True, 0, 9):
            with self.assertRaises(ValueError):
                home.prioritize_first(self.ranks, {}, {}, published_points=cap)
        for cap in (1, 2, 3):
            self.assertEqual(home.prioritize_first(self.ranks, self.base, self.roles(), published_points=cap), self.ranks)
        for role in (-1, 5, True, 1.5):
            with self.assertRaises(ValueError):
                home.prioritize_first(self.ranks, self.base, self.roles() | {1: role}, published_points=4)
        for prob in (True, 'a', float('nan'), float('inf'), -1.):
            with self.assertRaises(ValueError):
                home.prioritize_first(self.ranks, self.base | {(3, 4, 1): prob}, self.roles(), published_points=4)

    def test_missing_probability_rejected_and_ties_stable(self):
        with self.assertRaises(ValueError):
            home.prioritize_first(self.ranks, {}, self.roles(), published_points=4)
        uniform = {tuple(t): .1 for t in self.ranks}
        self.assertEqual(home.prioritize_first(self.ranks, uniform, dict.fromkeys(self.starters, 0), published_points=4), self.ranks)
