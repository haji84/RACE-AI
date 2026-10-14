"""Prediction routes reject invalid callers and serve bounded, uncached errors."""
from contextlib import redirect_stdout
from io import BytesIO,StringIO
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

from tests.test_live_research_contract import fixture,NOW

ROOT=Path(__file__).resolve().parents[1]
with patch.object(sys,'path',[str(ROOT/'web')]+sys.path):
    spec=importlib.util.spec_from_file_location('publish_prediction_route_test',ROOT/'web/api/publish-prediction.py')
    PUBLISH=importlib.util.module_from_spec(spec);spec.loader.exec_module(PUBLISH)
    READ=importlib.import_module('api.prediction')

COMMIT='a'*40
SECRET='synthetic-private-token-must-not-be-served'


class PredictionApiTests(unittest.TestCase):
    def setUp(self):
        self.feed,self.race=fixture()
        self.request=dict(publication_review='user-confirmation-2026-10-15-official-facts',
                          race_id=self.race['race_id'],request_id='123456-1')
        self.env={'VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':COMMIT,'BLOB_READ_WRITE_TOKEN':SECRET}

    def handler(self,module,*,body=b'{}',headers=None,path='/api/prediction'):
        handler=object.__new__(module.handler)
        handler.headers=headers or {};handler.path=path
        handler.rfile=BytesIO(body);handler.wfile=BytesIO();handler.response_headers=[]
        handler.send_response=lambda status:setattr(handler,'status',status)
        handler.send_header=lambda name,value:handler.response_headers.append((name,value))
        handler.end_headers=lambda:setattr(handler,'headers_ended',True)
        return handler

    def publish_handler(self,body=None,**headers):
        body=json.dumps(self.request).encode() if body is None else body
        default={'Authorization':'Bearer synthetic-oidc','X-Race-AI-Commit':COMMIT,
                 'Content-Type':'application/json','Content-Length':str(len(body))}
        default.update(headers)
        return self.handler(PUBLISH,body=body,headers=default)

    def assert_response(self,handler,status,error):
        self.assertEqual(handler.status,status)
        raw=handler.wfile.getvalue()
        self.assertEqual(json.loads(raw),{'error':error})
        headers=dict(handler.response_headers)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(headers['Content-Type'],'application/json; charset=utf-8')
        self.assertEqual(int(headers['Content-Length']),len(raw))
        self.assertTrue(handler.headers_ended)
        self.assertNotIn(SECRET,raw.decode());self.assertNotIn('synthetic-oidc',raw.decode())
        self.assertNotIn('private.invalid',raw.decode())

    def test_production_publisher_is_absent_before_auth_body_or_blob(self):
        handler=self.publish_handler()
        with patch.dict(os.environ,{**self.env,'VERCEL_ENV':'production'},clear=True), \
             patch.object(PUBLISH,'verify_github_oidc') as verify,patch.object(PUBLISH,'load_feed') as feed, \
             patch.object(PUBLISH,'create_blob_client') as client:
            handler.do_POST()
        self.assert_response(handler,404,'NOT_FOUND')
        verify.assert_not_called();feed.assert_not_called();client.assert_not_called()
        self.assertEqual(handler.rfile.tell(),0)

    def test_missing_or_rejected_oidc_never_opens_client_or_loads_day(self):
        for authorization in ('','Basic synthetic-oidc','Bearer rejected-oidc'):
            with self.subTest(authorization=authorization):
                handler=self.publish_handler(Authorization=authorization)
                with patch.dict(os.environ,self.env,clear=True), \
                     patch.object(PUBLISH,'verify_github_oidc',side_effect=ValueError(SECRET+' https://private.invalid')) as verify, \
                     patch.object(PUBLISH,'load_feed') as feed,patch.object(PUBLISH,'create_blob_client') as client:
                    handler.do_POST()
                self.assert_response(handler,404,'NOT_FOUND')
                feed.assert_not_called();client.assert_not_called();self.assertEqual(handler.rfile.tell(),0)
                self.assertEqual(verify.call_count,1 if authorization.startswith('Bearer ') else 0)

    def test_wrong_commit_is_conflict_before_body_day_and_client(self):
        handler=self.publish_handler(**{'X-Race-AI-Commit':'b'*40})
        with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
             patch.object(PUBLISH,'load_feed') as feed,patch.object(PUBLISH,'create_blob_client') as client:
            handler.do_POST()
        self.assert_response(handler,409,'DEPLOYMENT_NOT_CURRENT')
        feed.assert_not_called();client.assert_not_called();self.assertEqual(handler.rfile.tell(),0)

    def test_unbounded_or_wrong_mime_body_is_rejected_without_reading(self):
        for overrides in ({'Content-Length':'8193'},{'Content-Length':'0'},{'Content-Length':'-1'},
                          {'Content-Type':'text/plain'}):
            with self.subTest(overrides=overrides):
                handler=self.publish_handler(**overrides)
                with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
                     patch.object(PUBLISH,'load_feed') as feed,patch.object(PUBLISH,'create_blob_client') as client:
                    handler.do_POST()
                self.assert_response(handler,400,'BODY_INVALID')
                feed.assert_not_called();client.assert_not_called();self.assertEqual(handler.rfile.tell(),0)

    def test_malformed_duplicate_nonfinite_or_truncated_body_has_safe_422(self):
        for body,length in ((b'{',1),(b'{"x":1,"x":2}',13),(b'{"x":NaN}',9),
                            (b'\xff',1),(b'{"x":"\\ud800"}',14),(b'{}',3)):
            with self.subTest(body=body):
                handler=self.publish_handler(body,**{'Content-Length':str(length)})
                with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
                     patch.object(PUBLISH,'load_feed') as feed,patch.object(PUBLISH,'create_blob_client') as client:
                    handler.do_POST()
                self.assert_response(handler,422,'RESEARCH_PREDICTION_REJECTED')
                feed.assert_not_called();client.assert_not_called()

    def test_unknown_caller_fields_are_422_and_cannot_write_predictions(self):
        for extra in ({'generated_at':NOW.isoformat()},{'probabilities':[1]}, {'cloud_saved_at':NOW.isoformat()}):
            with self.subTest(extra=extra):
                handler=self.publish_handler(json.dumps({**self.request,**extra}).encode())
                client=Mock()
                with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
                     patch.object(PUBLISH,'datetime') as clock,patch.object(PUBLISH,'load_feed',return_value=(200,self.feed)), \
                     patch.object(PUBLISH,'create_blob_client',return_value=client):
                    clock.now.return_value=NOW
                    handler.do_POST()
                self.assert_response(handler,422,'RESEARCH_PREDICTION_REJECTED')
                client.get.assert_not_called();client.put.assert_not_called();client.close.assert_called_once()

    def test_nonobject_json_body_is_422_before_creating_client(self):
        for body in (b'[]',b'null',b'42',b'"caller-secret"'):
            handler=self.publish_handler(body)
            with self.subTest(body=body),patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
                 patch.object(PUBLISH,'load_feed',return_value=(200,self.feed)),patch.object(PUBLISH,'create_blob_client') as client:
                handler.do_POST()
            self.assert_response(handler,422,'RESEARCH_PREDICTION_REJECTED');client.assert_not_called()

    def test_publisher_store_failure_hides_exception_body_and_closes_client(self):
        handler=self.publish_handler();client=Mock();logs=StringIO()
        with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
             patch.object(PUBLISH,'datetime') as clock,patch.object(PUBLISH,'load_feed',return_value=(200,self.feed)), \
             patch.object(PUBLISH,'create_blob_client',return_value=client), \
             patch.object(PUBLISH,'publish_prediction',side_effect=OSError(SECRET+' https://private.invalid')),redirect_stdout(logs):
            clock.now.return_value=NOW;handler.do_POST()
        self.assert_response(handler,503,'PREDICTION_PUBLICATION_FAILED')
        client.close.assert_called_once();self.assertNotIn(SECRET,logs.getvalue());self.assertNotIn('private.invalid',logs.getvalue())

    def test_post_day_unavailable_is_503_without_client(self):
        handler=self.publish_handler()
        with patch.dict(os.environ,self.env,clear=True),patch.object(PUBLISH,'verify_github_oidc'), \
             patch.object(PUBLISH,'load_feed',return_value=(503,{'error':SECRET})), \
             patch.object(PUBLISH,'create_blob_client') as client:
            handler.do_POST()
        self.assert_response(handler,503,'DAY_PROGRAM_UNAVAILABLE');client.assert_not_called()

    def test_publisher_get_has_method_error_and_no_store(self):
        handler=self.handler(PUBLISH)
        with patch.object(PUBLISH,'create_blob_client') as client: handler.do_GET()
        self.assert_response(handler,405,'POST_REQUIRED');client.assert_not_called()

    def test_get_duplicate_extra_or_malformed_query_is_400_before_loading(self):
        race=self.race['race_id']
        paths=['/api/prediction','/api/prediction?race_id',f'/api/prediction?race_id={race}&race_id={race}',
               f'/api/prediction?race_id={race}&extra=secret',
               f'/api/prediction?race_id={race}&request_id=123-1&request_id=124-1']
        for path in paths:
            with self.subTest(path=path):
                handler=self.handler(READ,path=path)
                with patch.object(READ,'load_prediction') as load: handler.do_GET()
                self.assert_response(handler,400,'PREDICTION_QUERY_INVALID');load.assert_not_called()
                self.assertEqual(dict(handler.response_headers)['X-Robots-Tag'],'noindex')

    def test_absent_prediction_get_is_404_and_closes_client(self):
        handler=self.handler(READ,path='/api/prediction?race_id='+self.race['race_id'])
        client=Mock()
        with patch.dict(os.environ,self.env,clear=True),patch.object(READ,'utc_now',return_value=NOW), \
             patch.object(READ,'load_feed',return_value=(200,self.feed)), \
             patch.object(READ,'create_blob_client',return_value=client),patch.object(READ,'read_prediction',return_value=None) as read:
            handler.do_GET()
        self.assert_response(handler,404,'PREDICTION_NOT_SAVED')
        read.assert_called_once_with(self.race,client=client,now=NOW,request_id=None)
        client.close.assert_called_once()

    def test_get_day_unavailable_is_503_without_creating_client(self):
        handler=self.handler(READ,path='/api/prediction?race_id='+self.race['race_id'])
        with patch.object(READ,'utc_now',return_value=NOW), \
             patch.object(READ,'load_feed',return_value=(503,{'error':SECRET})), \
             patch.object(READ,'create_blob_client') as client:
            handler.do_GET()
        self.assert_response(handler,503,'DAY_PROGRAM_UNAVAILABLE');client.assert_not_called()

    def test_get_private_failures_are_sanitized_and_client_is_closed(self):
        for failure,status,error in ((ValueError(SECRET),422,'PREDICTION_DATA_REJECTED'),
                                     (OSError(SECRET+' https://private.invalid'),503,'PREDICTION_STORE_UNAVAILABLE')):
            handler=self.handler(READ,path='/api/prediction?race_id='+self.race['race_id']+'&request_id=123-1')
            client=Mock()
            with self.subTest(failure=type(failure).__name__),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(READ,'utc_now',return_value=NOW),patch.object(READ,'load_feed',return_value=(200,self.feed)), \
                 patch.object(READ,'create_blob_client',return_value=client),patch.object(READ,'read_prediction',side_effect=failure) as read:
                handler.do_GET()
            self.assert_response(handler,status,error)
            read.assert_called_once_with(self.race,client=client,now=NOW,request_id='123-1')
            client.close.assert_called_once()


if __name__=='__main__':unittest.main()
