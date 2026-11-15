"""Offline integrity checks for splitting the complete Python CI suite."""
import unittest
from scripts.ci_unittest_shard import module_key, shard_for_module, leaves

class _Dummy(unittest.TestCase):
    def test_one(self): pass

class CIUnittestShardingTests(unittest.TestCase):
    def test_unique_complete_module_partition(self):
        modules = ["test_boat_" + str(i) for i in range(200)] + ["test_horse_a", "test_ak_a"]
        for total in (1, 2, 4, 7, 16):
            groups = [[x for x in modules if shard_for_module(x, total) == k] for k in range(total)]
            self.assertEqual(sorted(x for group in groups for x in group), sorted(modules))
            self.assertEqual(len(set(x for group in groups for x in group)), len(modules))
    def test_module_key_identifies_normal_test(self):
        self.assertEqual(module_key(_Dummy("test_one")), __name__)
    def test_invalid_shard_counts_are_rejected(self):
        for value in (0, 33, -1, "4", True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): shard_for_module("test_boat_a", value)
        with self.assertRaises(ValueError): shard_for_module("", 4)
    def test_nested_suite_preserves_both_leaf_tests(self):
        suite = unittest.TestSuite([unittest.TestSuite([_Dummy("test_one")]), _Dummy("test_one")])
        self.assertEqual(len(tuple(leaves(suite))), 2)
