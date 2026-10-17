from datetime import datetime,timezone
from http.client import BadStatusLine,IncompleteRead
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from race_ai.official_update_worker import collect_race_update
from race_ai.official_race_updates import endpoint
from race_ai.tokuyama_day_worker import FetchResponse
from tests.test_official_race_updates import DAY,page,preview

NOW=datetime(2026,10,14,22,tzinfo=timezone.utc)


def review():
    root=json.loads((Path(__file__).resolve().parents[1]/'config/operator-official-facts.json').read_text(encoding='utf-8'))
    root['source_scopes'].append('https://www.boatrace.jp/owpc/pc/race/beforeinfo')
    return root


class OfficialUpdateWorkerTests(unittest.TestCase):
    def test_default_dryrun_never_fetches(self):
        transport=Mock()
        result=collect_race_update(DAY,'18',1,'beforeinfo',review=review(),now=NOW,transport=transport)
        self.assertEqual(result['status'],'DRY_RUN');transport.assert_not_called()

    def test_sibling_source_or_missing_rights_does_not_authorize_get(self):
        transport=Mock();r=review();r['source_scopes']=['https://www.boatrace.jp/owpc/pc/race/racelist']
        result=collect_race_update(DAY,'18',1,'beforeinfo',review=r,execute=True,now=NOW,transport=transport)
        self.assertEqual(result['status'],'SOURCE_RIGHTS_BLOCKED');transport.assert_not_called()

    def test_one_bounded_response_produces_source_hash_and_capture(self):
        url=endpoint(DAY,'18',1,'beforeinfo')
        transport=Mock(return_value=FetchResponse(page('beforeinfo',preview()),url,200,'text/html;charset=UTF-8'))
        result=collect_race_update(DAY,'18',1,'beforeinfo',review=review(),execute=True,now=NOW,transport=transport)
        self.assertEqual(result['status'],'AVAILABLE')
        self.assertEqual(result['captured_at'],NOW.isoformat())
        transport.assert_called_once_with(url,timeout=10,max_bytes=1000000)

    def test_failure_and_no_data_remain_distinct_from_zero_result(self):
        def unavailable(*args,**kwargs): raise TimeoutError('secret-provider-error')
        result=collect_race_update(DAY,'18',1,'beforeinfo',review=review(),execute=True,now=NOW,transport=unavailable)
        self.assertEqual(result['status'],'SOURCE_UNAVAILABLE')
        self.assertNotIn('secret-provider',str(result))
        url=endpoint(DAY,'18',1,'beforeinfo')
        result=collect_race_update(DAY,'18',1,'beforeinfo',review=review(),execute=True,now=NOW,
            transport=lambda *a,**kw:FetchResponse('<p>データがありません。</p>'.encode(),url,200,'text/html'))
        self.assertEqual(result['status'],'PENDING');self.assertIsNone(result['data'])

    def test_http_protocol_failures_are_sanitized_source_unavailable(self):
        for failure in (BadStatusLine('secret upstream body'),IncompleteRead(b'secret partial response',500)):
            transport=Mock(side_effect=failure)
            with self.subTest(failure=type(failure).__name__):
                result=collect_race_update(DAY,'18',1,'beforeinfo',review=review(),execute=True,now=NOW,transport=transport)
                self.assertEqual(result['status'],'SOURCE_UNAVAILABLE')
                self.assertNotIn('secret',str(result));self.assertNotIn('partial',str(result))
                transport.assert_called_once()
