"""Fail closed when a retained study download is altered or redirected."""
from hashlib import sha256
from io import BytesIO
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1 import retained_readback as readback


class Response(BytesIO):
    def __init__(self, content, url):
        super().__init__(content)
        self.url = url

    def geturl(self):
        return self.url


class RetainedReadbackTests(unittest.TestCase):
    def test_verified_bytes_are_returned_unchanged(self):
        raw = b'ciphertext sample\n'
        url = readback.ROOT + '/manifest.json'
        with patch.object(readback, 'urlopen', return_value=Response(raw, url)):
            self.assertEqual(readback.fetch_exact('manifest.json', len(raw), sha256(raw).hexdigest()), raw)

    def test_mismatch_truncation_and_excess_stop(self):
        raw = b'ciphertext sample\n'
        for changed in (raw[:-1], raw+b'x', b'x'+raw[1:]):
            with self.subTest(changed=changed), patch.object(readback, 'urlopen',
                    return_value=Response(changed, readback.ROOT+'/manifest.json')):
                with self.assertRaisesRegex(ValueError, 'RETAINED_FILE_INTEGRITY'):
                    readback.fetch_exact('manifest.json', len(raw), sha256(raw).hexdigest())

    def test_redirect_is_not_trusted_even_for_matching_bytes(self):
        raw = b'ciphertext sample\n'
        with patch.object(readback, 'urlopen', return_value=Response(raw, 'https://example.org/data')):
            with self.assertRaisesRegex(ValueError, 'RETAINED_URL_CHANGED'):
                readback.fetch_exact('manifest.json', len(raw), sha256(raw).hexdigest())

    def test_only_original_fixed_members_can_be_requested(self):
        with patch.object(readback, 'urlopen') as opened:
            with self.assertRaisesRegex(ValueError, 'RETAINED_MEMBER_INVALID'):
                readback.fetch_exact('../unrelated.json', 1, '0'*64)
            opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
