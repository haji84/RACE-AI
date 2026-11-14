"""Deterministic source-free sharding of the existing full Python unittest suite."""
from __future__ import annotations
import argparse
from hashlib import sha256
from pathlib import Path
import sys
import unittest

def module_key(test):
    identity = test.id()
    if not identity: raise ValueError("CI_TEST_ID_REQUIRED")
    parts = identity.split(".")
    if parts[0] == "tests" and len(parts) > 1: return parts[1]
    if parts[0] in ("unittest", "_FailedTest"): return parts[-1]
    return parts[0]

def shard_for_module(module, count):
    if type(count) is not int or not 1 <= count <= 32: raise ValueError("CI_SHARD_COUNT_INVALID")
    if not module: raise ValueError("CI_MODULE_REQUIRED")
    return int.from_bytes(sha256(module.encode("utf-8")).digest()[:8], "big") % count

def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from leaves(item)
        else: yield item

def run(index, count):
    if type(index) is not int or not 0 <= index < count: raise ValueError("CI_SHARD_INDEX_INVALID")
    testdir = Path(__file__).resolve().parents[1] / "tests"
    all_tests = tuple(leaves(unittest.defaultTestLoader.discover(
        start_dir=str(testdir), top_level_dir=str(testdir), pattern="test_*.py")))
    if not all_tests: raise RuntimeError("CI_NO_TESTS_DISCOVERED")
    chosen = tuple(t for t in all_tests if shard_for_module(module_key(t), count) == index)
    if not chosen: raise RuntimeError("CI_EMPTY_TEST_SHARD")
    print(f"CI_PYTHON_SHARD index={index} of={count} discovered={len(all_tests)} selected={len(chosen)}", flush=True)
    # Import errors are _FailedTest instances and must not be silently excluded.
    return unittest.TextTestRunner(verbosity=2, failfast=True).run(
        unittest.TestSuite(chosen)).wasSuccessful()

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--count", type=int, required=True)
    args = p.parse_args(argv)
    try: passed = run(args.index, args.count)
    except (ValueError, RuntimeError) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2
    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
