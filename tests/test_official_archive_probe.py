import unittest
from datetime import date
from race_ai.official_archive_probe import official_url,inspect_lzh,MAX_ARCHIVE_BYTES
from race_ai.core import SourceError


class OfficialKArchiveTests(unittest.TestCase):
    def test_documented_download_path(self):
        self.assertEqual(official_url(date(2026,10,13),"K"),
          "https://www1.mbrace.or.jp/od2/K/202610/k261013.lzh")
        self.assertEqual(official_url(date(2026,10,13),"B"),
          "https://www1.mbrace.or.jp/od2/B/202610/b261013.lzh")

    def test_lzh_header_probe_marks_not_parsed(self):
        fake=bytearray(70)
        fake[0]=30
        fake[2:7]=b'-lh5-'
        fake[20]=0
        result=inspect_lzh(bytes(fake))
        self.assertEqual(result["method"],"-lh5-")
        self.assertFalse(result["official_races_reconciled"])
        self.assertFalse(result["contents_parsed"])

    def test_web_error_html_not_mistaken_for_archive(self):
        with self.assertRaises(SourceError):
            inspect_lzh(b"<html>maintenance</html>"*10)

    def test_invalid_header_level_rejected(self):
        fake=bytearray(40)
        fake[2:7]=b'-lh5-'
        fake[20]=9
        with self.assertRaises(SourceError):
            inspect_lzh(bytes(fake))

    def test_unexpected_kind_rejected(self):
        with self.assertRaises(SourceError):
            official_url(date(2026,10,13),'X')

    def test_absurd_size_rejected(self):
        with self.assertRaises(SourceError):
            inspect_lzh(b'x'*(MAX_ARCHIVE_BYTES+1))


if __name__=='__main__':
    unittest.main()
