"""Research evaluation reads real immutable receipts without source GETs."""
from datetime import timedelta
from io import BytesIO
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

from tests.test_live_research_contract import fixture,NOW

ROOT=Path(__file__).resolve().parents[1]


class EvaluationApiTests(unittest.TestCase):
    def setUp(self):
        with patch.object(sys,'path',[str(ROOT/'web')]+sys.path):self.api=importlib.import_module('api.evaluation')
        self.feed,self.race=fixture();self.client=Mock()

    def handler(self,path):
        handler=object.__new__(self.api.handler);handler.path=path;handler.wfile=BytesIO();handler.response_headers={}
        handler.send_response=lambda status:setattr(handler,'status',status)
        handler.send_header=lambda key,value:handler.response_headers.update({key:value})
        handler.end_headers=lambda:None
        return handler

    def test_query_duplicate_extra_or_client_asof_rejected_before_store(self):
        for query in ('','?race_id','?race_id=x&race_id=y','?race_id=x&as_of=2026-10-15','?race_id=x&request_id=123-1'):
            with self.subTest(query=query),patch.object(self.api,'load_evaluation') as load:
                handler=self.handler('/api/evaluation'+query);handler.do_GET()
            self.assertEqual(handler.status,400);load.assert_not_called()
            self.assertEqual(handler.response_headers['Cache-Control'],'no-store')
            self.assertEqual(handler.response_headers['X-Robots-Tag'],'noindex')
            self.assertEqual(int(handler.response_headers['Content-Length']),len(handler.wfile.getvalue()))

    def test_day_unavailable_never_creates_private_client(self):
        with patch.object(self.api,'utc_now',return_value=NOW),patch.object(self.api,'load_feed',return_value=(503,{})),patch.object(self.api,'create_blob_client') as client:
            self.assertEqual(self.api.load_evaluation(self.race['race_id']),(503,{'error':'DAY_PROGRAM_UNAVAILABLE'}))
        client.assert_not_called()

    def test_live_validated_receipts_are_passed_to_pure_evaluation(self):
        prediction={'fixture':'prediction'};results={'fixture':'results'};report={'status':'EVALUATED'}
        with patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret'}),patch.object(self.api,'utc_now',return_value=NOW),patch.object(self.api,'load_feed',return_value=(200,self.feed)),patch.object(self.api,'create_blob_client',return_value=self.client),patch.object(self.api,'read_prediction',return_value=prediction) as read_prediction,patch.object(self.api,'read_current_race',return_value=results) as read_race,patch.object(self.api,'build_research_evaluation',return_value=report) as evaluate:
            self.assertEqual(self.api.load_evaluation(self.race['race_id']),(200,report))
        read_prediction.assert_called_once_with(self.race,client=self.client,now=NOW)
        read_race.assert_called_once_with(self.race,client=self.client,now=NOW)
        evaluate.assert_called_once_with(prediction,results,self.race,NOW)
        self.client.put.assert_not_called();self.client.close.assert_called_once()

    def test_absent_receipts_are_informative_empty_metrics_not_fake_zero(self):
        report={'status':'PREDICTION_NOT_SAVED','models':[]}
        with patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret'}),patch.object(self.api,'utc_now',return_value=NOW),patch.object(self.api,'load_feed',return_value=(200,self.feed)),patch.object(self.api,'create_blob_client',return_value=self.client),patch.object(self.api,'read_prediction',return_value=None),patch.object(self.api,'read_current_race',return_value=None),patch.object(self.api,'build_research_evaluation',return_value=report) as evaluate:
            self.assertEqual(self.api.load_evaluation(self.race['race_id']),(200,report))
        evaluate.assert_called_once_with(None,None,self.race,NOW)
        self.client.close.assert_called_once()

    def test_corrupt_or_failed_store_is_sanitized_and_closed(self):
        for error,status,code in ((ValueError('secret-body'),422,'EVALUATION_DATA_REJECTED'),(OSError('secret-body'),503,'EVALUATION_STORE_UNAVAILABLE')):
            self.client.reset_mock()
            with self.subTest(error=type(error).__name__),patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret'}),patch.object(self.api,'utc_now',return_value=NOW),patch.object(self.api,'load_feed',return_value=(200,self.feed)),patch.object(self.api,'create_blob_client',return_value=self.client),patch.object(self.api,'read_prediction',side_effect=error):
                self.assertEqual(self.api.load_evaluation(self.race['race_id']),(status,{'error':code}))
            self.client.close.assert_called_once()

    def test_midnight_between_receipts_never_returns_mixed_days(self):
        midnight=NOW.replace(hour=0,minute=0,second=0)+timedelta(days=1)
        with patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret'}),patch.object(self.api,'utc_now',side_effect=[NOW,NOW,NOW,midnight]),patch.object(self.api,'load_feed',return_value=(200,self.feed)),patch.object(self.api,'create_blob_client',return_value=self.client),patch.object(self.api,'read_prediction'),patch.object(self.api,'read_current_race'),patch.object(self.api,'build_research_evaluation') as evaluate:
            self.assertEqual(self.api.load_evaluation(self.race['race_id']),(422,{'error':'EVALUATION_DATA_REJECTED'}))
        evaluate.assert_not_called();self.client.close.assert_called_once()


if __name__=='__main__':unittest.main()
