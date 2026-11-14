"""Pure wait-policy contracts; no network, clocks and responses are fictional."""
from datetime import datetime, timedelta
import importlib
import unittest

try:
    policy=importlib.import_module('race_ai.source_retry_policy')
except ModuleNotFoundError:
    policy=None
AT=datetime.fromisoformat('2030-04-01T23:59:00+09:00')

class SourceRetryPolicyTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(policy,'shared source waiting policy is missing')
    def test_429_seconds_and_http_date_survive_midnight_without_shortening_server_wait(self):
        for value in ('3600','Mon, 01 Apr 2030 15:59:00 GMT'):
            wait=policy.plan_http_wait(429,{'Retry-After':value},AT)
            self.assertEqual(wait['state'],'RATE_LIMIT_WAIT')
            self.assertEqual(datetime.fromisoformat(wait['retry_at']),AT+timedelta(hours=1))
            self.assertTrue(policy.wait_active(wait,AT+timedelta(minutes=30)))
            self.assertFalse(policy.wait_active(wait,AT+timedelta(hours=1)))
    def test_retry_backoff_is_exponential_with_minimum_180_seconds(self):
        for status in (None,500,503):
            first=policy.plan_http_wait(status,{},AT)
            second=policy.plan_http_wait(status,{},AT,attempt=2)
            self.assertGreaterEqual(datetime.fromisoformat(first['retry_at'])-AT,timedelta(seconds=180))
            self.assertGreater(datetime.fromisoformat(second['retry_at']),datetime.fromisoformat(first['retry_at']))
        wait=policy.plan_http_wait(503,{'Retry-After':'7200'},AT,attempt=10)
        self.assertEqual(datetime.fromisoformat(wait['retry_at']),AT+timedelta(hours=2))
    def test_auth_denial_never_gets_an_automatic_retry(self):
        for status in (401,403):
            wait=policy.plan_http_wait(status,{'Retry-After':'1'},AT)
            self.assertEqual(wait['state'],'AUTHORIZATION_WAIT')
            self.assertIsNone(wait['retry_at'])
            self.assertTrue(policy.wait_active(wait,AT+timedelta(days=100)))
            wait['retry_at']=(AT-timedelta(days=1)).isoformat()
            self.assertTrue(policy.wait_active(wait,AT+timedelta(days=100)),
                            'a malformed review/auth timestamp must not grant automatic resumption')
    def test_not_yet_published_is_distinct_from_invalid_identity_or_unknown_4xx(self):
        for status in (200,404):
            wait=policy.plan_http_wait(status,{},AT,not_yet_published=True)
            self.assertEqual(wait['state'],'WAITING_PUBLICATION')
            self.assertEqual(wait['http_status'],status)
            self.assertIsNotNone(wait['retry_at'])
        review=policy.plan_http_wait(404,{},AT)
        self.assertEqual(review['state'],'SOURCE_REVIEW_WAIT')
        self.assertIsNone(review['retry_at'])
    def test_bad_retry_after_uses_backoff_and_unrepresentable_server_wait_stays_blocked(self):
        for value in ('-1','garbage','NaN'):
            wait=policy.plan_http_wait(429,{'retry-after':value},AT)
            self.assertGreaterEqual(datetime.fromisoformat(wait['retry_at'])-AT,timedelta(seconds=180))
        wait=policy.plan_http_wait(429,{'Retry-After':'9'*200},AT)
        self.assertIsNone(wait['retry_at'])
        self.assertTrue(policy.wait_active(wait,AT))
    def test_exception_has_only_safe_control_fields(self):
        error=policy.SourceWait('HTTP_RATE_LIMIT','2030-04-02T01:00:00+09:00',state='RATE_LIMIT_WAIT')
        self.assertIsInstance(error,ValueError)
        self.assertEqual((error.reason,error.retry_at,error.state),('HTTP_RATE_LIMIT','2030-04-02T01:00:00+09:00','RATE_LIMIT_WAIT'))
        self.assertEqual(str(error),'HTTP_RATE_LIMIT')
        with self.assertRaises(ValueError):policy.plan_http_wait(429,{},datetime(2030,4,1))
