"""Authored ZIP envelopes around a registered public log fixture; no live GET."""
from hashlib import sha256
import io
import stat
import unittest
from unittest.mock import patch
import zipfile

from tests import test_boat_venue_future_grid_nov7 as nov7


def packed(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in entries:archive.writestr(name,raw)
    return stream.getvalue()


class HistoryLogArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nov7.Nov7WitnessTests.setUpClass();cls.f=nov7.Nov7WitnessTests
        from race_ai import boat_history_log_archive as api
        from race_ai import boat_venue_future_grid as grid
        cls.api=api;cls.grid=grid;cls.name=grid.READBACK_LOG_MEMBER
        cls.path=f'actions/jobs/{cls.f.job["id"]}/logs'
    def extract(self,entries):return self.api.extract_readback_log(packed(entries),job_log_path=self.path)
    def test_exact_selected_raw_member_retains_bom_bytes_and_only_registered_route(self):
        raw=self.extract([('other-job.txt',b'authored unrelated log'),(self.name,self.f.log)])
        self.assertEqual(raw,self.f.log);self.assertEqual(sha256(raw).hexdigest(),self.f.fixture['log_sha256'])
        spec=self.grid.readback_log_archive(self.path)
        self.assertEqual(spec['route'],f'actions/runs/{self.f.actual_run["id"]}/attempts/1/logs')
        with self.assertRaises(ValueError):self.api.extract_readback_log(packed([(self.name,self.f.log)]),job_log_path='actions/jobs/1/logs')
    def test_same_hash_in_wrong_name_duplicate_hash_or_changed_body_cannot_substitute(self):
        for entries in ([('other-name.txt',self.f.log)],[(self.name,self.f.log),('other.txt',self.f.log)],
            [(self.name,self.f.log+b'changed')],[('nested/'+self.name,self.f.log)]):
            with self.subTest(names=[name for name,_ in entries]),self.assertRaises(ValueError):self.extract(entries)
    def test_unsafe_names_symlink_and_directory_payload_reject_without_extraction(self):
        link=zipfile.ZipInfo('link');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        for name in ('../outside','/absolute','a//b','a/./b','C:/outside','back\\slash',link,'directory/'):
            with self.subTest(name=str(name)),self.assertRaises(ValueError):
                self.extract([(self.name,self.f.log),(name,b'payload')])
    def test_member_total_count_and_envelope_bounds_are_enforced(self):
        self.assertEqual((self.api.MAX_MEMBERS,self.api.MAX_MEMBER,self.api.MAX_TOTAL),(512,8*1024*1024,32*1024*1024))
        for entries in ([(self.name,self.f.log)]+[(str(n),b'') for n in range(512)],
            [(self.name,self.f.log),('large',b'x'*(8*1024*1024+1))]):
            with self.assertRaises(ValueError):self.extract(entries)
        with patch.object(self.api,'MAX_TOTAL',len(self.f.log)+2),self.assertRaises(ValueError):
            self.extract([(self.name,self.f.log),('extra',b'xxx')])
        raw=packed([(self.name,self.f.log)])
        for body in (b'not zip',raw+b'trailing',raw[:-1]):
            with self.assertRaises(ValueError):self.api.extract_readback_log(body,job_log_path=self.path)
    def test_duplicate_names_and_corrupt_compressed_bytes_are_not_accepted(self):
        with patch('warnings.warn'):
            raw=packed([(self.name,self.f.log),(self.name,b'other')])
        with self.assertRaises(ValueError):self.api.extract_readback_log(raw,job_log_path=self.path)
        raw=bytearray(packed([(self.name,self.f.log)]));offset=30+len(self.name.encode())+10;raw[offset]^=255
        with self.assertRaises(ValueError):self.api.extract_readback_log(bytes(raw),job_log_path=self.path)


if __name__=='__main__':unittest.main()
