from datetime import datetime
from io import BytesIO
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
with patch.object(sys,'path',[str(ROOT/'web')]+sys.path):
    spec=importlib.util.spec_from_file_location('publish_race_route',ROOT/'web/api/publish-race.py')
    PUBLISH=importlib.util.module_from_spec(spec);spec.loader.exec_module(PUBLISH)
    READ=importlib.import_module('api.race')


class RaceRouteTests(unittest.TestCase):
    def handler(self,headers=None,body=b'{}'):
        handler=object.__new__(PUBLISH.handler);handler.headers=headers or {}
        handler.rfile=BytesIO(body);handler.respond=lambda status,data:setattr(handler,'result',(status,data))
        return handler

    def test_production_has_no_publisher_even_with_authorization(self):
        handler=self.handler({'Authorization':'Bearer synthetic-token'})
        with patch.dict('os.environ',{'VERCEL_ENV':'production'}),patch.object(PUBLISH,'verify_github_oidc') as verify,patch.object(PUBLISH,'load_feed') as feed:
            handler.do_POST()
        self.assertEqual(handler.result[0],404);verify.assert_not_called();feed.assert_not_called()

    def test_missing_and_invalid_oidc_never_load_program_or_blob(self):
        for headers in [{},{'Authorization':'Bearer invalid-token'}]:
            handler=self.handler(headers)
            with patch.dict('os.environ',{'VERCEL_ENV':'preview'}),patch.object(PUBLISH,'verify_github_oidc',side_effect=ValueError('invalid')),patch.object(PUBLISH,'load_feed') as feed:
                handler.do_POST()
            self.assertEqual(handler.result[0],404);feed.assert_not_called()

    def test_wrong_application_commit_fails_before_reading_body(self):
        handler=self.handler({'Authorization':'Bearer synthetic','X-Race-AI-Commit':'b'*40})
        with patch.dict('os.environ',{'VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40}),patch.object(PUBLISH,'verify_github_oidc'),patch.object(PUBLISH,'load_feed') as feed:
            handler.do_POST()
        self.assertEqual(handler.result[0],409);self.assertEqual(handler.rfile.tell(),0);feed.assert_not_called()

    def test_unbounded_or_duplicate_json_body_never_loads_program(self):
        for size,body in [('256001',b'{}'),('13',b'{"x":1,"x":2}')]:
            handler=self.handler({'Authorization':'Bearer synthetic','X-Race-AI-Commit':'a'*40,'Content-Type':'application/json','Content-Length':size},body)
            with patch.dict('os.environ',{'VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40}),patch.object(PUBLISH,'verify_github_oidc'),patch.object(PUBLISH,'load_feed') as feed:
                handler.do_POST()
            self.assertIn(handler.result[0],(400,422));feed.assert_not_called()

    def test_reader_requires_an_available_approved_day(self):
        with patch.object(READ,'load_feed',return_value=(503,{'error':'test'})),patch.object(READ,'create_blob_client') as client:
            self.assertEqual(READ.load_race('20261015-18-01'),(503,{'error':'DAY_PROGRAM_UNAVAILABLE'}))
        client.assert_not_called()

    def test_arbitrary_path_or_previous_day_is_never_given_to_blob(self):
        now=datetime.fromisoformat('2026-10-15T07:00:00+09:00')
        for identity in ['../secrets','20261014-18-01','20261015-25-01','20261015-18-13']:
            with patch.object(READ,'utc_now',return_value=now),patch.object(READ,'load_feed',return_value=(200,{'venues':[]})),patch.object(READ,'create_blob_client') as client:
                self.assertEqual(READ.load_race(identity)[0],422)
            client.assert_not_called()


if __name__=='__main__':unittest.main()
