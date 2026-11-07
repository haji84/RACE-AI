"""Synthetic CP932 official-layout fixtures exercise the real pinned parsers."""
from copy import deepcopy
from datetime import date
import hashlib
import struct
import unittest

DAY = date(2026, 11, 4)
AS_OF = "2026-11-05T19:00:00+09:00"
CAPTURE = "2026-11-05T18:00:00+09:00"


def daily_pair():
    b = ["STARTB", "17BBGN", "2026年11月4日"]
    k = ["STARTK", "17KBGN", "2026/11/04"]
    # Race 1: frame 6 enters course 1. Race 2: frame 3 stays course 3,
    # but frame 4 crosses it into course 2. Race 3: ordinary frame entry.
    for number, courses, finishes in (
        (1, [2, 3, 4, 5, 6, 1], [2, 3, 4, 5, 6, 1]),
        (2, [1, 4, 3, 2, 5, 6], [4, 3, 2, 1, 5, 6]),
        (3, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]),
    ):
        b.append(f" {number}R TEST H1800m 電話投票締切予定 12:{number:02d}")
        k.append(f" {number}R TEST H1800m")
        k.append(" 逃げ")
        for frame in range(1, 7):
            b.append(f" {frame} {4000 + frame} TEST")
            k.append(f" {finishes[frame-1]:02d} {frame} {4000+frame} TEST 55 33 6.80 {courses[frame-1]} 0.12 1.50.4")
    b.append("17BEND")
    k.extend(["17KEND","FINALK"])
    return "\n".join(b).encode("cp932"), "\n".join(k).encode("cp932")


def uncompressed_lzh(raw, filename):
    """One synthetic level-zero LHA entry; the production extractor stays real."""
    name = filename.encode("ascii")
    crc = 0
    for byte in raw:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    header = (b"-lh0-" + struct.pack("<IIIBBB", len(raw), len(raw), 0, 0x20, 0, len(name))
              + name + struct.pack("<H", crc))
    return bytes([len(header), sum(header) & 255]) + header + raw + b"\0"


def metadata(raw, kind):
    return {
        "source_url": f"https://www1.mbrace.or.jp/od2/{kind}/202611/{kind.lower()}261104.lzh",
        "source_sha256": ("a" if kind == "B" else "b") * 64,
        "extracted_text_sha256": hashlib.sha256(raw).hexdigest(),
        "captured_at": CAPTURE,
    }


def module(test):
    try:
        from race_ai import boat_entry_observations
    except ImportError:
        test.fail("entry-history intake and conditional statistics are missing")
    return boat_entry_observations


def history(test, b=None, k=None, **overrides):
    original_b, original_k = daily_pair()
    b = original_b if b is None else b
    k = original_k if k is None else k
    kwargs = {"day": DAY, "b_source": metadata(b, "B"), "k_source": metadata(k, "K")}
    kwargs.update(overrides)
    return module(test).build_entry_history(b, k, **kwargs)


