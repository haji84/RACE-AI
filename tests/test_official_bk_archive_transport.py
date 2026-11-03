"""Synthetic LHA bytes and fake HTTP; no official server accessed."""
import unittest
from datetime import date,datetime,timezone
from race_ai.official_bk_archive_transport import (
    archive_url,ingest_one,ArchiveTransportError)

DAY=date(2026,10,24)
ARCHIVE=b"\x16\x00-lh5-"+b"x"*200
class FakeResp:
 def __init__(self,raw=ARCHIVE,content_type="application/octet-stream",url=None):
    self.status=200;self.raw=raw;self.url=url or archive_url(DAY,"B")
    self.headers={"Content-Type":content_type,"Content-Length":str(len(raw)),
                  "Date":"Sat, 24 Oct 2026 00:00:00 GMT",
                  "Last-Modified":"Fri, 23 Oct 2026 01:00:00 GMT"}
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def geturl(self):return self.url
 def read(self,n):return self.raw[:n]
class FakeOpener:
 def __init__(self,reply):self.reply=reply;self.calls=0
 def open(self,req,timeout):
    self.calls+=1;self.url=req.full_url
    return self.reply
AT=lambda:datetime(2026,10,25,0,0,0,tzinfo=timezone.utc)
class BkArchiveTests(unittest.TestCase):
 def test_known_official_layout_path_date(self):
    self.assertEqual(archive_url(DAY,"B"),"https://www1.mbrace.or.jp/od2/B/202610/b261024.lzh")
    self.assertEqual(archive_url(DAY,"K"),"https://www1.mbrace.or.jp/od2/K/202610/k261024.lzh")
 def test_no_approval_no_get(self):
    client=FakeOpener(FakeResp())
    with self.assertRaisesRegex(ArchiveTransportError,"not admitted"):
        ingest_one(DAY,"B",allow_source=None,opener=client,clock=AT)
    self.assertEqual(client.calls,0)
 def test_one_approved_b_as_private_quarantine_only(self):
    client=FakeOpener(FakeResp())
    raw,receipt=ingest_one(DAY,"B",allow_source=lambda url,p:p=="pre_race_program_private_analysis",
                           opener=client,clock=AT)
    self.assertEqual(client.calls,1)
    self.assertEqual(raw,ARCHIVE)
    self.assertEqual(receipt["compressed_bytes"],len(ARCHIVE))
    self.assertFalse(receipt["allowed_in_predictive_snapshot"])
    self.assertFalse(receipt["source_publication_time_independently_verified"])
    self.assertIsNone(receipt["etag_sha256_if_present"])
    self.assertTrue(receipt["provider_archive_sha256"])
 def test_k_results_separate_from_prediction(self):
    reply=FakeResp(url=archive_url(DAY,"K"))
    client=FakeOpener(reply)
    data,receipt=ingest_one(DAY,"K",allow_source=lambda url,p:p=="post_race_results_private_audit",
                           opener=client,clock=AT)
    self.assertEqual(receipt["kind"],"K")
    self.assertFalse(receipt["allowed_in_verified_settlement"])
 def test_reject_fake_html_binary_or_changed_url(self):
    for resp in (FakeResp(raw=b"<html>wrong</html>"),
                 FakeResp(content_type="text/html"),
                 FakeResp(url="https://www1.mbrace.or.jp.attacker.invalid/")):
      client=FakeOpener(resp)
      with self.subTest(resp=resp),self.assertRaises(ArchiveTransportError):
        ingest_one(DAY,"B",allow_source=lambda *_:True,opener=client,clock=AT)
      self.assertEqual(client.calls,1)
 def test_no_future_k_autofetch(self):
    client=FakeOpener(FakeResp())
    with self.assertRaisesRegex(ArchiveTransportError,"current-day"):
      ingest_one(date(2026,10,25),"K",allow_source=lambda *_:True,opener=client,clock=AT)
    self.assertEqual(client.calls,0)

if __name__=="__main__":unittest.main()
