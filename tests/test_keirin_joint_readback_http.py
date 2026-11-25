from io import BytesIO
import unittest
from urllib.error import HTTPError, URLError

from scripts import keirin_joint_readback_http as readback


URL = 'https://raw.githubusercontent.com/haji84/RACE-AI/123/results/2026-11-25.json'


class Response(BytesIO):
    status = 200

    def __init__(self, body=b'{}', url=URL):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


class JointReadbackHttpTests(unittest.TestCase):
    def read(self, responses, *, url=URL, limit=10):
        self.requests, self.delays = [], []
        remaining = iter(responses)

        def open_request(request, *, timeout):
            self.requests.append((request.full_url, timeout))
            result = next(remaining)
            if isinstance(result, Exception):
                raise result
            return result

        return readback.get(url, limit, open_request=open_request, pause=self.delays.append)

    def test_transient_failure_retries_only_the_same_request(self):
        for error in (HTTPError(URL, 502, 'private detail', {}, None), URLError(TimeoutError())):
            with self.subTest(error=type(error)):
                self.assertEqual(self.read([error, Response()]), b'{}')
                self.assertEqual([request[0] for request in self.requests], [URL, URL])
                self.assertEqual(len(self.delays), 1)

    def test_repeated_transient_failure_stops_after_one_retry(self):
        with self.assertRaises(readback.ReadbackError) as caught:
            self.read([HTTPError(URL, 503, 'first', {}, None), HTTPError(URL, 504, 'second', {}, None)])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(readback.diagnostic('result_data', caught.exception),
                         {'stage': 'result_data', 'reason': 'HTTP_STATUS', 'http_status': 504, 'attempts': 2})

    def test_denials_missing_redirect_and_retry_after_are_preserved(self):
        for code, headers in [(401, {}), (403, {}), (404, {}), (429, {}), (302, {}), (503, {'Retry-After': '60'})]:
            with self.subTest(code=code), self.assertRaises(readback.ReadbackError) as caught:
                self.read([HTTPError(URL, code, 'private detail', headers, None)])
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.delays, [])
            self.assertEqual(readback.diagnostic('result_roster', caught.exception)['http_status'], code)

    def test_permanent_transport_failure_and_invalid_body_never_retry(self):
        for result in (URLError('private DNS detail'), Response(b'x' * 11), Response(b''),
                       Response(url=URL + '?redirect')):
            with self.subTest(result=type(result)), self.assertRaises(readback.ReadbackError):
                self.read([result])
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.delays, [])

    def test_other_hosts_and_unsafe_urls_are_not_requested(self):
        for url in ('https://other.example/test', 'http://api.github.com/test', 'https://user@api.github.com/test'):
            with self.subTest(url=url), self.assertRaises(readback.ReadbackError):
                self.read([], url=url)
            self.assertEqual(self.requests, [])

    def test_generic_failure_has_fixed_diagnostics(self):
        self.assertEqual(readback.diagnostic('original_cipher', AssertionError('private detail')),
                         {'stage': 'original_cipher', 'reason': 'VALIDATION_FAILED'})
