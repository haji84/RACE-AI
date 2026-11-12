"""Actual httpx response policy, with a synthetic transport and no live requests."""
from datetime import datetime,timezone
import unittest,httpx
from race_ai.source_retry_policy import SourceWait
try:
    from race_ai.racer_intraday_transport import OfficialClient
except ImportError:OfficialClient=None

class TransportTests(unittest.TestCase):
    def client(self,handler):
        self.assertIsNotNone(OfficialClient,'live collection must obey fixed endpoint and HTTP wait policy')
        http=httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False);self.addCleanup(http.close);return OfficialClient(client=http)
    def test_outside_endpoints_are_rejected_before_a_request(self):
        seen=[];client=self.client(lambda request:seen.append(request) or httpx.Response(200,content=b'{}'))
        for url in ['https://outside.invalid/data','https://www.boatrace.jp/owsp/sp/spdata?type=odds3t&hd=20261107&jcd=01&rno=1','https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20261107&jcd=01&rno=1&token=private']:
            with self.assertRaises(ValueError):client(url)
        self.assertEqual(seen,[])
    def test_backlog_rate_spacing_is_configured_without_concurrent_fetch(self):
        c=self.client(lambda request:httpx.Response(200,content=b'{}'))
        self.assertEqual(c.interval_seconds,1)
        guarded=OfficialClient(client=c.client,interval_seconds=2)
        self.assertEqual(guarded.interval_seconds,2)
        with self.assertRaisesRegex(ValueError,'INTRADAY_SOURCE_INTERVAL_INVALID'):
            OfficialClient(client=c.client,interval_seconds=0)
        with self.assertRaisesRegex(ValueError,'INTRADAY_SOURCE_INTERVAL_INVALID'):
            OfficialClient(client=c.client,interval_seconds=4)

    def test_retry_after_is_returned_without_inline_retry_or_redirect(self):
        seen=[];client=self.client(lambda request:seen.append(request) or httpx.Response(429,headers={'Retry-After':'3600'}))
        with self.assertRaises(SourceWait) as err:client('https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20261107&jcd=01&rno=1')
        self.assertEqual(len(seen),1);self.assertIsNotNone(err.exception.retry_at)
