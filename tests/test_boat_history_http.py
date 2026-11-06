"""Fictional HTTP responses: source allowlist, cadence, waits and redirects."""
import unittest
from unittest.mock import patch
import httpx

from race_ai.source_retry_policy import SourceWait
from scripts import boat_venue_history as cli


class HistoryHTTPTests(unittest.TestCase):
    def test_official_program_archive_uses_same_guarded_transport(self):
        client=self.client(lambda request:httpx.Response(200,content=b'official-program'))
        with patch.object(cli,'_SESSION',client),patch.object(cli,'_HTTP_WAIT',None):
            self.assertEqual(cli._http('https://www1.mbrace.or.jp/od2/B/202611/b261105.lzh')[0],b'official-program')

    def client(self,handler):
        client=httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False)
        self.addCleanup(client.close)
        return client

    def test_unapproved_url_never_reaches_transport(self):
        calls=[]
        with patch.object(cli,'_SESSION',self.client(lambda request:calls.append(request))):
            with self.assertRaises(ValueError):cli._http('https://example.org/data')
        self.assertEqual(calls,[])

    def test_redirect_and_rate_limit_do_not_retry_or_follow(self):
        for code,headers in ((302,{'Location':'https://example.org/elsewhere'}),(429,{'Retry-After':'3600'})):
            calls=[]
            def handler(request):
                calls.append(str(request.url));return httpx.Response(code,headers=headers,content=b'hold')
            with self.subTest(code=code),patch.object(cli,'_SESSION',self.client(handler)),patch.object(cli,'_HTTP_WAIT',None):
                with self.assertRaises(SourceWait):cli._http(cli.MENU)
                self.assertEqual(calls,[cli.MENU])

    def test_shared_wait_prevents_a_second_request(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url));return httpx.Response(429,headers={'Retry-After':'3600'},content=b'hold')
        with patch.object(cli,'_SESSION',self.client(handler)),patch.object(cli,'_HTTP_WAIT',None):
            with self.assertRaises(SourceWait):cli._http(cli.MENU)
            with self.assertRaises(SourceWait) as stopped:cli._http(cli.MENU)
            self.assertFalse(stopped.exception.upstream_attempted)
        self.assertEqual(len(calls),1)

    def test_success_stream_is_bounded_and_empty_body_is_rejected(self):
        for body in (b'index',b'',b'x'*200001):
            client=self.client(lambda request:httpx.Response(200,content=body))
            with self.subTest(size=len(body)),patch.object(cli,'_SESSION',client),patch.object(cli,'_HTTP_WAIT',None):
                if body==b'index':self.assertEqual(cli._http(cli.MENU)[0],body)
                else:
                    with self.assertRaises(ValueError):cli._http(cli.MENU)
