"""Source shortlist & Rakuten exclusion. This does NOT authorize auto-fetch."""
import unittest
from race_ai.keirin_non_rakuten_sources import (
    SOURCE_CATALOG, is_rakuten_domain, is_rakuten_url,
    source_id, non_rakuten_source_status,
)


class NonRakutenSourceTests(unittest.TestCase):
    def test_original_vendor_and_all_known_subdomains_are_excluded(self):
        for url in (
            "https://keirin.kdreams.jp/kaisai/",
            "https://kdreams.jp/a",
            "https://www.rakuten.co.jp/a",
            "https://member.rakuten.com/a",
            "https://rakuten-bank.co.jp/a",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_rakuten_url(url))
                self.assertIsNone(source_id(url))
                self.assertEqual(non_rakuten_source_status(url),
                                 "RAKUTEN_SOURCE_EXCLUDED_BY_OWNER")

    def test_independent_provider_hosts_remain_candidates_only(self):
        pairs = [
            ("https://www.keirin.jp/pc/raceschedule", "keirin_official"),
            ("https://www.winticket.jp/keirin/", "winticket"),
            ("https://sp.oddspark.com/keirin/", "oddspark"),
            ("https://www.chariloto.com/articles/6184", "chariloto"),
            ("https://keirin.netkeiba.com/info/kiyaku/", "netkeirin"),
            ("https://www.data.jma.go.jp/risk/obsdl/", "jma"),
        ]
        for url, expect in pairs:
            with self.subTest(url=url):
                self.assertFalse(is_rakuten_url(url))
                self.assertEqual(source_id(url), expect)
                expected_status = (
                    "OWNER_ATTESTED_PERSONAL_USE_PROVIDER_PROOF_UNVERIFIED"
                    if expect in ("keirin_official","winticket") else
                    "NON_RAKUTEN_CANDIDATE_NOT_MACHINE_AUTHORIZED"
                )
                self.assertEqual(non_rakuten_source_status(url),
                                 expected_status)

    def test_no_url_spoof_or_subdomain_confusion(self):
        for url in (
            "https://keirin.kdreams.jp.evil.example/a",
            "https://www.rakuten.co.jp@www.keirin.jp/a",
            "http://www.keirin.jp/a",
            "https://www.keirin.jp.evil.example/a",
            "https://127.0.0.1/a",
        ):
            with self.subTest(url=url):
                self.assertIsNone(source_id(url))

    def test_catalog_never_claims_machine_collection_granted(self):
        self.assertGreaterEqual(len(SOURCE_CATALOG), 5)
        self.assertTrue(all(
            row["automated_machine_collection_status"] in (
                "UNVERIFIED",
                "OWNER_ATTESTED_PERSONAL_USE_PROVIDER_PROOF_UNVERIFIED"
            ) for row in SOURCE_CATALOG))
        self.assertTrue(all(not is_rakuten_domain(host)
                            for row in SOURCE_CATALOG
                            for host in row["hosts"]))


if __name__ == "__main__":
    unittest.main()