class BoatEntryObservationsTests(unittest.TestCase):
    def test_real_archive_extraction_preserves_byte_hashes_and_computed_text_hashes(self):
        b, k = daily_pair()
        archives = [uncompressed_lzh(raw, name) for raw, name in ((b, "B261104.TXT"), (k, "K261104.TXT"))]
        sources = [metadata(raw, kind) for raw, kind in ((b, "B"), (k, "K"))]
        for archive, source in zip(archives, sources):
            source["source_sha256"] = hashlib.sha256(archive).hexdigest()
            del source["extracted_text_sha256"]
        out = module(self).build_entry_history_from_archives(
            *archives, day=DAY, b_source=sources[0], k_source=sources[1])
        self.assertEqual(len(out["records"]), 3)
        self.assertEqual(out["source_proofs"]["B"]["extracted_text_sha256"], hashlib.sha256(b).hexdigest())
        self.assertEqual(out["source_proofs"]["K"]["source_sha256"], hashlib.sha256(archives[1]).hexdigest())
        with self.assertRaisesRegex(ValueError, "HASH"):
            module(self).build_entry_history_from_archives(
                archives[0] + b"tampered", archives[1], day=DAY, b_source=sources[0], k_source=sources[1])

    def test_official_pair_uses_printed_closing_and_keeps_both_source_proofs(self):
        out = history(self)
        self.assertEqual(len(out["records"]), 3)
        self.assertEqual(out["records"][0]["cutoff_at"], "2026-11-04T12:01:00+09:00")
        self.assertEqual(out["records"][0]["result_captured_at"], CAPTURE)
        self.assertEqual(out["records"][0]["source_sha256"], "b" * 64)
        self.assertEqual(out["source_proofs"]["B"]["source_sha256"], "a" * 64)
        self.assertEqual(out["source_proofs"]["K"]["source_sha256"], "b" * 64)
        self.assertEqual(out["excluded_races"], {})

    def test_blank_lines_before_original_headers_keep_actual_closing(self):
        b, k = daily_pair()
        b = b.replace(b" 1R TEST", b"\r\n\r\n 1R TEST")
        self.assertEqual(history(self, b=b, k=k)["records"][0]["cutoff_at"], "2026-11-04T12:01:00+09:00")

    def test_displacement_and_unchanged_course_crossing_have_separate_samples(self):
        out = module(self).conditional_profile_before(history(self), as_of=AS_OF, racer_id="4003")
        self.assertEqual(out["racer_id"], "4003")
        self.assertEqual(out["sample_races"], 3)
        buckets = out["conditional_buckets"]
        self.assertEqual(buckets["displaced"], {
            "starts": 1, "wins": 0, "top2": 0, "top3": 0, "denominator": 1,
            "win_rate": 0.0, "top2_rate": 0.0, "top3_rate": 0.0})
        self.assertEqual(buckets["crossed_by_outer_frame"], {
            "starts": 2, "wins": 0, "top2": 1, "top3": 1, "denominator": 2,
            "win_rate": 0.0, "top2_rate": 0.5, "top3_rate": 0.5})
        self.assertEqual(buckets["any_inward_mover_present"]["starts"], 2)
        course = out["actual_course_when_inward_mover_present"]
        self.assertEqual(course["3"]["starts"], 1)
        self.assertEqual(course["3"]["top2_rate"], 1.0)
        self.assertEqual(course["4"]["starts"], 1)
        self.assertEqual(out["source_proofs"][0]["B"]["source_sha256"], "a" * 64)

    def test_inward_and_outer_to_inner3_rates_are_descriptive(self):
        out = module(self).conditional_profile_before(history(self), as_of=AS_OF, racer_id="4006")
        for name in ("inward", "outer_to_inner3"):
            self.assertEqual(out["conditional_buckets"][name], {
                "starts": 1, "wins": 1, "top2": 1, "top3": 1, "denominator": 1,
                "win_rate": 1.0, "top2_rate": 1.0, "top3_rate": 1.0})
        self.assertFalse(out["source_authenticity_independently_verified"])

    def test_empty_samples_have_zero_denominators_and_null_rates(self):
        out = module(self).conditional_profile_before(history(self), as_of=AS_OF, racer_id="4999")
        self.assertEqual(out["sample_races"], 0)
        for bucket in list(out["conditional_buckets"].values()) + list(out["actual_course_when_inward_mover_present"].values()):
            self.assertEqual(bucket, {"starts": 0, "wins": 0, "top2": 0, "top3": 0,
                "denominator": 0, "win_rate": None, "top2_rate": None, "top3_rate": None})

    def test_rejects_url_date_hash_and_roster_mismatch(self):
        b, k = daily_pair()
        wrong = metadata(b, "B")
        wrong["source_url"] = wrong["source_url"].replace("261104", "261103")
        with self.assertRaisesRegex(ValueError, "SOURCE_IDENTITY"):
            history(self, b_source=wrong)
        wrong = metadata(k, "K")
        wrong["extracted_text_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SOURCE_HASH"):
            history(self, k_source=wrong)
        with self.assertRaisesRegex(ValueError, "date|DATE"):
            history(self, k=k.replace(b"2026/11/04", b"2026/11/03"))
        with self.assertRaisesRegex(ValueError, "ROSTER"):
            history(self, k=k.replace(b"4001", b"4999", 1))

    def test_source_hash_cannot_be_replaced_after_roster_join(self):
        h = history(self)
        h["source_proofs"]["B"]["source_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "SOURCE"):
            module(self).conditional_profile_before(h, as_of=AS_OF, racer_id="4001")

    def test_results_available_at_or_after_as_of_are_rejected(self):
        h = history(self)
        for clock in (CAPTURE, "2026-11-05T17:59:59+09:00"):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                module(self).conditional_profile_before(h, as_of=clock, racer_id="4001")
        changed = deepcopy(h)
        changed["records"][0]["result_captured_at"] = "2026-11-05T20:00:00+09:00"
        with self.assertRaises(ValueError):
            module(self).conditional_profile_before(changed, as_of=AS_OF, racer_id="4001")

    def test_b_source_must_also_be_available_before_as_of(self):
        b, _ = daily_pair()
        source = metadata(b, "B")
        source["captured_at"] = AS_OF
        with self.assertRaises(ValueError):
            module(self).conditional_profile_before(history(self, b_source=source), as_of=AS_OF, racer_id="4001")

    def test_special_finishes_are_excluded_instead_of_counted_as_losses(self):
        _, k = daily_pair()
        k = k.replace(b"02 1 4001", b"F1 1 4001", 1)
        h = history(self, k=k)
        self.assertEqual(len(h["records"]), 2)
        self.assertEqual(h["excluded_races"], {"20261104-17-01": "UNVERIFIED_OR_SPECIAL_FINISH"})

    def test_duplicate_daily_history_cannot_double_count(self):
        h = history(self)
        with self.assertRaises(ValueError):
            module(self).conditional_profile_before([h, h], as_of=AS_OF, racer_id="4001")


if __name__ == "__main__":
    unittest.main()
