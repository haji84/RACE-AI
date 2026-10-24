"""Self-authored LHA bytes for Windows fallback and archive boundary tests."""
import struct
import unittest
from unittest.mock import patch

from race_ai.official_lzh_extract import extract_daily_lzh
from race_ai.core import SourceError

try:
    import lzhlib
except ImportError:
    lzhlib = None


def archive(name='B261015.TXT', content=b'authorized synthetic fixture', declared_size=None):
    crc = 0
    for byte in content:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    encoded = name.encode('ascii')
    header = b'-lh0-' + struct.pack('<IIIBB', len(content), len(content) if declared_size is None else declared_size, 0, 32, 0)
    header += bytes([len(encoded)]) + encoded + struct.pack('<H', crc)
    return bytes([len(header), sum(header) & 255]) + header + content + b'\x00'


@unittest.skipIf(lzhlib is None, 'portable LHA runtime not installed')
class PortableLzhTests(unittest.TestCase):
    def test_in_memory_extraction_without_system_library(self):
        with patch('ctypes.util.find_library', return_value=None):
            self.assertEqual(extract_daily_lzh(archive(), 'B261015.TXT'), b'authorized synthetic fixture')

    def test_unexpected_or_traversal_entry_never_extracts(self):
        for name in ['K261015.TXT', '../B261015.TXT', 'folder/B261015.TXT']:
            with self.subTest(name=name), patch('ctypes.util.find_library', return_value=None):
                with self.assertRaises(SourceError):
                    extract_daily_lzh(archive(name), 'B261015.TXT')

    def test_declared_oversize_rejected_before_decompression(self):
        with patch('ctypes.util.find_library', return_value=None):
            with self.assertRaises(SourceError):
                extract_daily_lzh(archive(declared_size=20_000_001), 'B261015.TXT')

    def test_crc_mismatch_rejected(self):
        raw = bytearray(archive())
        raw[-2] ^= 1
        with patch('ctypes.util.find_library', return_value=None):
            with self.assertRaises(SourceError):
                extract_daily_lzh(bytes(raw), 'B261015.TXT')
